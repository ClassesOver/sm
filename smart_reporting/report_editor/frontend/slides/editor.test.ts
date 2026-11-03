import { describe, expect, it } from 'vitest'
import { mountEditor } from './editor'
import type { SlidesDocument } from './state'

const documentFixture = (): SlidesDocument => ({
  reportId: 'report', revision: 1, sha256: 'old-sha', csrfToken: 'csrf-token', width: 1280, height: 720,
  slides: [{ index: 0, title: '首页', background: '#ffffff', elements: [
    { id: 'title', kind: 'text', text: '标题', x: 40, y: 40, width: 600, height: 90, fontSize: 32, rotation: 0 },
  ] }],
})
const settle = async () => { for (let n = 0; n < 12; n++) await Promise.resolve() }
const button = (root: HTMLElement, text: string) => [...root.querySelectorAll('button')].find((item) => item.textContent === text)!

describe('幻灯片显式保存与导出', () => {
  it('导出先保存正在编辑的文字，再用更新的 sha 导出；验收失败仍提供下载', async () => {
    const root = document.createElement('div')
    document.body.replaceChildren(root)
    const requests: { url: string; body: Record<string, unknown>; csrf: string | null }[] = []
    const send: typeof fetch = async (url, options) => {
      requests.push({ url: String(url), body: JSON.parse(String(options?.body)), csrf: new Headers(options?.headers).get('x-csrf-token') })
      if (String(url).endsWith('/draft')) {
        const result = documentFixture()
        result.sha256 = 'new-sha'
        result.slides[0].elements[0].text = '新标题'
        return new Response(JSON.stringify(result))
      }
      return new Response(JSON.stringify({ pptx: { downloadUrl: '/download/report.pptx', size: 100, sha256: 'artifact-sha', expiresAt: '2026-11-04' }, validation: { ok: false, issues: ['标题超出边界'] } }))
    }
    mountEditor(root, documentFixture(), '/reports/v1/slides/report/revision', send)
    root.querySelector<HTMLElement>('[data-element-id="title"]')!.click()
    const textarea = root.querySelector<HTMLTextAreaElement>('textarea')!
    textarea.value = '新标题'
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
    expect(requests).toEqual([])
    button(root, '保存并导出 PPTX').click()
    await settle()
    expect(requests.map(({ url, body, csrf }) => ({ url, body, csrf }))).toEqual([
      { url: '/reports/v1/slides/report/revision/draft', body: { expectedSha256: 'old-sha', operations: [{ op: 'update', slide: 0, id: 'title', text: '新标题' }] }, csrf: 'csrf-token' },
      { url: '/reports/v1/slides/report/revision/export', body: { expectedSha256: 'new-sha' }, csrf: 'csrf-token' },
    ])
    expect(new URL(root.querySelector<HTMLAnchorElement>('a[download]')!.href).pathname).toBe('/download/report.pptx')
    expect(root.textContent).toContain('标题超出边界')
    expect(root.textContent).toContain('未通过')
    expect([...root.querySelectorAll<HTMLButtonElement>('.slide-thumbnail')].every((item) => !item.disabled)).toBe(true)
  })

  it('409 保存失败后保留输入、未保存状态，且不继续导出', async () => {
    const root = document.createElement('div')
    document.body.replaceChildren(root)
    let requestCount = 0
    const send: typeof fetch = async () => {
      requestCount++
      return new Response(JSON.stringify({ detail: { code: 'conflict', message: '版本冲突' } }), { status: 409 })
    }
    mountEditor(root, documentFixture(), '/slides/report/revision', send)
    root.querySelector<HTMLElement>('[data-element-id="title"]')!.click()
    const textarea = root.querySelector<HTMLTextAreaElement>('textarea')!
    textarea.value = '保留文案'
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
    button(root, '保存并导出 PPTX').click()
    await settle()
    expect(requestCount).toBe(1)
    expect(root.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('保留文案')
    expect(root.textContent).toContain('未保存')
    expect(root.textContent).toContain('版本冲突')
    expect(button(root, '保存草稿').disabled).toBe(false)
  })
})

describe('幻灯片尺寸与属性契约', () => {
  it.each([2, undefined])('主画布和缩略图使用文档字体缩放，缺省兼容旧文档（%s）', (fontScale) => {
    const root = document.createElement('div')
    document.body.replaceChildren(root)
    const model = { ...documentFixture(), fontScale }
    mountEditor(root, model, '/slides/report/1')
    const main = root.querySelector<HTMLElement>('.slide-canvas .slide-element-text')!
    const thumbnail = root.querySelector<HTMLElement>('.thumbnail-preview .slide-element-text')!
    expect(parseFloat(main.style.fontSize)).toBeCloseTo(fontScale === 2 ? 40 : 26.66666667)
    expect(parseFloat(thumbnail.style.fontSize)).toBeCloseTo(fontScale === 2 ? 8.2 : 5.46666667)
  })

  it.each(['', '   '])('空字体会阻止保存，修正后发送清理过的字体名称（%j）', async (invalidFont) => {
    const root = document.createElement('div')
    document.body.replaceChildren(root)
    const requests: unknown[] = []
    const send: typeof fetch = async (_url, options) => {
      requests.push(JSON.parse(String(options?.body)))
      return new Response(JSON.stringify(documentFixture()))
    }
    mountEditor(root, documentFixture(), '/slides/report/1', send)
    root.querySelector<HTMLElement>('[data-element-id="title"]')!.click()
    const font = root.querySelector<HTMLInputElement>('input[type="text"]')!
    font.value = invalidFont
    font.dispatchEvent(new Event('input', { bubbles: true }))
    expect(font.validity.valid).toBe(false)
    button(root, '保存草稿').click()
    await settle()
    expect(requests).toEqual([])
    font.value = '  Arial  '
    font.dispatchEvent(new Event('input', { bubbles: true }))
    expect(font.validity.valid).toBe(true)
    button(root, '保存草稿').click()
    await settle()
    expect(requests).toEqual([{ expectedSha256: 'old-sha', operations: [{ op: 'update', slide: 0, id: 'title', fontFamily: 'Arial' }] }])
  })

  it('线条以 fill 显示描边颜色，编辑线条颜色不创建矩形底色', async () => {
    const root = document.createElement('div')
    document.body.replaceChildren(root)
    const model = documentFixture()
    model.slides[0].elements.push({ id: 'line', kind: 'shape', shape: 'line', fill: '#bb1122', color: '#000000', x: 20, y: 200, width: 500, height: 2, rotation: 0 })
    const requests: unknown[] = []
    const send: typeof fetch = async (_url, options) => {
      requests.push(JSON.parse(String(options?.body)))
      return new Response(JSON.stringify(model))
    }
    mountEditor(root, model, '/slides/report/1', send)
    root.querySelector<HTMLElement>('[data-element-id="line"]')!.click()
    const line = root.querySelector<HTMLElement>('.slide-canvas [data-element-id="line"]')!
    const thumbnail = root.querySelector<HTMLElement>('.thumbnail-preview .slide-element-shape')!
    expect(line.style.backgroundColor).toBe('')
    expect(line.style.borderBottomColor).toBe('rgb(187, 17, 34)')
    expect(thumbnail.style.borderBottomColor).toBe('rgb(187, 17, 34)')
    const label = [...root.querySelectorAll('label')].find((item) => item.textContent === '线条颜色')!
    expect(label).toBeDefined()
    const input = label.querySelector<HTMLInputElement>('input')!
    input.value = '#335577'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    expect(root.querySelector<HTMLElement>('.slide-canvas [data-element-id="line"]')!.style.borderBottomColor).toBe('rgb(51, 85, 119)')
    button(root, '保存草稿').click()
    await settle()
    expect(requests).toEqual([{ expectedSha256: 'old-sha', operations: [{ op: 'update', slide: 0, id: 'line', fill: '#335577' }] }])
  })
})

describe('发布门禁结果', () => {
  it('门禁允许发布时，载入、保存和导出不误报失败并保留下载链接', async () => {
    const root = document.createElement('div')
    document.body.replaceChildren(root)
    const model = { ...documentFixture(), publicationGate: { formalReleaseAllowed: true, issues: [] } }
    const send: typeof fetch = async (url) => new Response(JSON.stringify(String(url).endsWith('/draft')
      ? { ...model, sha256: 'new-sha' }
      : { pptx: { downloadUrl: '/download/report.pptx', size: 100, sha256: 'artifact-sha', expiresAt: '2026-11-04' }, validation: { ok: true, issues: [] }, publicationGate: model.publicationGate }))
    mountEditor(root, model, '/slides/report/1', send)
    expect(root.textContent).not.toContain('未通过')
    root.querySelector<HTMLElement>('[data-element-id="title"]')!.click()
    const text = root.querySelector<HTMLTextAreaElement>('textarea')!
    text.value = '新标题'
    text.dispatchEvent(new Event('input', { bubbles: true }))
    button(root, '保存草稿').click()
    await settle()
    expect(root.textContent).not.toContain('未通过')
    button(root, '保存并导出 PPTX').click()
    await settle()
    expect(root.textContent).not.toContain('未通过')
    expect(root.querySelector('.editor-message')?.textContent).toContain('可下载并继续编辑')
    expect(new URL(root.querySelector<HTMLAnchorElement>('a[download]')!.href).pathname).toBe('/download/report.pptx')
  })

  it('门禁不允许发布时，载入、保存和导出保留具体原因，验收成功也显示发布告警且允许下载', async () => {
    const root = document.createElement('div')
    document.body.replaceChildren(root)
    const model = { ...documentFixture(), publicationGate: { formalReleaseAllowed: false, issues: [{ code: 'needs_review', message: '发布证据仍需复核' }] } }
    const send: typeof fetch = async (url) => new Response(JSON.stringify(String(url).endsWith('/draft')
      ? { ...model, sha256: 'new-sha' }
      : { pptx: { downloadUrl: '/download/report.pptx', size: 100, sha256: 'artifact-sha', expiresAt: '2026-11-04' }, validation: { ok: true, issues: [] }, publicationGate: model.publicationGate }))
    mountEditor(root, model, '/slides/report/1', send)
    expect(root.textContent).toContain('发布检查未通过')
    expect(root.textContent).toContain('发布证据仍需复核')
    root.querySelector<HTMLElement>('[data-element-id="title"]')!.click()
    const text = root.querySelector<HTMLTextAreaElement>('textarea')!
    text.value = '待复核标题'
    text.dispatchEvent(new Event('input', { bubbles: true }))
    button(root, '保存草稿').click()
    await settle()
    expect(root.textContent).toContain('发布检查未通过')
    expect(root.textContent).toContain('发布证据仍需复核')
    button(root, '保存并导出 PPTX').click()
    await settle()
    expect(root.querySelector('.editor-message')?.textContent).toContain('发布检查未通过')
    expect(root.textContent).toContain('发布证据仍需复核')
    expect(new URL(root.querySelector<HTMLAnchorElement>('a[download]')!.href).pathname).toBe('/download/report.pptx')
  })
})
