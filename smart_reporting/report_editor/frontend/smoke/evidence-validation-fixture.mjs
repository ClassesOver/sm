// 固定 fixture：保存失败时也必须按当前草稿刷新引用校验，不重取登记详情。
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const editorUrl = process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1'
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  let factRequests = 0
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => { if (request.url().includes('/api/facts/')) factRequests += 1 })
  await page.goto(editorUrl, { waitUntil: 'networkidle' })
  await page.route('**/api/document', route => route.request().method() === 'PUT'
    ? route.fulfill({ status: 503, json: { detail: { code: 'fixture-save-unavailable' } } }) : route.continue())
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.locator('[data-status-row="citation"]', { hasText: '引用有效' }).waitFor()
  await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
  await page.locator('[data-status-row="citation"]', { hasText: '引用有效' }).waitFor()
  await page.locator('.evidence-tab-report').click()
  await page.locator('.ProseMirror').focus()
  await page.locator('.ProseMirror').evaluate(editor => {
    const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT)
    let node
    while ((node = walker.nextNode())) {
      const start = node.textContent.indexOf('12,450')
      if (start < 0) continue
      const range = document.createRange()
      range.setStart(node, start)
      range.setEnd(node, start + 6)
      const selection = window.getSelection()
      selection.removeAllRanges()
      selection.addRange(range)
      break
    }
  })
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await page.keyboard.type('12,780')
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-warning', { hasText: '需核对口径' }).waitFor()
  assert.ok((await page.locator('[data-status-row="verification"]').textContent()).includes('数值已核对'))
  assert.equal(factRequests, 1)
  assert.equal(await page.locator('.evidence-warning').textContent().then(text => text.includes('差异 +330')), false)
  await page.locator('[data-evidence="back"]').click()
  await page.locator('[data-status-row="citation"]', { hasText: '内容已变更' }).waitFor()
  const saved = await (await page.request.get(`${editorUrl}/api/document`)).json()
  assert.ok(saved.markdown.includes('12,450'))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ draftValidation: 'passed', registeredFactRequests: factRequests, unconfirmedDifference: 'not calculated' }))
} finally {
  await browser.close()
}
