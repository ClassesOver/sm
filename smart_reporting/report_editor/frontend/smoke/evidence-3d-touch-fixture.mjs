// Chromium CDP真实触摸输入模拟；不替代iPhone/Android设备验收。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="more"]').tap()
  await page.locator('[data-action="sources"]').tap()
  await page.locator('.evidence-directory-toggle').tap()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).tap()
  await page.getByRole('button', { name: '查看关系图', exact: true }).tap()
  const canvas = page.locator('.evidence-graph-3d canvas')
  const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
  await canvas.waitFor()
  // 正常选择/关闭使既有坐标缓存固定，隔离力布局运动，避免截图差异冒充相机响应。
  await picker.selectOption('computation:comp-fixture-001')
  await page.getByRole('button', { name: '关闭预览', exact: true }).tap()
  await page.getByRole('button', { name: '适应 3D', exact: true }).tap()
  await page.waitForTimeout(250)
  const title = await page.locator('.evidence-object-title').textContent()
  const scroll = await page.evaluate(() => ({ x: scrollX, y: scrollY }))
  const box = await canvas.boundingBox()
  const session = await page.context().newCDPSession(page)
  const touch = (id, x, y) => ({ id, x, y })
  const send = (type, touchPoints) => session.send('Input.dispatchTouchEvent', { type, touchPoints })
  const findComputation = async () => {
    const bounds = await canvas.boundingBox()
    for (let cy = bounds.height - 6; cy > 0; cy -= 12) {
      for (let cx = bounds.width - 6; cx > 0; cx -= 12) {
        await page.mouse.move(bounds.x + cx, bounds.y + cy)
        await page.waitForTimeout(25)
        if (await page.locator('.evidence-graph-3d').getAttribute('data-hovered') === 'computation:comp-fixture-001') {
          // 原生拾取有节流；不能把上一网格点的悬停回执当成当前坐标命中。
          await page.waitForTimeout(150)
          if (await page.locator('.evidence-graph-3d').getAttribute('data-hovered') === 'computation:comp-fixture-001') {
            return { x: bounds.x + cx, y: bounds.y + cy }
          }
        }
      }
    }
    assert.fail('触控旋转/缩放后仍可命中计算节点')
  }
  const output = new URL('../../../../output/', import.meta.url)
  await mkdir(output, { recursive: true })
  let before = await canvas.screenshot()
  await page.waitForTimeout(150)
  assert.equal(before.equals(await canvas.screenshot()), true, '固定节点及相机在手势前稳定')
  const x = box.x + 15
  const y = box.y + 20
  await send('touchStart', [touch(1, x, y)])
  for (let step = 1; step <= 8; step++) {
    await send('touchMove', [touch(1, x + step * 8, y + step * 5)])
    await page.waitForTimeout(25)
  }
  await send('touchEnd', [])
  await page.waitForTimeout(650)
  const rotated = await canvas.screenshot({ path: new URL('report-editor-v6-3d-touch-rotate.png', output).pathname })
  assert.equal(before.equals(rotated), false, '单指空白拖动改变3D视角')
  before = rotated
  await send('touchStart', [touch(1, x, y), touch(2, x + 60, y)])
  for (let step = 1; step <= 8; step++) {
    await send('touchMove', [touch(1, x, y), touch(2, x + 60 + step * 3, y)])
    await page.waitForTimeout(25)
  }
  await page.waitForTimeout(250)
  const pinched = await canvas.screenshot({ path: new URL('report-editor-v6-3d-touch-pinch.png', output).pathname })
  assert.equal(before.equals(pinched), false, '双指捏合改变3D视图')
  await send('touchEnd', [touch(1, x, y)])
  for (let step = 1; step <= 6; step++) {
    await send('touchMove', [touch(1, x + step * 5, y + step * 5)])
    await page.waitForTimeout(25)
  }
  await send('touchEnd', [])
  await page.waitForTimeout(650)
  assert.equal(pinched.equals(await canvas.screenshot()), false, '双指结束后单指继续旋转')
  assert.equal(await page.locator('.evidence-preview-summary').count(), 0, '手势不误选节点')
  assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  assert.deepEqual(await page.evaluate(() => ({ x: scrollX, y: scrollY })), scroll)
  // 在旋转、捏合后的实际视图中寻找节点，然后清除鼠标悬停再触摸点选。
  const hit = await findComputation()
  const hoveredFrame = await canvas.screenshot()
  await page.waitForTimeout(150)
  assert.equal(hoveredFrame.equals(await canvas.screenshot()), true, '静止悬停时小图标签不反复跳位')
  const tapBounds = await canvas.boundingBox()
  await page.mouse.move(tapBounds.x + 2, tapBounds.y + 2)
  await page.waitForFunction(() => !document.querySelector('.evidence-graph-3d').dataset.hovered)
  // 清除扫描时的悬停回执后，实际触摸输入仍须命中节点。
  await page.touchscreen.tap(hit.x, hit.y)
  await page.locator('.evidence-preview-summary').waitFor()
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  await page.getByRole('button', { name: '进入', exact: true }).tap()
  await page.locator('.evidence-object-title', { hasText: '渠道收入汇总' }).waitFor()
  await page.locator('[data-evidence="back"]').tap()
  await page.locator('.evidence-object-title', { hasText: title }).waitFor()
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.locator('.evidence-relations').screenshot({ path: new URL('report-editor-v6-3d-touch-preview.png', output).pathname })
  await page.getByRole('button', { name: '关闭预览', exact: true }).tap()
  const recoveryBox = await canvas.boundingBox()
  const recoveryX = recoveryBox.x + 15
  const recoveryY = recoveryBox.y + 20
  await send('touchStart', [touch(1, recoveryX, recoveryY), touch(2, recoveryX + 60, recoveryY)])
  for (let step = 1; step <= 8; step++) {
    await send('touchMove', [touch(1, recoveryX, recoveryY), touch(2, recoveryX + 60 + step * 8, recoveryY)])
    await page.waitForTimeout(25)
  }
  await send('touchEnd', [])
  await page.waitForTimeout(650)
  const overzoomed = await canvas.screenshot()
  await page.getByRole('button', { name: '适应 3D', exact: true }).tap()
  await page.waitForTimeout(250)
  const recovered = await canvas.screenshot({ path: new URL('report-editor-v6-3d-touch-recovered.png', output).pathname })
  assert.equal(overzoomed.equals(recovered), false, '放大后可通过适应恢复视野')
  assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  assert.equal(await page.locator('.evidence-preview-summary').count(), 0)
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  // 相同重置/适应视角前后逐像素比较，区分相机运动与误拖动节点。
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const normalizeCamera = async () => {
    await page.getByRole('button', { name: '重置视图', exact: true }).tap()
    await page.getByRole('button', { name: '适应 3D', exact: true }).tap()
    await page.mouse.move(recoveryX, recoveryY)
    await page.waitForTimeout(250)
    return canvas.screenshot()
  }
  const nodeBefore = await normalizeCamera()
  await canvas.screenshot({ path: new URL('report-editor-v6-3d-touch-node-before.png', output).pathname })
  const nodeHit = await findComputation()
  await page.mouse.move(recoveryX, recoveryY)
  await page.waitForTimeout(60)
  await send('touchStart', [touch(1, nodeHit.x, nodeHit.y)])
  await send('touchStart', [touch(1, nodeHit.x, nodeHit.y), touch(2, nodeHit.x - 50, nodeHit.y)])
  for (let step = 1; step <= 8; step++) {
    await send('touchMove', [touch(1, nodeHit.x, nodeHit.y), touch(2, nodeHit.x - 50 - step * 3, nodeHit.y)])
    await page.waitForTimeout(25)
  }
  const nodePinched = await canvas.screenshot({ path: new URL('report-editor-v6-3d-touch-node-pinch.png', output).pathname })
  assert.equal(nodeBefore.equals(nodePinched), false, '节点起点双指操作改变视图')
  await send('touchEnd', [touch(1, nodeHit.x, nodeHit.y)])
  for (let step = 1; step <= 4; step++) {
    await send('touchMove', [touch(1, nodeHit.x - step * 3, nodeHit.y + step * 3)])
    await page.waitForTimeout(25)
  }
  await send('touchEnd', [])
  await page.mouse.move(recoveryX, recoveryY)
  await page.waitForTimeout(400)
  assert.equal(nodePinched.equals(await canvas.screenshot()), false, '节点起点双指结束后单指继续旋转')
  assert.equal(await page.locator('.evidence-preview-summary').count(), 0, '节点起点手势不误预览')
  const nodeAfter = await normalizeCamera()
  await canvas.screenshot({ path: new URL('report-editor-v6-3d-touch-node-restored.png', output).pathname })
  assert.equal(nodeBefore.equals(nodeAfter), true, '节点起点捏合仅改变相机，不移动节点')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ touchRotate: 'passed', touchPinch: 'passed', resumedRotate: 'passed', touchTap: 'passed', navigation: 'passed', fitRecovery: 'passed', nodePinch: 'passed', errors }))
} finally {
  await browser.close()
}
