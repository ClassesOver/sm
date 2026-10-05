// 固定接口场景的详情视觉与操作验收，不替代真实登记/授权。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
const output = new URL('../../../../output/', import.meta.url)
await mkdir(output, { recursive: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/sources/validate', async route => {
    const response = await route.fetch()
    const json = await response.json()
    json.subjects[0].status = 'stale'
    json.subjects[0].warnings = ['华东地区各院区营业收入需核对登记期间与汇总口径，不自动修改报告正文。']
    json.summary = { valid: 0, stale: 1, unbound: 0 }
    await route.fulfill({ response, json })
  })
  await page.route('**/api/computations/*?*', async route => {
    const response = await route.fetch()
    const json = await response.json()
    json.parameters = { column: 'revenue', business_key: 'period_scope_'.repeat(18) }
    json.limitations = ['复算只使用当前修订登记的输入快照；新增或改动的业务口径需另行核对。']
    await route.fulfill({ response, json })
  })
  let failPage = true
  await page.route('**/api/datasets/*/preview?*', async route => {
    if (new URL(route.request().url()).searchParams.has('cursor') && failPage) {
      await route.fulfill({ status: 503, json: { detail: { code: 'source_unavailable' } } })
    } else await route.continue()
  })
  await page.route('**/api/datasets/*/download', route => route.fulfill({ status: 403 }))
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  const capture = async (name, target = page) => {
    for (const width of [1280, 390]) {
      await target.setViewportSize({ width, height: width === 390 ? 844 : 900 })
      assert.equal(await target.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${name}/${width}: 整页溢出`)
      assert.equal(await target.locator('.evidence-workspace').evaluate(node => node.scrollWidth <= node.clientWidth), true, `${name}/${width}: 工作区溢出`)
      assert.equal(await target.locator('.evidence-workspace').evaluate(node => getComputedStyle(node).backgroundColor), 'rgb(255, 255, 255)')
      if (width === 390) assert.equal(await target.locator('.evidence-pagination button, .evidence-dataset-actions button').evaluateAll(buttons =>
        buttons.every(button => button.getBoundingClientRect().height >= 40)), true)
      if (name === 'computation' && width === 390) {
        const parameters = target.locator('.evidence-computation-parameters').first()
        assert.equal(await parameters.evaluate(node => node.tabIndex), 0)
        assert.equal(await parameters.evaluate(node => node.scrollWidth > node.clientWidth), true, '长参数应在区块内横向滚动')
        await parameters.focus()
        await parameters.press('ArrowRight')
        await target.waitForFunction(() => document.querySelector('.evidence-computation-parameters').scrollLeft > 0)
      }
      await target.screenshot({ path: new URL(`report-editor-v6-detail-${name}-${width}.png`, output).pathname })
    }
    await target.setViewportSize({ width: 1280, height: 900 })
  }
  const collapse = async () => {
    const button = page.getByRole('button', { name: '收起', exact: true })
    if (await button.isVisible()) await button.click()
  }
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
  await page.locator('.evidence-fact-value').waitFor()
  await collapse()
  assert.equal(await page.locator('[data-status-row]').count(), 3)
  assert.ok((await page.locator('.evidence-warning').textContent()).includes('暂不计算差额'))
  await capture('fact-warning')
  await page.locator('.evidence-directory-item', { hasText: '渠道收入汇总' }).click()
  await page.locator('.evidence-computation-parameters').waitFor()
  await collapse()
  await capture('computation')
  await page.locator('.evidence-directory-item', { hasText: '收入明细.csv' }).click()
  await page.locator('.evidence-table').waitFor()
  const tableWidths = await page.locator('.evidence-table-wrap').evaluate(wrap => ({ wrap: wrap.offsetWidth, table: wrap.querySelector('table').offsetWidth }))
  assert.equal(tableWidths.wrap <= tableWidths.table + 2, true, '表格边界贴合列宽：' + JSON.stringify(tableWidths))
  await capture('dataset')
  await page.locator('.evidence-filter').fill('不存在的内容')
  assert.equal(await page.locator('.evidence-table tbody tr').count(), 1, '零匹配保留表头')
  assert.equal(await page.locator('.evidence-dataset-empty').textContent(), '本页没有匹配内容，可清除筛选查看本页数据。')
  await capture('zero-match')
  await page.getByRole('button', { name: '清除筛选', exact: true }).click()
  assert.equal(await page.locator('.evidence-filter').inputValue(), '')
  assert.equal(await page.locator('.evidence-filter').evaluate(node => node === document.activeElement), true)
  assert.equal(await page.locator('.evidence-dataset-empty').isVisible(), false)
  const rows = await page.locator('.evidence-table').textContent()
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await page.locator('.evidence-more-error').waitFor()
  assert.equal(await page.locator('.evidence-table').textContent(), rows)
  assert.equal(await page.getByRole('button', { name: '下一页', exact: true }).isEnabled(), true)
  await capture('page-error')
  failPage = false
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await page.locator('.evidence-dataset-scope', { hasText: '第 2 页' }).waitFor()
  await page.getByRole('button', { name: '下载此快照', exact: true }).click()
  await page.locator('.evidence-dataset-note', { hasText: '无权下载' }).waitFor()
  assert.equal(await page.locator('.evidence-dataset-note').getAttribute('role'), 'status')
  await capture('download-denied')
  const empty = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  empty.on('pageerror', error => errors.push(error.message))
  await empty.route('**/api/sources', async route => {
    const response = await route.fetch()
    const json = await response.json()
    json.datasets[0].rowCount = 0
    await route.fulfill({ response, json })
  })
  await empty.route('**/api/datasets/*/preview?*', async route => {
    const response = await route.fetch()
    const json = await response.json()
    await route.fulfill({ response, json: { ...json, rows: [], rowCountTotal: 0, offset: 0, nextCursor: null } })
  })
  await empty.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await empty.locator('[data-action="sources"]').click()
  await empty.locator('.evidence-directory-item', { hasText: '收入明细.csv' }).click()
  await empty.locator('.evidence-table').waitFor()
  assert.ok((await empty.locator('.evidence-dataset-scope').textContent()).includes('完整快照共 0 行'))
  assert.equal(await empty.locator('.evidence-dataset-empty').textContent(), '此快照没有数据行。')
  assert.equal(await empty.locator('.evidence-dataset-empty').getAttribute('role'), 'status')
  await capture('empty-snapshot', empty)
  let release
  await empty.route('**/api/computations/*?*', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ status: 503, json: { detail: { code: 'source_unavailable' } } })
  })
  await empty.locator('.evidence-directory-item', { hasText: '渠道收入汇总' }).click()
  await empty.locator('.evidence-placeholder').waitFor()
  await capture('loading', empty)
  assert.ok(release)
  release()
  await empty.getByRole('button', { name: '重试', exact: true }).waitFor()
  await capture('load-error', empty)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ detailStyle: 'passed', viewports: [1280, 390], states: ['fact-warning', 'computation', 'dataset', 'zero-match', 'page-error', 'download-denied', 'empty-snapshot', 'loading', 'load-error'] }))
} finally {
  await browser.close()
}
