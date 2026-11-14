// 真实主 canvas 八向缩放/移动，受控修订保存、授权下载、独立 ZIP 回读。
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
const directory = process.env.WORKBOOK_CHART_GEOMETRY_DIRECTORY ?? '/tmp/workbook-chart-geometry-browser-20261113'
const staticDirectory = process.env.PDF_SMOKE_STATIC_DIRECTORY
const engineDirectory = process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
const resumeDirectory = process.env.WORKBOOK_CHART_GEOMETRY_RESUME_DIRECTORY
const resume = resumeDirectory ? JSON.parse(await readFile(join(resumeDirectory, 'failure.json'), 'utf8')) : undefined
assert(staticDirectory && engineDirectory, 'Explicit frozen static and workbook engine directories are required')
const port = Number(process.env.WORKBOOK_CHART_GEOMETRY_PORT ?? 4367), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: false })
const manifest = await readFile(join(staticDirectory, '.vite/manifest.json'))
const engine = await readFile(join(engineDirectory, 'dist/cli.mjs'))
const nativeOffice = await readFile(join(repo, 'smart_reporting/report_editor/native_office.py'))
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', directory, '--port', String(port), ...(resumeDirectory ? ['--source', join(resumeDirectory, 'source.xlsx')] : [])], {
  cwd: repo, env: { ...process.env, PYTHONPATH: repo, PDF_SMOKE_STATIC_DIRECTORY: staticDirectory, AGENT_REPORTING_WORKBOOK_ENGINE_DIR: engineDirectory }, stdio: 'pipe',
})
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', data => { serverLog += data }); server.stderr.on('data', data => { serverLog += data })
const errors = [], consoleErrors = [], httpErrors = [], assetErrors = [], assetChecks = [], assets = new Map(), actions = []
try {
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })).ok) break } catch {}
    assert(attempt < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const preflight = await probeCanvasTextRendering(browser); assert.equal(preflight.ok, true, JSON.stringify(preflight))
  page = await browser.newPage({ viewport: { width: 2800, height: 1400 } })
  if (resume) await page.addInitScript(drafts => {
    if (sessionStorage.getItem('geometry-smoke-restored')) return
    for (const [key, value] of drafts) localStorage.setItem(key, value)
    sessionStorage.setItem('geometry-smoke-restored', '1')
  }, resume.diagnostics.drafts)
  await page.addInitScript(() => {
    window.__geometryFrames = []
    const stroke = CanvasRenderingContext2D.prototype.strokeRect
    CanvasRenderingContext2D.prototype.strokeRect = function (x, y, width, height) {
      if (this.strokeStyle === '#9aa4ad' && width >= 22 && height >= 22) {
        const m = this.getTransform()
        const canvas = this.canvas.getBoundingClientRect().width > 0 ? this.canvas : [...document.querySelectorAll('.workbook-grid canvas')].find(canvas => canvas.getBoundingClientRect().width > 0)
        if (canvas) {
          const r = canvas.getBoundingClientRect(), sx = r.width / canvas.width, sy = r.height / canvas.height
          // renderer 的灰框在真实 bounds 内缩0.5；恢复真实几何后点击八个控制点。
          window.__geometryFrames.push({ x: r.left + (m.a * (x - 0.5) + m.e) * sx, y: r.top + (m.d * (y - 0.5) + m.f) * sy,
            width: m.a * (width + 1) * sx, height: m.d * (height + 1) * sy, scaleX: m.a * sx, scaleY: m.d * sy,
            raw: { x, y, e: m.e, f: m.f, canvas: this.canvas.getBoundingClientRect().toJSON(), target: r.toJSON() } })
          window.__geometryFrames = window.__geometryFrames.slice(-100)
        }
      }
      return stroke.call(this, x, y, width, height)
    }
  })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(?:js|css)$/.test(path)) assetChecks.push((async () => {
      assert.equal(response.status(), 200)
      const bytes = await response.body(), disk = await readFile(join(staticDirectory, path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })().catch(error => assetErrors.push({ path, error: String(error) })))
  })
  const cdp = await page.context().newCDPSession(page); await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  const charts = () => page.evaluate(() => [...window.__sheetsWebCharts.store.values()].flat())
  const anchor = async () => (await charts()).find(chart => chart.chartPath === 'xl/charts/chart2.xml').anchor
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  const equalAnchor = expected => page.waitForFunction(expected => JSON.stringify([...window.__sheetsWebCharts.store.values()].flat().find(chart => chart.chartPath === 'xl/charts/chart2.xml')?.anchor) === JSON.stringify(expected), expected)
  const command = async id => { await page.locator(`[data-ribbon-command="${id}"]`).click(); await ready() }
  const frame = async () => {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const result = await page.evaluate(() => window.__geometryFrames.at(-1))
    if (await page.locator('.workbook-grid').getAttribute('data-selected-chart') === 'xl/charts/chart2.xml') {
      // 扩展先绘制到含缓存边距的离屏 canvas；实际控制点以浏览器截图蓝色像素为准，
      // 不把离屏 transform/公式栏 canvas 的 DOM 矩形误当成主 canvas 坐标。
      const pixels = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import io,json,sys
import numpy as np
from PIL import Image
a=np.asarray(Image.open(io.BytesIO(sys.stdin.buffer.read())).convert('RGB'))
y,x=np.where(np.all(a==[37,99,235],axis=2)&(np.indices(a.shape[:2])[0]>250))
assert len(x)>0
print(json.dumps({'x':int(x.min())+4,'y':int(y.min())+4,'width':int(x.max()-x.min())-7,'height':int(y.max()-y.min())-7}))
`], { input: await page.screenshot(), encoding: 'utf8' })
      assert.equal(pixels.status, 0, pixels.stderr)
      Object.assign(result, JSON.parse(pixels.stdout))
    }
    assert(result && result.x > 0 && result.y > 0 && result.x + result.width < innerWidthSafe, JSON.stringify(result))
    return result
  }
  // 视口固定，避免在 Node 断言中依赖浏览器的全局 innerWidth。
  const innerWidthSafe = 2800
  const selectSecond = async () => {
    const f = await frame()
    if (await page.locator('.workbook-grid').getAttribute('data-selected-chart') === 'xl/charts/chart2.xml') return f
    await page.mouse.click(f.x + f.width / 2, f.y + f.height / 2)
    await page.waitForFunction(() => document.querySelector('.workbook-grid')?.dataset.selectedChart === 'xl/charts/chart2.xml')
    return f
  }
  async function drag(corner, dx, dy, cancel) {
    await selectSecond()
    const f = await frame(), before = await anchor(), operations = await draft()
    const x = f.x + (corner.includes('w') ? 0 : corner.includes('e') ? f.width : f.width / 2)
    const y = f.y + (corner.includes('n') ? 0 : corner.includes('s') ? f.height : f.height / 2)
    await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + dx, y + dy, { steps: 8 })
    await page.locator('[data-chart-geometry-preview="xl/charts/chart2.xml"]').waitFor()
    assert.deepEqual(await anchor(), before, 'Preview must not mutate chart data')
    if (cancel === 'Escape') await page.keyboard.press('Escape')
    if (cancel === 'wheel') await page.mouse.wheel(0, 0)
    await page.mouse.up()
    if (cancel) {
      await page.locator('[data-chart-geometry-preview]').waitFor({ state: 'detached' })
      assert.deepEqual(await anchor(), before); assert.deepEqual(await draft(), operations)
    } else {
      await page.waitForFunction(before => JSON.stringify([...window.__sheetsWebCharts.store.values()].flat().find(chart => chart.chartPath === 'xl/charts/chart2.xml')?.anchor) !== JSON.stringify(before), before)
      await ready()
    }
    const after = await anchor()
    actions.push({ stage, corner, dx, dy, cancel, before, after, frame: f })
    return { before, after, frame: f }
  }
  stage = 'open'; await page.goto(origin + info.openPath); await ready()
  await page.waitForFunction(() => window.__sheetsWebCharts?.store.size > 0 && window.__geometryFrames.length >= 2)
  const originalCharts = await charts(), firstAnchor = originalCharts[0].anchor
  assert.deepEqual(originalCharts.map(chart => chart.title), ['Same', 'Same'])
  let manual
  if (resume) {
    assert(['rtl', 'save-download-reopen'].includes(resume.stage), 'Only continue a recorded RTL/save-stage smoke failure')
    actions.push(...resume.actions)
    const operations = await draft(), firstGeometry = operations.findIndex(operation => operation.kind === 'applyChartAnchors')
    assert(firstGeometry > 0)
    manual = operations.slice(0, firstGeometry)
    assert.deepEqual(await anchor(), resume.diagnostics.charts.find(chart => chart.chartPath === 'xl/charts/chart2.xml').anchor)
    if (resume.stage === 'rtl') {
      await page.locator('[data-ribbon-tab="View"]').click()
      await page.getByRole('combobox', { name: '缩放比例', exact: true }).selectOption('75')
    }
  } else {
  stage = 'manual-A1'; const nameBox = page.locator('[data-u-comp="defined-name"] input')
  await nameBox.fill('A1'); await nameBox.press('Enter'); await page.keyboard.type('Manual geometry'); await page.keyboard.press('Enter')
  await nameBox.fill('A1'); await nameBox.press('Enter'); await command('bold')
  await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(op => op.kind === 'applyCellEdits')))
  manual = await draft()
  stage = 'move'; await drag('', -110, 35)
  for (const corner of ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']) {
    stage = `resize-${corner}`
    const { before, after } = await drag(corner, corner.includes('w') ? -10 : corner.includes('e') ? 10 : 0, corner.includes('n') ? -8 : corner.includes('s') ? 8 : 0)
    const changed = Object.keys(after).filter(key => after[key] !== before[key])
    assert(changed.length > 0)
    for (const key of changed) {
      assert((corner.includes('n') && key.startsWith('fromRow')) || (corner.includes('s') && key.startsWith('toRow')) ||
        (corner.includes('w') && key.startsWith('fromColumn')) || (corner.includes('e') && key.startsWith('toColumn')), `${corner}: unexpected ${key}`)
    }
  }
  await page.screenshot({ path: join(directory, 'eight-handles.png'), fullPage: true })
  stage = 'minimum24'; const large = await anchor(), largeFrame = await frame()
  await drag('se', -largeFrame.width + 6, -largeFrame.height + 6)
  const tiny = await frame(); assert(Math.abs(tiny.width - 24 * tiny.scaleX) < 1 && Math.abs(tiny.height - 24 * tiny.scaleY) < 1, JSON.stringify(tiny))
  await page.screenshot({ path: join(directory, 'minimum24.png'), fullPage: true })
  await selectSecond(); await drag('', 32, 12)
  stage = 'undo-redo'; const tinyMoved = await anchor()
  await page.locator('[data-ribbon-tab="File"]').click(); await command('undo'); await command('redo'); await equalAnchor(tinyMoved)
  await command('undo'); await command('undo'); await equalAnchor(large)
  stage = 'cancel-Escape'; await drag('', 38, 22, 'Escape')
  stage = 'cancel-wheel'; await drag('se', 25, 15, 'wheel')
  stage = 'zoom75'; await page.locator('[data-ribbon-tab="View"]').click()
  await page.getByRole('combobox', { name: '缩放比例', exact: true }).selectOption('75'); await drag('', -24, 18)
  }
  if (resume?.stage !== 'save-download-reopen') {
  stage = 'rtl'; await page.locator('[data-ribbon-tab="View"]').click(); await command('toggle-right-to-left')
  const rtl = await drag('', 28, 15)
  assert(rtl.after.fromColumn < rtl.before.fromColumn || rtl.after.fromColumnOffset < rtl.before.fromColumnOffset, 'RTL screen-right must reduce logical column coordinate')
  await drag('se', 12, 9)
  await page.screenshot({ path: join(directory, 'rtl75.png'), fullPage: true })
  // 恢复默认视图后再保存，仍保留此前真实 zoom/RTL 操作证据。
  await command('toggle-right-to-left'); await page.locator('[data-ribbon-tab="View"]').click()
  await page.getByRole('combobox', { name: '缩放比例', exact: true }).selectOption('100')
  }
  assert.deepEqual((await charts())[0].anchor, firstAnchor)
  const adopted = await draft(), expected = await anchor()
  assert.deepEqual(adopted.slice(0, manual.length), manual)
  stage = 'draft-recovery'; await page.reload(); await ready(); await equalAnchor(expected); assert.deepEqual(await draft(), adopted)
  stage = 'save-download-reopen'
  const waiting = page.waitForResponse(response => response.url().endsWith('/api/save') && response.request().method() === 'POST')
  await page.locator('[data-action="save"]').click()
  const response = await waiting, payload = await response.json(); assert.equal(response.status(), 200, JSON.stringify(payload))
  assert.equal(payload.parentRevision, info.context.revision); assert.equal(payload.revision, info.context.revision + 1); assert.equal(payload.revisionRegistered, true)
  const link = page.locator('[data-action="xlsx-download"]'); await link.waitFor()
  const [download] = await Promise.all([page.waitForEvent('download'), link.click()])
  await download.saveAs(join(directory, 'geometry.xlsx')); assert.equal(await download.failure(), null)
  assert.equal(sha(await readFile(join(directory, 'geometry.xlsx'))), payload.artifacts.xlsx.sha256)
  await page.goto(payload.editor.openUrl); await ready(); await equalAnchor(expected)
  const reopened = await page.request.get(page.url() + '/api/file'); assert.equal(reopened.status(), 200)
  assert.equal(sha(await reopened.body()), payload.artifacts.xlsx.sha256)
  await page.screenshot({ path: join(directory, 'geometry-reopened.png'), fullPage: true })
  await writeFile(join(directory, 'expected.json'), JSON.stringify({ anchor: expected, actions }, null, 2))
  const verified = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-chart-object-geometry-verify.py'), directory], { cwd: repo, encoding: 'utf8' })
  assert.equal(verified.status, 0, verified.stdout + verified.stderr)
  await Promise.all(assetChecks); assert(assets.size > 0); assert.deepEqual(assetErrors, [])
  assert.equal(sha(await readFile(join(staticDirectory, '.vite/manifest.json'))), sha(manifest)); assert.equal(sha(await readFile(join(engineDirectory, 'dist/cli.mjs'))), sha(engine))
  assert.equal(sha(await readFile(join(repo, 'smart_reporting/report_editor/native_office.py'))), sha(nativeOffice))
  assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, [])
  const state = await (await page.request.get(origin + '/__smoke__/state')).json()
  assert.equal(state.plannerCalls, 0); assert.equal(state.savedRevisions, 1)
  const summary = { ok: true, resumedFrom: resumeDirectory ?? null, browserVersion: browser.version(), preflight, manifestSha256: sha(manifest), engineSha256: sha(engine), nativeOfficeSha256: sha(nativeOffice), assets: Object.fromEntries(assets), actions, manual, adopted,
    save: { payload, request: response.request().postDataJSON() }, independent: JSON.parse(verified.stdout), state, errors, consoleErrors, httpErrors, assetErrors }
  await writeFile(join(directory, 'summary.json'), JSON.stringify(summary, null, 2)); console.log(JSON.stringify({ ok: true, directory, actions: actions.length, independent: summary.independent }))
} catch (error) {
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, errors, consoleErrors, httpErrors, assetErrors, actions,
    diagnostics: page ? await page.evaluate(() => ({ frames: window.__geometryFrames, selected: document.querySelector('.workbook-grid')?.dataset.selectedChart, active: document.activeElement?.outerHTML.slice(0, 600),
      charts: [...(window.__sheetsWebCharts?.store.values() ?? [])].flat(), drafts: Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')), feedback: document.querySelector('.workbook-feedback')?.textContent })).catch(() => null) : null }, null, 2))
  if (page) await page.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally { await browser?.close(); server.kill('SIGTERM'); await writeFile(join(directory, 'server.log'), serverLog) }
