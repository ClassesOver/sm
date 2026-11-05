import { diffChars } from 'diff'
import { buttonClasses } from './button'

/** Render untrusted proposal text as text nodes, including the highlighted diff. */
export function renderAITextPreview(before: string, after: string, target: HTMLElement) {
  const controls = document.createElement('div'); controls.className = 'ai-preview-modes'
  controls.setAttribute('role', 'group'); controls.setAttribute('aria-label', '预览方式')
  const content = document.createElement('div'); content.className = 'ai-text-preview'
  // Bound diff work for large selections; full text views remain available.
  const parts = diffChars(before, after, { timeout: 100, maxEditLength: 10000 })
  const navigation = document.createElement('div'); navigation.className = 'ai-diff-navigation'
  navigation.setAttribute('role', 'group'); navigation.setAttribute('aria-label', '差异导航')
  const previous = document.createElement('button'); previous.type = 'button'; previous.textContent = '上一处'; previous.dataset.diffAction = 'previous'
  const next = document.createElement('button'); next.type = 'button'; next.textContent = '下一处'; next.dataset.diffAction = 'next'
  previous.className = next.className = buttonClasses('quiet')
  const position = document.createElement('span'); position.setAttribute('role', 'status'); position.setAttribute('aria-live', 'polite')
  navigation.append(previous, position, next)
  let groups: HTMLElement[][] = []
  let active = 0
  const navigate = (index: number, scroll = true) => {
    active = index
    groups.forEach((group, i) => group.forEach(node => { node.dataset.currentChange = String(i === active) }))
    position.textContent = groups.length ? `${active + 1} / ${groups.length} 处修改` : '没有文字变化'
    previous.disabled = active <= 0; next.disabled = active >= groups.length - 1
    if (scroll) groups[active]?.[0]?.scrollIntoView?.({ block: 'center', inline: 'nearest' })
  }
  previous.addEventListener('click', () => navigate(Math.max(0, active - 1)))
  next.addEventListener('click', () => navigate(Math.min(groups.length - 1, active + 1)))
  const views = new Map<string, HTMLButtonElement>()
  const show = (mode: string) => {
    for (const [id, button] of views) button.setAttribute('aria-pressed', String(id === mode))
    content.replaceChildren(); groups = []; navigation.hidden = mode !== 'diff'
    if (mode === 'diff') {
      const legend = document.createElement('p'); legend.className = 'ai-preview-legend'; legend.textContent = '删除线：原文删去 · 高亮：候选新增'
      const text = document.createElement('div'); text.className = 'ai-preview-text'
      let continuing = false
      for (const part of parts ?? []) {
        const node = document.createElement(part.added ? 'ins' : part.removed ? 'del' : 'span')
        node.textContent = part.value; text.append(node)
        if (part.added || part.removed) {
          if (!continuing) groups.push([])
          groups.at(-1)!.push(node); continuing = true
        } else continuing = false
      }
      content.append(legend, text)
      if (!parts) {
        legend.textContent = '内容较长，请切换前后对比查看完整原文和候选。'
        navigation.hidden = true
      }
      navigate(0, false)
    } else {
      const values = mode === 'compare' ? [['原文', before], ['候选', after]] : [[mode === 'original' ? '原文' : '候选', mode === 'original' ? before : after]]
      for (const [label, value] of values) {
        const section = document.createElement('section')
        const heading = document.createElement('h4'); heading.textContent = label!
        const text = document.createElement('div'); text.className = 'ai-preview-text'; text.textContent = value!
        section.append(heading, text); content.append(section)
      }
    }
    content.dataset.mode = mode
  }
  for (const [id, label] of [['diff', '差异'], ['compare', '前后对比'], ['original', '原文'], ['candidate', '候选']]) {
    const button = document.createElement('button'); button.type = 'button'; button.className = buttonClasses('quiet')
    button.textContent = label!; button.dataset.previewMode = id!
    button.addEventListener('click', () => show(id!)); controls.append(button); views.set(id!, button)
  }
  target.replaceChildren(controls, navigation, content); show('diff')
}
