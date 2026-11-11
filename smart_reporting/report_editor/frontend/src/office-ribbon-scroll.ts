/** 仅接管功能区溢出；输入框、触控板横滑和浏览器缩放保留原生行为。 */
export function bindOfficeRibbonScroll(root: HTMLElement): () => void {
  const viewport = (target: EventTarget | null) => {
    const element = target instanceof Element ? target.closest<HTMLElement>('[role=tabpanel], [role=tablist]') : null
    return element && root.contains(element) && element.scrollWidth > element.clientWidth + 1 ? element : null
  }
  const onWheel = (event: WheelEvent) => {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return
    if (event.target instanceof Element && event.target.closest('input, select, textarea, [contenteditable=true], [role=menu], [role=listbox], [data-rb-panel], [popover]')) return
    const panel = viewport(event.target)
    if (!panel) return
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? panel.clientWidth : 1)
    const next = Math.max(0, Math.min(panel.scrollWidth - panel.clientWidth, panel.scrollLeft + delta))
    if (next === panel.scrollLeft) return
    event.preventDefault()
    panel.scrollLeft = next
  }
  const onFocus = (event: FocusEvent) => {
    const panel = viewport(event.target)
    if (!panel || !(event.target instanceof HTMLElement)) return
    const outer = panel.getBoundingClientRect(), inner = event.target.getBoundingClientRect()
    const delta = inner.left < outer.left + 6 ? inner.left - outer.left - 6 : inner.right > outer.right - 6 ? inner.right - outer.right + 6 : 0
    panel.scrollLeft = Math.max(0, Math.min(panel.scrollWidth - panel.clientWidth, panel.scrollLeft + delta))
  }
  root.addEventListener('wheel', onWheel, { passive: false })
  root.addEventListener('focusin', onFocus)
  return () => { root.removeEventListener('wheel', onWheel); root.removeEventListener('focusin', onFocus) }
}
