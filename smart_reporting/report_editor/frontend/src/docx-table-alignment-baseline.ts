import {blocksToPmDoc} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import type {TableAlignment,TableAlignmentDisplayIndents} from './docx-table-alignment-core'
/** 可信 parser 基线派生的显示值；复用导入器处理 legacy 缩进、继承边距及浮动，不进入请求协议。 */
export function withDocxTableAlignmentDisplayIndents<T extends {docxIndex:number}>(anchors:T[],blocks:Parameters<typeof blocksToPmDoc>[0],sections:Parameters<typeof blocksToPmDoc>[1],options:Parameters<typeof blocksToPmDoc>[2]):(T&{tableAlignmentDisplayIndents?:TableAlignmentDisplayIndents})[]{
 const values=new Map<number,TableAlignmentDisplayIndents>()
 for(const alignment of ['left','center','right'] as const){
  const variants=blocks.map(block=>block.type==='table'&&block.table?{...block,table:{...block.table,align:alignment==='left'?undefined:alignment}}:block)
  const doc=blocksToPmDoc(variants,sections,options)
  for(const table of doc.content??[]){
   if(table.type!=='docTable'||typeof table.attrs?.docxIndex!=='number')continue
   const index=table.attrs.docxIndex,indent=table.attrs.indentTwips
   if(indent!==null&&(typeof indent!=='number'||!Number.isFinite(indent)))throw new Error('docx_table_alignment_display_indent_invalid')
   const value=values.get(index)??{left:null,center:null,right:null};value[alignment as TableAlignment]=indent;values.set(index,value)
  }
 }
 return anchors.map(anchor=>({...anchor,...(values.has(anchor.docxIndex)?{tableAlignmentDisplayIndents:values.get(anchor.docxIndex)!}:{})}))
}
