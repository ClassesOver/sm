import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_MARKUP_SMOKE_PORT ?? 4201), base = `http://127.0.0.1:${port}`
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const python = input => {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, RectangleObject, DecodedStreamObject, ArrayObject
from smart_reporting.reporting.tests.test_pdf_selection_markup import markup_source
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create':
 writer=PdfWriter(clone_from=PdfReader(BytesIO(markup_source(unit=2))))
 page=writer.pages[0];extra=DecodedStreamObject();extra.set_data(b'BT /F1 12 Tf 1 0 0 1 30 420 Tm (SECOND VISIBLE LINE) Tj ET')
 old=page.raw_get('/Contents');old=[old] if not isinstance(old,ArrayObject) else list(old)
 page[NameObject('/Contents')]=ArrayObject([*old,writer._add_object(extra)])
 out=BytesIO();writer.write(out);print(base64.b64encode(out.getvalue()).decode())
else:
 b=base64.b64decode(p['bytes'])
 if p['mode']=='inspect': print(json.dumps(inspect_pdf(b)))
 elif p['mode']=='patch':
  result=patch_pdf_with_receipt(b,p['operations']);result['bytes']=base64.b64encode(result.pop('content')).decode();print(json.dumps(result))
 elif p['mode']=='verify':
  before=PdfReader(BytesIO(base64.b64decode(p['source'])));after=PdfReader(BytesIO(b));assert len(after.pages)==2
  page=after.pages[1];old=before.pages[0];assert page.get_contents().get_data()==old.get_contents().get_data();assert page.extract_text()==old.extract_text()
  marks=[a.get_object() for a in page.get('/Annots',[]) if str(a.get_object().get('/Subtype')) in ['/Highlight','/Underline','/Squiggly','/StrikeOut']]
  assert [str(a['/Subtype']) for a in marks]==['/Underline','/Highlight','/Squiggly','/StrikeOut']
  for a in marks:
   assert len(a['/QuadPoints'])==16
   q=[float(v) for v in a['/QuadPoints']];assert abs(q[0]-25)<1 and abs(q[8]-30)<1
   assert 440<q[1]<465 and 410<q[9]<435
   assert a['/AP']['/N'].get_data()
  assert list(marks[0]['/C'])==[.17,.4,1];assert list(marks[2]['/C'])==[.13,.65,.35];assert list(marks[3]['/C'])==[.86,.22,.18]
  assert all(abs(float(a)-b)<1e-6 for a,b in zip(marks[1]['/C'],[43/255,102/255,1]))
  assert after.get_fields()['contact']['/V']==before.get_fields()['contact']['/V']
  print(json.dumps({'markups':[{'subtype':str(a['/Subtype']),'quads':[float(v) for v in a['/QuadPoints']],'color':[float(v) for v in a['/C']]} for a in marks],'textAndContentPreserved':True,'formValuesPreserved':True}))
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
    try { await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 }); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length >= 2 && !document.querySelector('[data-source-command-id="genoffice.pdf.page.rotateRight"]')?.disabled) }
    catch { throw new Error(JSON.stringify({ errors, body: await page.locator('body').innerText() })) }
  }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('crop-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const selectPage = async n => {
    await page.locator('[data-pdf-ribbon-tab="home"]').click()
    const jump = page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]'); await jump.fill(String(n)); await jump.press('Enter')
    await page.locator('[data-pdf-ribbon-tab="page"]').click()
  }
  const mark = (tab, type) => page.locator(`[data-source-command-id="genoffice.pdf.${tab}.markup.${type}"]`)
  const selectTwoLines = async () => {
    await page.waitForFunction(() => [...document.querySelectorAll('.textLayer span')].some(span => span.textContent === 'SECOND VISIBLE LINE'))
    await page.evaluate(() => {
      const spans = [...document.querySelectorAll('.textLayer span')]
      const first = spans.find(span => span.textContent === 'UNCHANGED PAGE 0'), last = spans.find(span => span.textContent === 'SECOND VISIBLE LINE')
      const range = document.createRange(); range.setStart(first.firstChild, 0); range.setEnd(last.firstChild, last.firstChild.length)
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
      document.dispatchEvent(new Event('selectionchange'))
    })
  }
  await open(1); await selectPage(1); await page.locator('[data-pdf-ribbon-tab="home"]').click()
  assert.equal(await mark('home', 'underline').isDisabled(), true)
  await selectTwoLines(); await mark('home', 'underline').click()
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-markup.pdf-underline').length === 2)
  const first = await ops(); assert.equal(first.filter(op => op.kind === 'addMarkup').length, 1)
  await mark('home', 'underline').click(); assert.deepEqual(await ops(), [])
  await mark('home', 'underline').click()
  await page.locator('[data-ribbon-command="markup-color-preset"][title="#2b66ff"]').first().click()
  await mark('home', 'highlight').click()
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); await mark('annotate', 'squiggly').click(); await mark('annotate', 'strikeout').click()
  const added = await ops(); assert.deepEqual(added.map(op => op.markupType), ['underline', 'highlight', 'squiggly', 'strikeout'])
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.equal((await ops()).length, 3)
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); assert.deepEqual(await ops(), added)
  await page.reload(); await page.locator('.pdf-ribbon').waitFor(); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3); assert.deepEqual(await ops(), added)
  await selectPage(2); await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click()
  await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '校验当前修改', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true' && document.querySelectorAll('.pdf-page').length === 2, null, { timeout: 30000 })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page-content').length === 2 && [...document.querySelectorAll('.pdf-page-content')].every(node => node.querySelector('canvas') && node.querySelector('.textLayer span')), null, { timeout: 30000 })
  const dimensions = await page.locator('.pdf-page-content').evaluateAll(nodes => nodes.map(node => [parseFloat(node.style.width), parseFloat(node.style.height)]))
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 30000 })
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl)); assert.deepEqual(downloaded, saved)
  const readback = JSON.parse(python({ mode: 'verify', bytes: downloaded.toString('base64'), source: source.toString('base64') }))
  assert.deepEqual(payload.operations.find(op => op.kind === 'reorderPages').pageIds, [2, 0].map(i => sourceModel.pages[i].pageId))
  await open(2); await selectPage(2); await page.locator('[data-pdf-ribbon-tab="home"]').click(); await selectTwoLines()
  assert.equal(await mark('home', 'underline').getAttribute('aria-pressed'), 'true'); assert.equal(await mark('home', 'underline').isDisabled(), true)
  await mark('home', 'underline').evaluate(button => button.dispatchEvent(new MouseEvent('click', { bubbles: true })))
  assert.deepEqual(await ops(), [])
  assert.match(await page.locator('.pdf-editor-message').innerText(), /尚不能移除/)
  assert.deepEqual(errors, [])
  const evidence = { ok: true, browserVersion: browser.version(), sourceSha256: hash(source), outputSha256: hash(downloaded), dimensions, readback, operations: payload.operations, desktopVerified: false, applicationImageVerified: false, provenance: 'production static UI; substituted auth/revision routes; real packed PDF engine; independent pypdf' }
  if (process.env.PDF_MARKUP_EVIDENCE_DIR) { const dir = process.env.PDF_MARKUP_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); await writeFile(`${dir}/source.pdf`, source); await writeFile(`${dir}/downloaded.pdf`, downloaded); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)) }
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
