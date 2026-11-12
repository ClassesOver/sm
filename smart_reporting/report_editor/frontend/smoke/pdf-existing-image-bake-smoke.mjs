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
const port = Number(process.env.PDF_IMAGE_BAKE_SMOKE_PORT ?? 4213)
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
  page.drawText('Image bake fixture', { x: 72, y: 720, size: 20, font })
  // Two distinct 2x2 PNG streams: the red one is the replacement target, the green one must stay untouched
  const solid = (r, g, b) => { const { deflateSync } = require('node:zlib'); const raw = Buffer.from([0, r, g, b, r, g, b, 0, r, g, b, r, g, b]); const crc = buf => { let c = ~0; for (const x of buf) { c ^= x; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1 } return ~c >>> 0 }; const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const body = Buffer.concat([Buffer.from(t), d]); const s = Buffer.alloc(4); s.writeUInt32BE(crc(body)); return Buffer.concat([l, body, s]) }; const h = Buffer.alloc(13); h.writeUInt32BE(2, 0); h.writeUInt32BE(2, 4); h[8] = 8; h[9] = 2; return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', h), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]) }
  // 8×8 split target: left half red, right half blue (flip / crop are visible in pixels)
  const split = (() => { const { deflateSync } = require('node:zlib'); const raw = Buffer.concat(Array.from({ length: 8 }, () => Buffer.from([0, ...Array.from({ length: 8 }, (_, x) => x < 4 ? [220, 30, 30] : [31, 79, 216]).flat()]))); const crc = buf => { let c = ~0; for (const x of buf) { c ^= x; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1 } return ~c >>> 0 }; const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const body = Buffer.concat([Buffer.from(type), data]); const sum = Buffer.alloc(4); sum.writeUInt32BE(crc(body)); return Buffer.concat([len, body, sum]) }; const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(8, 0); ihdr.writeUInt32BE(8, 4); ihdr[8] = 8; ihdr[9] = 2; return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]) })()
  page.drawImage(await pdf.embedPng(split), { x: 72, y: 420, width: 200, height: 150 })
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
const shotDir = process.env.PDF_IMAGE_BAKE_SHOTS ?? '/tmp'
// Prefer the production build: it has no Vite hot-reload WebSocket transport.
const production = process.env.PDF_IMAGE_BAKE_SMOKE_PRODUCTION !== '0'
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
  // 编辑 ▸ 编辑图像 ▸ 像素编辑（固定源 flip / crop / opacity 烘焙 → replaceImage）：桥接取图像自身像素，单独保存，先核对实际预览。
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations)
  const draftLength = n => page.waitForFunction(count => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations.length === count, n)
  // pypdf 读回目标图像尺寸与左/右 1/4 处像素
  const images = bytes => { const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); p=r.pages[0]\nout=[]\nfor i in p.images:\n im=i.image.convert("RGB"); w,h=im.size; out.append([[w,h],list(im.getpixel((w//4,h//2))),list(im.getpixel((3*w//4,h//2)))])\nprint(json.dumps({"pages":len(r.pages),"images":sorted(out),"text":p.extract_text()}))'], { input: bytes, encoding: 'utf8' }); if (result.status !== 0) throw new Error(result.stderr); return JSON.parse(result.stdout) }
  const sourceRead = images(sourceBytes)
  assert.deepEqual(sourceRead.images.find(item => item[0][0] === 8).slice(1), [[220, 30, 30], [31, 79, 216]])
  const targets = sourceModel.existingImages
  const target = targets.find(item => item.rect[0] === 72)
  assert.ok(target.bakeable, JSON.stringify(target))
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  const openDialog = async () => {
    await page.locator('[data-source-command-id="genoffice.pdf.edit.objects.editImage"]').click()
    const dialog = page.getByRole('dialog', { name: '编辑已有图像', exact: true })
    await dialog.waitFor({ state: 'visible' })
    await dialog.getByLabel('已有图像选择', { exact: true }).selectOption(String(targets.filter(item => item.editable).indexOf(target)))
    return dialog
  }
  // 裁剪：裁去右侧 50%，暂存的范围 = 固定源 cropRect；再撤销
  let dialog = await openDialog()
  await dialog.getByLabel('已有图像像素编辑').selectOption('crop')
  assert.equal(await dialog.getByLabel('已有图像X', { exact: true }).isDisabled(), true)
  assert.equal(await dialog.locator('[data-pdf-existing-image-replace]').isDisabled(), true, '像素编辑与替换互斥')
  await dialog.getByLabel('裁去右侧百分比').fill('50')
  await dialog.locator('[data-pdf-existing-image-confirm]').click()
  await draftLength(1)
  const [x1, y1, x2, y2] = target.rect
  const cropped = await readDraft()
  assert.deepEqual(cropped[0].bake, { kind: 'crop', crop: { l: 0, t: 0, r: .5, b: 1 } })
  assert.ok(cropped[0].rect.every((value, index) => Math.abs(value - [x1, y1, x1 + .5 * (x2 - x1), y2][index]) < .001), JSON.stringify(cropped[0].rect))
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click()
  await draftLength(0)
  // 透明度超出范围被拒绝；改为水平翻转
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  dialog = await openDialog()
  await dialog.getByLabel('已有图像像素编辑').selectOption('opacity')
  await dialog.getByLabel('图像透明度百分比').fill('0')
  await dialog.locator('[data-pdf-existing-image-confirm]').click()
  await page.waitForFunction(() => document.querySelector('.pdf-existing-image-dialog [role=alert]')?.textContent?.includes('1–100'))
  await dialog.getByLabel('已有图像像素编辑').selectOption('flip-h')
  await dialog.screenshot({ path: `${shotDir}/bake-dialog.png` })
  await dialog.locator('[data-pdf-existing-image-confirm]').click()
  await draftLength(1)
  const staged = await readDraft()
  assert.deepEqual(staged[0].bake, { kind: 'flip', axis: 'h' }); assert.deepEqual(staged[0].rect, target.rect); assert.equal(staged[0].image, undefined)
  // 撤销 / 重做 / 刷新恢复
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click()
  await draftLength(0)
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click()
  await draftLength(1)
  await page.reload(); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  assert.deepEqual(await readDraft(), staged)
  // 实际预览确认后保存
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  await page.getByRole('button', { name: '校验当前修改', exact: true }).click()
  await page.locator('.pdf-preview-review input[type="checkbox"]').waitFor({ state: 'visible', timeout: 60000 })
  await page.locator('.pdf-preview-review input[type="checkbox"]').check()
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  await page.screenshot({ path: `${shotDir}/bake-preview.png` })
  assert.ok(previewCalls.some(operations => operations[0]?.bake?.kind === 'flip'))
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => /已保存修订 2/.test(document.querySelector('.save-state-label')?.textContent ?? ''), null, { timeout: 60000 })
  assert.deepEqual(savePayload.operations, staged)
  assert.match(savePayload.confirmedPreviewDigest ?? '', /^[a-f0-9]{64}$/)
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloadedBytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.deepEqual(downloadedBytes, savedBytes)
  if (process.env.PDF_IMAGE_BAKE_OUTPUT) await writeFile(process.env.PDF_IMAGE_BAKE_OUTPUT, downloadedBytes)
  // 独立 pypdf 回读：目标按 BAKE_SCALE 3 取样（200×150pt → 600×450px），左右颜色互换；绿色图像不变，正文保留；来源文件不变。
  const outRead = images(downloadedBytes)
  assert.equal(outRead.pages, 1)
  const flipped = outRead.images.find(item => item[0][0] === 600)
  assert.deepEqual(flipped[0], [600, 450])
  const near = (actual, expected) => actual.every((value, index) => Math.abs(value - expected[index]) <= 12)
  assert.ok(near(flipped[1], [31, 79, 216]) && near(flipped[2], [220, 30, 30]), JSON.stringify(flipped))
  assert.deepEqual(outRead.images.find(item => item[0][0] === 2).slice(1), sourceRead.images.find(item => item[0][0] === 2).slice(1))
  assert.match(outRead.text, /Image bake fixture/)
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  const reopened = runBridge('inspect', savedBytes)
  const baked = reopened.existingImages.find(item => Math.abs(item.rect[0] - 72) < .05)
  assert.ok(baked && baked.rect.every((value, index) => Math.abs(value - target.rect[index]) < .05), 'footprint kept')
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/2`); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  assert.deepEqual(pageErrors.filter(message => !/WebSocket|\[vite\]/.test(message)), [])
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), images: outRead.images, productionBuild: production }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
