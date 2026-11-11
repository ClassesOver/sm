// @vitest-environment jsdom
import {Editor} from '@tiptap/core'
import {describe,it,expect,vi} from 'vitest'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {createDocxCaptionDialog} from './docx-caption-dialog'
describe('caption dialog',()=>{
 it('keeps the caret while editing and previews trusted text',()=>{
  const editor=new Editor({extensions:editorExtensions,content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'Anchor'}]}]}}),host=document.createElement('div');document.body.append(host)
  const run=vi.fn(()=>{editor.commands.insertContent('题注')})
  const dialog=createDocxCaptionDialog({editor,container:host,controls:{reason:()=>null,preview:(label,text)=>({number:1,display:label+' 1 '+text}),run},readOnlyReason:()=>null,onError:vi.fn()})
  try{const caret=editor.state.selection.from;dialog.open();const input=host.querySelector<HTMLInputElement>('[data-caption-text]')!;input.value='收入 & <😀>';input.dispatchEvent(new Event('input'));expect(editor.state.selection.from).toBe(caret);expect(host.querySelector('[data-caption-preview]')!.textContent).toBe('图 1 收入 & <😀>');host.querySelector<HTMLButtonElement>('[data-caption-confirm]')!.click();expect(run).toHaveBeenCalledWith('图','收入 & <😀>');expect(host.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true)}finally{dialog.dispose();editor.destroy();host.remove()}
 })
 it('rejects stale selection and locks, and leaves failed insertions open',()=>{
  const editor=new Editor({extensions:editorExtensions,content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'Anchor'}]}]}}),host=document.createElement('div');let lock:string|null=null;const run=vi.fn()
  const dialog=createDocxCaptionDialog({editor,container:host,controls:{reason:()=>null,preview:()=>({number:1,display:'图 1'}),run},readOnlyReason:()=>lock,onError:vi.fn()})
  try{dialog.open();const confirm=host.querySelector<HTMLButtonElement>('[data-caption-confirm]')!;confirm.click();expect(host.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(false);editor.commands.setTextSelection(2);expect(confirm.disabled).toBe(true);dialog.open();lock='正在保存';dialog.refresh();expect(confirm.disabled).toBe(true);confirm.click();expect(run).toHaveBeenCalledTimes(1)}finally{dialog.dispose();editor.destroy()}
 })
})
