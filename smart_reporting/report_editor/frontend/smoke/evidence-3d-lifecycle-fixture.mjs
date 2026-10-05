// 固定前端数据的Chromium WebGL生命周期回放，不替代真实设备或内存性能验收。
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  const contextWarnings = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {
    if (message.text().includes('Too many active WebGL contexts')) contextWarnings.push(message.text())
  })
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext
    const seen = new WeakSet()
    window.graphContexts = []
    HTMLCanvasElement.prototype.getContext = function (...args) {
      const context = original.apply(this, args)
      if (context && ['webgl', 'webgl2', 'experimental-webgl'].includes(args[0]) && !seen.has(context)) {
        seen.add(context)
        // 显式保留引用以验证主动释放；不能据此测量自然GC或宣称存在内存泄漏。
        const record = { canvas: this, context, draws: 0 }
        for (const method of ['drawArrays', 'drawElements']) {
          const draw = context[method].bind(context)
          context[method] = (...args) => { record.draws++; return draw(...args) }
        }
        window.graphContexts.push(record)
      }
      return context
    }
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.getByRole('button', { name: '展开', exact: true }).click()
  const canvas = page.locator('.evidence-graph-3d canvas')
  const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
  const checkContexts = async expected => {
    await page.waitForTimeout(100)
    const status = await page.evaluate(() => window.graphContexts.map(({ canvas, context }) => ({
      connected: canvas.isConnected, lost: context.isContextLost(),
    })))
    assert.equal(status.filter(item => !item.lost).length, expected, '仅可见3D实例保留活跃WebGL上下文')
    assert.equal(status.filter(item => !item.connected && !item.lost).length, 0, '移除的画布和能力探针主动释放上下文')
    return status.length
  }
  await canvas.waitFor()
  await page.getByRole('button', { name: '适应 3D', exact: true }).click()
  const title = await page.locator('.evidence-object-title').textContent()
  await checkContexts(1)
  const draws = () => page.evaluate(() => window.graphContexts.reduce((sum, item) => sum + item.draws, 0))
  const checkPaused = async () => {
    await page.waitForTimeout(150)
    const count = await draws()
    await page.waitForTimeout(150)
    assert.equal(await draws(), count, '隐藏3D画布停止原生绘制调用')
  }
  const checkDrawing = async () => {
    const count = await draws()
    await page.waitForTimeout(150)
    assert.ok(await draws() > count, '重新显示3D画布恢复原生绘制')
  }
  await checkDrawing()
  await page.getByRole('button', { name: '切换到关系列表', exact: true }).click()
  await page.getByRole('region', { name: '关系列表', exact: true }).waitFor()
  await checkPaused()
  await page.getByRole('button', { name: '切换到关系图', exact: true }).click()
  await canvas.waitFor()
  await checkDrawing()
  await page.getByRole('button', { name: '收起', exact: true }).click()
  await checkPaused()
  await page.getByRole('button', { name: '展开', exact: true }).click()
  await canvas.waitFor()
  await checkDrawing()
  for (let cycle = 0; cycle < 6; cycle++) {
    await picker.selectOption('computation:comp-fixture-001')
    await page.locator('.evidence-preview-summary').waitFor()
    await checkContexts(1)
    await page.getByRole('button', { name: '关闭预览', exact: true }).click()
    await checkContexts(1)
    await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
    assert.equal(await canvas.count(), 0)
    await checkContexts(0)
    await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
    await canvas.waitFor()
    await page.getByRole('button', { name: '适应 3D', exact: true }).click()
    await checkContexts(1)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  }
  await picker.selectOption('computation:comp-fixture-001')
  await picker.press('Enter')
  await page.locator('.evidence-object-title', { hasText: '渠道收入汇总' }).waitFor()
  await canvas.waitFor()
  await checkContexts(1)
  await page.locator('[data-evidence="back"]').click()
  await page.locator('.evidence-object-title', { hasText: title }).waitFor()
  await canvas.waitFor()
  await checkContexts(1)
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
  await page.locator('.evidence-tab-close').click()
  await checkContexts(0)
  assert.deepEqual(errors, [])
  assert.deepEqual(contextWarnings, [])
  console.log(JSON.stringify({ cycles: 6, hiddenDraws: 'passed', preview: 'passed', modeSwitch: 'passed', navigation: 'passed', close: 'passed', contexts: await checkContexts(0), errors, contextWarnings }))
} finally {
  await browser.close()
}
