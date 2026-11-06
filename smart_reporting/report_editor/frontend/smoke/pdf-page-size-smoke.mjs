import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_SIZE_SMOKE_PORT ?? 4200), base = `http://127.0.0.1:${port}`
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const python = input => {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, RectangleObject
from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create': print(base64.b64encode(size_fixture()).decode())
else:
 b=base64.b64decode(p['bytes'])
 if p['mode']=='inspect': print(json.dumps(inspect_pdf(b)))
 elif p['mode']=='patch':
  result=patch_pdf_with_receipt(b,p['operations']);result['bytes']=base64.b64encode(result.pop('content')).decode();print(json.dumps(result))
 elif p['mode']=='verify':
  source=PdfReader(BytesIO(base64.b64decode(p['source'])));saved=PdfReader(BytesIO(b));order=[2,0];assert len(saved.pages)==2
  for page,index in zip(saved.pages,order,strict=True):
   old=source.pages[index];rot=int(page.get('/Rotate',0));tw,th=(842,595) if rot in [90,270] else (595,842);k=min(tw/400,th/500)
   assert abs(float(page.mediabox.width)-tw)<1e-6 and abs(float(page.mediabox.height)-th)<1e-6
   assert list(page.cropbox)==list(page.mediabox)
   assert page.extract_text()==old.extract_text()
   for before,after in zip(old.get('/Annots',[]),page.get('/Annots',[]),strict=True):
    for x,y in zip(before.get_object()['/Rect'],after.get_object()['/Rect'],strict=True):assert abs(float(x)*k-float(y))<1e-6
  fields=saved.get_fields();assert fields['contact']['/V']=='Ada';assert fields['consent']['/V']=='/Off';assert fields['plan']['/V']=='/pro'
  print(json.dumps({'pages':[{'mediaBox':[float(v) for v in page.mediabox],'cropBox':[float(v) for v in page.cropbox],'rotation':int(page.get('/Rotate',0))} for page in saved.pages],'formValues':{name:str(field.get('/V')) for name,field in fields.items()},'textPreserved':True,'annotationsScaled':True}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python status ${result.status}`)
  return result.stdout.trim()
}
const source = Buffer.from(python({ mode: 'create' }), 'base64')
const inspect = bytes => JSON.parse(python({ mode: 'inspect', bytes: bytes.toString('base64') }))
const sourceModel = inspect(source)
let saved, payload, readOnly = false, browser
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  const revision = route => route.request().url().includes('/1/api/') ? 1 : 2
  const active = route => revision(route) === 1 ? source : saved
  await page.route('**/reports/v1/native/crop-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'crop-fixture', format: 'pdf', revision: revision(route), parentRevision: revision(route) === 1 ? null : 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'crop.pdf', size: active(route).length, sha256: hash(active(route)), mediaType: 'application/pdf' }, origin: 'upload' },
    csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readOnly,
  } }))
  await page.route('**/reports/v1/native/crop-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  const patch = (bytes, operations) => JSON.parse(python({ mode: 'patch', bytes: bytes.toString('base64'), operations }))
  await page.route('**/reports/v1/native/crop-fixture/*/api/preview', route => {
    const bytes = active(route), operations = route.request().postDataJSON()?.operations ?? []
    const receipt = operations.length ? patch(bytes, operations) : null
    const output = receipt ? Buffer.from(receipt.bytes, 'base64') : bytes
    return route.fulfill({ json: { sourceSha256: hash(bytes), draftSha256: hash(output), model: inspect(output), appliedOperationIndices: receipt?.appliedOperationIndices ?? [], skippedOperations: receipt?.skippedOperations ?? [], previewDigest: receipt?.previewDigest } })
  })
  await page.route('**/reports/v1/native/crop-fixture/*/api/preview.pdf', route => {
    const request = route.request().postDataJSON(), receipt = patch(active(route), request.operations)
    assert.equal(request.expectedPreviewDigest, receipt.previewDigest)
    return route.fulfill({ body: Buffer.from(receipt.bytes, 'base64'), contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': receipt.previewDigest } })
  })
  await page.route('**/reports/v1/native/crop-fixture/1/api/save', route => {
    payload = route.request().postDataJSON()
    const result = JSON.parse(python({ mode: 'patch', bytes: source.toString('base64'), operations: payload.operations }))
    saved = Buffer.from(result.bytes, 'base64')
    return route.fulfill({ json: { documentId: 'crop-fixture', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { pdf: { downloadUrl: '/crop-download.pdf', size: saved.length, sha256: hash(saved) } },
      editor: { openUrl: '/reports/v1/native/crop-fixture/2' }, validation: { ok: false, issues: [{ code: 'manual_review', message: '页面尺寸变更后请核验内容；下载仍可用' }] } } })
  })
  await page.route('**/crop-download.pdf', route => route.fulfill({ body: saved, contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/crop-fixture\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async revision => {
    await page.goto(`${base}/reports/v1/native/crop-fixture/${revision}`)
    try { await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 }); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length >= 2 && !document.querySelector('[data-source-command-id="genoffice.pdf.page.size"]')?.disabled) }
    catch { throw new Error(JSON.stringify({ errors, body: await page.locator('body').innerText() })) }
  }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('crop-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const selectPage = async n => {
    await page.locator('[data-pdf-ribbon-tab="home"]').click()
    const jump = page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]'); await jump.fill(String(n)); await jump.press('Enter')
    await page.locator('[data-pdf-ribbon-tab="page"]').click()
  }
  const sizeButton = page.locator('[data-source-command-id="genoffice.pdf.page.size"]')
  const sizeDialog = page.getByRole('dialog', { name: '页面尺寸', exact: true })
  await open(1); await selectPage(1)
  await sizeButton.click(); assert.match(await sizeDialog.innerText(), /重置裁切范围/)
  assert.deepEqual(await sizeDialog.locator('button').allTextContents(), ['A3', 'A4', 'A5', 'Letter', 'Legal', '取消'])
  await sizeDialog.getByRole('button', { name: '取消', exact: true }).click(); assert.deepEqual(await ops(), [])
  await page.locator('[data-pdf-ribbon-tab="fillForm"]').click()
  await page.getByLabel('contact', { exact: true }).fill('Ada'); await page.getByLabel('contact', { exact: true }).dispatchEvent('change')
  await page.getByLabel('consent', { exact: true }).uncheck(); await page.getByLabel('plan', { exact: true }).selectOption('pro')
  await selectPage(1); await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click()
  await selectPage(2); await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click()
  const beforeSize = await ops()
  await sizeButton.click(); await sizeDialog.getByRole('button', { name: 'A4', exact: true }).click()
  try { await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true' && document.querySelectorAll('.pdf-page').length === 2 && [...document.querySelectorAll('.pdf-page-content')].every(node => Math.abs(parseFloat(node.style.width) - 595) < 1e-6 && Math.abs(parseFloat(node.style.height) - 842) < 1e-6), null, { timeout: 30000 }) }
  catch { throw new Error(JSON.stringify({ errors, body: await page.locator('body').innerText() })) }
  const sized = await ops(); assert.deepEqual(sized.slice(beforeSize.length), [{ kind: 'setPageSize', preset: 'A4' }])
  const dimensions = await page.locator('.pdf-page-content').evaluateAll(nodes => nodes.map(node => [parseFloat(node.style.width), parseFloat(node.style.height)]))
  await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '返回原稿编辑', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'false')
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); assert.equal(await page.locator('[data-source-command-id="genoffice.pdf.page.crop"]').isDisabled(), true)
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.deepEqual(await ops(), beforeSize)
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); assert.deepEqual(await ops(), sized)
  await page.reload(); await page.locator('.pdf-ribbon').waitFor(); assert.deepEqual(await ops(), sized)
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 2)
  await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '校验当前修改', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true' && [...document.querySelectorAll('.pdf-page-content')].every(node => parseFloat(node.style.width) === 595))
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 30000 })
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl)); assert.deepEqual(downloaded, saved)
  const readback = JSON.parse(python({ mode: 'verify', bytes: downloaded.toString('base64'), source: source.toString('base64') }))
  assert.deepEqual(readback.pages.map(identity => identity.rotation), [180, 90])
  assert.deepEqual(payload.operations.find(op => op.kind === 'reorderPages').pageIds, [2, 0].map(i => sourceModel.pages[i].pageId))
  assert.equal(payload.operations.filter(op => op.kind === 'setPageSize').length, 1)
  await open(2); await selectPage(1)
  const reopened = await page.locator('.pdf-page.is-active .pdf-page-content').evaluate(node => [parseFloat(node.style.width), parseFloat(node.style.height)])
  assert.deepEqual(reopened, [595, 842])
  readOnly = true; await page.reload(); await page.locator('.pdf-ribbon').waitFor(); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 2)
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); assert.equal(await sizeButton.isDisabled(), true)
  await sizeButton.evaluate(button => button.dispatchEvent(new MouseEvent('click', { bubbles: true }))); assert.equal(await sizeDialog.isVisible(), false)
  assert.deepEqual(errors, [])
  const evidence = { ok: true, browserVersion: browser.version(), sourceSha256: hash(source), outputSha256: hash(downloaded), dimensions, readback, operations: payload.operations, desktopVerified: false, applicationImageVerified: false, provenance: 'production static UI; substituted auth/revision routes; real packed PDF engine; independent pypdf' }
  if (process.env.PDF_SIZE_EVIDENCE_DIR) { const dir = process.env.PDF_SIZE_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); await writeFile(`${dir}/source.pdf`, source); await writeFile(`${dir}/downloaded.pdf`, downloaded); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)) }
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
