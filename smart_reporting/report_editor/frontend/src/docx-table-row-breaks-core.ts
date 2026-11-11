import type {Node as PmNode} from '@tiptap/pm/model'
import {TableMap} from '@tiptap/pm/tables'
export type TableRowBreakStep={top:number;bottom:number;allowBreak:boolean}
export interface TableRowBreakCell {top:number;left:number;bottom:number;right:number}
export interface TableRowBreakSource {cells:TableRowBreakCell[];rows:{cantSplit:boolean;raw:string|null}[]}
function fail():never{throw new Error('docx_table_row_breaks_invalid')}
export function replayTableRowBreakSteps(flags:readonly boolean[],value:unknown){
 if(!Array.isArray(flags)||!flags.length||flags.length>100||flags.some(v=>typeof v!=='boolean')||!Array.isArray(value)||!value.length||value.length>50)fail()
 const cantSplit=[...flags],touched=flags.map(()=>false)
 const steps:TableRowBreakStep[]=value.map(step=>{if(!step||typeof step!=='object'||Array.isArray(step)||Object.keys(step).length!==3||Object.keys(step).some(k=>!['top','bottom','allowBreak'].includes(k))||!Number.isSafeInteger(step.top)||!Number.isSafeInteger(step.bottom)||step.top<0||step.top>=step.bottom||step.bottom>flags.length||typeof step.allowBreak!=='boolean')fail();return{top:step.top,bottom:step.bottom,allowBreak:step.allowBreak}})
 for(const step of steps)for(let r=step.top;r<step.bottom;r++){cantSplit[r]=!step.allowBreak;touched[r]=true}
 return{cantSplit,touched,steps}
}
export function tableRowBreakState(table:PmNode){
 if(table.type.spec.tableRole!=='table'||!table.childCount||table.childCount>100)fail()
 table.check();let count=0
 table.forEach(row=>{if(row.type.spec.tableRole!=='row'||row.childCount>30||typeof row.attrs.cantSplit!=='boolean')fail();row.forEach(cell=>{if(!Number.isSafeInteger(cell.attrs.colspan)||cell.attrs.colspan<1||cell.attrs.colspan>30||!Number.isSafeInteger(cell.attrs.rowspan)||cell.attrs.rowspan<1||cell.attrs.rowspan>100||cell.attrs.gridGap||++count>1000)fail()})})
 const map=TableMap.get(table);if(map.problems?.length||map.width<1||map.width>30||map.width*map.height>1000)fail()
 const cells:TableRowBreakCell[]=[],cantSplit:boolean[]=[]
 table.forEach((row,offset)=>{cantSplit.push(row.attrs.cantSplit);row.forEach((_cell,at)=>{const{top,left,bottom,right}=map.findCell(offset+1+at);cells.push({top,left,bottom,right})})})
 return{cells,cantSplit}
}
/** 固定来源rowPatchFor/setRowProps：selectedRect行带整行修改，保持所有格与段落。 */
export function applyTableRowBreakSteps(table:PmNode,steps:readonly TableRowBreakStep[]){
 const state=tableRowBreakState(table),result=replayTableRowBreakSteps(state.cantSplit,steps),rows:PmNode[]=[]
 table.forEach((row,_offset,r)=>rows.push(result.touched[r]?row.type.create({...row.attrs,cantSplit:result.cantSplit[r],cantSplitEdited:true},row.content,row.marks):row))
 return{...result,table:table.type.create(table.attrs,rows,table.marks)}
}
