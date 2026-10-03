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
  // 在旋转、捏合后的实际视图中寻找球体，然后清除鼠标悬停再触摸点选。
  let hit = null
  for (let cy = box.height - 6; cy > 0 && !hit; cy -= 12) {
    for (let cx = box.width - 6; cx > 0; cx -= 12) {
      await page.mouse.move(box.x + cx, box.y + cy)
      await page.waitForTimeout(25)
      if (await page.locator('.evidence-graph-3d').getAttribute('data-hovered') === 'computation:comp-fixture-001') {
        hit = { x: box.x + cx, y: box.y + cy }
        break
      }
    }
  }
  assert.ok(hit, '触控旋转/缩放后仍可命中计算节点')
  await page.mouse.move(x, y)
  await page.waitForTimeout(50)
  await page.touchscreen.tap(hit.x, hit.y)
  await page.locator('.evidence-preview-summary').waitFor()
  assert.equal(await picker.inputValue(), 'computation:comp-fixture-001')
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  await page.getByRole('button', { name: '进入', exact: true }).tap()
  await page.locator('.evidence-object-title', { hasText: 'comp-fixture-001' }).waitFor()
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
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ touchRotate: 'passed', touchPinch: 'passed', resumedRotate: 'passed', touchTap: 'passed', navigation: 'passed', fitRecovery: 'passed', errors }))
} finally {
  await browser.close()
}
