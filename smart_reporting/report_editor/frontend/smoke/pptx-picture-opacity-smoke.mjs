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
const output = resolve(process.env.PPTX_SMOKE_EVIDENCE_DIR ?? '/tmp/pptx-picture-opacity-smoke')
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
// 默认用生产构建（vite preview）；PPTX_OPACITY_SMOKE_PRODUCTION=0 时用开发服务器。
const production = process.env.PPTX_OPACITY_SMOKE_PRODUCTION !== '0'
const port = Number(process.env.PPTX_SMOKE_PORT ?? 4205)
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
assert.ok(sourcePicture.pictureOpacityEditable)
assert.equal(sourcePicture.pictureOpacity, 1)
const server = production
  ? spawn(resolve(frontend, 'node_modules/.bin/vite'), ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  : spawn(process.execPath, ['--input-type=module', '-e', `import { createServer } from 'vite'; const server = await createServer({ server: { host: '127.0.0.1', port: ${port}, strictPort: true, hmr: false } }); await server.listen()`], { cwd: frontend, stdio: 'ignore' })
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
  stage('Revision 1 loaded; setting picture transparency')
  const transparency = page.locator('[data-command="pictureOpacity"]')
  const setTransparency = async value => { await transparency.fill(String(value)); await transparency.blur() }
  // 未选图片时不可用并说明原因
  await page.locator('#object-select').selectOption(sourceShapes[0].id)
  await page.locator('#object-select').selectOption(sourcePicture.id)
  await page.locator('[data-ribbon-tab="pictureFormat"]').click()
  assert.equal(await transparency.isEnabled(), true)
  assert.equal(await transparency.inputValue(), '0')
  await setTransparency(60)
  const identity = { slideIndex: 0, elementId: sourcePicture.id, expectedSha256: sourcePicture.pictureSha256, expectedSize: sourcePicture.pictureSize }
  await waitDraft(operation => operation.pictureOpacities?.[0]?.opacity === 0.4)
  assert.deepEqual((await draft())[0].pictureOpacities, [{ ...identity, opacity: 0.4 }])
  assert.equal(await transparency.inputValue(), '60')
  // 撤销 / 重做
  await page.locator('[data-source-action="onUndo"]').click()
  await waitDraft(operation => !operation.pictureOpacities)
  await page.locator('[data-source-action="onRedo"]').click()
  await waitDraft(operation => operation.pictureOpacities?.[0]?.opacity === 0.4)
  // 改回来源值即撤回该修改；再设为 35%
  await page.locator('#object-select').selectOption(sourcePicture.id)
  await page.locator('[data-ribbon-tab="pictureFormat"]').click()
  await setTransparency(0)
  await waitDraft(operation => !operation.pictureOpacities)
  await setTransparency(35)
  await waitDraft(operation => operation.pictureOpacities?.[0]?.opacity === 0.65)
  // 设计 ▸ 背景图片：平铺 + 应用到全部页面（固定源 FormatBackgroundPane 图片填充）
  const backgroundPng = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGUlEQVR4nGN8cdSdgRTARJLqUQ2jGoaUBgAsYwIUY/XmyAAAAABJRU5ErkJggg==', 'base64')  // Pillow 生成的 16×16 PNG
  await page.locator('[data-ribbon-tab="design"]').click()
  await page.locator('[data-command="backgroundImage"]').click()
  await page.locator('.slides-bg-image-dialog').waitFor({ state: 'visible' })
  await page.getByLabel('背景图片填充方式').selectOption('tile')
  await page.locator('.slides-bg-image-dialog input[name=all]').check()
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.locator('.slides-bg-image-dialog button[value=ok]').click()])
  await chooser.setFiles({ name: 'bg.png', mimeType: 'image/png', buffer: backgroundPng })
  const completeDraft = await waitDraft(operation => operation.backgroundImages?.length === 1)
  assert.deepEqual(completeDraft[0].pictureOpacities, [{ ...identity, opacity: 0.65 }])
  assert.deepEqual(completeDraft[0].backgroundImages, [{ slideIndices: [0, 1], bytesBase64: backgroundPng.toString('base64'), extension: 'png', tile: true }])
  assert.match(await page.locator('.structure-pending').textContent(), /全部页面 · 背景图片（平铺）/)
  // 有待保存透明度时不能替换图片
  assert.equal(await page.locator('[data-command="replacePicture"]').isEnabled(), true)
  // 刷新后草稿恢复，控件回显 35
  await open()
  assert.deepEqual(await draft(), completeDraft, 'reload restores the entire operation')
  await page.locator('#object-select').selectOption(sourcePicture.id)
  await page.locator('[data-ribbon-tab="pictureFormat"]').click()
  assert.equal(await transparency.inputValue(), '35')
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
  assert.equal(sha(sourceBytes), sourceSha)
  // 独立回读：python-pptx + ZIP。位图不变，只有第 1 页 XML 变化，alphaModFix 为 65000。
  const independent = python({ mode: 'independent', bytes: downloaded.toString('base64') })
  assert.equal(independent.slides.length, 2)
  assert.equal(independent.slides[0].pictures[0].sha256, sourceIndependent.slides[0].pictures[0].sha256)
  assert.deepEqual(independent.slides[0].pictures[0].geometry, sourceIndependent.slides[0].pictures[0].geometry)
  assert.match(independent.slideXml, /<a:alphaModFix amt="65000"\/>/)
  assert.match(independent.slideXml, /<p:bg><p:bgPr><a:blipFill[^>]*><a:blip r:embed="rId\d+"\/><a:tile /)
  assert.doesNotMatch(sourceIndependent.slideXml, /alphaModFix/)
  assert.deepEqual(independent.slides[1], sourceIndependent.slides[1])
  // 第 2 页内容不变，只多了背景；新增唯一一个背景媒体部件，供两页共用
  const changed = new Set(['ppt/slides/slide1.xml', 'ppt/slides/slide2.xml', 'ppt/slides/_rels/slide1.xml.rels', 'ppt/slides/_rels/slide2.xml.rels', '[Content_Types].xml'])
  for (const [path, digest] of Object.entries(sourceIndependent.zip)) if (!changed.has(path)) assert.equal(independent.zip[path], digest, `untouched part ${path}`)
  const addedMedia = Object.keys(independent.zip).filter(path => !(path in sourceIndependent.zip) && path.startsWith('ppt/media/') && !path.endsWith('/'))
  assert.equal(addedMedia.length, 1)
  assert.equal(independent.zip[addedMedia[0]], sha(backgroundPng))
  activeBytes = downloaded; activeSha = sha(downloaded); activeRevision = 2
  stage('Independent download readback passed; opening revision 2')
  await open(2)
  const reopenedPicture = python({ mode: 'inspect', bytes: downloaded.toString('base64') }).model.slides[0].elements.find(element => element.type === 'picture')
  assert.equal(reopenedPicture.pictureOpacity, 0.65)
  const reopenedModel = python({ mode: 'inspect', bytes: downloaded.toString('base64') }).model
  assert.deepEqual(reopenedModel.slides.map(slide => slide.backgroundImage), [{ mode: 'tile' }, { mode: 'tile' }])
  await page.locator('#object-select').selectOption(reopenedPicture.id)
  await page.locator('[data-ribbon-tab="pictureFormat"]').click()
  assert.equal(await transparency.inputValue(), '35')
  await page.screenshot({ path: resolve(output, 'revision-2.png'), fullPage: true })
  assert.deepEqual(await draft(), [])
  const ignorable = message => /WebSocket|\[vite\]/.test(message)
  assert.deepEqual(pageErrors.filter(message => !ignorable(message)), []); assert.deepEqual(consoleErrors.filter(message => !ignorable(message)), []); assert.deepEqual(routeErrors, []); assert.deepEqual(failedResponses, [])
  await writeFile(resolve(output, 'downloaded.pptx'), downloaded)
  console.log(JSON.stringify({ ok: true, output, productionBuild: production, engine: 'real Python inspect/patch/render and python-pptx/ZIP readback', authorization: 'explicit route fixture', downloadedSha256: sha(downloaded), revision: 2, operations: savedPayload.operations }))
} catch (error) {
  const body = await page?.locator('body').innerText().catch(() => '')
  throw new Error(`${error.stack ?? error}\n${JSON.stringify({ body: body?.slice(-6000), pageErrors, consoleErrors, routeErrors, failedResponses, runtimeEvents })}`)
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
