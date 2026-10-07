// 验证后台排布期间仍能切换模式，以及关闭画布会终止未完成任务。
import assert from 'node:assert/strict'
import { chromium, firefox } from 'playwright'
const failure = process.env.REPORT_EDITOR_WORKER_FAILURE ?? ''
assert.ok(['', '1', 'constructor'].includes(failure))
const engine = process.env.REPORT_EDITOR_BROWSER ?? 'chromium'
assert.ok(['chromium', 'firefox'].includes(engine))
const browser = await ({ chromium, firefox })[engine].launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(rejectConstructor => {
    window.workerAudit = { created: 0, terminated: 0 }
    const NativeWorker = window.Worker
    window.Worker = class extends NativeWorker {
      constructor(...args) {
        if (rejectConstructor) throw new DOMException('fixture worker denied', 'SecurityError')
        super(...args)
        window.workerAudit.created++
      }
      terminate() { window.workerAudit.terminated++; return super.terminate() }
    }
  }, failure === 'constructor')
  await page.route('**/assets/evidence-label-layout.worker-*.js', async route => {
    await new Promise(resolve => setTimeout(resolve, 500))
    if (failure === '1') return route.fulfill({ contentType: 'text/javascript', body: 'throw new Error("fixture worker failure")' })
    const response = await route.fetch()
    await route.fulfill({ response })
  })
  await page.route('**/api/facts/**', route => {
    const factId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1))
    return route.fulfill({ json: {
      analysisId: 'analysis-fixture-001', factId, factKind: 'metric', displayValue: 100,
      entry: { unit: '元' }, warnings: [], inputFactRefs: factId === 'fact-fixture-001'
        ? Array.from({ length: 39 }, (_, index) => ({ analysisId: 'analysis-fixture-001', factId: `worker-input-${index}` })) : [],
    } })
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '查看关系图', exact: true }).click()
  const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
  const count = await picker.locator('option').count()
  assert.ok(count >= 40)
  await page.getByRole('button', { name: '显示全部节点名称', exact: true }).click()
  if (failure !== 'constructor') {
    await page.locator('.evidence-label-layout-status').waitFor({ state: 'visible' })
    assert.equal(await page.locator('.evidence-graph-3d').getAttribute('aria-busy'), 'true')
  } else {
    await page.waitForFunction(() => document.querySelector('.evidence-graph-3d')?.dataset.labelLayout === 'ready')
  }
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  const cancelled = await page.evaluate(() => window.workerAudit)
  assert.equal(cancelled.created, failure === 'constructor' ? 0 : 1)
  assert.equal(cancelled.terminated, failure === 'constructor' ? 0 : 1, '关闭画布终止未完成任务')
  await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.evidence-graph-3d')?.dataset.labelLayout === 'ready', null, { timeout: 5000 })
  assert.equal(await picker.locator('option').count(), count, '后台排布保留所有节点身份')
  assert.equal(await page.locator('.evidence-label-layout-status').isVisible(), false)
  assert.equal(await page.locator('.evidence-graph-3d').getAttribute('aria-busy'), null)
  const ready = await page.evaluate(() => window.workerAudit)
  assert.equal(ready.created - ready.terminated, failure ? 0 : 1, '故障线程终止，正常画布最多一个后台线程')
  if (failure) {
    const canvas = page.locator('.evidence-graph-3d canvas')
    const before = await canvas.screenshot()
    await page.getByRole('button', { name: '放大关系图', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('.evidence-graph-3d')?.dataset.labelLayout === 'ready')
    assert.equal(before.equals(await canvas.screenshot()), false, '故障恢复后仍可操作相机')
    assert.deepEqual(await page.evaluate(() => window.workerAudit), ready, '故障画布不重复创建后台线程')
  }
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ engine, nodes: count - 1, failure, cancellation: 'passed', modeSwitchWhilePending: 'passed', busyStatus: 'passed', errors }))
} finally { await browser.close() }
