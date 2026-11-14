import {afterEach,expect,it} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import {createDocxSpellcheckControl} from './docx-spellcheck'
import {SPELLCHECK_KEY} from './vendor/genoffice-docs/apps/docs/src/renderer/spellcheck-pref'

const Doc=Node.create({name:'doc',topNode:true,content:'paragraph+',renderHTML:()=>['div',0]})
const Paragraph=Node.create({name:'paragraph',group:'block',content:'text*',renderHTML:()=>['p',0]})
const Text=Node.create({name:'text',group:'inline',renderHTML:()=>['span',0]})
const editors:Editor[]=[]
const controls:{dispose:()=>void}[]=[]
afterEach(()=>{controls.splice(0).forEach(control=>control.dispose());editors.splice(0).forEach(editor=>editor.destroy());localStorage.removeItem(SPELLCHECK_KEY);document.body.replaceChildren()})
function editor(){const host=document.body.appendChild(document.createElement('div'));const result=new Editor({element:host,extensions:[Doc,Paragraph,Text],content:{type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'body'}]}]},editorProps:{attributes:{class:'doc-page','aria-label':'Word 文档编辑区'}}});editors.push(result);return result}

it('defaults on, persists toggles, retains current editor attributes, and remains usable read-only',()=>{
 const current=editor(),control=createDocxSpellcheckControl(current);controls.push(control);document.body.append(control.element)
 expect(control.element.getAttribute('aria-pressed')).toBe('true');expect(current.view.dom.getAttribute('spellcheck')).toBe('true')
 expect(current.view.dom.getAttribute('aria-label')).toBe('Word 文档编辑区')
 current.setEditable(false);control.element.click()
 expect(control.element.getAttribute('aria-pressed')).toBe('false');expect(current.view.dom.getAttribute('spellcheck')).toBe('false');expect(localStorage.getItem(SPELLCHECK_KEY)).toBe('0')
 control.element.click();expect(localStorage.getItem(SPELLCHECK_KEY)).toBe('1');expect(current.view.dom.getAttribute('spellcheck')).toBe('true')
})

it('does not change another editor and removes its toggle listener on dispose',()=>{
 const first=editor(),second=editor(),control=createDocxSpellcheckControl(first);controls.push(control);document.body.append(control.element)
 expect(second.view.dom.hasAttribute('spellcheck')).toBe(false)
 control.dispose();control.element.click()
 expect(first.view.dom.getAttribute('spellcheck')).toBe('true');expect(second.view.dom.hasAttribute('spellcheck')).toBe(false)
 expect(localStorage.getItem(SPELLCHECK_KEY)).toBeNull()
})
