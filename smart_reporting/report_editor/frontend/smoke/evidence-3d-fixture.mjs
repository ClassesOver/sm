import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  await page.addInitScript(() => {
    window.graphLabelText = []
    const fillText = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function (...args) {
      window.graphLabelText.push(args[0])
      return fillText.apply(this, args)
    }
  })
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
  assert.deepEqual((await page.locator('.evidence-3d-kind-key').evaluateAll(nodes => nodes.map(node => node.dataset.kind))).sort(), ['computation', 'fact', 'subject'], '图例只列已加载类型')
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
  await page.getByRole('button', { name: '适应 3D', exact: true }).click()
  await page.waitForTimeout(650)
  await canvas.screenshot({ path: new URL('report-editor-v6-3d-camera-before.png', output).pathname })
  const title = await page.locator('.evidence-object-title').textContent()
  const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
  await picker.focus()
  await picker.selectOption('computation:comp-fixture-001')
  await page.locator('.evidence-preview-summary').waitFor()
  await page.waitForFunction(() => window.graphLabelText.some(text => text.includes('已加载 1 条关系')))
  assert.equal(await page.evaluate(() => window.graphLabelText.some(text => text.includes('已加载 1 条关系'))), true, '预览节点名称画布保留已加载关系信息')
  assert.equal(await picker.evaluate(node => node === document.activeElement), true, '选择后恢复节点选择器焦点')
  await canvas.screenshot({ path: new URL('report-editor-v6-3d-camera-preview.png', output).pathname })
  assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  const tracePicker = page.getByRole('combobox', { name: '追踪预览关系端点' })
  assert.equal(await tracePicker.isEnabled(), true)
  await tracePicker.selectOption('subject:sub-fixture-001')
  await page.locator('.evidence-3d-trace-status', { hasText: '追踪 1 条登记关系' }).waitFor()
  await page.getByRole('button', { name: '适应追踪关系', exact: true }).click()
  await page.waitForTimeout(650)
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
  assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  assert.equal(await canvas.evaluate(node => node.getBoundingClientRect().height > 100), true)
  assert.equal(await tracePicker.evaluate(node => {
    const box = node.getBoundingClientRect()
    return box.left >= 0 && box.right <= innerWidth
  }), true, '390px 追踪选择器不越界')
  await page.locator('.evidence-relations').screenshot({ path: new URL('report-editor-v6-3d-trace-390.png', output).pathname })
  await tracePicker.selectOption('')
  await page.locator('.evidence-3d-trace-status', { hasText: '预览 1 条登记关系' }).waitFor()
  await page.getByRole('button', { name: '适应 3D', exact: true }).waitFor()
  for (const name of ['定位当前对象', '放大关系图', '缩小关系图', '重置视图']) {
    await page.getByRole('button', { name, exact: true }).click()
    await page.waitForTimeout(550)
    if (name === '定位当前对象') {
      await canvas.screenshot({ path: new URL('report-editor-v6-3d-locate.png', output).pathname })
    }
    assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  }
  await page.waitForTimeout(650)
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
  assert.equal(await page.locator('.evidence-3d-kind-key[data-kind="dataset"]').count(), 1, '追加快照后同步类型图例')
  assert.equal(await tracePicker.locator('option').count(), 5, '计算的三个已加载关系端点、全部及直接关系选项')
  assert.equal(await tracePicker.locator('option[value="preview-relations"]').count(), 1)
  await tracePicker.selectOption('subject:sub-fixture-001')
  await page.locator('.evidence-3d-trace-status', { hasText: '追踪 1 条登记关系' }).waitFor()
  await page.getByRole('button', { name: '适应追踪关系', exact: true }).click()
  await page.waitForTimeout(650)
  await canvas.screenshot({ path: new URL('report-editor-v6-3d-trace-branches.png', output).pathname })
  await tracePicker.selectOption('')
  await page.locator('.evidence-3d-trace-status', { hasText: '预览 3 条登记关系' }).waitFor()
  await picker.focus()
  await picker.press('Escape')
  await page.waitForFunction(() => !document.querySelector('.evidence-preview-summary'))
  await picker.waitFor()
  assert.equal(await tracePicker.isEnabled(), false, '无预览时不允许固定端点')
  assert.equal(await picker.evaluate(node => node === document.activeElement), true)
  await picker.selectOption('computation:comp-fixture-001')
  await page.getByRole('button', { name: '关闭预览', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.evidence-preview-summary'))
  await picker.waitFor()
  assert.equal(await picker.evaluate(node => node === document.activeElement), true, '关闭预览后恢复节点选择器焦点')
  await picker.selectOption('computation:comp-fixture-001')
  await picker.focus()
  await picker.press('Enter')
  await page.locator('.evidence-object-title', { hasText: 'comp-fixture-001' }).waitFor()
  await canvas.waitFor()
  await page.locator('[data-evidence="back"]').click()
  await page.locator('.evidence-object-title', { hasText: title }).waitFor()
  await picker.waitFor()
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
  await page.getByRole('button', { name: '关闭预览', exact: true }).click()
  await page.getByRole('button', { name: '适应 3D', exact: true }).click()
  await page.waitForTimeout(650)
  // 通过真实组件悬停命中寻找节点，不调用回调或直接操作组件实例。
  const findCanvasNode = async id => {
    const box = await canvas.boundingBox()
    for (let y = 6; y < box.height; y += 12) {
      for (let x = 6; x < box.width; x += 12) {
        await page.mouse.move(box.x + x, box.y + y)
        await page.waitForTimeout(25)
        if (await page.locator('.evidence-graph-3d').getAttribute('data-hovered') === id) {
          await page.waitForTimeout(150)
          if (await page.locator('.evidence-graph-3d').getAttribute('data-hovered') === id) {
            return { x: box.x + x, y: box.y + y }
          }
        }
      }
    }
    assert.fail(`真实画布未命中 ${id}`)
  }
  const box = await canvas.boundingBox()
  await page.mouse.move(box.x + 10, box.y + 10)
  const beforeRotate = await canvas.screenshot()
  await page.mouse.down()
  await page.mouse.move(box.x + 90, box.y + 65, { steps: 12 })
  await page.mouse.up()
  await page.waitForTimeout(650)
  const afterRotate = await canvas.screenshot({ path: new URL('report-editor-v6-3d-rotated.png', output).pathname })
  assert.equal(beforeRotate.equals(afterRotate), false, '空白拖动改变3D视角')
  await page.mouse.wheel(0, -240)
  await page.waitForTimeout(650)
  const afterWheel = await canvas.screenshot({ path: new URL('report-editor-v6-3d-wheel.png', output).pathname })
  assert.equal(afterRotate.equals(afterWheel), false, '滚轮缩放改变3D视图')
  assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  assert.equal(await page.locator('.evidence-preview-summary').count(), 0)
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  let hit = await findCanvasNode('computation:comp-fixture-001')
  await page.locator('.evidence-3d-trace-status', { hasText: '追踪 3 条登记关系' }).waitFor()
  await canvas.screenshot({ path: new URL('report-editor-v6-3d-hover-label.png', output).pathname })
  await page.mouse.click(hit.x, hit.y)
  await page.locator('.evidence-preview-summary').waitFor()
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001', '画布单击预览')
  assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  // 等待首次单击窗口结束，再独立验证两次相距100ms的画布点击。
  await page.waitForTimeout(400)
  hit = await findCanvasNode('computation:comp-fixture-001')
  await page.mouse.click(hit.x, hit.y, { clickCount: 2, delay: 100 })
  await page.locator('.evidence-object-title', { hasText: 'comp-fixture-001' }).waitFor()
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), true, '画布双击进入')
  await page.locator('[data-evidence="back"]').click()
  await page.locator('.evidence-object-title', { hasText: title }).waitFor()
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
  // 实际画布中键必须创建后台任务；先验证中键，防止后续Ctrl创建任务掩盖缺口。
  hit = await findCanvasNode('computation:comp-fixture-001')
  const taskCount = await page.locator('.evidence-tab-name').count()
  const backgroundBounds = await canvas.boundingBox()
  const clearBackgroundHover = async () => {
    await page.mouse.move(backgroundBounds.x + 5, backgroundBounds.y + 5)
    await page.waitForTimeout(100)
  }
  await clearBackgroundHover()
  const backgroundCanvas = await canvas.screenshot()
  const modifiedClick = async (point, options) => {
    const { modifiers = [], ...mouseOptions } = options
    for (const key of modifiers) await page.keyboard.down(key)
    try { await page.mouse.click(point.x, point.y, mouseOptions) }
    finally { for (const key of modifiers.reverse()) await page.keyboard.up(key) }
  }
  for (const options of [{ button: 'middle' }, { modifiers: ['Control'] }, { modifiers: ['Meta'] }, { button: 'right' }]) {
    hit = await findCanvasNode('computation:comp-fixture-001')
    await modifiedClick(hit, options)
    await page.waitForFunction(count => document.querySelectorAll('.evidence-tab-name').length === count, taskCount + 1)
    await page.waitForTimeout(400)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title, '后台打开不抢当前对象')
    assert.equal(await picker.inputValue(), 'computation:comp-fixture-001', '后台打开不改预览')
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false, '后台打开不改当前历史')
    await clearBackgroundHover()
    assert.equal(backgroundCanvas.equals(await canvas.screenshot()), true, '后台打开不改相机和节点现场')
  }
  hit = await findCanvasNode('computation:comp-fixture-001')
  await modifiedClick(hit, { modifiers: ['Control', 'Shift'] })
  await page.locator('.evidence-object-title', { hasText: 'comp-fixture-001' }).waitFor()
  assert.equal(await page.locator('.evidence-tab-name').count(), taskCount + 1, '前台打开复用已有任务')
  await page.locator('.evidence-tab', { hasText: '正文引用' }).click()
  await page.locator('.evidence-object-title', { hasText: title }).waitFor()
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
  for (const reducedMotion of ['reduce', 'no-preference']) {
    await page.emulateMedia({ reducedMotion })
    assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), reducedMotion === 'reduce')
    for (const name of ['定位当前对象', '放大关系图', '缩小关系图', '重置视图', '适应 3D']) {
      await page.getByRole('button', { name, exact: true }).click()
      await page.waitForTimeout(reducedMotion === 'reduce' ? 40 : 240)
      const settled = await canvas.screenshot()
      await page.waitForTimeout(300)
      assert.equal(settled.equals(await canvas.screenshot()), true, `${reducedMotion} ${name} 无后续相机动画`)
      assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
      assert.equal(await page.locator('.evidence-object-title').textContent(), title)
      assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
    }
  }
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ default3d: 'passed', containerSize: 'passed', modeSwitch: 'passed', preview: 'passed', relationTrace: 'passed', branchRetry: 'passed', navigation: 'passed', canvasClick: 'passed', canvasDoubleClick: 'passed', backgroundMouse: 'passed', foregroundReuse: 'passed', rotateAndWheel: 'passed', motionPreference: 'passed', errors }))
} finally {
  await browser.close()
}
