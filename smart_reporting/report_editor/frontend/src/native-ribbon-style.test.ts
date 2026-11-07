import { beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const theme = readFileSync('src/style.css', 'utf8')
const word = readFileSync('src/docx.css', 'utf8')
const workbook = readFileSync('src/workbook.css', 'utf8')

function rule(selector: string) {
  for (const sheet of Array.from(document.styleSheets)) {
    for (const item of Array.from(sheet.cssRules)) {
      if (item instanceof CSSStyleRule && item.selectorText === selector) return item.style
    }
  }
  throw new Error(`Missing rule: ${selector}`)
}

describe('native ribbon theme isolation', () => {
  beforeEach(() => {
    document.head.innerHTML = `<style>${theme}</style><style>${word}</style><style>${workbook}</style>`
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

  it('uses the report action palette for both active tabs and keeps the font inherited', () => {
    expect(rule('.docx-native .docx-ribbon .ribbon-tab.active').color).toBe('var(--color-primary)')
    expect(rule('.workbook-ribbon-tabs button[aria-selected="true"]').color).toBe('var(--color-primary)')
    expect(rule('.docx-native .docx-ribbon').fontFamily).toBe('inherit')
    expect(rule('.workbook-ribbon').fontFamily).toBe('inherit')
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
    expect(rule('.docx-native .docx-ribbon .ribbon-body').overflowX).toBe('auto')
    expect(rule('.workbook-ribbon-body').overflowX).toBe('auto')
    expect(rule('.workbook-ribbon-group').display).toBe('grid')
    expect(rule('.workbook-ribbon-group').getPropertyValue('grid-template-rows')).toBe('repeat(3,32px)')
    expect(rule('.workbook-ribbon-group button[aria-pressed="mixed"]').borderStyle).toBe('dashed')
    expect(rule('.docx-native .docx-ribbon .ribbon-tabs').getPropertyValue('-webkit-app-region')).not.toBe('drag')
  })
})
