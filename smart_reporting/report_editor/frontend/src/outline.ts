export interface OutlineItem {
  text: string
  level: number
  id: string
}

export function reorderMarkdownSections(markdown: string, from: number, to: number): string {
  const trailingNewline = markdown.endsWith('\n')
  const lines = markdown.split('\n')
  if (markdown.endsWith('\n')) lines.pop()
  let fence: '`' | '~' | null = null
  const headings = lines
    .map((line, index) => {
      const marker = /^\s*(`{3,}|~{3,})/.exec(line)?.[1]?.[0] as '`' | '~' | undefined
      if (marker && (!fence || fence === marker)) {
        fence = fence ? null : marker
        return { index, level: 0 }
      }
      return { index, level: fence ? 0 : /^(#{1,6})\s+/.exec(line)?.[1].length ?? 0 }
    })
    .filter((heading) => heading.level > 0)
  if (from < 0 || to < 0 || from >= headings.length || to >= headings.length) return markdown
  const source = headings[from]
  const sectionEnd = (headingIndex: number) => {
    const level = headings[headingIndex].level
    return headings.slice(headingIndex + 1).find((heading) => heading.level <= level)?.index ?? lines.length
  }
  const sourceEnd = sectionEnd(from)
  const targetHeading = headings[to]
  if (source.level !== targetHeading.level) return markdown
  const targetEnd = sectionEnd(to)
  const reordered = source.index < targetHeading.index ? [
      ...lines.slice(0, source.index),
      ...lines.slice(targetHeading.index, targetEnd),
      ...lines.slice(sourceEnd, targetHeading.index),
      ...lines.slice(source.index, sourceEnd),
      ...lines.slice(targetEnd),
    ] : [
    ...lines.slice(0, targetHeading.index),
    ...lines.slice(source.index, sourceEnd),
    ...lines.slice(targetEnd, source.index),
    ...lines.slice(targetHeading.index, targetEnd),
    ...lines.slice(sourceEnd),
  ]
  const result = reordered.join('\n')
  return trailingNewline && !result.endsWith('\n') ? `${result}\n` : result
}

interface OutlineElements {
  container: HTMLElement
  editor: HTMLElement
  toggle: HTMLButtonElement
  getMarkdown?: () => string
  replaceMarkdown?: (markdown: string) => void
  onActive?: (item: OutlineItem) => void
  initialCollapsed?: boolean
  onCollapsedChange?: (collapsed: boolean) => void
}

export function createOutlineController({
  container,
  editor,
  toggle,
  getMarkdown,
  replaceMarkdown,
  onActive,
  initialCollapsed,
  onCollapsedChange,
}: OutlineElements) {
  const list = container.querySelector<HTMLElement>('.outline-list')
  if (!list) throw new Error('report outline list is missing')
  let currentItems: OutlineItem[] = []
  let hasRendered = false
  let previousMarkdown: string | null = null
  const undo = document.createElement('button')
  undo.type = 'button'; undo.className = 'outline-undo'; undo.textContent = '撤销排序'; undo.hidden = true
  container.querySelector('.outline-heading')?.append(undo)
  undo.addEventListener('click', () => { if (previousMarkdown !== null) { replaceMarkdown?.(previousMarkdown); previousMarkdown = null; undo.hidden = true } })

  const setCollapsed = (collapsed: boolean, notify = false) => {
    container.classList.toggle('is-collapsed', collapsed)
    container.parentElement?.classList.toggle('outline-collapsed', collapsed)
    toggle.setAttribute('aria-expanded', String(!collapsed))
    if (notify) onCollapsedChange?.(collapsed)
  }

  setCollapsed(initialCollapsed ?? container.classList.contains('is-collapsed'))

  toggle.addEventListener('click', () =>
    setCollapsed(!container.classList.contains('is-collapsed'), true),
  )

  const setActive = (index: number) => {
    list.querySelectorAll('.outline-link').forEach((item, itemIndex) => {
      if (itemIndex === index) item.setAttribute('aria-current', 'location')
      else item.removeAttribute('aria-current')
    })
    const active = currentItems[index]
    if (active) onActive?.(active)
  }

  return {
    update(items: OutlineItem[]) {
      if (
        hasRendered &&
        items.length === currentItems.length &&
        items.every((item, index) => {
          const current = currentItems[index]
          return current?.id === item.id && current.level === item.level && current.text === item.text
        })
      ) {
        return
      }
      hasRendered = true
      currentItems = items
      list.replaceChildren(
        ...items.map((item, index) => {
          const button = document.createElement('button')
          button.type = 'button'
          button.draggable = Boolean(getMarkdown && replaceMarkdown)
          button.className = `outline-link level-${Math.min(3, Math.max(1, item.level))}`
          button.textContent = item.text || '未命名章节'
          button.addEventListener('click', () => {
            setActive(index)
            const headings = editor.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')
            const target =
              (item.id
                ? Array.from(editor.querySelectorAll<HTMLElement>('[id]')).find(
                    (element) => element.id === item.id,
                  )
                : null) ?? headings[index]
            if (target && typeof target.scrollIntoView === 'function') {
              const reducedMotion =
                typeof window.matchMedia === 'function' &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches
              target.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
            }
            if (window.innerWidth <= 768) setCollapsed(true)
          })
          button.addEventListener('keydown', (event) => {
            if (!getMarkdown || !replaceMarkdown || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return
            const step = event.key === 'ArrowUp' ? -1 : 1
            const target = index + step
            if (target < 0 || target >= items.length || items[target].level !== item.level) return
            event.preventDefault()
            replaceMarkdown(reorderMarkdownSections(getMarkdown(), index, target))
          })
          if (getMarkdown && replaceMarkdown) {
            button.addEventListener('dragstart', (event) => {
              event.dataTransfer?.setData('text/plain', String(index))
              button.classList.add('is-dragging')
            })
            button.addEventListener('dragend', () => button.classList.remove('is-dragging'))
            button.addEventListener('dragover', (event) => { event.preventDefault(); button.classList.add('is-drag-over') })
            button.addEventListener('dragleave', () => button.classList.remove('is-drag-over'))
            button.addEventListener('drop', (event) => {
              event.preventDefault()
              button.classList.remove('is-drag-over')
              const from = Number(event.dataTransfer?.getData('text/plain'))
              if (!Number.isInteger(from) || from === index || items[from]?.level !== item.level) return
              previousMarkdown = getMarkdown()
              replaceMarkdown(reorderMarkdownSections(previousMarkdown, from, index))
              undo.hidden = false
            })
          }
          return button
        }),
      )
      container.classList.toggle('is-empty', items.length === 0)
      let count = container.querySelector<HTMLElement>('.outline-count')
      if (!count) { count = document.createElement('div'); count.className = 'outline-count'; container.append(count) }
      count.textContent = `${items.length} 个章节`
      let hint = container.querySelector<HTMLElement>('.outline-empty-hint')
      if (items.length === 0) {
        if (!hint) { hint = document.createElement('div'); hint.className = 'outline-empty-hint'; container.append(hint) }
        hint.textContent = '使用 Markdown 标题创建章节'
      } else hint?.remove()
    },
    setActive,
  }
}
