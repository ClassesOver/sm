// Chromium 触控输入模拟，不替代移动真机或软键盘验收。
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
  const map = page.locator('.evidence-graph-map')
  const viewport = await page.locator('.evidence-graph-scroll').boundingBox()
  const x = viewport.x + 25
  const y = viewport.y + 220
  assert.equal(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.className, { x, y }), 'evidence-graph-map')
  const session = await page.context().newCDPSession(page)
  const touch = (id, x, y) => ({ id, x, y })
  const send = (type, touchPoints) => session.send('Input.dispatchTouchEvent', { type, touchPoints })
  const pan = () => map.evaluate(node => node.style.transform)
  const transform = () => map.evaluate(node => {
    const matrix = new DOMMatrix(getComputedStyle(node).transform)
    return { scale: matrix.a, x: matrix.e, y: matrix.f }
  })
  const original = await pan()
  await map.evaluate(node => {
    window.touchTrace = []
    for (const type of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'lostpointercapture']) {
      document.addEventListener(type, event => window.touchTrace.push([type, event.pointerId, event.clientX, event.clientY, event.target.className]), { capture: true })
    }
  })
  await send('touchStart', [touch(1, x, y)])
  await send('touchMove', [touch(1, x + 20, y - 20)])
  await page.waitForFunction(() => document.querySelector('.evidence-graph-map').style.transform.includes('translate(20px, -20px)'))
  const first = await pan()
  assert.notEqual(first, original)
  await send('touchStart', [touch(1, x + 20, y - 20), touch(2, x + 80, y - 20)])
  await send('touchMove', [touch(1, x + 20, y - 20), touch(2, x + 100, y - 30)])
  const pinched = await transform()
  assert.ok(Math.abs(pinched.scale - Math.hypot(80, 10) / 60) < 0.01)
  assert.notEqual(await pan(), first)
  await send('touchEnd', [touch(2, x + 100, y - 30)])
  await send('touchMove', [touch(1, x + 30, y - 30)])
  await page.waitForFunction(({ x, y }) => {
    const matrix = new DOMMatrix(getComputedStyle(document.querySelector('.evidence-graph-map')).transform)
    return Math.abs(matrix.e - x - 10) < 0.01 && Math.abs(matrix.f - y + 10) < 0.01
  }, pinched)
  assert.ok(Math.abs((await transform()).scale - pinched.scale) < 0.01)
  await send('touchEnd', [])
  const events = await page.evaluate(() => window.touchTrace)
  assert.equal(events.filter(event => event[0] === 'pointerdown').length, 2)
  await page.getByRole('button', { name: '重置视图', exact: true }).tap()
  const startingNode = page.locator('.evidence-node').first()
  const nodeBounds = await startingNode.boundingBox()
  const nodeX = nodeBounds.x + 15
  const nodeY = nodeBounds.y + nodeBounds.height / 2
  assert.equal(await page.evaluate(({ x, y }) => Boolean(document.elementFromPoint(x, y)?.closest('.evidence-node')), { x: nodeX, y: nodeY }), true, JSON.stringify(nodeBounds))
  await send('touchStart', [touch(3, nodeX, nodeY)])
  await send('touchStart', [touch(3, nodeX, nodeY), touch(4, nodeX + 60, nodeY)])
  await send('touchMove', [touch(3, nodeX, nodeY), touch(4, nodeX + 90, nodeY)])
  assert.ok(Math.abs((await transform()).scale - 1.5) < 0.01, JSON.stringify({ transform: await transform(), trace: await page.evaluate(() => window.touchTrace) }))
  await send('touchEnd', [])
  assert.equal(await page.locator('.evidence-node.is-selected').count(), 0)
  await startingNode.click()
  assert.equal(await startingNode.getAttribute('aria-pressed'), 'true')
  await page.getByRole('button', { name: '关闭预览', exact: true }).tap()
  await page.getByRole('button', { name: '重置视图', exact: true }).tap()
  await page.getByRole('button', { name: '缩小关系图', exact: true }).tap()
  const node = page.locator('.evidence-node').first()
  await node.tap()
  assert.equal(await node.getAttribute('aria-pressed'), 'true')
  await page.getByRole('button', { name: '关闭预览', exact: true }).tap()
  assert.equal(await page.locator('.evidence-node.is-selected').count(), 0)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  const output = new URL('../../../../output/', import.meta.url)
  await mkdir(output, { recursive: true })
  await page.screenshot({ path: new URL('report-editor-v6-touch-emulation.png', output).pathname })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ touchEmulation: 'passed', firstPan: first, pinchScale: pinched.scale, resumedPan: 'passed', nodeOriginPinch: 'passed', mouseAfterPinch: 'passed', zoomedTap: 'passed' }))
} finally {
  await browser.close()
}
