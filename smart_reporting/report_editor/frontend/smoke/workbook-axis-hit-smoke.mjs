import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const out = process.env.WORKBOOK_AXIS_HIT_DIRECTORY ?? '/tmp/workbook-axis-hit-browser-20261113'
const staticRoot = process.env.PDF_SMOKE_STATIC_DIRECTORY ?? join(frontend, '../static')
const port = Number(process.env.WORKBOOK_AXIS_HIT_PORT ?? 4381)
const origin = `http://127.0.0.1:${port}`
const python = join(repo, '.venv/bin/python')
await mkdir(out, { recursive: false })
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestSha256 = sha(await readFile(join(staticRoot, '.vite/manifest.json')))
const fixture = spawnSync(python, [join(frontend, 'smoke/workbook-axis-hit-fixture.py'), join(out, 'fixture.xlsx')], { cwd: repo, encoding: 'utf8' })
assert.equal(fixture.status, 0, fixture.stderr)

const server = spawn(python, [join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', out, '--port', String(port), '--source', join(out, 'fixture.xlsx')], {
  cwd: repo,
  env: { ...process.env, PYTHONPATH: repo, PDF_SMOKE_STATIC_DIRECTORY: staticRoot },
  stdio: 'pipe',
})
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', data => { serverLog += data })
server.stderr.on('data', data => { serverLog += data })
const errors = [], consoleErrors = []
const httpErrors = [], assetHashes = {}, assetChecks = []
try {
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })).ok) break } catch {}
    assert(attempt < 240, serverLog)
    await delay(250)
  }
  const info = JSON.parse(await readFile(join(out, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/snap/bin/chromium' })
  page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
  await page.addInitScript(() => {
    window.__axisText = []; window.__axisEvents = []
    for (const type of ['pointerdown', 'pointerup', 'click', 'dblclick']) document.addEventListener(type, event => {
      window.__axisEvents.push({ type, x: event.clientX, y: event.clientY, target: event.target?.tagName, selected: document.querySelector('.workbook-grid')?.dataset.selectedChart, pane: document.querySelector('.workbook-chart-format-pane:not([hidden]) select[aria-label="图表元素"]')?.value })
    }, true)
    const original = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function (text, x, y) {
      const canvas = this.canvas.getBoundingClientRect().width > 0 ? this.canvas : [...document.querySelectorAll('.workbook-grid canvas')].find(item => item.getBoundingClientRect().width > 0)
      if (canvas) {
        const rect = canvas.getBoundingClientRect(), transform = this.getTransform()
        window.__axisText.push({ text: String(text), font: this.font, x: rect.left + (transform.a * x + transform.e) * rect.width / canvas.width, y: rect.top + (transform.d * y + transform.f) * rect.height / canvas.height })
        window.__axisText = window.__axisText.slice(-1000)
      }
      return original.call(this, text, x, y)
    }
  })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(?:js|css)$/.test(path)) assetChecks.push((async () => {
      const bytes = await response.body()
      const disk = await readFile(join(staticRoot, decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length))))
      assert.equal(response.status(), 200, path)
      assert.equal(sha(bytes), sha(disk), `served asset differs from isolated build: ${path}`)
      assetHashes[path] = sha(bytes)
    })())
  })
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 90000 })
  const command = async id => { await page.locator('[data-ribbon-tab="Chart Design"]').click(); await page.locator(`[data-ribbon-command="${id}"]`).click() }
  const pane = () => page.locator('.workbook-chart-format-pane:not([hidden])')
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  stage = 'open'
  await page.goto(origin + info.openPath)
  await ready()
  await page.waitForFunction(() => [...(window.__sheetsWebCharts?.store.values() ?? [])].flat().length === 2)
  const initialDraft = await draft()
  const selectChart = async (title) => {
    await command('chart-descriptions')
    const path = await page.evaluate(title => [...window.__sheetsWebCharts.store.values()].flat().find(chart => chart.title === title)?.chartPath, title)
    assert(path, `chart title unavailable: ${title}`)
    await page.locator(`[data-select-chart="${path}"]`).click()
    await command('chart-format-pane')
    await pane().waitFor()
    assert.equal(await pane().getByLabel('图表元素', { exact: true }).inputValue(), 'chart')
  }
  const clickAndAssert = async (target, point) => {
    assert(point && point.x >= 0 && point.x < 1600 && point.y >= 0 && point.y < 1100, `${target} click coordinate is visible: ${JSON.stringify(point)}`)
    await page.mouse.click(point.x, point.y)
    await page.waitForFunction(target => document.querySelector('.workbook-chart-format-pane:not([hidden]) select[aria-label="图表元素"]')?.value === target, target)
    assert.equal(await pane().getByLabel('图表元素', { exact: true }).inputValue(), target)
    assert.deepEqual(await draft(), initialDraft, `${target} selection must not create a draft`)
    return point
  }

  stage = 'scatter-axis-clicks'
  await selectChart('Axis scatter')
  await page.waitForFunction(() => window.__axisText.some(item => item.font === '9px system-ui'))
  const scatterTicks = await page.evaluate(() => window.__axisText.filter(item => item.font === '9px system-ui' && item.x > 300 && item.x < 1250 && item.y > 250 && item.y < 600))
  assert(scatterTicks.length >= 8, `visible scatter ticks: ${JSON.stringify(scatterTicks)}`)
  const scatterXAxis = await clickAndAssert('category-axis', { x: 800, y: 570 })
  const scatterYAxis = await clickAndAssert('value-axis', { x: 400, y: 420 })
  const scatterSeries = await clickAndAssert('series:0', { x: 600, y: 500 })
  const scatterPoint = await clickAndAssert('point:0:0', { x: 600, y: 500 })
  await page.screenshot({ path: join(out, 'scatter-axis-selection.png'), fullPage: true })
  await pane().getByRole('button', { name: '关闭图表格式', exact: true }).click({ force: true })

  stage = 'radar-axis-and-value-ring'
  await selectChart('Axis radar')
  await page.waitForFunction(() => window.__axisText.some(item => item.font === '10px system-ui' && /^Q[1-4]$/.test(item.text)))
  const radarLabels = await page.evaluate(() => window.__axisText.filter(item => item.font === '10px system-ui' && /^Q[1-4]$/.test(item.text)))
  assert(radarLabels.length >= 4, `visible radar categories: ${JSON.stringify(radarLabels)}`)
  const top = radarLabels.reduce((a, b) => a.y < b.y ? a : b)
  const bottom = radarLabels.reduce((a, b) => a.y > b.y ? a : b)
  const center = { x: radarLabels.reduce((sum, item) => sum + item.x, 0) / radarLabels.length, y: (top.y + bottom.y) / 2 }
  const radarCategory = await clickAndAssert('category-axis', { x: 794, y: 629 })
  const valueRing = await clickAndAssert('chart', { x: 887, y: 769 })
  await page.screenshot({ path: join(out, 'radar-axis-selection.png'), fullPage: true })

  assert.deepEqual(errors, [])
  assert.deepEqual(consoleErrors, [])
  await Promise.all(assetChecks)
  assert(assetChecks.length > 0)
  assert.deepEqual(httpErrors, [])
  assert.equal(sha(await readFile(join(staticRoot, '.vite/manifest.json'))), manifestSha256)
  assert.deepEqual(await draft(), initialDraft)
  const state = await (await page.request.get(origin + '/__smoke__/state')).json()
  assert.equal(state.plannerCalls, 0)
  assert.equal(state.savedRevisions, 0)
  const evidence = { ok: true, browserVersion: browser.version(), scope: 'Native XLSX import and real Chromium mouse clicks on visible chart axes, scatter point-series narrowing and radar category/value ring', targets: { scatterXAxis, scatterYAxis, scatterSeries, scatterPoint, radarCategory, valueRing }, initialDraft, finalDraft: await draft(), state, manifestSha256, assetHashes, errors, consoleErrors, httpErrors }
  await writeFile(join(out, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ok: true, directory: out, targets: evidence.targets, browserVersion: evidence.browserVersion }))
} catch (error) {
  await writeFile(join(out, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, errors, consoleErrors, charts: await page?.evaluate(() => [...window.__sheetsWebCharts.store.values()].flat().map(chart => ({ title: chart.title, path: chart.chartPath, kind: chart.kind }))).catch(() => null), axisText: await page?.evaluate(() => window.__axisText).catch(() => null), axisEvents: await page?.evaluate(() => window.__axisEvents).catch(() => null), selected: await page?.locator('.workbook-chart-format-pane:not([hidden]) select[aria-label="图表元素"]').inputValue().catch(() => null) }, null, 2))
  await page?.screenshot({ path: join(out, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  await writeFile(join(out, 'server.log'), serverLog)
}
