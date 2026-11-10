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
const port = Number(process.env.PDF_REDACT_SMOKE_PORT ?? 4199)
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
import { PDFDocument, PDFName, PDFString, StandardFonts } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './bridge/operations.ts'
const input = JSON.parse(readFileSync(0, 'utf8'))
const bytes = Buffer.from(input.bytes, 'base64')
let output
if (input.mode === 'create') {
  const pdf = await PDFDocument.create()
  const font = await pdf.embedFont(StandardFonts.Helvetica)
  const first = pdf.addPage([612, 792])
  first.drawText('ACCOUNT-SECRET-4711', { x: 72, y: 700, size: 18, font })
  first.drawText('Public quarterly summary', { x: 72, y: 600, size: 18, font })
  const second = pdf.addPage([612, 792])
  second.drawText('Second page stays intact', { x: 72, y: 700, size: 18, font })
  const note = pdf.context.register(pdf.context.obj({ Type: 'Annot', Subtype: 'Text', Rect: [30,60,50,78], Contents: PDFString.of('Keep native note') })); second.node.set(PDFName.of('Annots'), pdf.context.obj([note]))
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
const production = process.env.PDF_REDACT_SMOKE_PRODUCTION !== '0'
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
  // 固定源 Annotate ▸ 涂黑 / 清除涂黑 / 应用涂黑：标记区域 → 保存新修订时由 PDFium 永久移除内容（来源修订不变）。
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pdf'))?.[1] ?? '{"operations":[]}').operations)
  const extract = bytes => { const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); print(json.dumps([[p.extract_text(), [str(a.get_object().get("/Subtype")) for a in (p.get("/Annots") or [])]] for p in r.pages]))'], { input: bytes, encoding: 'utf8' }); if (result.status !== 0) throw new Error(result.stderr); return JSON.parse(result.stdout) }
  assert.match(extract(sourceBytes)[0][0], /ACCOUNT-SECRET-4711/)
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  const redact = page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.redact"]')
  const content = page.locator('.pdf-page').first().locator('.pdf-page-content')
  await content.scrollIntoViewIfNeeded()
  // 页面 612×792：秘密文字基线 y=700（屏幕约 11.6% 处），拖出覆盖整行的区域
  const dragRect = async (from, to) => {
    const box = await content.boundingBox()
    await page.mouse.move(box.x + box.width * from[0], box.y + box.height * from[1]); await page.mouse.down()
    await page.mouse.move(box.x + box.width * to[0], box.y + box.height * to[1], { steps: 4 }); await page.mouse.up()
  }
  await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.applyRedaction"]').click()
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('请先用“涂黑”工具标记'))
  await redact.click(); assert.equal(await redact.getAttribute('aria-pressed'), 'true')
  await dragRect([0.08, 0.08], [0.7, 0.14])
  await page.waitForFunction(() => document.querySelectorAll('[data-pdf-redaction]').length === 1, null, { timeout: 30000 })
  await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.clearRedaction"]').click()
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('已清除 1 处'))
  assert.deepEqual(await readDraft(), [])
  assert.equal(await page.locator('[data-pdf-redaction]').count(), 0)
  await dragRect([0.08, 0.08], [0.7, 0.14])
  await page.waitForFunction(() => document.querySelectorAll('[data-pdf-redaction]').length === 1, null, { timeout: 30000 })
  const drafted = await readDraft()
  assert.equal(drafted.length, 1)
  assert.equal(drafted[0].kind, 'redact'); assert.equal(drafted[0].pageId, sourceModel.pages[0].pageId)
  const [x1, y1, x2, y2] = drafted[0].rect
  assert.ok(x1 < 72 && x2 > 300 && y1 < 700 && y2 > 712 && y1 > 620, JSON.stringify(drafted[0].rect))
  if (process.env.PDF_REDACT_SCREENSHOT) await page.screenshot({ path: process.env.PDF_REDACT_SCREENSHOT })
  await page.reload(); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  assert.deepEqual(await readDraft(), drafted)
  await page.waitForFunction(() => document.querySelectorAll('[data-pdf-redaction]').length === 1, null, { timeout: 30000 })
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.applyRedaction"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
  assert.deepEqual(savePayload.operations, drafted)
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloadedBytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.deepEqual(downloadedBytes, savedBytes)
  if (process.env.PDF_REDACT_OUTPUT) await writeFile(process.env.PDF_REDACT_OUTPUT, downloadedBytes)
  // 独立 pypdf 回读：秘密文字不可提取，其余文字与第 2 页便签保留；来源文件不变。
  const pagesOut = extract(downloadedBytes)
  assert.equal(pagesOut.length, 2)
  assert.doesNotMatch(pagesOut[0][0], /SECRET|4711/)
  assert.match(pagesOut[0][0], /Public quarterly summary/)
  assert.match(pagesOut[1][0], /Second page stays intact/)
  assert.deepEqual(pagesOut[1][1], ['/Text'])
  assert.match(extract(sourceBytes)[0][0], /ACCOUNT-SECRET-4711/)
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/2`); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 2, null, { timeout: 30000 })
  assert.deepEqual(pageErrors.filter(message => !/WebSocket|\[vite\]/.test(message)), [])
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), pages: pagesOut, productionBuild: production }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
