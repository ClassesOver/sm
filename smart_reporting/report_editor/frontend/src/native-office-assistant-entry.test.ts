import { expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'

it('保留 XLSX 加载期间点击，助手挂载后打开并聚焦，且不发起模型请求', async () => {
  let open: (() => void) | undefined
  let ready!: (view: { dispose(): void }) => void
  const pending = new Promise<{ dispose(): void }>(resolve => { ready = resolve })
  vi.doMock('./workbook-main', () => ({ createWorkbookEditorView: (_shell: unknown, options: { onAssistant: () => void }) => { open = options.onAssistant; return pending } }))
  const host = document.body.appendChild(document.createElement('main'))
  const draft = new NativeDraft({ documentId:'doc', revision:1, sourceSha256:'a'.repeat(64), scope:{database:'d',companyId:'c',userId:'u',threadId:'t'} }, localStorage)
  const api = { officeAIStart: vi.fn(), officeAICancel: vi.fn() }
  const { createNativeOfficeView } = await import('./native-office-view')
  try {
    const creating = createNativeOfficeView({ editor:host } as never, { api:api as never, draft, context:{ editingEnabled:true, officeReadAIEnabled:true, context:{format:'xlsx',sourceFile:{sha256:'a'.repeat(64)}} } as never })
    await vi.waitFor(() => expect(open).toBeTypeOf('function'))
    open!()
    const dispose = vi.fn(); ready({dispose})
    const view = await creating
    const panel = host.parentElement!.querySelector<HTMLElement>('.native-office-assistant')!
    expect(panel.hidden).toBe(false)
    expect(document.activeElement).toBe(panel.querySelector('textarea'))
    expect(api.officeAIStart).not.toHaveBeenCalled()
    view.dispose(); expect(dispose).toHaveBeenCalledOnce()
  } finally { vi.doUnmock('./workbook-main'); host.remove(); localStorage.clear() }
})
