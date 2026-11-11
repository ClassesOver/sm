import { afterEach, expect, it, vi } from 'vitest'
import { createNativeOfficeView } from './native-office-view'

const editor = vi.hoisted(() => ({ create: vi.fn() }))
vi.mock('./slides-main', () => ({ createSlidesEditorView: editor.create }))
vi.mock('./slides-native-ai', () => ({ createSlidesNativeAIClient: () => ({ start: vi.fn() }) }))
afterEach(() => { vi.clearAllMocks(); document.body.replaceChildren() })

it.each([false, true])('PPTX 编辑助手入口和客户端同时遵循 aiEnabled=%s', async aiEnabled => {
  const host = document.createElement('div'); document.body.append(host)
  const view = { ready: Promise.resolve(), dispose: vi.fn() }
  editor.create.mockReturnValue(view)
  const result = await createNativeOfficeView({ editor: host } as never, {
    api: {} as never, draft: {} as never,
    context: { editingEnabled: true, aiEnabled, csrfToken: 'csrf', context: { format: 'pptx', documentId: 'deck', revision: 1, sourceFile: { sha256: 'a'.repeat(64) } } } as never,
  })
  const forwarded = editor.create.mock.calls[0]![1]
  expect(typeof forwarded.onAssistant === 'function').toBe(aiEnabled)
  expect(Boolean(forwarded.nativeAI)).toBe(aiEnabled)
  result.dispose(); expect(view.dispose).toHaveBeenCalledOnce()
})
