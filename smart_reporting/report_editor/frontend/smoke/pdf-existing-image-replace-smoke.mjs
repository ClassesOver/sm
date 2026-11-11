import assert from 'node:assert/strict'
import { auditOfficeDesktopLayout } from './office-desktop-layout.mjs'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const engine = `${repo}/smart_reporting/reporting/pdf_engine`
const port = Number(process.env.PDF_IMAGE_REPLACE_SMOKE_PORT ?? 4211)
const baseUrl = `http://127.0.0.1:${port}`
const mediaType = 'application/pdf'
const appearances = process.env.PDF_LAYOUT_ANNOTATIONS === '1'
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
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
import { PDFDocument, PDFName, PDFString, StandardFonts } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './bridge/operations.ts'
const input = JSON.parse(readFileSync(0, 'utf8'))
const bytes = Buffer.from(input.bytes, 'base64')
let output
if (input.mode === 'create') {
  const pdf = await PDFDocument.create()
  const font = await pdf.embedFont(StandardFonts.Helvetica)
  const page = pdf.addPage([612, 792])
  page.drawText('Image replacement fixture', { x: 72, y: 720, size: 20, font })
  // Two distinct 2x2 PNG streams: the red one is the replacement target, the green one must stay untouched
  const solid = (r, g, b) => { const { deflateSync } = require('node:zlib'); const raw = Buffer.from([0, r, g, b, r, g, b, 0, r, g, b, r, g, b]); const crc = buf => { let c = ~0; for (const x of buf) { c ^= x; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1 } return ~c >>> 0 }; const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const body = Buffer.concat([Buffer.from(t), d]); const s = Buffer.alloc(4); s.writeUInt32BE(crc(body)); return Buffer.concat([l, body, s]) }; const h = Buffer.alloc(13); h.writeUInt32BE(2, 0); h.writeUInt32BE(2, 4); h[8] = 8; h[9] = 2; return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', h), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]) }
  page.drawImage(await pdf.embedPng(solid(220, 30, 30)), { x: 72, y: 420, width: 200, height: 150 })
  page.drawImage(await pdf.embedPng(solid(30, 160, 60)), { x: 340, y: 420, width: 150, height: 150 })
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
const shotDir = process.env.PDF_IMAGE_REPLACE_SHOTS ?? '/tmp'
// Prefer the production build: it has no Vite hot-reload WebSocket transport.
const production = process.env.PDF_IMAGE_REPLACE_SMOKE_PRODUCTION !== '0'
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
  const previewCalls = []
  await page.route('**/reports/v1/native/fixture-pdf/*/api/preview', route => {
    const { operations } = route.request().postDataJSON()
    if (!operations.length || !route.request().url().includes('/1/api/')) { const model = route.request().url().includes('/1/api/') ? sourceModel : runBridge('inspect', savedBytes); return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model, appliedOperationIndices: [], skippedOperations: [] } }) }
    previewCalls.push(operations)
    const receipt = runBridge('patch', sourceBytes, operations), bytes = Buffer.from(receipt.bytes, 'base64')
    return route.fulfill({ json: { sourceSha256: sourceSha, draftSha256: receipt.sha256, model: runBridge('inspect', bytes), previewDigest: receipt.previewDigest, appliedOperationIndices: receipt.appliedOperationIndices, skippedOperations: receipt.skippedOperations } })
  })
  await page.route('**/reports/v1/native/fixture-pdf/1/api/preview.pdf', route => {
    const receipt = runBridge('patch', sourceBytes, route.request().postDataJSON().operations)
    return route.fulfill({ body: Buffer.from(receipt.bytes, 'base64'), contentType: mediaType, headers: { 'X-Native-Preview-Digest': receipt.previewDigest } })
  })
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
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  // 编辑 ▸ 编辑图像 ▸ 替换为新图像（固定源 replaceExisting → replaceImage）：保留位置与层级，单独保存，先核对实际预览。
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations)
  const replacement = Buffer.from(await page.evaluate(() => { const c = document.createElement('canvas'); c.width = 40; c.height = 30; const x = c.getContext('2d'); x.fillStyle = '#1f4fd8'; x.fillRect(0, 0, 40, 30); x.fillStyle = '#ffd400'; x.fillRect(10, 8, 20, 14); return c.toDataURL('image/png').split(',')[1] }), 'base64')
  const images = bytes => { const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys,hashlib; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); p=r.pages[0]; print(json.dumps({"images":sorted([list(i.image.size),i.image.convert("RGB").getpixel((0,0))] for i in p.images),"text":p.extract_text(),"pages":len(r.pages)}))'], { input: bytes, encoding: 'utf8' }); if (result.status !== 0) throw new Error(result.stderr); return JSON.parse(result.stdout) }
  const sourceRead = images(sourceBytes)
  assert.deepEqual(sourceRead.images.map(item => item[0]), [[2, 2], [2, 2]])
  const targets = sourceModel.existingImages
  assert.equal(targets.length, 2); assert.ok(targets.every(item => item.editable && item.replaceable), JSON.stringify(targets))
  const target = targets.find(item => item.rect[0] === 72)
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.edit.objects.editImage"]').click()
  const dialog = page.getByRole('dialog', { name: '编辑已有图像', exact: true })
  await dialog.waitFor({ state: 'visible' })
  const select = dialog.getByLabel('已有图像选择', { exact: true })
  const optionIndex = targets.filter(item => item.editable).indexOf(target)
  await select.selectOption(String(optionIndex))
  assert.equal(await dialog.getByLabel('已有图像X', { exact: true }).inputValue(), String(target.rect[0]))
  assert.equal(await dialog.locator('.pdf-existing-image-replace-info').textContent(), '不替换像素')
  // 非 PNG/JPEG 被拒绝
  await dialog.getByLabel('选择替换图像').setInputFiles({ name: 'bad.gif', mimeType: 'image/gif', buffer: Buffer.from('GIF89a') })
  await page.waitForFunction(() => document.querySelector('.pdf-existing-image-dialog [role=alert]')?.textContent?.includes('PNG 或 JPEG'))
  await dialog.getByLabel('选择替换图像').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: replacement })
  await page.waitForFunction(() => document.querySelector('.pdf-existing-image-replace-info')?.textContent?.includes('logo.png（40×30）'))
  await dialog.screenshot({ path: `${shotDir}/dialog.png` })
  await dialog.locator('[data-pdf-existing-image-confirm]').click()
  await page.waitForFunction(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations.length === 1)
  const staged = await readDraft()
  assert.equal(staged[0].kind, 'transformExistingImage'); assert.deepEqual(staged[0].rect, target.rect)
  assert.equal(staged[0].imageId, target.imageId); assert.ok(staged[0].image.startsWith('iVBORw0KGgo'))
  // 撤销 / 重做
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click()
  await page.waitForFunction(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations.length === 0)
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click()
  await page.waitForFunction(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations.length === 1)
  assert.deepEqual(await readDraft(), staged)
  // 实际预览确认后保存
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  await page.getByRole('button', { name: '校验当前修改', exact: true }).click()
  await page.locator('.pdf-preview-review input[type="checkbox"]').waitFor({ state: 'visible', timeout: 60000 })
  await page.locator('.pdf-preview-review input[type="checkbox"]').check()
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  await page.screenshot({ path: `${shotDir}/preview.png` })
  assert.ok(previewCalls.some(operations => operations[0]?.image === staged[0].image))
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => /已保存修订 2/.test(document.querySelector('.save-state-label')?.textContent ?? ''), null, { timeout: 60000 })
  assert.deepEqual(savePayload.operations, staged)
  assert.match(savePayload.confirmedPreviewDigest ?? '', /^[a-f0-9]{64}$/)
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloadedBytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.deepEqual(downloadedBytes, savedBytes)
  if (process.env.PDF_IMAGE_REPLACE_OUTPUT) await writeFile(process.env.PDF_IMAGE_REPLACE_OUTPUT, downloadedBytes)
  // 独立 pypdf 回读：目标换成 40×30 新像素（左上角蓝色），另一张绿色 2×2 不变，正文保留；来源文件不变。
  const outRead = images(downloadedBytes)
  assert.equal(outRead.pages, 1)
  assert.deepEqual(outRead.images.map(item => item[0]).sort(), [[2, 2], [40, 30]])
  assert.deepEqual(outRead.images.find(item => item[0][0] === 40)[1], [31, 79, 216])
  assert.deepEqual(outRead.images.find(item => item[0][0] === 2)[1], [30, 160, 60])
  assert.match(outRead.text, /Image replacement fixture/)
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  const reopened = runBridge('inspect', savedBytes)
  const replaced = reopened.existingImages.find(item => Math.abs(item.rect[0] - 72) < .05)
  assert.ok(replaced && replaced.rect.every((value, index) => Math.abs(value - target.rect[index]) < .05), 'footprint kept')
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/2`); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  assert.deepEqual(pageErrors.filter(message => !/WebSocket|\[vite\]/.test(message)), [])
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), images: outRead.images, productionBuild: production }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
