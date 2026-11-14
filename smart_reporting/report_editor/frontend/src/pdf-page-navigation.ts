/** Reading-only desktop navigation. Never handles keys from document controls. */
export function bindPdfPageNavigation(viewport: HTMLElement, options: {
  signal: AbortSignal
  available(): boolean
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
  viewport.addEventListener('pointerdown', () => { invalidate(); pointerDown = true }, { signal: options.signal })
  for (const type of ['wheel', 'pointerdown', 'touchstart']) view.addEventListener(type, invalidate, { capture: true, passive: true, signal: options.signal })
  view.addEventListener('blur', invalidate, { signal: options.signal })
  viewport.addEventListener('focusout', invalidate, { signal: options.signal })
  for (const type of ['pointerup', 'pointercancel', 'blur']) {
    view.addEventListener(type, () => { pointerDown = false }, { signal: options.signal })
  }
  viewport.addEventListener('keydown', event => {
    if (event.target !== viewport) return
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229
      || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || pointerDown) { invalidate(); return }
    if (!options.available()) { invalidate(); return }
    // A modal can be open while focus is being restored to the canvas.
    if (viewport.ownerDocument.querySelector('dialog[open], [aria-modal="true"]:not([hidden])')) { invalidate(); return }
    const paging = event.key === 'PageUp' || event.key === 'PageDown'
    const pages: readonly { pageId: string; pageIds?: readonly string[] }[] = paging ? options.readingRows?.() ?? options.pages() : options.pages()
    if (intent?.key !== key()) invalidate()
    const currentId = intent?.pageId ?? options.readingPage()
    const current = pages.findIndex(page => page.pageId === currentId || page.pageIds?.includes(currentId))
    if (current < 0) return
    let next: number
    switch (event.key) {
      case 'PageDown': next = current + 1 < pages.length ? current + 1 : current; break
      case 'PageUp': next = Math.max(current - 1, 0); break
      case 'Home': next = 0; break
      case 'End': next = pages.length - 1; break
      default: invalidate(); return
    }
    event.preventDefault()
    // At the first/last page, consume paging without scrolling back to its top.
    if (next !== current || event.key === 'Home' || event.key === 'End') {
      const pageId = pages[next]!.pageId
      options.navigate(pageId)
      recordNavigation(pageId)
    }
  }, { signal: options.signal })
  return { recordNavigation, invalidate }
}
