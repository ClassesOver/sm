import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_COMMENTS_SMOKE_PORT ?? 4207), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import json,sys,base64
from io import BytesIO
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,DictionaryObject,ArrayObject,NumberObject,TextStringObject
from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create':
 b=size_fixture();model=inspect_pdf(b);b=patch_pdf(b,[{'kind':'addTextAnnotation','pageId':model['pages'][0]['pageId'],'rect':[100,100,120,118],'text':'control note'},{'kind':'addTextAnnotation','pageId':model['pages'][2]['pageId'],'rect':[100,100,120,118],'text':'far note'}])
 w=PdfWriter(clone_from=PdfReader(BytesIO(b)));annots=w.pages[0]['/Annots'];root=next(ref for ref in annots if ref.get_object().get('/Subtype')=='/Text');root.get_object()[NameObject('/T')]=TextStringObject('Alice');root.get_object()[NameObject('/CreationDate')]=TextStringObject('D:20200101000000Z')
 for ref in annots:
  if ref.get_object().get('/Contents')=='control note':ref.get_object()[NameObject('/T')]=TextStringObject('Carol')
 reply=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Text'),NameObject('/Rect'):ArrayObject([NumberObject(x) for x in [80,80,100,98]]),NameObject('/Contents'):TextStringObject('reply needle'),NameObject('/T'):TextStringObject('Bob'),NameObject('/IRT'):root,NameObject('/RT'):NameObject('/R'),NameObject('/P'):w.pages[0].indirect_reference})
 annots.append(w._add_object(reply));out=BytesIO();w.write(out);b=out.getvalue();print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b)}))
elif p['mode']=='inspect':print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();r['model']=inspect_pdf(base64.b64decode(r['bytes']));print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const fixture = python({ mode: 'create' }), source = Buffer.from(fixture.bytes, 'base64'), revisions = new Map([[1, source]]), payloads = []
let browser, readonly = false
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = []
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  await page.addInitScript(() => {
    window.__annotationReads = []; window.__firstDoc = null; window.__delayPreview = false; window.__failFar = true; window.__released = false
    const original = Worker.prototype.postMessage
    Worker.prototype.postMessage = function(message, ...args) {
      if (message?.action === 'GetTextContent' && window.__delayPreview && message.sourceName !== window.__firstDoc) { setTimeout(() => original.call(this, message, ...args), 200); return }
      if (message?.action === 'GetAnnotations') {
        window.__firstDoc ??= message.sourceName
        window.__annotationReads.push({ doc: message.sourceName, page: message.data.pageIndex })
        if (message.data.pageIndex === 2 && window.__failFar) {
          window.__failFar = false
          queueMicrotask(() => this.dispatchEvent(new MessageEvent('message', { data: { sourceName: message.targetName, targetName: message.sourceName, callback: 2, callbackId: message.callbackId, reason: { name: 'UnknownErrorException', message: 'fixture annotations unavailable', details: 'test fault' } } })))
          return
        }
        if (message.data.pageIndex === 1 && !window.__released) { const release = () => { window.__released = true; original.call(this, message, ...args) }; if (location.pathname.endsWith('/1')) window.__releaseAnnotationRead = release; else setTimeout(release, 150); return }
      }
      return original.call(this, message, ...args)
    }
  })
  const revision = route => Number(route.request().url().match(/comments-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/comments-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'comments-fixture', revision: revision(route), parentRevision: revision(route) === 1 ? null : revision(route) - 1, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'notes.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/comments-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/comments-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes, ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/comments-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations); assert.equal(input.expectedPreviewDigest, result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes, 'base64'), contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': result.previewDigest } })
  })
  await page.route('**/reports/v1/native/comments-fixture/*/api/save', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations), next = revision(route) + 1, bytes = Buffer.from(result.bytes, 'base64'); payloads.push(input); revisions.set(next, bytes)
    return route.fulfill({ json: { documentId: 'comments-fixture', revision: next, parentRevision: next - 1, revisionRegistered: true, artifacts: { pdf: { downloadUrl: `/note-download-${next}.pdf`, size: bytes.length, sha256: sha(bytes) } }, editor: { openUrl: `/reports/v1/native/comments-fixture/${next}` }, validation: { ok: false, issues: [{ code: 'manual_review', message: '请核验内容；下载仍可用' }] } } })
  })
  await page.route(/\/note-download-\d+\.pdf$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/note-download-(\d+)/)[1])), contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/comments-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => { await page.goto(`${base}/reports/v1/native/comments-fixture/${n}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 }) }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('comments-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const panel = page.getByRole('complementary', { name: '全文便签批注' }), filter = page.getByLabel('筛选便签批注')
  const toggle = page.locator('[data-source-command-id="genoffice.pdf.view.navigation.comments"]')
  const roots = panel.locator('.pdf-comment-list > [role="listitem"]')
  const loaded = () => page.waitForFunction(() => !document.querySelector('.pdf-comments-sidebar [role="status"]')?.textContent?.includes('载入中'))
  await open(1); assert.deepEqual(await ops(), [])
  await page.locator('[data-pdf-ribbon-tab="view"]').click(); await toggle.click()
  await page.waitForFunction(() => window.__annotationReads.some(row => row.page === 1))
  await toggle.click(); assert.equal(await panel.isVisible(), false); await page.evaluate(() => window.__releaseAnnotationRead()); await page.waitForFunction(() => window.__released); await toggle.click()
  await page.waitForFunction(() => document.querySelector('.pdf-comments-sidebar [role="status"]')?.textContent?.includes('1 页未能读取'))
  assert.equal(await roots.count(), 2)
  await panel.getByRole('button', { name: '重试未读页面', exact: true }).click(); await loaded(); assert.equal(await roots.count(), 3)
  const readCounts = await page.evaluate(() => window.__annotationReads)
  const docName = readCounts[0].doc
  assert.deepEqual(readCounts.filter(row => row.doc === docName).map(row => row.page), [0,1,2,2])
  await toggle.click(); assert.equal(await panel.isVisible(), false); await toggle.click(); await loaded()
  assert.deepEqual(await page.evaluate(() => window.__annotationReads), readCounts)
  assert.equal(await page.locator('.pdf-thumbnails').isVisible(), false); assert.equal(await page.locator('.pdf-outline').isVisible(), false)
  await filter.fill('BOB'); assert.equal(await roots.count(), 1); await roots.first().locator('summary').click()
  assert.ok((await roots.first().locator('.pdf-comment-row').allTextContents()).some(text => text.includes('reply needle')))
  await roots.first().locator('.pdf-comment-row').first().click()
  const selected = page.locator('.pdf-comment-selected'); await selected.waitFor(); assert.ok((await selected.innerText()).includes('keep note'))
  assert.equal(await selected.getByRole('button', { name: '编辑便签' }).isDisabled(), true)
  await filter.fill('Carol'); await roots.first().locator('.pdf-comment-row').first().click(); await page.waitForFunction(() => document.querySelector('.pdf-comment-selected p')?.textContent === 'control note')
  await selected.getByRole('button', { name: '编辑便签' }).click(); await page.getByLabel('编辑便签正文').fill('edited through sidebar'); await page.getByRole('button', { name: '应用便签修改', exact: true }).click(); await loaded()
  await filter.fill('edited through'); assert.equal(await roots.count(), 1)
  await page.locator('[data-pdf-ribbon-tab="home"]').click(); await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); await loaded(); assert.equal(await roots.count(), 0)
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); await loaded(); assert.equal(await roots.count(), 1)
  await roots.first().locator('.pdf-comment-row').first().click(); await selected.getByRole('button', { name: '删除便签' }).click(); await loaded(); assert.equal(await roots.count(), 0)
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); await loaded(); assert.equal(await roots.count(), 1)
  const jump = page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]'); await jump.fill('2'); await jump.press('Enter')
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.note"]').click(); await page.getByLabel('文字批注内容').fill('pending via sidebar')
  await page.locator('.pdf-page-content').nth(1).click({ position: { x: 120, y: 90 } }); await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-note').length === 1); await loaded()
  await filter.fill('pending via'); assert.equal(await roots.count(), 1); await roots.first().locator('.pdf-comment-row').first().click(); await page.waitForFunction(() => document.querySelector('.pdf-comment-selected')?.classList.contains('pdf-pending-note'))
  await selected.getByRole('button', { name: '编辑便签' }).click(); await page.getByLabel('编辑便签正文').fill('pending updated'); await page.getByRole('button', { name: '应用便签修改', exact: true }).click(); await loaded()
  await filter.fill('far note'); assert.equal(await roots.count(), 1); await roots.first().locator('.pdf-comment-row').first().click(); assert.equal(await page.locator('.pdf-page.is-active').getAttribute('data-page-id'), fixture.model.pages[2].pageId)
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click(); await loaded(); await roots.first().locator('.pdf-comment-row').first().click()
  assert.match(await roots.first().innerText(), /第 1 页/)
  await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click(); await loaded(); assert.equal(await roots.count(), 0)
  await filter.fill(''); assert.equal(await roots.count(), 3)
  const beforeView = await ops()
  await page.locator('[data-pdf-ribbon-tab="view"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.thumbnails"]').click(); assert.equal(await panel.isVisible(), false)
  await toggle.click(); await loaded(); assert.equal(await filter.inputValue(), ''); assert.deepEqual(await ops(), beforeView)
  await page.evaluate(() => window.__delayPreview = true)
  await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '校验当前修改', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true'); assert.equal(await roots.count(), 0); assert.match(await panel.locator('[role="status"]').innerText(), /载入中/); await loaded()
  await filter.fill('pending updated'); assert.equal(await roots.count(), 1); await roots.first().locator('.pdf-comment-row').first().click(); assert.equal(await selected.getByRole('button', { name: '编辑便签' }).isDisabled(), true)
  await page.getByRole('button', { name: '返回原稿编辑', exact: true }).click(); await loaded(); await roots.first().locator('.pdf-comment-row').first().click(); await page.waitForFunction(() => document.querySelector('.pdf-comment-selected')?.classList.contains('pdf-pending-note'))
  assert.deepEqual(await ops(), beforeView)
  await page.locator('[data-action="save"]').click(); await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 30000 })
  const link = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href'), downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], link)); assert.deepEqual(downloaded, revisions.get(2))
  readonly = true; await page.goto(`${base}/reports/v1/native/comments-fixture/2`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 2)
  await page.locator('[data-pdf-ribbon-tab="view"]').click(); await toggle.click(); await loaded(); await filter.fill('edited through'); await roots.first().locator('.pdf-comment-row').first().click()
  assert.equal(await selected.getByRole('button', { name: '编辑便签' }).isDisabled(), true)
  await page.setViewportSize({ width: 390, height: 844 }); assert.ok(await panel.getByRole('button', { name: '关闭批注侧栏' }).isVisible()); await panel.getByRole('button', { name: '关闭批注侧栏' }).click(); assert.equal(await panel.isVisible(), false)
  assert.deepEqual(errors, [])
  const evidence = { ok: true, browserVersion: browser.version(), sourceSha256: sha(source), downloadedSha256: sha(downloaded), initialReads: readCounts, wholeDocumentThreads: true, failureRetryAndCache: true, filterReplyAndAuthor: true, exactNativeAndPendingCardNavigation: true, safeEditUndoRedo: true, reverseDeletePageProjection: true, actualPreviewReadonlyAndReturn: true, viewDoesNotMutateDraft: true, readonlyReopenAndMobileClose: true, operations: payloads[0].operations, provenance: 'production static UI, real packed engine/PDF.js and worker-message failure injection; substituted authorization/revision routes; no production/desktop/full-image claim' }
  if (process.env.PDF_COMMENTS_EVIDENCE_DIR) { const dir = process.env.PDF_COMMENTS_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); await writeFile(`${dir}/source.pdf`, source); await writeFile(`${dir}/downloaded.pdf`, downloaded); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)); await page.screenshot({ path: `${dir}/mobile.png`, fullPage: true }) }
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
