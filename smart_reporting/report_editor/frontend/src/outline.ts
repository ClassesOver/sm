export interface OutlineItem {
  text: string
  level: number
  id: string
}

// 章节标题尾部的 [[analysis:...]] 是工作流编排绑定标记（存在 Markdown 里），
// 目录只展示纯文本标题，剥掉标记并收敛多余空白。
const BINDING_MARKER = /\[\[[^\]]*\]\]/g
export function displayOutlineText(text: string): string {
  return text.replace(BINDING_MARKER, '').replace(/[ \t]{2,}/g, ' ').trim()
}

// 刚插入还没输入文字的标题不进目录：否则大纲会留下"未命名章节"占位噪声，
// 且章节计数与层级结构状态会被空标题干扰。
export function namedOutlineItems(items: OutlineItem[]): OutlineItem[] {
  return items.filter((item) => item.text.trim().length > 0)
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
      // 与 namedOutlineItems 一致只统计有文字的标题，否则空标题（"## "）会让
      // 目录下标与这里的标题下标错位，拖拽移动到错误章节。
      return { index, level: fence ? 0 : /^(#{1,6})[ \t]+\S/.exec(line)?.[1].length ?? 0 }
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
  // 目录条目来自 ProseMirror 文档；#report-editor 里还挂着加载/导出等
  // 隐藏面板的标题。点击导航与滚动跟随的标题索引必须建立在正文
  // （.ProseMirror）内的非空标题上，否则会错位。注意 ProseMirror 挂载
  // 晚于控制器创建，必须每次惰性查询。
  const outlineHeadings = () => {
    const scope = editor.querySelector('.ProseMirror') ?? editor
    return Array.from(scope.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6'))
      .filter((heading) => heading.textContent?.trim())
  }
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

  const collapseAndRestoreFocus = () => {
    setCollapsed(true, true)
    toggle.focus()
  }

  container.querySelector<HTMLButtonElement>('.outline-close')?.addEventListener(
    'click',
    collapseAndRestoreFocus,
  )

  toggle.addEventListener('click', () => {
    const collapsed = !container.classList.contains('is-collapsed')
    setCollapsed(collapsed, true)
    if (!collapsed && window.innerWidth <= 768) {
      list.querySelector<HTMLButtonElement>('.outline-link')?.focus()
    }
  })

  window.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || container.classList.contains('is-collapsed') || window.innerWidth > 768) return
    event.preventDefault()
    collapseAndRestoreFocus()
  })

  const setActive = (index: number) => {
    const links = list.querySelectorAll<HTMLElement>('.outline-link')
    links.forEach((item, itemIndex) => {
      if (itemIndex === index) {
        item.setAttribute('aria-current', 'location')
      }
      else item.removeAttribute('aria-current')
    })
    const activeLink = links[index]
    if (activeLink && window.innerWidth > 768) {
      const listRect = list.getBoundingClientRect()
      const activeRect = activeLink.getBoundingClientRect()
      if (activeRect.top < listRect.top) list.scrollTop -= listRect.top - activeRect.top
      else if (activeRect.bottom > listRect.bottom) list.scrollTop += activeRect.bottom - listRect.bottom
    }
    const active = currentItems[index]
    if (active) onActive?.(active)
  }

  // 滚动跟随：阅读时自动高亮当前章节，并同步状态栏"当前位置"。
  let lastActiveIndex = -1
  let spyFrame = 0
  const spyActive = () => {
    spyFrame = 0
    const headings = outlineHeadings()
    const anchor = window.scrollY + 140
    let index = 0
    headings.forEach((heading, headingIndex) => {
      if (heading.getBoundingClientRect().top + window.scrollY <= anchor) index = headingIndex
    })
    if (index !== lastActiveIndex) {
      lastActiveIndex = index
      setActive(index)
    }
  }
  window.addEventListener('scroll', () => {
    if (currentItems.length && !spyFrame) spyFrame = requestAnimationFrame(spyActive)
  }, { passive: true })

  return {
    update(items: OutlineItem[], chapterCount?: number) {
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
          button.className = `outline-link level-${Math.min(6, Math.max(1, item.level))}`
          button.textContent = displayOutlineText(item.text) || '未命名章节'
          button.title = button.textContent
          button.addEventListener('click', () => {
            setActive(index)
            const target =
              (item.id
                ? Array.from(editor.querySelectorAll<HTMLElement>('[id]')).find(
                    (element) => element.id === item.id,
                  )
                : null) ?? outlineHeadings()[index]
            if (target && typeof target.scrollIntoView === 'function') {
              const reducedMotion =
                typeof window.matchMedia === 'function' &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches
              target.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
            }
            if (window.innerWidth <= 768) {
              setCollapsed(true)
              toggle.focus()
            }
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
      const chapters = chapterCount ?? items.length
      count.textContent = `${chapters} 个章节`
      let hint = container.querySelector<HTMLElement>('.outline-empty-hint')
      if (items.length === 0) {
        if (!hint) { hint = document.createElement('div'); hint.className = 'outline-empty-hint'; container.append(hint) }
        hint.textContent = '使用 Markdown 标题创建章节'
      } else hint?.remove()
    },
    setActive,
  }
}
