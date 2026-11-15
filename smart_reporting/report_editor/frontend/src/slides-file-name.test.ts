import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'
import type { NativeOfficeReadTask } from './native-api'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
afterEach(() => { document.body.innerHTML = ''; document.documentElement.lang = ''; vi.unstubAllGlobals() })

it.each([['en-US', 'en'], ['zh-CN', 'zh-CN'], ['zh-Hant-HK', 'zh-TW']])('uses %s for naming and leaves saving to the dialog', async (language, nameLocale) => {
  document.documentElement.lang = language
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const sha256 = 'a'.repeat(64)
  const draft = new NativeDraft({ documentId: 'slides', revision: 1, sourceSha256: sha256,
    scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }, localStorage)
  const completed: NativeOfficeReadTask = { taskId: 'naming', clientRequestId: 'request', status: 'completed',
    result: { answer: 'Drafts/Quarterly Results.pptx', sourceSha256: sha256, effectiveSha256: sha256,
      readingVersion: 'source', citations: [], issues: [],
      coverage: { scope: 'document', fullyReadBlockIds: [], totalBlocks: 0, scopeReadComplete: false } } }
  const officeAIStart = vi.fn(async () => ({ ...completed, status: 'running' as const }))
  const officeAIStatus = vi.fn(async () => completed)
  const officeAICancel = vi.fn(async () => completed)
  const saveAs = vi.fn()
  const app = document.createElement('main')
  document.body.append(app)
  const shell = createEditorShell(app, 'full', 'pptx')
  const view = createSlidesEditorView(shell.editor, { native: true, draft, saveAs,
    save: shell.save, download: shell.exportPptx, slideNaming: { officeAIStart, officeAIStatus, officeAICancel },
    request: async path => (path === 'deck' ? { revision: 1, sha256, size: { cx: 9144000, cy: 5143500 },
      slides: [{ slideIndex: 0, elements: [] }] } : { slides: [] }) as never })
  try {
    await view.ready
    const command = app.querySelector<HTMLButtonElement>('[data-source-action="onNameWithAi"]')!
    expect(command.disabled).toBe(false)
    command.click()
    for (let turn = 0; turn < 8; turn++) await Promise.resolve()
    expect(app.querySelector<HTMLInputElement>('input[name="filename"]')!.value).toBe('Quarterly Results.pptx')
    expect(officeAIStart).toHaveBeenCalledWith(expect.objectContaining({
      action: 'fileName', nameLocale, expectedSha256: sha256, operations: [], selection: null,
    }), expect.any(AbortSignal))
    expect(officeAIStatus).toHaveBeenCalledWith('naming', expect.any(AbortSignal))
    expect(saveAs).not.toHaveBeenCalled()
  } finally {
    view.dispose()
  }
})
