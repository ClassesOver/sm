// 对既有最终截图做离线像素回放与故障注入；不启动服务，不保存或修改工作簿。
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from 'playwright'
import { assertChartAboveCells } from './office-xlsx-chart-layering-smoke.mjs'

const [actual, oldHost, oldComponent, overlayOnly, directory, rawCanvas] = process.argv.slice(2)
assert.ok(actual && oldHost && oldComponent && overlayOnly && directory, '依次指定实际宿主截图、旧宿主RED、组件RED、仅覆盖基线截图、证据目录')
await mkdir(directory, { recursive: true })
const browser = await chromium.launch({ headless: true }), results = []
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 })
async function loadScreenshot(path) {
  await page.setContent('<body style="margin:0"><canvas style="display:block"></canvas></body>')
  await page.evaluate(async source => {
    const image = new Image(); image.src = source; await image.decode()
    const canvas = document.querySelector('canvas'); canvas.width = image.width; canvas.height = image.height
    canvas.getContext('2d').drawImage(image, 0, 0)
  }, 'data:image/png;base64,' + (await readFile(path)).toString('base64'))
}
async function check(name, expected, options = {}) {
  let pixels, error
  try { pixels = await assertChartAboveCells(page, { screenshotPath: join(directory, name + '.png'), ...options }) } catch (caught) { error = String(caught) }
  results.push({ name, expected, accepted: !error, pixels, error })
  assert.equal(!error, expected, JSON.stringify(results.at(-1)))
  return pixels
}
try {
  await loadScreenshot(actual)
  const pixels = await check('actual-host-antialiased-frame', true)
  if (rawCanvas) { await loadScreenshot(rawCanvas); await check('actual-host-transparent-raw-canvas', true) }
  for (const [name, path, options] of [
    ['old-host-missing-first-bar', oldHost, {}],
    ['old-component-missing-bar-and-frame', oldComponent, { forbiddenColors: ['#F97316', '#0000FF', '#D00000'] }],
    ['old-component-two-bars-cell-overlays', overlayOnly, { forbiddenColors: ['#F97316', '#0000FF', '#D00000'] }],
  ]) { await loadScreenshot(path); await check(name, false, options) }
  // 故意擦除六像素：其比例仍高于98%，必须被连续性检查拒绝。
  await loadScreenshot(actual)
  await page.evaluate(frame => { const ctx = document.querySelector('canvas').getContext('2d'); ctx.fillStyle = '#ffffff'; ctx.fillRect(frame.left + 20, frame.top, 6, 1) }, pixels.frame)
  await check('negative-six-pixel-top-edge-gap', false)
  // 用工作表格线色伪造整个图框，不能被灰色alpha容差误认。
  await loadScreenshot(actual)
  await page.evaluate(frame => {
    const ctx = document.querySelector('canvas').getContext('2d'), width = frame.right - frame.left + 1, height = frame.bottom - frame.top + 1
    ctx.fillStyle = '#d6d8db'
    ctx.fillRect(frame.left, frame.top, width, 2); ctx.fillRect(frame.left, frame.bottom - 1, width, 2)
    ctx.fillRect(frame.left, frame.top, 2, height); ctx.fillRect(frame.right - 1, frame.top, 2, height)
  }, pixels.frame)
  await check('negative-gridline-colored-frame', false)
  const evidence = { ok: true, browserVersion: browser.version(), boundary: '仅重放保存截图，故障注入只作用于离线canvas副本', results }
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify(evidence))
} finally { await browser.close() }
