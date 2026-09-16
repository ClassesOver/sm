export function scrollProgress(scrollTop: number, scrollHeight: number, viewportHeight: number) {
  const available = scrollHeight - viewportHeight
  if (available <= 0) return 100
  return Math.min(100, Math.max(0, Math.round((scrollTop / available) * 100)))
}

export function createScrollProgressController(element: HTMLElement) {
  const update = () => {
    const root = document.documentElement
    const progress = scrollProgress(window.scrollY, root.scrollHeight, window.innerHeight)
    element.style.width = `${progress}%`
    element.setAttribute('aria-valuenow', String(progress))
  }
  window.addEventListener('scroll', update, { passive: true })
  window.addEventListener('resize', update)
  update()
  return { update }
}

export function createBackToTopController(button: HTMLButtonElement, threshold = 600) {
  const update = () => { button.hidden = window.scrollY < threshold }
  button.addEventListener('click', () => {
    const reducedMotion =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' })
  })
  window.addEventListener('scroll', update, { passive: true })
  update()
  return { update }
}
