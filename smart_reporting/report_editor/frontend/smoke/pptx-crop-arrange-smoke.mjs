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
const output = resolve(process.env.PPTX_SMOKE_EVIDENCE_DIR ?? '/tmp/pptx-crop-arrange-smoke')
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestSha256 = sha(await readFile(resolve(staticRoot, '.vite/manifest.json')))
if (process.env.PPTX_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.PPTX_EXPECTED_MANIFEST_SHA256)
const port = Number(process.env.PPTX_SMOKE_PORT ?? 4198)
const stage = message => console.log(`${new Date().toISOString()} ${message}`)
const base = `http://127.0.0.1:${port}`
const contentType = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
const python = payload => {
  stage(`Python ${payload.mode} start`)
  const result = spawnSync(resolve(repo, '.venv/bin/python'), [resolve(frontend, 'smoke/pptx-crop-arrange-fixture.py')], {
    cwd: repo, env: { ...process.env, PYTHONPATH: repo, MPLCONFIGDIR: '/tmp/pptx-crop-arrange-mpl' }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 60 * 1024 * 1024, timeout: 180000, stdio: ['pipe', 'pipe', 'inherit'],
  })
  if (result.status !== 0) throw new Error(result.stderr || `fixture Python exited ${result.status}`)
  stage(`Python ${payload.mode} end`)
  return JSON.parse(result.stdout)
}
stage('Creating real two-slide fixture')
const fixture = python({ mode: 'create' })
stage('Fixture created; independent source readback')
const sourceBytes = Buffer.from(fixture.bytes, 'base64'), sourceSha = sha(sourceBytes)
await mkdir(output, { recursive: true })
await writeFile(resolve(output, 'source.pptx'), sourceBytes)
const sourceIndependent = python({ mode: 'independent', bytes: fixture.bytes })
let activeBytes = sourceBytes, activeRevision = 1, activeSha = sourceSha
let savedBytes, savedPayload, saveReceipt
const pageErrors = [], failedResponses = [], consoleErrors = [], routeErrors = [], runtimeEvents = [], runtimeJavaScript = new Map(), identityReads = []
const sourcePicture = fixture.model.slides[0].elements.find(element => element.type === 'picture')
const sourceShapes = fixture.model.slides[0].elements.filter(element => element.name.startsWith('Arrange '))
assert.ok(sourcePicture?.pictureReplaceable)
assert.equal(sourceShapes.length, 3)
assert.ok(sourcePicture.pictureCropEditable)
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
  await route('**/reports/v1/native/fixture-crop-arrange/*/api/context', request => request.fulfill({ json: {
    context: { documentId: 'fixture-crop-arrange', format: 'pptx', revision: activeRevision, parentRevision: activeRevision === 1 ? null : 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'crop-arrange.pptx', size: activeBytes.length, sha256: activeSha, mediaType: contentType }, origin: 'upload' },
    csrfToken: 'crop-arrange-fixture-csrf', capabilities: { pptx_editor: true }, editingEnabled: true, aiEnabled: false,
  } }))
  await route('**/reports/v1/native/fixture-crop-arrange/*/api/file', request => request.fulfill({ body: activeBytes, contentType }))
  // The auxiliary PDF iframe is a valid placeholder fixture; visual PPTX rendering below uses the real render-tree bridge.
  await route('**/reports/v1/native/fixture-crop-arrange/*/api/preview.pdf*', request => request.fulfill({ body: Buffer.from(fixture.previewPdf, 'base64'), contentType: 'application/pdf', headers: { 'Content-Disposition': 'attachment; filename="fixture-preview.pdf"' } }))
  for (const endpoint of ['preview', 'render-tree']) await route(`**/reports/v1/native/fixture-crop-arrange/*/api/${endpoint}`, async request => {
    const payload = request.request().postDataJSON()
    assert.equal(payload.expectedSha256, activeSha)
    assert.equal(request.request().headers()['x-csrf-token'], 'crop-arrange-fixture-csrf')
    const result = python({ mode: endpoint === 'render-tree' ? 'render' : 'inspect', bytes: activeBytes.toString('base64'), operations: payload.operations })
    await request.fulfill({ json: endpoint === 'render-tree' ? result : { sourceSha256: activeSha, draftSha256: result.sha256, model: result.model } })
  })
  await route('**/reports/v1/native/fixture-crop-arrange/1/api/save', async request => {
    savedPayload = request.request().postDataJSON()
    assert.equal(request.request().headers()['x-csrf-token'], 'crop-arrange-fixture-csrf')
    assert.equal(savedPayload.expectedSha256, sourceSha)
    savedBytes = Buffer.from(python({ mode: 'patch', bytes: fixture.bytes, operations: savedPayload.operations }).bytes, 'base64')
    saveReceipt = { documentId: 'fixture-crop-arrange', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { pptx: { downloadUrl: '/crop-arrange-download.pptx', size: savedBytes.length, sha256: sha(savedBytes) } },
      editor: { openUrl: '/reports/v1/native/fixture-crop-arrange/2' }, validation: { ok: true, issues: [] } }
    await request.fulfill({ json: saveReceipt })
  })
  await route('**/crop-arrange-download.pptx', request => request.fulfill({ body: savedBytes, contentType }))
  await page.addInitScript(() => {
    if (!location.href.startsWith('http') || window.top !== window || !location.pathname.endsWith('/native.html')) return
    history.replaceState(null, '', `/reports/v1/native/fixture-crop-arrange/${new URL(location.href).searchParams.get('smokeRevision') === '2' ? 2 : 1}`)
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
  await open()
  stage('Revision 1 loaded; dragging the source crop handle')
  await page.locator('#object-select').selectOption(sourcePicture.id)
  await page.locator('[data-ribbon-tab="pictureFormat"]').click()
  await page.locator('[data-command="cropPicture"]').click()
  const west = page.locator('.crop-handle').nth(7)
  await west.waitFor({ state: 'visible' })
  const handle = await west.boundingBox()
  assert.ok(handle)
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
  await page.mouse.down()
  await page.mouse.move(handle.x + handle.width / 2 + 36, handle.y + handle.height / 2, { steps: 8 })
  await page.mouse.up()
  await page.keyboard.press('Enter')
  await waitDraft(operation => operation.pictureCrops?.length === 1 && operation.pictureCrops[0].srcRect?.l > 0)
  const cropDraft = await draft()
  assert.equal(cropDraft[0].pictureCrops[0].expectedSha256, sourcePicture.pictureSha256)
  await page.locator('[data-source-action="onUndo"]').click()
  await waitDraft(operation => !operation.pictureCrops?.length)
  await page.locator('[data-source-action="onRedo"]').click()
  await waitDraft(operation => operation.pictureCrops?.length === 1)
  assert.deepEqual(await draft(), cropDraft, 'crop undo/redo restores crop and frame as one transaction')
  stage('Crop undo/redo passed; selecting three objects through native checkboxes')
  await page.locator('#object-select').selectOption(sourceShapes[0].id)
  for (const shape of sourceShapes) await page.locator(`[data-arrange-object="${shape.id}"]`).check()
  await page.locator('[data-ribbon-tab="home"]').click()
  await page.locator('[data-command="alignTop"]').click()
  await waitDraft(operation => operation.edits?.filter(edit => edit.geometry).length === 2)
  const alignedDraft = await draft()
  assert.deepEqual(alignedDraft[0].pictureCrops, cropDraft[0].pictureCrops)
  await page.locator('[data-command="distributeHorizontal"]').click()
  await waitDraft(operation => {
    const frame = operation.edits?.find(edit => edit.elementId === sourceShapes[1].id)?.geometry
    return frame && frame.x !== sourceShapes[1].geometry.x
  })
  const completeDraft = await draft()
  await page.locator('[data-source-action="onUndo"]').click()
  assert.deepEqual(await draft(), alignedDraft, 'one Undo restores only the batch arrangement and keeps crop')
  await page.locator('[data-source-action="onRedo"]').click()
  assert.deepEqual(await draft(), completeDraft)
  await mkdir(output, { recursive: true })
  await writeFile(resolve(output, 'draft-checkpoint.json'), JSON.stringify({ completed: false, stage: 'before-reload', sourceSha256: sourceSha, operations: completeDraft, manifestSha256 }, null, 2))
  stage('Crop, arrange and single-step Undo/Redo passed; reloading draft')
  await open()
  assert.deepEqual(await draft(), completeDraft, 'reload restores the entire operation')
  assert.equal(await page.locator('[data-source-action="onUndo"]').isDisabled(), true)
  await mkdir(output, { recursive: true })
  await page.screenshot({ path: resolve(output, 'before-save.png'), fullPage: true })
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存', null, { timeout: 60000 })
  assert.deepEqual(savedPayload.operations, completeDraft)
  stage('Real Python save completed; downloading issued artifact')
  const issuedDownloadUrl = await page.getByRole('link', { name: '下载 PPTX', exact: true }).getAttribute('href')
  assert.equal(issuedDownloadUrl, saveReceipt.artifacts.pptx.downloadUrl)
  const download = await page.evaluate(async url => {
    const response = await fetch(url)
    return { status: response.status, bytes: Array.from(new Uint8Array(await response.arrayBuffer())) }
  }, issuedDownloadUrl)
  assert.equal(download.status, 200)
  const downloaded = Buffer.from(download.bytes)
  assert.equal(sha(downloaded), saveReceipt.artifacts.pptx.sha256)
  assert.equal(downloaded.length, saveReceipt.artifacts.pptx.size)
  assert.equal(sha(sourceBytes), sourceSha)
  const independent = python({ mode: 'independent', bytes: downloaded.toString('base64') })
  assert.equal(independent.slides.length, 2)
  const sourceImage = sourceIndependent.slides[0].pictures[0]
  const croppedImage = independent.slides[0].pictures[0]
  assert.equal(croppedImage.sha256, sourceImage.sha256, 'non-destructive crop leaves the bitmap unchanged')
  const crop = completeDraft[0].pictureCrops[0]
  for (const side of ['l', 't', 'r', 'b']) assert.ok(Math.abs(croppedImage.srcRect[side] - (crop.srcRect?.[side] ?? 0)) <= .000011)
  for (const [index, value] of ['x', 'y', 'width', 'height'].entries()) assert.ok(Math.abs(croppedImage.geometry[index] - Math.round(crop.geometry[value] * 9525)) <= 1)
  const shapes = sourceShapes.map(source => independent.slides[0].shapes.find(shape => shape.name === source.name))
  assert.ok(shapes.every(shape => shape.geometry[1] === 70 * 9525), 'alignTop uses the minimum top across the three selected shapes')
  const gaps = [shapes[1].geometry[0] - shapes[0].geometry[0] - shapes[0].geometry[2], shapes[2].geometry[0] - shapes[1].geometry[0] - shapes[1].geometry[2]]
  assert.ok(Math.abs(gaps[0] - gaps[1]) <= 1, 'horizontal distribution leaves equal edge-to-edge gaps')
  assert.deepEqual(shapes.map(shape => shape.text), ['First shape', 'Second shape', 'Third shape'])
  assert.deepEqual(independent.slides[1], sourceIndependent.slides[1])
  for (const [path, digest] of Object.entries(sourceIndependent.zip)) {
    if (path !== 'ppt/slides/slide1.xml') assert.equal(independent.zip[path], digest, `untouched part ${path}`)
  }
  activeBytes = downloaded; activeSha = sha(downloaded); activeRevision = 2
  stage('Independent download readback passed; opening revision 2')
  await open(2)
  const reopened = python({ mode: 'inspect', bytes: downloaded.toString('base64') }).model
  const reopenedPicture = reopened.slides[0].elements.find(element => element.type === 'picture')
  assert.equal(reopenedPicture.pictureSha256, sourcePicture.pictureSha256)
  assert.ok(reopenedPicture.srcRect.l > 0)
  await page.locator('#object-select').selectOption(reopenedPicture.id)
  await page.locator('[data-ribbon-tab="pictureFormat"]').click()
  await page.locator('[data-command="cropPicture"]').click()
  await page.locator('.crop-frame').waitFor({ state: 'visible' })
  await page.keyboard.press('Escape')
  await page.locator('.crop-overlay').waitFor({ state: 'detached' })
  await page.screenshot({ path: resolve(output, 'revision-2.png'), fullPage: true })
  assert.deepEqual(await draft(), [])
  await Promise.all(identityReads)
  assert.deepEqual(pageErrors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(routeErrors, []); assert.deepEqual(failedResponses, [])
  assert.equal(sha(await readFile(resolve(staticRoot, '.vite/manifest.json'))), manifestSha256, 'dist remained frozen')
  const receipt = { ok: true, authorization: 'explicit route fixture; production auth is not exercised', engine: 'real Python inspect/patch/render and python-pptx/ZIP readback',
    pdfPreview: 'valid attachment placeholder fixture; PDF conversion and native PDF plugin are not exercised',
    manifestSha256, runtimeJavaScript: [...runtimeJavaScript.values()], inputBaseline, sourceSha256: sourceSha, downloadedSha256: sha(downloaded),
    revision: 2, operations: savedPayload.operations, independent, pageErrors, consoleErrors, routeErrors, failedResponses, runtimeEvents }
  await writeFile(resolve(output, 'source.pptx'), sourceBytes)
  await writeFile(resolve(output, 'downloaded.pptx'), downloaded)
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(receipt, null, 2))
  console.log(JSON.stringify({ ok: true, output, manifestSha256, downloadedSha256: sha(downloaded), revision: 2, runtimeJavaScript: runtimeJavaScript.size, errors: [] }))
} catch (error) {
  const body = await page?.locator('body').innerText().catch(() => '')
  throw new Error(`${error.stack ?? error}\n${JSON.stringify({ body: body?.slice(-6000), pageErrors, consoleErrors, routeErrors, failedResponses, runtimeEvents })}`)
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
