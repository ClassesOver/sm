// Browser adaptation of fixed GenOffice Rust worksheet ConditionalRule fields and
// renderer buildConditionalRule; source serializer remains the persistence oracle.
import { applyCfRules, buildDxfXml, OOXML_ICON_SETS, WORST_FIRST_ICON_SETS, type CfWireRule } from './conditional-formatting-source'
import { isValidRuleSqref } from './cf-schemas'
import { formatAddress, parseAddress } from './cell-address'
import { decodeXmlText, escapeXmlText, readXmlAttribute, sectionInner, extractElements } from './xml'
import { createStylesheetColorResolver } from './table-style-read'
import { formatSheetQualifier } from './sheets-edit'

export interface ConditionalFormattingSnapshot {
  rules: CfWireRule[]
  issues: string[]
  /** Exact original XML retained even when the editable projection is incomplete. */
  sourceXml: string
  /** Source writer enforces unchanged identity for these extension-backed rules. */
  linkedRuleIds: string[]
  linkedRules: CfWireRule[]
}
const attr = (xml: string, name: string) => readXmlAttribute(xml.match(/^<[^>]*>/)?.[0] ?? xml, name)
const flag = (xml: string, name: string) => ['1', 'true'].includes(attr(xml, name) ?? '')
const num = (value: string | undefined) => { const n = Number(value); if (value === undefined || !Number.isFinite(n)) throw Error('CF numeric attribute invalid'); return n }
const text = (xml: string) => decodeXmlText(xml.replace(/^<[^>]*>/, '').replace(/<\/[^>]*>$/, ''))
function ranges(sqref: string) {
  if (!isValidRuleSqref(sqref)) throw Error('CF ranges invalid')
  return sqref.split(' ').map(ref => { const [a,b=a] = ref.replace(/\$/g,'').split(':');const first=parseAddress(a!),last=parseAddress(b!);return {startRow:first.row,endRow:last.row,startColumn:first.column,endColumn:last.column} })
}
function color(xml: string) {
 const rgb=attr(xml,'rgb');if(!rgb||! /^(?:[0-9a-f]{2})?[0-9a-f]{6}$/i.test(rgb))throw Error('CF color is not representable RGB');return '#'+rgb.slice(-6).toUpperCase()
}
function threshold(xml: string): Record<string, unknown> {
 const type=attr(xml,'type');if(type==='min'||type==='max')return {type}
 if(!['num','percent','percentile','formula'].includes(type??''))throw Error('CF threshold unsupported')
 const value=attr(xml,'val');return {type,value:type==='formula'?decodeXmlText(value??''):num(value)}
}
// Reference/function case and optional sheet-name quoting do not change the
// condition. Literal case and whitespace (including reference intersection)
// remain significant; comparing only the projected base rule misses stale x14.
function formulaIdentity(formula: string): string {
 return formula.trim().replace(/^=/,'').split('"').map((part,index)=>index%2?part:part.toUpperCase().replace(/'((?:[^']|'')+)'!/g,(_full,name:string)=>`${formatSheetQualifier(name.replaceAll("''","'"))}!`)).join('"')
}
function validateLinkedThresholds(base: string, twin: string): void {
 const values=extractElements(base,'cfvo'),extended=extractElements(twin,'x14:cfvo')
 const mismatch=()=>{throw Error('CF linked extension threshold differs from its base rule')}
 if(values.length!==extended.length)mismatch()
 for(let index=0;index<values.length;index++){
  const value=values[index]!,other=extended[index]!,type=attr(value,'type'),otherType=attr(other,'type')?.replace(/^autoMin$/,'min').replace(/^autoMax$/,'max')
  if(type!==otherType||['0','false'].includes(attr(value,'gte')??'')!==['0','false'].includes(attr(other,'gte')??''))mismatch()
  if(type==='min'||type==='max')continue
  const formulas=extractElements(other,'xm:f').map(text)
  if(formulas.length!==1)mismatch()
  if(type==='formula'){
   const original=decodeXmlText(attr(value,'val')??'')
   if(!original.trim()||!formulas[0]?.trim()||formulaIdentity(original)!==formulaIdentity(formulas[0]!))mismatch()
  }else if(num(attr(value,'val'))!==num(formulas[0]))mismatch()
 }
}
function dxfStyle(xml: string | undefined, resolve: (entry:string)=>string|undefined): Record<string, unknown> {
 if(xml===undefined)throw Error('CF dxf reference missing')
 const sourceColor=(node:string)=>{
  const theme=attr(node,'theme'),tint=attr(node,'tint'),indexed=attr(node,'indexed')
  if(theme!==undefined&&(!/^\d+$/.test(theme)||Number(theme)>11))throw Error('CF theme index unsupported')
  if(tint!==undefined&&(!Number.isFinite(Number(tint))||Number(tint)<-1||Number(tint)>1))throw Error('CF tint invalid')
  if(indexed!==undefined&&(!/^\d+$/.test(indexed)||Number(indexed)>65))throw Error('CF indexed color unsupported')
  const value=resolve(node);if(value===undefined)throw Error('CF dxf color cannot be resolved from source')
  return value
 }
 // Resolve existing source theme/tint/indexed palettes through the table-style
 // reader's shared source algorithm. Unknown attributes remain in identity.
 const hasForeground=/<fgColor\b/.test(xml)
 xml=xml.replace(/<(?:color|fgColor|bgColor)\b[^>]*>/g,node=>{
  if(!/\b(?:theme|indexed|tint)=/.test(node)||attr(node,'indexed')==='64'&&node.startsWith('<bgColor')&&hasForeground)return node
  const rgb=sourceColor(node),stripped=node.replace(/\s+(?:theme|tint|indexed|rgb)\s*=\s*(?:"[^"]*"|'[^']*')/g,'')
  return stripped.replace(/\/?\s*>$/,end=>` rgb="FF${rgb.slice(1)}"${end}`)
 })
 const style: Record<string,unknown>={}
 const font=extractElements(xml,'font')[0]
 if(font) {
  for(const [tag,key]of [['b','bl'],['i','it'],['strike','st'],['u','ul']]) {
   const node=extractElements(font,tag!)[0];if(!node)continue
   const val=attr(node,'val');if(val!==undefined&&!['1','true','single'].includes(val))throw Error('CF explicit off/underline style unsupported')
   style[key!]=['st','ul'].includes(key!)?{s:1}:1
  }
  const node=extractElements(font,'color')[0];if(node)style.cl={rgb:color(node)}
  const rest=font.replace(/^<font[^>]*>|<\/font>$/g,'').replace(/<(b|i|strike|u|color)\b[^>]*(?:\/>|>[\s\S]*?<\/\1>)/g,'').trim();if(rest)throw Error('CF dxf font contains unprojected properties')
 }
 const fill=extractElements(xml,'fill')[0]
 if(fill){const pattern=extractElements(fill,'patternFill')[0];if(!pattern||!['solid',undefined].includes(attr(pattern,'patternType')))throw Error('CF dxf fill unsupported');const fg=extractElements(pattern,'fgColor')[0],bg=extractElements(pattern,'bgColor')[0];if(!fg&&!bg)throw Error('CF dxf fill color missing');style.bg={rgb:color(fg??bg!)};if(fg&&bg&&attr(bg,'indexed')!=='64'&&color(bg)!==color(fg))throw Error('CF patterned fill background unsupported')}
 const rest=xml.replace(/^<dxf[^>]*>|<\/dxf>$/g,'').replace(/<(font|fill)\b[^>]*(?:\/>|>[\s\S]*?<\/\1>)/g,'').trim();if(rest)throw Error('CF dxf contains unprojected properties')
 // Accept conventional solid foreground fills as the same single-color dxf;
 // every other source attribute must survive projection through the writer.
 const normalized=xml.replace(/\s+patternType=["']solid["']/g,'').replace(/<bgColor\s+indexed=["']64["']\s*\/>/g,'').replace(/<(\/?)fgColor\b/g,'<$1bgColor')
 if(canonical(normalized)!==canonical(buildDxfXml(style)))throw Error('CF dxf includes unprojected attributes')
 return style
}
/** Canonical lexical identity, including every non-whitespace text/attribute; no ignored fields. */
function canonical(xml: string): string {
 // Fixed-source Rust resolve_color discards the ARGB alpha byte. Normalize
 // only valid color rgb attributes; unknown XML attributes still participate.
 xml=xml.replace(/<(?:color|fgColor|bgColor)\b[^>]*>/g,node=>node.replace(/\brgb=(?:"([0-9a-f]{6}|[0-9a-f]{8})"|'([0-9a-f]{6}|[0-9a-f]{8})')/gi,(_match,double:string|undefined,single:string|undefined)=>`rgb="FF${(double??single)!.slice(-6).toUpperCase()}"`))
 const tokens=xml.match(/<[^>]*>|[^<]+/g)??[]
 return tokens.flatMap(token=>{
  if(!token.startsWith('<'))return token.trim()?['text:'+decodeXmlText(token)]:[]
  if(/^<\//.test(token))return [token.replace(/\s+/g,'')]
  const name=token.match(/^<([^\s/>]+)/)?.[1];if(!name)throw Error('CF XML unsupported')
  const attrs=[...token.matchAll(/([^\s=<>]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)].map(m=>[m[1],decodeXmlText(m[2]??m[3]??'')]).sort((a,b)=>a[0]!.localeCompare(b[0]!))
  return [`<${name}:${JSON.stringify(attrs)}>`,...(/\/>$/.test(token)?[`</${name}>`]:[])]
 }).join('')
}
function canonicalRule(xml: string): string {
 // Explicit XML-schema defaults carry no extra editor state.
 return canonical(xml.replace(/\s+(stopIfTrue|reverse|equalAverage|percent|bottom)=(?:"(?:0|false)"|'(?:0|false)')/g,'')
  .replace(/\s+(showValue|aboveAverage|gte)=(?:"(?:1|true)"|'(?:1|true)')/g,'')
  .replace(/\s+(stopIfTrue|reverse|equalAverage|percent|bottom)=(?:"true"|'true')/g,' $1="1"')
  .replace(/\s+(showValue|aboveAverage|gte)=(?:"false"|'false')/g,' $1="0"'))
}

/** Fixed-source univer-sync.ts cellIs conditions, adapted to plain wire rules. */
function cellIsCondition(operator:string|undefined,formulas:string[],areas:CfWireRule['ranges']):Record<string,unknown>{
 const first=formulas[0],second=formulas[1],between=operator==='between'||operator==='notBetween'
 if(!first||formulas.length!==(between?2:1))throw Error('CF cellIs operands invalid')
 const symbols:Record<string,string>={equal:'=',notEqual:'<>',greaterThan:'>',greaterThanOrEqual:'>=',lessThan:'<',lessThanOrEqual:'<='}
 if(!between&&!symbols[operator??''])throw Error('CF cellIs operator unsupported')
 const a=Number(first),b=Number(second),numeric=Number.isFinite(a)
 if(numeric&&between&&!Number.isFinite(b))throw Error('CF cellIs second operand unsupported')
 const cells=areas.reduce((sum,r)=>sum+(r.endRow-r.startRow+1)*(r.endColumn-r.startColumn+1),0)
 const formulaBudget=cells>0&&cells<=20_000
 const anchorArea=[...areas].sort((a,b)=>a.startRow-b.startRow||a.startColumn-b.startColumn)[0]!
 const anchor=formatAddress(anchorArea.startRow,anchorArea.startColumn)
 if(numeric){
  const excelBlank=between?(operator==='between'?Math.min(a,b)<=0&&0<=Math.max(a,b):!(Math.min(a,b)<=0&&0<=Math.max(a,b))):({equal:0===a,notEqual:0!==a,greaterThan:0>a,greaterThanOrEqual:0>=a,lessThan:0<a,lessThanOrEqual:0<=a}[operator!])!
  const diverges=excelBlank!==(operator==='notEqual'||operator==='notBetween')
  if(!formulaBudget||!diverges)return{subType:'number',operator,value:formulas.map(Number)}
  const comparison=between?`AND(${anchor}>=${Math.min(a,b)},${anchor}<=${Math.max(a,b)})`:`${anchor}${symbols[operator!]}${a}`
  return{subType:'formula',value:operator==='notBetween'?`NOT(${comparison})`:comparison}
 }
 const quoted=first.match(/^"([\s\S]*)"$/),wrap=(value:string)=>/^"[\s\S]*"$/.test(value)?value:`(${value})`
 if(operator==='equal'&&quoted&&!formulaBudget)return{subType:'text',operator,value:quoted[1]!.replace(/""/g,'"')}
 const operand=operator==='equal'?(quoted?first.replace(/[*?]/g,'~$&'):`(${first})`):wrap(first)
 const comparison=between?`AND(${anchor}>=${wrap(first)},${anchor}<=${wrap(second!)})`:`${anchor}${symbols[operator!]}${operand}`
 return{subType:'formula',value:operator==='notBetween'?`NOT(${comparison})`:comparison}
}

export function readConditionalFormattingSnapshot(worksheetXml: string, stylesXml: string, themePalette?: readonly string[]): ConditionalFormattingSnapshot {
 const result: ConditionalFormattingSnapshot={rules:[],issues:[],sourceXml:worksheetXml,linkedRuleIds:[],linkedRules:[]}
 const dxfs=extractElements(sectionInner(stylesXml,'dxfs')??'','dxf')
 const resolveColor=createStylesheetColorResolver(stylesXml,themePalette)
 const priorities=new Set<number>(),parsed: Array<{priority:number;rule:CfWireRule}>=[]
 const blocks=[...worksheetXml.matchAll(/<conditionalFormatting\b[^>]*(?:\/>|>[\s\S]*?<\/conditionalFormatting>)/g)].map(m=>m[0])
 const twins=extractElements(worksheetXml,'x14:conditionalFormatting'),usedTwins=new Set<string>()
 if((worksheetXml.match(/<(?:[\w.-]+:)?conditionalFormatting\b/g)??[]).length!==blocks.length+twins.length)result.issues.push('CF contains unprojected or malformed conditionalFormatting blocks')
 let outside=worksheetXml.replace(/<conditionalFormatting\b[^>]*(?:\/>|>[\s\S]*?<\/conditionalFormatting>)/g,'')
 for(const twin of twins)outside=outside.replace(twin,'')
 if(/<(?:[\w.-]+:)?cfRule\b/.test(outside))result.issues.push('CF rules outside supported base blocks')
 for(const block of blocks)try{
  const sqref=attr(block,'sqref');if(!sqref)throw Error('CF range missing')
  const opening=block.match(/^<conditionalFormatting\b[^>]*>/)?.[0]??''
  if(opening.replace(/^<conditionalFormatting\b/,'').replace(/\s+sqref\s*=\s*(?:"[^"]*"|'[^']*')/,'').replace(/\/?\s*>$/,'').trim())throw Error('CF block attributes are not fully projected')
  const areas=ranges(sqref),entries=extractElements(block,'cfRule')
  if(!entries.length)throw Error('CF block has no readable rules')
  const outer=block.replace(/^<conditionalFormatting[^>]*>|<\/conditionalFormatting>$/g,'');if(outer.replace(/<cfRule\b[^>]*(?:\/>|>[\s\S]*?<\/cfRule>)/g,'').trim())throw Error('CF block includes unprojected content')
  for(const entry of entries){
   let comparable=entry
   let linkedTwin: string | undefined
   const extension=extractElements(entry,'extLst')[0]
   if(extension){
    const ids=extractElements(extension,'x14:id').map(text)
    const matching=twins.filter(twin=>extractElements(twin,'x14:cfRule').some(rule=>attr(rule,'id')===ids[0]))
    const x14Bindings=[...worksheetXml.matchAll(/\bxmlns:x14\s*=\s*["']([^"']+)["']/g)].map(match=>match[1])
    const xmBindings=[...worksheetXml.matchAll(/\bxmlns:xm\s*=\s*["']([^"']+)["']/g)].map(match=>match[1])
    if(ids.length!==1||!ids[0]||result.linkedRuleIds.includes(ids[0])||matching.length!==1||!x14Bindings.length||x14Bindings.some(uri=>uri!=='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main')||!xmBindings.length||xmBindings.some(uri=>uri!=='http://schemas.microsoft.com/office/excel/2006/main'))throw Error('CF linked extension identity is missing or ambiguous')
    const twin=matching[0]!,rules=extractElements(twin,'x14:cfRule'),twinRule=rules.find(rule=>attr(rule,'id')===ids[0])!,twinRanges=extractElements(twin,'xm:sqref').map(text)
    if(rules.length!==1||twinRanges.length!==1||twinRanges[0]!==sqref||attr(twinRule,'type')!==attr(entry,'type')||attr(twinRule,'priority')!==attr(entry,'priority'))throw Error('CF linked extension scope differs from its base rule')
    validateLinkedThresholds(entry,twinRule)
    result.linkedRuleIds.push(ids[0]);usedTwins.add(twin)
    linkedTwin=twinRule
    comparable=entry.replace(extension,'')
   }
   const priority=num(attr(entry,'priority'));if(!Number.isSafeInteger(priority)||priority<1||priorities.has(priority))throw Error('CF priorities invalid or ambiguous');priorities.add(priority)
   const type=attr(entry,'type'),formulas=extractElements(entry,'formula').map(text)
   const rule: Record<string,unknown>={}
   let cellIsProjection:Record<string,unknown>|undefined
   if(type==='colorScale'){
    const node=extractElements(entry,'colorScale')[0]!;const values=extractElements(node,'cfvo').map(threshold),colors=extractElements(node,'color').map(color);if(values.length<2||values.length!==colors.length)throw Error('CF color scale malformed')
    Object.assign(rule,{type:'colorScale',config:values.map((value,index)=>({index,value,color:colors[index]}))})
   } else if(type==='dataBar'){
    const node=extractElements(entry,'dataBar')[0]!;const values=extractElements(node,'cfvo').map(threshold);if(values.length!==2)throw Error('CF data bar malformed')
    const positiveColor=color(extractElements(node,'color')[0]!),extensionBar=linkedTwin?extractElements(linkedTwin,'x14:dataBar')[0]:undefined
    const negative=extensionBar?extractElements(extensionBar,'x14:negativeFillColor')[0]:undefined
    Object.assign(rule,{type:'dataBar',isShowValue:!['0','false'].includes(attr(node,'showValue')??''),config:{min:values[0],max:values[1],positiveColor,nativeColor:negative?color(negative):extensionBar&&flag(extensionBar,'negativeBarColorSameAsPositive')?positiveColor:'#FF0000',isGradient:!extensionBar||!['0','false'].includes(attr(extensionBar,'gradient')??'')}})
   } else if(type==='iconSet'){
    const node=extractElements(entry,'iconSet')[0]!,iconType=attr(node,'iconSet')??'3TrafficLights1',values=extractElements(node,'cfvo');if(!OOXML_ICON_SETS.has(iconType)||values.length!==Number(iconType[0]))throw Error('CF icon set unsupported')
    const config=values.map((value,index)=>{const fileIcon=flag(node,'reverse')?values.length-1-index:index;return{iconType,iconId:String(WORST_FIRST_ICON_SETS.has(iconType)?fileIcon:values.length-1-fileIcon),operator:attr(value,'gte')==='0'?'greaterThan':'greaterThanOrEqual',value:index===0?{type:'min'}:threshold(value)}}).reverse()
    Object.assign(rule,{type:'iconSet',config,isShowValue:!['0','false'].includes(attr(node,'showValue')??'')})
   } else {
    Object.assign(rule,{type:'highlightCell',style:attr(entry,'dxfId')===undefined?{}:dxfStyle(dxfs[num(attr(entry,'dxfId'))],resolveColor)})
    if(type==='cellIs'){
     const operator=attr(entry,'operator')
     cellIsProjection=cellIsCondition(operator,formulas,areas)
     // Validate original cellIs XML with the source serializer before applying
     // its renderer projection; formulas are restored verbatim below.
     Object.assign(rule,{subType:'number',operator,value:formulas.map(()=>0)})
    } else if(['containsText','notContainsText','beginsWith','endsWith'].includes(type??''))Object.assign(rule,{subType:'text',operator:type,value:decodeXmlText(attr(entry,'text')??'')})
    else if(['containsBlanks','notContainsBlanks','containsErrors','notContainsErrors'].includes(type??''))Object.assign(rule,{subType:'text',operator:type,value:''})
    else if(type==='duplicateValues'||type==='uniqueValues')Object.assign(rule,{subType:type})
    else if(type==='top10')Object.assign(rule,{subType:'rank',value:num(attr(entry,'rank')),isBottom:flag(entry,'bottom'),isPercent:flag(entry,'percent')})
    else if(type==='aboveAverage')Object.assign(rule,{subType:'average',operator:(['0','false'].includes(attr(entry,'aboveAverage')??'')?'lessThan':'greaterThan')+(flag(entry,'equalAverage')?'OrEqual':'')})
    else if(type==='expression'&&formulas.length===1)Object.assign(rule,{subType:'formula',value:formulas[0]})
    else throw Error(`CF type ${type??'missing'} unsupported`)
   }
   const wire:CfWireRule={ranges:areas,stopIfTrue:flag(entry,'stopIfTrue'),rule}
   // Roundtrip all source attributes/formulas through its trusted serializer.
   const reproduced=applyCfRules('<worksheet><sheetData/></worksheet>',[wire],{internDxf:()=>num(attr(entry,'dxfId')??'0')})
   let serialized=extractElements(reproduced,'cfRule')[0]!.replace(/priority="1"/,`priority="${priority}"`)
   if(cellIsProjection){let index=0;serialized=serialized.replace(/<formula>[\s\S]*?<\/formula>/g,()=>`<formula>${escapeXmlText(formulas[index++]!)}</formula>`)}
   if(attr(entry,'dxfId')===undefined)serialized=serialized.replace(/ dxfId="0"/,'')
   if(canonicalRule(comparable)!==canonicalRule(serialized))throw Error('CF rule contains unprojected attributes, formulas or extension data')
   if(cellIsProjection){delete rule.operator;delete rule.value;Object.assign(rule,cellIsProjection)}
   if(linkedTwin)result.linkedRules.push(wire)
   parsed.push({priority,rule:wire})
  }
 }catch(error){result.issues.push((error as Error).message)}
 if(twins.some(twin=>!usedTwins.has(twin)))result.issues.push('CF extension has no unique represented base rule')
 result.rules=parsed.sort((a,b)=>a.priority-b.priority).map(item=>item.rule)
 return result
}
