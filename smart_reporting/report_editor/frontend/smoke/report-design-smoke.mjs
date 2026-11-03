import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { chromium } from 'playwright'

// 在运行中的 Vite 页面验证真实 DOM / Pointer Events；API 使用隔离的合成报告。
const url = process.env.REPORT_DESIGN_URL ?? 'http://127.0.0.1:5174/reports/v1/editor/assets/'
const fixture = JSON.parse(await readFile(new URL('../src/fixtures/report-design.json', import.meta.url), 'utf8'))
const browser = await chromium.launch({ headless: true })
const errors = []
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.on('pageerror', error => errors.push(error.message))
  let design = structuredClone(fixture)
  let designSha256 = 'a'.repeat(64)
  let generation = 0
  let editable = true
  const templates = new Map()
  const context = { title: '经营分析报告', periodLabel: '2026 年 10 月', organizationName: '示例组织', generatedByLabel: '报告团队', generatedDate: '2026-11-03', watermarkText: '内部资料' }
  const state = () => ({ design, designSha256, documentContext: context })
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname.split('/api/')[1]
    const payload = request.postDataJSON()
    let result = {}
    if (path === 'document') result = { path: 'report.md', markdown: '# 经营报告\n\n## 指标分析\n\n本期指标变化供复核。', sha256: 'b'.repeat(64), csrfToken: 'test', designEditable: editable, lineageFeatures: { panel: false, exportSources: true }, ...state() }
    else if (path === 'design' && request.method() === 'PUT') {
      assert.equal(payload.expectedDesignSha256, designSha256)
      design = payload.design
      designSha256 = (++generation).toString(16).padStart(64, '0')
      result = state()
    } else if (path === 'design') result = state()
    else if (path === 'design-templates') result = { items: [...templates.values()] }
    else if (path.startsWith('design-templates/')) {
      const templateId = path.split('/')[1]
      if (request.method() === 'DELETE') result = { deleted: templates.delete(templateId) }
      else { result = { templateId, ...payload }; templates.set(templateId, result) }
    } else if (path === 'design-preview') {
      assert.equal(payload.expectedDesignSha256, designSha256)
      result = { previewId: 'preview-1', status: 'running', documentSha256: 'b'.repeat(64), designSha256 }
    } else if (path === 'design-preview/preview-1') result = { previewId: 'preview-1', status: 'succeeded', validation: { ok: false, issues: [{ message: '合成预览告警' }] } }
    else if (path === 'sources') result = { available: false }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(result) })
  })
  await page.goto(url)
  await page.locator('.ProseMirror').waitFor()
  await page.getByRole('button', { name: '报告设计', exact: true }).click()
  const panel = page.getByRole('dialog', { name: '报告设计' })
  await panel.waitFor()
  await panel.evaluate(el => Promise.all(el.getAnimations({ subtree: true }).map(animation => animation.finished)))
  const title = panel.locator('[data-cover-block="title"]')
  const bounds = await title.boundingBox()
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + 20)
  await page.mouse.down()
  await page.mouse.move(bounds.x + bounds.width / 2 + 20, bounds.y + 40, { steps: 4 })
  await page.mouse.up()
  const movedX = Number(await panel.locator('[name="box.x"]').inputValue())
  assert.ok(Math.abs(movedX - 35) < 0.05, `拖动后 x=${movedX}`)
  await title.press('Shift+ArrowRight')
  assert.equal(Number(await panel.locator('[name="box.x"]').inputValue()), movedX + 5)
  await panel.locator('[name="box.text"]').fill('自定义封面 <script>')
  assert.equal(await title.locator('.design-cover-text').textContent(), '自定义封面 <script>')
  await panel.locator('[name="box.width"]').fill('200')
  await panel.locator('[name="box.width"]').blur()
  assert.equal(Number(await panel.locator('[name="box.x"]').inputValue()), 10)
  await page.screenshot({ path: '/tmp/report-design-smoke-cover.png' })
  await panel.locator('[data-design-tab="templates"]').click()
  await panel.locator('[name="templateName"]').fill('月报样式')
  await panel.locator('[data-design-action="template-new"]').click()
  await page.waitForFunction(() => document.querySelector('[name="templateId"]')?.options.length === 2)
  await panel.locator('[name="templateName"]').fill('月报样式修订')
  await panel.locator('[data-design-action="template-rename"]').click()
  await page.waitForFunction(() => document.querySelector('[name="templateId"]')?.selectedOptions[0]?.textContent === '月报样式修订')
  await panel.locator('[data-design-action="template-apply"]').click()
  assert.equal(await title.locator('.design-cover-text').textContent(), context.title)
  await panel.locator('[data-design-tab="typography"]').click()
  await panel.locator('[name="type.font"]').selectOption('sans')
  assert.match(await page.locator('.ProseMirror p').last().evaluate(el => getComputedStyle(el).fontFamily), /Noto Sans/)
  await panel.locator('[name="type.size"]').fill('14')
  assert.equal(await page.locator('#report-editor').evaluate(el => el.style.getPropertyValue('--design-body-size')), '14pt')
  await panel.locator('[data-design-action="preview"]').click()
  await panel.locator('[data-design-pdf]:not([hidden])').waitFor()
  assert.match(await panel.locator('[data-design-preview-status]').textContent(), /验收未通过.*合成预览告警/)
  await panel.locator('[name="type.size"]').fill('15')
  assert.match(await panel.locator('[data-design-preview-status]').textContent(), /已过期/)
  await page.screenshot({ path: '/tmp/report-design-smoke-desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await panel.evaluate(el => el.scrollWidth <= window.innerWidth), true)
  await page.screenshot({ path: '/tmp/report-design-smoke-mobile.png' })
  await panel.locator('[data-design-action="retry"]').click()
  await page.waitForFunction(() => document.querySelector('.design-save-status')?.textContent === '设计已保存')
  await panel.getByRole('button', { name: '关闭报告设计' }).click()
  editable = false
  await page.reload()
  await page.locator('.ProseMirror').waitFor()
  assert.equal(await page.locator('[data-action="export-settings"]').isVisible(), false)
  assert.equal(await page.locator('.report-design-panel').count(), 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ designSmoke: 'passed', drag: true, keyboard: true, templates: true, previewWarnings: true, stalePreview: true, responsive: true, sharedReadOnly: true }))
} finally { await browser.close() }
