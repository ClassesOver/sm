import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesEditorView } from './slides-main'
import { createEditorShell } from './shell'
import { NativeDraft } from './native-draft'
import { pickSlideImage, prepareSlideImage } from './slides-native-images'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
vi.mock('./slides-native-images', () => ({ pickSlideImage: vi.fn(), prepareSlideImage: vi.fn() }))
afterEach(() => { document.body.innerHTML = ''; vi.unstubAllGlobals(); vi.resetAllMocks() })

it('stages a selected local image as a paragraph bullet and rejects a stale selection', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const sha256 = 'a'.repeat(64)
  const draft = new NativeDraft({ documentId: 'picture-bullet', revision: 1, sourceSha256: sha256,
    scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } },
  { getItem: () => null, setItem() {}, removeItem() {} })
  const app = document.body.appendChild(document.createElement('main'))
  const shell = createEditorShell(app, 'full', 'pptx')
  const slides = ['first', 'second'].map((id, slideIndex) => ({
    slideIndex, elements: [{ id, name: id, type: 'text', text: id, editable: true }],
  }))
  const view = createSlidesEditorView(shell.editor, { native: true, draft, save: shell.save, download: shell.exportPptx,
    request: async path => (path === 'deck' ? { revision: 1, sha256, size: { cx: 9144000, cy: 5143500 }, slides } : { slides: [] }) as never })
  const file = new File(['png fixture'], 'bullet.png', { type: 'image/png' })
  const image = { extension: 'png' as const, bytesBase64: 'aW1hZ2U=', descr: 'bullet.png',
    geometry: { x: 0, y: 0, width: 1, height: 1 } }
  vi.mocked(prepareSlideImage).mockResolvedValue(image)
  let finish!: (file: File | null) => void
  vi.mocked(pickSlideImage).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValueOnce(file)
  try {
    await view.ready
    const control = app.querySelector<HTMLButtonElement>('[data-command="pictureBullet"]')!
    expect(control.disabled).toBe(false)
    control.click()
    app.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="1"]')!.click()
    finish(file)
    await Promise.resolve()
    expect(prepareSlideImage).not.toHaveBeenCalled()
    expect(draft.operations).toEqual([])
    control.click()
    await vi.waitFor(() => expect(draft.operations[0]).toMatchObject({ paragraphFormatting: [
      { slideIndex: 1, elementId: 'second', bullet: 'blip', bulletImage: { bytesBase64: image.bytesBase64, extension: 'png' } },
    ] }))
  } finally { view.dispose() }
})
