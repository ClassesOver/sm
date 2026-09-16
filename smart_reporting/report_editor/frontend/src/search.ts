export interface SearchControllerOptions {
  root: HTMLElement
  getText: () => string
  replaceText: (text: string) => void
  setQuery?: (query: string, replacement: string) => void
  navigate?: (direction: 'prev' | 'next') => void
}

const PROTOCOL_MARKER = /\[\[(?:section|citation):[^\]]+\]\]/g

function protectedRanges(text: string): Array<[number, number]> {
  return Array.from(text.matchAll(PROTOCOL_MARKER), (match) => [
    match.index ?? 0,
    (match.index ?? 0) + match[0].length,
  ])
}

function isProtected(index: number, ranges: Array<[number, number]>): boolean {
  return ranges.some(([start, end]) => index >= start && index < end)
}

function replaceOutsideProtected(text: string, query: string, replacement: string): string {
  if (!query) return text
  const ranges = protectedRanges(text)
  let result = ''
  let cursor = 0
  let index = text.indexOf(query)
  while (index >= 0) {
    if (!isProtected(index, ranges)) {
      result += text.slice(cursor, index) + replacement
      cursor = index + query.length
    }
    index = text.indexOf(query, index + Math.max(query.length, 1))
  }
  return result + text.slice(cursor)
}

export function createSearchController({ root, getText, replaceText, setQuery, navigate }: SearchControllerOptions) {
  const panel = document.createElement('section')
  panel.className = 'search-panel'
  panel.hidden = true
  panel.innerHTML = `<input class="search-query" aria-label="搜索文本" placeholder="搜索报告内容"><span class="search-count" aria-live="polite">0 个匹配</span><button type="button" data-search="prev">↑</button><button type="button" data-search="next">↓</button><input class="search-replacement" aria-label="替换为" placeholder="替换为"><button type="button" data-search="replace">替换</button><button type="button" data-search="all">全部替换</button><button type="button" data-search="close" aria-label="关闭搜索">×</button>`
  const metadata = root.querySelector('.report-meta')
  if (metadata) metadata.after(panel)
  else root.prepend(panel)
  const query = panel.querySelector<HTMLInputElement>('.search-query')!
  const replacement = panel.querySelector<HTMLInputElement>('.search-replacement')!
  const count = panel.querySelector<HTMLElement>('.search-count')!
  let matches: number[] = []
  let current = 0
  let editor: HTMLElement | null = null
  const clearHighlights = () => editor?.querySelectorAll('.search-match').forEach((node) => node.replaceWith(document.createTextNode(node.textContent ?? '')))
  const highlight = () => {
    if (!editor || !query.value) return
    clearHighlights()
    const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT)
    const nodes: Text[] = []
    while (walker.nextNode()) if (walker.currentNode.textContent?.includes(query.value)) nodes.push(walker.currentNode as Text)
    let matchIndex = 0
    nodes.forEach((node) => {
      const value = node.textContent ?? ''
      const fragment = document.createDocumentFragment()
      let cursor = 0
      let index = value.indexOf(query.value)
      while (index >= 0) {
        fragment.append(value.slice(cursor, index))
        const mark = document.createElement('mark')
        mark.className = `search-match${matchIndex === current ? ' search-match-active' : ''}`
        mark.textContent = query.value
        fragment.append(mark)
        matchIndex += 1
        cursor = index + query.value.length
        index = value.indexOf(query.value, cursor)
      }
      fragment.append(value.slice(cursor))
      node.replaceWith(fragment)
    })
  }
  const refresh = () => {
    const text = getText()
    const ranges = protectedRanges(text)
    matches = []
    if (query.value) {
      let index = text.indexOf(query.value)
      while (index >= 0) {
        if (!isProtected(index, ranges)) matches.push(index)
        index = text.indexOf(query.value, index + query.value.length)
      }
    }
    current = Math.min(current, Math.max(0, matches.length - 1))
    count.textContent = matches.length ? `${current + 1} / ${matches.length} 个匹配` : '0 个匹配'
    if (setQuery) setQuery(query.value, replacement.value)
    else highlight()
  }
  const move = (offset: number) => {
    if (!matches.length) return
    current = (current + offset + matches.length) % matches.length
    refresh()
    navigate?.(offset < 0 ? 'prev' : 'next')
    const active = editor?.querySelector<HTMLElement>('.search-match-active')
    if (active && typeof active.scrollIntoView === 'function') active.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  const close = () => { panel.hidden = true }
  const open = () => {
    panel.hidden = false
    query.focus()
    refresh()
  }
  panel.addEventListener('click', (event) => {
    const action = (event.target as HTMLElement).dataset.search
    if (action === 'close') close()
    if (action === 'prev') move(-1)
    if (action === 'next') move(1)
    if (action === 'replace' && query.value && matches.length) {
      const text = getText()
      const start = matches[current]
      replaceText(text.slice(0, start) + replacement.value + text.slice(start + query.value.length))
      refresh()
    }
    if (action === 'all' && query.value) {
      replaceText(replaceOutsideProtected(getText(), query.value, replacement.value))
      refresh()
    }
  })
  query.addEventListener('input', refresh)
  query.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return
    event.preventDefault()
    move(event.shiftKey ? -1 : 1)
  })
  window.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
      event.preventDefault()
      open()
    } else if (event.key === 'Escape' && !panel.hidden) close()
  })
  return { panel, open, close, setEditor: (value: HTMLElement) => { editor = value; refresh() } }
}
