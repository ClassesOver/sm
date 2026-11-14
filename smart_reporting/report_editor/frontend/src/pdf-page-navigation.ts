/** Reading-only desktop navigation. Never handles keys from document controls. */
export function bindPdfPageNavigation(viewport: HTMLElement, options: {
  signal: AbortSignal
  available(): boolean
  pages(): readonly { pageId: string }[]
  activePage(): string
  navigate(pageId: string): void
}) {
  let pointerDown = false
  const view = viewport.ownerDocument.defaultView!
  viewport.addEventListener('pointerdown', () => { pointerDown = true }, { signal: options.signal })
  for (const type of ['pointerup', 'pointercancel', 'blur']) {
    view.addEventListener(type, () => { pointerDown = false }, { signal: options.signal })
  }
  viewport.addEventListener('keydown', event => {
    if (event.target !== viewport || event.defaultPrevented || event.isComposing || event.keyCode === 229
      || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || pointerDown || !options.available()) return
    // A modal can be open while focus is being restored to the canvas.
    if (viewport.ownerDocument.querySelector('dialog[open], [aria-modal="true"]:not([hidden])')) return
    const pages = options.pages()
    const current = pages.findIndex(page => page.pageId === options.activePage())
    if (current < 0) return
    let next: number
    switch (event.key) {
      case 'PageDown': next = Math.min(current + 1, pages.length - 1); break
      case 'PageUp': next = Math.max(current - 1, 0); break
      case 'Home': next = 0; break
      case 'End': next = pages.length - 1; break
      default: return
    }
    event.preventDefault()
    options.navigate(pages[next]!.pageId)
  }, { signal: options.signal })
}
