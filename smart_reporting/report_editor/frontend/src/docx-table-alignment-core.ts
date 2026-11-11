import type {Node as PmNode} from '@tiptap/pm/model'
import {TableMap} from '@tiptap/pm/tables'
export type TableAlignment='left'|'center'|'right'
export type TableAlignmentDisplayIndents=Record<TableAlignment,number|null>
export interface TableAlignmentSource {alignment:'center'|'right'|null;raw:string|null;rawIndent:string|null;rawWidth:string|null;bidiVisual:boolean;positioning:'inline'|'floating';cells:{top:number;left:number;bottom:number;right:number}[]}
export function tableAlignmentState(table:PmNode){
 if(table.type.spec.tableRole!=='table'||!table.childCount||table.childCount>100||![null,undefined,'center','right','left'].includes(table.attrs.tblAlign))throw new Error('docx_table_alignment_invalid')
 table.check();let count=0
 table.forEach(row=>{if(row.type.spec.tableRole!=='row'||row.childCount>30)throw new Error('docx_table_alignment_invalid');row.forEach(cell=>{if(!Number.isSafeInteger(cell.attrs.colspan)||cell.attrs.colspan<1||!Number.isSafeInteger(cell.attrs.rowspan)||cell.attrs.rowspan<1||cell.attrs.gridGap||++count>1000)throw new Error('docx_table_alignment_invalid')})})
 const map=TableMap.get(table);if(map.problems?.length||map.width<1||map.width>30||map.width*map.height>1000)throw new Error('docx_table_alignment_invalid')
 const cells:TableAlignmentSource['cells']=[];table.forEach((row,offset)=>row.forEach((_cell,at)=>{const{top,left,bottom,right}=map.findCell(offset+1+at);cells.push({top,left,bottom,right})}))
 return{cells,alignment:table.attrs.tblAlign??null}
}
export function applyTableAlignment(table:PmNode,alignment:TableAlignment,displayIndents?:TableAlignmentDisplayIndents):PmNode{
 if(!['left','center','right'].includes(alignment))throw new Error('docx_table_alignment_invalid')
 tableAlignmentState(table)
 return table.type.create({...table.attrs,tblAlign:alignment==='left'?null:alignment,...(displayIndents?{indentTwips:displayIndents[alignment]}:{})},table.content,table.marks)
}
