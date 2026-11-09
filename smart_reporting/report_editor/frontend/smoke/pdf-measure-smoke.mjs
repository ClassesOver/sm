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
const port = Number(process.env.PDF_DRAW_SMOKE_PORT ?? 4208)
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
const production = process.env.PDF_DRAW_SMOKE_PRODUCTION !== '0'
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
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pdf'))?.[1] ?? '{"operations":[]}').operations)
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  const tool = page.locator('[data-pdf-draw-shape="measure"]')
  await tool.click()
  const drag = async (index, x1 = .2, x2 = .6) => {
    const content = page.locator('.pdf-page-content').nth(index)
    await content.scrollIntoViewIfNeeded(); await delay(250); await page.waitForFunction(index => typeof document.querySelectorAll('.pdf-page-content')[index]?.onpointerdown === 'function', index); const b = await content.boundingBox()
    await page.mouse.move(b.x + b.width * x1, b.y + b.height * .45); await page.mouse.down()
    await page.mouse.move(b.x + b.width * x2, b.y + b.height * .45, { steps: 5 }); await page.mouse.up()
  }
  const modal = page.getByRole('dialog', { name: '标定测量比例' })
  await drag(0); await modal.waitFor({ state: 'visible' })
  await modal.getByRole('button', { name: '取消' }).click()
  assert.equal((await readDraft()).length, 0)
  await drag(0); await modal.waitFor({ state: 'visible' })
  await page.getByLabel('参考线实际长度').fill('0'); await modal.getByRole('button', { name: '应用比例' }).click()
  assert.match(await modal.getByRole('alert').innerText(), /大于零/)
  await page.getByLabel('参考线实际长度').fill('2'); await page.getByLabel('测量单位').fill('米')
  await modal.getByRole('button', { name: '应用比例' }).click(); assert.match(await modal.getByRole('alert').innerText(), /ASCII/)
  await page.getByLabel('测量单位').fill('m'); await modal.getByRole('button', { name: '应用比例' }).click()
  await page.waitForFunction(() => document.querySelector('[data-pdf-measure-label]')?.textContent === '2.00 m')
  // Cancelling a requested recalibration retains the previous valid scale.
  await tool.click(); await drag(0, .2, .4); await modal.waitFor({ state: 'visible' }); await modal.getByRole('button', { name: '取消' }).click(); assert.equal((await readDraft()).length, 1)
  for (const index of [1, 2, 3]) { await drag(index); await page.waitForFunction(n => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pdf'))?.[1] ?? '{"operations":[]}').operations.length === n, index + 1) }
  const drafted = await readDraft()
  assert.equal(drafted.length, 4)
  const length = op => Math.hypot(op.to[0] - op.from[0], op.to[1] - op.from[1])
  const pointsPerM = length(drafted[0]) / 2
  for (const [index, op] of drafted.entries()) {
    assert.equal(op.pageId, sourceModel.pages[index].pageId)
    assert.equal(op.label, `${(length(op) / pointsPerM).toFixed(2)} m`)
    assert.ok(index % 2 ? Math.abs(op.to[0] - op.from[0]) < .05 : Math.abs(op.to[1] - op.from[1]) < .05)
  }
  // Active tool click recalibrates the next reference line; old labels remain unchanged.
  await tool.click(); assert.equal(await tool.getAttribute('aria-pressed'), 'true'); await drag(0, .2, .4); await modal.waitFor({ state: 'visible' })
  await page.getByLabel('参考线实际长度').fill('4'); await modal.getByRole('button', { name: '应用比例' }).click()
  await page.waitForFunction(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pdf'))?.[1] ?? '{"operations":[]}').operations.length === 5)
  const finalDraft = await readDraft(); assert.equal(finalDraft[4].label, '4.00 m'); assert.deepEqual(finalDraft.slice(0, 4), drafted)
  if (process.env.PDF_DRAW_SCREENSHOT) await page.screenshot({ path: process.env.PDF_DRAW_SCREENSHOT })
  await page.reload(); await page.locator('.pdf-ribbon').waitFor(); await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  await tool.click(); await drag(0); await modal.waitFor({ state: 'visible' })
  await page.keyboard.press('Escape'); assert.deepEqual(await readDraft(), finalDraft)
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
  assert.deepEqual(savePayload.operations, finalDraft)
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.deepEqual(downloaded, savedBytes)
  if (process.env.PDF_DRAW_OUTPUT) await writeFile(process.env.PDF_DRAW_OUTPUT, downloaded)
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import sys,json
from io import BytesIO
from pypdf import PdfReader
r=PdfReader(BytesIO(sys.stdin.buffer.read()));out=[]
for page in r.pages:
 for ref in page.get('/Annots',[]):
  a=ref.get_object()
  if a.get('/Subtype')!='/Line':continue
  ap=a['/AP']['/N'].get_object()
  assert ap['/Resources']['/Font']['/F1'].get_object()['/BaseFont']=='/Helvetica'
  label=a['/Contents']; assert ('('+label+') Tj').encode() in ap.get_data()
  out.append({'page':len(out), 'label':label, 'endpoints':list(a['/L'])})
assert len(r.get_fields())==5
assert any(a.get_object().get('/Contents')=='Keep native note' for a in r.pages[1]['/Annots'])
print(json.dumps(out))
`], { input: downloaded, encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  const actual = JSON.parse(result.stdout)
  const expectedOrder = [finalDraft[0], finalDraft[4], ...finalDraft.slice(1, 4)]
  assert.deepEqual(actual.map(x => x.label), expectedOrder.map(op => op.label))
  assert.deepEqual(actual.map(x => x.endpoints), expectedOrder.map(op => [...op.from, ...op.to]))
  assert.deepEqual(pageErrors.filter(message => !/WebSocket|\[vite\]/.test(message)), [])
  readOnly = true; await page.reload(); await page.locator('.pdf-ribbon').waitFor(); await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); assert.equal(await tool.isDisabled(), true)
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloaded).digest('hex'), measurements: actual, productionBuild: production }))
} finally {
  await browser?.close(); server.kill('SIGTERM')
}
