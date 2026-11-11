import type {Node as PmNode} from '@tiptap/pm/model'
import {TableMap} from '@tiptap/pm/tables'
import {normalizeTableCellMargins,type TableCellMargins,type PartialTableCellMargins} from './docx-table-cell-margins-core'
export type TableCellMarginOverrideStep={top:number;left:number;bottom:number;right:number;margins:TableCellMargins|null}
export interface TableCellMarginOverrideCell {top:number;left:number;bottom:number;right:number;rawPresent:boolean;hasPhysicalOverrides:boolean;raw:PartialTableCellMargins|null;effective:PartialTableCellMargins|null;resetEffective:PartialTableCellMargins|null}
export interface TableCellMarginOverridesSource {cells:TableCellMarginOverrideCell[]}
function fail():never{throw new Error('docx_table_cell_margin_overrides_invalid')}
const equal=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b)
export function normalizeTableCellMarginOverrideSteps(value:unknown,width:number,height:number):TableCellMarginOverrideStep[]{
 if(!Array.isArray(value)||!value.length||value.length>50)fail()
 return value.map(step=>{
  if(!step||typeof step!=='object'||Array.isArray(step)||Object.keys(step).length!==5||Object.keys(step).some(k=>!['top','left','bottom','right','margins'].includes(k))||![step.top,step.left,step.bottom,step.right].every(Number.isSafeInteger)||step.top<0||step.left<0||step.top>=step.bottom||step.left>=step.right||step.bottom>height||step.right>width||step.margins===undefined)fail()
  return{top:step.top,left:step.left,bottom:step.bottom,right:step.right,margins:step.margins===null?null:normalizeTableCellMargins(step.margins,true) as TableCellMargins}
 })
}
export function replayTableCellMarginOverrides(source:TableCellMarginOverridesSource,value:unknown){
 if(!source||!Array.isArray(source.cells)||!source.cells.length||source.cells.length>1000)fail()
 const cells=source.cells.map(c=>{
  if(!c||![c.top,c.left,c.bottom,c.right].every(Number.isSafeInteger)||c.top<0||c.left<0||c.bottom<=c.top||c.right<=c.left||c.bottom>100||c.right>30||typeof c.rawPresent!=='boolean'||typeof c.hasPhysicalOverrides!=='boolean'||c.rawPresent&&!c.hasPhysicalOverrides||[c.raw,c.effective,c.resetEffective].some(m=>m===undefined))fail()
  const raw=normalizeTableCellMargins(c.raw),effective=normalizeTableCellMargins(c.effective),resetEffective=normalizeTableCellMargins(c.resetEffective)
  if(!c.rawPresent&&raw)fail()
  return{...c,raw,effective,resetEffective}
 })
 const width=Math.max(...cells.map(c=>c.right)),height=Math.max(...cells.map(c=>c.bottom))
 if(width*height>1000)fail()
 const slots=Array<number>(width*height).fill(-1)
 cells.forEach((c,i)=>{for(let r=c.top;r<c.bottom;r++)for(let col=c.left;col<c.right;col++){const at=r*width+col;if(slots[at]!==-1)fail();slots[at]=i}})
 if(slots.includes(-1))fail()
 const steps=normalizeTableCellMarginOverrideSteps(value,width,height),margins=cells.map(c=>c.effective),raw=cells.map(c=>c.raw),rawPresent=cells.map(c=>c.rawPresent),hasPhysicalOverrides=cells.map(c=>c.hasPhysicalOverrides),touched=cells.map(()=>false)
 for(const s of steps){const owners=new Set<number>();for(let r=s.top;r<s.bottom;r++)for(let c=s.left;c<s.right;c++)owners.add(slots[r*width+c]);for(const i of owners){margins[i]=s.margins??cells[i].resetEffective;raw[i]=s.margins;rawPresent[i]=s.margins!==null;hasPhysicalOverrides[i]=s.margins!==null;touched[i]=true}}
 return{cells,steps,margins,raw,rawPresent,hasPhysicalOverrides,touched,width,height}
}
/** 来源selectedCells的owner去重语义；继承值由服务端真实parser签发，不由客户端猜测。 */
export function applyTableCellMarginOverrideSteps(table:PmNode,steps:readonly TableCellMarginOverrideStep[],source:TableCellMarginOverridesSource){
 const result=replayTableCellMarginOverrides(source,steps)
 if(table.type.spec.tableRole!=='table'||table.childCount!==result.height)fail()
 table.check();const map=TableMap.get(table)
 if(map.problems?.length||map.width!==result.width||map.height!==result.height)fail()
 let i=0;const rows:PmNode[]=[]
 table.forEach((row,rowOffset)=>{if(row.type.spec.tableRole!=='row')fail();const children:PmNode[]=[];row.forEach((cell,cellOffset)=>{const c=result.cells[i],rect=map.findCell(rowOffset+1+cellOffset);if(!c||cell.attrs.gridGap||!equal(rect,{left:c.left,top:c.top,right:c.right,bottom:c.bottom}))fail();children.push(result.touched[i]?cell.type.create({...cell.attrs,cellMar:result.margins[i]},cell.content,cell.marks):cell);i++});rows.push(row.type.create(row.attrs,children,row.marks))})
 if(i!==result.cells.length)fail()
 return{...result,table:table.type.create(table.attrs,rows,table.marks)}
}
