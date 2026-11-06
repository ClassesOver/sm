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
const port = Number(process.env.PDF_ROTATE_SMOKE_PORT ?? process.env.PDF_FORM_SMOKE_PORT ?? 4196)
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
const production = process.env.PDF_ROTATE_SMOKE_PRODUCTION !== '0'
const server = production
  ? spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  : spawn(process.execPath, ['--input-type=module', '-e', `import { createServer } from 'vite'; const server = await createServer({ server: { host: '127.0.0.1', port: ${port}, strictPort: true, hmr: false } }); await server.listen()`], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
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
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.home.properties.documentProperties"]').click()
  await page.locator('.pdf-properties-panel').waitFor({ state: 'visible' })
  assert.equal(await page.locator('.pdf-properties-panel [data-property="Title"]').textContent(), 'PDF properties smoke')
  assert.equal(await page.locator('.pdf-properties-panel [data-property="Author"]').textContent(), 'Smart Reporting')
  await page.locator('[data-pdf-ribbon-tab="view"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.outline"]').click()
  await page.locator('.pdf-outline-link').filter({ hasText: 'Page Two' }).click()
  await page.waitForFunction(() => document.querySelector('.pdf-page.is-active .pdf-page-label')?.textContent?.startsWith('第 2 页'))
  const spread = page.locator('[data-source-command-id="genoffice.pdf.view.navigation.pageSpread"]')
  await spread.click()
  assert.equal(await page.locator('.pdf-document-pages').getAttribute('data-spread'), 'two')
  await spread.click()
  assert.equal(await page.locator('.pdf-document-pages').getAttribute('data-spread'), 'single')
  const initialPageWidth = await page.locator('.pdf-page.is-active .pdf-page-content').evaluate(element => Number.parseFloat(element.style.width))
  await page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.goToPage"]').fill('2')
  await page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.goToPage"]').press('Enter')
  await page.waitForFunction(() => document.querySelector('.pdf-page.is-active .pdf-page-label')?.textContent?.startsWith('第 2 页'))
  await page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.zoomOut"]').click()
  await page.waitForFunction(width => Number.parseFloat(document.querySelector('.pdf-page.is-active .pdf-page-content')?.style.width || '') < width, initialPageWidth)
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]').fill('1')
  await page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]').press('Enter')
  await page.waitForFunction(() => document.querySelector('.pdf-page.is-active .pdf-page-label')?.textContent?.startsWith('第 1 页'))
  await page.locator('[data-pdf-ribbon-tab="fillForm"]').click()
  await page.locator('[data-pdf-form-navigation="next"]').click()
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'contact.name')
  await page.locator('[data-pdf-form-navigation="previous"]').click()
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'region')
  await page.locator('[aria-label="contact.name"]').fill('Ada Lovelace')
  await page.locator('[aria-label="contact.name"]').dispatchEvent('change')
  await page.locator('[aria-label="consent"]').check()
  await page.locator('[aria-label="plan"]').selectOption('pro')
  await page.locator('[aria-label="region"]').selectOption('south')
  assert.equal(await page.locator('.pdf-form-controls [data-pdf-editable="true"]').count(), 4)
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  const jump = page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]')
  await jump.fill('2'); await jump.press('Enter')
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click()
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await jump.fill('3'); await jump.press('Enter')
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click()
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pdf'))[1]).operations)
  const beforeBulk = await readDraft()
  const bulk = page.locator('[data-source-command-id="genoffice.pdf.page.rotateAll"]')
  assert.equal(await bulk.isEnabled(), true)
  await bulk.click()
  const rotated = await readDraft()
  assert.deepEqual(rotated.slice(beforeBulk.length).map(op => [op.pageId, op.delta]), [3,1,0].map(index => [sourceModel.pages[index].pageId,90]))
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.deepEqual(await readDraft(), beforeBulk)
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); assert.deepEqual(await readDraft(), rotated)
  await page.reload(); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  assert.deepEqual(await readDraft(), rotated)
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3, null, { timeout: 30000 })
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 30000 })
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  assert.equal(new URL(downloadUrl).pathname, '/fixture-download.pdf')
  const downloadedBytes = Buffer.from(await page.evaluate(async url => {
    const response = await fetch(url)
    if (!response.ok) throw new Error(`download failed: ${response.status}`)
    return [...new Uint8Array(await response.arrayBuffer())]
  }, downloadUrl))
  assert.deepEqual(downloadedBytes, savedBytes)
  const outputModel = runBridge('inspect', downloadedBytes)
  const independentOrder = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); f=r.get_fields(); print(json.dumps({"pages":[[float(p.mediabox.width),float(p.mediabox.height),int(p.get("/Rotate",0)),[float(v) for v in p.cropbox]] for p in r.pages],"forms":{k:str(f[k].get("/V")) for k in ["contact.name","consent","plan","region"]},"radioOptions":[str(v) for v in f["plan"].get("/Opt",[])],"notes":[[i,str(a.get_object().get("/Contents")),[float(v) for v in a.get_object().get("/Rect",[])]] for i,p in enumerate(r.pages) for a in p.get("/Annots",[]) if str(a.get_object().get("/Subtype"))=="/Text"]}))'], { input: downloadedBytes, encoding: 'utf8' })
  if (independentOrder.status !== 0) throw new Error(independentOrder.stderr || `pypdf exited ${independentOrder.status}`)
  assert.deepEqual(JSON.parse(independentOrder.stdout).pages, [[700, 500, 0, [12,24,688,476]], [500, 400, 270, [12,24,488,376]], [612, 792, 90, [12,24,600,768]]])
  assert.deepEqual(JSON.parse(independentOrder.stdout).forms, { 'contact.name': 'Ada Lovelace', consent: '/Yes', plan: '/1', region: 'south' })
  assert.deepEqual(JSON.parse(independentOrder.stdout).radioOptions, ['basic','pro'])
  assert.equal(JSON.parse(independentOrder.stdout).radioOptions[Number(JSON.parse(independentOrder.stdout).forms.plan.slice(1))], 'pro')
  assert.deepEqual(JSON.parse(independentOrder.stdout).notes, [[1,'Keep native note',[30,60,50,78]]])
  const values = Object.fromEntries(outputModel.formFields.map(field => [field.name, field.value]))
  assert.deepEqual(values, { 'contact.name': 'Ada Lovelace', consent: true, plan: 'pro', region: 'south' })
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  assert.equal(runBridge('inspect', sourceBytes).formFields.find(field => field.name === 'contact.name').value, '')
  assert.deepEqual(savePayload.operations.filter(operation => operation.kind === 'setFormValue').map(({ kind, name, fieldId, expectedFieldSha256 }) => ({ kind, name, fieldId, expectedFieldSha256 })),
    ['contact.name', 'consent', 'plan', 'region'].map(name => {
      const field = sourceModel.formFields.find(item => item.name === name)
      return { kind: 'setFormValue', name, fieldId: field.fieldId, expectedFieldSha256: field.expectedFieldSha256 }
    }))
  assert.deepEqual(savePayload.operations.find(operation => operation.kind === 'reorderPages').pageIds, [3,1,0].map(index => sourceModel.pages[index].pageId))
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/2`); await page.locator('.pdf-ribbon').waitFor({ timeout:60000 })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3, null, { timeout: 30000 })
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); assert.equal(await page.locator('[data-source-command-id="genoffice.pdf.page.rotateAll"]').isEnabled(),true)
  readOnly = true; await page.reload(); await page.locator('.pdf-ribbon').waitFor({ timeout:60000 }); await page.locator('[data-pdf-ribbon-tab="page"]').click(); assert.equal(await page.locator('[data-source-command-id="genoffice.pdf.page.rotateAll"]').isDisabled(),true)
  assert.deepEqual(pageErrors, [])
  if(process.env.PDF_ROTATE_EVIDENCE_DIR){const dir=process.env.PDF_ROTATE_EVIDENCE_DIR;await mkdir(dir,{recursive:true});await writeFile(`${dir}/source.pdf`,sourceBytes);await writeFile(`${dir}/downloaded.pdf`,downloadedBytes);await writeFile(`${dir}/evidence.json`,JSON.stringify({ok:true,accepted:true,provenance:'browser authorization/revision routes substituted; real packed PDF engine and pypdf readback',desktopVerified:false,applicationImageVerified:false,sourceSha,outputSha:createHash('sha256').update(downloadedBytes).digest('hex'),operations:savePayload.operations,independentReadback:JSON.parse(independentOrder.stdout),productionBuild:production,formValues:values,browserVersion:browser.version()},null,2))}
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), values, independentReadback: JSON.parse(independentOrder.stdout), productionBuild: production, operations: savePayload.operations.length }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
