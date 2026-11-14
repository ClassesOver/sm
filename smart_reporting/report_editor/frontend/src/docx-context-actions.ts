/** Native command bindings for the fixed-source document context menu. */
import type {Editor} from '@tiptap/core'
import {NodeSelection} from '@tiptap/pm/state'
import type {DocxAnchor} from './docx-operations'
import {safeDocxLink} from './docx-operations'
import type {DocxTableCommands} from './docx-tables'
import {docxClipboardCopy,docxClipboardCut,docxClipboardPaste} from './docx-clipboard'
import {openDocxFontDialog,docxFontDialogUnavailable} from './docx-font-dialog'
import {openDocxParagraphDialog,docxParagraphDialogUnavailable} from './docx-paragraph-dialog'
import {docxLinkSelection,applyDocxLink,linkSelectionUnavailable} from './docx-links'
import {openDocxLinkDialog} from './docx-link-dialog'
import {createDocxNumberingValueControl} from './docx-numbering-value-host'
import {docxNumberingValueTarget,setDocxNumberingValue} from './docx-custom-list'
import {createModal} from './modal'
import type {DocxContextMenuActions,DocxContextMenuAction,DocxContextMenuTarget} from './docx-context-menu'
import type {createDocxFieldControls} from './docx-field-controls'

export function createDocxContextActions(options:{editor:Editor;root:HTMLElement;anchors:DocxAnchor[];onError:(error:unknown)=>void;tables?:DocxTableCommands;fields?:ReturnType<typeof createDocxFieldControls>;prepare?:(run:()=>void)=>Promise<void>;extra?:DocxContextMenuActions}){
 const {editor,root,anchors}=options
 let closeDialog:(()=>void)|undefined
 const numbering=createDocxNumberingValueControl(editor,true,anchors,options.onError)
 const close=()=>{closeDialog?.();closeDialog=undefined}
 const linkTarget=()=>{const value=docxLinkSelection(editor,anchors);if(!value)throw Error(linkSelectionUnavailable);return value}
 const linkReason=()=>docxLinkSelection(editor,anchors)?null:linkSelectionUnavailable
 const openLinkDialog=()=>{const selected=linkTarget(),doc=editor.state.doc,selection=editor.state.selection;close();const dialog=openDocxLinkDialog(root,selected.href??'https://',{unavailable:()=>!editor.isEditable||editor.state.doc!==doc||!editor.state.selection.eq(selection),apply:href=>{if(!applyDocxLink(editor,selected,href))throw Error('超链接未能进入草稿')},onClose:()=>{closeDialog=undefined}});closeDialog=dialog.dispose}
 const image=(t:DocxContextMenuTarget)=>{
  const src=t.imageSrc
  if(!src||!(/^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(src)||src.startsWith('blob:'+location.origin+'/')))throw Error('只支持已载入的本地栅格图片')
  return src
 }
 const imageReason=(t:DocxContextMenuTarget)=>{try{image(t);return null}catch(e){return e instanceof Error?e.message:String(e)}}
 const cutReason=()=>{
  const selection=editor.state.selection
  if(!editor.isEditable)return '当前文档不可剪切'
  if(selection.empty)return '请选择要剪切的内容'
  let reason:string|null=null
  editor.state.doc.nodesBetween(selection.from,selection.to,(node,_pos,parent)=>{
   if(parent!==editor.state.doc)return
   const id=node.attrs.docxIndex,anchor=id==null?undefined:anchors.find(a=>a.docxIndex===id)
   if(selection instanceof NodeSelection){if(id!=null&&(!['docParagraph','docHeading','docListItem'].includes(node.type.name)||!anchor?.editable||anchor.deletable===false))reason='当前原有对象暂不支持剪切';return false}
   if(!['docParagraph','docHeading','docListItem'].includes(node.type.name)||id!=null&&!anchor?.editable)reason='当前选区包含暂不支持剪切的对象'
   return false
  })
  return reason
 }
 const actions:DocxContextMenuActions={
  copy:()=>docxClipboardCopy(editor),cut:{reason:cutReason,run:()=>{const reason=cutReason();if(reason)throw Error(reason);docxClipboardCut(editor)}},paste:()=>docxClipboardPaste(editor),pasteText:()=>docxClipboardPaste(editor,'text'),
  font:{reason:()=>docxFontDialogUnavailable(editor,anchors),run:()=>{close();closeDialog=openDocxFontDialog(root,editor,anchors)}},
  paragraph:{reason:()=>docxParagraphDialogUnavailable(editor,anchors),run:()=>{close();closeDialog=openDocxParagraphDialog(root,editor,anchors)}},
  link:{reason:linkReason,run:openLinkDialog},editLink:{reason:linkReason,run:openLinkDialog},removeLink:{reason:linkReason,run:()=>{if(!applyDocxLink(editor,linkTarget(),null))throw Error('超链接未能移除')}},
  openLink:{reason:t=>{try{safeDocxLink(t.linkHref);return null}catch(e){return e instanceof Error?e.message:String(e)}},run:t=>{const href=safeDocxLink(t.linkHref);window.open(href,'_blank','noopener,noreferrer')}},
  copyLink:async t=>{if(!t.linkHref)throw Error('当前位置没有超链接');if(!navigator.clipboard?.writeText)throw Error('浏览器不支持复制链接，请使用键盘复制');await navigator.clipboard.writeText(t.linkHref)},
  viewImage:{reason:imageReason,run:t=>{const src=image(t);close();const modal=createModal({root,label:'查看图片',cardClass:'docx-settings-dialog',closeLabel:'关闭图片',onRequestClose:()=>close(),content:'<h2>查看图片</h2>'}),img=document.createElement('img');img.src=src;img.alt='文档中的图片';img.tabIndex=0;img.style.cssText='max-width:100%;max-height:75vh;object-fit:contain';modal.card.append(img);closeDialog=modal.remove;modal.open(img)}},
  saveImage:{reason:imageReason,run:t=>{const src=image(t),a=document.createElement('a'),mime=/^data:image\/(png|jpeg|gif|webp);/i.exec(src)?.[1]?.toLowerCase();a.href=src;a.download=mime?'image.'+(mime==='jpeg'?'jpg':mime):'image';root.append(a);a.click();a.remove()}},
  setNumberingValue:{reason:()=>numbering.reason(),run:()=>numbering.open()},
  restartNumbering:{reason:()=>{try{const t=docxNumberingValueTarget(editor,anchors);return t.node.attrs.kind==='ordered'?null:'请选择编号列表'}catch(e){return e instanceof Error?e.message:String(e)}},run:()=>setDocxNumberingValue(editor,anchors,{mode:'restart',value:1})},
  continueNumbering:{reason:()=>{try{const t=docxNumberingValueTarget(editor,anchors);return t.node.attrs.kind!=='ordered'?'请选择编号列表':t.previous?null:'没有可继续的前序列表'}catch(e){return e instanceof Error?e.message:String(e)}},run:()=>setDocxNumberingValue(editor,anchors,{mode:'continue'})},
 }
 if(options.fields){const fields=options.fields,prepare=options.prepare??(async(run:()=>void)=>run());Object.assign(actions,{
  updateFields:{description:'仅更新当前选中的域。',reason:()=>fields.selectionReason(),run:()=>prepare(()=>fields.updateSelected())},
  editField:{reason:()=>fields.selectionReason(),run:()=>prepare(()=>fields.openEdit())},toggleFieldCodes:{reason:(t:DocxContextMenuTarget)=>t.field&&t.from>=t.field.from&&t.from<=t.field.to?null:'请将光标放在域内',run:()=>fields.toggleSelectedCode()},
 })}
 if(options.tables){const table=options.tables,map={insertRowBefore:'table-insert-row-before',insertRowAfter:'table-insert-row-after',insertColumnBefore:'table-insert-column-before',insertColumnAfter:'table-insert-column-after',deleteRow:'table-delete-row',deleteColumn:'table-delete-column',insertCells:'table-insert-cells',deleteCells:'table-delete-cells',deleteTable:'table-delete',splitTable:'table-split-table',selectCell:'table-select-cell',selectRow:'table-select-row',selectColumn:'table-select-column',selectTable:'table-select-all',mergeCells:'table-merge-cells',splitCells:'table-split-cells',distributeRows:'table-distribute-rows',distributeColumns:'table-distribute-columns',autofitContents:'table-autofit-contents',autofitWindow:'table-autofit-window',autofitFixed:'table-autofit-fixed',textHorizontal:'table-text-direction-horizontal',textRotate90:'table-text-direction-rotate-90',textRotate270:'table-text-direction-rotate-270',tableProperties:'table-properties',alignTopLeft:'table-align-top-left',alignTopCenter:'table-align-top-center',alignTopRight:'table-align-top-right',alignMiddleLeft:'table-align-middle-left',alignMiddleCenter:'table-align-middle-center',alignMiddleRight:'table-align-middle-right',alignBottomLeft:'table-align-bottom-left',alignBottomCenter:'table-align-bottom-center',alignBottomRight:'table-align-bottom-right'}as const
  for(const [id,command]of Object.entries(map))actions[id as DocxContextMenuAction]={reason:()=>table.reason(command),run:()=>table.run(command)}
 }
 Object.assign(actions,options.extra)
 return {actions,dispose(){close();numbering.destroy()}}
}
