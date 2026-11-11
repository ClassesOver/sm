import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { verifyBrowserTextInput } from './browser-input-preflight.mjs'

// This is an explicit authorization/CSRF route fixture, not a live-service authorization test.
// Preview, rendering, save and downloaded-file inspection run the real Python/OOXML engine.
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(frontend, '../../..')
const staticRoot = process.env.PPTX_STATIC_ROOT ? resolve(process.env.PPTX_STATIC_ROOT) : resolve(frontend, '../static')
const output = resolve(process.env.PPTX_SMOKE_EVIDENCE_DIR ?? '/tmp/pptx-notes-smoke')
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestSha256 = sha(await readFile(resolve(staticRoot, '.vite/manifest.json')))
if (process.env.PPTX_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.PPTX_EXPECTED_MANIFEST_SHA256)
const port = Number(process.env.PPTX_SMOKE_PORT ?? 4202)
const stage = message => console.log(`${new Date().toISOString()} ${message}`)
const base = `http://127.0.0.1:${port}`
const contentType = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
const python = payload => {
  stage(`Python ${payload.mode} start`)
  const result = spawnSync(resolve(repo, '.venv/bin/python'), [resolve(frontend, 'smoke/pptx-notes-fixture.py')], {
    cwd: repo, env: { ...process.env, PYTHONPATH: repo, MPLCONFIGDIR: '/tmp/pptx-notes-mpl' }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 60 * 1024 * 1024, timeout: 180000, stdio: ['pipe', 'pipe', 'inherit'],
  })
  if (result.status !== 0) throw new Error(result.stderr || `fixture Python exited ${result.status}`)
  stage(`Python ${payload.mode} end`)
  return JSON.parse(result.stdout)
}
stage('Creating real three-slide notes fixture')
const fixture = python({ mode: 'create' })
stage('Fixture created; independent source readback')
const sourceBytes = Buffer.from(fixture.bytes, 'base64'), sourceSha = sha(sourceBytes)
await mkdir(output, { recursive: true })
await writeFile(resolve(output, 'source.pptx'), sourceBytes)
const sourceIndependent = python({ mode: 'independent', bytes: fixture.bytes })
let activeBytes = sourceBytes, activeRevision = 1, activeSha = sourceSha
let savedBytes, savedPayload, saveReceipt
const pageErrors = [], failedResponses = [], consoleErrors = [], routeErrors = [], runtimeEvents = [], runtimeJavaScript = new Map(), identityReads = []
assert.deepEqual(fixture.model.slides.map(slide => slide.notesText), ['已有备注\n第二行', '', ''])
assert.ok(fixture.model.slides.every(slide => slide.notesEditable === true))
const downloads = new Map()
const saves = []
const server = spawn(resolve(frontend, 'node_modules/.bin/vite'), ['preview', '--outDir', staticRoot, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser, page
try {
  let reachable = false
  for (let attempt = 0; attempt < 120; attempt++) {
    try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`, { signal: AbortSignal.timeout(500) })).ok) { reachable = true; break } } catch {}
    await delay(250)
  }
  assert.ok(reachable, 'Static Vite preview server is unreachable (check sandbox local binding)')
  stage('Static preview ready; launching Chromium')
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  browser.on('disconnected', () => { runtimeEvents.push({ event: 'browser-disconnected', time: new Date().toISOString() }); stage('Browser disconnected') })
  const inputBaseline = await verifyBrowserTextInput(browser)
  stage('Chromium text input preflight passed')
  page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true })
  page.on('close', () => { runtimeEvents.push({ event: 'page-close', time: new Date().toISOString() }); stage('Page closed') })
  page.on('crash', () => { runtimeEvents.push({ event: 'page-crash', time: new Date().toISOString() }); stage('Page crashed') })
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) failedResponses.push({ path, status: response.status() })
    if (response.ok() && path.endsWith('.js')) identityReads.push((async () => {
      const bytes = await response.body()
      const relative = path.slice('/reports/v1/editor/assets/'.length)
      assert.ok(!relative.includes('..') && path.startsWith('/reports/v1/editor/assets/'))
      const fileBytes = await readFile(resolve(staticRoot, relative))
      assert.equal(sha(bytes), sha(fileBytes), `browser JavaScript identity ${path}`)
      runtimeJavaScript.set(path, { path, size: bytes.length, sha256: sha(bytes) })
    })().catch(error => { routeErrors.push(error.stack ?? String(error)) }))
  })
  const route = (pattern, handler) => page.route(pattern, async request => {
    try { await handler(request) }
    catch (error) { routeErrors.push(error.stack ?? String(error)); await request.fulfill({ status: 500, body: String(error) }) }
  })
  await route('**/favicon.ico', request => request.fulfill({ body: '', status: 200 }))
  await route('**/reports/v1/native/fixture-notes/*/api/context', request => request.fulfill({ json: {
    context: { documentId: 'fixture-notes', format: 'pptx', revision: activeRevision, parentRevision: activeRevision === 1 ? null : activeRevision - 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'notes.pptx', size: activeBytes.length, sha256: activeSha, mediaType: contentType }, origin: 'upload' },
    csrfToken: 'notes-fixture-csrf', capabilities: { pptx_editor: true }, editingEnabled: true, aiEnabled: false,
  } }))
  await route('**/reports/v1/native/fixture-notes/*/api/file', request => request.fulfill({ body: activeBytes, contentType }))
  // The auxiliary PDF iframe is a valid placeholder fixture; visual PPTX rendering below uses the real render-tree bridge.
  await route('**/reports/v1/native/fixture-notes/*/api/preview.pdf*', request => request.fulfill({ body: Buffer.from(fixture.previewPdf, 'base64'), contentType: 'application/pdf', headers: { 'Content-Disposition': 'attachment; filename="fixture-preview.pdf"' } }))
  for (const endpoint of ['preview', 'render-tree']) await route(`**/reports/v1/native/fixture-notes/*/api/${endpoint}`, async request => {
    const payload = request.request().postDataJSON()
    assert.equal(payload.expectedSha256, activeSha)
    assert.equal(request.request().headers()['x-csrf-token'], 'notes-fixture-csrf')
    const result = python({ mode: endpoint === 'render-tree' ? 'render' : 'inspect', bytes: activeBytes.toString('base64'), operations: payload.operations })
    await request.fulfill({ json: endpoint === 'render-tree' ? result : { sourceSha256: activeSha, draftSha256: result.sha256, model: result.model } })
  })
  await route('**/reports/v1/native/fixture-notes/*/api/save', async request => {
    savedPayload = request.request().postDataJSON()
    assert.equal(request.request().headers()['x-csrf-token'], 'notes-fixture-csrf')
    assert.equal(savedPayload.expectedSha256, activeSha)
    savedBytes = Buffer.from(python({ mode: 'patch', bytes: activeBytes.toString('base64'), operations: savedPayload.operations }).bytes, 'base64')
    const revision = activeRevision + 1, url = '/notes-download-' + revision + '.pptx'
    downloads.set(url, savedBytes)
    saveReceipt = { documentId: 'fixture-notes', revision, parentRevision: activeRevision, revisionRegistered: true,
      artifacts: { pptx: { downloadUrl: url, size: savedBytes.length, sha256: sha(savedBytes) } },
      editor: { openUrl: '/reports/v1/native/fixture-notes/' + revision }, validation: { ok: true, issues: [] } }
    saves.push({ payload: savedPayload, receipt: saveReceipt })
    await request.fulfill({ json: saveReceipt })
  })
  await route('**/notes-download-*.pptx', request => request.fulfill({ body: downloads.get(new URL(request.request().url()).pathname), contentType }))
  await page.addInitScript(() => {
    if (!location.href.startsWith('http') || window.top !== window || !location.pathname.endsWith('/native.html')) return
    history.replaceState(null, '', `/reports/v1/native/fixture-notes/${new URL(location.href).searchParams.get('smokeRevision') ?? 1}`)
  })
  const open = async (revision = 1) => {
    await page.goto(`${base}/reports/v1/editor/assets/native.html?smokeRevision=${revision}`)
    await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
    await page.waitForFunction(() => document.querySelector('.canvas-status')?.textContent.includes('点击对象选择'), null, { timeout: 60000 })
  }
  const draft = () => page.evaluate(() => {
    const entry = Object.keys(localStorage).find(key => key.startsWith('native-editor-draft:'))
    return entry ? JSON.parse(localStorage.getItem(entry)).operations : []
  })
  const waitDraft = async predicate => {
    for (let attempt = 0; attempt < 100; attempt++) {
      const operations = await draft()
      if (predicate(operations[0] ?? {})) return operations
      await delay(100)
    }
    throw new Error(`draft condition timed out: ${JSON.stringify(await draft())}`)
  }
  let independentBefore = sourceIndependent
  const partsPreserved = (independent, adding) => {
    for (const [path, digest] of Object.entries(independentBefore.zip)) {
      assert.ok(path in independent.zip, path)
      if (path.startsWith('ppt/notesSlides/')) continue
      if (adding && ['[Content_Types].xml', 'ppt/slides/_rels/slide2.xml.rels', 'ppt/presentation.xml', 'ppt/_rels/presentation.xml.rels'].includes(path)) continue
      assert.equal(independent.zip[path], digest, path)
    }
    for (const path of Object.keys(independent.zip)) {
      if (!(path in independentBefore.zip)) assert.ok(adding && path.startsWith('ppt/notesSlides/'), 'unexpected new part ' + path)
    }
    independentBefore = independent
  }
  const saveAndOpen = async (adding = true, expectedNotes = null) => {
    const operations = await draft()
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存', null, { timeout: 60000 })
    if (expectedNotes === null) assert.deepEqual(savedPayload.operations, operations)
    else assert.deepEqual(savedPayload.operations[0].notesEdits, expectedNotes)
    const issued = await page.getByRole('link', { name: '下载 PPTX', exact: true }).getAttribute('href')
    assert.equal(issued, saveReceipt.artifacts.pptx.downloadUrl)
    const result = await page.evaluate(async url => {
      const response = await fetch(url)
      return { status: response.status, bytes: Array.from(new Uint8Array(await response.arrayBuffer())) }
    }, issued)
    assert.equal(result.status, 200)
    const bytes = Buffer.from(result.bytes)
    assert.equal(sha(bytes), saveReceipt.artifacts.pptx.sha256)
    assert.equal(bytes.length, saveReceipt.artifacts.pptx.size)
    const independent = python({ mode: 'independent', bytes: bytes.toString('base64') })
    partsPreserved(independent, adding)
    await writeFile(resolve(output, 'revision-' + saveReceipt.revision + '.pptx'), bytes)
    activeBytes = bytes; activeSha = sha(bytes); activeRevision = saveReceipt.revision
    await open(activeRevision)
    assert.deepEqual(await draft(), [])
    return { bytes, independent, model: python({ mode: 'inspect', bytes: bytes.toString('base64') }).model }
  }
  const firstText = '  中文😀 $& & < > 字面&#10;\n\n来源零备注  '
  const secondText = '新页备注\n内部空行\n\n结束😀'
  const notesBySource = independent => Object.fromEntries(independent.slides.map(slide => [slide.sourceText, slide.notesText]))
  const showNotes = async () => {
    if (!await page.locator('[data-notes-panel]').isVisible()) {
      await page.locator('[data-ribbon-tab="view"]').click()
      await page.locator('[data-command="notes"]').click()
    }
    await page.locator('[data-notes-text]').waitFor()
  }
  await open()
  stage('Editing existing page notes and switching page directly without explicit blur')
  await showNotes()
  assert.equal(await page.locator('[data-notes-text]').inputValue(), '已有备注\n第二行')
  await page.locator('[data-notes-text]').fill(firstText)
  await page.locator('.slide-open[data-slide-index="1"]').click()
  await showNotes()
  assert.equal(await page.locator('[data-notes-text]').inputValue(), '')
  await page.locator('[data-notes-text]').fill(secondText)
  const edited = await waitDraft(op => op.notesEdits?.some(item => item.slideIndex === 0 && item.text === firstText)
    && op.notesEdits?.some(item => item.slideIndex === 1 && item.text === secondText))
  stage('Undoing, redoing and refreshing notes drafts')
  await page.locator('[data-source-action="onUndo"]').click()
  await waitDraft(op => !op.notesEdits?.some(item => item.slideIndex === 1))
  await page.locator('[data-source-action="onRedo"]').click()
  assert.deepEqual(await draft(), edited)
  await open()
  assert.deepEqual(await draft(), edited)
  await showNotes()
  assert.equal(await page.locator('[data-notes-text]').inputValue(), firstText)
  await page.locator('.slide-open[data-slide-index="1"]').click(); await showNotes()
  assert.equal(await page.locator('[data-notes-text]').inputValue(), secondText)
  stage('Moving the ordinary third page before edited sources')
  const thirdRow = () => page.locator('.slide-row').filter({has: page.locator('.slide-open[data-slide-index="2"]')})
  await thirdRow().getByRole('button', {name: '上移页面', exact: true}).click()
  await thirdRow().getByRole('button', {name: '上移页面', exact: true}).click()
  await waitDraft(op => JSON.stringify(op.order) === '[2,0,1]')
  await page.getByText('第 2 页 · 演讲者备注', {exact: true}).waitFor()
  await page.getByText('第 3 页 · 演讲者备注', {exact: true}).waitFor()
  await page.screenshot({path: resolve(output, 'notes-before-save.png'), fullPage: true})
  const saved = await saveAndOpen()
  assert.equal(activeRevision, 2)
  assert.deepEqual(saved.independent.slides.map(slide => slide.sourceText), ['来源 2', '来源 0', '来源 1'])
  assert.deepEqual(notesBySource(saved.independent), {'来源 2': '', '来源 0': firstText, '来源 1': secondText})
  assert.deepEqual(saved.model.slides.map(slide => slide.notesText), ['', firstText, secondText])
  stage('Clearing saved source notes and saving immediately without explicit blur')
  await page.locator('.slide-open[data-slide-index="1"]').click(); await showNotes()
  assert.equal(await page.locator('[data-notes-text]').inputValue(), firstText)
  await page.locator('[data-notes-text]').fill('')
  const cleared = await saveAndOpen(false, [{slideIndex: 1, text: ''}])
  assert.equal(activeRevision, 3)
  assert.deepEqual(notesBySource(cleared.independent), {'来源 2': '', '来源 0': '', '来源 1': secondText})
  assert.deepEqual(cleared.model.slides.map(slide => slide.notesText), ['', '', secondText])
  await page.locator('.slide-open[data-slide-index="1"]').click(); await showNotes()
  assert.equal(await page.locator('[data-notes-text]').inputValue(), '')
  await page.screenshot({path: resolve(output, 'notes-cleared-reopened.png'), fullPage: true})
  assert.equal(saves.length, 2)
  await Promise.all(identityReads)
  assert.deepEqual(pageErrors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(routeErrors, []); assert.deepEqual(failedResponses, [])
  assert.equal(sha(await readFile(resolve(staticRoot, '.vite/manifest.json'))), manifestSha256)
  const evidence = {ok: true, authorization: 'explicit route fixture; production auth is not exercised',
    pdfPreview: 'valid attachment placeholder; PDF conversion and native PDF plugin are not exercised',
    engine: 'real Python inspect/patch/render and independent python-pptx/ZIP readback',
    manifestSha256, runtimeJavaScript: [...runtimeJavaScript.values()], sourceSha256: sourceSha,
    revision: activeRevision, saves, saved: saved.independent, cleared: cleared.independent,
    pageErrors, consoleErrors, routeErrors, failedResponses, runtimeEvents, inputBaseline}
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ok: true, output, revision: activeRevision, manifestSha256, runtimeJavaScript: runtimeJavaScript.size}))

} catch (error) {
  const body = await page?.locator('body').innerText().catch(() => '')
  throw new Error(`${error.stack ?? error}\n${JSON.stringify({ body: body?.slice(-6000), pageErrors, consoleErrors, routeErrors, failedResponses, runtimeEvents })}`)
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
