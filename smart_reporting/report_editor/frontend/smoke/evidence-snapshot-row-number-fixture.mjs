// 宽表固定序号验收：列窗口、分页、筛选与横向滚动；不替代真实后端权限验证。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
const output = new URL('../../../../output/', import.meta.url)
await mkdir(output, { recursive: true })
try {
  for (const width of [1280, 390]) {
    const page = await browser.newPage({ viewport: { width, height: width === 390 ? 844 : 900 } })
    page.setDefaultTimeout(15000)
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const columns = Array.from({ length: 61 }, (_, i) => `字段${i + 1}`)
    await page.route('**/api/datasets/*/columns', route => route.fulfill({ json: {
      datasetId: 'dataset-fixture-001', columns, restricted: true, maxColumnsPerPage: 50,
    } }))
    await page.route('**/api/datasets/*/preview?*', route => {
      const url = new URL(route.request().url())
      const selected = url.searchParams.getAll('columns')
      if (!selected.length) return route.fulfill({ status: 422, json: { detail: { code: 'resource_limit_exceeded' } } })
      const offset = url.searchParams.has('cursor') ? 2 : 0
      return route.fulfill({ json: {
        datasetId: 'dataset-fixture-001', columns: selected,
        rows: [1, 2].map(i => selected.map(name => `${name}-row-${offset + i}`)),
        rowCountTotal: 4, offset, limit: 50, nextCursor: offset ? null : 'page-2',
        truncatedCells: 0, truncatedByBudget: false,
      } })
    })
    const rowNumbers = () => page.locator('td.evidence-row-number').allTextContents()
    await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
    if (!(await page.locator('[data-action="sources"]').isVisible())) {
      await page.getByRole('button', { name: '更多操作', exact: true }).click()
    }
    await page.locator('[data-action="sources"]').click()
    const datasetItem = page.locator('.evidence-directory-item', { hasText: '季度收入快照' })
    await datasetItem.waitFor({ state: 'attached' })
    if (!(await datasetItem.isVisible())) {
      await page.locator('.evidence-directory-toggle').click()
    }
    await datasetItem.click()
    await page.locator('.evidence-column-window').waitFor()
    assert.deepEqual(await rowNumbers(), ['1', '2'])
    assert.equal(await page.locator('.evidence-table th:not(.evidence-row-number)').count(), 50)
    await page.locator('.evidence-filter').fill('row-2')
    assert.deepEqual(await rowNumbers(), ['2'])
    await page.locator('.evidence-filter').fill('')
    await page.getByRole('button', { name: '下一页', exact: true }).click()
    await page.locator('.evidence-dataset-scope', { hasText: '预览序号 3–4' }).waitFor()
    assert.deepEqual(await rowNumbers(), ['3', '4'])
    await page.locator('.evidence-column-window').selectOption('1')
    await page.locator('.evidence-table th', { hasText: '字段51' }).waitFor()
    assert.deepEqual(await rowNumbers(), ['1', '2'])
    const geometry = await page.locator('.evidence-table-wrap').evaluate(wrap => {
      wrap.scrollLeft = wrap.scrollWidth
      const left = wrap.getBoundingClientRect().left
      return {
        scroll: wrap.scrollLeft,
        cells: [...wrap.querySelectorAll('th.evidence-row-number, td.evidence-row-number')].map(cell => ({
          left: cell.getBoundingClientRect().left - left, width: cell.getBoundingClientRect().width,
        })),
        overflow: document.documentElement.scrollWidth > innerWidth,
      }
    })
    assert.ok(geometry.scroll > 0)
    assert.equal(geometry.overflow, false)
    assert.ok(geometry.cells.every(cell => Math.abs(cell.left - 1) <= 1 && cell.width >= 110), JSON.stringify(geometry))
    await page.screenshot({ path: new URL(`report-editor-snapshot-row-number-${width}.png`, output).pathname })
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log(JSON.stringify({ viewports: [1280, 390], pagination: true, filtering: true, columnWindows: true, stickyRowNumbers: true }))
} finally {
  await browser.close()
}
