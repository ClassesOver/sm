// 固定源推荐入口：真实选区、排名预览/取消、插入、草稿历史和授权HTTP产物闭环。
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
const directory = process.env.WORKBOOK_RECOMMENDED_DIRECTORY ?? '/dev/shm/office-recommended-charts-20261113/browser'
const staticDirectory = process.env.PDF_SMOKE_STATIC_DIRECTORY, engineDirectory = process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
assert(staticDirectory && engineDirectory, '必须显式指定冻结前端与workbook bridge')
const port = Number(process.env.WORKBOOK_RECOMMENDED_PORT ?? 4411), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: false })
const manifest = await readFile(join(staticDirectory, '.vite/manifest.json')), engine = await readFile(join(engineDirectory, 'dist/cli.mjs'))
const nativeOffice = await readFile(join(repo, 'smart_reporting/report_editor/native_office.py'))
const fixture = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-recommended-charts-verify.py'), directory, '--fixture'], { cwd: repo, encoding: 'utf8' })
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
  await name.fill('D20'); await name.press('Enter'); await page.keyboard.type('Manual recommendation'); await page.keyboard.press('Enter')
  await name.fill('D20'); await name.press('Enter'); await command('bold')
  await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(operation => operation.kind === 'applyCellEdits' && operation.edits.some(edit => edit.row === 19 && edit.column === 3 && edit.style?.bold === true))))
  const manual = await draft()
  await name.fill('A1:B4'); await name.press('Enter'); await page.locator('[data-ribbon-tab="Insert"]').click()
  const dialog = page.getByRole('dialog', { name: '推荐的图表', exact: true })
  stage = 'recommendation-preview'; await command('recommended-charts-open'); await dialog.waitFor()
  const rankings = await dialog.locator('[data-recommended-chart]').evaluateAll(nodes => nodes.map(node => ({ kind: node.dataset.recommendedChart, text: node.textContent })))
  assert.equal(rankings[0].kind, 'line'); assert(rankings[0].text.includes('时间序列适合用趋势展示'))
  const preview = await dialog.locator('[data-recommended-chart="line"] path').getAttribute('d')
  assert.equal(preview, 'M8.0,66.7 L90.0,37.3 L172.0,8.0')
  assert.deepEqual(await draft(), manual); assert.equal((await charts()).length, 1)
  await page.screenshot({ path: join(directory, 'recommendations-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  const fit = await dialog.locator('.workbook-recommended-charts-dialog').evaluate(node => {
    const rect = node.getBoundingClientRect(); return { left: rect.left, right: rect.right, width: innerWidth, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth }
  })
  assert(fit.left >= 0 && fit.right <= fit.width && fit.scrollWidth <= fit.clientWidth + 1, JSON.stringify(fit))
  await page.screenshot({ path: join(directory, 'recommendations-mobile.png'), fullPage: true })
  await page.setViewportSize({ width: 1760, height: 1100 })
  stage = 'cancel'; await dialog.locator('[data-recommended-close]').click(); await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(await draft(), manual)
  await command('recommended-charts-open'); await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' }); assert.deepEqual(await draft(), manual)
  stage = 'pick-insert'; await command('recommended-charts-open'); await dialog.locator('[data-recommended-chart="line"]').click(); await count(2); await ready()
  await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(operation => operation.kind === 'applyChartAdditions')))
  const adopted = await draft(); assert.deepEqual(adopted.slice(0, manual.length), manual)
  const addition = adopted.find(operation => operation.kind === 'applyChartAdditions').additions[0]
  assert.equal(addition.chart.chartType, 'line'); assert.equal(addition.chart.series.length, 1)
  assert.deepEqual(addition.chart.series[0].categories, ['2023', '2024', '2025'])
  assert.deepEqual(addition.chart.series[0].values, [10, 20, 30])
  stage = 'undo-redo'; await page.locator('[data-ribbon-tab="File"]').click(); await command('undo'); await count(1)
  assert.deepEqual(await draft(), manual)
  await command('redo'); await count(2); assert.deepEqual(await draft(), adopted)
  stage = 'draft-recovery'; await page.reload(); await ready(); await count(2); assert.deepEqual(await draft(), adopted)
  stage = 'save-download-reopen'
  const waiting = page.waitForResponse(response => response.url().endsWith('/api/save') && response.request().method() === 'POST')
  await page.locator('[data-action="save"]').click()
  const response = await waiting, saved = await response.json(); assert.equal(response.status(), 200, JSON.stringify(saved))
  assert.equal(saved.parentRevision, info.context.revision); assert.equal(saved.revision, info.context.revision + 1); assert.equal(saved.revisionRegistered, true)
  const request = response.request().postDataJSON(); assert.equal(request.expectedSha256, fixtureIdentity.sourceSha256); assert.deepEqual(request.operations, adopted)
  const link = page.locator('[data-action="xlsx-download"]'); await link.waitFor()
  const [download] = await Promise.all([page.waitForEvent('download'), link.click()])
  await download.saveAs(join(directory, 'recommended.xlsx')); assert.equal(await download.failure(), null)
  assert.equal(sha(await readFile(join(directory, 'recommended.xlsx'))), saved.artifacts.xlsx.sha256)
  await page.goto(saved.editor.openUrl); await ready(); await count(2)
  const reopened = await page.request.get(page.url() + '/api/file'); assert.equal(reopened.status(), 200); assert.equal(sha(await reopened.body()), saved.artifacts.xlsx.sha256)
  assert.equal((await charts()).find(chart => chart.chartPath === 'xl/charts/chart2.xml').kind, 'line')
  await page.screenshot({ path: join(directory, 'recommended-reopened.png'), fullPage: true })
  const verification = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-recommended-charts-verify.py'), directory], { cwd: repo, encoding: 'utf8' })
  assert.equal(verification.status, 0, verification.stderr || verification.stdout)
  await Promise.all(checks); assert(assets.size > 0)
  assert.equal(sha(await readFile(join(staticDirectory, '.vite/manifest.json'))), sha(manifest)); assert.equal(sha(await readFile(join(engineDirectory, 'dist/cli.mjs'))), sha(engine))
  assert.equal(sha(await readFile(join(repo, 'smart_reporting/report_editor/native_office.py'))), sha(nativeOffice))
  assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, []); assert.deepEqual(assetErrors, [])
  const state = await (await page.request.get(origin + '/__smoke__/state')).json(); assert.equal(state.plannerCalls, 0); assert.equal(state.savedRevisions, 1)
  const evidence = { ok: true, browserVersion: browser.version(), preflight, sourceSha256: fixtureIdentity.sourceSha256, manifestSha256: sha(manifest), engineSha256: sha(engine), nativeOfficeSha256: sha(nativeOffice),
    assets: Object.fromEntries(assets), rankings, preview, fit, manual, adopted, request, saved, independent: JSON.parse(verification.stdout), state, errors, consoleErrors, httpErrors, assetErrors }
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, directory, assets: assets.size, independent: evidence.independent }))
} catch (error) {
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, errors, consoleErrors, httpErrors, assetErrors,
    diagnostics: page ? await page.evaluate(() => ({ charts: [...(window.__sheetsWebCharts?.store.values() ?? [])].flat(), drafts: Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')), feedback: document.querySelector('.workbook-feedback')?.textContent })).catch(() => null) : null }, null, 2))
  await page?.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally { await browser?.close(); server.kill('SIGTERM'); await writeFile(join(directory, 'server.log'), serverLog) }
