import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { inspectExtractLayout } from './office-pdf-extract-layout.mjs'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const directory = process.env.PDF_EXTRACT_SMOKE_DIRECTORY ?? '/tmp/pdf-extract-built-20261111-final-01'
const port = Number(process.env.PDF_EXTRACT_SMOKE_PORT ?? 4296), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: true })
const manifest = await readFile(join(frontend, '../static/.vite/manifest.json'))
if (process.env.PDF_EXPECTED_MANIFEST_SHA256) assert.equal(sha(manifest), process.env.PDF_EXPECTED_MANIFEST_SHA256)
await writeFile(join(directory, 'build-manifest.json'), manifest)
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/pdf-extract-server.py'), '--directory', directory, '--port', String(port)], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', data => { serverLog += data }); server.stderr.on('data', data => { serverLog += data })
const pageErrors = [], consoleErrors = [], httpErrors = [], checks = [], assets = new Map()
const layout = { cases: [], failures: [] }, checkLayout = process.env.PDF_EXTRACT_LAYOUT === '1'
let releaseExtract
try {
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(`${origin}/__smoke__/state`)).ok) break } catch {}
    assert(attempt < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1550, height: 1100 } })
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (!path.startsWith('/reports/v1/editor/assets/') || !/\.(?:m?js|css)$/.test(path) || response.status() !== 200) return
    checks.push((async () => {
      assert.equal(response.status(), 200)
      const bytes = await response.body(), disk = await readFile(join(frontend, '../static', path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(bytes), sha(disk)); assets.set(path, { sha256:sha(bytes), size:bytes.length })
    })())
  })
  stage = 'open-real-grant'; await page.goto(origin + info.openPath)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3)
  const before = await page.evaluate(() => Object.fromEntries(Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).map(key => [key, localStorage.getItem(key)])))
  stage = 'extract-ribbon'; await page.locator('[data-pdf-ribbon-tab="page"]').click()
  const command = page.locator('[data-source-command-id="genoffice.pdf.page.extract"]')
  assert.equal(await command.isDisabled(), false); await command.click()
  const dialog = page.getByRole('dialog', { name: '提取页面', exact: true })
  await dialog.waitFor({ state: 'visible' })
  assert.match(await dialog.innerText(), /无表单、批注或保护/)
  if (checkLayout) {
    if (!await dialog.getByLabel('提取页码').evaluate(node=>node===document.activeElement)) layout.failures.push('open: 首字段焦点')
    await inspectExtractLayout(page,dialog,directory,'open',layout)
    await dialog.getByLabel('提取页码').fill('0'); await dialog.locator('[data-pdf-extract-apply]').click()
    await page.waitForFunction(()=>document.querySelector('dialog[open] [role=status]')?.textContent.includes('页码'))
    await inspectExtractLayout(page,dialog,directory,'invalid',layout)
    const state=await (await fetch(`${origin}/__smoke__/state`)).json()
    assert.equal(state.requests.filter(request=>request.method==='POST'&&request.path.endsWith('/api/extract-pages')).length,0)
    if(process.env.PDF_EXTRACT_LAYOUT_BASELINE!=='1'){
      await dialog.getByRole('button',{name:'关闭提取页面',exact:true}).click()
      assert.ok(await command.evaluate(node=>node===document.activeElement))
      await command.click();await dialog.getByLabel('提取页码').press('Escape')
      await dialog.waitFor({state:'hidden'});assert.ok(await command.evaluate(node=>node===document.activeElement))
      await command.click();assert.ok(await dialog.getByLabel('提取页码').evaluate(node=>node===document.activeElement))
    }
  }
  await dialog.getByLabel('提取页码').fill('3,1')
  let intercepted
  if (checkLayout) {
    let signal
    const gate=new Promise(resolve=>{releaseExtract=resolve})
    intercepted=new Promise(resolve=>{signal=resolve})
    await page.route('**/api/extract-pages',async route=>{signal();await gate;await route.continue()})
  }
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/extract-pages') && response.request().method() === 'POST')
  await dialog.locator('[data-pdf-extract-apply]').click()
  if (checkLayout) {
    await intercepted
    assert.equal(await dialog.getByLabel('提取页码').isDisabled(),true)
    assert.equal(await dialog.locator('[data-pdf-extract-apply]').isDisabled(),true)
    await inspectExtractLayout(page,dialog,directory,'busy',layout)
    releaseExtract()
  }
  const response = await responsePromise
  assert.equal(response.status(), 200, await response.text())
  const payload = await response.json(), sent = response.request().postDataJSON()
  assert.deepEqual(sent.pages, [3, 1]); assert.equal(sent.expectedSha256, info.sourceSha256)
  assert.equal(payload.revision, 1); assert.equal(payload.parentRevision, null); assert.equal(payload.revisionRegistered, true)
  assert.equal(payload.validation.ok, false); assert(payload.validation.issues.some(issue => issue.code === 'native_validation_pending'))
  await dialog.getByRole('link', { name: '下载提取 PDF', exact: true }).waitFor()
  assert.match(await dialog.innerText(), /验收未通过/)
  assert.equal(await dialog.getByRole('link', { name: '下载提取 PDF', exact: true }).getAttribute('href'), payload.artifacts.pdf.downloadUrl)
  assert.equal(await dialog.getByRole('link', { name: '打开独立文档', exact: true }).getAttribute('href'), payload.editor.openUrl)
  if(checkLayout){
    await inspectExtractLayout(page,dialog,directory,'warning',layout)
    await dialog.getByRole('button',{name:'关闭',exact:true}).click()
    assert.ok(await command.evaluate(node=>node===document.activeElement))
    await command.click();assert.equal(await dialog.getByLabel('提取页码').inputValue(),'3,1')
    assert.equal(await dialog.getByRole('link',{name:'下载提取 PDF',exact:true}).getAttribute('href'),payload.artifacts.pdf.downloadUrl)
    if(process.env.PDF_EXTRACT_LAYOUT_BASELINE!=='1')assert.deepEqual(layout.failures,[])
  }
  assert.deepEqual(await page.evaluate(() => Object.fromEntries(Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).map(key => [key, localStorage.getItem(key)]))), before)
  await page.screenshot({ path: join(directory, 'extracted.png'), fullPage: true })
  stage = 'download-real-pdf'
  const downloadPromise=page.waitForEvent('download')
  await dialog.getByRole('link',{name:'下载提取 PDF',exact:true}).click()
  const download=await downloadPromise,output=await readFile(await download.path())
  assert.equal(output.length, payload.artifacts.pdf.size); assert.equal(sha(output), payload.artifacts.pdf.sha256)
  await writeFile(join(directory, 'downloaded.pdf'), output)
  const verification = spawnSync(join(repo, '.venv/bin/python'), ['-c', 'import json,sys,hashlib;from io import BytesIO;from pypdf import PdfReader;raw=open(sys.argv[1],"rb").read();r=PdfReader(BytesIO(raw));print(json.dumps({"sha256":hashlib.sha256(raw).hexdigest(),"pageTexts":[p.extract_text().strip() for p in r.pages]}))', join(directory, 'downloaded.pdf')], { cwd: repo, encoding: 'utf8' })
  assert.equal(verification.status, 0, verification.stderr)
  const independent = JSON.parse(verification.stdout)
  assert.deepEqual(independent.pageTexts, ['source page three', 'source page one']); assert.equal(independent.sha256, payload.artifacts.pdf.sha256)
  await writeFile(join(directory, 'independent.json'), JSON.stringify(independent, null, 2))
  const state = await (await fetch(`${origin}/__smoke__/state`)).json()
  assert.equal(state.sourceSha256, info.sourceSha256); assert.equal(state.children.length, 1)
  assert.equal(state.children[0].documentId, payload.documentId); assert.equal(state.children[0].source.origin, 'derived')
  assert.equal(state.children[0].source.parentDocumentId, info.context.documentId); assert.equal(state.children[0].source.parentRevision, info.context.revision)
  assert.equal(state.children[0].source.parentSha256, info.sourceSha256)
  stage = 'reopen-derived'; await page.goto(payload.editor.openUrl)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 2)
  const childContext = await page.evaluate(async () => (await fetch(`${location.pathname}/api/context`)).json())
  assert.equal(childContext.context.documentId, payload.documentId); assert.equal(childContext.context.origin, 'derived')
  assert.equal(childContext.context.sourceFile.sha256, payload.artifacts.pdf.sha256)
  assert.equal(childContext.editingEnabled, true)
  await page.screenshot({ path: join(directory, 'reopened.png'), fullPage: true })
  await Promise.all(checks)
  assert.deepEqual(pageErrors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, [])
  assert.deepEqual(await readFile(join(frontend, '../static/.vite/manifest.json')), manifest)
  const finalState = await (await fetch(`${origin}/__smoke__/state`)).json()
  assert.equal(finalState.sourceSha256, info.sourceSha256)
  const extractPosts = finalState.requests.filter(request => request.method === 'POST' && request.path.endsWith('/api/extract-pages'))
  assert.equal(extractPosts.length, 1)
  assert.equal(finalState.requests.some(request => request.method === 'POST' && /\/api\/(save|export)$/.test(request.path)), false)
  const summary = { ok: true, directory, manifestSha256: sha(manifest), browserVersion: browser.version(), sourceSha256: info.sourceSha256,
    scope: 'real browser/grant/cookie/CSRF/engine/publication/download/reopen; in-memory document and grant/artifact repositories; no provider required',
    payload, request: sent, independent, childContext, sourceUnchanged: true, draftUnchanged: true,
    assets: Object.fromEntries(assets), layout, pageErrors, consoleErrors, httpErrors, requests: finalState.requests }
  await writeFile(join(directory, 'summary.json'), JSON.stringify(summary, null, 2))
  console.log(JSON.stringify({ ok: true, directory, assets: assets.size, pages: independent.pageTexts.length }))
} catch (error) {
  if (page) {
    await writeFile(join(directory, 'failure.html'), await page.content()).catch(() => {})
    await page.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {})
  }
  console.error(JSON.stringify({ stage, directory })); throw error
} finally {
  releaseExtract?.()
  await browser?.close()
  server.kill()
  await writeFile(join(directory, 'server.log'), serverLog)
  if (server.exitCode === null) await Promise.race([new Promise(resolve => server.once('exit', resolve)), delay(5000)])
  if (server.exitCode === null) server.kill('SIGKILL')
}
