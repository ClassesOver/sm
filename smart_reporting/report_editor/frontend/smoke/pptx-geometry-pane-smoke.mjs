import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { verifyBrowserTextInput } from './browser-input-preflight.mjs'
import { inspectGeometryPane } from './office-pptx-geometry-layout.mjs'

// This is an explicit authorization/CSRF route fixture, not a live-service authorization test.
// Preview, rendering, save and downloaded-file inspection run the real Python/OOXML engine.
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(frontend, '../../..')
const staticRoot = process.env.PPTX_STATIC_ROOT ? resolve(process.env.PPTX_STATIC_ROOT) : resolve(frontend, '../static')
const output = resolve(process.env.PPTX_SMOKE_EVIDENCE_DIR ?? '/tmp/pptx-geometry-pane-smoke')
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestSha256 = sha(await readFile(resolve(staticRoot, '.vite/manifest.json')))
if (process.env.PPTX_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.PPTX_EXPECTED_MANIFEST_SHA256)
const port = Number(process.env.PPTX_SMOKE_PORT ?? 4199)
const stage = message => console.log(`${new Date().toISOString()} ${message}`)
const base = `http://127.0.0.1:${port}`
const contentType = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
const python = payload => {
  stage(`Python ${payload.mode} start`)
  const result = spawnSync(resolve(repo, '.venv/bin/python'), [resolve(frontend, 'smoke/pptx-groups-show-fixture.py')], {
    cwd: repo, env: { ...process.env, PYTHONPATH: repo, MPLCONFIGDIR: '/tmp/pptx-groups-show-mpl' }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 60 * 1024 * 1024, timeout: 180000, stdio: ['pipe', 'pipe', 'inherit'],
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
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true })
  page = await context.newPage()
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
  await route('**/reports/v1/native/fixture-geometry-pane/*/api/context', request => request.fulfill({ json: {
    context: { documentId: 'fixture-geometry-pane', format: 'pptx', revision: activeRevision, parentRevision: activeRevision === 1 ? null : activeRevision - 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'groups-show.pptx', size: activeBytes.length, sha256: activeSha, mediaType: contentType }, origin: 'upload' },
    csrfToken: 'geometry-pane-fixture-csrf', capabilities: { pptx_editor: true }, editingEnabled: true, aiEnabled: false,
  } }))
  await route('**/reports/v1/native/fixture-geometry-pane/*/api/file', request => request.fulfill({ body: activeBytes, contentType }))
  // The auxiliary PDF iframe is a valid placeholder fixture; visual PPTX rendering below uses the real render-tree bridge.
  await route('**/reports/v1/native/fixture-geometry-pane/*/api/preview.pdf*', request => request.fulfill({ body: Buffer.from(fixture.previewPdf, 'base64'), contentType: 'application/pdf', headers: { 'Content-Disposition': 'attachment; filename="fixture-preview.pdf"' } }))
  for (const endpoint of ['preview', 'render-tree']) await route(`**/reports/v1/native/fixture-geometry-pane/*/api/${endpoint}`, async request => {
    const payload = request.request().postDataJSON()
    assert.equal(payload.expectedSha256, activeSha)
    assert.equal(request.request().headers()['x-csrf-token'], 'geometry-pane-fixture-csrf')
    const result = python({ mode: endpoint === 'render-tree' ? 'render' : 'inspect', bytes: activeBytes.toString('base64'), operations: payload.operations })
    await request.fulfill({ json: endpoint === 'render-tree' ? result : { sourceSha256: activeSha, draftSha256: result.sha256, model: result.model } })
  })
  await route('**/reports/v1/native/fixture-geometry-pane/*/api/save', async request => {
    savedPayload = request.request().postDataJSON()
    assert.equal(request.request().headers()['x-csrf-token'], 'geometry-pane-fixture-csrf')
    assert.equal(savedPayload.expectedSha256, activeSha)
    savedBytes = Buffer.from(python({ mode: 'patch', bytes: activeBytes.toString('base64'), operations: savedPayload.operations }).bytes, 'base64')
    const revision = activeRevision + 1, url = '/groups-show-download-' + revision + '.pptx'
    downloads.set(url, savedBytes)
    saveReceipt = { documentId: 'fixture-geometry-pane', revision, parentRevision: activeRevision, revisionRegistered: true,
      artifacts: { pptx: { downloadUrl: url, size: savedBytes.length, sha256: sha(savedBytes) } },
      editor: { openUrl: '/reports/v1/native/fixture-geometry-pane/' + revision }, validation: { ok: true, issues: [] } }
    saves.push({ payload: savedPayload, receipt: saveReceipt })
    await request.fulfill({ json: saveReceipt })
  })
  await route('**/groups-show-download-*.pptx', request => request.fulfill({ body: downloads.get(new URL(request.request().url()).pathname), contentType }))
  await page.addInitScript(() => {
    if (!location.href.startsWith('http') || window.top !== window || !location.pathname.endsWith('/native.html')) return
    history.replaceState(null, '', `/reports/v1/native/fixture-geometry-pane/${new URL(location.href).searchParams.get('smokeRevision') ?? 1}`)
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
  const partsPreserved = independent => {
    assert.deepEqual(Object.keys(independent.zip).sort(), Object.keys(sourceIndependent.zip).sort())
    for (const [path, digest] of Object.entries(sourceIndependent.zip)) {
      if (path !== 'ppt/slides/slide1.xml') assert.equal(independent.zip[path], digest, path)
    }
  }
  const saveAndOpen = async () => {
    const operations = await draft()
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => (document.querySelector('.slides-save-state') ?? document.querySelector('.save-state-label'))?.textContent === '已保存', null, { timeout: 60000 })
    assert.deepEqual(savedPayload.operations, operations)
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
    partsPreserved(independent)
    await writeFile(resolve(output, 'revision-' + saveReceipt.revision + '.pptx'), bytes)
    activeBytes = bytes; activeSha = sha(bytes); activeRevision = saveReceipt.revision
    await open(activeRevision)
    assert.deepEqual(await draft(), [])
    return { bytes, independent, model: python({ mode: 'inspect', bytes: bytes.toString('base64') }).model }
  }
  await open()
  const targets = [fixture.model.slides[0].elements.find(item => item.name === 'Group A'), fixture.model.slides[0].elements.find(item => item.type === 'picture')]
  const layout = await inspectGeometryPane(page, { output, viewports: process.env.PPTX_GEOMETRY_VIEWPORTS ?? '1440x900,320x640,640x360,390x320,1440x360', targets, draft })
  assert.deepEqual(layout.failures, [])
  stage('Editing real geometry through centimetre and percent fields')
  const shape = targets[0], picture = targets[1]
  const pane = page.locator('.slides-geometry-pane')
  const change = async (name, value) => { const field = pane.locator(`[data-geometry="${name}"]`); await field.fill(value); await field.press('Enter') }
  await page.locator('#object-select').selectOption(shape.id)
  await pane.locator('[data-geometry-ratio]').check()
  await change('width', '5.08')
  await waitDraft(op => op.edits?.some(item => item.elementId === shape.id && Math.abs(item.geometry?.width - 192) < .001))
  const shapeEdit = (await draft())[0].edits.find(item => item.elementId === shape.id)
  assert.ok(Math.abs(shapeEdit.geometry.height - 64 * 192 / 140) < .001)
  const widthAfter = await pane.locator('[data-geometry="width"]').inputValue()
  await page.locator('[data-source-action="onUndo"]').click(); assert.deepEqual(await draft(), [])
  await page.locator('[data-source-action="onRedo"]').click()
  assert.equal(await pane.locator('[data-geometry="width"]').inputValue(), widthAfter)
  await page.locator('#object-select').selectOption(picture.id)
  await page.waitForFunction(() => !document.querySelector('[data-geometry-original]').disabled)
  // 比例复选框是会话设置；独立设置图片尺寸，明确关闭联动。
  if (await pane.locator('[data-geometry-ratio]').isChecked()) await pane.locator('[data-geometry-ratio]').uncheck()
  await change('scaleWidth', '200')
  await change('scaleHeight', '150')
  await change('x', '5.08')
  const pending = await draft()
  const pictureEdit = pending[0].edits.find(item => item.elementId === picture.id)
  assert.deepEqual(pictureEdit.geometry, { x: 192, y: 336, width: 240, height: 120 })
  await open(); assert.deepEqual(await draft(), pending)
  const saved = await saveAndOpen()
  const actual = saved.independent.slides[0].shapes
  const expected = structuredClone(sourceIndependent.slides[0].shapes)
  expected.find(item => item.name === 'Group A').geometry = [200*9525, 100*9525, 192*9525, Math.round(64*192/140*9525)]
  expected.find(item => item.name === 'Group image').geometry = [192*9525, 336*9525, 240*9525, 120*9525]
  assert.deepEqual(actual, expected, '保存仅改变指定几何，文字、对象身份、裁剪及图片不变')
  await page.locator('#object-select').selectOption(saved.model.slides[0].elements.find(item => item.name === picture.name).id)
  assert.equal(await pane.locator('[data-geometry="width"]').inputValue(), '6.35')
  assert.equal(await pane.locator('[data-geometry="height"]').inputValue(), '3.18')
  assert.equal(await pane.locator('[data-geometry="x"]').inputValue(), '5.08')
  await page.screenshot({ path: resolve(output, 'geometry-reopened.png'), fullPage: true })
  await Promise.all(identityReads)
  assert.deepEqual(pageErrors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(routeErrors, []); assert.deepEqual(failedResponses, [])
  assert.equal(sha(await readFile(resolve(staticRoot, '.vite/manifest.json'))), manifestSha256)
  const evidence = { ok: true, authorization: 'explicit authorization/CSRF/revision fixtures', pdfPreview: 'attachment placeholder, not conversion',
    manifestSha256, runtimeJavaScript: [...runtimeJavaScript.values()], sourceSha256: sourceSha,
    revision: activeRevision, saves, source: sourceIndependent, saved: saved.independent, pending, layout,
    pageErrors, consoleErrors, routeErrors, failedResponses, runtimeEvents, inputBaseline }
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ok: true, output, revision: activeRevision, manifestSha256, runtimeJavaScript: runtimeJavaScript.size }))
} catch (error) {
  const body = await page?.locator('body').innerText().catch(() => '')
  throw new Error(`${error.stack ?? error}\n${JSON.stringify({ body: body?.slice(-6000), pageErrors, consoleErrors, routeErrors, failedResponses, runtimeEvents })}`)
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
