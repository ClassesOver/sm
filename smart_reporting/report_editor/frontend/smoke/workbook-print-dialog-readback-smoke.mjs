// 只读续验：复用04已签发的真实XLSX，不重跑选项、打印或签发。
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
const directory = process.env.WORKBOOK_PRINT_DIALOG_DIRECTORY, previous = process.env.WORKBOOK_PRINT_DIALOG_RESUME_FROM
const staticDirectory = process.env.PDF_SMOKE_STATIC_DIRECTORY, engineDirectory = process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
assert(directory && previous && staticDirectory && engineDirectory)
const port = Number(process.env.WORKBOOK_PRINT_DIALOG_PORT ?? 4421), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: false })
const source = await readFile(join(previous, 'printed.xlsx')), manifest = await readFile(join(staticDirectory, '.vite/manifest.json')), engine = await readFile(join(engineDirectory, 'dist/cli.mjs'))
const backendPaths = ['smart_reporting/reporting/delivery/office_engine.py', ...['native_office.py', 'native.py', 'native_api.py'].map(name => `smart_reporting/report_editor/${name}`)]
const identities = async () => Object.fromEntries(await Promise.all(backendPaths.map(async path => [path, sha(await readFile(join(repo, path)))])))
const backend = await identities(); assert.deepEqual(backend, JSON.parse(await readFile(join(previous, 'backend-start-identities.json'), 'utf8')))
await writeFile(join(directory, 'backend-start-identities.json'), JSON.stringify(backend, null, 2))
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', directory, '--port', String(port), '--source', join(previous, 'printed.xlsx')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
let serverLog = '', browser, page
server.stdout.on('data', bytes => { serverLog += bytes }); server.stderr.on('data', bytes => { serverLog += bytes })
const errors = [], consoleErrors = [], httpErrors = [], assetErrors = [], checks = [], assets = new Map()
try {
  for (let i = 0; ; i++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })).ok) break } catch {}
    assert(i < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8')); assert.equal(info.sourceSha256, sha(source))
  browser = await chromium.launch({ headless: true }); const preflight = await probeCanvasTextRendering(browser); assert.equal(preflight.ok, true)
  page = await browser.newPage({ viewport: { width: 1760, height: 1100 } })
  const cdp = await page.context().newCDPSession(page); await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(js|css)$/.test(path)) checks.push((async () => {
      const bytes = await response.body(), disk = await readFile(join(staticDirectory, path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(response.status(), 200); assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })().catch(error => assetErrors.push({ path, error: String(error) })))
  })
  await page.goto(origin + info.openPath)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  const loaded = await page.request.get(page.url() + '/api/file'); assert.equal(loaded.status(), 200); assert.equal(sha(await loaded.body()), sha(source))
  await page.locator('[data-ribbon-tab=File]').click(); await page.locator('[data-ribbon-command=print]').click()
  const dialog = page.getByRole('dialog', { name: '打印预览', exact: true }); await dialog.waitFor()
  await page.waitForFunction(() => document.querySelector('[data-print-preview]')?.srcdoc.includes('class="page"') && !document.querySelector('[data-print-submit]')?.disabled, null, { timeout: 60000 })
  for (const [field, value] of [['paper', '13'], ['scale', '70'], ['margins', 'narrow'], ['orientation', 'landscape']]) assert.equal(await dialog.locator(`[data-print-${field}]`).inputValue(), value)
  const preview = await dialog.locator('[data-print-preview]').evaluate(frame => ({ sandbox: frame.getAttribute('sandbox'), html: frame.srcdoc }))
  assert.equal(preview.sandbox, ''); assert(preview.html.includes('Updated')); assert(!preview.html.includes('Never print hidden sheet'))
  await page.screenshot({ path: join(directory, 'readback-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  const mobileActions = {}
  for (const action of ['pdf', 'submit', 'cancel']) {
    await dialog.locator(`[data-print-${action}]`).scrollIntoViewIfNeeded()
    const box = await dialog.locator(`[data-print-${action}]`).boundingBox(); assert(box && box.x >= 0 && box.y >= 0 && box.x + box.width <= 390 && box.y + box.height <= 844)
    mobileActions[action] = box
    await page.screenshot({ path: join(directory, `readback-mobile-${action}.png`), fullPage: true })
  }
  await dialog.locator('[data-print-cancel]').click()
  const draft = await page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? [])); assert.deepEqual(draft, [])
  const verification = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-print-dialog-verify.py'), previous], { cwd: repo, encoding: 'utf8' }); assert.equal(verification.status, 0, verification.stderr || verification.stdout)
  await writeFile(join(directory, 'independent-checkpoint.json'), verification.stdout)
  await Promise.all(checks); assert(assets.size > 0); assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, []); assert.deepEqual(assetErrors, [])
  const backendEnd = await identities(); assert.deepEqual(backendEnd, backend); assert.equal(sha(await readFile(join(staticDirectory, '.vite/manifest.json'))), sha(manifest)); assert.equal(sha(await readFile(join(engineDirectory, 'dist/cli.mjs'))), sha(engine))
  await writeFile(join(directory, 'backend-end-identities.json'), JSON.stringify(backendEnd, null, 2))
  const state = await (await page.request.get(origin + '/__smoke__/state')).json(); assert.equal(state.plannerCalls, 0); assert.equal(state.savedRevisions, 0)
  const evidence = { ok: true, mode: 'zero-save independent authorized reopen of previous downloaded artifact; earlier chain remains separately recorded', previous, browserVersion: browser.version(), preflight,
    artifactSha256: sha(source), manifestSha256: sha(manifest), engineSha256: sha(engine), backendExecution: 'live workspace; start/end identities verified', backend, backendEnd,
    assets: Object.fromEntries(assets), sandbox: preview.sandbox, mobileActions, independent: JSON.parse(verification.stdout), errors, consoleErrors, httpErrors, assetErrors, state }
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, directory, artifactSha256: sha(source), savedRevisions: state.savedRevisions }))
} catch (error) {
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ error: String(error), stack: error.stack, serverLog, errors, consoleErrors, httpErrors, assetErrors }, null, 2))
  await page?.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {}); throw error
} finally { await browser?.close(); server.kill('SIGTERM'); await writeFile(join(directory, 'server.log'), serverLog) }
