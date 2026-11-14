import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { pickSlideImage, prepareSlideImage } from './slides-native-images'

vi.mock('./slides-native-images', async importActual => ({
  ...await importActual<typeof import('./slides-native-images')>(),
  pickSlideImage: vi.fn(), prepareSlideImage: vi.fn(),
}))

beforeEach(() => {
  vi.stubGlobal('ResizeObserver',class {observe(){}disconnect(){}})
  document.body.innerHTML = '<main id="app"></main>'
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
  vi.mocked(pickSlideImage).mockReset(); vi.mocked(prepareSlideImage).mockReset()
})
afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren() })

async function setup(command = 'backgroundImage') {
  const deck = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 },
    slides: [0, 1].map(slideIndex => ({ slideIndex, animations: [], elements: [], backgroundOwn: true })) }
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify(deck)))
  vi.stubGlobal('fetch', fetcher)
  const root = document.querySelector<HTMLElement>('#app')!, shell = createEditorShell(root, 'full', 'pptx')
  const view = createSlidesEditorView(shell.editor, { save: shell.save, download: shell.exportPptx, native: true })
  await vi.waitFor(() => expect(root.querySelectorAll('.slide-open')).toHaveLength(2))
  const opener = root.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!
  opener.focus(); opener.click()
  return { root, shell, fetcher, view, opener, dialog: root.querySelector<HTMLDialogElement>('.slides-bg-image-dialog')! }
}

it.each(['cancel', 'nativeCancel', 'title'])('discards background fields and restores the opener on %s', async action => {
  const { dialog, opener, shell, view } = await setup(), before = shell.statusLabel.textContent
  dialog.querySelector<HTMLInputElement>('[name=from]')!.value = '#ff8800'
  dialog.querySelector<HTMLInputElement>('[name=all]')!.checked = true
  if (action === 'nativeCancel') dialog.dispatchEvent(new Event('cancel', { cancelable: true }))
  else if (action === 'title') {
    const close = dialog.querySelector<HTMLButtonElement>('[aria-label="关闭设置背景格式"]')!
    expect(close).not.toBeNull(); close.click()
  } else dialog.querySelector<HTMLButtonElement>('[value=cancel]')!.click()
  expect(dialog.isConnected).toBe(false); expect(document.activeElement).toBe(opener)
  expect(shell.statusLabel.textContent).toBe(before)
  opener.click()
  const next = document.querySelector<HTMLDialogElement>('.slides-bg-image-dialog')!
  expect(next.querySelector<HTMLInputElement>('[name=from]')!.value).toBe('#ffffff')
  expect(next.querySelector<HTMLInputElement>('[name=all]')!.checked).toBe(false)
  view.dispose()
})

it('separates the background title and actions from named scrolling feedback', async () => {
  const { dialog, view } = await setup()
  expect(dialog.querySelector(':scope > header h3')?.textContent).toBe('设置背景格式')
  expect(dialog.querySelector(':scope > footer button[value=ok]')).not.toBeNull()
  const feedback = dialog.querySelector<HTMLElement>('[role=alert]')!
  expect(feedback.getAttribute('aria-label')).toBe('背景设置错误'); expect(feedback.tabIndex).toBe(0)
  expect(dialog.querySelector('.slides-background-body')).not.toBeNull()
  view.dispose()
})

it('ignores an image selection that resolves after the background dialog closes', async () => {
  let resolvePick!: (file: File) => void
  vi.mocked(pickSlideImage).mockReturnValue(new Promise(resolve => { resolvePick = resolve }))
  vi.mocked(prepareSlideImage).mockResolvedValue({ bytesBase64: 'image', extension: 'png', descr: 'fixture', geometry: { x: 0, y: 0, width: 10, height: 10 } })
  const { dialog, shell, view } = await setup('backgroundImage'), before = shell.statusLabel.textContent
  dialog.querySelector<HTMLButtonElement>('[value=ok]')!.click()
  dialog.querySelector<HTMLButtonElement>('[value=cancel]')!.click()
  resolvePick(new File(['fixture'], 'image.png', { type: 'image/png' }))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(shell.statusLabel.textContent).toBe(before)
  expect(prepareSlideImage).not.toHaveBeenCalled()
  expect(document.querySelector('.structure-pending')?.textContent).not.toContain('背景图片')
  view.dispose()
})

it('prevents duplicate image pickers while one selection is pending', async () => {
  vi.mocked(pickSlideImage).mockReturnValue(new Promise(() => {}))
  const { dialog, view } = await setup('backgroundImage')
  const confirm = dialog.querySelector<HTMLButtonElement>('[value=ok]')!
  confirm.click(); confirm.click()
  expect(pickSlideImage).toHaveBeenCalledTimes(1)
  view.dispose()
})

it('ignores image decoding completed after cancellation', async () => {
  let resolveImage!: (image: Awaited<ReturnType<typeof prepareSlideImage>>) => void
  vi.mocked(pickSlideImage).mockResolvedValue(new File(['fixture'], 'image.png'))
  vi.mocked(prepareSlideImage).mockReturnValue(new Promise(resolve => { resolveImage = resolve }))
  const { dialog, shell, view } = await setup('backgroundImage'), before = shell.statusLabel.textContent
  const confirm = dialog.querySelector<HTMLButtonElement>('[value=ok]')!
  confirm.click()
  await vi.waitFor(() => expect(prepareSlideImage).toHaveBeenCalledTimes(1))
  dialog.querySelector<HTMLButtonElement>('[value=cancel]')!.click()
  resolveImage({ bytesBase64: 'image', extension: 'png', descr: 'fixture', geometry: { x: 0, y: 0, width: 10, height: 10 } })
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(shell.statusLabel.textContent).toBe(before)
  expect(document.querySelector('.structure-pending')?.textContent).not.toContain('背景图片')
  view.dispose()
})

it('keeps gradient colors, direction, graphics and all-page targets in the save payload', async () => {
  const { dialog, shell, fetcher, view } = await setup()
  dialog.querySelector<HTMLSelectElement>('[name=fill]')!.value='gradient'
  dialog.querySelector<HTMLInputElement>('[name=from]')!.value = '#ff8800'
  dialog.querySelector<HTMLInputElement>('[name=to]')!.value = '#004488'
  dialog.querySelector<HTMLSelectElement>('[name=direction]')!.value = '2'
  dialog.querySelector<HTMLInputElement>('[name=graphics]')!.checked = true
  dialog.querySelector<HTMLInputElement>('[name=all]')!.checked = true
  dialog.querySelector<HTMLButtonElement>('[value=ok]')!.click()
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ revision: 2, revisionRegistered: true, validation: { issues: [] } })))
  shell.save.click(); await vi.waitFor(() => expect(shell.statusLabel.textContent).toBe('已保存'))
  const payload = JSON.parse(fetcher.mock.calls.at(-1)![1]!.body as string)
  expect(payload.backgroundGradients).toEqual([{ slideIndices: [0, 1], from: '#FF8800', to: '#004488', angleDeg: 45, radial: false }])
  expect(payload.backgroundGraphics).toEqual([{ slideIndex: 0, hidden: true }, { slideIndex: 1, hidden: true }])
  view.dispose()
})
