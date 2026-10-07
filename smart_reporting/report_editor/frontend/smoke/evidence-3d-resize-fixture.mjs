import assert from 'node:assert/strict'
import { chromium } from 'playwright'

// 定向检查桌面/竖屏/横屏尺寸变化，原生适应调整距离并保留用户现场。
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
  const snapshot = () => page.evaluate(() => {
    const graph = window.currentGraph3d, target = graph.controls().target
    const viewport = document.querySelector('.evidence-graph-3d')
    const offset = graph.camera().position.clone().sub(target).normalize()
    return { width: viewport.clientWidth, height: viewport.clientHeight,
      zoom: document.querySelector('.evidence-camera-readout').textContent.split('\n')[0],
      target: target.toArray(), direction: offset.toArray(), up: graph.camera().up.toArray(),
      positions: graph.graphData().nodes.map(({id,x,y,z}) => ({id,x,y,z})),
      points: graph.graphData().nodes.map(node => graph.graph2ScreenCoords(node.x,node.y,node.z)) }
  })
  const equalVector = (actual, expected) => actual.forEach((value,index) => assert.ok(Math.abs(value-expected[index]) < 1e-6))
  const initial = await snapshot()
  assert.equal(initial.zoom, '缩放 100%')
  await page.setViewportSize({width:390,height:844})
  await page.getByRole('button',{name:'查看关系图',exact:true}).click()
  await page.waitForTimeout(350)
  const mobile = await snapshot()
  assert.equal(mobile.zoom, initial.zoom)
  assert.ok(mobile.points.every(point => point.x > 14 && point.x < mobile.width-14 && point.y > 14 && point.y < mobile.height-14), '桌面切窄屏后节点仍在画布内')
  assert.deepEqual(mobile.positions, initial.positions)
  equalVector(mobile.direction, initial.direction)
  equalVector(mobile.target, initial.target)
  await page.getByRole('button',{name:'放大关系图',exact:true}).click()
  await page.waitForTimeout(300)
  await page.evaluate(() => {
    const graph = window.currentGraph3d, target = graph.controls().target.clone()
    const position = graph.camera().position.clone()
    target.x += 4; target.y += 2; position.x += 4; position.y += 2
    graph.cameraPosition(position, target, 0)
    graph.controls().update()
  })
  const user = await snapshot()
  assert.equal(user.zoom, '缩放 125%')
  for (const [width,height] of [[844,390],[390,844],[1280,900]]) {
    await page.setViewportSize({width,height})
    await page.waitForTimeout(350)
    const resized = await snapshot()
    assert.equal(resized.zoom, user.zoom)
    equalVector(resized.direction, user.direction)
    equalVector(resized.target, user.target)
    equalVector(resized.up, user.up)
    assert.deepEqual(resized.positions, initial.positions)
  }
  const beforeMode = await snapshot()
  await page.getByRole('button',{name:'切换到 2D 关系图',exact:true}).click()
  await page.getByRole('button',{name:'切换到 3D 关系图',exact:true}).click()
  await page.waitForTimeout(300)
  const restored = await snapshot()
  assert.equal(restored.zoom, beforeMode.zoom)
  equalVector(restored.target, beforeMode.target)
  equalVector(restored.direction, beforeMode.direction)
  assert.deepEqual(restored.positions, initial.positions)
  const canvas = page.locator('.evidence-graph-3d canvas')
  await page.mouse.move(0,0)
  const beforePreview = await canvas.screenshot()
  await page.getByRole('combobox',{name:'选择 3D 节点预览'}).selectOption('fact:analysis_001/input-a')
  await page.getByRole('button',{name:'关闭预览',exact:true}).click()
  await page.mouse.move(0,0)
  await page.waitForTimeout(300)
  assert.equal((await canvas.screenshot()).equals(beforePreview), true, '同尺寸关闭预览后恢复原视角像素')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({resize:'passed',bounds:'passed',zoom:'passed',pan:'passed',direction:'passed',restore:'passed',errors}))
} finally {await browser.close()}
