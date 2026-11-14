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
const port = Number(process.env.PDF_SIGFIELD_SMOKE_PORT ?? 4207)
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
import { PDFDocument, PDFName, PDFString, PDFHexString, StandardFonts, rgb } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './bridge/operations.ts'
const input = JSON.parse(readFileSync(0, 'utf8'))
const bytes = Buffer.from(input.bytes, 'base64')
let output
if (input.mode === 'create') {
  const pdf = await PDFDocument.create()
  const font = await pdf.embedFont(StandardFonts.Helvetica)
  const first = pdf.addPage([612, 792])
  first.drawText('Contract body text', { x: 72, y: 700, size: 18, font })
  first.drawText('Party A signature:', { x: 72, y: 230, size: 12, font })
  first.drawRectangle({ x: 72, y: 120, width: 240, height: 80, borderColor: rgb(0.6, 0.6, 0.6), borderWidth: 1 })
  pdf.addPage([612, 792]).drawText('Second page stays intact', { x: 72, y: 700, size: 18, font })
  // AcroForm 签名字段（/FT /Sig），未签署
  const widget = pdf.context.register(pdf.context.obj({ FT: 'Sig', T: PDFHexString.fromText('PartyA'), Type: 'Annot', Subtype: 'Widget', Rect: [72, 120, 312, 200], F: 4, P: first.ref }))
  first.node.set(PDFName.of('Annots'), pdf.context.obj([widget]))
  pdf.catalog.set(PDFName.of('AcroForm'), pdf.context.obj({ Fields: [widget], SigFlags: 1 }))
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
const production = process.env.PDF_SIGFIELD_SMOKE_PRODUCTION !== '0'
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
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  // 固定源 Sign ▸ 放入签名字段：默认放入第一个未签署的签名字段，按字段框缩放居中，写入字段关联。
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pdf'))?.[1] ?? '{"operations":[]}').operations)
  const readback = bytes => { const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); a=[x.get_object() for x in (r.pages[0].get("/Annots") or [])]; print(json.dumps([[str(x.get("/Subtype")), str(x.get("/GenOfficeFormField","")), [round(float(v),1) for v in x.get("/Rect")], "/V" in x] for x in a]))'], { input: bytes, encoding: 'utf8' }); if (result.status !== 0) throw new Error(result.stderr); return JSON.parse(result.stdout) }
  assert.deepEqual(sourceModel.signatureFields.map(field => [field.name, field.bindable, field.widgets]), [['PartyA', true, [{ pageIndex: 0, rect: [72, 120, 312, 200] }]]])
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  // 上游签名对话框（固定源 SignatureDialog）保持不变：手绘后点“放置”；随后出现“放入位置”选择，默认首个可放入的签名字段。
  const signDialog = page.locator('dialog.pdf-signature-source-dialog')
  const drawSignature = async () => {
    await page.locator('[data-source-command-id="genoffice.pdf.annotate.signature.sign"]').click()
    await signDialog.waitFor({ state: 'visible' })
    await signDialog.getByRole('button', { name: '手绘', exact: true }).click()
    const padBox = await signDialog.locator('.pdf-sign-pad').boundingBox()
    await page.mouse.move(padBox.x + padBox.width * 0.08, padBox.y + padBox.height * 0.62); await page.mouse.down()
    for (const [x, y] of [[0.19, 0.25], [0.29, 0.69], [0.42, 0.31], [0.54, 0.62], [0.88, 0.37]]) await page.mouse.move(padBox.x + x * padBox.width, padBox.y + y * padBox.height, { steps: 3 })
    await page.mouse.up()
    await signDialog.locator('.pdf-modal-actions button.primary').click()
  }
  await drawSignature()
  const chooser = page.locator('dialog.pdf-sign-target-dialog')
  await chooser.waitFor({ state: 'visible' })
  const target = chooser.getByLabel('签名放入位置')
  assert.equal(await target.inputValue(), sourceModel.signatureFields[0].fieldId)
  assert.deepEqual(await target.locator('option').allTextContents(), ['签名字段：PartyA（第 1 页）', '在页面上拖出位置'])
  await chooser.getByRole('button', { name: '确定' }).click()
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('已将签名放入签名字段'))
  const drafted = await readDraft()
  assert.equal(drafted.length, 1)
  assert.equal(drafted[0].shape, 'ink'); assert.equal(drafted[0].width, 1.6)
  assert.deepEqual(drafted[0].signatureField, { fieldId: sourceModel.signatureFields[0].fieldId, expectedFieldSha256: sourceModel.signatureFields[0].expectedFieldSha256 })
  const points = drafted[0].paths.flat(), xs = points.filter((_, index) => index % 2 === 0), ys = points.filter((_, index) => index % 2 === 1)
  assert.ok(Math.min(...xs) >= 72 && Math.max(...xs) <= 312 && Math.min(...ys) >= 120 && Math.max(...ys) <= 200, JSON.stringify([Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]))
  // 同一字段已放入后不再提供选择：确认签名直接进入上游拖放流程（不弹出放入位置），按 Esc 退出不改草稿。
  await drawSignature()
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('请在页面上拖出签名放置区域'))
  assert.equal(await chooser.count(), 0)
  await page.keyboard.press('Escape')
  assert.deepEqual(await readDraft(), drafted)
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.deepEqual(await readDraft(), [])
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); assert.deepEqual(await readDraft(), drafted)
  await page.reload(); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  assert.deepEqual(await readDraft(), drafted)
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 1, null, { timeout: 30000 })
  await page.waitForFunction(() => !document.querySelector('[data-action="save"]')?.disabled, null, { timeout: 30000 })
  if (process.env.PDF_SIGFIELD_SCREENSHOT) await page.screenshot({ path: process.env.PDF_SIGFIELD_SCREENSHOT })
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 }).catch(async error => { console.error(await page.locator('.save-state-label').textContent(), await page.locator('.pdf-editor-message').textContent(), pageErrors); throw error })
  assert.deepEqual(savePayload.operations, drafted)
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloadedBytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.deepEqual(downloadedBytes, savedBytes)
  if (process.env.PDF_SIGFIELD_OUTPUT) await writeFile(process.env.PDF_SIGFIELD_OUTPUT, downloadedBytes)
  // 独立 pypdf 回读：签名字段控件仍无 /V；新增 Ink 关联 PartyA，范围在字段框内；来源文件不变。
  const annotations = readback(downloadedBytes)
  assert.deepEqual(annotations.map(([subtype, field, , signed]) => [subtype, field, signed]), [['/Widget', '', false], ['/Ink', 'PartyA', false]])
  const inkRect = annotations[1][2]
  assert.ok(inkRect[0] >= 70 && inkRect[2] <= 314 && inkRect[1] >= 118 && inkRect[3] <= 202, JSON.stringify(inkRect))
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/2`); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 2, null, { timeout: 30000 })
  assert.equal(runBridge('inspect', downloadedBytes).signatureFields[0].visuallySigned, true)
  assert.deepEqual(pageErrors.filter(message => !/WebSocket|\[vite\]/.test(message)), [])
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), annotations, productionBuild: production }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
