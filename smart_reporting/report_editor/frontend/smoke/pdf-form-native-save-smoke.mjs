import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd()
const repo = new URL('../../../', `file://${frontend}/`).pathname
const engine = `${repo}/smart_reporting/reporting/pdf_engine`
const port = Number(process.env.PDF_FORM_SMOKE_PORT ?? 4198)
const baseUrl = `http://127.0.0.1:${port}`
const mediaType = 'application/pdf'
const runBridge = (mode, bytes, operations = []) => {
  const result = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', `
import { readFileSync } from 'node:fs'
import { PDFDocument, PDFName, PDFString } from 'pdf-lib'
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
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    await delay(250)
  }
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()) })
  await page.route('**/reports/v1/native/fixture-pdf/1/api/context', route => route.fulfill({ json: {
    context: { documentId: 'fixture-pdf', format: 'pdf', revision: 1, parentRevision: null,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'fixture.pdf', size: sourceBytes.length, sha256: sourceSha, mediaType }, origin: 'upload' },
    csrfToken: 'fixture-csrf', capabilities: { pdf_editor: true }, editingEnabled: true,
  } }))
  await page.route('**/reports/v1/native/fixture-pdf/1/api/file', route => route.fulfill({ body: sourceBytes, contentType: mediaType }))
  await page.route('**/reports/v1/native/fixture-pdf/1/api/preview', route => route.fulfill({ json: {
    sourceSha256: sourceSha, draftSha256: sourceSha, model: sourceModel, appliedOperationIndices: [], skippedOperations: [],
  } }))
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
  await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-pdf/1'))
  await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
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
  await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click()
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
  const independentOrder = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); print(json.dumps([[float(p.mediabox.width), float(p.mediabox.height)] for p in r.pages]))'], { input: downloadedBytes, encoding: 'utf8' })
  if (independentOrder.status !== 0) throw new Error(independentOrder.stderr || `pypdf exited ${independentOrder.status}`)
  assert.deepEqual(JSON.parse(independentOrder.stdout), [[500, 400], [612, 792]])
  const values = Object.fromEntries(outputModel.formFields.map(field => [field.name, field.value]))
  assert.deepEqual(values, { 'contact.name': 'Ada Lovelace', consent: true, plan: 'pro', region: 'south' })
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  assert.equal(runBridge('inspect', sourceBytes).formFields.find(field => field.name === 'contact.name').value, '')
  assert.deepEqual(savePayload.operations.filter(operation => operation.kind === 'setFormValue').map(({ kind, name, fieldId, expectedFieldSha256 }) => ({ kind, name, fieldId, expectedFieldSha256 })),
    ['contact.name', 'consent', 'plan', 'region'].map(name => {
      const field = sourceModel.formFields.find(item => item.name === name)
      return { kind: 'setFormValue', name, fieldId: field.fieldId, expectedFieldSha256: field.expectedFieldSha256 }
    }))
  assert.deepEqual(savePayload.operations.find(operation => operation.kind === 'reorderPages').pageIds, sourceModel.pages.map(page => page.pageId).reverse())
  assert.deepEqual(pageErrors, [])
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), values, reversedPageSizes: JSON.parse(independentOrder.stdout), operations: savePayload.operations.length }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
