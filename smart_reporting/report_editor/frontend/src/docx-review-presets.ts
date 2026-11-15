import type {Editor} from '@tiptap/core'
import type {Node as PmNode} from '@tiptap/pm/model'
import {AllSelection} from '@tiptap/pm/state'
import {docxAIReadSelection} from './docx-ai-read-selection'
import type {DocxAnchor} from './docx-operations'
import {TRANSLATE_LANGS} from './vendor/genoffice-docs/apps/docs/src/renderer/components/translate-langs'
import {zh} from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'

export type DocxPresetSelection = {blockId:string;cellId?:string}[]
export type DocxPresetScope = 'selection'|'document'
/** Source ReviewTab presets; execution and explicit adoption remain in Native AI. */
export function createDocxReviewPresets(options:{
 editor:Editor;source:PmNode;anchors:readonly DocxAnchor[];reason():string|null
 open(instruction:string,selection:DocxPresetSelection,scope:DocxPresetScope):void
 onError(error:unknown):void;confirm?(message:string):boolean;flush?():void
}){
 const element=document.createElement('div');element.className='ribbon-group-items docx-review-presets'
 const button=(action:string,label:string)=>{const value=document.createElement('button');value.type='button';value.className='rb-icon docx-ribbon-command';value.dataset.action=action;value.textContent=label;value.setAttribute('aria-label',label);value.onmousedown=event=>event.preventDefault();return value}
 const editorButton=button('review-editor',zh.ribbonEditorBtn),translate=button('review-translate',zh.ribbonTranslate)
 const menu=document.createElement('div');menu.className='layout-menu';menu.setAttribute('role','menu');menu.setAttribute('aria-label','翻译目标语言');menu.hidden=true
 translate.setAttribute('aria-haspopup','menu');translate.setAttribute('aria-expanded','false')
 function dismiss(){menu.hidden=true;translate.setAttribute('aria-expanded','false')}
 function run(language?:typeof TRANSLATE_LANGS[number]){
  dismiss()
  try{
   const reason=options.reason();if(reason)throw new Error(reason)
   options.flush?.()
   const doc=options.editor.state.doc,scope:DocxPresetScope=options.editor.state.selection.empty?'document':'selection'
   const targets=docxAIReadSelection(doc,scope==='document'?new AllSelection(doc):options.editor.state.selection,options.source,options.anchors)
   if(!targets.length)throw new Error('此范围含新增、复杂或无法核验的对象，请保存或重新选择可信正文段落／单元格；未扩大授权。')
   if(targets.length>100)throw new Error('一次最多处理100个段落、单元格或整表，请缩小选区；未截断或发送正文。')
   for(const target of targets){
    const anchor=options.anchors.find(item=>item.blockId===target.blockId)
    const editable=target.cellId?anchor?.cells?.flat().find(cell=>cell.cellId===target.cellId)?.editable:anchor?.cells?anchor.cells.flat().every(cell=>cell.editable):anchor?.editable
    if(!editable)throw new Error('此范围含只读对象，请重新选择可编辑正文；未跳过目标或扩大授权。')
   }
   if(scope==='document'&&!(options.confirm??window.confirm)(`将授权 AI 处理整篇正文的 ${targets.length} 个段落／整表。不含页眉页脚、脚注尾注及图片。生成会消耗模型额度；候选仍需显式采纳。是否继续？`))return
   const prompt=language?(scope==='selection'?zh.ribbonTranslateSelectionPrompt:zh.ribbonTranslatePrompt).replace('{lang}',zh[`ribbonLang${language.key}`]):scope==='selection'?zh.ribbonEditorSelectionPrompt:zh.ribbonEditorPrompt
   options.open(prompt+'\n仅处理明确授权的段落／单元格；选中部分文字按整段／整格处理，保持结构不变。',targets,scope)
  }catch(error){options.onError(error)}
 }
 editorButton.onclick=()=>run()
 translate.onclick=()=>{if(options.reason())return;menu.hidden=!menu.hidden;translate.setAttribute('aria-expanded',String(!menu.hidden))}
 for(const language of TRANSLATE_LANGS){const item=button('review-translate-'+language.code,zh.ribbonTranslateTo.replace('{lang}',zh[`ribbonLang${language.key}`]));item.dataset.language=language.code;item.setAttribute('role','menuitem');item.onclick=()=>run(language);menu.append(item)}
 const wrap=document.createElement('div');wrap.className='rb-split-wrap';wrap.append(translate,menu);element.append(editorButton,wrap)
 const keydown=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!menu.hidden){event.preventDefault();dismiss();translate.focus()}}
 const outside=(event:Event)=>{if(event.target instanceof globalThis.Node&&!element.contains(event.target))dismiss()}
 element.addEventListener('keydown',keydown);document.addEventListener('pointerdown',outside,true)
 const refresh=()=>{const reason=options.reason();for(const control of [editorButton,translate]){control.disabled=reason!==null;control.title=reason??`${control.textContent}：选中部分文字按整段／整格处理；先预览再采纳`}if(reason)dismiss()}
 options.editor.on('transaction',refresh);refresh()
 return {element,refresh,dispose(){options.editor.off('transaction',refresh);document.removeEventListener('pointerdown',outside,true);element.remove()}}
}
