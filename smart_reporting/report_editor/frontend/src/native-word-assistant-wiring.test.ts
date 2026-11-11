import { beforeEach, expect, it, vi } from 'vitest'
const state=vi.hoisted(()=>({context:vi.fn(),word:vi.fn(),edit:vi.fn(),selection:vi.fn(),flush:vi.fn(),readSelection:vi.fn(),open:vi.fn(),dispose:vi.fn(),options:undefined as any}))
vi.mock('./native-api',()=>({createNativeApi:()=>({context:state.context})}))
vi.mock('./docx-main',()=>({createDocxEditorView:async (_shell:unknown,options:unknown)=>{state.options=options;return {setSaving:vi.fn(),flushPendingEdits:state.flush,getReadSelection:state.readSelection}}}))
vi.mock('./native-session',()=>({bindNativeSession:()=>({update:vi.fn(),dispose:vi.fn()})}))
vi.mock('./native-ai',()=>({bindNativeAI:state.edit}))
vi.mock('./native-word-assistant',()=>({bindNativeWordAssistant:state.word}))
import {startNativeEditor} from './native-main'
beforeEach(()=>{
 document.body.innerHTML='<div id="app"></div>';window.history.replaceState({},'', '/reports/v1/native/doc/1');vi.clearAllMocks()
 state.context.mockResolvedValue({context:{documentId:'doc',revision:1,format:'docx',sourceFile:{sha256:'a'.repeat(64),size:10},scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},csrfToken:'csrf',editingEnabled:false,wordReadAIEnabled:true})
 state.word.mockImplementation((root:HTMLElement)=>{
  const panel=document.createElement('section');panel.className='native-word-assistant';panel.hidden=true;root.append(panel)
  return {open:state.open,dispose:state.dispose}
 });state.edit.mockReturnValue({setSelection:state.selection,dispose:vi.fn()})
})
it('Word 阅读独立于编辑开关，图标入口可访问并同步当前选区和待提交编辑',async()=>{
 await startNativeEditor();expect(state.word).toHaveBeenCalled();expect(state.edit).not.toHaveBeenCalled()
 const options=state.word.mock.calls[0][1];state.readSelection.mockReturnValue([{blockId:'b1',cellId:'c1'}]);state.options.onSelectionChange([{blockId:'whole-table-from-editing'}]);expect(options.selection()).toEqual([{blockId:'b1',cellId:'c1'}])
 options.flushPendingEdits();expect(state.flush).toHaveBeenCalled()
 const entry=document.querySelector<HTMLButtonElement>('[data-action=word-read-ai]')!;expect(entry).not.toBeNull();expect(entry.querySelector('svg')).not.toBeNull();entry.click();expect(state.open).toHaveBeenCalledWith('ask')
 window.dispatchEvent(new Event('pagehide'))
})
