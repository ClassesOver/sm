import type {Schema} from '@tiptap/pm/model'
import type {DocxPmNode} from './docx-operations'
import {normalizeTableAltText,type TableAltText,type TableAltTextSource} from './docx-table-alt-text-core'
export interface DocxTableAltTextAnchor {tableAltTextEditable?:boolean;tableAltTextReadOnlyReason?:string|null;tableAltTextSource?:TableAltTextSource}
export function projectDocxTableAltText(source:DocxPmNode,anchor:DocxTableAltTextAnchor,value:TableAltText,schema?:Schema):DocxPmNode{
 const baseline=anchor.tableAltTextSource
 if(!schema||source.type!=='docTable'||!anchor.tableAltTextEditable||!baseline)throw new Error(anchor.tableAltTextReadOnlyReason??'当前来源表格不支持修改替代文字')
 if(Object.entries(source.attrs??{}).some(([key,v])=>key.startsWith('nativeTable')&&key!=='nativeTableAltText'&&v)||source.attrs?.tblAltEdited||source.attrs?.cellMarEdited)throw new Error('替代文字不能与同表其他修改混用，请先保存')
 if(typeof baseline.title!=='string'||typeof baseline.description!=='string'||[baseline.rawTitle,baseline.rawDescription].some(v=>v!==null&&typeof v!=='string'))throw new Error('替代文字来源无效')
 const pending=source.attrs?.nativeTableAltText,expected=pending?normalizeTableAltText(pending):baseline
 if((source.attrs?.tblCaption??'')!==expected.title||(source.attrs?.tblDescription??'')!==expected.description)throw new Error('替代文字来源与当前文件不一致')
 const next=normalizeTableAltText(value),table=schema.nodeFromJSON(source),json=table.type.create({...table.attrs,tblCaption:next.title||null,tblDescription:next.description||null,nativeTableAltText:next},table.content,table.marks).toJSON() as DocxPmNode
 return schema.nodeFromJSON(json).toJSON() as DocxPmNode
}
