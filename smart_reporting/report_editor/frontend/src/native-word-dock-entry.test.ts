import { beforeEach, expect, it, vi } from 'vitest'
const state=vi.hoisted(()=>({context:vi.fn(),view:vi.fn(),options:undefined as any}))
vi.mock('./native-api',()=>({createNativeApi:()=>({context:state.context})}))
vi.mock('./docx-main',()=>({createDocxEditorView:(_shell:unknown,options:unknown)=>{state.options=options;return state.view()}}))
import { startNativeEditor } from './native-main'
beforeEach(()=>{
  document.body.innerHTML='<div id="app"></div>';localStorage.clear();window.history.replaceState({},'', '/reports/v1/native/doc/1')
  state.context.mockResolvedValue({context:{documentId:'doc',revision:1,format:'docx',sourceFile:{sha256:'a'.repeat(64),size:10},scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},csrfToken:'csrf',editingEnabled:true,aiEnabled:true,wordReadAIEnabled:true})
  state.view.mockResolvedValue({refresh:vi.fn(),setSaving:vi.fn(),flushPendingEdits:vi.fn(),getReadSelection:()=>[]})
})
it('Word 正文独立停靠，工具栏入口及审阅入口统一切换阅读和编辑',async()=>{
  await startNativeEditor()
  const workspace=document.querySelector<HTMLElement>('.office-task-workspace')!,dock=workspace.querySelector<HTMLElement>('.office-task-dock')!
  const reader=dock.querySelector<HTMLElement>('.native-word-assistant')!,editor=dock.querySelector<HTMLElement>('.native-ai:not(.native-word-assistant)')!
  expect(workspace.querySelector('.office-task-main')).not.toBeNull()
  expect(workspace.querySelector('.toolbar')).toBeNull();expect(dock.hidden).toBe(true)
  const read=document.querySelector<HTMLButtonElement>('[data-action=word-read-ai]')!,edit=document.querySelector<HTMLButtonElement>('[data-action=word-edit-ai]')!
  expect(read.querySelector('svg')).not.toBeNull();expect(edit.querySelector('svg')).not.toBeNull()
  read.click();await vi.waitFor(()=>expect(reader.hidden).toBe(false));expect(editor.hidden).toBe(true)
  edit.click();await vi.waitFor(()=>expect(reader.hidden).toBe(true));expect(editor.hidden).toBe(false)
  dock.querySelector<HTMLButtonElement>('[aria-label="收起 AI 助手"]')!.click();expect(dock.hidden).toBe(true)
  state.options.onReviewAI({sourceId:'source',targetId:'comment'},'请回复')
  await vi.waitFor(()=>expect(dock.hidden).toBe(false));expect(editor.hidden).toBe(false)
  expect(editor.querySelector('textarea')!.value).toBe('请回复')
  window.dispatchEvent(new Event('pagehide'))
  expect(document.querySelector('.office-task-workspace')).toBeNull()
})
