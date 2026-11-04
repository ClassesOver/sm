import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update: vi.fn() }) }))

import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'

describe('PPTX live preview', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    document.body.replaceChildren()
  })

  it('keeps one preview request in flight and resends only the latest edits', async () => {
    document.body.innerHTML = '<main id="app"></main>'
    const deck = {
      revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 },
      slides: [{ slideIndex: 0, animations: [], elements: [{
        id: 'title', type: 'text', name: 'title', text: '标题', editable: true,
        geometry: { x: 10, y: 20, width: 300, height: 80 },
      }] }],
    }
    const tree = { slides: [{ slideIndex: 0, nodes: [] }] }
    const previews: { body: { edits: { text?: string }[] }; resolve: () => void }[] = []
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/render-tree') && init?.method === 'POST') {
        return new Promise<Response>(resolve => {
          previews.push({
            body: JSON.parse(init.body as string),
            resolve: () => resolve(new Response(JSON.stringify(tree))),
          })
        })
      }
      if (url.endsWith('/api/render-tree')) return new Response(JSON.stringify(tree))
      return new Response(JSON.stringify(deck))
    })
    vi.stubGlobal('fetch', fetcher)
    const root = document.querySelector<HTMLElement>('#app')!
    const shell = createEditorShell(root, 'full', 'pptx')
    createSlidesEditorView(shell.editor, { save: shell.save, download: shell.exportPptx })
    await vi.waitFor(() => expect(root.querySelector<HTMLElement>('.slides-canvas')!.hidden).toBe(false))
    const text = root.querySelector<HTMLTextAreaElement>('#object-text')!
    const type = (value: string) => { text.value = value; text.dispatchEvent(new Event('input')) }

    type('第一版')
    await vi.waitFor(() => expect(previews).toHaveLength(1), { timeout: 2000 })
    type('第二版')
    await new Promise(resolve => setTimeout(resolve, 550))
    type('第三版')
    await new Promise(resolve => setTimeout(resolve, 550))
    expect(previews).toHaveLength(1)

    previews[0]!.resolve()
    await vi.waitFor(() => expect(previews).toHaveLength(2))
    expect(previews[1]!.body.edits[0]!.text).toBe('第三版')
    previews[1]!.resolve()
    await new Promise(resolve => setTimeout(resolve, 50))
    expect(previews).toHaveLength(2)
  })
})
