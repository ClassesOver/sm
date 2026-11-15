import { beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const theme = readFileSync('src/style.css', 'utf8')
const word = readFileSync('src/docx.css', 'utf8')
const workbook = readFileSync('src/workbook.css', 'utf8')
const migrated = ['docs/ribbon.css','docs/adapter.css','sheets/reset.css','sheets/vendor/ribbon.scoped.css','sheets/adapter.css'].map(file=>readFileSync(`packages/office-desktop-ui/src/${file}`,'utf8')).join('\n')

function rule(selector: string) {
  const result=document.createElement('div').style
  let found=false
  for (const sheet of Array.from(document.styleSheets)) {
    for (const item of Array.from(sheet.cssRules)) {
      if (item instanceof CSSStyleRule && item.selectorText === selector) { found=true; for(let index=0;index<item.style.length;index++){const name=item.style[index];result.setProperty(name,item.style.getPropertyValue(name))} }
    }
  }
  if(found)return result
  throw new Error(`Missing rule: ${selector}`)
}

describe('native ribbon theme isolation', () => {
  beforeEach(() => {
    document.head.innerHTML = `<style>${theme}</style><style>${word}</style><style>${workbook}</style><style>${migrated}</style>`
    document.body.innerHTML = `
      <section class="docx-native">
        <div class="docx-ribbon"><div class="ribbon-tabs"><button class="ribbon-tab active">开始</button></div>
          <button class="rb-icon" aria-pressed="true">B</button><input class="rb-select" /></div>
        <div class="doc-page"><p style="font-family:serif;color:rgb(120,30,40)">原文格式</p></div>
      </section>
      <section><div class="workbook-ribbon"><nav class="workbook-ribbon-tabs"><button aria-selected="true">开始</button></nav>
        <div class="workbook-ribbon-group"><button aria-pressed="mixed">B</button></div></div>
        <div class="workbook-grid"><input style="border-radius:0px;font-size:18px" /></div>
      </section>`
  })

  it('uses the desktop app accents and tab typography', () => {
    expect(rule('.docx-native .docx-ribbon .ribbon-tab.active').color).toBe('var(--word-blue)')
    expect(rule('.workbook-ribbon .ribbon-tabs > button:not(.qa-btn).active').color).toBe('var(--accent-dark)')
    expect(rule('.docx-native .docx-ribbon .ribbon-tab').fontSize).toBe('13px')
    expect(rule('.workbook-ribbon .ribbon-tabs > button:not(.qa-btn)').fontWeight).toBe('600')
  })

  it('does not apply ribbon typography or input geometry to the document or grid', () => {
    const paragraph = document.querySelector('.doc-page p')!
    const gridInput = document.querySelector('.workbook-grid input')!
    expect(getComputedStyle(paragraph).fontFamily).toBe('serif')
    expect(getComputedStyle(paragraph).color).toBe('rgb(120, 30, 40)')
    expect(getComputedStyle(gridInput).fontSize).toBe('18px')
    expect(getComputedStyle(gridInput).borderRadius).toBe('0px')
  })

  it('contains overflow inside the ribbon and gives mixed formatting a distinct state', () => {
    expect(rule('.docx-native .docx-ribbon .ribbon-tabs').overflowX).toBe('auto')
    expect(rule('.docx-native .docx-ribbon .ribbon-body').overflowX).toBe('scroll')
    expect(rule('.workbook-ribbon .ribbon').overflowX).toBe('scroll')
    expect(rule('.workbook-ribbon .ribbon-group').display).toBe('flex')
    expect(migrated).toContain('outline: 1px dashed var(--border-strong)')
    expect(rule('.docx-native .docx-ribbon .ribbon-tabs').getPropertyValue('-webkit-app-region')).not.toBe('drag')
  })
})
