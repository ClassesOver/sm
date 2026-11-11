/** Local package adapter; full snapshots use the fixed-source writer, old append API unchanged. */
import { applyCfRules, buildDxfXml, type CfWireRule } from './conditional-formatting-source'
import { readConditionalFormattingSnapshot } from './conditional-formatting-read'
import { StylesheetEditor } from './styles-write'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { createBufferEntrySource, assemblePackage, assertOnlyTouchedEntriesChanged } from './zip'
import { isValidRuleSqref } from './cf-schemas'
import { formatAddress } from './cell-address'
import { readXmlAttribute, extractElements } from './xml'
import { parseThemePalette } from './style-read'
export interface SheetConditionalFormattingSnapshot { sheetName: string; rules: readonly CfWireRule[] }
export async function replaceConditionalFormattingSnapshots(bytes: Uint8Array, sheets: readonly SheetConditionalFormattingSnapshot[]): Promise<Uint8Array> {
 if (!sheets.length) return bytes
 const source=await createBufferEntrySource(bytes),book=await source.readText('xl/workbook.xml')
 const hasStyles=await source.has('xl/styles.xml')
 // Reuse the existing engine's minimal stylesheet recipe only if a new dxf needs it.
 const stylesXml=hasStyles?await source.readText('xl/styles.xml'):await(await createBufferEntrySource(await(await import('./blank')).createBlankWorkbook())).readText('xl/styles.xml')
 const styles=new StylesheetEditor(stylesXml),replaced=new Map<string,string>(),added=new Map<string,string>(),seen=new Set<string>()
 const themePalette=await source.has('xl/theme/theme1.xml')?parseThemePalette(await source.readText('xl/theme/theme1.xml')):undefined
 for(const snapshot of sheets){
  if(seen.has(snapshot.sheetName))throw Error('Duplicate conditional-formatting sheet snapshot')
  seen.add(snapshot.sheetName)
  const sheet=parseSheetElements(book).find(item=>item.name===snapshot.sheetName)
  if(!sheet?.relationshipId)throw Error('Conditional-formatting target sheet does not exist')
  const path=await resolveWorksheetPath(source,sheet.relationshipId),xml=await source.readText(path)
  const original=readConditionalFormattingSnapshot(xml,stylesXml,themePalette)
  if(original.issues.length)throw Error('Conditional-formatting source snapshot is incomplete: '+original.issues.join('; '))
  for(const linked of original.linkedRules){
   const matches=snapshot.rules.filter(rule=>wireIdentity(rule)===wireIdentity(linked))
   if(matches.length!==1)throw Error('Conditional-formatting linked source rule must remain unchanged')
  }
  for(const wire of snapshot.rules){
   if(!wire.ranges.length||wire.ranges.some(area=>Object.values(area).some(value=>!Number.isSafeInteger(value)||value<0)||!isValidRuleSqref(`${formatAddress(area.startRow,area.startColumn)}:${formatAddress(area.endRow,area.endColumn)}`)))throw Error('Conditional-formatting snapshot range invalid')
  }
  if(wireIdentityArray(original.rules)===wireIdentityArray(snapshot.rules))continue
  const entries=extractElements(xml,'cfRule').sort((a,b)=>Number(readXmlAttribute(a,'priority'))-Number(readXmlAttribute(b,'priority')))
  const sourceDxfs=original.rules.flatMap((wire,index)=>{const id=readXmlAttribute(entries[index]??'','dxfId');return id===undefined?[]:[{wire,id:Number(id),style:buildDxfXml(wire.rule.style)}]})
  const requested=snapshot.rules.filter(wire=>wire.rule.type==='highlightCell')
  let highlight=0
  let next=applyCfRules(xml,snapshot.rules,{internDxf(dxf){
   const wire=requested[highlight++]!,exact=sourceDxfs.filter(item=>wireIdentity(item.wire)===wireIdentity(wire))
   if(exact.length===1)return exact[0]!.id
   if(original.rules.some((item,index)=>readXmlAttribute(entries[index]??'','type')==='cellIs'&&readXmlAttribute(entries[index]??'','dxfId')===undefined&&conditionIdentity(item)===conditionIdentity(wire)&&buildDxfXml(item.rule.style)===dxf))return 0
   const sameStyle=sourceDxfs.filter(item=>item.style===dxf),ids=new Set(sameStyle.map(item=>item.id))
   return ids.size===1?sameStyle[0]!.id:styles.internDxf(dxf)
  }})
  // The renderer's cellIs projection is deliberately a formula for Excel
  // blank/text/reference behavior. Recover condition XML only from this ZIP,
  // never from a client-provided raw identity. Style/stop edits keep cellIs.
  const usedConditions=new Set<number>()
  const candidates=new Map<string,CfWireRule[]>()
  for(const wire of snapshot.rules){
   if(original.linkedRules.some(item=>wireIdentity(item)===wireIdentity(wire)))continue
   const isolated=applyCfRules('<worksheet><sheetData/></worksheet>',[wire],{internDxf:()=>0})
   const block=extractElements(isolated,'conditionalFormatting')[0]!
   const key=serializedConditionKey(block)
   candidates.set(key,[...(candidates.get(key)??[]),wire])
  }
  next=next.replace(/<conditionalFormatting\b[^>]*>[\s\S]*?<\/conditionalFormatting>/g,block=>{
   if(/<extLst\b/.test(block))return block
   const requestedWire=candidates.get(serializedConditionKey(block))?.shift()
   if(!requestedWire)return block
   const matching=original.rules.map((wire,index)=>({wire,index})).filter(({wire,index})=>!usedConditions.has(index)&&readXmlAttribute(entries[index]??'','type')==='cellIs'&&conditionIdentity(wire)===conditionIdentity(requestedWire))
   const index=(matching.find(({wire})=>wireIdentity(wire)===wireIdentity(requestedWire))??matching.find(({wire})=>buildDxfXml(wire.rule.style)===buildDxfXml(requestedWire.rule.style))??matching[0])?.index??-1
   if(index<0)return block
   usedConditions.add(index)
   const originalWire=original.rules[index]!,raw=entries[index]!,serialized=extractElements(block,'cfRule')[0]!
   let restored=raw.replace(/\bpriority=(?:"[^"]*"|'[^']*')/,`priority="${readXmlAttribute(serialized,'priority')}"`)
   if(wireIdentity(originalWire)===wireIdentity(requestedWire))return block.replace(serialized,()=>restored)
   for(const attribute of ['dxfId','stopIfTrue']){
    const sameStyle=buildDxfXml(originalWire.rule.style)===buildDxfXml(requestedWire.rule.style)
    const value=attribute==='dxfId'&&sameStyle?readXmlAttribute(raw,attribute):readXmlAttribute(serialized,attribute)
    restored=restored.replace(new RegExp(`\\s+${attribute}=(?:"[^"]*"|'[^']*')`),'')
    if(value!==undefined)restored=restored.replace('<cfRule',`<cfRule ${attribute}="${value}"`)
   }
   return block.replace(serialized,()=>restored)
  })
  const check=readConditionalFormattingSnapshot(next,styles.serialize(),themePalette)
  if(check.issues.length||check.rules.length!==snapshot.rules.length)throw Error('Conditional-formatting target snapshot is not lossless: '+check.issues.join('; '))
  if(next!==xml)replaced.set(path,next)
 }
 if(styles.changed){
  if(hasStyles)replaced.set('xl/styles.xml',styles.serialize())
  else{
   added.set('xl/styles.xml',styles.serialize())
   const contentTypes=await source.readText('[Content_Types].xml')
   if(![...contentTypes.matchAll(/<Override\b[^>]*\/>/g)].some(node=>readXmlAttribute(node[0],'PartName')==='/xl/styles.xml'))replaced.set('[Content_Types].xml',appendRootChild(contentTypes,'Types','<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'))
   const relsPath='xl/_rels/workbook.xml.rels',rels=await source.readText(relsPath),type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles'
   const rel=[...rels.matchAll(/<Relationship\b[^>]*\/>/g)].find(node=>readXmlAttribute(node[0],'Type')===type)
   if(rel){if(!['styles.xml','./styles.xml','/xl/styles.xml'].includes(readXmlAttribute(rel[0],'Target')??''))throw Error('A nonstandard styles relationship cannot be replaced implicitly.')}
   else{let max=0;for(const id of rels.matchAll(/\bId="rId([0-9]+)"/g))max=Math.max(max,Number(id[1]));replaced.set(relsPath,appendRootChild(rels,'Relationships',`<Relationship Id="rId${max+1}" Type="${type}" Target="styles.xml"/>`))}
  }
 }
 if(!replaced.size)return bytes
 const mutation=await assemblePackage(bytes,{replaced,added,addedBinary:new Map(),removedEntries:[],addedEntries:[...added.keys()],touchedEntries:[...replaced.keys(),...added.keys()]})
 assertOnlyTouchedEntriesChanged(mutation)
 return mutation.buffer
}

function serializedConditionKey(block:string):string{
 return block.replace(/<cfRule\b[^>]*>/,opening=>opening.replace(/\s+(?:dxfId|priority)="[^"]*"/g,''))
}
function wireIdentityArray(rules:readonly CfWireRule[]):string{
 return rules.map(wireIdentity).join('\n')
}
function conditionIdentity(wire:CfWireRule):string{
 const {style: _style,...condition}=wire.rule
 return wireIdentity({...wire,stopIfTrue:false,rule:condition})
}

function wireIdentity(rule:CfWireRule):string{
 return JSON.stringify(rule,(_key,value:unknown)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.entries(value).filter(([,item])=>item!==undefined).sort(([a],[b])=>a.localeCompare(b))):value)
}

// Same minimal insertion recipe as existing rules.ts; existing sections are never reconstructed.
function appendRootChild(xml:string,rootName:string,child:string):string{
 const empty=xml.match(new RegExp(`<${rootName}\\b([^>]*?)/>`))
 if(empty?.index!==undefined)return xml.slice(0,empty.index)+`<${rootName}${empty[1]}>${child}</${rootName}>`+xml.slice(empty.index+empty[0].length)
 const close=`</${rootName}>`,at=xml.lastIndexOf(close);if(at<0)throw Error(`OOXML part has no closing ${close}.`)
 return xml.slice(0,at)+child+xml.slice(at)
}
