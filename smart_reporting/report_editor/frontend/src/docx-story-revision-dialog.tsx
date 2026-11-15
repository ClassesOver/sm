import {useState} from 'react'
import {storyRevisionDraft,storyRevisionItems,type DocxStoryRevisionDraft,type DocxStoryRevisionTarget} from './docx-story-revisions'
export interface DocxStoryRevisionDialogProps {
 embedded?:boolean
 targets:readonly DocxStoryRevisionTarget[];drafts?:readonly DocxStoryRevisionDraft[]
 readOnly?:readonly {partPath:string;noteId?:string;reason:string}[]
 onApply:(drafts:DocxStoryRevisionDraft[])=>void;onClose:()=>void
}
/** Pure draft UI; the native host owns history and the actual save. */
export function DocxStoryRevisionDialog({embedded=false,targets,drafts=[],readOnly=[],onApply,onClose}:DocxStoryRevisionDialogProps){
 const [pending,setPending]=useState<DocxStoryRevisionDraft[]>(()=>[...drafts])
 const items=storyRevisionItems(targets,pending)
 const decide=(target:DocxStoryRevisionTarget,action:'accept'|'reject')=>setPending(current=>[...current.filter(d=>d.targetId!==target.targetId),storyRevisionDraft(target,action)])
 return <div role={embedded?undefined:"dialog"} aria-modal={embedded?undefined:true} aria-label={embedded?undefined:"非正文修订审阅"} className="docx-dialog">
  <h2>非正文修订审阅</h2><p>脚注、尾注、页眉和页脚的插入与删除。保存后写入 Word 文件。</p>
  {!items.length&&<p>没有可处理的非正文插入或删除修订。</p>}
  <ul>{items.map(item=><li key={item.targetId}>
   <p><strong>{item.location}</strong> · {item.author||'未知作者'} · {item.type==='insertion'?'插入':'删除'}</p><p>{item.text||'非文本内容'}</p>
   <button type="button" aria-pressed={item.pendingAction==='accept'} onClick={()=>decide(item,'accept')}>接受</button>
   <button type="button" aria-pressed={item.pendingAction==='reject'} onClick={()=>decide(item,'reject')}>拒绝</button>
   {item.pendingAction&&<span role="status">{item.pendingAction==='accept'?'待接受':'待拒绝'}</span>}
  </li>)}</ul>
  {readOnly.length>0&&<details><summary>保留原样的其他修订（{readOnly.length}）</summary><ul>{readOnly.map((entry,i)=><li key={i}>{entry.partPath}{entry.noteId?` · ${entry.noteId}`:''}：{entry.reason}</li>)}</ul></details>}
  <button type="button" onClick={onClose}>取消</button><button type="button" disabled={!pending.length} onClick={()=>onApply(pending)}>应用到草稿</button>
 </div>
}
