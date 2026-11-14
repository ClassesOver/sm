// Adapted from GenOffice MailMergePanel.tsx, Apache-2.0, fixed source f8c17004.
import {useMemo,useState} from 'react'
import type {Editor} from '@tiptap/core'
import {documentText,substituteMergeFields} from './docx-mail-merge-template'
import {useModalKeys} from './vendor/genoffice-docs/apps/docs/src/renderer/components/modal-keys'
import type {MailMergeSource} from './docx-mail-merge'
import type {DocxPmNode} from './docx-operations'

export function mailMergePreview(doc:DocxPmNode,record:Record<string,string>):string{
 return documentText(substituteMergeFields(doc,record))
}
export function DocxMailMergePanel({editor,source,onPickSource,onInsertField,onMerge,onClose,reason}:{editor:Editor;source:MailMergeSource|null;onPickSource:()=>void;onInsertField:(name:string)=>void;onMerge:()=>void;onClose:()=>void;reason:()=>string|null}){
 const modalKeys=useModalKeys(onClose),[recordIndex,setRecordIndex]=useState(0),[error,setError]=useState('')
 const records=source?.records??[],record=records[Math.min(recordIndex,Math.max(0,records.length-1))]
 const preview=useMemo(()=>record?mailMergePreview(editor.getJSON(),record):'',[editor,record])
 const run=(action:()=>void)=>{try{const blocked=reason();if(blocked)throw new Error(blocked);action();setError('')}catch(err){setError(err instanceof Error?err.message:String(err))}}
 return <div className="modal-backdrop" ref={modalKeys.ref} onKeyDown={modalKeys.onKeyDown} onMouseDown={event=>event.target===event.currentTarget&&onClose()}><div className="modal modal-mailmerge" role="dialog" aria-modal="true" aria-label="邮件合并">
  <h2>邮件合并</h2>
  <div className="mailmerge-section"><div className="mailmerge-label">收件人来源</div><div className="modal-row"><span className="mailmerge-source-name">{source?.name??'尚未选择收件人'}</span><button onClick={onPickSource}>选择收件人 CSV</button></div><div className="mailmerge-note">UTF-8 CSV；导入记录仅用于邮件合并，不作为受控业务事实。</div></div>
  <div className="mailmerge-section"><div className="mailmerge-label">合并字段</div>{source?<div className="mailmerge-fields">{source.fields.map(name=><button key={name} className="mailmerge-field" title="插入当前光标所在正文段落；保存后生效" onMouseDown={event=>event.preventDefault()} onClick={()=>run(()=>{onInsertField(name);onClose()})}>{name}</button>)}</div>:<div className="mailmerge-empty">选择来源后显示字段</div>}<div className="mailmerge-note">字段插入进入草稿，可撤销；请保存并打开新修订后继续合并。当前支持普通 MERGEFIELD；IF、NEXT、SKIPIF、嵌套域及跨段域模板尚未开放。</div></div>
  {source&&records.length>0&&<><div className="mailmerge-section"><div className="mailmerge-label">预览结果</div><div className="modal-row"><button disabled={recordIndex<=0} onClick={()=>setRecordIndex(recordIndex-1)}>上一条</button><span className="mailmerge-counter">第 {recordIndex+1} 条 / 共 {records.length} 条</span><button disabled={recordIndex>=records.length-1} onClick={()=>setRecordIndex(recordIndex+1)}>下一条</button></div><pre className="mailmerge-preview">{preview}</pre></div>
  <div className="mailmerge-section"><div className="mailmerge-label">输出</div><div className="modal-row"><label className="mailmerge-radio"><input type="radio" checked readOnly/>单一文档，每条记录另起一页</label><label className="mailmerge-radio" title="本批未开放"><input type="radio" disabled/>每条记录一个文件</label></div><div className="modal-row"><label className="mailmerge-radio"><input type="radio" disabled/>标签（未开放）</label><label className="mailmerge-radio"><input type="radio" disabled/>信封（未开放）</label></div><div className="modal-row"><button className="btn-primary" onClick={()=>run(onMerge)}>合并并另存为新修订</button></div></div></>}
  {error&&<div className="modal-error" role="alert">{error}</div>}<div className="modal-actions"><button onClick={onClose}>关闭</button></div>
 </div></div>
}
