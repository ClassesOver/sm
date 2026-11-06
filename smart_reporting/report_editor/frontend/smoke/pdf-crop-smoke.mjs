import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_CROP_SMOKE_PORT ?? 4198), base = `http://127.0.0.1:${port}`
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const python = input => {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from pypdf import PdfReader
from smart_reporting.reporting.tests.test_pdf_crop import crop_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create': print(base64.b64encode(crop_fixture(unit=2,page_count=4)).decode())
else:
 b=base64.b64decode(p['bytes'])
 if p['mode']=='inspect': print(json.dumps(inspect_pdf(b)))
 elif p['mode']=='patch':
  result=patch_pdf_with_receipt(b,p['operations']);result['bytes']=base64.b64encode(result.pop('content')).decode();print(json.dumps(result))
 elif p['mode']=='verify':
  source=PdfReader(BytesIO(base64.b64decode(p['source'])));saved=PdfReader(BytesIO(b))
  order=[3,1,0];assert len(saved.pages)==3
  for page,index in zip(saved.pages,order,strict=True):
   old=source.pages[index]
   assert list(page.mediabox)==list(old.mediabox)
   assert page.get_contents().get_data()==old.get_contents().get_data()
   assert page.get('/UserUnit')==2
   assert 'HIDDEN CONTENT STILL EXISTS' in page.extract_text()
  notes=[str(a.get_object().get('/Contents')) for a in saved.pages[2].get('/Annots',[]) if str(a.get_object().get('/Subtype'))=='/Text'];assert notes==['keep note']
  fields=saved.get_fields();assert fields['contact']['/V']=='Ada';assert fields['consent']['/V']=='/Off';assert fields['plan']['/V']=='/pro'
  print(json.dumps({'pages':[{'cropBox':[float(v) for v in page.cropbox],'rotation':int(page.get('/Rotate',0)),'mediaBox':[float(v) for v in page.mediabox]} for page in saved.pages],'formValues':{name:str(field.get('/V')) for name,field in fields.items()},'notes':notes,'contentStreamsPreserved':True,'userUnitPreserved':True}))
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
  await page.route('**/reports/v1/native/crop-fixture/*/api/preview', route => { const model = revision(route) === 1 ? sourceModel : inspect(saved); return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model, appliedOperationIndices: [], skippedOperations: [] } }) })
  await page.route('**/reports/v1/native/crop-fixture/1/api/save', route => {
    payload = route.request().postDataJSON()
    const result = JSON.parse(python({ mode: 'patch', bytes: source.toString('base64'), operations: payload.operations }))
    saved = Buffer.from(result.bytes, 'base64')
    return route.fulfill({ json: { documentId: 'crop-fixture', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { pdf: { downloadUrl: '/crop-download.pdf', size: saved.length, sha256: hash(saved) } },
      editor: { openUrl: '/reports/v1/native/crop-fixture/2' }, validation: { ok: false, issues: [{ code: 'manual_review', message: '裁切后请核验内容；下载仍可用' }] } } })
  })
  await page.route('**/crop-download.pdf', route => route.fulfill({ body: saved, contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/crop-fixture\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async revision => {
    await page.goto(`${base}/reports/v1/native/crop-fixture/${revision}`)
    try { await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 }); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length >= 3 && !document.querySelector('[data-source-command-id="genoffice.pdf.page.crop"]')?.disabled) }
    catch { throw new Error(JSON.stringify({ errors, body: await page.locator('body').innerText() })) }
  }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('crop-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const selectPage = async n => {
    await page.locator('[data-pdf-ribbon-tab="home"]').click()
    const jump = page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]'); await jump.fill(String(n)); await jump.press('Enter')
    await page.locator('[data-pdf-ribbon-tab="page"]').click()
  }
  const cropButton = page.locator('[data-source-command-id="genoffice.pdf.page.crop"]')
  const dialog = page.getByRole('dialog', { name: '裁切当前页面' })
  const applyCrop = async margins => {
    await cropButton.click()
    for (const [i, label] of ['左侧裁去 (%)', '顶部裁去 (%)', '右侧裁去 (%)', '底部裁去 (%)'].entries()) await dialog.getByLabel(label, { exact: true }).fill(String(margins[i]))
    await dialog.getByRole('button', { name: '应用裁切', exact: true }).click()
  }
  await open(1); await selectPage(1)
  await cropButton.click(); assert.match(await dialog.innerText(), /只隐藏边缘内容/)
  await dialog.getByRole('button', { name: '取消', exact: true }).click(); assert.deepEqual(await ops(), [])
  await applyCrop([0, 0, 0, 0]); assert.deepEqual(await ops(), [])
  await applyCrop([60, 0, 40, 0]); assert.equal(await dialog.isVisible(), true); assert.deepEqual(await ops(), [])
  assert.match(await dialog.getByRole('alert').innerText(), /不能覆盖整个页面/)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  const dimensions = []
  for (let n = 1; n <= 4; n++) {
    await selectPage(n)
    const before = await page.locator('.pdf-page.is-active .pdf-page-content').evaluate(node => [parseFloat(node.style.width), parseFloat(node.style.height)])
    await applyCrop([10, 20, 30, 10]); await dialog.waitFor({ state: 'hidden' })
    await page.waitForFunction(before => { const node = document.querySelector('.pdf-page.is-active .pdf-page-content'); return node && Math.abs(parseFloat(node.style.width) / before[0] - .6) < 1e-6 && Math.abs(parseFloat(node.style.height) / before[1] - .7) < 1e-6 }, before)
    const after = await page.locator('.pdf-page.is-active .pdf-page-content').evaluate(node => [parseFloat(node.style.width), parseFloat(node.style.height)])
    dimensions.push({ sourceIndex: n - 1, before, after })
  }
  const allCropped = await ops(); assert.equal(allCropped.filter(op => op.kind === 'cropPage').length, 4)
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.equal((await ops()).filter(op => op.kind === 'cropPage').length, 3)
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); assert.deepEqual(await ops(), allCropped)
  await page.reload(); await page.locator('.pdf-ribbon').waitFor(); assert.deepEqual(await ops(), allCropped)
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 4)
  await selectPage(1); await applyCrop([10, 0, 0, 0]); await dialog.waitFor({ state: 'hidden' })
  await selectPage(2); await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click()
  await selectPage(3); await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click()
  await page.locator('[data-pdf-ribbon-tab="fillForm"]').click()
  await page.getByLabel('contact', { exact: true }).fill('Ada'); await page.getByLabel('contact', { exact: true }).dispatchEvent('change')
  await page.getByLabel('consent', { exact: true }).uncheck(); await page.getByLabel('plan', { exact: true }).selectOption('pro')
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 30000 })
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl)); assert.deepEqual(downloaded, saved)
  const readback = JSON.parse(python({ mode: 'verify', bytes: downloaded.toString('base64'), source: source.toString('base64') }))
  const expected = [[48, 158, 314, 434], [86, 66, 352, 342], [70.8, 66, 276, 388]]
  for (const [i, identity] of readback.pages.entries()) { assert.equal(identity.rotation, [270, 180, 0][i]); identity.cropBox.forEach((value, j) => assert.ok(Math.abs(value - expected[i][j]) < 1e-6)) }
  assert.deepEqual(payload.operations.find(op => op.kind === 'reorderPages').pageIds, [3, 1, 0].map(i => sourceModel.pages[i].pageId))
  assert.equal(payload.operations.filter(op => op.kind === 'cropPage').length, 4)
  await open(2); await selectPage(1)
  const reopened = await page.locator('.pdf-page.is-active .pdf-page-content').evaluate(node => [parseFloat(node.style.width), parseFloat(node.style.height)])
  assert.deepEqual(reopened, [552, 532])
  readOnly = true; await page.reload(); await page.locator('.pdf-ribbon').waitFor(); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3)
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); assert.equal(await cropButton.isDisabled(), true)
  await cropButton.evaluate(button => button.dispatchEvent(new MouseEvent('click', { bubbles: true }))); assert.equal(await dialog.isVisible(), false)
  assert.deepEqual(errors, [])
  const evidence = { ok: true, browserVersion: browser.version(), sourceSha256: hash(source), outputSha256: hash(downloaded), dimensions, readback, operations: payload.operations, desktopVerified: false, applicationImageVerified: false, provenance: 'production static UI; substituted auth/revision routes; real packed PDF engine; independent pypdf' }
  if (process.env.PDF_CROP_EVIDENCE_DIR) { const dir = process.env.PDF_CROP_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); await writeFile(`${dir}/source.pdf`, source); await writeFile(`${dir}/downloaded.pdf`, downloaded); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)) }
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
