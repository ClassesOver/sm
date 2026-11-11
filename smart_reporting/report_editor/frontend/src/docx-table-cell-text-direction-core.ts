import type {Node as PmNode} from '@tiptap/pm/model'
import {TableMap} from '@tiptap/pm/tables'
export {Schema} from '@tiptap/pm/model'
export type TableCellTextDirectionStep={top:number;left:number;bottom:number;right:number;direction:'lrTb'|'tbRl'|'btLr'}
const fail=():never=>{throw new Error('docx_table_cell_text_direction_invalid')}
const positive=(n:unknown):n is number=>Number.isSafeInteger(n)&&Number(n)>0
/** GenOffice f8c17004 table-ops.ts selectedCells/setCellTextDirection/setCellProps等效纯投影。
 * SHA256 d47b69d719287f3126b97bb157b548451a234102351f95ddcfd6af3d44a5adbd。
 * 来源按rect网格slot去重owner；宿主新增严格输入和TableMap原子校验，不改内容/几何。
 */
export function applyTableCellTextDirectionSteps(table:PmNode,steps:readonly TableCellTextDirectionStep[]){
 if(table.type.spec.tableRole!=='table'||!table.childCount||table.childCount>100||!Array.isArray(steps)||!steps.length||steps.length>50)fail()
 table.check();let count=0
 table.forEach(row=>{if(row.type.spec.tableRole!=='row'||row.childCount>30)fail();row.forEach(cell=>{if(!positive(cell.attrs.colspan)||cell.attrs.colspan>30||!positive(cell.attrs.rowspan)||cell.attrs.rowspan>100||cell.attrs.gridGap||++count>1000||![null,undefined,'tbRl','btLr'].includes(cell.attrs.textDirection))fail()})})
 const map=TableMap.get(table)
 if(map.problems?.length||map.width<1||map.width>30||map.height*map.width>1000)fail()
 const changes=new Map<number,'tbRl'|'btLr'|null>()
 for(const step of steps){
  if(!step||typeof step!=='object'||Array.isArray(step)||Object.keys(step).length!==5||Object.keys(step).some(k=>!['top','left','bottom','right','direction'].includes(k))||![step.top,step.left,step.bottom,step.right].every(Number.isSafeInteger)||step.top<0||step.left<0||step.bottom<=step.top||step.right<=step.left||step.bottom>map.height||step.right>map.width||!['lrTb','tbRl','btLr'].includes(step.direction))fail()
  for(let r=step.top;r<step.bottom;r++)for(let c=step.left;c<step.right;c++)changes.set(map.map[r*map.width+c],step.direction==='lrTb'?null:step.direction)
 }
 const rows:PmNode[]=[],directions:('tbRl'|'btLr'|null)[]=[]
 table.forEach((row,rowOffset)=>{const cells:PmNode[]=[];row.forEach((cell,offset)=>{const pos=rowOffset+1+offset,direction=changes.has(pos)?changes.get(pos)!:cell.attrs.textDirection??null;directions.push(direction);cells.push(changes.has(pos)?cell.type.create({...cell.attrs,textDirection:direction,tcPrEdited:true},cell.content,cell.marks):cell)});rows.push(row.type.create(row.attrs,cells,row.marks))})
 return{table:table.type.create(table.attrs,rows,table.marks),directions}
}
