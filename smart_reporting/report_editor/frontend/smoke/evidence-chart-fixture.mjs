// 固定图表 fixture：当前页、分页失败、后退和刷新恢复。
import assert from 'node:assert/strict'
import { chromium, firefox, webkit } from 'playwright'

const engine = process.env.REPORT_EDITOR_BROWSER ?? 'chromium'
assert.ok(['chromium', 'firefox', 'webkit'].includes(engine), `Unsupported browser: ${engine}`)
const browser = await ({ chromium, firefox, webkit })[engine].launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  const offsets = []
  let failNext = true
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/charts', route => route.fulfill({ json: { available: true, charts: [{
    chartId: 'chart-fixture', datasetIds: ['dataset-fixture-001'], datasetIdsRegistered: true,
    plotDataFileCount: 2, plotDataKind: 'chart-input/v1', transformNotes: [], imageSize: 100,
  }] } }))
  await page.route('**/api/charts/chart-fixture/source?*', route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0)
    offsets.push(offset)
    if (offset === 20 && failNext) {
      failNext = false
      return route.fulfill({ status: 409, json: { detail: { code: 'snapshot_integrity_failed' } } })
    }
    return route.fulfill({ json: {
      available: true, chartId: 'chart-fixture', datasetIds: ['dataset-fixture-001'],
      transformNotes: [], computationId: 'comp-fixture-001', image: { size: 100, sha256: 'a'.repeat(64) },
      plotData: [21, 2].map((rowCount, index) => ({
        fileResourceId: `plot-${index}`, role: index ? 'short' : 'main', columns: ['value'],
        rowCount, offset, limit: 20,
        rows: Array.from({ length: rowCount }, (_, row) => [`图表记录${row + 1}`]).slice(offset, offset + 20),
        truncated: offset + 20 < rowCount,
      })),
    } })
  })
  await page.goto('http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: 'chart-fixture' }).click()
  const mainTable = page.locator('.evidence-table').first()
  await mainTable.getByText('图表记录1', { exact: true }).waitFor()
  await page.getByRole('button', { name: '展开', exact: true }).click()
  const chartCanvas = page.locator('.evidence-graph-3d canvas')
  await chartCanvas.waitFor()
  const graphIds = await page.getByRole('combobox', { name: '选择 3D 节点预览' })
    .locator('option').evaluateAll(options => options.map(option => option.value).filter(Boolean).sort())
  assert.deepEqual(graphIds, ['chart:chart-fixture', 'computation:comp-fixture-001', 'dataset:dataset-fixture-001'])
  assert.equal(await page.locator('.evidence-3d-kind-key[data-kind="chart"]').count(), 1, '图表关系图保留图表类型')
  assert.equal(await page.locator('.evidence-3d-kind-key[data-kind="dataset"]').count(), 1, '图表关系图保留数据集类型')
  assert.equal(await page.locator('.evidence-3d-kind-key[data-kind="computation"]').count(), 1, '图表关系图保留计算类型')
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  assert.equal(await page.locator('.evidence-node[data-evidence-node="chart:chart-fixture"]').count(), 1, '2D关系图保留图表节点')
  const inputPairs = await page.locator('.evidence-graph-edge').evaluateAll(edges =>
    edges.map(edge => [edge.dataset.from, edge.dataset.to]).sort())
  assert.deepEqual(inputPairs, [
    ['computation:comp-fixture-001', 'chart:chart-fixture'],
    ['dataset:dataset-fixture-001', 'chart:chart-fixture'],
  ], '2D图表关系保留两个登记输入及方向')
  await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
  await chartCanvas.waitFor()
  await page.locator('.evidence-more').click()
  await page.locator('.evidence-more-error').waitFor()
  assert.equal(await mainTable.locator('tr:has(td)').count(), 20)
  assert.equal(await page.locator('.evidence-more').isEnabled(), true)
  await page.locator('.evidence-more').click()
  await mainTable.getByText('图表记录21', { exact: true }).waitFor()
  assert.equal(await mainTable.locator('tr:has(td)').count(), 1)
  await page.getByText('共 2 行 · 当前页无预览记录', { exact: true }).waitFor()
  // 在同任务进入计算，再后退，图表当前页继续复用。
  await page.getByRole('button', { name: '切换到关系列表', exact: true }).click()
  await page.locator('.evidence-relation-list button', { hasText: 'comp-fixture-001' }).click()
  await page.locator('[data-evidence="back"]').click()
  await mainTable.getByText('图表记录21', { exact: true }).waitFor()
  assert.deepEqual(offsets, [0, 20, 20])
  await page.reload({ waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await mainTable.getByText('图表记录21', { exact: true }).waitFor()
  assert.deepEqual(offsets, [0, 20, 20, 20])
  await page.locator('.evidence-previous').click()
  await mainTable.getByText('图表记录1', { exact: true }).waitFor()
  assert.equal(await mainTable.locator('tr:has(td)').count(), 20)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ chartPaging: 'passed', chartGraph: 'passed', graphIds, inputPairs, offsets }))
} finally {
  await browser.close()
}
