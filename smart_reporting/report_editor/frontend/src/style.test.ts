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

  it('keeps tables and callouts quiet so data remains the focus', () => {
    const header = document.querySelector('th')!
    const quote = document.querySelector('blockquote')!

    expect(getComputedStyle(header).backgroundColor).toBe('rgb(244, 247, 249)')
    expect(getComputedStyle(quote).backgroundColor).toBe('rgb(247, 249, 250)')
    expect(getComputedStyle(quote).borderLeftColor).toBe('rgb(128, 151, 170)')
    expect(getComputedStyle(quote).paddingLeft).toBe('18px')
  })
})
