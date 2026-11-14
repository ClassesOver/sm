import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const out = process.env.WORKBOOK_LINE_AREA_HIT_DIRECTORY ?? '/tmp/workbook-line-area-hit-20261113'
const staticRoot = process.env.PDF_SMOKE_STATIC_DIRECTORY ?? '/tmp/workbook-axis-hit-static-source-scale-20261113'
const port = Number(process.env.WORKBOOK_LINE_AREA_HIT_PORT ?? 4382), origin = `http://127.0.0.1:${port}`
const python = join(repo, '.venv/bin/python'), sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(out, { recursive: false })
const fixture = spawnSync(python, [join(frontend, 'smoke/workbook-line-area-hit-fixture.py'), join(out, 'fixture.xlsx')], { cwd: repo, encoding: 'utf8' })
assert.equal(fixture.status, 0, fixture.stderr)
const manifestSha256 = sha(await readFile(join(staticRoot, '.vite/manifest.json')))
const server = spawn(python, [join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', out, '--port', String(port), '--source', join(out, 'fixture.xlsx')], {
  cwd: repo, env: { ...process.env, PYTHONPATH: repo, PDF_SMOKE_STATIC_DIRECTORY: staticRoot }, stdio: 'pipe',
})
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', data => { serverLog += data }); server.stderr.on('data', data => { serverLog += data })
const errors = [], consoleErrors = [], httpErrors = [], assetHashes = {}, assetChecks = []
try {
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })).ok) break } catch {}
    assert(attempt < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(out, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/snap/bin/chromium' })
  page = await browser.newPage({ viewport: { width: 1600, height: 1100 } }); page.setDefaultTimeout(20000)
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(?:js|css)$/.test(path)) assetChecks.push((async () => {
      const bytes = await response.body(), disk = await readFile(join(staticRoot, decodeURIComponent(path.slice('/reports/v1/editor/assets/'.length))))
      assert.equal(response.status(), 200, path); assert.equal(sha(bytes), sha(disk), `served asset differs: ${path}`); assetHashes[path] = sha(bytes)
    })())
  })
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 90000 })
  const command = async id => { await page.locator('[data-ribbon-tab="Chart Design"]').click(); await page.locator(`[data-ribbon-command="${id}"]`).click() }
  const pane = () => page.locator('.workbook-chart-format-pane:not([hidden])')
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  stage = 'open'; await page.goto(origin + info.openPath); await ready()
  await page.waitForFunction(() => [...(window.__sheetsWebCharts?.store.values() ?? [])].flat().length === 2)
  const initialDraft = await draft()
  async function selectChart(title) {
    await command('chart-descriptions')
    const path = await page.evaluate(title => [...window.__sheetsWebCharts.store.values()].flat().find(chart => chart.title === title)?.chartPath, title)
    assert(path, `missing chart ${title}`); await page.locator(`[data-select-chart="${path}"]`).click()
    await command('chart-format-pane'); await pane().waitFor()
  }
  async function clickTarget(target, point) {
    assert(point.x >= 0 && point.x < 1600 && point.y >= 0 && point.y < 1100, `offscreen ${target}: ${JSON.stringify(point)}`)
    await page.mouse.click(point.x, point.y)
    await page.waitForFunction(target => document.querySelector('.workbook-chart-format-pane:not([hidden]) select[aria-label="图表元素"]')?.value === target, target)
    assert.deepEqual(await draft(), initialDraft)
    return point
  }

  stage = 'line-series-segment'
  await selectChart('Line hit')
  const lineSegment = await clickTarget('series:0', { x: 542, y: 436 })
  await page.screenshot({ path: join(out, 'line-segment-selected.png'), fullPage: true })
  await pane().getByRole('button', { name: '关闭图表格式', exact: true }).click({ force: true })

  stage = 'line-marker-narrowing'
  await selectChart('Line hit')
  await clickTarget('category-axis', { x: 800, y: 553 })
  const lineMarkerSeries = await clickTarget('series:0', { x: 423, y: 489 })
  const lineMarkerPoint = await clickTarget('point:0:0', { x: 423, y: 489 })
  await page.screenshot({ path: join(out, 'line-marker-point-selected.png'), fullPage: true })
  await pane().getByRole('button', { name: '关闭图表格式', exact: true }).click({ force: true })

  stage = 'area-fill'
  await selectChart('Area hit')
  const areaFill = await clickTarget('series:0', { x: 700, y: 800 })
  await page.screenshot({ path: join(out, 'area-fill-selected.png'), fullPage: true })
  assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, [])
  await Promise.all(assetChecks); assert(assetChecks.length > 0); assert.deepEqual(httpErrors, [])
  assert.equal(sha(await readFile(join(staticRoot, '.vite/manifest.json'))), manifestSha256)
  assert.deepEqual(await draft(), initialDraft)
  const state = await (await page.request.get(origin + '/__smoke__/state')).json()
  assert.equal(state.plannerCalls, 0); assert.equal(state.savedRevisions, 0)
  const evidence = { ok: true, browserVersion: browser.version(), targets: { lineSegment, lineMarkerSeries, lineMarkerPoint, areaFill }, initialDraft, finalDraft: await draft(), manifestSha256, assetHashes, errors, consoleErrors, httpErrors, state }
  await writeFile(join(out, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ok: true, directory: out, browserVersion: browser.version(), targets: evidence.targets, assets: assetChecks.length }))
} catch (error) {
  await writeFile(join(out, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, errors, consoleErrors, selected: await page?.locator('.workbook-chart-format-pane:not([hidden]) select[aria-label="图表元素"]').inputValue().catch(() => null) }, null, 2))
  await page?.screenshot({ path: join(out, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  await browser?.close(); server.kill('SIGTERM'); await writeFile(join(out, 'server.log'), serverLog)
}
