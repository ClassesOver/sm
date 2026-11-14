// @vitest-environment jsdom
import {Editor} from '@tiptap/core'
import {describe,it,expect,vi} from 'vitest'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {createDocxCaptionDialog} from './docx-caption-dialog'
describe('caption dialog',()=>{
 it.each(['saving','selection','validation'] as const)('moves focused confirmation to the status when %s disables insertion',cause=>{
  const editor=new Editor({extensions:editorExtensions,content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'Anchor'}]}]}}),host=document.body.appendChild(document.createElement('div')),opener=host.appendChild(document.createElement('button')),run=vi.fn()
  let lock:string|null=null,invalid=false
  const dialog=createDocxCaptionDialog({editor,container:host,controls:{reason:()=>{if(invalid)throw new Error('题注来源不可用');return null},preview:(label,text)=>({number:1,display:label+' 1 '+text}),run},readOnlyReason:()=>lock,onError:vi.fn()})
  try{
   dialog.open({currentTarget:opener})
   const input=host.querySelector<HTMLInputElement>('[data-caption-text]')!,confirm=host.querySelector<HTMLButtonElement>('[data-caption-confirm]')!,status=host.querySelector<HTMLElement>('[role=status]')!
   input.value='未提交描述';input.dispatchEvent(new Event('input'));confirm.focus()
   if(cause==='saving')lock='正在保存文档'
   if(cause==='selection')editor.commands.setTextSelection(2)
   if(cause==='validation')invalid=true
   dialog.refresh()
   expect(confirm.disabled).toBe(true);expect(document.activeElement).toBe(status);expect(status.textContent).not.toBe('');expect(input.value).toBe('未提交描述');expect(run).not.toHaveBeenCalled()
   input.focus();dialog.refresh();expect(document.activeElement).toBe(input)
   window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))
   expect(host.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true);expect(document.activeElement).toBe(opener);expect(editor.state.doc.textContent).toBe('Anchor')
  }finally{dialog.dispose();editor.destroy();host.remove()}
 })
 it('names the preview and keeps a long description unchanged when cancelled',()=>{
  const editor=new Editor({extensions:editorExtensions,content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'Anchor'}]}]}}),host=document.body.appendChild(document.createElement('div')),opener=host.appendChild(document.createElement('button')),run=vi.fn()
  const dialog=createDocxCaptionDialog({editor,container:host,controls:{reason:()=>null,preview:(label,text)=>({number:1,display:label+' 1 '+text}),run},readOnlyReason:()=>null,onError:vi.fn()})
  try{
   editor.view.focus();const selection=editor.state.selection;dialog.open({currentTarget:opener});expect(editor.state.selection.eq(selection)).toBe(true);const input=host.querySelector<HTMLInputElement>('[data-caption-text]')!,text='长题注 & <😀>'.repeat(80);input.value=text;input.dispatchEvent(new Event('input'))
   const preview=host.querySelector<HTMLElement>('[data-caption-preview]')!
   expect(preview.getAttribute('role')).toBe('region');expect(preview.getAttribute('aria-label')).toBe('题注预览');expect(preview.tabIndex).toBe(0);expect(preview.textContent).toBe('图 1 '+text)
   const cancel=host.querySelector<HTMLButtonElement>('[data-caption-cancel]')!;expect(cancel).not.toBeNull();cancel.click()
   expect(host.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true);expect(document.activeElement).toBe(opener);expect(editor.state.doc.textContent).toBe('Anchor');expect(run).not.toHaveBeenCalled()
   dialog.open();expect(input.value).toBe('');expect(preview.textContent).toBe('图 1 ')
  }finally{dialog.dispose();editor.destroy();host.remove()}
 })
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
