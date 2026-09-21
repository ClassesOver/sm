import { beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const stylesheet = readFileSync('src/style.css', 'utf8')

describe('report editor visual hierarchy', () => {
  beforeEach(() => {
    document.head.innerHTML = `<style>${stylesheet}</style>`
    document.body.innerHTML = `
      <main class="report-app">
        <section class="editor-surface">
          <div id="report-editor">
            <div class="ProseMirror">
              <h1>医院运营月报</h1>
              <h2>核心结论</h2>
              <blockquote>本月运营稳定。</blockquote>
              <table><thead><tr><th>指标</th></tr></thead><tbody><tr><td>门急诊人次</td></tr></tbody></table>
            </div>
          </div>
        </section>
      </main>
    `
  })

  it('uses ink tones for document headings instead of the action blue', () => {
    const h1 = document.querySelector('h1')!
    const h2 = document.querySelector('h2')!

    expect(getComputedStyle(h1).color).toBe('rgb(27, 42, 65)')
    expect(getComputedStyle(h2).color).toBe('rgb(48, 67, 90)')
  })

  it('uses a Song-style font for desktop prose while keeping headings and table text sans-serif', () => {
    const rules = Array.from(document.styleSheets[0].cssRules)
    const desktop = rules.find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule &&
      rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText.split(/,\s*/).includes('#report-editor .ProseMirror p'),
      ),
    )!
    const fontFor = (selector: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule =>
        rule instanceof CSSStyleRule && rule.selectorText.split(/,\s*/).includes(selector),
    )!.style.fontFamily

    for (const selector of [
      '#report-editor .ProseMirror p',
      '#report-editor .ProseMirror li',
      '#report-editor .ProseMirror blockquote',
      '#report-editor .ProseMirror figcaption',
    ]) {
      expect(fontFor(selector)).toContain('Noto Serif CJK SC')
    }
    expect(fontFor('#report-editor .ProseMirror table p')).toContain('Noto Sans CJK SC')
    expect(fontFor('#report-editor .ProseMirror table li')).toContain('Noto Sans CJK SC')
    expect(getComputedStyle(document.querySelector('h1')!).fontFamily).toContain('Noto Sans CJK SC')
  })

  it('keeps code-block insertion carets visible on the dark surface', () => {
    const rules = Array.from(document.styleSheets[0].cssRules)
      .filter((rule): rule is CSSStyleRule => rule instanceof CSSStyleRule)
    const style = (selector: string) => rules.find((rule) => rule.selectorText === selector)!.style

    expect(style('#report-editor .ProseMirror pre').caretColor).toBe('#8ee7ff')
    expect(style('#report-editor .ProseMirror pre code').caretColor).toBe('#8ee7ff')
    expect(style('#report-editor .ProseMirror pre:focus-within').borderColor).toBe('rgb(86, 180, 233)')
    expect(style('#report-editor .ProseMirror pre:focus-within').boxShadow).toContain('0 0 0 3px')
  })

  it('uses a quiet rule for document separators', () => {
    const rules = Array.from(document.styleSheets[0].cssRules)
      .filter((rule): rule is CSSStyleRule => rule instanceof CSSStyleRule)
    const rule = rules.find((item) => item.selectorText === '#report-editor .ProseMirror hr')!.style

    expect(rule.background).toBe('transparent')
    expect(rule.height).toBe('1px')
    expect(rule.margin).toBe('0.5em 0px')
    expect(rule.borderTop).toBe('1px solid rgb(215, 224, 231)')
    expect(rule.padding).toBe('0px')

    const selected = rules.find(
      (item) => item.selectorText === '#report-editor .ProseMirror hr.ProseMirror-selectednode',
    )!.style
    expect(selected.background).toBe('transparent')
    expect(selected.borderTopColor).toBe('rgb(145, 172, 190)')

    const selectedOverlay = rules.find(
      (item) => item.selectorText === '#report-editor .ProseMirror hr.ProseMirror-selectednode::before',
    )!.style
    expect(selectedOverlay.display).toBe('none')
  })

  it('retains the existing sans-serif editor font outside desktop', () => {
    expect(getComputedStyle(document.querySelector('.ProseMirror')!).fontFamily).toContain('Noto Sans CJK SC')
  })

  it('gives desktop report content a compact editorial rhythm', () => {
    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === '#report-editor .ProseMirror h1',
      ),
    )
    expect(desktop).toBeDefined()
    if (!desktop) return
    const style = (selector: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText === selector,
    )!.style

    expect(style('#report-editor .ProseMirror h1').marginBottom).toBe('1.15em')
    expect(style('#report-editor .ProseMirror h2').marginTop).toBe('1.75em')
    expect(style('#report-editor .ProseMirror table').width).toBe('100%')
    expect(style('#report-editor .ProseMirror table').fontVariantNumeric).toBe('tabular-nums')
    expect(style('#report-editor .milkdown-image-block').marginTop).toBe('1.45em')
  })

  it('keeps tables and callouts quiet so data remains the focus', () => {
    const header = document.querySelector('th')!
    const quote = document.querySelector('blockquote')!

    expect(getComputedStyle(header).backgroundColor).toBe('rgb(244, 247, 249)')
    expect(getComputedStyle(quote).backgroundColor).toBe('rgb(247, 249, 250)')
    expect(getComputedStyle(quote).borderLeftColor).toBe('rgb(128, 151, 170)')
    expect(getComputedStyle(quote).paddingLeft).toBe('18px')
    expect(getComputedStyle(document.querySelector('td')!).paddingTop).toBe('8px')
  })

  it('keeps status separators silent and makes the active outline legible', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      `<div class="report-meta"><span class="meta-dot">·</span></div>
       <nav class="outline-list"><button class="outline-link" aria-current="location">关键指标</button></nav>`,
    )

    expect(getComputedStyle(document.querySelector('.meta-dot')!).display).toBe('none')
    expect(getComputedStyle(document.querySelector('.outline-link')!).borderLeftWidth).toBe('3px')
  })

  it('keeps automatic-save feedback stable while its indicator changes state', () => {
    const rules = Array.from(document.styleSheets[0].cssRules)
      .filter((rule): rule is CSSStyleRule => rule instanceof CSSStyleRule)
    const style = (selector: string) => rules.find((rule) => rule.selectorText === selector)!.style

    expect(style('.save-state::before').width).toBe('12px')
    expect(style('.save-state::before').flexBasis).toBe('12px')
    expect(style('.save-state::before').transition).toContain('transform 160ms')
    expect(style('.save-state:not([aria-busy="true"])::before').transform).toBe('scale(0.58)')

    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === '.save-state',
      ),
    )!
    const desktopState = Array.from(desktop.cssRules).find((rule): rule is CSSStyleRule =>
      rule instanceof CSSStyleRule && rule.selectorText === '.save-state',
    )!.style
    expect(desktopState.width).toBe('168px')
  })

  it('uses a stable two-pane history browser on desktop', () => {
    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === '.history-browser',
      ),
    )!
    const style = (selector: string, property: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule =>
        rule instanceof CSSStyleRule &&
        rule.selectorText === selector &&
        Boolean(rule.style.getPropertyValue(property)),
    )!.style

    expect(style('.history-card', 'width').width).toBe('calc(100% - 40px)')
    expect(style('.history-card', 'max-width').maxWidth).toBe('1280px')
    expect(style('.history-browser', 'grid-template-columns').gridTemplateColumns).toBe('minmax(240px, 280px) minmax(0, 1fr)')
    expect(style('.history-list', 'overflow-y').overflowY).toBe('auto')
    expect(style('.history-list', 'align-content').alignContent).toBe('start')
    expect(style('.history-preview', 'overflow').overflow).toBe('hidden')
    expect(style('.history-diff', 'grid-template-columns').gridTemplateColumns).toBe('minmax(0, 1fr) minmax(0, 1fr)')
    expect(style('.history-item[aria-pressed="true"]', 'background').background).toBe('rgb(241, 246, 249)')
  })

  it('uses restrained desktop workspace chrome around the report sheet', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      `<header class="app-bar"></header>
       <div class="report-meta">当前章节：核心结论</div>
       <aside class="report-outline"><div class="outline-heading">目录</div></aside>`,
    )

    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) => nested instanceof CSSStyleRule && nested.selectorText === 'body'),
    )
    expect(desktop).toBeDefined()
    if (!desktop) return
    const style = (selector: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText === selector,
    )!.style

    expect(style('body').background).toBe('rgb(243, 246, 248)')
    expect(style('.report-meta').borderBottom).toBe('1px solid rgb(220, 229, 236)')
    expect(style('.report-outline').borderRight).toBe('1px solid rgb(220, 229, 236)')
    expect(style('.outline-heading').letterSpacing).toBe('0')
  })

  it('keeps desktop controls compact and the active outline treatment quiet', () => {
    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === '.report-actions button',
      ),
    )
    expect(desktop).toBeDefined()
    if (!desktop) return
    const style = (selector: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText === selector,
    )!.style

    expect(style('.report-actions button').height).toBe('32px')
    expect(style('.toolbar-group + .toolbar-group::before').height).toBe('14px')
    expect(style('.outline-link[aria-current="location"]').borderLeftWidth).toBe('2px')
    expect(style('.outline-link[aria-current="location"]').background).toBe('rgb(241, 244, 246)')
  })

  it('gives export actions a quieter visual weight than save', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      `<nav class="report-actions toolbar-compact">
        <button data-action="save" class="is-primary">保存</button>
        <button data-action="pdf">PDF</button>
      </nav>`,
    )
    const save = document.querySelector('[data-action="save"]')!
    const pdf = document.querySelector('[data-action="pdf"]')!

    expect(getComputedStyle(save).backgroundColor).toBe('rgb(11, 79, 138)')
    expect(getComputedStyle(pdf).color).toBe('rgb(81, 102, 121)')
  })

  it('keeps frequent desktop actions labeled without hiding them in the more menu', () => {
    const rules = Array.from(document.styleSheets[0].cssRules)
    const medium = rules.find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 1181px) and (max-width: 1600px)',
    )!
    const compact = rules.filter((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px) and (max-width: 1180px)',
    )
    const mediumRules = Array.from(medium.cssRules).filter((rule): rule is CSSStyleRule => rule instanceof CSSStyleRule)
    const compactRules = compact.flatMap((rule) => Array.from(rule.cssRules))
      .filter((rule): rule is CSSStyleRule => rule instanceof CSSStyleRule)
    const declaration = (styles: CSSStyleRule[], selector: string, property: string) =>
      styles.filter((rule) => rule.selectorText.split(/,\s*/).includes(selector))
        .map((rule) => rule.style.getPropertyValue(property))
        .find(Boolean)

    expect(declaration(mediumRules, '.secondary-actions', 'display')).toBe('inline-flex')
    expect(declaration(mediumRules, '.report-actions [data-action="more"]', 'display')).toBe('none')
    expect(declaration(mediumRules, '.toolbar-group-output [data-action="pdf"] span', 'display')).toBe('none')
    expect(declaration(mediumRules, '.toolbar-group-edit-view [data-action="focus"] span', 'display')).toBe('none')
    expect(declaration(compactRules, '.secondary-actions', 'display')).toBe('none')
    expect(declaration(compactRules, '.report-actions [data-action="more"]', 'display')).toBe('inline-flex')
    expect(declaration(compactRules, '.report-actions button span', 'display')).toBe('none')
  })

  it('makes selected controls and expanded menus visibly persistent', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      `<nav class="report-actions">
        <button data-action="view" aria-pressed="true">A4</button>
        <button data-action="more" aria-expanded="true">更多</button>
      </nav>`,
    )
    const selected = document.querySelector('[data-action="view"]')!
    const expanded = document.querySelector('[data-action="more"]')!

    expect(getComputedStyle(selected).backgroundColor).toBe('rgb(234, 240, 244)')
    expect(getComputedStyle(expanded).backgroundColor).toBe('rgb(234, 240, 244)')
  })

  it('makes unavailable search actions visibly inactive', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      '<div class="search-panel"><button disabled>下一个匹配</button></div>',
    )
    const disabled = document.querySelector('.search-panel button')!

    expect(getComputedStyle(disabled).opacity).toBe('0.42')
    expect(getComputedStyle(disabled).cursor).toBe('default')
  })

  it('makes the focused search field clearly visible', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      '<div class="search-panel"><input class="search-query"></div>',
    )
    const input = document.querySelector<HTMLInputElement>('.search-query')!
    input.focus()

    expect(getComputedStyle(input).borderColor).toBe('rgb(0, 126, 167)')
    expect(getComputedStyle(input).outlineWidth).toBe('3px')
  })

  it('keeps search icon buttons stable and keyboard focus visible', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      '<div class="search-panel"><button data-search="next">↓</button></div>',
    )
    const button = document.querySelector<HTMLButtonElement>('.search-panel button')!
    button.focus()
    const style = getComputedStyle(button)

    expect(style.width).toBe('32px')
    expect(style.paddingLeft).toBe('0px')
    expect(style.display).toBe('inline-flex')
    expect(style.outlineWidth).toBe('3px')
  })

  it('uses one restrained desktop treatment for utility surfaces', () => {
    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === '.search-panel',
      ),
    )
    expect(desktop).toBeDefined()
    if (!desktop) return
    const style = (selector: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule =>
        rule instanceof CSSStyleRule && rule.selectorText.split(/,\s*/).includes(selector),
    )!.style

    expect(style('.search-panel').borderRadius).toBe('6px')
    expect(style('.history-card').borderRadius).toBe('8px')
    expect(style('.shortcuts-close').width).toBe('32px')
    expect(style('.shortcuts-close').height).toBe('32px')
    expect(style('.history-item').background).toBe('transparent')
    expect(style('.history-item').borderBottomWidth).toBe('1px')
  })

  it('integrates desktop Milkdown controls with the editor chrome', () => {
    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === '#report-editor .milkdown-toolbar',
      ),
    )
    expect(desktop).toBeDefined()
    if (!desktop) return
    const style = (selector: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule =>
        rule instanceof CSSStyleRule && rule.selectorText.split(/,\s*/).includes(selector),
    )!.style

    expect(style('#report-editor .milkdown-toolbar').borderRadius).toBe('6px')
    expect(style('#report-editor .milkdown-toolbar .toolbar-item svg').width).toBe('18px')
    expect(style('#report-editor .milkdown-slash-menu').borderRadius).toBe('8px')
    expect(style('#report-editor .milkdown-link-preview > .link-preview').borderRadius).toBe('6px')
    expect(style('#report-editor .milkdown-ai-instruction > .ai-instruction').borderRadius).toBe('8px')
    expect(style('#report-editor .milkdown-ai-diff-actions').borderRadius).toBe('8px')
  })

  it('keeps keyboard focus visible inside outline links', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      '<nav class="outline-list"><button class="outline-link">超长章节标题</button></nav>',
    )
    const button = document.querySelector<HTMLButtonElement>('.outline-link')!
    button.focus()
    const style = getComputedStyle(button)

    expect(style.outlineWidth).toBe('2px')
    expect(style.outlineOffset).toBe('-2px')
  })

  it('shows keyboard focus on previewable report images', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      '<div id="report-editor"><div class="ProseMirror"><img src="chart.png" tabindex="0"></div></div>',
    )
    const image = document.querySelector<HTMLImageElement>('#report-editor img')!
    image.focus()
    const style = getComputedStyle(image)

    expect(style.outlineWidth).toBe('3px')
    expect(style.outlineOffset).toBe('3px')
  })

  it('polishes image preview controls and media edges', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      '<div class="image-preview"><button class="image-preview-close">×</button><figure><img src="chart.png"><figcaption>收入趋势与预算执行情况</figcaption></figure></div>',
    )
    const close = document.querySelector<HTMLButtonElement>('.image-preview-close')!
    close.focus()

    expect(getComputedStyle(close).outlineWidth).toBe('3px')
    expect(getComputedStyle(document.querySelector('.image-preview img')!).borderWidth).toBe('1px')
    expect(getComputedStyle(document.querySelector('.image-preview figcaption')!).lineHeight).toBe('20px')
  })

  it('keeps the focus mode exit control visibly interactive', () => {
    document.body.insertAdjacentHTML(
      'beforeend',
      '<main class="focus-mode"><button class="focus-mode-exit">退出专注</button></main>',
    )
    const exit = document.querySelector<HTMLButtonElement>('.focus-mode-exit')!
    exit.focus()
    const style = getComputedStyle(exit)

    expect(style.display).toBe('block')
    expect(style.outlineWidth).toBe('3px')
    expect(style.outlineOffset).toBe('2px')
  })

  it('keeps the mobile action menu above the safe-area toolbar', () => {
    const rules = Array.from(document.styleSheets[0].cssRules)
    const mobile = rules.find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(max-width: 768px)',
    )!
    const findRule = (selector: string) => Array.from(mobile.cssRules).find(
      (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText === selector,
    )!

    expect(findRule('.secondary-actions').style.bottom).toBe('calc(66px + env(safe-area-inset-bottom))')
    expect(findRule('.app-bar > .report-actions').style.background).toBe('rgba(255, 255, 255, 0.94)')
    expect(findRule('.report-actions button').style.height).toBe('48px')
  })

  it('keeps mobile search controls in a stable three-row grid', () => {
    const rules = Array.from(document.styleSheets[0].cssRules)
    const mobile = rules.find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(max-width: 768px)',
    )!
    const findRule = (selector: string) => Array.from(mobile.cssRules).find(
      (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText === selector,
    )!
    const panel = findRule('.search-panel').style

    expect(panel.display).toBe('grid')
    expect(panel.gridTemplateColumns).toBe('minmax(0, 1fr) max-content 32px 32px')
    expect(panel.gridTemplateAreas.replace(/\s+/g, ' ')).toBe('"query prev next close" "replacement replace all all" "count count count count"')
    expect(findRule('.search-count').style.gridArea).toBe('count')
  })

  it('shows a touch-sized outline close control only on mobile', () => {
    const rules = Array.from(document.styleSheets[0].cssRules)
    const base = rules.find((rule): rule is CSSStyleRule =>
      rule instanceof CSSStyleRule && rule.selectorText === '.outline-close',
    )!
    const mobile = rules.find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(max-width: 768px)',
    )!
    const mobileClose = Array.from(mobile.cssRules).find((rule): rule is CSSStyleRule =>
      rule instanceof CSSStyleRule && rule.selectorText === '.outline-close',
    )!

    expect(base.style.display).toBe('none')
    expect(mobileClose.style.display).toBe('inline-flex')
    expect(mobileClose.style.width).toBe('40px')
    expect(mobileClose.style.height).toBe('40px')
  })

  it('keeps the desktop outline header and count outside its scrolling chapter list', () => {
    const rules = Array.from(document.styleSheets[0].cssRules)
    const desktop = rules.find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule &&
      rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === '.report-outline',
      ),
    )

    expect(desktop).toBeDefined()
    const findRule = (selector: string) => Array.from(desktop!.cssRules).find(
      (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText === selector,
    )!
    const outline = findRule('.report-outline').style
    const list = findRule('.outline-list').style

    expect(outline.display).toBe('flex')
    expect(outline.flexDirection).toBe('column')
    expect(outline.overflow).toBe('hidden')
    expect(list.overflowY).toBe('auto')
    expect(list.overscrollBehavior).toBe('contain')
    expect(list.scrollbarGutter).toBe('stable')
  })

  it('aligns desktop status details with the report sheet across view and outline modes', () => {
    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === '.report-meta',
      ),
    )!
    const style = (selector: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText === selector,
    )!.style

    expect(style('.report-meta').paddingLeft).toBe('268px')
    expect(style('.view-wide .report-meta').paddingRight).toBe('0px')
    expect(style('.outline-collapsed .report-meta').padding).toBe('0px')
  })

  it('softens the desktop sheet chrome while keeping navigation anchored', () => {
    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === 'body',
      ),
    )!
    const style = (selector: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText === selector,
    )!.style

    expect(style('.app-bar').minHeight).toBe('60px')
    expect(style('.report-meta').minHeight).toBe('34px')
    expect(style('.report-outline').top).toBe('86px')
    expect(style('.editor-surface::before').height).toBe('1px')
    expect(style('.editor-surface::before').background).toBe('rgb(151, 172, 188)')
    expect(style('.editor-surface').boxShadow).toContain('0 14px 36px')
  })

  it('gives localized desktop editing overlays enough room and clear active feedback', () => {
    const desktop = Array.from(document.styleSheets[0].cssRules).find((rule): rule is CSSMediaRule =>
      rule instanceof CSSMediaRule && rule.conditionText === '(min-width: 769px)' &&
      Array.from(rule.cssRules).some((nested) =>
        nested instanceof CSSStyleRule && nested.selectorText === '#report-editor .milkdown-toolbar',
      ),
    )!
    const style = (selector: string) => Array.from(desktop.cssRules).find(
      (rule): rule is CSSStyleRule => rule instanceof CSSStyleRule && rule.selectorText === selector,
    )!.style

    expect(style('#report-editor .milkdown-toolbar').padding).toBe('3px')
    expect(style('#report-editor .milkdown-toolbar .toolbar-item.active').background).toBe('rgb(220, 236, 246)')
    expect(style('#report-editor .milkdown-slash-menu .menu-group li > span').whiteSpace).toBe('nowrap')
    expect(style('#report-editor .milkdown-link-edit > .link-edit').minWidth).toBe('360px')
    expect(style('#report-editor .milkdown-ai-instruction > .ai-instruction').width).toBe('400px')
    expect(style('#report-editor .milkdown-ai-instruction > .ai-instruction').maxWidth).toBe('calc(100vw - 40px)')
  })
})
