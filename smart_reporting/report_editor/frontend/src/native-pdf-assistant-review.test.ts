import { expect, it, vi } from 'vitest'
import { bindNativePDFAssistant } from './native-pdf-assistant'
import { NativeDraft } from './native-draft'

it('旧取消请求失败不得覆写后续任务已完成状态', async () => {
  let rejectCancel!: (reason: Error) => void
  const api = {
    pdfAIStart: vi.fn()
      .mockImplementationOnce(() => new Promise(() => {}))
      .mockResolvedValueOnce({taskId:'new', status:'completed', result:{answer:'新任务成功回答'}}),
    pdfAICancel: vi.fn().mockImplementationOnce(() => new Promise((_, reject) => { rejectCancel = reject })),
  }
  const root = document.createElement('div'); document.body.append(root)
  const draft = new NativeDraft({documentId:'review-read', revision:1, sourceSha256:'a'.repeat(64), scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}, localStorage)
  const binding = bindNativePDFAssistant(root, {api:api as never,draft,selection:()=>[],onNavigate:vi.fn()})
  binding.open('summarize')
  binding.open('keyPoints')
  await vi.waitFor(() => expect(root.querySelector('[role=status]')?.textContent).toContain('阅读完成'))
  rejectCancel(new Error('旧任务取消连接失败'))
  await Promise.resolve(); await Promise.resolve()
  expect(root.querySelector('.native-ai-answer')?.textContent).toBe('新任务成功回答')
  expect(root.querySelector('[role=status]')?.textContent).toContain('阅读完成')
  binding.dispose(); root.remove(); localStorage.clear()
})
