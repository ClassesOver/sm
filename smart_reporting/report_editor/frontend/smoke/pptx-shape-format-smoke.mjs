import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { verifyBrowserTextInput } from './browser-input-preflight.mjs'
import { inspectShapeFormat } from './office-pptx-shape-format-layout.mjs'

// This is an explicit authorization/CSRF route fixture, not a live-service authorization test.
// Preview, rendering, save and downloaded-file inspection run the real Python/OOXML engine.
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(frontend, '../../..')
const staticRoot = process.env.PPTX_STATIC_ROOT ? resolve(process.env.PPTX_STATIC_ROOT) : resolve(frontend, '../static')
const output = resolve(process.env.PPTX_SMOKE_EVIDENCE_DIR ?? '/tmp/pptx-shape-format-smoke')
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestSha256 = sha(await readFile(resolve(staticRoot, '.vite/manifest.json')))
if (process.env.PPTX_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.PPTX_EXPECTED_MANIFEST_SHA256)
const port = Number(process.env.PPTX_SMOKE_PORT ?? 4350)
const stage = message => console.log(`${new Date().toISOString()} ${message}`)
const base = `http://127.0.0.1:${port}`
const contentType = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
const python = payload => {
  stage(`Python ${payload.mode} start`)
  const result = spawnSync(resolve(repo, '.venv/bin/python'), [resolve(frontend, 'smoke/pptx-shape-format-fixture.py')], {
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
  const browserContext = await browser.newContext({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true })
  page = await browserContext.newPage()
  page.on('close', () => { runtimeEvents.push({ event: 'page-close', time: new Date().toISOString() }); stage('Page closed') })
  page.on('crash', () => { runtimeEvents.push({ event: 'page-crash', time: new Date().toISOString() }); stage('Page crashed') })
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) failedResponses.push({ path, status: response.status() })
    if (response.ok() && /\.(js|css)$/.test(path)) identityReads.push((async () => {
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
  await route('**/reports/v1/native/fixture-shape-format/*/api/context', request => request.fulfill({ json: {
    context: { documentId: 'fixture-shape-format', format: 'pptx', revision: activeRevision, parentRevision: activeRevision === 1 ? null : activeRevision - 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'groups-show.pptx', size: activeBytes.length, sha256: activeSha, mediaType: contentType }, origin: 'upload' },
    csrfToken: 'shape-format-fixture-csrf', capabilities: { pptx_editor: true }, editingEnabled: true, aiEnabled: false,
  } }))
  await route('**/reports/v1/native/fixture-shape-format/*/api/file', request => request.fulfill({ body: activeBytes, contentType }))
  // The auxiliary PDF iframe is a valid placeholder fixture; visual PPTX rendering below uses the real render-tree bridge.
  await route('**/reports/v1/native/fixture-shape-format/*/api/preview.pdf*', request => request.fulfill({ body: Buffer.from(fixture.previewPdf, 'base64'), contentType: 'application/pdf', headers: { 'Content-Disposition': 'attachment; filename="fixture-preview.pdf"' } }))
  for (const endpoint of ['preview', 'render-tree']) await route(`**/reports/v1/native/fixture-shape-format/*/api/${endpoint}`, async request => {
    const payload = request.request().postDataJSON()
    assert.equal(payload.expectedSha256, activeSha)
    assert.equal(request.request().headers()['x-csrf-token'], 'shape-format-fixture-csrf')
    const result = python({ mode: endpoint === 'render-tree' ? 'render' : 'inspect', bytes: activeBytes.toString('base64'), operations: payload.operations })
    await request.fulfill({ json: endpoint === 'render-tree' ? result : { sourceSha256: activeSha, draftSha256: result.sha256, model: result.model } })
  })
  await route('**/reports/v1/native/fixture-shape-format/*/api/save', async request => {
    savedPayload = request.request().postDataJSON()
    assert.equal(request.request().headers()['x-csrf-token'], 'shape-format-fixture-csrf')
    assert.equal(savedPayload.expectedSha256, activeSha)
    savedBytes = Buffer.from(python({ mode: 'patch', bytes: activeBytes.toString('base64'), operations: savedPayload.operations }).bytes, 'base64')
    const revision = activeRevision + 1, url = '/groups-show-download-' + revision + '.pptx'
    downloads.set(url, savedBytes)
    saveReceipt = { documentId: 'fixture-shape-format', revision, parentRevision: activeRevision, revisionRegistered: true,
      artifacts: { pptx: { downloadUrl: url, size: savedBytes.length, sha256: sha(savedBytes) } },
      editor: { openUrl: '/reports/v1/native/fixture-shape-format/' + revision }, validation: { ok: true, issues: [] } }
    saves.push({ payload: savedPayload, receipt: saveReceipt })
    await request.fulfill({ json: saveReceipt })
  })
  await route('**/groups-show-download-*.pptx', request => request.fulfill({ body: downloads.get(new URL(request.request().url()).pathname), contentType, headers:{'Content-Disposition':'attachment; filename="shape-format-revision-2.pptx"'} }))
  await page.addInitScript(() => {
    if (!location.href.startsWith('http') || window.top !== window || !location.pathname.endsWith('/native.html')) return
    history.replaceState(null, '', `/reports/v1/native/fixture-shape-format/${new URL(location.href).searchParams.get('smokeRevision') ?? 1}`)
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
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存', null, { timeout: 60000 })
    assert.deepEqual(savedPayload.operations, operations)
    const issued = await page.getByRole('link', { name: '下载 PPTX', exact: true }).getAttribute('href')
    assert.equal(issued, saveReceipt.artifacts.pptx.downloadUrl)
    const lockedState=await page.locator('.slides-shape-format-pane').evaluate(node=>({inert:!!node.closest('[inert]'),controls:[...node.querySelectorAll('input,button')].map(control=>control.disabled)}))
    assert.ok(lockedState.controls.length>0&&lockedState.controls.every(Boolean))
    const pendingDownload=page.waitForEvent('download')
    await page.getByRole('link',{name:'下载 PPTX',exact:true}).click()
    const download=await pendingDownload,bytes=await readFile(await download.path())
    assert.equal(sha(bytes), saveReceipt.artifacts.pptx.sha256)
    assert.equal(bytes.length, saveReceipt.artifacts.pptx.size)
    const independent = python({ mode: 'independent', bytes: bytes.toString('base64') })
    partsPreserved(independent)
    await writeFile(resolve(output, 'revision-' + saveReceipt.revision + '.pptx'), bytes)
    activeBytes = bytes; activeSha = sha(bytes); activeRevision = saveReceipt.revision
    await open(activeRevision)
    assert.deepEqual(await draft(), [])
    return { bytes, independent, lockedState, model: python({ mode: 'inspect', bytes: bytes.toString('base64') }).model }
  }
  await open()
  const pane=page.locator('.slides-shape-format-pane')
  const targets=['Simple RGB','Inherited outline','Complex source'].map(name=>{const item=fixture.model.slides[0].elements.find(e=>e.name===name);return {...item,fillEditable:name!=='Complex source',strokeEditable:name==='Simple RGB'}})
  assert.ok(targets[0].brushSource.shape.fill==='#123456'&&targets[0].brushSource.shape.stroke.widthPt===2.25)
  const layout=await inspectShapeFormat(page,{output,targets,draft});assert.deepEqual(layout.failures,[])
  const shape=targets[0];await page.locator('#object-select').selectOption(shape.id)
  const well=field=>pane.locator(`[data-chart-format-well="shape-${field}"]`)
  const pick=async(field,color)=>{await well(field).focus();await well(field).scrollIntoViewIfNeeded();await well(field).press('ArrowDown');const cell=page.locator(`[data-chart-format-palette] [role=gridcell][title="${color}"]`).last();await cell.focus();await cell.press('Enter');assert.ok(await well(field).evaluate(n=>n===document.activeElement),'选择色块后返回入口')}
  await pick('fill','Red');await waitDraft(op=>op.shapeStyles?.[0]?.fill==='#FF0000')
  await pick('stroke','Blue');await waitDraft(op=>op.shapeStyles?.[0]?.stroke?.color==='#0070C0')
  const width=pane.locator('[data-shape-width]');await width.fill('3.5');await width.press('Enter');await waitDraft(op=>op.shapeStyles?.[0]?.stroke?.widthPt===3.5)
  const expected={slideIndex:0,elementId:shape.id,fill:'#FF0000',stroke:{color:'#0070C0',widthPt:3.5}}
  assert.deepEqual((await draft())[0].shapeStyles,[expected])
  await page.locator('[data-source-action="onUndo"]').click();assert.equal((await draft())[0].shapeStyles[0].stroke.widthPt,2.25)
  await page.locator('[data-source-action="onRedo"]').click();assert.deepEqual((await draft())[0].shapeStyles,[expected])
  for(const field of ['fill','stroke']){
   await pane.locator(`[data-shape-reset="${field}"]`).click();await waitDraft(op=>op.shapeStyles?.[0]?.[field]===undefined)
   await page.locator('[data-source-action="onUndo"]').click();assert.deepEqual((await draft())[0].shapeStyles,[expected])
  }
  for(const field of ['fill','stroke']){
   await pane.locator(`[data-shape-none="${field}"]`).focus();await page.keyboard.press('Space');await waitDraft(op=>field==='fill'?op.shapeStyles?.[0]?.fill==='none':op.shapeStyles?.[0]?.stroke===null)
   await page.locator('[data-source-action="onUndo"]').click();assert.deepEqual((await draft())[0].shapeStyles,[expected])
  }
  const pending=await draft();await open();assert.deepEqual(await draft(),pending)
  await page.locator('#object-select').selectOption(shape.id)
  const saved=await saveAndOpen()
  const names=sourceIndependent.slides[0].shapes.map(s=>s.name)
  for(const name of names){
   const before=sourceIndependent.slides[0].shapes.find(s=>s.name===name),after=saved.independent.slides[0].shapes.find(s=>s.name===name)
   if(name==='Simple RGB'){const {styleXml:a,...unchanged}=before,{styleXml:b,...actual}=after;assert.deepEqual(actual,unchanged);assert.match(b,/FF0000/);assert.match(b,/0070C0/);assert.match(b,/w="44450"/)}else assert.deepEqual(after,before)
  }
  await page.locator('#object-select').selectOption(saved.model.slides[0].elements.find(s=>s.name==='Simple RGB').id)
  assert.equal(await width.inputValue(),'3.5');await width.scrollIntoViewIfNeeded();await page.screenshot({path:resolve(output,'shape-format-reopened.png')})
  await Promise.all(identityReads)
  assert.deepEqual(pageErrors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(routeErrors, []); assert.deepEqual(failedResponses, [])
  assert.equal(sha(await readFile(resolve(staticRoot, '.vite/manifest.json'))), manifestSha256)
  const evidence = { ok: true, authorization: 'explicit authorization/CSRF/revision fixtures', pdfPreview: 'attachment placeholder, not conversion',
    manifestSha256, runtimeJavaScript: [...runtimeJavaScript.values()], sourceSha256: sourceSha,
    revision: activeRevision, saves, source: sourceIndependent, saved: saved.independent, savedLockedState:saved.lockedState, pending, layout,
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
