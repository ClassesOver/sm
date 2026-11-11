import { beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

/**
 * 四种原生 Office 编辑器（Word / Excel / PowerPoint / PDF）共享以 md 报告编辑器为基准的视觉语言。
 * 守卫：基准 token 派生自 style.css；四个 Ribbon 的选中、悬停、按下、禁用、焦点状态引用同一组 --office-*；
 * PDF/PPTX 不再保留独立的青绿色强调色。
 */
const read = (name: string) => readFileSync(`src/${name}`, 'utf8')
const theme = read('style.css')
const office = read('office-theme.css')
const sheets = { word: read('docx.css'), workbook: read('workbook.css'), pdf: read('pdf.css') + read('pdf-ribbon.css'), slides: read('slides.css') }
const ribbonModule = read('slides-native-ribbon.ts')

function rule(selector: string) {
  for (const sheet of Array.from(document.styleSheets)) {
    for (const item of Array.from(sheet.cssRules)) {
      if (item instanceof CSSStyleRule && item.selectorText.replace(/\s+/g, ' ') === selector) return item.style
    }
  }
  throw new Error(`Missing rule: ${selector}`)
}
function rootToken(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

describe('unified native Office visual language (md baseline)', () => {
  beforeEach(() => {
    document.head.innerHTML = [theme, sheets.word, sheets.workbook, sheets.pdf, sheets.slides, office].map(css => `<style>${css}</style>`).join('')
  })

  it('derives every office token from the md editor design tokens', () => {
    expect(rootToken('--office-accent')).toBe('var(--color-primary)')
    expect(rootToken('--office-accent-soft')).toBe('var(--color-primary-soft)')
    expect(rootToken('--office-canvas')).toBe('var(--color-bg)')
    expect(rootToken('--office-pressed-bg')).toBe('var(--color-primary-soft)')
    expect(rootToken('--office-pressed-border')).toBe('var(--color-border-strong)')
    expect(rootToken('--office-hover-border')).toBe('var(--color-border-strong)')
    // md `.report-actions button` 的悬停底色、焦点环、禁用透明度与分组分隔线
    expect(theme).toMatch(/\.report-actions button:not\(\.is-primary\):hover \{[^}]*background: #f2f6f9/)
    expect(rootToken('--office-hover-bg')).toBe('#f2f6f9')
    expect(theme).toMatch(/\.report-actions button:focus-visible \{[^}]*outline: 2px solid #8fc9df/)
    expect(rootToken('--office-focus-ring')).toBe('#8fc9df')
    expect(theme).toMatch(/\.report-actions button:disabled \{[^}]*opacity: 0\.55/)
    expect(rootToken('--office-disabled-opacity')).toBe('0.55')
    expect(theme).toMatch(/\.toolbar-group \+ \.toolbar-group::before \{[^}]*background: #dfe8ef/)
    expect(rootToken('--office-separator')).toBe('#dfe8ef')
  })

  it('gives all four ribbons the same selected-tab, hover, pressed, disabled and focus treatment', () => {
    expect(rule('.docx-native .docx-ribbon .ribbon-tab.active').color).toBe('var(--office-accent)')
    expect(rule('.workbook-ribbon-tabs button[aria-selected="true"]').color).toBe('var(--office-accent)')
    expect(rule(':is(.pdf-ribbon-tabs, .slides-native-ribbon-tabs) [role="tab"][aria-selected="true"]').color).toBe('var(--office-accent)')

    expect(rule('.workbook-ribbon-group button:hover:not(:disabled)').background).toContain('var(--office-hover-bg)')
    expect(sheets.word).toContain('border-color:var(--office-hover-border); background:var(--office-hover-bg)')
    expect(office).toContain('border-color: var(--office-hover-border); background: var(--office-hover-bg)')

    for (const css of [sheets.word, sheets.workbook]) expect(css).toContain('var(--office-pressed-bg)')
    expect(office).toContain('background: var(--office-pressed-bg); color: var(--office-pressed-ink)')
    for (const css of [sheets.word, sheets.workbook, office]) {
      expect(css).toMatch(/opacity:\s?var\(--office-disabled-opacity\)/)
      expect(css).toMatch(/outline:\s?2px solid var\(--office-focus-ring\)/)
      expect(css).toMatch(/border-right:\s?1px solid var\(--office-separator\)/)
    }
  })

  it('removes the separate PDF/PPTX teal accent and inline ribbon theme', () => {
    const teal = /#(237a6e|247d70|247f70|176b5e|277e71|278071|166f62|186b60|e9eeed)\b/i
    for (const css of Object.values(sheets)) expect(css).not.toMatch(teal)
    expect(ribbonModule).not.toMatch(teal)
    expect(ribbonModule).not.toContain("document.createElement('style')")
    expect(ribbonModule).toContain("import './office-theme.css'")
    for (const entry of ['pdf-main.ts', 'docx-main.tsx', 'workbook-main.ts']) expect(read(entry)).toContain("import './office-theme.css'")
  })

  it('shares one canvas, paper shadow and status bar across the four document views', () => {
    expect(rule('.native-pdf-editor, .native-pdf-editor .pdf-document-pages, .docx-native .editor-scroll, .editor-format-docx .editor-surface, .editor-format-pptx .editor-surface, .editor-format-pptx .slides-stage').background).toBe('var(--office-canvas)')
    expect(rule('.pdf-page-content, .docx-native .doc-page, .slides-canvas .konvajs-content').boxShadow).toBe('var(--office-page-shadow)')
    const status = rule('.pdf-view-status, .docx-native .docx-view-status, .slides-statusbar')
    expect(status.background).toBe('var(--office-tabbar)')
    expect(status.fontSize).toBe('var(--office-label-size)')
  })

  it('leaves document content colours alone', () => {
    expect(sheets.pdf).toContain('.pdf-highlight{position:absolute;background:#ffe03c66')
    expect(sheets.word).toContain('.docx-native { --surface:#fff; --text:#222;')
  })
})

describe('slides canvas selection stroke', () => {
  it('reads the unified accent token instead of a hard-coded teal', async () => {
    const { officeSelectionStroke } = await import('./slides-canvas')
    const host = document.createElement('div')
    host.style.setProperty('--office-accent', '#0b4f8a')
    document.body.append(host)
    expect(officeSelectionStroke(host)).toBe('#0b4f8a')
    expect(read('slides-canvas.tsx')).not.toMatch(/#237a6e/i)
    host.remove()
  })
})
