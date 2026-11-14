// 直接插入九种源图表：人工数据/样式、草稿历史及真实授权保存下载回读。
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
const directory = process.env.WORKBOOK_DIRECT_DIRECTORY ?? '/dev/shm/office-chart-insert-20261113/frozen-save'
const staticDirectory = process.env.PDF_SMOKE_STATIC_DIRECTORY, engineDirectory = process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
assert(staticDirectory && engineDirectory, '必须显式指定冻结前端与workbook bridge')
const port = Number(process.env.WORKBOOK_DIRECT_PORT ?? 4411), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: false })
const manifest = await readFile(join(staticDirectory, '.vite/manifest.json')), engine = await readFile(join(engineDirectory, 'dist/cli.mjs'))
if (process.env.WORKBOOK_DIRECT_MANIFEST) assert.equal(sha(manifest), process.env.WORKBOOK_DIRECT_MANIFEST)
const nativeOffice = await readFile(join(repo, 'smart_reporting/report_editor/native_office.py'))
const fixture = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-direct-charts-verify.py'), directory, '--fixture'], { cwd: repo, encoding: 'utf8' })
assert.equal(fixture.status, 0, fixture.stderr)
const fixtureIdentity = JSON.parse(fixture.stdout)
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', directory, '--port', String(port), '--source', join(directory, 'fixture.xlsx')], {
  cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe',
})
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', data => { serverLog += data }); server.stderr.on('data', data => { serverLog += data })
const errors = [], consoleErrors = [], httpErrors = [], assetErrors = [], assets = new Map(), checks = []
try {
  for (let i = 0; ; i++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })).ok) break } catch {}
    assert(i < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8'))
  assert.equal(info.sourceSha256, fixtureIdentity.sourceSha256)
  browser = await chromium.launch({ headless: true })
  const preflight = await probeCanvasTextRendering(browser); assert.equal(preflight.ok, true, JSON.stringify(preflight))
  page = await browser.newPage({ viewport: { width: 1760, height: 1100 }, acceptDownloads: true })
  const cdp = await page.context().newCDPSession(page); await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(js|css)$/.test(path)) checks.push((async () => {
      assert.equal(response.status(), 200)
      const bytes = await response.body(), disk = await readFile(join(staticDirectory, path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })().catch(error => assetErrors.push({ path, error: String(error) })))
  })
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  const charts = () => page.evaluate(() => [...window.__sheetsWebCharts.store.values()].flat())
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  const count = expected => page.waitForFunction(expected => [...window.__sheetsWebCharts.store.values()].flat().length === expected, expected)
  const command = async id => { await page.locator(`[data-ribbon-command="${id}"]`).click(); await ready() }
  stage = 'open'; await page.goto(origin + info.openPath); await ready(); await count(1)
  stage = 'manual-draft'
  const name = page.locator('[data-u-comp="defined-name"] input')
  await name.fill('D20'); await name.press('Enter'); await page.keyboard.type('Manual direct chart'); await page.keyboard.press('Enter')
  await name.fill('D20'); await name.press('Enter'); await command('bold')
  await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(operation => operation.kind === 'applyCellEdits' && operation.edits.some(edit => edit.row === 19 && edit.column === 3 && edit.style?.bold === true))))
  const manual = await draft()
  const kinds = ['column', 'bar', 'line', 'area', 'pie', 'scatter', 'radar', 'doughnut', 'combo'], additions = []
  for (const [index, kind] of kinds.entries()) {
    stage = `direct-${kind}`
    await name.fill('A1:C4'); await name.press('Enter'); await page.locator('[data-ribbon-tab="Insert"]').click()
    const button = page.locator(`[data-ribbon-command="insert-chart:${kind}"]`)
    await button.scrollIntoViewIfNeeded()
    const hit = await button.evaluate(node => { const r = node.getBoundingClientRect(); return node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)) }); assert(hit)
    await button.click(); await count(index + 2); await ready()
    await page.waitForFunction(expected => Object.entries(localStorage).some(([key,value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).filter(operation => operation.kind === 'applyChartAdditions').length === expected), index + 1)
    const current = await draft(); assert.deepEqual(current.slice(0, manual.length), manual)
    const addition = current.filter(operation => operation.kind === 'applyChartAdditions').at(-1).additions[0]
    assert.equal(addition.chart.chartType, kind); additions.push({ kind, hit, addition })
  }
  const adopted = await draft()
  await page.screenshot({path:join(directory,'direct-charts-desktop.png'),animations:'disabled'})
  stage = 'undo-redo'; await page.locator('[data-ribbon-tab="File"]').click(); await command('undo'); await count(9)
  assert.deepEqual(await draft(), adopted.slice(0, -1))
  await command('redo'); await count(10); assert.deepEqual(await draft(), adopted)
  stage = 'draft-recovery'; await page.reload(); await ready(); await count(10); assert.deepEqual(await draft(), adopted)
  stage = 'save-download-reopen'
  const waiting = page.waitForResponse(response => response.url().endsWith('/api/save') && response.request().method() === 'POST')
  await page.locator('[data-action="save"]').click()
  const response = await waiting, saved = await response.json(); assert.equal(response.status(), 200, JSON.stringify(saved))
  assert.equal(saved.parentRevision, info.context.revision); assert.equal(saved.revision, info.context.revision + 1); assert.equal(saved.revisionRegistered, true)
  const request = response.request().postDataJSON(); assert.equal(request.expectedSha256, fixtureIdentity.sourceSha256); assert.deepEqual(request.operations, adopted)
  const link = page.locator('[data-action="xlsx-download"]'); await link.waitFor()
  const [download] = await Promise.all([page.waitForEvent('download'), link.click()])
  await download.saveAs(join(directory, 'direct-charts.xlsx')); assert.equal(await download.failure(), null)
  assert.equal(sha(await readFile(join(directory, 'direct-charts.xlsx'))), saved.artifacts.xlsx.sha256)
  await page.goto(saved.editor.openUrl); await ready(); await count(10)
  const reopened = await page.request.get(page.url() + '/api/file'); assert.equal(reopened.status(), 200); assert.equal(sha(await reopened.body()), saved.artifacts.xlsx.sha256)
  const reopenedCharts = await charts()
  for (const [index, kind] of kinds.entries()) {
    assert.equal(reopenedCharts.find(chart => chart.chartPath === `xl/charts/chart${index + 2}.xml`)?.kind, kind)
  }
  await page.screenshot({ path: join(directory, 'direct-charts-reopened.png'), fullPage: true })
  stage = 'narrow-controls'; await page.setViewportSize({ width: 390, height: 640 }); await page.locator('[data-ribbon-tab="Insert"]').click()
  const narrowControls = []
  for (const kind of kinds) {
    const button = page.locator(`[data-ribbon-command="insert-chart:${kind}"]`); await button.scrollIntoViewIfNeeded()
    assert(await button.isEnabled())
    const hit = await button.evaluate(node => { const r = node.getBoundingClientRect(); return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)) }); assert(hit)
    narrowControls.push({kind,hit})
  }
  await page.screenshot({path:join(directory,'direct-charts-mobile-controls.png'),animations:'disabled'})

  const verification = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-direct-charts-verify.py'), directory], { cwd: repo, encoding: 'utf8' })
  assert.equal(verification.status, 0, verification.stderr || verification.stdout)
  await Promise.all(checks); assert(assets.size > 0)
  assert.equal(sha(await readFile(join(staticDirectory, '.vite/manifest.json'))), sha(manifest)); assert.equal(sha(await readFile(join(engineDirectory, 'dist/cli.mjs'))), sha(engine))
  assert.equal(sha(await readFile(join(repo, 'smart_reporting/report_editor/native_office.py'))), sha(nativeOffice))
  assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, []); assert.deepEqual(assetErrors, [])
  const state = await (await page.request.get(origin + '/__smoke__/state')).json(); assert.equal(state.plannerCalls, 0); assert.equal(state.savedRevisions, 1)
  const evidence = { ok: true, browserVersion: browser.version(), preflight, sourceSha256: fixtureIdentity.sourceSha256, manifestSha256: sha(manifest), engineSha256: sha(engine), nativeOfficeSha256: sha(nativeOffice),
    assets: Object.fromEntries(assets), additions, narrowControls, manual, adopted, request, saved, independent: JSON.parse(verification.stdout), state, errors, consoleErrors, httpErrors, assetErrors }
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, directory, assets: assets.size, independent: evidence.independent }))
} catch (error) {
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, errors, consoleErrors, httpErrors, assetErrors,
    diagnostics: page ? await page.evaluate(() => ({ charts: [...(window.__sheetsWebCharts?.store.values() ?? [])].flat(), drafts: Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')), feedback: document.querySelector('.workbook-feedback')?.textContent })).catch(() => null) : null }, null, 2))
  await page?.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally { await browser?.close(); server.kill('SIGTERM'); await writeFile(join(directory, 'server.log'), serverLog) }
