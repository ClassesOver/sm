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
const port = Number(process.env.PDF_LAYOUT_SMOKE_PORT ?? 4201)
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
import { PDFDocument, PDFName, PDFString, StandardFonts } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './bridge/operations.ts'
const input = JSON.parse(readFileSync(0, 'utf8'))
const bytes = Buffer.from(input.bytes, 'base64')
let output
if (input.mode === 'create') {
  const pdf = await PDFDocument.create()
  const font = await pdf.embedFont(StandardFonts.Helvetica)
  for (let index = 1; index <= 5; index++) pdf.addPage([612, 792]).drawText("Layout page " + index, { x: 72, y: 700, size: 28, font })
  if (process.env.PDF_LAYOUT_ANNOTATIONS === '1') {
    const field=pdf.getForm().createTextField('customer');field.addToPage(pdf.getPages()[0],{x:72,y:600,width:180,height:24});field.setText('ALICE-FORM')
    const bytes=await pdf.save(),model=await inspectPdf(bytes)
    const result=await patchPdfWithReceipt(bytes,[{kind:'addDrawing',pageId:model.pages[0].pageId,shape:'measure',from:[72,500],to:[272,500],color:[1,0,0],width:2,label:'2.00 m'}],model.sourceSha256)
    output={bytes:Buffer.from(result.bytes).toString('base64')}
  } else output = { bytes: Buffer.from(await pdf.save()).toString('base64') }
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
const production = process.env.PDF_LAYOUT_SMOKE_PRODUCTION !== '0'
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
  // 固定源 Pages ▸ 合并页面（N 合 1）/ 拆分页面：单独保存为新修订，先显示服务端实际预览。
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pdf'))?.[1] ?? '{"operations":[]}').operations)
  const readback = bytes => { const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); print(json.dumps([[round(float(p.mediabox.width)),round(float(p.mediabox.height)),round(float(p.cropbox.width)),round(float(p.cropbox.height)),p.extract_text()] for p in r.pages]))'], { input: bytes, encoding: 'utf8' }); if (result.status !== 0) throw new Error(result.stderr); return JSON.parse(result.stdout) }
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  const mergeButton = page.locator('[data-source-command-id="genoffice.pdf.page.mergePages"]')
  const splitButton = page.locator('[data-source-command-id="genoffice.pdf.page.splitPages"]')
  assert.equal(await mergeButton.isEnabled(), true)
  // 已有其他修改时禁用并说明原因
  await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click()
  await page.waitForFunction(() => document.querySelector('[data-source-command-id="genoffice.pdf.page.mergePages"]')?.disabled)
  assert.match(await mergeButton.getAttribute('title'), /单独保存/)
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.deepEqual(await readDraft(), [])
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  if (!appearances) {
  // 拆分页面：选择后显示实际预览（5 页 → 10 页），返回原文件后撤销
  await splitButton.click()
  await page.locator('.pdf-layout-dialog').waitFor({ state: 'visible' })
  await page.locator('[data-pdf-split-pages="2"]').click()
  try { await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true' && document.querySelectorAll('.pdf-page').length === 10, null, { timeout: 60000 }) }
  catch { throw new Error(JSON.stringify({ preview: await page.evaluate(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview), pages: await page.locator('.pdf-page').count(), status: await page.locator('.pdf-editor-message').textContent(), dialog: await page.locator('.pdf-layout-dialog [role=alert]').textContent(), draft: await readDraft(), previewCalls, pageErrors })) }
  assert.deepEqual(await readDraft(), [{ kind: 'splitPages', perPage: 2 }])
  // 合并页面：校验非法页数，再以 4 合 1 + 分隔线保存
  await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '返回原稿编辑' }).click()
  await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview !== 'true' && document.querySelectorAll('.pdf-page').length === 5, null, { timeout: 60000 })
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click()
  assert.deepEqual(await readDraft(), [])
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  } else { assert.equal(await splitButton.isDisabled(),true); assert.match(await splitButton.getAttribute('title'),/表单/) }
  await mergeButton.click()
  await page.locator('.pdf-layout-dialog').waitFor({ state: 'visible' })
  await page.getByLabel('每张页数').fill('17')
  await page.locator('.pdf-layout-dialog').getByRole('button', { name: '确定' }).click()
  assert.match(await page.locator('.pdf-layout-dialog [role=alert]').textContent(), /2–16/)
  await page.getByLabel('每张页数').fill('4')
  await page.getByLabel('排列顺序').selectOption('horizontal')
  await page.getByLabel('绘制分隔线').check()
  await page.locator('.pdf-layout-dialog').getByRole('button', { name: '确定' }).click()
  await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true' && document.querySelectorAll('.pdf-page').length === 2, null, { timeout: 60000 })
  assert.equal(await page.locator('.pdf-page-label').first().textContent(), '第 1 页（重排版预览）')
  const drafted = await readDraft()
  assert.deepEqual(drafted, [{ kind: 'mergePages', perSheet: 4, direction: 'horizontal', separator: true }])
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  if (process.env.PDF_LAYOUT_SCREENSHOT) await page.screenshot({ path: process.env.PDF_LAYOUT_SCREENSHOT })
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
  assert.deepEqual(savePayload.operations, drafted)
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloadedBytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.deepEqual(downloadedBytes, savedBytes)
  if (process.env.PDF_LAYOUT_OUTPUT) { await writeFile(process.env.PDF_LAYOUT_OUTPUT, downloadedBytes); await writeFile(process.env.PDF_LAYOUT_OUTPUT+'.source.pdf',sourceBytes) }
  // 独立 pypdf 回读：4 合 1 → 2 张纸，第 1 张含第 1–4 页文字、第 2 张含第 5 页；来源文件不变。
  const pagesOut = readback(downloadedBytes)
  assert.equal(pagesOut.length, 2)
  for (const index of [1, 2, 3, 4]) assert.match(pagesOut[0][4], new RegExp(`Layout page ${index}`))
  assert.match(pagesOut[1][4], /Layout page 5/)
  assert.doesNotMatch(pagesOut[1][4], /Layout page 1/)
  if (!appearances) assert.ok(previewCalls.some(operations => operations[0]?.kind === 'splitPages'))
  else { assert.match(pagesOut[0][4],/ALICE-FORM/); assert.match(pagesOut[0][4],/2\.00 m/) }
  assert.equal(readback(sourceBytes).length, 5)
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/2`); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 2, null, { timeout: 30000 })
  assert.deepEqual(pageErrors.filter(message => !/WebSocket|\[vite\]/.test(message)), [])
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), pages: pagesOut.map(item => item.slice(0, 4)), productionBuild: production }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
