import type {Editor} from '@tiptap/core'
import {buttonClasses} from './button'
import {createModal} from './modal'
import {asianCharCount,countWords,documentTextForWordCount,nonAsianWordCount} from './vendor/genoffice-docs/apps/docs/src/renderer/word-count'

interface Options {editor:Editor;container:HTMLElement}

export function createDocxWordCountControl({editor,container}:Options){
 const button=document.createElement('button')
 button.type='button';button.className=buttonClasses('secondary');button.textContent='字数统计';button.setAttribute('aria-label','字数统计');button.dataset.action='word-count'
 let modal:ReturnType<typeof createModal>|undefined,disposed=false
 const close=()=>modal?.close()
 const open=()=>{
  if(disposed||editor.isDestroyed)return
  const text=documentTextForWordCount(editor.state.doc)
  let paragraphs=0
  editor.state.doc.descendants(node=>{if(node.isTextblock&&documentTextForWordCount(node).trim())paragraphs++;return true})
  const stats=[
   ['words','字数',countWords(text)],['asianChars','中日韩字符',asianCharCount(text)],['nonAsianWords','其他词语',nonAsianWordCount(text)],
   ['charsNoSpace','字符数（不计空白）',text.replace(/\s/g,'').length],['charsWithSpace','字符数（含空格）',text.replace(/\n/g,'').length],['paragraphs','非空段落',paragraphs],
  ] as const
  if(!modal)modal=createModal({root:container,label:'字数统计',closeLabel:'关闭字数统计',cardClass:'docx-word-count-dialog',content:'<h2>字数统计</h2><dl data-word-count-stats></dl><div class="modal-actions"><button type="button" data-action="close">关闭</button></div>'})
  const list=modal.card.querySelector<HTMLElement>('[data-word-count-stats]')!
  list.replaceChildren()
  for(const [key,label,value] of stats){const row=document.createElement('div'),term=document.createElement('dt'),count=document.createElement('dd');row.dataset.stat=key;count.dataset.value='';term.textContent=label;count.textContent=String(value);row.append(term,count);list.append(row)}
  modal.card.querySelector<HTMLButtonElement>('[data-action="close"]')!.onclick=close
  modal.open()
 }
 button.addEventListener('click',open)
 return {element:button,open,dispose(){disposed=true;modal?.remove();button.removeEventListener('click',open)}}
}
