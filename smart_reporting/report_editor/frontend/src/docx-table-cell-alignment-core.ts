import type {Node as PmNode} from '@tiptap/pm/model'
import {TableMap} from '@tiptap/pm/tables'
export {Schema} from '@tiptap/pm/model'
import {alignAttrFor,effectiveBidi} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/direction'
export type TableCellAlignmentStep={top:number;left:number;bottom:number;right:number;vertical:'top'|'center'|'bottom';horizontal:'left'|'center'|'right'}
export interface CellAlignmentParagraph {type:string;align:string|null;bidi:boolean;bidiInherited:boolean;bidiInferred:boolean}
const fail=():never=>{throw new Error('docx_table_cell_alignment_invalid')}
const positive=(n:unknown):n is number=>Number.isSafeInteger(n)&&Number(n)>0
export function tableCellAlignmentState(table:PmNode){
 const alignments:('center'|'bottom'|null)[]=[],paragraphs:CellAlignmentParagraph[][]=[]
 table.forEach(row=>row.forEach(cell=>{if(![null,undefined,'top','center','bottom'].includes(cell.attrs.vAlign))fail();alignments.push(cell.attrs.vAlign==='center'||cell.attrs.vAlign==='bottom'?cell.attrs.vAlign:null);const paras:CellAlignmentParagraph[]=[];cell.forEach(p=>{if(['docParagraph','docListItem','docHeading'].includes(p.type.name))paras.push({type:p.type.name,align:p.attrs.align??null,bidi:p.attrs.bidi===true,bidiInherited:p.attrs.bidiInherited===true,bidiInferred:p.attrs.bidiInferred===true})});paragraphs.push(paras)}))
 return{alignments,paragraphs}
}
/** Source f8c17004 table-ops.ts setCellAlignment/selectedCells等效纯投影。
 * 文件SHA d47b69d719287f3126b97bb157b548451a234102351f95ddcfd6af3d44a5adbd。
 * 复用vendor direction闭包，严格宿主校验；仅直属paragraph/list，保留heading/atoms/tcPrEdited。
 */
export function applyTableCellAlignmentSteps(table:PmNode,steps:readonly TableCellAlignmentStep[]){
 if(table.type.spec.tableRole!=='table'||!table.childCount||table.childCount>100||!Array.isArray(steps)||!steps.length||steps.length>50)fail()
 table.check();let count=0
 table.forEach(row=>{if(row.type.spec.tableRole!=='row'||row.childCount>30)fail();row.forEach(cell=>{if(!positive(cell.attrs.colspan)||cell.attrs.colspan>30||!positive(cell.attrs.rowspan)||cell.attrs.rowspan>100||cell.attrs.gridGap||++count>1000)fail()})})
 const map=TableMap.get(table)
 if(map.problems?.length||map.width<1||map.width>30||map.height*map.width>1000)fail()
 const changes=new Map<number,TableCellAlignmentStep>()
 for(const step of steps){
  if(!step||typeof step!=='object'||Array.isArray(step)||Object.keys(step).length!==6||Object.keys(step).some(k=>!['top','left','bottom','right','vertical','horizontal'].includes(k))||![step.top,step.left,step.bottom,step.right].every(Number.isSafeInteger)||step.top<0||step.left<0||step.bottom<=step.top||step.right<=step.left||step.bottom>map.height||step.right>map.width||!['top','center','bottom'].includes(step.vertical)||!['left','center','right'].includes(step.horizontal))fail()
  for(let r=step.top;r<step.bottom;r++)for(let c=step.left;c<step.right;c++)changes.set(map.map[r*map.width+c],step)
 }
 const rows:PmNode[]=[]
 table.forEach((row,rowOffset)=>{const cells:PmNode[]=[];row.forEach((cell,offset)=>{
  const step=changes.get(rowOffset+1+offset)
  if(!step){cells.push(cell);return}
  const children:PmNode[]=[]
  cell.forEach(child=>{if(child.type.name==='docParagraph'||child.type.name==='docListItem')children.push(child.type.create({...child.attrs,align:alignAttrFor(step.horizontal,effectiveBidi(child.attrs))},child.content,child.marks));else children.push(child)})
  cells.push(cell.type.create({...cell.attrs,vAlign:step.vertical==='top'?null:step.vertical},children,cell.marks))
 });rows.push(row.type.create(row.attrs,cells,row.marks))})
 const result=table.type.create(table.attrs,rows,table.marks)
 return {table:result,...tableCellAlignmentState(result)}
}
