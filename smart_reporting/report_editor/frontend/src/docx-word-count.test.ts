import {afterEach,expect,it} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import {createDocxWordCountControl} from './docx-word-count'

const Doc=Node.create({name:'doc',topNode:true,content:'paragraph+',renderHTML:()=>['div',0]})
const Paragraph=Node.create({name:'paragraph',group:'block',content:'text*',renderHTML:()=>['p',0]})
const Text=Node.create({name:'text',group:'inline',renderHTML:()=>['span',0]})
let cleanup:(()=>void)|undefined
afterEach(()=>{cleanup?.();cleanup=undefined;document.body.replaceChildren()})

it('shows source word and character counts plus nonempty paragraphs without estimated pages or lines',()=>{
 const host=document.body.appendChild(document.createElement('div'))
 const editor=new Editor({element:host,extensions:[Doc,Paragraph,Text],content:{type:'doc',content:[
  {type:'paragraph',content:[{type:'text',text:'你好 Word 12'}]},
  {type:'paragraph',content:[]},
  {type:'paragraph',content:[{type:'text',text:'再见!'}]},
 ]}})
 const control=createDocxWordCountControl({editor,container:document.body});document.body.append(control.element)
 cleanup=()=>{control.dispose();editor.destroy()}
 control.element.focus();control.element.click()
 const dialog=document.querySelector<HTMLElement>('[role="dialog"]')!
 expect(dialog.getAttribute('aria-label')).toBe('字数统计')
 const values=Object.fromEntries([...dialog.querySelectorAll<HTMLElement>('[data-stat]')].map(row=>[row.dataset.stat,row.querySelector('[data-value]')?.textContent]))
 expect(values).toEqual({words:'6',asianChars:'4',nonAsianWords:'2',charsNoSpace:'11',charsWithSpace:'15',paragraphs:'2'})
 expect(dialog.textContent).not.toMatch(/页数|行数/)
 dialog.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(dialog.closest('[hidden]')).not.toBeNull()
 expect(document.activeElement).toBe(control.element)
})

it('keeps its read-only entry available for a noneditable editor',()=>{
 const host=document.body.appendChild(document.createElement('div'))
 const editor=new Editor({element:host,extensions:[Doc,Paragraph,Text],content:{type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'body'}]}]}})
 editor.setEditable(false)
 const control=createDocxWordCountControl({editor,container:document.body});document.body.append(control.element)
 cleanup=()=>{control.dispose();editor.destroy()}
 expect(control.element.disabled).toBe(false);control.element.click()
 expect(document.querySelector('[role="dialog"]')).not.toBeNull()
})
