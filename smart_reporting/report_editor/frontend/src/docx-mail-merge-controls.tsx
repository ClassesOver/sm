import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import type {Editor} from '@tiptap/core'
import type {createNativeApi} from './native-api'
import type {NativeDraft} from './native-draft'
import type {DocxAnchor} from './docx-operations'
import {commitDocxNativeOperations} from './docx-native-history'
import {mailMergeOperation,uploadDocxMailMergeSource,type MailMergeSource} from './docx-mail-merge'
import {DocxMailMergePanel} from './docx-mail-merge-panel'
import './docx-mail-merge.css'

export function createDocxMailMergeControls(options:{editor:Editor;host:HTMLElement;api:ReturnType<typeof createNativeApi>;draft:NativeDraft;anchors:DocxAnchor[];reason:()=>string|null;onSave:()=>void;onError:(error:unknown)=>void}){
 const {editor,host,draft}=options
 let source:MailMergeSource|null=null,root:ReturnType<typeof createRoot>|undefined,container:HTMLElement|undefined,target:{anchor:DocxAnchor;offset:number}|undefined,opener:HTMLElement|undefined
 const close=()=>{root?.unmount();container?.remove();root=undefined;container=undefined;if(opener?.isConnected)opener.focus();else if(!editor.isDestroyed)editor.view.focus()}
 const lock=()=>options.reason()??(draft.operations.length?'请先保存或撤销当前草稿，再执行邮件合并':null)
 const render=()=>{if(!root)return;flushSync(()=>root!.render(<DocxMailMergePanel editor={editor} source={source} reason={lock} onClose={close} onPickSource={()=>{
   const input=document.createElement('input');input.type='file';input.accept='.csv,text/csv';input.onchange=()=>{const file=input.files?.[0];if(file)void uploadDocxMailMergeSource(options.api,file).then(value=>{source=value;render()}).catch(options.onError)};input.click()
 }} onInsertField={name=>{if(!target)throw new Error('请先把光标放在普通正文段落内');commitDocxNativeOperations(editor,[{kind:'insertMailMergeField',documentSha256:draft.identity.sourceSha256,docxIndex:target.anchor.docxIndex,expectedObjectSha256:target.anchor.expectedObjectSha256,offset:target.offset,name}])}} onMerge={()=>{if(!source)throw new Error('请先选择收件人');commitDocxNativeOperations(editor,[mailMergeOperation(source,draft.identity.sourceSha256)]);close();options.onSave()}}/>))}
 const open=()=>{try{const blocked=options.reason();if(blocked)throw new Error(blocked);opener=document.activeElement instanceof HTMLElement?document.activeElement:undefined;const {$from,$to}=editor.state.selection;target=undefined
   if(editor.state.selection.empty&&$from.sameParent($to)&&$from.depth===1){const anchor=options.anchors.find(item=>item.docxIndex===$from.parent.attrs.docxIndex);if(anchor?.editable)target={anchor,offset:$from.parentOffset}}
   if(!root){container=document.createElement('div');host.append(container);root=createRoot(container)}render()
 }catch(error){options.onError(error)}}
 return {open,dispose:close}
}
