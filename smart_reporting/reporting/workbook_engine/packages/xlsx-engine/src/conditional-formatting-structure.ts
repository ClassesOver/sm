/** Trusted interval planner shared by file replay and official structural followers. */
import {formatAddress,parseRange,columnIndex} from './cell-address'
import {FORMULA_REFERENCE_PATTERN} from './sheets-edit'
import {shiftFormulaText,shiftRangeReference,type ShiftSpec} from './structural'
import {offsetFormulaRefs} from './conditional-formatting-offset-source'
import type {CfWireRule} from './conditional-formatting-source'
type Area=CfWireRule['ranges'][number]
export interface ConditionalFormattingStructureOptions {geometry:'cells'|'rows-columns'}
export interface ConditionalFormattingStructureGroup {sourceRuleIndex:number;groups:CfWireRule[]}
const references=new RegExp(FORMULA_REFERENCE_PATTERN.source,'giu')
const skip=/((?:"(?:[^"]|"")*")|(?:(?<=[A-Za-z0-9_.])\[(?:[^\][]|\[[^\][]*\])*\]))/
function mapFormulas(value:unknown,change:(formula:string)=>string):unknown{
 if(Array.isArray(value))return value.map(item=>mapFormulas(item,change))
 if(!value||typeof value!=='object')return value
 const result:Record<string,unknown>=Object.fromEntries(Object.entries(value).map(([key,item])=>[key,mapFormulas(item,change)]))
 if((result.type==='formula'||result.subType==='formula')&&typeof result.value==='string')result.value=change(result.value)
 return result
}
function formulas(rule:Record<string,unknown>):string[]{const result:string[]=[];mapFormulas(rule,value=>{result.push(value);return value});return result}
function relativeKey(formula:string,row:number,column:number):string{
 return formula.split(skip).map((segment,index)=>index%2?segment:segment.replace(references,(full,guard:string,qualifier:string|undefined,reference:string)=>{
  const prefix=qualifier?qualifier+'!':''
  const value=reference.replace(/(\$?)([A-Z]{1,3})(\$?)(\d+)/gi,(_full,ca:string,col:string,ra:string,digits:string)=>`${ca?'C$':'C'}${columnIndex(col)-(ca?0:column)}${ra?'R$':'R'}${Number(digits)-1-(ra?0:row)}`)
  return guard+prefix+value
 })).join('')
}
function key(rule:Record<string,unknown>):string{return JSON.stringify(rule,(_key,value:unknown)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b))):value)}
/** Split only at formula/reference transition boundaries, never at every cell. */
export function planConditionalFormattingStructure(rules:readonly CfWireRule[],hostSheetName:string,editedSheetName:string,spec:ShiftSpec,options:ConditionalFormattingStructureOptions={geometry:'rows-columns'}):ConditionalFormattingStructureGroup[]{
 const ownSheet=hostSheetName.toLowerCase()===editedSheetName.toLowerCase()
 let partitionCount=0
 return rules.map((wire,sourceRuleIndex)=>{
  const anchor=[...wire.ranges].sort((a,b)=>a.startRow-b.startRow||a.startColumn-b.startColumn)[0]!
  const rowCuts=new Set<number>(),colCuts=new Set<number>()
  const cut=(axis:'row'|'column',position:number)=>{if(Number.isSafeInteger(position))(axis==='row'?rowCuts:colCuts).add(position)}
  if(ownSheet){cut(spec.axis,spec.start);if(spec.delta<0)cut(spec.axis,spec.start-spec.delta);if(spec.band){cut(spec.axis==='row'?'column':'row',spec.band.start);cut(spec.axis==='row'?'column':'row',spec.band.end+1)}}
  for(const formula of formulas(wire.rule))for(const [segmentIndex,segment]of formula.split(skip).entries()){
   if(segmentIndex%2)continue
   for(const match of segment.matchAll(references)){
    const qualifier=match[2],reference=match[3]!
    const own=qualifier===undefined?ownSheet:(qualifier.startsWith("'")?qualifier.slice(1,-1).replaceAll("''","'"):qualifier).toLowerCase()===editedSheetName.toLowerCase()
    for(const token of reference.split(':')){
     const cell=token.match(/^(\$?)([A-Z]{1,3})(\$?)(\d+)$/i),column=token.match(/^(\$?)([A-Z]{1,3})$/i),row=token.match(/^(\$?)(\d+)$/)
     const endpoints=cell?[{axis:'column' as const,absolute:cell[1]==='$',value:columnIndex(cell[2]!)},{axis:'row' as const,absolute:cell[3]==='$',value:Number(cell[4])-1}]:column?[{axis:'column' as const,absolute:column[1]==='$',value:columnIndex(column[2]!)}]:row?[{axis:'row' as const,absolute:row[1]==='$',value:Number(row[2])-1}]:[]
     for(const endpoint of endpoints){
      if(endpoint.absolute)continue
      const origin=endpoint.axis==='row'?anchor.startRow:anchor.startColumn,max=endpoint.axis==='row'?1048576:16384
      // Copy/fill off-grid transitions also change formula identity.
      cut(endpoint.axis,origin-endpoint.value);cut(endpoint.axis,origin+max-endpoint.value)
      if(own&&endpoint.axis===spec.axis){cut(endpoint.axis,origin+spec.start-endpoint.value);if(spec.delta<0)cut(endpoint.axis,origin+spec.start-spec.delta-endpoint.value)}
      if(own&&spec.band&&endpoint.axis!==spec.axis){cut(endpoint.axis,origin+spec.band.start-endpoint.value);cut(endpoint.axis,origin+spec.band.end+1-endpoint.value)}
     }
    }
   }
  }
  const groups=new Map<string,CfWireRule>()
  for(const area of [...wire.ranges].sort((a,b)=>a.startRow-b.startRow||a.startColumn-b.startColumn)){
   const rows=[area.startRow,...[...rowCuts].filter(value=>value>area.startRow&&value<=area.endRow).sort((a,b)=>a-b),area.endRow+1]
   const cols=[area.startColumn,...[...colCuts].filter(value=>value>area.startColumn&&value<=area.endColumn).sort((a,b)=>a-b),area.endColumn+1]
   partitionCount+=(rows.length-1)*(cols.length-1)
   if(partitionCount>10000)throw Error('Conditional-formatting structural partition budget exceeded')
   for(let r=0;r<rows.length-1;r++)for(let c=0;c<cols.length-1;c++){
    const original:Area={startRow:rows[r]!,endRow:rows[r+1]!-1,startColumn:cols[c]!,endColumn:cols[c+1]!-1}
    const crossStart=spec.axis==='row'?original.startColumn:original.startRow,crossEnd=spec.axis==='row'?original.endColumn:original.endRow
    const moves=ownSheet&&(!spec.band||crossStart>=spec.band.start&&crossEnd<=spec.band.end)
    const reference=moves?shiftRangeReference(`${formatAddress(original.startRow,original.startColumn)}:${formatAddress(original.endRow,original.endColumn)}`,spec):`${formatAddress(original.startRow,original.startColumn)}:${formatAddress(original.endRow,original.endColumn)}`
    if(reference===null)continue
    const range={...parseRange(reference)}
    if(range.startRow>1048575||range.startColumn>16383)continue
    range.endRow=Math.min(range.endRow,1048575);range.endColumn=Math.min(range.endColumn,16383)
    // Interior inserts belong to the preceding portion of an existing range.
    if(options.geometry==='rows-columns'&&moves&&spec.delta>0){
     const end=spec.axis==='row'?original.endRow:original.endColumn,start=spec.axis==='row'?area.startRow:area.startColumn,areaEnd=spec.axis==='row'?area.endRow:area.endColumn
     if(end===spec.start-1&&start<spec.start&&spec.start<=areaEnd){if(spec.axis==='row')range.endRow+=spec.delta;else range.endColumn+=spec.delta}
    }
    const rule=mapFormulas(wire.rule,formula=>shiftFormulaText(offsetFormulaRefs(formula,original.startRow-anchor.startRow,original.startColumn-anchor.startColumn),spec,ownSheet,editedSheetName)) as Record<string,unknown>
    // Normalize to an absolute host origin only for grouping; each emitted
    // group's actual formula remains relative to its own top-left anchor.
    const identity=key(mapFormulas(rule,formula=>relativeKey(formula,range.startRow,range.startColumn)) as Record<string,unknown>)
    const existing=groups.get(identity)
    if(existing)groups.set(identity,{...existing,ranges:[...existing.ranges,range]})
    else groups.set(identity,{ranges:[range],stopIfTrue:wire.stopIfTrue,rule})
    const fullAxis=spec.axis==='row'?area.startRow===0&&area.endRow===1048575:area.startColumn===0&&area.endColumn===16383
    const originalStart=spec.axis==='row'?original.startRow:original.startColumn
    if(options.geometry==='rows-columns'&&moves&&fullAxis&&spec.delta>0&&spec.start===0&&originalStart===0){
     const inserted={...range};if(spec.axis==='row'){inserted.startRow=0;inserted.endRow=spec.delta-1}else{inserted.startColumn=0;inserted.endColumn=spec.delta-1}
     const insertedKey=key(mapFormulas(rule,formula=>relativeKey(formula,inserted.startRow,inserted.startColumn)) as Record<string,unknown>),previous=groups.get(insertedKey)
     groups.set(insertedKey,previous?{...previous,ranges:[...previous.ranges,inserted]}:{ranges:[inserted],stopIfTrue:wire.stopIfTrue,rule})
    }
   }
  }
  return{sourceRuleIndex,groups:[...groups.values()].map(group=>{
   const merged:Area[]=[]
   for(const range of [...group.ranges].sort((a,b)=>a.startRow-b.startRow||a.startColumn-b.startColumn)){
    const index=merged.findIndex(previous=>previous.startColumn===range.startColumn&&previous.endColumn===range.endColumn&&previous.endRow+1===range.startRow||previous.startRow===range.startRow&&previous.endRow===range.endRow&&previous.endColumn+1===range.startColumn)
    if(index<0)merged.push(range)
    else merged[index]={startRow:Math.min(merged[index]!.startRow,range.startRow),endRow:Math.max(merged[index]!.endRow,range.endRow),startColumn:Math.min(merged[index]!.startColumn,range.startColumn),endColumn:Math.max(merged[index]!.endColumn,range.endColumn)}
   }
   return{...group,ranges:merged}
  }).sort((a,b)=>a.ranges[0]!.startRow-b.ranges[0]!.startRow||a.ranges[0]!.startColumn-b.ranges[0]!.startColumn)}
 })
}
