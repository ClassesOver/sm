/** ISO/IEC 29500 §18.10.1.30/38/78: raw shared items and grouped items are separate index spaces. */
import { groupLabel, type PivotFieldGrouping } from './pivot-grouping'

export interface StandardPivotGrouping {
  fieldIndex: number
  groupItems: string[]
  rawItems: {type:'n'|'d';value:string;source:number}[]
  range: {groupBy:'range'|'months'|'quarters'|'years';startNum?:number;endNum?:number;startDate?:string;endDate?:string;groupInterval:number}
}
export interface PivotGroupingPersistence {fieldIndex:number;mode:'standard'|'private';reason?:string}

/** Gregorian ISO dates cannot represent Excel's fictitious 1900-02-29 (serial 60). */
export function pivotDateTime(serial:number,date1904=false):string|undefined {
  if(!Number.isFinite(serial)||serial<0||serial>2958465||!date1904&&Math.floor(serial)===60)return undefined
  const milliseconds=(date1904?Date.UTC(1904,0,1):Date.UTC(1899,11,30))+(serial+(!date1904&&serial<60?1:0))*86400000
  const date=new Date(Math.round(milliseconds))
  return Number.isFinite(date.getTime())&&date.getUTCFullYear()<=9999?date.toISOString().replace(/\.000Z$/,'').replace(/Z$/,''):undefined
}

export function standardPivotGrouping(fieldIndex:number,rule:PivotFieldGrouping,source:readonly (string|number|boolean|null|undefined)[]):{standard?:StandardPivotGrouping;persistence:PivotGroupingPersistence}{
 const privateMode=(reason:string)=>({persistence:{fieldIndex,mode:'private' as const,reason}})
 if(!source.length||source.some(value=>typeof value!=='number'||!Number.isFinite(value)))return privateMode('标准范围分组要求全部来源为数值且无空值；文本、空值或非法值保留兼容分组。')
 const values=source as readonly number[],unique=[...new Set(values)]
 let range:StandardPivotGrouping['range'],groups:string[],rawItems:StandardPivotGrouping['rawItems']
 if(rule.kind==='range'){
  const min=Math.min(...values),max=Math.max(...values),origin=rule.rangeStart??0
  const lower=Math.floor((min-origin)/rule.rangeStep),upper=Math.floor((max-origin)/rule.rangeStep)+1
  if(!Number.isSafeInteger(lower)||!Number.isSafeInteger(upper)||upper-lower>10000)return privateMode('数值分组完整区间超过10000组或超出安全数值范围，保留兼容分组。')
  const start=origin+lower*rule.rangeStep,end=origin+upper*rule.rangeStep
  if(!Number.isFinite(start)||!Number.isFinite(end)||!(end>max)||!(start<=min))return privateMode('数值分组边界无法精确表达，保留兼容分组。')
  groups=Array.from({length:upper-lower},(_,index)=>groupLabel(rule,origin+(lower+index+.5)*rule.rangeStep))
  range={groupBy:'range',startNum:start,endNum:end,groupInterval:rule.rangeStep}
  groups=[`<${start}`,...groups,`>${end}`]
  rawItems=unique.map(source=>({type:'n',value:String(source),source}))
 }else{
  const dates=unique.map(value=>pivotDateTime(value,rule.date1904))
  if(dates.some(value=>!value))return privateMode('日期分组含无法用Gregorian日期表达的序列（含1900年序列60），保留兼容分组。')
  const sorted=[...dates as string[]].sort(),start=sorted[0]!,end=sorted[sorted.length-1]!
  if(rule.dateUnit==='month')groups=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  else if(rule.dateUnit==='quarter')groups=['Q1','Q2','Q3','Q4']
  else{const first=Number(start.slice(0,4)),last=Number(end.slice(0,4));groups=Array.from({length:last-first+1},(_,i)=>String(first+i))}
  range={groupBy:rule.dateUnit==='month'?'months':rule.dateUnit==='quarter'?'quarters':'years',startDate:start,endDate:end,groupInterval:1}
  groups=[`<${start}`,...groups,`>${end}`]
  rawItems=unique.map((source,index)=>({type:'d',value:dates[index]!,source}))
 }
 const labels=new Set(groups)
 if(values.some(value=>!labels.has(groupLabel(rule,value))))return privateMode('分组标签与标准范围成员不一致，保留兼容分组。')
 return {standard:{fieldIndex,groupItems:groups,rawItems,range},persistence:{fieldIndex,mode:'standard'}}
}
