// 与2D复杂图使用同一关系形态；仅验证固定前端数据，不验证后端权限。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const analysisId = 'analysis-fixture-001'
const root = 'fact-fixture-001'
const layer = prefix => Array.from({ length: 12 }, (_, i) => `${prefix}-${i}`)
const first = layer('first')
const shared = layer('shared')
const branch = layer('branch')
const longLabels = process.env.REPORT_EDITOR_LONG_LABELS === '1'
const suffix = longLabels ? '-long' : ''
if (longLabels) {
  first[0] = '跨院区收入与成本口径调整后月度汇总计算结果'.repeat(3)
  shared[0] = '医疗服务收入明细与患者来源渠道关联输入快照'.repeat(3)
}
const inputs = new Map([
  [root, first],
  [first[0], [...shared, root, first[0]]],
  [first[1], [...shared, ...branch]],
  [branch[0], [first[1], root]],
])
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/facts/**', route => {
    const factId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1))
    return route.fulfill({ json: {
      analysisId, factId, factKind: 'metric', displayValue: 12450,
      entry: { unit: '万元' }, inputFactRefs: (inputs.get(factId) ?? []).map(factId => ({ analysisId, factId })), warnings: [],
    } })
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
  const canvas = page.locator('.evidence-graph-3d canvas')
  // 检查真实渲染像素：内缩2px避开主题边框/截图舍入，标签或球体触边即视为裁切风险。
  const fitsCanvas = async () => page.evaluate(async png => {
    const image = new Image()
    image.src = `data:image/png;base64,${png}`
    await image.decode()
    const probe = document.createElement('canvas')
    probe.width = image.width
    probe.height = image.height
    const context = probe.getContext('2d')
    context.drawImage(image, 0, 0)
    const { data } = context.getImageData(0, 0, probe.width, probe.height)
    const background = (x, y) => {
      const offset = (y * probe.width + x) * 4
      return [247, 251, 253].every((value, channel) => Math.abs(data[offset + channel] - value) <= 2)
    }
    const pixel = (x, y) => ({ x, y, color: [...data.slice((y * probe.width + x) * 4, (y * probe.width + x) * 4 + 4)] })
    for (let x = 2; x < probe.width - 2; x++) {
      if (!background(x, 2)) return pixel(x, 2)
      if (!background(x, probe.height - 3)) return pixel(x, probe.height - 3)
    }
    for (let y = 2; y < probe.height - 2; y++) {
      if (!background(2, y)) return pixel(2, y)
      if (!background(probe.width - 3, y)) return pixel(probe.width - 3, y)
    }
    return true
  }, (await canvas.screenshot()).toString('base64'))
  const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
  const trace = page.getByRole('combobox', { name: '追踪预览关系端点' })
  await canvas.waitFor()
  assert.equal(await picker.locator('option').count(), 16)
  const title = await page.locator('.evidence-object-title').textContent()
  const back = await page.locator('[data-evidence="back"]').isEnabled()
  for (const [key, count] of [[first[0], 27], [first[1], 39], [branch[0], 39]]) {
    await picker.selectOption(`fact:${analysisId}/${key}`)
    await page.locator('.evidence-branch-load').click()
    await page.getByRole('button', { name: '已加载登记关系', exact: true }).waitFor()
    assert.equal(await picker.locator('option').count(), count + 1)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), back)
  }
  // 对照2D累计图，确认两种模式共享39个身份和55条真实登记边。
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  assert.equal(await page.locator('.evidence-node').count(), 39)
  assert.equal(await page.locator('.evidence-graph-edge').count(), 55)
  await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
  await canvas.waitFor()
  const output = new URL('../../../../output/', import.meta.url)
  await mkdir(output, { recursive: true })
  for (const [width, height] of [[1280, 900], [390, 844], [844, 390]]) {
    await page.setViewportSize({ width, height })
    if (width === 390) await page.getByRole('button', { name: '查看关系图', exact: true }).click()
    await picker.selectOption(`fact:${analysisId}/${first[0]}`)
    // 自引用边仍登记，但不作为端点选项列出。
    assert.equal(await trace.locator(`option[value="fact:${analysisId}/${first[0]}"]`).count(), 0)
    await trace.selectOption(`fact:${analysisId}/${shared[0]}`)
    if (longLabels) {
      assert.equal(await picker.locator('option:checked').textContent(), `事实 · ${first[0]}`, '预览选择器保留完整名称')
      assert.equal(await trace.locator('option:checked').textContent(), `追踪：事实 · ${shared[0]}`, '追踪选择器保留完整名称')
      assert.equal((await page.locator('.evidence-preview-summary').textContent()).includes(first[0]), true)
    }
    await page.locator('.evidence-3d-trace-status', { hasText: '追踪 1 条登记关系' }).waitFor()
    await page.getByRole('button', { name: '适应追踪关系', exact: true }).click()
    await page.waitForTimeout(250)
    await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-complex-3d-trace-${width}${suffix}.png`, output).pathname })
    assert.equal(await fitsCanvas(), true, `${width}px追踪名称与图形不触及画布四边`)
    await page.getByRole('button', { name: '缩小关系图', exact: true }).click()
    await page.waitForTimeout(250)
    assert.equal(await fitsCanvas(), true, `${width}px缩小后名称与图形不触及画布四边`)
    await canvas.screenshot({ path: new URL(`report-editor-v6-complex-3d-trace-zoom-${width}${suffix}.png`, output).pathname })
    await page.getByRole('button', { name: '放大关系图', exact: true }).click()
    await page.waitForTimeout(250)
    assert.equal(await trace.inputValue(), `fact:${analysisId}/${shared[0]}`)
    await page.locator('.evidence-3d-trace-status', { hasText: '追踪 1 条登记关系' }).waitFor()
    await trace.selectOption('')
    await page.getByRole('button', { name: '适应 3D', exact: true }).click()
    await page.waitForTimeout(250)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    assert.equal(await canvas.evaluate(node => node.getBoundingClientRect().height > 100), true)
    await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-complex-3d-${width}${suffix}.png`, output).pathname })
    assert.equal(await picker.inputValue(), `fact:${analysisId}/${first[0]}`)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), back)
  }
  await picker.focus()
  await picker.press('Enter')
  await page.locator('.evidence-object-title', { hasText: first[0] }).waitFor()
  await canvas.waitFor()
  assert.equal(await picker.locator('option').count(), 40, '进入对象后保留任务累计节点')
  await page.locator('[data-evidence="back"]').click()
  await page.locator('.evidence-object-title', { hasText: title }).waitFor()
  assert.equal(await picker.inputValue(), `fact:${analysisId}/${first[0]}`)
  assert.equal(await picker.locator('option').count(), 40, '后退恢复复杂图和预览')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ nodes: 39, edges: 55, longLabels, traceBounds: 'passed', sharedIdentity: 'passed', batches: 'passed', tracing: 'passed', viewports: 'passed', navigation: 'passed', readability: 'manual review required', errors }))
} finally {
  await browser.close()
}
