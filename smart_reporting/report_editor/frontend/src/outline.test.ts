import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createOutlineController, displayOutlineText, namedOutlineItems, reorderMarkdownSections } from './outline'

it('strips analysis binding markers from outline display text', () => {
  expect(displayOutlineText('1. 收入规模与结构分析[[analysis:analysis_001]][[analysis:analysis_005]]'))
    .toBe('1. 收入规模与结构分析')
  expect(displayOutlineText('2. 工作量分析  [[analysis:analysis_002]]')).toBe('2. 工作量分析')
  expect(displayOutlineText('3. 无绑定标记')).toBe('3. 无绑定标记')
})

it('drops empty or whitespace-only headings from the outline', () => {
  expect(
    namedOutlineItems([
      { id: 'a', level: 2, text: '经营情况' },
      { id: 'b', level: 2, text: '' },
      { id: 'c', level: 3, text: '   ' },
      { id: 'd', level: 3, text: '门诊收入' },
    ]),
  ).toEqual([
    { id: 'a', level: 2, text: '经营情况' },
    { id: 'd', level: 3, text: '门诊收入' },
  ])
})

it('reorders same-level markdown sections without moving child sections out of their parent', () => {
  const markdown = '# 摘要\nA\n# 经营\nB\n## 门诊\nC\n# 风险\nD\n'
  expect(reorderMarkdownSections(markdown, 1, 3)).toBe(
    '# 摘要\nA\n# 风险\nD\n# 经营\nB\n## 门诊\nC\n',
  )
})

it('moves a dragged section past intermediate siblings instead of swapping', () => {
  const markdown = '# 摘要\nA\n# 经营\nB\n## 门诊\nC\n# 风险\nD\n# 展望\nE\n'
  // 下标为目录过滤后的标题序号：摘要 0、经营 1、门诊 2、风险 3、展望 4。
  expect(reorderMarkdownSections(markdown, 0, 3)).toBe(
    '# 经营\nB\n## 门诊\nC\n# 风险\nD\n# 摘要\nA\n# 展望\nE\n',
  )
  expect(reorderMarkdownSections(markdown, 4, 1)).toBe(
    '# 摘要\nA\n# 展望\nE\n# 经营\nB\n## 门诊\nC\n# 风险\nD\n',
  )
})

it('counts only named headings so outline indexes match after empty headings', () => {
  // 目录经 namedOutlineItems 过滤掉空标题；拖拽传入的是过滤后的下标。
  const markdown = '# 摘要\nA\n## \n# 经营\nB\n# 风险\nD\n'
  expect(reorderMarkdownSections(markdown, 1, 2)).toBe('# 摘要\nA\n## \n# 风险\nD\n# 经营\nB\n')
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
      <aside id="outline">
        <div class="outline-heading"><span>目录</span><button type="button" class="outline-close">关闭</button></div>
        <nav class="outline-list"></nav>
      </aside>
      <div id="editor"><h1>摘要</h1><h3></h3><h2>经营情况</h2></div>
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
    expect(document.querySelectorAll<HTMLButtonElement>('.outline-link')[1].title).toBe('经营情况')
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

  it('applies a persisted initial collapsed state', () => {
    const container = document.querySelector<HTMLElement>('#outline')!
    const toggle = document.querySelector<HTMLButtonElement>('#toggle')!

    createOutlineController({
      container,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle,
      initialCollapsed: true,
    })

    expect(container.classList).toContain('is-collapsed')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
  })

  it('reports user collapse changes for preference persistence', () => {
    const onCollapsedChange = vi.fn()
    const toggle = document.querySelector<HTMLButtonElement>('#toggle')!
    createOutlineController({
      container: document.querySelector<HTMLElement>('#outline')!,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle,
      onCollapsedChange,
    })

    toggle.click()

    expect(onCollapsedChange).toHaveBeenCalledWith(true)
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

  it('follows the reading position and highlights the current chapter', async () => {
    const editor = document.querySelector<HTMLElement>('#editor')!
    const [h1, h2] = editor.querySelectorAll<HTMLElement>('h1, h2')
    // rect.top 是视口坐标：文档坐标 100 与 700 的标题随滚动改变视口位置
    h1.getBoundingClientRect = () => ({ top: 100 - window.scrollY } as DOMRect)
    h2.getBoundingClientRect = () => ({ top: 700 - window.scrollY } as DOMRect)
    const onActive = vi.fn()
    const controller = createOutlineController({
      container: document.querySelector<HTMLElement>('#outline')!,
      editor,
      toggle: document.querySelector<HTMLButtonElement>('#toggle')!,
      onActive,
    })
    controller.update([
      { id: 'summary', level: 1, text: '摘要' },
      { id: 'operation', level: 2, text: '经营情况' },
    ])
    const links = document.querySelectorAll<HTMLElement>('.outline-link')

    const setScrollY = (value: number) => {
      Object.defineProperty(window, 'scrollY', { value, configurable: true })
    }

    setScrollY(480)
    window.dispatchEvent(new Event('scroll'))
    await vi.waitFor(() => expect(links[0].getAttribute('aria-current')).toBe('location'))
    expect(onActive).toHaveBeenLastCalledWith({ id: 'summary', level: 1, text: '摘要' })

    setScrollY(560)
    window.dispatchEvent(new Event('scroll'))
    await vi.waitFor(() => expect(links[1].getAttribute('aria-current')).toBe('location'))
    expect(links[0].getAttribute('aria-current')).toBeNull()
    expect(onActive).toHaveBeenLastCalledWith({ id: 'operation', level: 2, text: '经营情况' })
  })

  it('renders heading levels four and deeper with their own outline depth', () => {
    const controller = createOutlineController({
      container: document.querySelector<HTMLElement>('#outline')!,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle: document.querySelector<HTMLButtonElement>('#toggle')!,
    })
    controller.update([
      { id: 'deep', level: 4, text: '深级章节' },
      { id: 'deeper', level: 6, text: '更深层章节' },
    ])
    expect(document.querySelector('.outline-link.level-4')).not.toBeNull()
    expect(document.querySelector('.outline-link.level-6')).not.toBeNull()
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
    // 与拖拽一致提供撤销；目录按新顺序重建后，焦点留在移动后的章节上，可继续用方向键移动。
    expect(document.querySelector<HTMLButtonElement>('.outline-undo')!.hidden).toBe(false)
    controller.update([
      { id: 'b', level: 1, text: 'B' },
      { id: 'a', level: 1, text: 'A' },
    ])
    expect(document.activeElement).toBe(document.querySelectorAll<HTMLButtonElement>('.outline-link')[0])
    expect(document.activeElement?.textContent).toBe('B')
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

  it('does not rebuild outline controls when headings are unchanged', () => {
    const controller = createOutlineController({
      container: document.querySelector<HTMLElement>('#outline')!,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle: document.querySelector<HTMLButtonElement>('#toggle')!,
    })
    const items = [
      { id: 'summary', level: 1, text: '摘要' },
      { id: 'operation', level: 2, text: '经营情况' },
    ]
    controller.update(items)
    const firstButton = document.querySelector('.outline-link')

    controller.update(items.map((item) => ({ ...item })))

    expect(document.querySelector('.outline-link')).toBe(firstButton)
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

  it('focuses the first chapter when the mobile outline opens', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    const container = document.querySelector<HTMLElement>('#outline')!
    container.classList.add('is-collapsed')
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

    toggle.click()

    expect(document.activeElement).toBe(document.querySelector('.outline-link'))
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })
  })

  it('returns focus to the outline toggle after selecting a mobile chapter', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    const container = document.querySelector<HTMLElement>('#outline')!
    const toggle = document.querySelector<HTMLButtonElement>('#toggle')!
    const controller = createOutlineController({
      container,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle,
    })
    controller.update([{ id: 'summary', level: 1, text: '摘要' }])
    toggle.click()
    document.querySelector<HTMLButtonElement>('.outline-link')!.click()

    expect(container.classList).toContain('is-collapsed')
    expect(document.activeElement).toBe(toggle)
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })
  })

  it('closes the mobile outline with Escape and restores toggle focus', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    const container = document.querySelector<HTMLElement>('#outline')!
    container.classList.add('is-collapsed')
    const toggle = document.querySelector<HTMLButtonElement>('#toggle')!
    const controller = createOutlineController({
      container,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle,
    })
    controller.update([{ id: 'summary', level: 1, text: '摘要' }])
    toggle.click()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(container.classList).toContain('is-collapsed')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(toggle)
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })
  })

  it('closes the mobile outline with its visible control and restores toggle focus', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    const container = document.querySelector<HTMLElement>('#outline')!
    container.classList.add('is-collapsed')
    const toggle = document.querySelector<HTMLButtonElement>('#toggle')!
    const controller = createOutlineController({
      container,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle,
    })
    controller.update([{ id: 'summary', level: 1, text: '摘要' }])
    toggle.click()

    document.querySelector<HTMLButtonElement>('.outline-close')!.click()

    expect(container.classList).toContain('is-collapsed')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(toggle)
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })
  })

  it('keeps the active chapter visible inside a long desktop outline', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
    const container = document.querySelector<HTMLElement>('#outline')!
    const controller = createOutlineController({
      container,
      editor: document.querySelector<HTMLElement>('#editor')!,
      toggle: document.querySelector<HTMLButtonElement>('#toggle')!,
    })
    controller.update([
      { id: 'summary', level: 1, text: '摘要' },
      { id: 'operation', level: 1, text: '经营情况' },
      { id: 'risk', level: 1, text: '风险提示' },
    ])
    const list = container.querySelector<HTMLElement>('.outline-list')!
    const active = list.querySelectorAll<HTMLButtonElement>('.outline-link')[2]
    list.scrollTop = 40
    list.getBoundingClientRect = () => ({ top: 100, bottom: 300 } as DOMRect)
    active.getBoundingClientRect = () => ({ top: 320, bottom: 350 } as DOMRect)

    controller.setActive(2)

    expect(list.scrollTop).toBe(90)
  })
})
