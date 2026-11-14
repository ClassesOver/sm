import type {Editor} from '@tiptap/core'
import {buttonClasses} from './button'
import {SPELLCHECK_KEY,spellcheckEnabled} from './vendor/genoffice-docs/apps/docs/src/renderer/spellcheck-pref'

export function createDocxSpellcheckControl(editor:Editor){
 const button=document.createElement('button')
 button.type='button';button.className=buttonClasses('secondary');button.textContent='拼写检查';button.dataset.action='spellcheck';button.setAttribute('aria-label','拼写检查')
 let enabled=spellcheckEnabled(),disposed=false
 const refresh=()=>{
  button.setAttribute('aria-pressed',String(enabled));button.classList.toggle('active',enabled)
 }
 const apply=()=>{
  editor.setOptions({editorProps:{...editor.options.editorProps,attributes:{...(editor.options.editorProps.attributes as Record<string,string>),spellcheck:String(enabled)}}})
  refresh()
 }
 const toggle=()=>{
  if(disposed||editor.isDestroyed)return
  enabled=!enabled;localStorage.setItem(SPELLCHECK_KEY,enabled?'1':'0');apply()
 }
 button.addEventListener('click',toggle)
 apply()
 return {element:button,refresh,dispose(){disposed=true;button.removeEventListener('click',toggle)}}
}
