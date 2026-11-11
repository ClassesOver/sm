/** Source-only CF structural materialization; no client provenance is accepted. */
import {readConditionalFormattingSnapshot} from './conditional-formatting-read'
import {planConditionalFormattingStructure,type ConditionalFormattingStructureOptions} from './conditional-formatting-structure'
import {formatAddress} from './cell-address'
import {shiftFormulaText,shiftRangedFeatures,shiftQualifiedFormulas,type ShiftSpec} from './structural'
import {offsetFormulaRefs} from './conditional-formatting-offset-source'
import {decodeXmlText,escapeXmlText,escapeXmlAttribute,extractElements,readXmlAttribute} from './xml'
const bases=/<conditionalFormatting\b[^>]*(?:\/>|>[\s\S]*?<\/conditionalFormatting>)/g
const containers=/<x14:conditionalFormattings\b[^>]*>[\s\S]*?<\/x14:conditionalFormattings>/g
function body(xml:string):string{return decodeXmlText(xml.replace(/^<[^>]*>|<\/[^>]*>$/g,''))}
function attribute(xml:string,name:string,value:string):string{
 const opening=xml.match(/^<[^>]*>/)![0],clean=opening.replace(new RegExp(`\\s+${name}=(?:"[^"]*"|'[^']*')`),'')
 return xml.replace(opening,()=>clean.replace(/\/?\s*>$/,end=>` ${name}="${escapeXmlAttribute(value)}"${end}`))
}
export function overlayConditionalFormattingXml(target:string,source:string):string{
 const blocks=[...source.matchAll(bases)].map(match=>match[0]).join('')
 let next=target.replace(bases,'')
 const anchor=next.match(/<dataValidations\b|<hyperlinks\b|<printOptions\b|<pageMargins\b|<pageSetup\b|<headerFooter\b|<rowBreaks\b|<colBreaks\b|<drawing\b|<legacyDrawing\b|<picture\b|<oleObjects\b|<tableParts\b|<extLst\b|<\/worksheet>/)?.index
 if(anchor===undefined)throw Error('CF structural worksheet closing identity missing')
 next=next.slice(0,anchor)+blocks+next.slice(anchor)
 const replacements=[...source.matchAll(containers)].map(match=>match[0]);let index=0
 next=next.replace(containers,()=>replacements[index++]??'')
 if(index<replacements.length)throw Error('CF linked structural container identity missing')
 next=next.replace(/<ext\b([^>]*)>\s*<\/ext>/g,(full,attrs:string)=>readXmlAttribute(attrs,'uri')==='{78C0D931-6437-407D-A8EE-F0AAD7539E65}'?'':full)
 return next.replace(/<extLst\b[^>]*>\s*<\/extLst>/g,'')
}
export function shiftConditionalFormattingXml(xml:string,stylesXml:string,theme:readonly string[]|undefined,host:string,edited:string,spec:ShiftSpec,options:ConditionalFormattingStructureOptions={geometry:'rows-columns'}):string{
 if(!/<conditionalFormatting\b/.test(xml))return xml
 const source=readConditionalFormattingSnapshot(xml,stylesXml,theme)
 // Incomplete legacy CF keeps the existing surgical range-only contract;
 // it never becomes an editable complete snapshot through this planner.
 if(source.issues.length&&options.geometry==='cells')throw Error('Conditional-formatting cell-shift source incomplete: '+source.issues.join('; '))
 if(source.issues.length)return host===edited?shiftRangedFeatures(xml,spec):shiftQualifiedFormulas(xml,spec,edited)
 const plans=planConditionalFormattingStructure(source.rules,host,edited,spec,options)
 if(JSON.stringify(plans.flatMap(plan=>plan.groups))===JSON.stringify(source.rules))return xml
 const raw=extractElements(xml,'cfRule').sort((a,b)=>Number(readXmlAttribute(a,'priority'))-Number(readXmlAttribute(b,'priority')))
 const twins=extractElements(xml,'x14:conditionalFormatting'),newTwins:string[]=[],blocks:string[]=[]
 const ids=new Set(extractElements(xml,'x14:id').map(body));let counter=1,priority=0
 const newId=()=>{let id:string;do{id=`{00000000-0000-4000-8000-${String(counter++).padStart(12,'0')}}`}while(ids.has(id));ids.add(id);return id}
 for(const plan of plans){
  const original=source.rules[plan.sourceRuleIndex]!,entry=raw[plan.sourceRuleIndex]!,anchor=[...original.ranges].sort((a,b)=>a.startRow-b.startRow||a.startColumn-b.startColumn)[0]!
  const linked=extractElements(entry,'x14:id')[0],id=linked?body(linked):undefined
  for(const [groupIndex,group]of plan.groups.entries()){
   priority++
   const first=[...group.ranges].sort((a,b)=>a.startRow-b.startRow||a.startColumn-b.startColumn)[0]!
   const originalPoint={row:first.startRow,column:first.startColumn}
   const crossStart=spec.axis==='row'?first.startColumn:first.startRow,crossEnd=spec.axis==='row'?first.endColumn:first.endRow
   if(host===edited&&(!spec.band||crossStart>=spec.band.start&&crossEnd<=spec.band.end)){
    const value=spec.axis==='row'?originalPoint.row:originalPoint.column
    const restored=spec.delta>0?(value>=spec.start+spec.delta?value-spec.delta:value>=spec.start?spec.start-1:value):(value>=spec.start?value-spec.delta:value)
    if(spec.axis==='row')originalPoint.row=Math.max(0,restored);else originalPoint.column=Math.max(0,restored)
   }
   const formula=(value:string)=>shiftFormulaText(offsetFormulaRefs(value,originalPoint.row-anchor.startRow,originalPoint.column-anchor.startColumn),spec,host===edited,edited)
   const transform=(value:string)=>value.replace(/<(formula|xm:f)\b([^>]*)>([\s\S]*?)<\/\1>/g,(_full,tag:string,attrs:string,content:string)=>`<${tag}${attrs}>${escapeXmlText(formula(decodeXmlText(content)))}</${tag}>`).replace(/<(?:x14:)?cfvo\b[^>]*>/g,node=>readXmlAttribute(node,'type')==='formula'&&readXmlAttribute(node,'val')!==undefined?attribute(node,'val',formula(readXmlAttribute(node,'val')!)):node)
   const sqref=group.ranges.map(range=>`${formatAddress(range.startRow,range.startColumn)}:${formatAddress(range.endRow,range.endColumn)}`).join(' ')
   let rule=attribute(transform(entry),'priority',String(priority))
   if(id){
    const derived=groupIndex===0?id:newId(),twin=twins.find(value=>extractElements(value,'x14:cfRule').some(node=>readXmlAttribute(node,'id')===id))!
    rule=rule.replace(linked!,()=>linked!.replace(/>[^<]*</,()=>`>${derived}<`))
    let next=transform(twin).replace(/<x14:cfRule\b[^>]*>/,node=>attribute(attribute(node,'id',derived),'priority',String(priority)))
    next=next.replace(/<xm:sqref\b[^>]*>[\s\S]*?<\/xm:sqref>/,`<xm:sqref>${escapeXmlText(sqref)}</xm:sqref>`)
    newTwins.push(next)
   }
   blocks.push(`<conditionalFormatting sqref="${escapeXmlAttribute(sqref)}">${rule}</conditionalFormatting>`)
  }
 }
 let transformed=xml.replace(bases,'');let placed=false
 transformed=transformed.replace(containers,container=>{if(placed)return '';placed=true;return newTwins.length?container.replace(/^([^>]*>)[\s\S]*(<\/x14:conditionalFormattings>)$/,'$1'+newTwins.join('')+'$2'):''})
 const close=transformed.lastIndexOf('</worksheet>');transformed=transformed.slice(0,close)+blocks.join('')+transformed.slice(close)
 const output=overlayConditionalFormattingXml(xml,transformed)
 const check=readConditionalFormattingSnapshot(output,stylesXml,theme)
 const identity=(value:unknown)=>JSON.stringify(value,(_key,item:unknown)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item)
 if(check.issues.length||identity(check.rules)!==identity(plans.flatMap(plan=>plan.groups)))throw Error('CF structural derived identity incomplete: '+check.issues.join('; '))
 return output
}
