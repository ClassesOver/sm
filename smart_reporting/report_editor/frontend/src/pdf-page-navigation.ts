import { navAction } from './genoffice-pdf-key-nav'

/** Reading-only desktop navigation from the canvas or a page thumbnail. */
export function bindPdfPageNavigation(viewport: HTMLElement, options: {
  signal: AbortSignal
  available(): boolean
  thumbnails?: HTMLElement
  pages(): readonly { pageId: string }[]
  readingPage(): string
  readingRows?(): readonly { pageId: string; pageIds?: readonly string[] }[]
  navigationKey?(): string
  navigate(pageId: string): void
}) {
  let pointerDown = false
  let intent: { pageId: string; key: string } | undefined
  const key = () => JSON.stringify([options.navigationKey?.(), options.pages().map(page => page.pageId), options.readingRows?.().map(row => [row.pageId, row.pageIds])])
  const invalidate = () => { intent = undefined }
  const recordNavigation = (pageId: string) => { intent = { pageId, key: key() } }
  const view = viewport.ownerDocument.defaultView!
  const beginPointer = () => { invalidate(); pointerDown = true }
  viewport.addEventListener('pointerdown', beginPointer, { signal: options.signal })
  options.thumbnails?.addEventListener('pointerdown', beginPointer, { signal: options.signal })
  for (const type of ['wheel', 'pointerdown', 'touchstart']) view.addEventListener(type, invalidate, { capture: true, passive: true, signal: options.signal })
  view.addEventListener('blur', invalidate, { signal: options.signal })
  viewport.addEventListener('focusout', invalidate, { signal: options.signal })
  for (const type of ['pointerup', 'pointercancel', 'dragend', 'blur']) {
    view.addEventListener(type, () => { pointerDown = false }, { signal: options.signal })
  }
  const handleKey = (event: KeyboardEvent) => {
    const target = event.target
    const thumbnail = target instanceof view.HTMLButtonElement && target.matches('.pdf-thumbnail[data-page-id]')
      && options.thumbnails?.contains(target) ? target : undefined
    if (target !== viewport && !thumbnail) return
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229
      || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || pointerDown) { invalidate(); return }
    if (!options.available()) { invalidate(); return }
    // A modal can be open while focus is being restored to the canvas.
    if (viewport.ownerDocument.querySelector('dialog[open], [aria-modal="true"]:not([hidden])')) { invalidate(); return }
    const action = navAction(event.key, !!thumbnail)
    if (!action || (thumbnail && action.type !== 'stepPage')) { invalidate(); return }
    if (action.type === 'scrollBy' || event.key === ' ') {
      const delta = action.type === 'scrollBy' ? action.delta : Math.max(0, viewport.clientHeight - 40)
      event.preventDefault()
      invalidate()
      viewport.scrollTop = Math.max(0, Math.min(viewport.scrollTop + delta, viewport.scrollHeight - viewport.clientHeight))
      return
    }
    const paging = action.type === 'scrollViewport' || action.type === 'stepPage'
    const pages: readonly { pageId: string; pageIds?: readonly string[] }[] = paging ? options.readingRows?.() ?? options.pages() : options.pages()
    if (intent?.key !== key()) invalidate()
    const currentId = thumbnail?.dataset.pageId ?? intent?.pageId ?? options.readingPage()
    const current = pages.findIndex(page => page.pageId === currentId || page.pageIds?.includes(currentId))
    if (current < 0) return
    const next = action.type === 'scrollEdge' ? action.edge === 'top' ? 0 : pages.length - 1
      : Math.max(0, Math.min(current + action.dir, pages.length - 1))
    event.preventDefault()
    // At the first/last row, consume paging without scrolling back to its top.
    if (next !== current || action.type === 'scrollEdge') {
      const pageId = pages[next]!.pageId
      options.navigate(pageId)
      if (thumbnail) {
        const nextThumbnail = [...options.thumbnails!.querySelectorAll<HTMLButtonElement>('.pdf-thumbnail[data-page-id]')]
          .find(control => control.dataset.pageId === pageId)
        nextThumbnail?.focus({ preventScroll: true })
        nextThumbnail?.scrollIntoView({ block: 'nearest' })
      }
      recordNavigation(pageId)
    }
  }
  viewport.addEventListener('keydown', handleKey, { signal: options.signal })
  options.thumbnails?.addEventListener('keydown', handleKey, { signal: options.signal })
  return { recordNavigation, invalidate }
}
