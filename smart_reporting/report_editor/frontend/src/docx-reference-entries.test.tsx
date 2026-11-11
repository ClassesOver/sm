import {afterEach,expect,it,vi} from 'vitest'
import {Editor} from '@tiptap/core'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {DocxInsertSource} from './docx-insert-source'

const editors:Editor[]=[]
afterEach(()=>{editors.splice(0).forEach(editor=>editor.destroy());document.body.replaceChildren()})

it('opens trusted bookmark and cross-reference controls through the Insert ribbon without changing the body selection',()=>{
 const editor=new Editor({extensions:editorExtensions,content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'引用位置'}]}]}});editors.push(editor)
 editor.commands.setTextSelection(3)
 const before=editor.getJSON(),onBookmarks=vi.fn(),onCrossReference=vi.fn(),host=document.createElement('div');document.body.append(host)
 const root=createRoot(host)
 flushSync(()=>root.render(<DocxInsertSource editor={editor} editable onBookmarks={onBookmarks} onCrossReference={onCrossReference}/>))
 for(const [action,callback]of [['insert-bookmark',onBookmarks],['insert-cross-ref',onCrossReference]] as const){
  const button=host.querySelector<HTMLButtonElement>('[data-action="'+action+'"]')!
  expect(button.disabled).toBe(false)
  const event=new MouseEvent('mousedown',{bubbles:true,cancelable:true});button.dispatchEvent(event);expect(event.defaultPrevented).toBe(true)
  button.click();expect(callback).toHaveBeenCalledOnce()
 }
 expect(editor.getJSON()).toEqual(before);expect(editor.state.selection.from).toBe(3)
 editor.setEditable(false)
 flushSync(()=>root.render(<DocxInsertSource editor={editor} editable={false} onBookmarks={onBookmarks} onCrossReference={onCrossReference}/>))
 expect(host.querySelector<HTMLButtonElement>('[data-action="insert-cross-ref"]')!.disabled).toBe(true)
 root.unmount()
})
