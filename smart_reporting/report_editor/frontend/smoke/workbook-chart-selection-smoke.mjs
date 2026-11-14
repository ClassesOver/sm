// 真实 canvas 选图、原生功能区、文件写入、下载和独立回读；复用受控修订宿主。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { probeCanvasTextRendering } from './canvas-font-preflight.mjs'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const directory = process.env.WORKBOOK_CHART_SELECTION_DIRECTORY ?? '/tmp/workbook-chart-selection-browser-20261113'
const staticDirectory = process.env.PDF_SMOKE_STATIC_DIRECTORY ?? join(frontend, '../static')
const port = Number(process.env.WORKBOOK_CHART_SELECTION_PORT ?? 4356), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: false })
const manifest = await readFile(join(staticDirectory, '.vite/manifest.json'))
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', directory, '--port', String(port)], {
  cwd: repo, env: { ...process.env, PYTHONPATH: repo, PDF_SMOKE_STATIC_DIRECTORY: staticDirectory }, stdio: 'pipe',
})
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', data => { serverLog += data }); server.stderr.on('data', data => { serverLog += data })
const errors = [], consoleErrors = [], httpErrors = [], assets = new Map(), assetErrors = [], checks = [], saves = []
try {
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })).ok) break } catch {}
    assert(attempt < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const preflight = await probeCanvasTextRendering(browser); assert.equal(preflight.ok, true, JSON.stringify(preflight))
  page = await browser.newPage({ viewport: { width: 1760, height: 1100 } })
  await page.addInitScript(() => {
    window.__selectionFrames = []; window.__selectionPaints = []; window.__selectionEvents = []; window.__selectionFocus = []
    const focus = HTMLElement.prototype.focus
    HTMLElement.prototype.focus = function (...args) {
      const result = focus.apply(this, args)
      window.__selectionFocus.push({ tag:this.tagName, class:this.className, id:this.id, comp:this.dataset.uComp, active:document.activeElement?.outerHTML.slice(0,350), stack:new Error().stack })
      window.__selectionFocus = window.__selectionFocus.slice(-30)
      return result
    }
    for (const type of ['pointerdown', 'pointerup', 'click', 'dblclick', 'focusin']) document.addEventListener(type, event => {
      window.__selectionEvents.push({ type, x: event.clientX, y: event.clientY, tag: event.target?.tagName, class: event.target?.className, selected: document.querySelector('.workbook-grid')?.dataset.selectedChart })
      window.__selectionEvents = window.__selectionEvents.slice(-30)
    }, true)
    const stroke = CanvasRenderingContext2D.prototype.strokeRect, text = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.strokeRect = function (x, y, width, height) {
      if (this.strokeStyle === '#9aa4ad' && width >= 40 && height >= 30) {
        const m = this.getTransform()
        // Univer 扩展也绘制到离屏缓存；点击坐标使用实际可见主 canvas 的 CSS 比例。
        const canvas = this.canvas.getBoundingClientRect().width > 0 ? this.canvas : [...document.querySelectorAll('.workbook-grid canvas')].find(canvas => canvas.getBoundingClientRect().width > 0)
        if (!canvas) return stroke.call(this, x, y, width, height)
        const r = canvas.getBoundingClientRect(), sx = r.width / canvas.width, sy = r.height / canvas.height
        window.__selectionFrames.push({ localX: x, x: r.left + (m.a * x + m.e) * sx, y: r.top + (m.d * y + m.f) * sy, width: m.a * width * sx, height: m.d * height * sy })
        window.__selectionFrames = window.__selectionFrames.slice(-50)
      }
      return stroke.call(this, x, y, width, height)
    }
    CanvasRenderingContext2D.prototype.fillText = function (...args) {
      if (this.font.includes('system-ui')) { window.__selectionPaints.push(String(args[0])); window.__selectionPaints = window.__selectionPaints.slice(-3000) }
      return text.apply(this, args)
    }
  })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(?:js|css)$/.test(path)) checks.push((async () => {
      assert.equal(response.status(), 200)
      const bytes = await response.body(), disk = await readFile(join(staticDirectory, path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })().catch(error => assetErrors.push({ path, error: String(error) })))
  })
  const cdp = await page.context().newCDPSession(page); await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  const charts = () => page.evaluate(() => [...window.__sheetsWebCharts.store.values()].flat())
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  const waitChart = expected => page.waitForFunction(expected => {
    const chart = [...window.__sheetsWebCharts.store.values()].flat().find(c => c.chartPath === 'xl/charts/chart2.xml')
    return chart && Object.entries(expected).every(([key, value]) => key === 'legend' ? (chart.legend?.position ?? 'none') === value : chart[key] === value)
  }, expected, { timeout: 30000 })
  const command = async id => { await page.locator(`[data-ribbon-command="${id}"]`).click(); await ready() }
  async function selectSecond(doubleClick = false) {
    const frame = await page.evaluate(() => window.__selectionFrames.filter(frame => frame.width >= 40 && frame.height >= 30 && frame.x >= 0 && frame.x < innerWidth - 50 && frame.y >= 0 && frame.y < innerHeight - 50).sort((a, b) => a.localX - b.localX).at(-1))
    assert(frame, 'No actual visible chart frame')
    const x = Math.min(1720, frame.x + frame.width / 2), y = frame.y + Math.min(frame.height / 2, 120)
    await writeFile(join(directory, `select-point-${stage}.json`), JSON.stringify({ frame, x, y, hit: await page.evaluate(({ x, y }) => document.elementsFromPoint(x,y).map(element => ({ tag:element.tagName, class:element.className })), {x,y}) }, null, 2))
    if (doubleClick) await page.mouse.dblclick(x, y)
    else await page.mouse.click(x, y)
    await page.waitForFunction(() => document.querySelector('.workbook-grid')?.getAttribute('data-selected-chart') === 'xl/charts/chart2.xml')
    if (doubleClick) {
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('.workbook-grid')), true)
    }
  }
  async function saveAndReopen(name, parent) {
    const waiting = page.waitForResponse(response => response.url().endsWith('/api/save') && response.request().method() === 'POST')
    await page.locator('[data-action="save"]').click()
    const response = await waiting, payload = await response.json(); assert.equal(response.status(), 200, JSON.stringify(payload))
    assert.equal(payload.parentRevision, parent); assert.equal(payload.revision, parent + 1); assert.equal(payload.revisionRegistered, true)
    const link = page.locator('[data-action="xlsx-download"]'); await link.waitFor()
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()])
    await download.saveAs(join(directory, `${name}.xlsx`)); assert.equal(await download.failure(), null)
    assert.equal(sha(await readFile(join(directory, `${name}.xlsx`))), payload.artifacts.xlsx.sha256)
    await page.goto(payload.editor.openUrl); await ready()
    const file = await page.request.get(page.url() + '/api/file'); assert.equal(file.status(), 200); assert.equal(sha(await file.body()), payload.artifacts.xlsx.sha256)
    await page.screenshot({ path: join(directory, `${name}-reopened.png`), fullPage: true })
    saves.push({ name, payload, request: response.request().postDataJSON() })
  }
  stage = 'open'; await page.goto(origin + info.openPath); await ready()
  await page.waitForFunction(() => window.__sheetsWebCharts?.store.size > 0)
  assert.deepEqual((await charts()).map(c => c.title), ['Same', 'Same'])
  stage = 'manual-edit'
  const nameBox = page.locator('[data-u-comp="defined-name"] input')
  await nameBox.fill('A1'); await nameBox.press('Enter'); await command('bold')
  await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(op => op.kind === 'applyCellEdits')))
  const manual = await draft()
  stage = 'direct-selection'; await page.locator('[data-ribbon-tab="Chart Design"]').click()
  assert.equal(await page.locator('[aria-label="快速布局"]').isDisabled(), true)
  await selectSecond(true); await page.screenshot({ path: join(directory, 'selected-second.png'), fullPage: true })
  await page.keyboard.press('Escape'); assert.equal(await page.locator('[aria-label="快速布局"]').isDisabled(), true)
  stage = 'keyboard-accessible-selection'; await command('chart-descriptions')
  await page.locator('[data-select-chart="xl/charts/chart2.xml"]').focus(); await page.keyboard.press('Enter')
  await page.waitForFunction(() => document.querySelector('.workbook-grid')?.getAttribute('data-selected-chart') === 'xl/charts/chart2.xml')
  stage = 'selected-title'; await command('chart-title')
  await page.getByRole('textbox', { name: '图表标题', exact: true }).fill('Selected')
  await page.locator('[data-chart-design-submit]').click(); await waitChart({ title: 'Selected' })
  assert.equal((await charts())[0].title, 'Same')
  stage = 'type-and-layout'; await command('chart-type-pie'); await waitChart({ kind: 'pie' })
  for (const [id, legend] of [['1', 'right'], ['2', 'top'], ['3', 'bottom'], ['4', 'none'], ['2', 'top']]) {
    await page.getByRole('combobox', { name: '快速布局', exact: true }).selectOption(`chart-layout:${id}`)
    await waitChart({ legend })
    await page.waitForFunction(enabled => ([...window.__sheetsWebCharts.store.values()].flat().find(c => c.chartPath.endsWith('chart2.xml'))?.dataLabels?.showPercent ?? false) === enabled, id !== '3')
    const target = (await charts())[1]
    assert.equal(target.dataLabels?.showPercent ?? false, id !== '3')
  }
  const beforePalette = (await charts())[1].series[0].pointColors ?? null
  stage = 'palette'; await page.getByRole('combobox', { name: '更改颜色', exact: true }).selectOption('chart-colors:green')
  await page.waitForFunction(() => [...window.__sheetsWebCharts.store.values()].flat().find(c => c.chartPath.endsWith('chart2.xml'))?.series[0]?.pointColors?.[0]?.toLowerCase() === '#375623')
  await page.waitForFunction(() => window.__selectionPaints.includes('33%') && window.__selectionPaints.includes('67%'))
  const adopted = await draft(); assert.deepEqual(adopted.slice(0, manual.length), manual)
  stage = 'undo-redo'; await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
  await page.waitForFunction(before => JSON.stringify([...window.__sheetsWebCharts.store.values()].flat().find(c => c.chartPath.endsWith('chart2.xml'))?.series[0]?.pointColors ?? null) === JSON.stringify(before), beforePalette)
  await command('redo')
  await page.waitForFunction(() => [...window.__sheetsWebCharts.store.values()].flat().find(c => c.chartPath.endsWith('chart2.xml'))?.series[0]?.pointColors?.[0]?.toLowerCase() === '#375623')
  stage = 'draft-recovery'; await page.reload(); await ready()
  await waitChart({ title: 'Selected', kind: 'pie', legend: 'top' }); assert.deepEqual(await draft(), adopted)
  await page.locator('[data-ribbon-tab="View"]').click()
  await page.getByRole('combobox', { name: '缩放比例', exact: true }).selectOption('75')
  await page.locator('[data-ribbon-tab="Chart Design"]').click()
  await page.screenshot({ path: join(directory, 'pie-preview.png'), fullPage: true })
  stage = 'save-edited'; await saveAndReopen('edited', info.context.revision)
  await waitChart({ title: 'Selected', kind: 'pie', legend: 'top' })
  stage = 'zoom-selection'; await page.locator('[data-ribbon-tab="View"]').click()
  await page.evaluate(() => { window.__selectionFrames = [] })
  await page.getByRole('combobox', { name: '缩放比例', exact: true }).selectOption('75')
  await page.waitForFunction(() => window.__selectionFrames.length >= 2)
  await page.locator('[data-ribbon-tab="Chart Design"]').click(); await selectSecond()
  stage = 'keyboard-delete'; await page.keyboard.press('Delete')
  await page.waitForFunction(() => [...window.__sheetsWebCharts.store.values()].flat().length === 1)
  assert.equal((await charts())[0].title, 'Same')
  stage = 'save-deleted'; await saveAndReopen('deleted', info.context.revision + 1)
  assert.equal((await charts()).length, 1)
  const verified = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-chart-selection-verify.py'), directory], { cwd: repo, encoding: 'utf8' })
  assert.equal(verified.status, 0, verified.stdout + verified.stderr)
  await Promise.all(checks); assert(assets.size > 0); assert.equal(sha(await readFile(join(staticDirectory, '.vite/manifest.json'))), sha(manifest))
  assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, []); assert.deepEqual(assetErrors, [])
  const state = await (await page.request.get(origin + '/__smoke__/state')).json(); assert.equal(state.plannerCalls, 0); assert.equal(state.savedRevisions, 2)
  const summary = { ok: true, browserVersion: browser.version(), scope: 'Real manual UI, native canvas selection and ribbon, HTTP save/download/reopen; scoped memory revision repository', preflight, manifestSha256: sha(manifest), assets: Object.fromEntries(assets), manual, adopted, saves, independent: JSON.parse(verified.stdout), state, errors, consoleErrors, httpErrors, assetErrors }
  await writeFile(join(directory, 'summary.json'), JSON.stringify(summary, null, 2)); console.log(JSON.stringify({ ok: true, directory, assets: assets.size, independent: summary.independent }))
} catch (error) {
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, errors, consoleErrors, httpErrors, assetErrors,
    diagnostics: page ? await page.evaluate(() => ({ frames:window.__selectionFrames, events:window.__selectionEvents, focus:window.__selectionFocus, active:document.activeElement?.outerHTML.slice(0,600), selected:document.querySelector('.workbook-grid')?.dataset.selectedChart, charts: [...(window.__sheetsWebCharts?.store.values() ?? [])].flat(), drafts: Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')), feedback: document.querySelector('.workbook-feedback')?.textContent })).catch(() => null) : null }, null, 2))
  if (page) await page.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally { await browser?.close(); server.kill('SIGTERM'); await writeFile(join(directory, 'server.log'), serverLog) }
