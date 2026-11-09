import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const engine = `${repo}/smart_reporting/reporting/pdf_engine`
const port = Number(process.env.PDF_BLANK_SMOKE_PORT ?? 4197)
const baseUrl = `http://127.0.0.1:${port}`
const mediaType = 'application/pdf'
const runBridge = (mode, bytes, operations = []) => {
  if (mode !== 'create') {
    const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin);b=base64.b64decode(p['bytes'])
if p['mode']=='inspect':print(json.dumps(inspect_pdf(b)))
else:
 r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify({ mode, bytes: bytes.toString('base64'), operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
    if (result.status !== 0) throw new Error(result.stderr)
    return JSON.parse(result.stdout)
  }
  const result = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', `
import { readFileSync } from 'node:fs'
import { PDFDocument, PDFName, PDFString, degrees } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './bridge/operations.ts'
const input = JSON.parse(readFileSync(0, 'utf8'))
const bytes = Buffer.from(input.bytes, 'base64')
let output
if (input.mode === 'create') {
  const pdf = await PDFDocument.create()
  pdf.setTitle('PDF properties smoke')
  pdf.setAuthor('Smart Reporting')
  pdf.addPage([612, 792])
  const secondPage = pdf.addPage([500, 400])
  pdf.addPage([320, 480]); pdf.addPage([700, 500])
  pdf.getPages().forEach((page, i) => { page.setRotation(degrees(i * 90)); const b=page.getMediaBox(); page.setCropBox(12, 24, b.width - 24, b.height - 48) })
  const note = pdf.context.register(pdf.context.obj({ Type: 'Annot', Subtype: 'Text', Rect: [30,60,50,78], Contents: PDFString.of('Keep native note') })); secondPage.node.set(PDFName.of('Annots'), pdf.context.obj([note]))
  const outlines = pdf.context.obj({ Type: 'Outlines', Count: 1 })
  const outlineRef = pdf.context.register(outlines)
  const item = pdf.context.obj({ Title: PDFString.of('Page Two'), Parent: outlineRef, Dest: [secondPage.ref, PDFName.of('Fit')] })
  const itemRef = pdf.context.register(item)
  outlines.set(PDFName.of('First'), itemRef)
  outlines.set(PDFName.of('Last'), itemRef)
  pdf.catalog.set(PDFName.of('Outlines'), outlineRef)
  const form = pdf.getForm()
  form.createTextField('contact.name').addToPage(pdf.getPages()[0], { x: 48, y: 700, width: 220, height: 24 })
  form.createCheckBox('consent').addToPage(pdf.getPages()[0], { x: 48, y: 650, width: 18, height: 18 })
  const radio = form.createRadioGroup('plan'); radio.addOptionToPage('basic', pdf.getPages()[0], { x: 48, y: 610, width: 18, height: 18 }); radio.addOptionToPage('pro', pdf.getPages()[0], { x: 100, y: 610, width: 18, height: 18 })
  const dropdown = form.createDropdown('region'); dropdown.addOptions(['north', 'south']); dropdown.addToPage(pdf.getPages()[0], { x: 48, y: 560, width: 160, height: 24 })
  output = { bytes: Buffer.from(await pdf.save()).toString('base64') }
} else if (input.mode === 'inspect') output = await inspectPdf(bytes)
else if (input.mode === 'patch') { const result = await patchPdfWithReceipt(bytes, input.operations, input.sha256); output = { bytes: Buffer.from(result.bytes).toString('base64'), sha256: result.sha256 } }
else throw new Error('unknown mode')
process.stdout.write(JSON.stringify(output))
`], { cwd: engine, input: JSON.stringify({ mode, bytes: bytes.toString('base64'), operations, sha256: createHash('sha256').update(bytes).digest('hex') }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `PDF bridge exited ${result.status}`)
  return JSON.parse(result.stdout)
}

const sourceBytes = Buffer.from(runBridge('create', Buffer.alloc(0)).bytes, 'base64')
const sourceSha = createHash('sha256').update(sourceBytes).digest('hex')
const sourceModel = runBridge('inspect', sourceBytes)
let savedBytes
let savePayload
let readOnly = false
// Prefer the production build: it has no Vite hot-reload WebSocket transport.
const production = process.env.PDF_BLANK_SMOKE_PRODUCTION !== '0'
const server = production
  ? spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  : spawn(process.execPath, ['--input-type=module', '-e', `import { createServer } from 'vite'; const server = await createServer({ server: { host: '127.0.0.1', port: ${port}, strictPort: true, hmr: false } }); await server.listen()`], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()) })
  await page.route('**/reports/v1/native/fixture-pdf/*/api/context', route => { const revision = route.request().url().includes('/1/api/') ? 1 : 2; const bytes = revision === 1 ? sourceBytes : savedBytes; return route.fulfill({ json: {
    context: { documentId: 'fixture-pdf', format: 'pdf', revision, parentRevision: revision === 1 ? null : 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'fixture.pdf', size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), mediaType }, origin: 'upload' },
    csrfToken: 'fixture-csrf', capabilities: { pdf_editor: true }, editingEnabled: !readOnly,
  } }) })
  await page.route('**/reports/v1/native/fixture-pdf/*/api/file', route => route.fulfill({ body: route.request().url().includes('/1/api/') ? sourceBytes : savedBytes, contentType: mediaType }))
  await page.route('**/reports/v1/native/fixture-pdf/*/api/preview', route => { const model = route.request().url().includes('/1/api/') ? sourceModel : runBridge('inspect', savedBytes); return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model, appliedOperationIndices: [], skippedOperations: [] } }) })
  await page.route('**/reports/v1/native/fixture-pdf/1/api/save', async route => {
    savePayload = route.request().postDataJSON()
    const patched = runBridge('patch', sourceBytes, savePayload.operations)
    savedBytes = Buffer.from(patched.bytes, 'base64')
    const sha256 = createHash('sha256').update(savedBytes).digest('hex')
    await route.fulfill({ json: { documentId: 'fixture-pdf', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { pdf: { downloadUrl: '/fixture-download.pdf', size: savedBytes.length, sha256 } },
      editor: { openUrl: '/reports/v1/native/fixture-pdf/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/fixture-download.pdf', route => route.fulfill({ body: savedBytes, contentType: mediaType }))
  await page.route(/\/reports\/v1\/native\/fixture-pdf\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/1`)
  try { await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 }) }
  catch { throw new Error(JSON.stringify({ url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1200), pageErrors })) }
  try { await page.waitForFunction(() => document.querySelector('[aria-label="contact.name"]') && document.querySelector('[aria-label="region"]'), null, { timeout: 8000 }) }
  catch { throw new Error(JSON.stringify({ body: (await page.locator('body').innerText()).slice(0, 1600), pageErrors })) }
  // 固定源 Pages ▸ 插入空白页：在当前页之后插入与当前页显示尺寸相同的空白页，作为可撤销草稿，保存时由引擎写入。
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pdf'))[1]).operations)
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  const insertBlank = page.locator('[data-source-command-id="genoffice.pdf.page.insertBlank"]')
  assert.equal(await insertBlank.isEnabled(), true)
  await insertBlank.click()
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 5, null, { timeout: 30000 })
  const inserted = await readDraft()
  const blankOp = inserted.find(op => op.kind === 'insertBlankPage')
  assert.match(blankOp.pageId, /^blank:[a-z0-9-]+$/)
  // 第 1 页 CropBox 为 588×744（旋转 0°），空白页按显示尺寸创建
  assert.deepEqual([blankOp.width, blankOp.height], [588, 744])
  assert.deepEqual(inserted.find(op => op.kind === 'reorderPages').pageIds, [sourceModel.pages[0].pageId, blankOp.pageId, ...sourceModel.pages.slice(1).map(item => item.pageId)])
  await page.waitForFunction(() => document.querySelector('.pdf-page.is-active .pdf-page-label')?.textContent === '第 2 页（新插入的空白页，保存后写入）')
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page.is-active canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  // 空白页不接受裁切（需来源身份），但可旋转
  assert.equal(await page.locator('[data-source-command-id="genoffice.pdf.page.crop"]').isDisabled(), true)
  await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click()
  if (process.env.PDF_BLANK_SCREENSHOT) await page.screenshot({ path: process.env.PDF_BLANK_SCREENSHOT })
  const withRotation = await readDraft()
  assert.deepEqual(withRotation.at(-1), { kind: 'rotatePage', pageId: blankOp.pageId, delta: 90 })
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.deepEqual(await readDraft(), inserted)
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.deepEqual(await readDraft(), [])
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 4, null, { timeout: 30000 })
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click()
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); assert.deepEqual(await readDraft(), withRotation)
  await page.reload(); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  assert.deepEqual(await readDraft(), withRotation)
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 5, null, { timeout: 30000 })
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloadedBytes = Buffer.from(await page.evaluate(async url => {
    const response = await fetch(url)
    if (!response.ok) throw new Error(`download failed: ${response.status}`)
    return [...new Uint8Array(await response.arrayBuffer())]
  }, downloadUrl))
  assert.deepEqual(downloadedBytes, savedBytes)
  assert.deepEqual(savePayload.operations, withRotation)
  // 独立 pypdf 回读：空白页位于第 2 页、尺寸与旋转正确且没有内容流；来源页保持原样。
  const readback = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); print(json.dumps([[float(p.mediabox.width),float(p.mediabox.height),int(p.get("/Rotate",0)),"/Contents" in p,len(p.get("/Annots") or [])] for p in r.pages]))'], { input: downloadedBytes, encoding: 'utf8' })
  if (readback.status !== 0) throw new Error(readback.stderr)
  const pagesOut = JSON.parse(readback.stdout)
  assert.equal(pagesOut.length, 5)
  assert.deepEqual(pagesOut[1], [588, 744, 90, false, 0])
  assert.deepEqual(pagesOut.map(item => item.slice(0, 2)), [[612, 792], [588, 744], [500, 400], [320, 480], [700, 500]])
  assert.equal(pagesOut[2][4], 1)
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/2`); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 5, null, { timeout: 30000 })
  assert.deepEqual(pageErrors.filter(message => !/WebSocket|\[vite\]/.test(message)), [])
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), pages: pagesOut, productionBuild: production, operations: savePayload.operations.map(op => op.kind) }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
