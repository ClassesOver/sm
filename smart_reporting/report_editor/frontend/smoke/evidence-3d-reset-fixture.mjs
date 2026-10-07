import assert from 'node:assert/strict'
import { chromium } from 'playwright'

// 定向检查追踪端点后重置的100%刻度及视图切换恢复。
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/sources*', route => route.fulfill({ json: {
    available: true, datasets: [], subjects: [],
    facts: [{ analysisId: 'analysis_001', factId: 'spatial-root', factKind: 'metric', label: '事实产出', name: '事实产出', displayValue: 1, unit: '元', datasetIds: [] }],
    drilldown: { enabled: false, metrics: [], subjects: [] },
  } }))
  await page.route('**/api/facts/**', route => {
    const factId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1))
    return route.fulfill({ json: {
      analysisId: 'analysis_001', factId, factKind: 'metric', displayValue: 1,
      entry: { unit: '元' }, warnings: [],
      inputFactRefs: factId === 'spatial-root' ? ['input-a', 'input-b', 'input-c', 'input-d', 'input-e', 'input-f'].map(factId => ({ analysisId: 'analysis_001', factId })) : [],
    } })
  })
  await page.route('**/assets/3d-force-graph-*.js', async route => {
    const response = await route.fetch()
    const source = await response.text()
    const patched = source.replace(/export\{(\w+) as default\};/, (_, constructor) => `
      function GraphProbe(...args) {
        const graph = new ${constructor}(...args);
        window.currentGraph3d = graph;
        return graph;
      }
      export { GraphProbe as default };`)
    assert.notEqual(patched, source)
    await route.fulfill({ response, body: patched })
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '事实产出' }).click()
  await page.waitForFunction(() => {
    const graph = window.currentGraph3d
    return graph && Math.abs(graph.cameraPosition().x) > 1 && Math.abs(graph.cameraPosition().y) > 1
  })
  await page.getByRole('combobox', { name: '选择 3D 节点预览' }).selectOption('fact:analysis_001/input-a')
  await page.getByRole('combobox', { name: '追踪预览关系端点' }).selectOption('fact:analysis_001/spatial-root')
  await page.getByRole('button', { name: '适应追踪关系', exact: true }).click()
  await page.waitForTimeout(400)
  const distance = () => page.evaluate(() => window.currentGraph3d.camera().position.distanceTo(window.currentGraph3d.controls().target))
  const fitted = await distance()
  await page.getByRole('button', { name: '重置视图', exact: true }).click()
  await page.waitForTimeout(400)
  const reset = await distance()
  console.log(JSON.stringify({ fitted, reset, hud: await page.locator('.evidence-camera-readout').textContent() }))
  assert.ok(Math.abs(reset - fitted) < 1e-5, '重置应适应当前可见的追踪关系')
  assert.equal((await page.locator('.evidence-camera-readout').textContent()).split('\n')[0], '缩放 100%')
  const positions = await page.evaluate(() => window.currentGraph3d.graphData().nodes.map(({ id,x,y,z }) => ({ id,x,y,z })))
  await page.getByRole('button', { name: '放大关系图', exact: true }).click()
  await page.waitForTimeout(300)
  assert.equal((await page.locator('.evidence-camera-readout').textContent()).split('\n')[0], '缩放 125%')
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
  await page.locator('.evidence-graph-3d canvas').waitFor()
  await page.waitForTimeout(300)
  assert.equal((await page.locator('.evidence-camera-readout').textContent()).split('\n')[0], '缩放 125%')
  assert.equal(await page.locator('.evidence-graph-3d').getAttribute('data-scope'), 'pair')
  assert.deepEqual(await page.evaluate(() => window.currentGraph3d.graphData().nodes.map(({ id,x,y,z }) => ({ id,x,y,z }))), positions)
  await page.getByRole('button', { name: '重置视图', exact: true }).click()
  assert.equal((await page.locator('.evidence-camera-readout').textContent()).split('\n')[0], '缩放 100%')
  await page.locator('.evidence-relations').screenshot({ path: '/home/junge/pros/smart_reporting/output/report-editor-3d-reset-trace.png' })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ reset: 'passed', zoom: 'passed', restore: 'passed', positions: 'unchanged', errors }))
} finally { await browser.close() }
