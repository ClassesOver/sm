// Frozen production assets, real grant/cookie/CSRF, PDF engine, publication and download.
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const directory = process.env.PDF_FORM_DESIGN_SMOKE_DIRECTORY ?? '/tmp/pdf-form-design-browser-20261111-final01'
const port = Number(process.env.PDF_FORM_DESIGN_SMOKE_PORT ?? 4297), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: true })
const manifest = await readFile(join(frontend, '../static/.vite/manifest.json'))
await writeFile(join(directory, 'build-manifest.json'), manifest)
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/pdf-form-design-server.py'), '--directory', directory, '--port', String(port)], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', data => { serverLog += data }); server.stderr.on('data', data => { serverLog += data })
const pageErrors = [], consoleErrors = [], httpErrors = [], checks = [], assets = new Map()
try {
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(`${origin}/__smoke__/state`)).ok) break } catch {}
    assert(attempt < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1500, height: 1100 } })
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (!path.startsWith('/reports/v1/editor/assets/') || !path.endsWith('.js')) return
    checks.push((async () => {
      const bytes = await response.body(), disk = await readFile(join(frontend, '../static', path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })())
  })
  stage = 'open-real-grant'; await page.goto(origin + info.openPath)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  await page.locator('[data-pdf-ribbon-tab="formDesign"]').click()
  const command = page.locator('[data-source-command-id="genoffice.pdf.formDesign.deleteField"]')
  await command.waitFor(); assert.equal(await command.isDisabled(), false); await command.click()
  const panel = page.locator('.pdf-form-design-panel')
  await panel.waitFor({ state: 'visible' })
  assert.match(await panel.innerText(), /remove_me/)
  await panel.screenshot({ path: join(directory, 'candidate.png') })
  const operations = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations)
  assert.deepEqual(await operations(), [])
  stage = 'stage-undo-redo'
  await panel.locator('li').filter({ hasText: 'remove_me' }).locator('[data-pdf-form-widget-remove]').click()
  await page.waitForFunction(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations.length === 1)
  const staged = await operations(); assert.equal(staged[0].kind, 'removeFormWidget'); assert.equal(staged[0].fieldName, 'remove_me'); assert.equal(staged[0].sourceSha256, info.sourceSha256)
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click()
  assert.deepEqual(await operations(), [])
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click()
  assert.deepEqual(await operations(), staged)
  await panel.getByRole('button', { name: '关闭字段设计', exact: true }).click()
  stage = 'real-preview'
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  await page.getByRole('button', { name: '校验当前修改', exact: true }).click()
  await page.locator('.pdf-preview-review input[type="checkbox"]').waitFor({ state: 'visible' })
  await page.locator('.pdf-preview-review input[type="checkbox"]').check()
  await page.screenshot({ path: join(directory, 'preview.png'), fullPage: true })
  stage = 'save-publication'
  const saving = page.waitForResponse(response => response.url().endsWith('/api/save') && response.request().method() === 'POST')
  await page.locator('[data-action="save"]').click()
  const saved = await saving, payload = await saved.json()
  assert.equal(saved.status(), 200, JSON.stringify(payload)); assert.equal(payload.revisionRegistered, true)
  assert.equal(payload.parentRevision, 4); assert.equal(payload.revision, 5)
  assert.deepEqual(saved.request().postDataJSON().operations, staged)
  const downloadLink = page.locator('.native-delivery a').filter({ hasText: '下载 PDF' })
  await downloadLink.waitFor(); assert.equal(await downloadLink.getAttribute('href'), payload.artifacts.pdf.downloadUrl)
  stage = 'download-pypdf'
  const downloaded = await page.request.get(payload.artifacts.pdf.downloadUrl)
  assert.equal(downloaded.status(), 200)
  const bytes = await downloaded.body(); assert.equal(sha(bytes), payload.artifacts.pdf.sha256); assert.equal(bytes.length, payload.artifacts.pdf.size)
  await writeFile(join(directory, 'downloaded.pdf'), bytes)
  const verification = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import json,sys,hashlib
from pypdf import PdfReader
source=PdfReader(sys.argv[1]);output=PdfReader(sys.argv[2])
assert set(source.get_fields())=={'keep','remove_me'}
assert set(output.get_fields())=={'keep'}
assert len(output.pages)==len(source.pages)==1
assert output.pages[0].extract_text()==source.pages[0].extract_text()
refs=output.pages[0]['/Annots'];assert len(refs)==1
assert all(ref.get_object()['/Subtype']=='/Widget' for ref in refs)
assert refs[0].get_object()['/Parent'].get_object()['/T']=='keep'
print(json.dumps({'fields':list(output.get_fields()),'validWidgetCount':len(refs),'bodyPreserved':True,'sourceSha256':hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest(),'outputSha256':hashlib.sha256(open(sys.argv[2],'rb').read()).hexdigest()}))
`, join(directory, 'source.pdf'), join(directory, 'downloaded.pdf')], { cwd: repo, encoding: 'utf8' })
  assert.equal(verification.status, 0, verification.stderr)
  const independent = JSON.parse(verification.stdout); assert.equal(independent.sourceSha256, info.sourceSha256)
  await writeFile(join(directory, 'independent.json'), JSON.stringify(independent, null, 2))
  stage = 'reopen'
  await page.goto(payload.editor.openUrl)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  const reopened = await page.evaluate(async () => (await fetch(`${location.pathname}/api/context`)).json())
  assert.equal(reopened.context.revision, 5); assert.equal(reopened.context.sourceFile.sha256, payload.artifacts.pdf.sha256)
  await page.locator('[data-pdf-ribbon-tab="formDesign"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.formDesign.deleteField"]').click()
  assert.match(await panel.innerText(), /keep/); assert.doesNotMatch(await panel.innerText(), /remove_me/)
  await page.screenshot({ path: join(directory, 'reopened.png'), fullPage: true })
  await Promise.all(checks)
  assert.deepEqual(pageErrors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, [])
  assert.deepEqual(await readFile(join(frontend, '../static/.vite/manifest.json')), manifest)
  const state = await (await fetch(`${origin}/__smoke__/state`)).json()
  assert.equal(state.sourceSha256, info.sourceSha256); assert.equal(state.savedRevisions, 1)
  const summary = { ok: true, directory, scope: 'real browser/production assets/PDF.js/grant/cookie/CSRF/packed engine/publication/download/reopen; shared in-memory document/grant/artifact repositories; no HTTP substitutes', browserVersion: browser.version(), manifestSha256: sha(manifest), sourceSha256: info.sourceSha256, payload, staged, reopened, independent, sourceUnchanged: true, assets: Object.fromEntries(assets), pageErrors, consoleErrors, httpErrors, requests: state.requests }
  await writeFile(join(directory, 'summary.json'), JSON.stringify(summary, null, 2)); console.log(JSON.stringify({ ok: true, directory }))
} catch (error) {
  await page?.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {})
  if (page) await page.content().then(html => writeFile(join(directory, 'failure.html'), html)).catch(() => {})
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ stage, error: String(error), pageErrors, consoleErrors, httpErrors }, null, 2))
  throw error
} finally {
  await browser?.close(); server.kill()
  await writeFile(join(directory, 'server.log'), serverLog)
  if (server.exitCode === null) await Promise.race([new Promise(resolve => server.once('exit', resolve)), delay(5000)])
  if (server.exitCode === null) server.kill('SIGKILL')
}
