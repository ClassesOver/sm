import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  let attempts = 0
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/computations/*?*', async route => {
    attempts += 1
    if (attempts === 1) return route.fulfill({ status: 409, json: { detail: { code: 'snapshot_integrity_failed' } } })
    await route.continue()
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.getByRole('button', { name: '展开', exact: true }).click()
  const canvas = page.locator('.evidence-graph-3d canvas')
  await canvas.waitFor()
  const output = new URL('../../../../output/', import.meta.url)
  await mkdir(output, { recursive: true })
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    if (width === 390) await page.getByRole('button', { name: '查看关系图', exact: true }).click()
    await page.waitForFunction(() => {
      const viewport = document.querySelector('.evidence-graph-3d')
      const canvas = viewport?.querySelector('canvas')
      if (!canvas) return false
      const bounds = canvas.getBoundingClientRect()
      return Math.abs(bounds.width - viewport.clientWidth) < 1 && Math.abs(bounds.height - viewport.clientHeight) < 1
    })
    await page.getByRole('button', { name: '适应 3D', exact: true }).click()
    // 等待组件的 500ms 相机动画完成后保存视觉证据。
    await page.waitForTimeout(650)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-3d-${width}.png`, output).pathname })
  }
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  await page.locator('.evidence-node').first().waitFor()
  assert.equal(await canvas.count(), 0)
  await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
  await canvas.waitFor()
  const title = await page.locator('.evidence-object-title').textContent()
  const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
  await picker.selectOption('computation:comp-fixture-001')
  await page.locator('.evidence-preview-summary').waitFor()
  assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  assert.equal(await page.locator('.evidence-preview').evaluate(preview => {
    const bounds = preview.getBoundingClientRect()
    return [...preview.querySelectorAll('button')].every(button => {
      const box = button.getBoundingClientRect()
      return box.left >= bounds.left && box.right <= bounds.right && box.top >= bounds.top && box.bottom <= bounds.bottom
    })
  }), true, '390px 预览操作完整可见')
  await page.locator('.evidence-relations').screenshot({ path: new URL('report-editor-v6-3d-preview-390.png', output).pathname })
  await page.locator('.evidence-branch-load').click()
  await page.getByRole('button', { name: '重试加载关系', exact: true }).waitFor()
  await page.locator('.evidence-branch-load').click()
  await page.getByRole('button', { name: '已加载登记关系', exact: true }).waitFor()
  assert.equal(attempts, 2)
  assert.equal(await picker.locator('option').count(), 5, '四个累计节点与占位选项')
  await page.getByRole('button', { name: '关闭预览', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.evidence-preview-summary'))
  await picker.selectOption('computation:comp-fixture-001')
  await page.getByRole('button', { name: '进入', exact: true }).click()
  await page.locator('.evidence-object-title', { hasText: 'comp-fixture-001' }).waitFor()
  await canvas.waitFor()
  await page.locator('[data-evidence="back"]').click()
  await page.locator('.evidence-object-title', { hasText: title }).waitFor()
  await picker.waitFor()
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ default3d: 'passed', containerSize: 'passed', modeSwitch: 'passed', preview: 'passed', branchRetry: 'passed', navigation: 'passed', errors }))
} finally {
  await browser.close()
}
