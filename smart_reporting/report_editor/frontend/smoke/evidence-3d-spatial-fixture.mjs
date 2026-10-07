import assert from 'node:assert/strict'
import { chromium } from 'playwright'

// 定向检查原生深度分层、相机方向与现场恢复；不替代密集名称避障验收。
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
      inputFactRefs: factId === 'spatial-root' ? ['input-a', 'input-b'].map(factId => ({ analysisId: 'analysis_001', factId })) : [],
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
  const initial = await page.evaluate(() => {
    const graph = window.currentGraph3d
    const nodes = graph.graphData().nodes
    return {
      mode: graph.dagMode(),
      layers: new Set(nodes.map(node => node.z)).size,
      positions: nodes.map(({ id, x, y, z }) => ({ id, x, y, z })),
      directions: graph.graphData().links.map(link => link.target.z - link.source.z),
    }
  })
  assert.equal(initial.mode, 'zin')
  assert.ok(initial.layers >= 2)
  assert.ok(initial.directions.every(distance => distance > 0), '输入位于产出后方')
  const readout = page.locator('.evidence-camera-readout')
  assert.ok((await readout.textContent()).includes('缩放 100%'))
  assert.match(await readout.textContent(), /水平 -?\d+° · 俯仰 -?\d+° · 倾斜 -?\d+°/)
  await page.getByRole('button', { name: '放大关系图', exact: true }).click()
  await page.waitForFunction(() => Number(document.querySelector('.evidence-camera-readout').textContent.match(/缩放 (\d+)%/)[1]) > 100)
  await page.waitForTimeout(250)
  const savedReadout = await readout.textContent()
  await page.evaluate(() => {
    const grid = window.currentGraph3d.scene().children.find(object => object.type === 'GridHelper')
    window.gridDisposed = { geometry: false, material: false }
    grid.geometry.addEventListener('dispose', () => window.gridDisposed.geometry = true)
    grid.material.addEventListener('dispose', () => window.gridDisposed.material = true)
  })
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  assert.deepEqual(await page.evaluate(() => window.gridDisposed), { geometry: true, material: true })
  await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
  await page.locator('.evidence-graph-3d canvas').waitFor()
  const restored = await page.evaluate(() => window.currentGraph3d.graphData().nodes.map(({ id, x, y, z }) => ({ id, x, y, z })))
  assert.deepEqual(restored, initial.positions, '模式往返保持已有节点坐标')
  assert.equal(await readout.textContent(), savedReadout, '模式往返保持缩放及旋转刻度')
  assert.equal(await page.evaluate(() => window.currentGraph3d.scene().children.filter(object => object.type === 'GridHelper').length), 1)
  await page.evaluate(() => {
    window.currentGraph3d.cameraPosition({ x: 0, y: 0, z: 300 }, { x: 0, y: 0, z: 0 }, 0)
    window.currentGraph3d.controls().update()
  })
  await page.getByRole('button', { name: '重置视图', exact: true }).click()
  await page.waitForFunction(() => Math.abs(window.currentGraph3d.cameraPosition().x) > 1 && Math.abs(window.currentGraph3d.cameraPosition().y) > 1)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ layers: initial.layers, restore: 'passed', reset: 'passed', gridDisposal: 'passed', errors }))
} finally {
  await browser.close()
}
