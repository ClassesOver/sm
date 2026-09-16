import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createOutlineController, reorderMarkdownSections } from './outline'

it('reorders same-level markdown sections without moving child sections out of their parent', () => {
  const markdown = '# 摘要\nA\n# 经营\nB\n## 门诊\nC\n# 风险\nD\n'
  expect(reorderMarkdownSections(markdown, 1, 3)).toBe(
    '# 摘要\nA\n# 风险\nD\n# 经营\nB\n## 门诊\nC\n',
  )
})

it('ignores headings inside fenced code blocks', () => {
  const markdown = '# 真章节\n```md\n# 代码示例\n```\n# 第二章\n正文\n'
  expect(reorderMarkdownSections(markdown, 0, 1)).toBe(
    '# 第二章\n正文\n# 真章节\n```md\n# 代码示例\n```\n',
  )
})

it('ignores headings inside tilde fenced code blocks', () => {
  const markdown = '~~~md\n# 伪标题\n~~~\n# 真标题\n# 第二标题\n'
  expect(reorderMarkdownSections(markdown, 0, 1)).toBe('~~~md\n# 伪标题\n~~~\n# 第二标题\n# 真标题\n')
})

describe('createOutlineController', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button id="toggle" aria-expanded="true"></button>
      <aside id="outline"><nav class="outline-list"></nav></aside>
      <div id="editor"><h1>摘要</h1><h2>经营情况</h2></div>
    `
  })

  it('renders official Milkdown outline levels and navigates to the heading', () => {
    const heading = document.querySelector('h2')!
    heading.scrollIntoView = vi.fn()
    const controller = createOutlineController({
      container: document.querySelector<HTMLElement>('#outline')!,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle: document.querySelector<HTMLButtonElement>('#toggle')!,
    })

    controller.update([
      { id: 'summary', level: 1, text: '摘要' },
      { id: 'operation', level: 2, text: '经营情况' },
    ])
    document.querySelectorAll<HTMLButtonElement>('.outline-link')[1].click()

    expect(document.querySelectorAll('.outline-link')).toHaveLength(2)
    expect(document.querySelectorAll('.outline-link')[1].classList).toContain('level-2')
    expect(heading.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
  })

  it('toggles the outline and marks the active heading', () => {
    const container = document.querySelector<HTMLElement>('#outline')!
    const toggle = document.querySelector<HTMLButtonElement>('#toggle')!
    const controller = createOutlineController({
      container,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle,
    })
    controller.update([
      { id: 'summary', level: 1, text: '摘要' },
      { id: 'operation', level: 2, text: '经营情况' },
    ])

    controller.setActive(1)
    toggle.click()

    expect(document.querySelectorAll('.outline-link')[1].getAttribute('aria-current')).toBe(
      'location',
    )
    expect(container.classList).toContain('is-collapsed')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
  })

  it('reports the active section to the surrounding shell', () => {
    const onActive = vi.fn()
    const controller = createOutlineController({
      container: document.querySelector<HTMLElement>('#outline')!,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle: document.querySelector<HTMLButtonElement>('#toggle')!,
      onActive,
    })
    controller.update([
      { id: 'summary', level: 1, text: '摘要' },
      { id: 'operation', level: 2, text: '经营情况' },
    ])
    controller.setActive(1)
    expect(onActive).toHaveBeenCalledWith({ id: 'operation', level: 2, text: '经营情况' })
  })

  it('supports keyboard moving a section to the previous same-level item', () => {
    const replaceMarkdown = vi.fn()
    const controller = createOutlineController({
      container: document.querySelector<HTMLElement>('#outline')!,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle: document.querySelector<HTMLButtonElement>('#toggle')!,
      getMarkdown: () => '# A\nA\n# B\nB\n',
      replaceMarkdown,
    })
    controller.update([
      { id: 'a', level: 1, text: 'A' },
      { id: 'b', level: 1, text: 'B' },
    ])
    const second = document.querySelectorAll<HTMLButtonElement>('.outline-link')[1]
    second.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
    expect(replaceMarkdown).toHaveBeenCalledWith('# B\nB\n# A\nA\n')
  })

  it('supports direct drag reorder without a sorting mode button', () => {
    document.body.innerHTML = '<aside id="outline"><nav class="outline-list"></nav></aside><div id="editor"><h1>A</h1><h1>B</h1></div>'
    const container = document.querySelector<HTMLElement>('#outline')!
    const controller = createOutlineController({
      container,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle: document.createElement('button'),
      getMarkdown: () => '# A\n# B\n',
      replaceMarkdown: vi.fn(),
    })
    controller.update([{ text: 'A', level: 1, id: '' }, { text: 'B', level: 1, id: '' }])
    expect(container.querySelector('.outline-reorder-toggle')).toBeNull()
    expect(container.querySelectorAll('[draggable="true"]')).toHaveLength(2)
  })

  it('shows chapter count and an actionable empty-state hint', () => {
    document.body.innerHTML = '<aside id="outline"><div class="outline-heading"><span>目录</span><button class="outline-reorder-toggle">排序</button></div><nav class="outline-list"></nav></aside><div id="editor"></div>'
    const container = document.querySelector<HTMLElement>('#outline')!
    const controller = createOutlineController({ container, editor: document.querySelector<HTMLElement>('#editor')!, toggle: document.createElement('button') })
    controller.update([])
    expect(container.querySelector('.outline-count')?.textContent).toBe('0 个章节')
    expect(container.querySelector('.outline-empty-hint')?.textContent).toContain('Markdown 标题')
    controller.update([{ text: '摘要', level: 1, id: '' }])
    expect(container.querySelector('.outline-count')?.textContent).toBe('1 个章节')
    expect(container.querySelector('.outline-empty-hint')).toBeNull()
  })

  it('respects reduced motion when navigating', () => {
    const heading = document.querySelector('h2')!
    heading.scrollIntoView = vi.fn()
    vi.stubGlobal('matchMedia', () => ({ matches: true }))
    const controller = createOutlineController({
      container: document.querySelector<HTMLElement>('#outline')!,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle: document.querySelector<HTMLButtonElement>('#toggle')!,
    })
    controller.update([
      { id: 'summary', level: 1, text: '摘要' },
      { id: 'operation', level: 2, text: '经营情况' },
    ])
    document.querySelectorAll<HTMLButtonElement>('.outline-link')[1].click()

    expect(heading.scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' })
    vi.unstubAllGlobals()
  })
})
