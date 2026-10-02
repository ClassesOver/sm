import assert from 'node:assert/strict'
import { chromium, firefox, webkit } from 'playwright'

const engine = process.env.REPORT_EDITOR_BROWSER ?? 'chromium'
assert.ok(['chromium', 'firefox', 'webkit'].includes(engine), `Unsupported browser: ${engine}`)
const denied = process.env.REPORT_EDITOR_CLIPBOARD_DENIED === '1'
const browser = await ({ chromium, firefox, webkit })[engine].launch({ headless: true })
try {
  const context = await browser.newContext(engine === 'chromium' && !denied
    ? { permissions: ['clipboard-read', 'clipboard-write'] } : {})
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const url = process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1'
  if (denied) {
    await page.route(url, async route => {
      const response = await route.fetch()
      await route.fulfill({ response, headers: { ...response.headers(), 'permissions-policy': 'clipboard-write=()' } })
    })
  }
  await page.goto(url, { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '收入明细.csv' }).click()
  const table = page.locator('.evidence-table')
  await table.waitFor()
  const outcomes = []
  const copy = async (count) => {
    const expected = await table.evaluate(node => [...node.querySelectorAll('tr')].map(row =>
      [...row.querySelectorAll('th, td')].map(cell => cell.textContent).join('\t')).join('\n'))
    await page.getByRole('button', { name: '复制本页', exact: true }).click()
    const success = page.getByText(`已复制本页可见 ${count} 行`, { exact: true })
    const unavailable = page.getByText('复制不可用，请手动选择表格内容复制', { exact: true })
    await success.or(unavailable).waitFor()
    if (await unavailable.isVisible()) {
      assert.equal(denied, true, 'Clipboard unexpectedly unavailable')
      outcomes.push('unavailable')
      assert.equal(await page.getByRole('button', { name: '复制本页', exact: true }).isEnabled(), true)
      return
    }
    assert.equal(denied, false, 'Clipboard write unexpectedly allowed by browser policy')
    if (engine === 'chromium') {
      assert.equal(await page.evaluate(() => navigator.clipboard.readText()), expected)
    } else {
      await page.evaluate(() => {
        const input = document.createElement('textarea')
        input.id = 'clipboard-paste-probe'
        input.setAttribute('aria-label', 'Clipboard test target')
        document.body.append(input)
        input.focus()
      })
      await page.keyboard.press('Control+V')
      await page.waitForFunction(value => document.querySelector('#clipboard-paste-probe').value === value, expected)
      await page.locator('#clipboard-paste-probe').evaluate(input => input.remove())
    }
    outcomes.push('readback')
  }
  await copy(2)
  await page.locator('.evidence-filter').fill('华东')
  await copy(2)
  await page.locator('.evidence-filter').fill('不存在')
  await copy(0)
  await page.locator('.evidence-filter').fill('华北')
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await page.locator('.evidence-dataset-scope', { hasText: '第 2 页' }).waitFor()
  await copy(2)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ browser: engine, denied, clipboardOutcomes: outcomes, filteredPages: [1, 2], emptyFilter: 'headers-only' }))
} finally {
  await browser.close()
}
