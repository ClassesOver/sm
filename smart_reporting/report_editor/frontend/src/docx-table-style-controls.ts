import type {Editor} from '@tiptap/core'
import {NodeSelection,Selection} from '@tiptap/pm/state'
import {projectDocxTableStyle,type DocxTableStyleAnchor} from './docx-table-style'
import {DEFAULT_TABLE_LOOK,TABLE_STYLE_PRESETS,type TableStyleLook} from './docx-table-style-core'
function selected(editor:Editor){
 const selection=editor.state.selection
 if(selection instanceof NodeSelection&&selection.node.type.name==='docTable')return{pos:selection.from,node:selection.node}
 for(let depth=selection.$from.depth;depth>0;depth--)if(selection.$from.node(depth).type.name==='docTable')return{pos:selection.$from.before(depth),node:selection.$from.node(depth)}
 return null
}
export function docxTableStyleUnavailable(editor:Editor,anchors:readonly DocxTableStyleAnchor[]):string|null{
 if(!editor.isEditable)return'当前文档只读'
 const table=selected(editor);if(!table)return'请先选择表格'
 const anchor=anchors.find(a=>a.docxIndex===table.node.attrs.docxIndex)
 if(!anchor?.tableStyleEditable)return anchor?.tableStyleReadOnlyReason??'当前来源不支持表格样式'
 if(Object.entries(table.node.attrs).some(([k,v])=>k.startsWith('nativeTable')&&k!=='nativeTableStyle'&&v))return'请先保存同表其他修改'
 return null
}
export function applyDocxTableStyle(editor:Editor,input:unknown,anchors:readonly DocxTableStyleAnchor[]):boolean{
 const reason=docxTableStyleUnavailable(editor,anchors);if(reason)return false
 const target=selected(editor)!,anchor=anchors.find(a=>a.docxIndex===target.node.attrs.docxIndex)!
 const projected=projectDocxTableStyle(target.node.toJSON(),anchor,input,editor.schema),node=editor.schema.nodeFromJSON(projected)
 if(node.eq(target.node))return false
 const state=editor.state,tr=state.tr.replaceWith(target.pos,target.pos+target.node.nodeSize,node)
 tr.setSelection(Selection.fromJSON(tr.doc,state.selection.toJSON()))
 editor.view.dispatch(tr);editor.view.focus();return true
}
export function toggleDocxTableStyleLook(editor:Editor,key:keyof TableStyleLook,anchors:readonly DocxTableStyleAnchor[]):boolean{
 if(!Object.hasOwn(DEFAULT_TABLE_LOOK,key))throw Error('docx_table_style_look_invalid')
 const table=selected(editor);if(!table)return false
 const look=(table.node.attrs.tblLook??DEFAULT_TABLE_LOOK) as TableStyleLook
 return applyDocxTableStyle(editor,{look:{...look,[key]:!look[key]}},anchors)
}
export function selectedDocxTableStyle(editor:Editor,anchors:readonly DocxTableStyleAnchor[]){
 const table=selected(editor),anchor=table&&anchors.find(a=>a.docxIndex===table.node.attrs.docxIndex)
 return{styleId:table?.node.attrs.tblStyleId??null,look:(table?.node.attrs.tblLook??DEFAULT_TABLE_LOOK) as TableStyleLook,options:anchor?.tableStyleOptions??[],reason:docxTableStyleUnavailable(editor,anchors)}
}
/** Source gallery and six look options, bound to the active table and current source anchors. */
export function createDocxTableStyleControls(options:{editor:Editor;anchors:readonly DocxTableStyleAnchor[]|(()=>readonly DocxTableStyleAnchor[]);onError?:(error:unknown)=>void}){
 const {editor}=options,element=document.createElement('div')
 element.className='docx-table-style-controls';element.dataset.docxTableStyleControls=''
 Object.assign(element.style,{display:'flex',gap:'12px',alignItems:'stretch',maxWidth:'100%'})
 const getAnchors=()=>typeof options.anchors==='function'?options.anchors():options.anchors
 let disposed=false
 function setButtonState(button:HTMLButtonElement,label:string,reason:string|null,pressed:boolean){
  button.title=reason??label
  button.disabled=Boolean(reason)
  button.setAttribute('aria-pressed',String(pressed))
  button.classList.toggle('active',pressed)
  if(reason)button.setAttribute('aria-description',reason)
  else button.removeAttribute('aria-description')
 }
 function button(run:()=>void){
  const button=document.createElement('button')
  button.type='button'
  button.addEventListener('mousedown',event=>event.preventDefault())
  button.addEventListener('click',()=>{try{run()}catch(error){options.onError?.(error)}})
  return button
 }
 function group(label:string,contentClass:string){
  const section=document.createElement('section'),content=document.createElement('div'),caption=document.createElement('div')
  section.className='table-tool-group'
  section.setAttribute('aria-label',label)
  content.className=contentClass
  caption.className='ribbon-group-label'
  caption.textContent=label
  section.append(content,caption)
  element.append(section)
  return content
 }
 const gallery=group('表格样式','table-style-gallery')
 const looks=group('表格样式选项','table-style-options')
 // GenOffice Ribbon.tsx Table Design appearance switches.
 const lookButtons=([
  ['firstRow','首行'],['lastRow','末行'],['bandedRows','镶边行'],
  ['firstColumn','首列'],['lastColumn','末列'],['bandedColumns','镶边列'],
 ] as const).map(([key,label])=>{
  const control=button(()=>{toggleDocxTableStyleLook(editor,key,getAnchors())})
  control.dataset.tableLook=key
  control.className='table-option-toggle table-tool-button'
  const check=document.createElement('span'),caption=document.createElement('span')
  check.className='table-option-check'
  check.setAttribute('aria-hidden','true')
  caption.textContent=label
  control.append(check,caption)
  looks.append(control)
  return {key,label,control}
 })
 function refresh(){
  if(disposed)return
  const anchors=getAnchors(),state=selectedDocxTableStyle(editor,anchors),table=selected(editor),pending=table?.node.attrs.nativeTableStyle
  gallery.replaceChildren()
  function card(id:string,label:string,pressed:boolean,run:()=>void,preset?:typeof TABLE_STYLE_PRESETS[keyof typeof TABLE_STYLE_PRESETS]){
   const anchor=anchors.find(item=>item.docxIndex===table?.node.attrs.docxIndex),reason=state.reason??(preset&&anchor?.tableStyleState?.presetEditable===false?'当前表格含合并或无法逐格写入的单元格，内置样式暂不支持':null)
   const control=button(run),preview=document.createElement('span'),name=document.createElement('span')
   control.dataset.tableStyle=id
   control.className='table-style-card'
   setButtonState(control,label,reason,pressed)
   name.textContent=label
   preview.className=id==='none'?'table-style-card-grid plain':'table-style-card-grid'
   if(preset)Object.assign(preview.style,{
    borderColor:`#${preset.borderColor}`,
    borderTopColor:`#${preset.headerFill??'FFFFFF'}`,
    background:`repeating-linear-gradient(to bottom,#${preset.band1Fill??'FFFFFF'} 0 50%,#${preset.band2Fill??'FFFFFF'} 50% 100%)`,
   })
   preview.setAttribute('aria-hidden','true');control.append(preview,name);gallery.append(control)
  }
  card('none','无样式',state.styleId===null&&!pending?.preset,()=>{applyDocxTableStyle(editor,{style:{kind:'none'}},getAnchors())})
  const labels:Record<keyof typeof TABLE_STYLE_PRESETS,string>={'grid':'网格样式','blue-header':'蓝色标题','blue-banded':'蓝色带状','gray-banded':'灰色带状','green-header':'绿色标题'}
  for(const id of Object.keys(TABLE_STYLE_PRESETS) as Array<keyof typeof TABLE_STYLE_PRESETS>)card(id,labels[id],pending?.style?.kind==='preset'&&pending.style.id===id,()=>{applyDocxTableStyle(editor,{style:{kind:'preset',id}},getAnchors())},TABLE_STYLE_PRESETS[id])
  for(const info of state.options)card(`document:${info.styleId}`,info.name,state.styleId===info.styleId,()=>{applyDocxTableStyle(editor,{style:{kind:'document',styleId:info.styleId}},getAnchors())})
  for(const {key,label,control} of lookButtons)setButtonState(control,label,state.reason,state.look[key])
 }
 editor.on('transaction',refresh);editor.on('selectionUpdate',refresh);refresh()
 return{element,refresh,dispose(){if(disposed)return;disposed=true;editor.off('transaction',refresh);editor.off('selectionUpdate',refresh);element.remove()}}
}
