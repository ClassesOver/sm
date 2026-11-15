import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import postcss from 'postcss'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const source = postcss.parse(read('./vendor/genoffice-docs/apps/docs/src/renderer/styles.css'))
const packaged = '../packages/office-desktop-ui/src/docs/'
const scoped = postcss.parse(read(packaged + 'ribbon.css'))
const adapter = postcss.parse(read(packaged + 'adapter.css'))
const host = postcss.parse(read('./docx.css'))
const declarations = (sheet: postcss.Root, selector: string) => {
  const result: string[][] = []
  sheet.walkRules(rule => {
    if (rule.selector === selector) result.push(rule.nodes.filter(node => node.type === 'decl').map(node => node.toString()))
  })
  return result
}

describe('direct desktop Word ribbon migration', () => {
  it.each([
    '.ribbon', '.ribbon-tabs', '.ribbon-tab', '.ribbon-tab:hover', '.ribbon-tab.active',
    '.ribbon-tab.active::after', '.ribbon-tab-file', '.ribbon-body', '.ribbon-group',
    '.ribbon-group-items', '.ribbon-group-label', '.ribbon-sep', '.rb-big', '.rb-big-icon',
    '.rb-big .rb-big-icon', '.rb-big:hover:not(:disabled) .rb-big-icon', '.rb-icon',
    '.rb-icon:hover:not(:disabled)', '.rb-icon.active', '.rb-icon:disabled', '.rb-select',
    '.rb-font-family', '.rb-font-size', '.rb-row', '.rb-small',
  ])('uses unchanged pinned upstream declarations for %s', selector => {
    const original = declarations(source, selector)
    expect(original.length).toBeGreaterThan(0)
    const migrated = declarations(scoped, selector === '.ribbon' ? '.docx-native .docx-ribbon' : `.docx-native .docx-ribbon ${selector}`)
    expect(selector === '.ribbon' ? migrated.slice(1) : migrated).toEqual(original)
  })

  it('loads the selector adapter and leaves source control appearance in authority', () => {
    expect(read('./docx-main.tsx')).toContain("import './vendor/genoffice-docs/scoped.css'")
    expect(read('./docx.css')).toContain("@import '@smart-reporting/office-desktop-ui/docs.css'")
    host.walkRules(rule => expect(rule.selector).not.toMatch(/ribbon-tab|ribbon-body|rb-icon|rb-big|ribbon-group/))
    adapter.walkRules(rule => {
      expect(rule.selector).toMatch(/^\.docx-native \.docx-ribbon/)
      expect(rule.selector).not.toMatch(/ProseMirror|docx-page|document|paper/)
      if (rule.selector === '.docx-native .docx-ribbon .ribbon-tab') {
        expect(rule.nodes.map(node => node.toString())).toEqual(['flex-shrink: 0'])
      }
    })
    expect(read(packaged + 'adapter.css')).toContain('f8c17004fb730df11f0f743164ffd8b4281bb38c')
  })

  it('keeps packaged chrome independent of old app UI and document styling', () => {
    const css = read(packaged + 'ribbon.css') + read(packaged + 'adapter.css')
    expect(css).not.toContain('@import')
    expect(css).not.toContain('vendor/genoffice-docs')
    scoped.walkRules(rule => {
      expect(rule.selector).toContain('.docx-native .docx-ribbon')
      expect(rule.selector).not.toMatch(/ProseMirror|\.page\b|\.document\b|\.paper\b/)
    })
    expect(read(packaged + 'index.css')).toBe("@import './ribbon.css';\n@import './adapter.css';\n")
  })
})
