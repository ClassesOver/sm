import { afterEach, expect, it, vi } from 'vitest'
import { bindNativeWordAssistant } from './native-word-assistant'
import { bindNativeOfficeAssistant } from './native-office-assistant'
import { bindNativePDFAssistant } from './native-pdf-assistant'
import { NativeDraft } from './native-draft'

afterEach(() => { document.body.replaceChildren(); localStorage.clear() })

it.each(['docx', 'xlsx', 'pptx', 'pdf'] as const)('%s 助手统一控件布局，Esc 关闭后返回入口，输入法 Esc 不关闭', format => {
  const root = document.body.appendChild(document.createElement('main'))
  const entry = root.appendChild(document.createElement('button')); entry.className = 'office-ai-entry'
  const draft = new NativeDraft({documentId:'read',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
  const api = {wordAIStart:vi.fn(),officeAIStart:vi.fn(),pdfAIStart:vi.fn()}
  const common = {api:api as never,draft}
  const binding = format === 'docx' ? bindNativeWordAssistant(root,{...common,selection:()=>[],flushPendingEdits:vi.fn()})
    : format === 'pdf' ? bindNativePDFAssistant(root,{...common,selection:()=>[],onNavigate:vi.fn()})
    : bindNativeOfficeAssistant(root,{...common,format,context:async()=>({operations:[],selection:null})})
  entry.focus(); binding.open()
  const panel=root.querySelector<HTMLElement>('.native-ai-panel')!, input=panel.querySelector('textarea')!
  expect(document.activeElement).toBe(input)
  input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true}))
  expect(panel.hidden).toBe(false)
  input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))
  expect(panel.hidden).toBe(true)
  expect(document.activeElement).toBe(entry)
  binding.open()
  expect(panel.querySelector('[role=status]')?.textContent).toBe('')
  expect(panel.querySelector('.office-assistant-details summary')?.textContent).toBe('阅读范围与限制')
  expect(panel.querySelector('.office-assistant-header h3')?.textContent).toContain('AI 助手')
  const close=panel.querySelector<HTMLButtonElement>('.office-assistant-close')!
  expect(close.querySelector('svg')).not.toBeNull()
  expect(close.getAttribute('aria-label')).toBe('关闭助手')
  expect(panel.querySelector('.office-assistant-actions button')?.textContent).toContain('开始阅读')
  close.click();expect(panel.hidden).toBe(true);expect(document.activeElement).toBe(entry)
  expect(api.wordAIStart).not.toHaveBeenCalled();expect(api.officeAIStart).not.toHaveBeenCalled();expect(api.pdfAIStart).not.toHaveBeenCalled()
  binding.dispose()
})

it('PDF 停靠栏展开后再聚焦，避免隐藏祖先吞掉首次焦点', async () => {
  const { mountPdfTaskDock } = await import('./pdf-ai-dock')
  const root = document.body.appendChild(document.createElement('main')), layout = root.appendChild(document.createElement('div'))
  const draft = new NativeDraft({documentId:'dock',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},localStorage)
  const binding = bindNativePDFAssistant(root,{api:{} as never,draft,selection:()=>[],onNavigate:vi.fn()})
  const dock = mountPdfTaskDock(root,layout,{read:binding})
  const input = root.querySelector('textarea')!, visibleAtFocus:boolean[] = []
  const focus = vi.spyOn(input,'focus').mockImplementation(() => { visibleAtFocus.push(!root.querySelector<HTMLElement>('.pdf-ai-dock')!.hidden) })
  binding.open();await Promise.resolve();await Promise.resolve()
  expect(visibleAtFocus.at(-1)).toBe(true)
  focus.mockRestore();dock.dispose();binding.dispose()
})
