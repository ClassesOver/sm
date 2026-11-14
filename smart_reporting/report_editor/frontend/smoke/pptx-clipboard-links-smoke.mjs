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
const output = resolve(process.env.PPTX_SMOKE_EVIDENCE_DIR ?? '/tmp/pptx-clipboard-links-smoke')
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestSha256 = sha(await readFile(resolve(staticRoot, '.vite/manifest.json')))
if (process.env.PPTX_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.PPTX_EXPECTED_MANIFEST_SHA256)
const port = Number(process.env.PPTX_SMOKE_PORT ?? 4201)
const stage = message => console.log(`${new Date().toISOString()} ${message}`)
const base = `http://127.0.0.1:${port}`
const contentType = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
const python = payload => {
  stage(`Python ${payload.mode} start`)
  const result = spawnSync(resolve(repo, '.venv/bin/python'), [resolve(frontend, 'smoke/pptx-clipboard-links-fixture.py')], {
    cwd: repo, env: { ...process.env, PYTHONPATH: repo, MPLCONFIGDIR: '/tmp/pptx-clipboard-links-mpl' }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 60 * 1024 * 1024, timeout: 180000, stdio: ['pipe', 'pipe', 'inherit'],
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
const sourceByName = new Map(fixture.model.slides[0].elements.map(item => [item.name, item]))
for (const name of ['A', 'B', 'After', 'Image']) assert.ok(sourceByName.has(name))
assert.equal(sourceByName.get('A').brushSource.text.fontFamily, 'Arial')
assert.equal(sourceByName.get('B').brushSource.text.fontFamily, 'Calibri')
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
  await route('**/reports/v1/native/fixture-clipboard-links/*/api/context', request => request.fulfill({ json: {
    context: { documentId: 'fixture-clipboard-links', format: 'pptx', revision: activeRevision, parentRevision: activeRevision === 1 ? null : activeRevision - 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'clipboard-links.pptx', size: activeBytes.length, sha256: activeSha, mediaType: contentType }, origin: 'upload' },
    csrfToken: 'clipboard-links-fixture-csrf', capabilities: { pptx_editor: true }, editingEnabled: true, aiEnabled: false,
  } }))
  await route('**/reports/v1/native/fixture-clipboard-links/*/api/file', request => request.fulfill({ body: activeBytes, contentType }))
  // The auxiliary PDF iframe is a valid placeholder fixture; visual PPTX rendering below uses the real render-tree bridge.
  await route('**/reports/v1/native/fixture-clipboard-links/*/api/preview.pdf*', request => request.fulfill({ body: Buffer.from(fixture.previewPdf, 'base64'), contentType: 'application/pdf', headers: { 'Content-Disposition': 'attachment; filename="fixture-preview.pdf"' } }))
  for (const endpoint of ['preview', 'render-tree']) await route(`**/reports/v1/native/fixture-clipboard-links/*/api/${endpoint}`, async request => {
    const payload = request.request().postDataJSON()
    assert.equal(payload.expectedSha256, activeSha)
    assert.equal(request.request().headers()['x-csrf-token'], 'clipboard-links-fixture-csrf')
    const result = python({ mode: endpoint === 'render-tree' ? 'render' : 'inspect', bytes: activeBytes.toString('base64'), operations: payload.operations })
    await request.fulfill({ json: endpoint === 'render-tree' ? result : { sourceSha256: activeSha, draftSha256: result.sha256, model: result.model } })
  })
  await route('**/reports/v1/native/fixture-clipboard-links/*/api/save', async request => {
    savedPayload = request.request().postDataJSON()
    assert.equal(request.request().headers()['x-csrf-token'], 'clipboard-links-fixture-csrf')
    assert.equal(savedPayload.expectedSha256, activeSha)
    savedBytes = Buffer.from(python({ mode: 'patch', bytes: activeBytes.toString('base64'), operations: savedPayload.operations }).bytes, 'base64')
    const revision = activeRevision + 1, url = '/clipboard-links-download-' + revision + '.pptx'
    downloads.set(url, savedBytes)
    saveReceipt = { documentId: 'fixture-clipboard-links', revision, parentRevision: activeRevision, revisionRegistered: true,
      artifacts: { pptx: { downloadUrl: url, size: savedBytes.length, sha256: sha(savedBytes) } },
      editor: { openUrl: '/reports/v1/native/fixture-clipboard-links/' + revision }, validation: { ok: true, issues: [] } }
    saves.push({ payload: savedPayload, receipt: saveReceipt })
    await request.fulfill({ json: saveReceipt })
  })
  await route('**/clipboard-links-download-*.pptx', request => request.fulfill({ body: downloads.get(new URL(request.request().url()).pathname), contentType }))
  await page.addInitScript(() => {
    if (!location.href.startsWith('http') || window.top !== window || !location.pathname.endsWith('/native.html')) return
    history.replaceState(null, '', `/reports/v1/native/fixture-clipboard-links/${new URL(location.href).searchParams.get('smokeRevision') ?? 1}`)
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
  const partsPreserved = (independent, changed) => {
    assert.deepEqual(Object.keys(independent.zip).sort(), Object.keys(independentBefore.zip).sort())
    for (const [path, digest] of Object.entries(independentBefore.zip)) if (!changed.includes(path)) assert.equal(independent.zip[path], digest, path)
    independentBefore = independent
  }
  const saveAndOpen = async (changed = ['ppt/slides/slide1.xml', 'ppt/slides/slide2.xml', 'ppt/slides/_rels/slide1.xml.rels', 'ppt/slides/_rels/slide2.xml.rels']) => {
    const operations = await draft()
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存', null, { timeout: 60000 })
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
    partsPreserved(independent, changed)
    await writeFile(resolve(output, 'revision-' + saveReceipt.revision + '.pptx'), bytes)
    activeBytes = bytes; activeSha = sha(bytes); activeRevision = saveReceipt.revision
    await open(activeRevision)
    assert.deepEqual(await draft(), [])
    return { bytes, independent, model: python({ mode: 'inspect', bytes: bytes.toString('base64') }).model }
  }
  const linkUrl = 'https://example.com/path?a=$&b=2&encoded=%26'
  const shape = (independent, index, name) => independent.slides[index].shapes.find(item => item.name === name)
  const pictures = (independent, index) => independent.slides[index].shapes.filter(item => item.pictureSha256)
  const sourceImage = shape(sourceIndependent, 0, 'Image')
  const assertImage = copy => {
    assert.equal(copy.pictureSha256, sourceImage.pictureSha256)
    assert.deepEqual(copy.srcRect, sourceImage.srcRect)
    assert.deepEqual(copy.geometry, [sourceImage.geometry[0] + 20 * 9525, sourceImage.geometry[1] + 20 * 9525, ...sourceImage.geometry.slice(2)])
  }
  const font = run => Object.fromEntries(Object.entries(run).filter(([key]) => key !== 'text'))
  const select = id => page.locator('#object-select').selectOption(id)
  const home = () => page.locator('[data-ribbon-tab="home"]').click()
  const command = id => page.locator('[data-command="' + id + '"]').click()
  const canvasKeyboard=process.env.PPTX_CLIPBOARD_KEYBOARD==='1'
  const canvasFocus=async(image=false)=>{
    const canvas=page.locator('.slides-canvas canvas').first();await canvas.scrollIntoViewIfNeeded();const box=await canvas.boundingBox()
    await page.evaluate(()=>document.activeElement instanceof HTMLElement&&document.activeElement.blur())
    const geometry=sourceImage.geometry
    await canvas.click({position:{x:box.width*(image?(geometry[0]+geometry[2]/2)/fixture.model.size.cx:.9),y:box.height*(image?(geometry[1]+geometry[3]/2)/fixture.model.size.cy:.9)}})
    assert.equal(await page.locator('.slides-canvas').evaluate(node=>node===document.activeElement),true)
    if(image)assert.equal(await page.locator('#object-select').inputValue(),sourceByName.get('Image').id)
  }
  const history = id => page.locator('[data-source-action="' + id + '"]').click()
  const linkDialog = async id => {
    await select(id)
    await page.locator('[data-ribbon-tab="insert"]').click()
    await command('insertLink')
    await page.locator('.slides-native-link-dialog').waitFor()
  }
  await open()
  stage('Copying image and brushing A onto B through native controls')
  if(canvasKeyboard){await home();await canvasFocus(true);await page.keyboard.press('Control+c')}
  else {await select(sourceByName.get('Image').id); await home(); await command('copy')}
  assert.deepEqual(await draft(), [], 'copy does not change draft')
  await select(sourceByName.get('A').id); await command('formatBrush')
  assert.equal(await page.locator('[data-command="formatBrush"]').getAttribute('aria-pressed'), 'true')
  await select(sourceByName.get('B').id)
  const brushed = await waitDraft(op => op.textFormatting?.some(item => item.elementId === sourceByName.get('B').id))
  assert.equal(await page.locator('[data-command="formatBrush"]').getAttribute('aria-pressed'), 'false')
  await history('onUndo'); assert.deepEqual(await draft(), [])
  await history('onRedo'); assert.deepEqual(await draft(), brushed)
  stage('Setting exact object URL through native dialog')
  await linkDialog(sourceByName.get('After').id)
  await page.locator('[data-link-url]').fill(linkUrl)
  await page.locator('[data-link-confirm]').click()
  await waitDraft(op => op.linkEdits?.some(item => item.target?.url === linkUrl))
  stage('Pasting onto page two, undoing, restoring and refreshing draft')
  await page.locator('.slide-open[data-slide-index="1"]').click(); await home()
  if(canvasKeyboard){await canvasFocus();await page.keyboard.press('Control+v')}else await command('paste')
  const pasted = await waitDraft(op => op.clipboardPastes?.length === 1)
  assert.deepEqual(pasted[0].clipboardPastes, [{sourceSlideIndex: 0, elementIds: [sourceByName.get('Image').id], slideIndex: 1, dx: 20, dy: 20}])
  await history('onUndo'); await waitDraft(op => !op.clipboardPastes?.length)
  await history('onRedo'); assert.deepEqual(await draft(), pasted)
  await open(); assert.deepEqual(await draft(), pasted); await home()
  assert.equal(await page.locator('[data-command="paste"]').isDisabled(), true, 'clipboard buffer is memory-only')
  await page.screenshot({path: resolve(output, 'copy-brush-link-draft.png'), fullPage: true})
  const copied = await saveAndOpen()
  const sourceA = shape(sourceIndependent, 0, 'A'), savedB = shape(copied.independent, 0, 'B')
  assert.equal(savedB.text, '来源 B')
  assert.deepEqual(savedB.paragraphs.map(item => item.align), sourceA.paragraphs.map(item => item.align))
  assert.deepEqual(savedB.paragraphs.map(item => item.runs.map(font)), sourceA.paragraphs.map(item => item.runs.map(font)))
  assert.equal(savedB.fill, sourceA.fill); assert.deepEqual(savedB.line, sourceA.line)
  assert.equal(shape(copied.independent, 0, 'After').url, linkUrl)
  assert.equal(pictures(copied.independent, 1).length, 1); assertImage(pictures(copied.independent, 1)[0])
  assert.notEqual(pictures(copied.independent, 1)[0].id, sourceImage.id)
  assert.equal(copied.model.slides[0].elements.find(item => item.name === 'After').elementLink.url, linkUrl)
  stage('Cutting saved source image and pasting into page two')
  const image = copied.model.slides[0].elements.find(item => item.name === 'Image')
  if(canvasKeyboard){await home();await canvasFocus(true);await page.keyboard.press('Control+x')}
  else {await select(image.id); await home(); await command('cut')}
  await waitDraft(op => op.deletions?.some(item => item.elementId === image.id))
  assert.equal(await page.locator('#object-select option').evaluateAll((options, id) => options.filter(option => option.value === id).length, image.id), 0, 'cut hides source immediately')
  await page.locator('.slide-open[data-slide-index="1"]').click()
  if(canvasKeyboard){await canvasFocus();await page.keyboard.press('Control+v')}else await command('paste')
  const cutDraft = await waitDraft(op => op.clipboardPastes?.length === 1 && op.deletions?.length === 1)
  await open(2); assert.deepEqual(await draft(), cutDraft)
  const cut = await saveAndOpen()
  assert.equal(pictures(cut.independent, 0).length, 0); assert.equal(pictures(cut.independent, 1).length, 2)
  for (const copy of pictures(cut.independent, 1)) assertImage(copy)
  assert.equal(new Set(pictures(cut.independent, 1).map(item => item.id)).size, 2)
  stage('Removing saved object URL and verifying revision four')
  const after = cut.model.slides[0].elements.find(item => item.name === 'After')
  await linkDialog(after.id)
  assert.equal(await page.locator('[data-link-url]').inputValue(), linkUrl)
  await page.locator('[data-link-remove]').click()
  await waitDraft(op => op.linkEdits?.some(item => item.elementId === after.id && item.target === null))
  const cleared = await saveAndOpen(['ppt/slides/slide1.xml', 'ppt/slides/_rels/slide1.xml.rels'])
  assert.equal(shape(cleared.independent, 0, 'After').url, null)
  assert.equal(cleared.model.slides[0].elements.find(item => item.name === 'After').elementLink, null)
  assert.equal(activeRevision, 4); assert.equal(saves.length, 3)
  await page.screenshot({path: resolve(output, 'revision-four.png'), fullPage: true})
  await Promise.all(identityReads)
  assert.deepEqual(pageErrors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(routeErrors, []); assert.deepEqual(failedResponses, [])
  assert.equal(sha(await readFile(resolve(staticRoot, '.vite/manifest.json'))), manifestSha256)
  const evidence = {ok: true, canvasKeyboard, authorization: 'explicit route fixture; production auth is not exercised',
    pdfPreview: 'valid attachment placeholder; PDF conversion and native PDF plugin are not exercised',
    engine: 'real Python inspect/patch/render and independent python-pptx/ZIP readback',
    manifestSha256, runtimeJavaScript: [...runtimeJavaScript.values()], sourceSha256: sourceSha,
    revision: activeRevision, saves, copied: copied.independent, cut: cut.independent, cleared: cleared.independent,
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
