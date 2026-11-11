import type {Node as PmNode} from '@tiptap/pm/model'
import {TableMap} from '@tiptap/pm/tables'
export type TableCellWrapStep={top:number;left:number;bottom:number;right:number;wrap:boolean}
export interface TableCellWrapCell {top:number;left:number;bottom:number;right:number;rawPresent:boolean;hasPhysicalNoWrap:boolean;raw:string|null;noWrap:boolean;resetNoWrap:false}
export interface TableCellWrapSource {cells:TableCellWrapCell[]}
function fail():never{throw new Error('docx_table_cell_wrap_invalid')}
const equal=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b)
export function normalizeTableCellWrapSteps(value:unknown,width:number,height:number):TableCellWrapStep[]{
 if(!Array.isArray(value)||!value.length||value.length>50)fail()
 return value.map(step=>{
  if(!step||typeof step!=='object'||Array.isArray(step)||Object.keys(step).length!==5||Object.keys(step).some(k=>!['top','left','bottom','right','wrap'].includes(k))||![step.top,step.left,step.bottom,step.right].every(Number.isSafeInteger)||step.top<0||step.left<0||step.top>=step.bottom||step.left>=step.right||step.bottom>height||step.right>width||typeof step.wrap!=='boolean')fail()
  return{top:step.top,left:step.left,bottom:step.bottom,right:step.right,wrap:step.wrap}
 })
}
export function replayTableCellWrapSteps(source:TableCellWrapSource,value:unknown){
 if(!source||!Array.isArray(source.cells)||!source.cells.length||source.cells.length>1000)fail()
 const cells=source.cells.map(c=>{
  if(!c||![c.top,c.left,c.bottom,c.right].every(Number.isSafeInteger)||c.top<0||c.left<0||c.bottom<=c.top||c.right<=c.left||c.bottom>100||c.right>30||typeof c.rawPresent!=='boolean'||c.rawPresent&&!c.hasPhysicalNoWrap)fail()
  if(c.resetNoWrap!==false||typeof c.noWrap!=='boolean'||typeof c.hasPhysicalNoWrap!=='boolean'||(c.rawPresent?typeof c.raw!=='string':c.raw!==null)||!c.rawPresent&&c.noWrap)fail()
  return{...c}
 })
 const width=Math.max(...cells.map(c=>c.right)),height=Math.max(...cells.map(c=>c.bottom))
 if(width*height>1000)fail()
 const slots=Array<number>(width*height).fill(-1)
 cells.forEach((c,i)=>{for(let r=c.top;r<c.bottom;r++)for(let col=c.left;col<c.right;col++){const at=r*width+col;if(slots[at]!==-1)fail();slots[at]=i}})
 if(slots.includes(-1))fail()
 const steps=normalizeTableCellWrapSteps(value,width,height),noWrap=cells.map(c=>c.noWrap),touched=cells.map(()=>false)
 for(const s of steps){const owners=new Set<number>();for(let r=s.top;r<s.bottom;r++)for(let c=s.left;c<s.right;c++)owners.add(slots[r*width+c]);for(const i of owners){noWrap[i]=!s.wrap;touched[i]=true}}
 return{cells,steps,noWrap,touched,width,height}
}
export function applyTableCellWrapSteps(table:PmNode,steps:readonly TableCellWrapStep[],source:TableCellWrapSource){
 const result=replayTableCellWrapSteps(source,steps)
 if(table.type.spec.tableRole!=='table'||table.childCount!==result.height)fail()
 table.check();const map=TableMap.get(table)
 if(map.problems?.length||map.width!==result.width||map.height!==result.height)fail()
 let i=0;const rows:PmNode[]=[]
 table.forEach((row,rowOffset)=>{if(row.type.spec.tableRole!=='row')fail();const children:PmNode[]=[];row.forEach((cell,cellOffset)=>{const c=result.cells[i],rect=map.findCell(rowOffset+1+cellOffset);if(!c||cell.attrs.gridGap||!equal(rect,{left:c.left,top:c.top,right:c.right,bottom:c.bottom}))fail();children.push(result.touched[i]?cell.type.create({...cell.attrs,noWrap:result.noWrap[i]?true:null},cell.content,cell.marks):cell);i++});rows.push(row.type.create(row.attrs,children,row.marks))})
 if(i!==result.cells.length)fail()
 return{...result,table:table.type.create(table.attrs,rows,table.marks)}
}
