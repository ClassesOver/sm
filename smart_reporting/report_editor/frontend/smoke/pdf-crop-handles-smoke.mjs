// Run after the root's frozen frontend build; auth/revision routes are explicit substitutes.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_CROP_HANDLES_SMOKE_PORT ?? 4269)
const base = `http://127.0.0.1:${port}`
const evidenceDir = process.env.PDF_CROP_HANDLES_EVIDENCE_DIR ?? '/tmp/pdf-crop-handles-smoke'
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const manifest = await readFile(`${repo}/smart_reporting/report_editor/static/.vite/manifest.json`)
await mkdir(evidenceDir, { recursive: true })
function python(payload) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from pypdf import PdfReader
from smart_reporting.reporting.tests.test_pdf_crop import crop_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create': print(base64.b64encode(crop_fixture(unit=2,page_count=4)).decode())
elif p['mode']=='inspect': print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 result=patch_pdf_with_receipt(base64.b64decode(p['bytes']),p['operations'])
 result['bytes']=base64.b64encode(result.pop('content')).decode();print(json.dumps(result))
elif p['mode']=='verify':
 before=PdfReader(BytesIO(base64.b64decode(p['source'])))
 after=PdfReader(BytesIO(base64.b64decode(p['bytes'])))
 assert len(after.pages)==4
 for old,new in zip(before.pages,after.pages,strict=True):
  assert list(new.mediabox)==list(old.mediabox)
  assert new.get('/Rotate')==old.get('/Rotate')
  assert new.get('/UserUnit')==2
  assert new.get_contents().get_data()==old.get_contents().get_data()
  assert new.extract_text()==old.extract_text()
 assert after.get_fields()['contact']['/V']=='original'
 print(json.dumps({'cropBoxes':[[float(v) for v in page.cropbox] for page in after.pages],'contentPreserved':True,'formValue':'original'}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 24 * 1024 * 1024 })
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}
const source = Buffer.from(python({ mode: 'create' }), 'base64')
const sourceSha256 = hash(source)
const inspect = bytes => JSON.parse(python({ mode: 'inspect', bytes: bytes.toString('base64') }))
const model = inspect(source)
let saved, browser, page, previewBytes, previewReceipt, previewRequest, previewModelResponse, saveRequest
const errors = [], responses = [], assets = []
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  let ready = false
  for (let n = 0; n < 80; n++) { try { ready = (await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok } catch {} if (ready) break; await delay(250) }
  assert.ok(ready, 'frontend preview server unavailable')
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
  page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('response', response => {
    responses.push({ url: response.url(), status: response.status() })
    if (response.url().endsWith('.js')) assets.push(response.body().then(async bytes => {
      const path = new URL(response.url()).pathname.replace('/reports/v1/editor/assets/', '')
      assert.equal(hash(bytes), hash(await readFile(`${repo}/smart_reporting/report_editor/static/${path}`)))
      return { path, sha256: hash(bytes), size: bytes.length }
    }))
  })
  const revision = route => route.request().url().includes('/1/api/') ? 1 : 2
  const active = route => revision(route) === 1 ? source : saved
  await page.route('**/reports/v1/native/crop-handles/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'crop-handles', format: 'pdf', revision: revision(route), origin: 'upload',
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'crop.pdf', sha256: hash(active(route)), size: active(route).length, mediaType: 'application/pdf' } },
    csrfToken: 'fixture', editingEnabled: true, pdfTextEnabled: false,
  } }))
  await page.route('**/reports/v1/native/crop-handles/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/crop-handles/*/api/preview', route => {
    const current = revision(route) === 1 ? model : inspect(saved)
    const payload = route.request().postDataJSON()
    assert.equal(payload.expectedSha256, current.sourceSha256)
    if (payload.operations.length) {
      const { bytes, ...receipt } = JSON.parse(python({ mode: 'patch', bytes: active(route).toString('base64'), operations: payload.operations }))
      const content = Buffer.from(bytes, 'base64')
      previewModelResponse = { sourceSha256: current.sourceSha256, draftSha256: hash(content), model: inspect(content),
        previewDigest: receipt.previewDigest, appliedOperationIndices: receipt.appliedOperationIndices, skippedOperations: receipt.skippedOperations }
      return route.fulfill({ json: previewModelResponse })
    }
    return route.fulfill({ json: { sourceSha256: current.sourceSha256, draftSha256: current.sourceSha256, model: current } })
  })
  await page.route('**/reports/v1/native/crop-handles/1/api/preview.pdf', async route => {
    previewRequest = route.request().postDataJSON()
    assert.equal(previewRequest.expectedSha256, sourceSha256)
    const { bytes, ...receipt } = JSON.parse(python({ mode: 'patch', bytes: source.toString('base64'), operations: previewRequest.operations }))
    assert.equal(previewRequest.expectedPreviewDigest, receipt.previewDigest)
    previewBytes = Buffer.from(bytes, 'base64'); previewReceipt = receipt
    assert.equal(hash(previewBytes), previewModelResponse.draftSha256)
    await writeFile(`${evidenceDir}/preview.pdf`, previewBytes)
    await writeFile(`${evidenceDir}/preview-receipt.json`, JSON.stringify({ request: previewRequest, receipt, modelResponse: previewModelResponse }, null, 2))
    return route.fulfill({ body: previewBytes, contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': receipt.previewDigest } })
  })
  await page.route('**/reports/v1/native/crop-handles/1/api/save', route => {
    saveRequest = route.request().postDataJSON()
    assert.equal(saveRequest.expectedSha256, sourceSha256)
    const receipt = JSON.parse(python({ mode: 'patch', bytes: source.toString('base64'), operations: saveRequest.operations }))
    saved = Buffer.from(receipt.bytes, 'base64')
    return route.fulfill({ json: { documentId: 'crop-handles', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { pdf: { downloadUrl: '/crop-handles-download.pdf', sha256: hash(saved), size: saved.length } },
      editor: { openUrl: '/reports/v1/native/crop-handles/2' }, validation: { ok: false, issues: [{ code: 'manual_review', message: '请核验裁切结果，下载仍可用' }] } } })
  })
  await page.route('**/crop-handles-download.pdf', route => route.fulfill({ body: saved, contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/crop-handles\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  await page.goto(`${base}/reports/v1/native/crop-handles/1`)
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 4 && !document.querySelector('[data-source-command-id="genoffice.pdf.page.crop"]')?.disabled)
  await page.evaluate(() => {
    window.__cropDiagnostics = []
    for (const kind of ['scroll', 'wheel', 'resize', 'blur', 'pointerdown', 'pointermove', 'pointerup', 'pointercancel']) {
      window.addEventListener(kind, event => {
        const stage = document.querySelector('[data-pdf-crop-canvas]')
        if (!stage) return
        const rect = stage.getBoundingClientRect(), target = event.target
        window.__cropDiagnostics.push({ kind, time: performance.now(), x: event.clientX, y: event.clientY,
          target: target instanceof Element ? `${target.tagName}.${target.className}` : String(target),
          handle: target instanceof Element ? target.getAttribute('data-pdf-crop-handle') : null,
          rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
          margins: [...document.querySelectorAll('.pdf-crop-dialog input[type="number"]')].map(input => input.value),
          activePage: document.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id'),
          scroll: [window.scrollX, window.scrollY], active: document.activeElement?.outerHTML?.slice(0, 300) })
      }, true)
    }
  })
  const operations = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('crop-handles'))?.[1] ?? '{"operations":[]}').operations)
  const selectPage = async n => {
    await page.locator('[data-pdf-ribbon-tab="home"]').click()
    const jump = page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]'); await jump.fill(String(n)); await jump.press('Enter')
    await page.locator('[data-pdf-ribbon-tab="page"]').click()
  }
  const crop = page.locator('[data-source-command-id="genoffice.pdf.page.crop"]')
  const dialog = page.getByRole('dialog', { name: '裁切当前页面', exact: true })
  const labels = ['左侧裁去 (%)', '顶部裁去 (%)', '右侧裁去 (%)', '底部裁去 (%)']
  const geometry = [], expectedBoxes = []
  for (let index = 0; index < 4; index++) {
    await selectPage(index + 1)
    if (index === 3) await page.setViewportSize({ width: 520, height: 740 })
    await crop.click()
    const stage = dialog.locator('[data-pdf-crop-canvas]')
    await stage.waitFor(); assert.equal(await stage.locator('[data-pdf-crop-handle]').count(), 8)
    const pixels = await stage.locator('canvas').evaluate(canvas => {
      const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
      let ink = 0; for (let i = 0; i < data.length; i += 4) if (data[i + 3] && Math.min(data[i], data[i + 1], data[i + 2]) < 220) ink++
      return { width: canvas.width, height: canvas.height, ink }
    })
    assert.ok(pixels.ink > 30, `rotation ${index * 90} rendered an empty screenshot`)
    const nw = stage.locator('[data-pdf-crop-handle="nw"]')
    await nw.scrollIntoViewIfNeeded()
    // 打开不同尺寸页面会滚动对话框；待浏览器派发完滚动再按下，避免按契约取消拖动。
    await stage.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const bounds = await stage.boundingBox(), handle = await nw.boundingBox()
    assert.ok(bounds && handle)
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
    await page.mouse.down(); await page.mouse.move(handle.x + handle.width / 2 + bounds.width * .1, handle.y + handle.height / 2 + bounds.height * .2, { steps: 8 }); await page.mouse.up()
    const margins = await Promise.all(labels.map(label => dialog.getByLabel(label, { exact: true }).inputValue().then(Number)))
    assert.ok(Math.abs(margins[0] - 10) < .2 && Math.abs(margins[1] - 20) < .2, JSON.stringify({ index, margins, bounds, handle }))
    assert.equal((await operations()).filter(op => op.kind === 'cropPage').length, index)
    await dialog.getByLabel(labels[2], { exact: true }).fill('30')
    await dialog.getByLabel(labels[3], { exact: true }).fill('10')
    const [l, t] = margins.map(value => value / 100), r = .3, b = .1
    const box = index === 0 ? [10 + l * 380, 20 + b * 460, 390 - r * 380, 480 - t * 460]
      : index === 1 ? [10 + t * 380, 20 + l * 460, 390 - b * 380, 480 - r * 460]
        : index === 2 ? [10 + r * 380, 20 + t * 460, 390 - l * 380, 480 - b * 460]
          : [10 + b * 380, 20 + r * 460, 390 - t * 380, 480 - l * 460]
    expectedBoxes.push(box); geometry.push({ rotation: index * 90, bounds, pixels, margins })
    await dialog.screenshot({ path: `${evidenceDir}/crop-${index * 90}.png` })
    const apply = dialog.getByRole('button', { name: '应用裁切', exact: true })
    await apply.scrollIntoViewIfNeeded(); assert.equal(await apply.isVisible(), true); await apply.click()
    await dialog.waitFor({ state: 'hidden' })
    await page.waitForFunction(count => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('crop-handles'))?.[1] ?? '{"operations":[]}').operations.filter(op => op.kind === 'cropPage').length === count, index + 1)
  }
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.getByLabel('页面缩放滑块', { exact: true }).fill('100')
  await page.getByLabel('页面缩放滑块', { exact: true }).dispatchEvent('input')
  const draftBeforePreview = await operations()
  assert.equal(draftBeforePreview.length, 4)
  assert.ok(draftBeforePreview.every(operation => operation.kind === 'cropPage'))
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  await page.getByRole('button', { name: '校验当前修改', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('#report-editor')?.dataset.pdfPreview === 'true' && document.querySelectorAll('.pdf-page').length === 4)
  assert.ok(previewBytes, 'pure crop must request actual preview.pdf bytes')
  assert.equal(previewReceipt.sourceSha256, sourceSha256)
  assert.equal(previewReceipt.sha256, hash(previewBytes))
  assert.deepEqual(previewRequest.operations, draftBeforePreview)
  assert.deepEqual(await operations(), draftBeforePreview)
  const previewReadback = JSON.parse(python({ mode: 'verify', source: source.toString('base64'), bytes: previewBytes.toString('base64') }))
  previewReadback.cropBoxes.forEach((box, i) => box.forEach((value, j) => assert.ok(Math.abs(value - expectedBoxes[i][j]) < .0001)))
  const previewDimensions = [], expectedDimensions = [[456, 644], [552, 532], [456, 644], [552, 532]]
  for (let index = 0; index < 4; index++) {
    const card = page.locator('.pdf-page').nth(index)
    await card.scrollIntoViewIfNeeded()
    await card.locator('.pdf-page-content > canvas').waitFor()
    const dimensions = await card.locator('.pdf-page-content').evaluate(node => [parseFloat(node.style.width), parseFloat(node.style.height)])
    assert.deepEqual(dimensions, expectedDimensions[index], `actual preview dimensions for rotation ${index * 90}`)
    const canvas = await card.locator('.pdf-page-content > canvas').evaluate(canvas => ({ width: canvas.width, height: canvas.height }))
    assert.ok(canvas.width > 0 && canvas.height > 0)
    previewDimensions.push({ rotation: index * 90, dimensions, canvas })
    await card.screenshot({ path: `${evidenceDir}/preview-${index * 90}.png` })
  }
  assert.equal(await page.locator('.pdf-draft-overlays').count(), 0)
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  assert.equal(await crop.isDisabled(), true)
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  await page.getByRole('button', { name: '返回原稿编辑', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('#report-editor')?.dataset.pdfPreview === 'false' && !document.querySelector('[data-source-command-id="genoffice.pdf.page.crop"]')?.disabled)
  assert.deepEqual(await operations(), draftBeforePreview)
  const returnedDimensions = await page.locator('.pdf-page-content').evaluateAll(nodes => nodes.map(node => [parseFloat(node.style.width), parseFloat(node.style.height)]))
  assert.deepEqual(returnedDimensions, expectedDimensions)
  assert.equal(hash(source), sourceSha256)
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2')
  const url = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], url))
  assert.deepEqual(downloaded, saved)
  assert.deepEqual(downloaded, previewBytes, 'saved PDF bytes must match the independently generated actual preview')
  assert.deepEqual(saveRequest.operations, draftBeforePreview)
  const readback = JSON.parse(python({ mode: 'verify', source: source.toString('base64'), bytes: downloaded.toString('base64') }))
  readback.cropBoxes.forEach((box, i) => box.forEach((value, j) => assert.ok(Math.abs(value - expectedBoxes[i][j]) < .0001)))
  assert.equal(hash(source), sourceSha256)
  assert.deepEqual(errors, [])
  const actualAssets = await Promise.all(assets)
  await writeFile(`${evidenceDir}/source.pdf`, source); await writeFile(`${evidenceDir}/downloaded.pdf`, downloaded)
  const diagnostics = await page.evaluate(() => window.__cropDiagnostics)
  const evidence = { ok: true, manifestSha256: hash(manifest), browserVersion: browser.version(), sourceSha256, outputSha256: hash(downloaded), geometry, expectedBoxes, preview: { sha256: hash(previewBytes), receipt: previewReceipt, request: previewRequest, readback: previewReadback, dimensions: previewDimensions, returnedDimensions, draftUnchanged: true, matchesSavedBytes: true }, readback, assets: actualAssets, responses, errors, diagnostics, provenance: 'frozen production UI and actual PDF.js canvas; substituted auth/revision routes; real packed engine and independent pypdf; not production HTTP/auth or full application-image acceptance' }
  await writeFile(`${evidenceDir}/summary.json`, JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, evidenceDir }))
} catch (error) {
  console.error(error)
  await page?.screenshot({ path: `${evidenceDir}/failure.png`, fullPage: true }).catch(() => {})
  const diagnostics = await page?.evaluate(() => window.__cropDiagnostics).catch(() => undefined)
  await writeFile(`${evidenceDir}/failure.json`, JSON.stringify({ ok: false, message: String(error), stack: error.stack, responses, errors, diagnostics }, null, 2)).catch(writeError => console.error(writeError))
  throw error
} finally { await browser?.close(); server.kill('SIGTERM') }
