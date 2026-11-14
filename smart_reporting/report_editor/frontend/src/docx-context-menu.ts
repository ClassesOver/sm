/** Browser adapter for GenOffice f8c17004 ContextMenu.tsx / App.onDocContextMenu.
 * Source groups and target semantics are preserved; all commands go through supplied
 * native callbacks, never the source's unvalidated direct editing commands.
 */
import {getMarkRange,type Editor} from '@tiptap/core'
import type {Node as PmNode} from '@tiptap/pm/model'
import {NodeSelection,TextSelection,type Selection} from '@tiptap/pm/state'
import {fieldRangeAt,type FieldRange} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/field-codes'
import {wordRangeAtCaret} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/comments'
import './docx-context-menu.css'

export interface DocxContextMenuTarget {
 readonly pos:number; readonly from:number; readonly to:number; readonly text:string
 readonly nodeType:string; readonly inTable:boolean; readonly inList:boolean
 readonly imageSrc:string|null; readonly linkHref:string|null
 readonly link:Readonly<{from:number;to:number;href:string}>|null
 readonly field:FieldRange|null; readonly commentId:string|null
 readonly doc:PmNode; readonly selection:Selection
}
// Group order follows the pinned source. Missing handlers remain visibly disabled.
const groups = [
 ['clipboard',[['cut','剪切'],['copy','复制'],['paste','粘贴'],['pasteText','只保留文本']]],
 ['picture',[['viewImage','查看图片'],['saveImage','图片另存为']]],
 ['text',[['font','字体…'],['paragraph','段落…']]],
 ['table',[
  ['insertRowBefore','在上方插入行'],['insertRowAfter','在下方插入行'],['insertColumnBefore','在左侧插入列'],['insertColumnAfter','在右侧插入列'],['insertCells','插入单元格…'],
  ['deleteRow','删除行'],['deleteColumn','删除列'],['deleteTable','删除表格'],['deleteCells','删除单元格…'],
  ['selectCell','选择单元格'],['selectRow','选择行'],['selectColumn','选择列'],['selectTable','选择表格'],
  ['mergeCells','合并单元格'],['splitCells','拆分单元格…'],['splitTable','拆分表格'],['distributeRows','平均分布各行'],['distributeColumns','平均分布各列'],
  ['alignTopLeft','顶端左对齐'],['alignTopCenter','顶端居中'],['alignTopRight','顶端右对齐'],['alignMiddleLeft','中部左对齐'],['alignMiddleCenter','中部居中'],['alignMiddleRight','中部右对齐'],['alignBottomLeft','底端左对齐'],['alignBottomCenter','底端居中'],['alignBottomRight','底端右对齐'],
  ['textHorizontal','横向文字'],['textRotate90','文字旋转90°'],['textRotate270','文字旋转270°'],
  ['autofitContents','根据内容调整表格'],['autofitWindow','根据窗口调整表格'],['autofitFixed','固定列宽'],['tableProperties','表格属性…']]],
 ['field',[['updateFields','更新域'],['toggleFieldCodes','切换域代码'],['editField','编辑域…']]],
 ['list',[['restartNumbering','重新开始编号'],['continueNumbering','继续编号'],['setNumberingValue','设置编号值…'],['adjustListIndents','调整列表缩进…'],['listLevel1','列表级别 1'],['listLevel2','列表级别 2'],['listLevel3','列表级别 3'],['listLevel4','列表级别 4'],['listLevel5','列表级别 5'],['listLevel6','列表级别 6'],['listLevel7','列表级别 7'],['listLevel8','列表级别 8'],['listLevel9','列表级别 9']]],
 ['ai',[['synonyms','同义词'],['translate','翻译…'],['redact','隐藏所选文本'],['unredact','取消隐藏所选文本']]],
 ['wrap',[['wrapInline','嵌入型'],['wrapSquare','四周型环绕'],['wrapTight','紧密型环绕'],['wrapThrough','穿越型环绕'],['wrapTopBottom','上下型环绕'],['wrapBehind','衬于文字下方'],['wrapFront','浮于文字上方'],['bringToFront','置于顶层'],['bringForward','上移一层'],['sendBackward','下移一层'],['sendToBack','置于底层']]],
 ['link',[['editLink','编辑超链接…'],['openLink','打开超链接'],['copyLink','复制超链接'],['removeLink','取消超链接']]],
 ['insertLink',[['link','超链接…']]],
 ['review',[['newComment','新建批注'],['replyComment','回复批注'],['deleteComment','删除批注'],['resolveComment','解决批注'],['acceptRevision','接受修订'],['rejectRevision','拒绝修订'],['acceptAllRevisions','接受所有修订'],['rejectAllRevisions','拒绝所有修订'],['trackChanges','修订']]],
] as const
export type DocxContextMenuAction = typeof groups[number][1][number][0]
export type DocxContextMenuHandler = ((target:DocxContextMenuTarget)=>unknown)|{
 run:(target:DocxContextMenuTarget)=>unknown
 /** Native scope wording when the source command is only partially supported. */
 label?:string
 description?:string
 /** Return the native engine's exact unsupported/save/selection reason. */
 reason?:(target:DocxContextMenuTarget)=>string|null
}
export type DocxContextMenuActions=Partial<Record<DocxContextMenuAction,DocxContextMenuHandler>>
export interface DocxContextMenuOptions {
 editor:Editor; root:HTMLElement; actions:DocxContextMenuActions
 locked:()=>string|null|boolean; onError:(error:unknown)=>void
}
const readOnlyActions=new Set<DocxContextMenuAction>(['copy','viewImage','saveImage','openLink','copyLink','toggleFieldCodes','selectCell','selectRow','selectColumn','selectTable'])

export function createDocxContextMenu({editor,root,actions,locked,onError}:DocxContextMenuOptions){
 const owner=root.ownerDocument,win=owner.defaultView!
 let menu:HTMLElement|null=null,target:DocxContextMenuTarget|null=null,disposed=false,opener:HTMLElement|null=null
 const isInside=(node:EventTarget|null):node is HTMLElement=>node instanceof win.HTMLElement&&editor.view.dom.contains(node)&&node.closest('.ProseMirror')===editor.view.dom&&!node.closest('input,textarea,select,[role=dialog],.doc-nested-table')
 function close(restore=false){
  if(!menu)return
  menu.remove();menu=null;target=null
  if(restore&&!editor.isDestroyed){if(opener?.isConnected)opener.focus({preventScroll:true});else editor.view.focus()}
  opener=null
 }
 function stale(t:DocxContextMenuTarget){return disposed||editor.isDestroyed||editor.view.composing||editor.state.doc!==t.doc||!editor.state.selection.eq(t.selection)}
 function reason(id:DocxContextMenuAction,t:DocxContextMenuTarget){
  if(stale(t))return '文档或选区已变化，请重新打开菜单'
  const handler=actions[id]
  if(!handler)return '此操作尚未接入原生编辑器'
  if(!readOnlyActions.has(id)){const lock=locked();if(lock)return typeof lock==='string'?lock:'当前文档不可编辑';if(!editor.isEditable)return '当前文档为只读'}
  if(id==='newComment'&&t.selection.empty&&!wordRangeAtCaret(editor))return '请先选择内容或将光标放在词语中'
  if((id==='cut'||id==='copy')&&t.selection.empty)return '请先选择内容'
  if((id==='synonyms')&&(!t.text.trim()||t.text.trim().length>20))return '请选择不超过20个字符的词语'
  if(['translate','redact','unredact'].includes(id)&&!t.text.trim())return '请先选择文本'
  if(['replyComment','deleteComment','resolveComment'].includes(id)&&!t.commentId)return '当前位置没有批注'
  return typeof handler==='function'?null:handler.reason?.(t)??null
 }
 function refresh(){
  if(!menu||!target)return
  if(stale(target)){close(menu.contains(owner.activeElement));return}
  for(const button of menu.querySelectorAll<HTMLButtonElement>('[data-context-action]')){
   let why:string|null
   try{why=reason(button.dataset.contextAction as DocxContextMenuAction,target)}catch(error){why='当前操作不可用';onError(error)}
   const handler=actions[button.dataset.contextAction as DocxContextMenuAction],description=typeof handler==='object'?handler.description:undefined
   button.disabled=!!why;button.title=why??description??''
   if(button.title)button.setAttribute('aria-description',button.title);else button.removeAttribute('aria-description')
  }
 }
 function eligible(group:typeof groups[number][0],t:DocxContextMenuTarget){
  switch(group){
   case 'picture':case 'wrap':return t.imageSrc!==null
   case 'text':case 'ai':return t.imageSrc===null
   case 'table':return t.inTable
   case 'field':return !!t.field
   case 'list':return t.inList&&t.imageSrc===null
   case 'link':return t.linkHref!==null
   case 'insertLink':return t.linkHref===null
   default:return true
  }
 }
 function run(id:DocxContextMenuAction){
  const frozen=target;if(!frozen)return
  try{
   const why=reason(id,frozen)
   if(why){close(true);onError(new Error(why));return}
   const handler=actions[id]!;close(true)
   const result=typeof handler==='function'?handler(frozen):handler.run(frozen)
   Promise.resolve(result).catch(onError)
  }catch(error){close(true);onError(error)}
 }
 function snapshot(pos:number,eventTarget:HTMLElement):DocxContextMenuTarget{
  const {doc,selection}=editor.state,$pos=doc.resolve(pos)
  let inTable=selection instanceof NodeSelection&&selection.node.type.name==='docTable',inList=selection instanceof NodeSelection&&selection.node.type.name==='docListItem'
  for(let depth=$pos.depth;depth>0;depth--){const name=$pos.node(depth).type.name;inTable||=name==='docTable'||name==='docTableCell'||name==='docTableHeader';inList||=name==='docListItem'}
  const selected=selection instanceof NodeSelection?selection.node:null
  const imageSrc=selected?.type.name==='docInlineImage'?String(selected.attrs.dataUrl||'')||null:selected?.type.name==='docProtected'&&selected.attrs.blockType==='image'?String(selected.attrs.imageDataUrl||selected.attrs.dataUrl||selected.attrs.src||'')||eventTarget.closest('.doc-protected')?.querySelector('img')?.getAttribute('src')||null:null
  const mark=editor.schema.marks.link,range=mark?getMarkRange($pos,mark):undefined
  const href=range?doc.resolve(range.from).nodeAfter?.marks.find(m=>m.type===mark)?.attrs.href:null
  const domLink=eventTarget.closest<HTMLAnchorElement>('a[href]')
  const linkHref=typeof href==='string'?href:domLink?.getAttribute('href')??null
  const link=range&&typeof href==='string'?Object.freeze({...range,href}):null
  const commentMark=$pos.marks().find(m=>m.type.name==='comment')
  const commentId=eventTarget.closest<HTMLElement>('[data-comment-id]')?.dataset.commentId??String(commentMark?.attrs.ids??'').split(' ').filter(Boolean)[0]??null
  return Object.freeze({pos,from:selection.from,to:selection.to,text:doc.textBetween(selection.from,selection.to,'\n'),nodeType:selected?.type.name??$pos.parent.type.name,inTable,inList,imageSrc,linkHref,link,field:fieldRangeAt(editor.state,pos),commentId,doc,selection})
 }
 function show(event:MouseEvent|KeyboardEvent,keyboard:boolean){
  if(disposed||editor.isDestroyed||editor.view.composing||('isComposing'in event&&(event.isComposing||event.keyCode===229))||!isInside(event.target))return
  let pos=editor.state.selection.head,x=0,y=0
  try{
   if(keyboard){const coords=editor.view.coordsAtPos(pos);x=coords.left;y=coords.bottom}
   else{
    const mouse=event as MouseEvent;x=mouse.clientX;y=mouse.clientY
    const hit=editor.view.posAtCoords({left:x,top:y});if(!hit)return
    pos=Math.max(0,Math.min(hit.pos,editor.state.doc.content.size))
    // An atom's painted DOM can resolve to the text position after it. Source
    // App selects the actual pointed picture node before looking at the caret.
    const element=event.target as HTMLElement
    if(element.closest('img,.doc-protected')){
     let imagePos:number|null=null
     editor.state.doc.descendants((candidate,at)=>{
      if(imagePos!==null)return false
      if(candidate.type.name!=='docInlineImage'&&!(candidate.type.name==='docProtected'&&candidate.attrs.blockType==='image'))return
      const dom=editor.view.nodeDOM(at)
      if(dom&&(dom===element||dom.contains(element)))imagePos=at
     })
     if(imagePos!==null)pos=imagePos
    }
    const node=editor.state.doc.nodeAt(pos)
    const image=node?.type.name==='docInlineImage'||node?.type.name==='docProtected'&&node.attrs.blockType==='image'
    if(image&&NodeSelection.isSelectable(node!))editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc,pos)))
    else if(pos<editor.state.selection.from||pos>editor.state.selection.to)editor.view.dispatch(editor.state.tr.setSelection(TextSelection.near(editor.state.doc.resolve(pos))))
   }
   close();event.preventDefault();opener=editor.view.dom
   target=snapshot(pos,event.target as HTMLElement)
   menu=owner.createElement('div');menu.className='docx-context-menu ctx-menu';menu.setAttribute('role','menu');menu.setAttribute('aria-label','Word 文档菜单');menu.tabIndex=-1
   for(const[group,items]of groups){
    if(!eligible(group,target))continue
    const section=owner.createElement('div');section.setAttribute('role','group');section.dataset.contextGroup=group
    for(const[id,label]of items){const button=owner.createElement('button');button.type='button';button.className='ctx-item';button.dataset.contextAction=id;button.setAttribute('role','menuitem');const handler=actions[id];button.textContent=typeof handler==='object'?handler.label??label:label;button.addEventListener('mousedown',e=>e.preventDefault());button.addEventListener('click',()=>run(id));section.append(button)}
    menu.append(section)
   }
   menu.addEventListener('keydown',navigate);menu.addEventListener('contextmenu',e=>e.preventDefault());root.append(menu);refresh()
   if(!menu)return
   const rect=menu.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(x,win.innerWidth-rect.width-8))+'px';menu.style.top=Math.max(8,Math.min(y,win.innerHeight-Math.min(rect.height,win.innerHeight-16)-8))+'px'
   ;(menu.querySelector<HTMLButtonElement>('button:not(:disabled)')??menu).focus({preventScroll:true})
  }catch(error){close();onError(error)}
 }
 function navigate(event:KeyboardEvent){
  if(event.isComposing||event.keyCode===229)return
  if(event.key==='Escape'||event.key==='Tab'){event.preventDefault();close(true);return}
  if(!menu||!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return
  event.preventDefault();refresh();if(!menu)return
  const enabled=[...menu.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];if(!enabled.length)return
  const at=enabled.indexOf(owner.activeElement as HTMLButtonElement),index=event.key==='Home'?0:event.key==='End'?enabled.length-1:(at+(event.key==='ArrowDown'?1:-1)+enabled.length)%enabled.length
  enabled[index]!.focus({preventScroll:true})
 }
 const context=(event:MouseEvent)=>show(event,event.clientX===0&&event.clientY===0)
 const keyboard=(event:KeyboardEvent)=>{if(event.key==='ContextMenu'||event.key==='F10'&&event.shiftKey&&!event.ctrlKey&&!event.metaKey&&!event.altKey)show(event,true)}
 const outside=(event:MouseEvent)=>{if(menu&&!menu.contains(event.target as Node))close()}
 const blur=()=>close()
 root.addEventListener('contextmenu',context);root.addEventListener('keydown',keyboard)
 owner.addEventListener('mousedown',outside,true);win.addEventListener('blur',blur);editor.on('transaction',refresh)
 return{close:()=>close(true),refresh,dispose(){if(disposed)return;disposed=true;close();root.removeEventListener('contextmenu',context);root.removeEventListener('keydown',keyboard);owner.removeEventListener('mousedown',outside,true);win.removeEventListener('blur',blur);editor.off('transaction',refresh)}}
}
