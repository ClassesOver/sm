// @vitest-environment jsdom
import {Editor} from '@tiptap/core'
import {NodeSelection} from '@tiptap/pm/state'
import {afterEach,describe,expect,it,vi} from 'vitest'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {createDocxContextMenu,type DocxContextMenuActions} from './docx-context-menu'
const disposals:(()=>void)[]=[]
afterEach(()=>{disposals.splice(0).forEach(f=>f());document.body.replaceChildren()})
function setup(actions:DocxContextMenuActions={},locked:()=>string|null=()=>null,content?:object){
 const root=document.body.appendChild(document.createElement('div')),editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:editorExtensions,content:content??{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'First text'}]},{type:'docParagraph',content:[{type:'text',text:'Second'}]}]} as never,editorProps:{handleScrollToSelection:()=>true}})
 let hit=2;vi.spyOn(editor.view,'posAtCoords').mockImplementation(()=>({pos:hit,inside:0}));vi.spyOn(editor.view,'coordsAtPos').mockReturnValue({left:20,right:20,top:20,bottom:40})
 const errors:unknown[]=[],menu=createDocxContextMenu({editor,root,actions,locked,onError:e=>errors.push(e)})
 disposals.push(()=>{menu.dispose();editor.destroy();root.remove()})
 const open=(pos=2,target:HTMLElement=editor.view.dom)=>{hit=pos;const event=new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:30,clientY:40});target.dispatchEvent(event);return event}
 const button=(id:string)=>root.querySelector<HTMLButtonElement>(`[data-context-action="${id}"]`)!
 return{root,editor,menu,errors,open,button}
}
describe('native Word body context menu',()=>{
 it('preserves a selected range under the pointer and runs the real callback against that range',()=>{
  const {editor,open,button,root}=setup({cut:()=>{editor.commands.deleteSelection()}})
  editor.commands.setTextSelection({from:1,to:6});const event=open(3)
  expect(event.defaultPrevented).toBe(true);expect(editor.state.selection.from).toBe(1);expect(editor.state.selection.to).toBe(6)
  expect(root.querySelector('[role=menu]')).not.toBeNull();button('cut').click();expect(editor.state.doc.textContent).toBe(' textSecond');expect(root.querySelector('[role=menu]')).toBeNull()
 })
 it('moves the caret when clicking outside the selection, freezes the target and never intercepts outside the editor',()=>{
  let targetPos=-1;const{editor,open,button,root}=setup({font:target=>{targetPos=target.pos}})
  editor.commands.setTextSelection({from:1,to:5});open(14);expect(editor.state.selection.from).toBe(14);button('font').click();expect(targetPos).toBe(14)
  const event=new MouseEvent('contextmenu',{bubbles:true,cancelable:true});root.dispatchEvent(event);expect(event.defaultPrevented).toBe(false);expect(root.querySelector('[role=menu]')).toBeNull()
 })
 it.each(['document','selection','lock','readonly'] as const)('rejects stale %s state before running a callback',cause=>{
  let lock:string|null=null,calls=0;const {editor,open,button,root}=setup({paste:()=>{calls++;editor.commands.insertContent('BAD')}},()=>lock)
  open();const action=button('paste')
  if(cause==='document')editor.commands.insertContent('changed')
  if(cause==='selection')editor.commands.setTextSelection(3)
  if(cause==='lock')lock='正在保存'
  if(cause==='readonly')editor.setEditable(false)
  action.click();expect(calls).toBe(0);expect(editor.state.doc.textContent).not.toContain('BAD');expect(root.querySelector('[role=menu]')).toBeNull()
 })
 it('opens from Shift+F10 at the selection, supports menu navigation and restores focus on escape',()=>{
  const{editor,root}=setup({copy:()=>{},font:()=>{}});editor.commands.setTextSelection({from:1,to:5});editor.view.focus()
  const event=new KeyboardEvent('keydown',{key:'F10',shiftKey:true,bubbles:true,cancelable:true});editor.view.dom.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true);expect(editor.state.selection.to).toBe(5);const first=root.querySelector<HTMLButtonElement>('[role=menuitem]:not(:disabled)')!;expect(document.activeElement).toBe(first)
  first.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true,cancelable:true}));expect(document.activeElement).toBe(root.querySelector('[data-context-action=font]'))
  document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));expect(root.querySelector('[role=menu]')).toBeNull();expect(document.activeElement).toBe(editor.view.dom)
 })
 it('allows readonly copy, disables missing actions and only exposes eligible groups',()=>{
  let copied='';const{editor,open,button,root}=setup({copy:t=>{copied=t.text}});editor.commands.setTextSelection({from:1,to:6});editor.setEditable(false);open(3)
  expect(button('copy').disabled).toBe(false);expect(button('paste').disabled).toBe(true);expect(button('font').disabled).toBe(true);expect(root.querySelector('[data-context-action=mergeCells]')).toBeNull();expect(root.querySelector('[data-context-action=editField]')).toBeNull();button('copy').click();expect(copied).toBe('First')
 })
 it('selects a picture node at the pointer and exposes picture actions without pretending mutations exist',()=>{
  let image='';const{editor,open,button}=setup({viewImage:t=>{image=t.imageSrc!}},()=>null,{type:'doc',content:[{type:'docParagraph',content:[{type:'docInlineImage',attrs:{dataUrl:'data:image/png;base64,AA=='}}]}]})
  open(1);expect(editor.state.selection.constructor.name).toBe('NodeSelection');expect(button('viewImage').disabled).toBe(false);expect(button('wrapSquare').disabled).toBe(true);button('viewImage').click();expect(image).toBe('data:image/png;base64,AA==')
 })
 it('rejects IME menus and closes on outside click, reporting callback errors without leaking listeners',()=>{
  const{editor,open,root,errors,button,menu}=setup({font:()=>{throw new Error('font unavailable')}})
  const composing=vi.spyOn(editor.view,'composing','get').mockReturnValue(true);expect(open().defaultPrevented).toBe(false);expect(root.querySelector('[role=menu]')).toBeNull();composing.mockReturnValue(false)
  open();button('font').click();expect((errors[0] as Error).message).toBe('font unavailable')
  open();document.body.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));expect(root.querySelector('[role=menu]')).toBeNull();menu.dispose();expect(open().defaultPrevented).toBe(false)
 })
 it('finds the clicked image DOM even when coordinate resolution lands after its atom',()=>{
  const{editor,open,button}=setup({viewImage:()=>{}},()=>null,{type:'doc',content:[{type:'docParagraph',content:[{type:'docInlineImage',attrs:{dataUrl:'data:image/png;base64,AA=='}},{type:'text',text:'after'}]}]})
  const img=editor.view.dom.querySelector('img')!;open(2,img)
  expect(editor.state.selection.constructor.name).toBe('NodeSelection');expect(editor.state.selection.from).toBe(1);expect(button('viewImage').disabled).toBe(false)
 })
 it('uses field/link/list/table eligibility and supplies the whole pointed link range',()=>{
  let href='';const{editor,open,button,root}=setup({openLink:t=>{href=t.link!.href}},()=>null,{type:'doc',content:[{type:'docListItem',attrs:{kind:'ordered'},content:[{type:'text',text:'Linked',marks:[{type:'link',attrs:{href:'https://example.com'}},{type:'instrField',attrs:{instr:' DATE '}}]}]}]})
  open(3);expect(button('restartNumbering')).not.toBeNull();expect(button('editField')).not.toBeNull();expect(root.querySelector('[data-context-action=tableProperties]')).toBeNull();expect(root.querySelector('[data-context-action=link]')).toBeNull();expect(button('openLink').disabled).toBe(false);button('openLink').click();expect(href).toBe('https://example.com');expect(editor.state.doc.textContent).toBe('Linked')
 })
 it('uses engine-specific disabled reasons and permits keyboard ContextMenu only inside the editor',()=>{
  const{editor,root,button}=setup({font:{run:()=>{throw new Error('must not run')},reason:()=> '请先保存'}})
  editor.view.dom.dispatchEvent(new KeyboardEvent('keydown',{key:'ContextMenu',bubbles:true,cancelable:true}));expect(button('font').disabled).toBe(true);expect(button('font').title).toBe('请先保存')
  document.body.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));const event=new KeyboardEvent('keydown',{key:'ContextMenu',bubbles:true,cancelable:true});root.dispatchEvent(event);expect(event.defaultPrevented).toBe(false)
 })
 it('does not enable new comment at an empty paragraph caret',()=>{
  const{open,button}=setup({newComment:()=>{}},()=>null,{type:'doc',content:[{type:'docParagraph'}]});open(1);expect(button('newComment').disabled).toBe(true)
 })

 it('offers table commands for a whole-table keyboard selection and preserves that selection',()=>{
  const{editor,root,button,open,menu}=setup({tableProperties:()=>{}},()=>null,{type:'doc',content:[{type:'docTable',content:[{type:'docTableRow',content:[{type:'docTableCell',content:[{type:'docParagraph',content:[{type:'text',text:'cell'}]}]}]}]},{type:'docParagraph'}]})
  editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc,0)));const selection=editor.state.selection
  editor.view.dom.dispatchEvent(new KeyboardEvent('keydown',{key:'ContextMenu',bubbles:true,cancelable:true}));expect(root.querySelector('[role=menu]')).not.toBeNull();expect(button('tableProperties')).not.toBeNull();expect(button('tableProperties').disabled).toBe(false);expect(editor.state.selection.eq(selection)).toBe(true)
  menu.close();expect(open(4,editor.view.dom.querySelector<HTMLElement>('td p')!).defaultPrevented).toBe(true);expect(button('tableProperties').disabled).toBe(false)
 })

 it.each(['nested-editor','nested-table'] as const)('leaves the browser menu untouched inside a %s island',kind=>{
  const{editor,open,root}=setup({paste:()=>{editor.commands.insertContent('WRONG ROOT')}})
  const island=editor.view.dom.appendChild(document.createElement('div'));island.className=kind==='nested-editor'?'ProseMirror':'doc-nested-table';island.contentEditable='true'
  const text=island.appendChild(document.createElement('span'));text.textContent='Nested editor content'
  const selection=editor.state.selection,doc=editor.state.doc,event=open(2,text)
  expect(event.defaultPrevented).toBe(false);expect(root.querySelector('[role=menu]')).toBeNull();expect(editor.state.selection.eq(selection)).toBe(true);expect(editor.state.doc).toBe(doc)
  const keyboard=new KeyboardEvent('keydown',{key:'ContextMenu',bubbles:true,cancelable:true});text.dispatchEvent(keyboard);expect(keyboard.defaultPrevented).toBe(false);expect(root.querySelector('[role=menu]')).toBeNull()
 })

 it('shows the supplied native scope label and description while disabled reasons remain exact',()=>{
  let reason:string|null=null
  const{editor,open,button,menu}=setup({acceptRevision:{run:()=>{},label:'接受所选受支持的正文修订',description:'仅处理当前选区内可写回的正文插入与删除修订',reason:()=>reason}})
  open();const action=button('acceptRevision');expect(action.textContent).toBe('接受所选受支持的正文修订');expect(action.title).toBe('仅处理当前选区内可写回的正文插入与删除修订');expect(action.getAttribute('aria-description')).toBe(action.title)
  reason='请先保存当前编辑';menu.refresh();expect(action.disabled).toBe(true);expect(action.title).toBe(reason);expect(action.getAttribute('aria-description')).toBe(reason);expect(editor.state.doc.textContent).toBe('First textSecond')
 })

})
