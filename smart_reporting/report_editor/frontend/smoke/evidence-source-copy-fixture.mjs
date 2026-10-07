// 使用真实复制事件验证原生Slice转换，不写入服务端正文。
import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] })
  let writes = 0
  const errors = []
  page.on('pageerror', error => errors.push(error.name))
  await page.route('**/api/document', async route => {
    if (route.request().method() !== 'GET') { writes++; return route.abort() }
    const response = await route.fetch()
    const payload = await response.json()
    payload.markdown = '# 报告\n\n## 月度收入[[analysis:analysis_001]] [[citation:sub-fixture-001]]\n\n收入 **保持稳定**。[[citation:sub-fixture-001]] 请查看[医院](https://example.invalid)。\n'
    await route.fulfill({ response, json: payload })
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  const editor = page.locator('.ProseMirror')
  await editor.waitFor()
  const original = await editor.textContent()
  await editor.focus()
  await editor.evaluate(element => {
    const range = document.createRange()
    range.selectNodeContents(element)
    const selection = window.getSelection()
    selection.removeAllRanges(); selection.addRange(range)
  })
  await page.waitForTimeout(100)
  await page.keyboard.press('Control+C')
  const copied = await page.evaluate(async () => {
    const items = await navigator.clipboard.read()
    const item = items.find(item => item.types.includes('text/plain'))
    return { text: await (await item.getType('text/plain')).text(), html: await (await item.getType('text/html')).text() }
  })
  for (const value of [copied.text, copied.html]) {
    assert.ok(!value.includes('analysis:') && !value.includes('citation:'), '复制结果不含隐藏协议')
    assert.ok(value.includes('保持稳定') && value.includes('医院'))
  }
  assert.ok(copied.text.includes('# 报告') && copied.text.includes('## 月度收入'))
  assert.ok(copied.text.includes('**保持稳定**') && copied.text.includes('[医院](https://example.invalid)'))
  assert.ok(copied.html.includes('<strong>保持稳定</strong>') && copied.html.includes('href="https://example.invalid/"'))
  assert.equal(await editor.textContent(), original)
  assert.equal(await page.locator('.report-protocol-marker[data-marker-count="2"]').count(), 1)
  assert.equal(writes, 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ plain: 'passed', html: 'passed', formatting: 'passed', original: 'unchanged', writes, errors }))
} finally { await browser.close() }
