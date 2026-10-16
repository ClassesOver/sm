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
  // 首屏会把图整体缩小到可见，固定偏移可能落在图外；在图内找一个不压节点的空白点作为拖动起点。
  const { x, y } = await page.evaluate(() => {
    const scroll = document.querySelector('.evidence-graph-scroll').getBoundingClientRect()
    const box = document.querySelector('.evidence-graph-map').getBoundingClientRect()
    const left = Math.max(box.left, scroll.left), top = Math.max(box.top, scroll.top)
    const right = Math.min(box.right, scroll.right), bottom = Math.min(box.bottom, scroll.bottom)
    const nodes = [...document.querySelectorAll('.evidence-graph-map .evidence-node')].map(node => node.getBoundingClientRect())
    const clear = (px, py) => nodes.every(rect => px < rect.left - 40 || px > rect.right + 40 || py < rect.top - 40 || py > rect.bottom + 40)
    for (let py = top + 30; py < bottom - 30; py += 10) {
      for (let px = left + 30; px < right - 30; px += 10) {
        if (clear(px, py) && document.elementFromPoint(px, py)?.className === 'evidence-graph-map') return { x: Math.round(px), y: Math.round(py) }
      }
    }
    return { x: left + 25, y: top + 25 }
  })
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
  const startTransform = await transform()
  await map.evaluate(node => {
    window.touchTrace = []
    for (const type of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'lostpointercapture']) {
      document.addEventListener(type, event => window.touchTrace.push([type, event.pointerId, event.clientX, event.clientY, event.target.className]), { capture: true })
    }
  })
  await send('touchStart', [touch(1, x, y)])
  await send('touchMove', [touch(1, x + 20, y - 20)])
  // 首屏适应后平移不一定从 0 开始：按相对位移判断单指拖动 (+20, -20)。
  await page.waitForFunction(start => {
    const matrix = new DOMMatrix(getComputedStyle(document.querySelector('.evidence-graph-map')).transform)
    return Math.abs(matrix.e - start.x - 20) < 0.5 && Math.abs(matrix.f - start.y + 20) < 0.5
  }, startTransform)
  const first = await pan()
  assert.notEqual(first, original)
  await send('touchStart', [touch(1, x + 20, y - 20), touch(2, x + 80, y - 20)])
  await send('touchMove', [touch(1, x + 20, y - 20), touch(2, x + 100, y - 30)])
  const pinched = await transform()
  // 双指缩放按指距比例作用于当前缩放（首屏适应后不一定为 1）。
  assert.ok(Math.abs(pinched.scale - startTransform.scale * Math.hypot(80, 10) / 60) < 0.01)
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
