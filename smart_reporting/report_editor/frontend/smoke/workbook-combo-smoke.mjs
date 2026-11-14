// 固定源组合图 SelectData：逐系列类型/次轴、真实草稿、撤销重做、保存下载及独立回读。
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
const directory = process.env.WORKBOOK_COMBO_DIRECTORY ?? '/dev/shm/office-next-xlsx-combo-20261113/browser-frozen-01'
const staticDirectory = process.env.PDF_SMOKE_STATIC_DIRECTORY, engineDirectory = process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
assert(staticDirectory && engineDirectory, '必须指定root冻结的静态产物与工作簿桥')
const port = Number(process.env.WORKBOOK_COMBO_PORT ?? 4426), origin = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: false })
const harnessIdentities = {}
for (const name of ['workbook-combo-smoke.mjs', 'workbook-combo-verify.py', 'workbook-ai-charts-server.py', 'pdf_smoke_static.py', 'pdf-form-design-server.py', 'canvas-font-preflight.mjs']) {
  const bytes = await readFile(join(frontend, 'smoke', name)); harnessIdentities[name] = sha(bytes)
  await writeFile(join(directory, 'executed-' + name), bytes)
}
await writeFile(join(directory, 'harness-before-identities.json'), JSON.stringify(harnessIdentities, null, 2))
const manifest = await readFile(join(staticDirectory, '.vite/manifest.json')), engine = await readFile(join(engineDirectory, 'dist/cli.mjs'))
assert(process.env.WORKBOOK_COMBO_BACKEND_MANIFEST, '必须指定本轮104份live后端基线')
const backendBaseline = JSON.parse(await readFile(process.env.WORKBOOK_COMBO_BACKEND_MANIFEST, 'utf8'))
const backendExpected = Object.fromEntries(backendBaseline.map(entry => [entry.path, entry.sha256]))
const backendPaths = Object.keys(backendExpected)
const identities = async () => Object.fromEntries(await Promise.all(backendPaths.map(async path => [path, sha(await readFile(join(repo, path)))])))
const backend = await identities(); await writeFile(join(directory, 'backend-start-identities.json'), JSON.stringify(backend, null, 2))
const backendBaselineMismatches = backendPaths.filter(path => backend[path] !== backendExpected[path]).map(path => ({ path, frozen: backendExpected[path], actual: backend[path] }))
await writeFile(join(directory, 'backend-baseline-mismatches.json'), JSON.stringify(backendBaselineMismatches, null, 2))
const verify = args => spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-combo-verify.py'), directory, ...args], { cwd: repo, encoding: 'utf8' })
const fixture = verify(['--fixture']); assert.equal(fixture.status, 0, fixture.stderr); const fixtureIdentity = JSON.parse(fixture.stdout)
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', directory, '--port', String(port), '--source', join(directory, 'fixture.xlsx')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', bytes => { serverLog += bytes }); server.stderr.on('data', bytes => { serverLog += bytes })
const errors = [], consoleErrors = [], httpErrors = [], assetErrors = [], checks = [], assets = new Map()
try {
  for (let i = 0; ; i++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })).ok) break } catch {}
    assert(i < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8')); assert.equal(info.sourceSha256, fixtureIdentity.sourceSha256)
  browser = await chromium.launch({ headless: true }); const preflight = await probeCanvasTextRendering(browser); assert.equal(preflight.ok, true)
  page = await browser.newPage({ viewport: { width: 1760, height: 1100 }, acceptDownloads: true })
  const cdp = await page.context().newCDPSession(page); await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  page.on('pageerror', error => errors.push(error.message)); page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('dialog', dialog => dialog.type() === 'beforeunload' ? dialog.accept() : dialog.dismiss())
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(js|css)$/.test(path)) checks.push((async () => {
      const bytes = await response.body(), disk = await readFile(join(staticDirectory, path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(response.status(), 200); assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })().catch(error => assetErrors.push({ path, error: String(error) })))
  })
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false' && document.querySelector('#report-editor')?.inert !== true, null, { timeout: 60000 })
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  const dialog = () => page.getByRole('dialog', { name: '选择数据源', exact: true })
  const open = async () => { await page.locator('[data-ribbon-tab="Chart Design"]').click(); await page.locator('[data-ribbon-command="chart-select-data"]').click(); await dialog().waitFor(); await dialog().locator('[data-chart-data-name]').first().waitFor() }
  const rows = () => dialog().locator('[data-chart-data-row]')
  const edits = operations => operations.filter(operation => operation.kind === 'applyChartEdits').flatMap(operation => operation.edits)
  const apply = async count => {
    await dialog().locator('[data-chart-data-submit]').click(); await dialog().waitFor({ state: 'hidden', timeout: 60000 }); await ready()
    assert.equal(edits(await draft()).length, count)
  }
  stage = 'open'; await page.goto(origin + info.openPath); await ready()
  const nameBox = page.locator('[data-u-comp="defined-name"] input')
  stage = 'manual'; await nameBox.fill('J2'); await nameBox.press('Enter'); await page.keyboard.type('Manual combo draft'); await page.keyboard.press('Enter'); await nameBox.fill('J2'); await nameBox.press('Enter')
  await page.locator('[data-ribbon-tab="Home"]').click(); await page.locator('[data-ribbon-command="bold"]').click()
  await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(operation => operation.kind === 'applyCellEdits' && operation.edits.some(edit => edit.row === 1 && edit.column === 9 && edit.style?.bold === true))))
  const manual = await draft()
  stage = 'cancel'; await open(); assert.equal(await rows().count(), 3); await rows().first().locator('[data-chart-data-name]').fill('Discarded'); await dialog().locator('[data-chart-data-cancel]').click(); assert.deepEqual(await draft(), manual)
  await open(); await page.keyboard.press('Escape'); await dialog().waitFor({ state: 'hidden' }); assert.deepEqual(await draft(), manual)
  stage = 'series-edit'; await open()
  assert.deepEqual(await rows().locator('[data-chart-data-plot]').evaluateAll(nodes => nodes.map(node => node.value)), ['barChart', 'barChart', 'lineChart'])
  assert.deepEqual(await rows().locator('[data-chart-data-secondary]').evaluateAll(nodes => nodes.map(node => node.checked)), [false, false, true])
  await rows().nth(0).locator('[data-chart-data-plot]').selectOption('lineChart')
  await rows().nth(1).locator('[data-chart-data-secondary]').check()
  await dialog().locator('[data-chart-data-add]').click()
  await rows().nth(3).locator('[data-chart-data-name]').fill('Added')
  await rows().nth(3).locator('[data-chart-data-values]').fill('E2:E3')
  await rows().nth(3).locator('[data-chart-data-categories]').fill('A2:A3')
  for (let i = 3; i > 0; i--) await rows().nth(i).locator('[data-chart-data-up]').click()
  await page.screenshot({ path: join(directory, 'combo-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 }); await rows().nth(3).locator('[data-chart-data-secondary]').scrollIntoViewIfNeeded()
  const fit = await dialog().locator('.workbook-chart-data-dialog').evaluate(node => { const box = node.getBoundingClientRect(); return { left: box.left, right: box.right, viewport: innerWidth, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth } }); assert(fit.left >= 0 && fit.right <= fit.viewport && fit.scrollWidth <= fit.clientWidth + 1)
  await page.screenshot({ path: join(directory, 'combo-mobile.png'), fullPage: true })
  await dialog().locator('[data-chart-data-submit]').scrollIntoViewIfNeeded(); const mobileSubmit = await dialog().locator('[data-chart-data-submit]').boundingBox()
  assert(mobileSubmit && mobileSubmit.x >= 0 && mobileSubmit.y >= 0 && mobileSubmit.x + mobileSubmit.width <= 390 && mobileSubmit.y + mobileSubmit.height <= 844)
  await page.screenshot({ path: join(directory, 'combo-mobile-submit.png'), fullPage: true }); await apply(1); await page.setViewportSize({ width: 1760, height: 1100 })
  const first = edits(await draft())[0].seriesSet
  assert.deepEqual(first.map(entry => [entry.name, entry.plot, entry.secondaryAxis]), [['Added', 'barChart', false], ['North', 'lineChart', false], ['South', 'barChart', true], ['Rate', 'lineChart', true]])
  assert.equal(first[1].color.toLowerCase(), '#123456'); assert.deepEqual(first[0].values, [7, 9])
  const adopted = await draft(); assert.deepEqual(adopted.filter(operation => operation.kind === 'applyCellEdits'), manual)
  stage = 'undo'; await page.locator('[data-ribbon-tab="File"]').click(); await page.locator('[data-ribbon-command="undo"]').click()
  await page.waitForFunction(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).every(([, value]) => !(JSON.parse(value).operations ?? []).some(operation => operation.kind === 'applyChartEdits'))); await ready(); assert.deepEqual(await draft(), manual)
  stage = 'redo'; await page.locator('[data-ribbon-command="redo"]').click()
  await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(operation => operation.kind === 'applyChartEdits'))); await ready(); assert.deepEqual(await draft(), adopted)
  const readControls = async () => ({ names: await rows().locator('[data-chart-data-name]').evaluateAll(nodes => nodes.map(node => node.value)), plots: await rows().locator('[data-chart-data-plot]').evaluateAll(nodes => nodes.map(node => node.value)), secondary: await rows().locator('[data-chart-data-secondary]').evaluateAll(nodes => nodes.map(node => node.checked)) })
  const expectedControls = { names: ['Added', 'North', 'South', 'Rate'], plots: ['barChart', 'lineChart', 'barChart', 'lineChart'], secondary: [false, false, true, true] }
  stage = 'draft-recovery'; await page.reload(); await ready(); await open(); assert.deepEqual(await readControls(), expectedControls)
  await dialog().locator('[data-chart-data-cancel]').click(); assert.deepEqual(await draft(), adopted)
  stage = 'save'; const waiting = page.waitForResponse(response => response.url().endsWith('/api/save') && response.request().method() === 'POST')
  await page.locator('[data-action="save"]').click(); const response = await waiting, saved = await response.json(), request = response.request().postDataJSON()
  await writeFile(join(directory, 'save-checkpoint.json'), JSON.stringify({ status: response.status(), request, saved }, null, 2))
  assert.equal(response.status(), 200, JSON.stringify(saved)); assert.equal(saved.revisionRegistered, true); assert.equal(saved.parentRevision, info.context.revision); assert.equal(saved.revision, info.context.revision + 1)
  assert.equal(request.expectedSha256, fixtureIdentity.sourceSha256); assert.deepEqual(request.operations, adopted)
  assert.equal(saved.validation.ok, false); assert(saved.validation.issues.some(issue => issue.code === 'native_source_review_pending')); assert(saved.artifacts.xlsx.downloadUrl)
  stage = 'download'; const [download] = await Promise.all([page.waitForEvent('download'), page.locator('[data-action="xlsx-download"]').click()]); await download.saveAs(join(directory, 'combo.xlsx')); assert.equal(await download.failure(), null)
  assert.equal(sha(await readFile(join(directory, 'combo.xlsx'))), saved.artifacts.xlsx.sha256)
  stage = 'reopen'; await page.goto(new URL(saved.editor.openUrl, origin).href); await ready(); await open(); assert.deepEqual(await readControls(), expectedControls)
  await page.screenshot({ path: join(directory, 'series-reopened.png'), fullPage: true }); await dialog().locator('[data-chart-data-cancel]').click()
  const reopened = await page.request.get(page.url() + '/api/file'); assert.equal(reopened.status(), 200); assert.equal(sha(await reopened.body()), saved.artifacts.xlsx.sha256)
  const verification = verify([]); assert.equal(verification.status, 0, verification.stderr || verification.stdout); await writeFile(join(directory, 'independent-checkpoint.json'), verification.stdout)
  await Promise.all(checks); await writeFile(join(directory, 'asset-checkpoint.json'), JSON.stringify(Object.fromEntries(assets), null, 2))
  assert(assets.size > 0); assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, []); assert.deepEqual(assetErrors, [])
  const backendEnd = await identities(); await writeFile(join(directory, 'backend-end-identities.json'), JSON.stringify(backendEnd, null, 2)); assert.deepEqual(backendEnd, backend)
  assert.equal(sha(await readFile(join(staticDirectory, '.vite/manifest.json'))), sha(manifest)); assert.equal(sha(await readFile(join(engineDirectory, 'dist/cli.mjs'))), sha(engine))
  const state = await (await page.request.get(origin + '/__smoke__/state')).json(); assert.equal(state.plannerCalls, 0); assert.equal(state.savedRevisions, 1)
  const evidence = { ok: true, browserVersion: browser.version(), preflight, sourceSha256: fixtureIdentity.sourceSha256, manifestSha256: sha(manifest), engineSha256: sha(engine), harnessIdentities, backendExecution: 'live workspace; start/end identities verified; frozen baseline mismatches reported separately', backend, backendEnd, backendBaselineMismatches,
    assets: Object.fromEntries(assets), fit, mobileSubmit, manual, first, adopted, request, saved, independent: JSON.parse(verification.stdout), state, errors, consoleErrors, httpErrors, assetErrors }
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, directory, independent: evidence.independent }))
} catch (error) {
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, errors, consoleErrors, httpErrors, assetErrors,
    diagnostics: page ? await page.evaluate(() => ({ dialogError: document.querySelector('.workbook-chart-data-dialog [role=alert]')?.textContent, drafts: Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')), feedback: document.querySelector('.workbook-feedback')?.textContent })).catch(() => null) : null }, null, 2))
  await page?.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {}); throw error
} finally { await browser?.close(); server.kill('SIGTERM'); await writeFile(join(directory, 'server.log'), serverLog) }
