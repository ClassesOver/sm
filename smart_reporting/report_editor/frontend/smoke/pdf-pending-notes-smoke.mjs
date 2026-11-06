import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_PENDING_NOTES_SMOKE_PORT ?? 4205), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import json,sys,base64
from io import BytesIO
from pypdf import PdfReader,PdfWriter
from smart_reporting.reporting.tests.test_pdf_selection_markup import markup_source
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create':
 b=markup_source(unit=2);print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b)}))
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
  const revision = route => Number(route.request().url().match(/pending-notes-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/pending-notes-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'pending-notes-fixture', revision: revision(route), parentRevision: revision(route) === 1 ? null : revision(route) - 1, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'notes.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/pending-notes-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/pending-notes-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes, ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/pending-notes-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations); assert.equal(input.expectedPreviewDigest, result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes, 'base64'), contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': result.previewDigest } })
  })
  await page.route('**/reports/v1/native/pending-notes-fixture/*/api/save', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations), next = revision(route) + 1, bytes = Buffer.from(result.bytes, 'base64'); payloads.push(input); revisions.set(next, bytes)
    return route.fulfill({ json: { documentId: 'pending-notes-fixture', revision: next, parentRevision: next - 1, revisionRegistered: true, artifacts: { pdf: { downloadUrl: `/note-download-${next}.pdf`, size: bytes.length, sha256: sha(bytes) } }, editor: { openUrl: `/reports/v1/native/pending-notes-fixture/${next}` }, validation: { ok: false, issues: [{ code: 'manual_review', message: '请核验内容；下载仍可用' }] } } })
  })
  await page.route(/\/note-download-\d+\.pdf$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/note-download-(\d+)/)[1])), contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/pending-notes-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => { await page.goto(`${base}/reports/v1/native/pending-notes-fixture/${n}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 }) }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('pending-notes-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const pending = page.locator('.pdf-pending-note')
  const waitPending = n => page.waitForFunction(n => document.querySelectorAll('.pdf-pending-note').length === n, n)
  const edit = async (index, text, cancel = false) => { await pending.nth(index).getByRole('button', { name: '编辑便签' }).click(); await page.getByLabel('编辑便签正文').fill(text); await page.getByRole('button', { name: cancel ? '取消' : '应用便签修改', exact: true }).click() }
  const zoomHalf = async () => { await page.locator('[data-pdf-ribbon-tab="home"]').click(); await page.getByLabel('页面缩放', { exact: true }).selectOption('0.5'); await page.waitForFunction(() => parseFloat(document.querySelector('.pdf-page-content')?.style.width || '') === 380) }
  const place = async (n, text, x = 120, y = 160) => {
    await page.locator('[data-pdf-ribbon-tab="home"]').click(); const jump = page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]'); await jump.fill(String(n)); await jump.press('Enter')
    await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.note"]').click(); await page.getByLabel('文字批注内容').fill(text)
    const holder = page.locator('.pdf-page-content').nth(n - 1); await holder.locator('canvas').waitFor(); await holder.click({ position: { x, y } })
  }
  await open(1); await zoomHalf()
  await place(1, 'same pending'); await waitPending(1)
  await place(1, 'same pending'); await waitPending(2)
  const identical = await ops(); assert.deepEqual(identical[0], identical[1])
  await pending.first().getByRole('button', { name: '删除便签' }).evaluate(node => { window.__stalePendingDelete = node })
  await pending.first().getByRole('button', { name: '删除便签' }).click(); await waitPending(1)
  const afterDelete = await ops(); await page.evaluate(() => window.__stalePendingDelete.dispatchEvent(new MouseEvent('click', { bubbles: true })))
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('草稿已变化')); assert.deepEqual(await ops(), afterDelete)
  await page.locator('[data-pdf-ribbon-tab="home"]').click(); await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); await waitPending(2)
  await edit(0, 'cancelled', true); assert.deepEqual(await ops(), identical)
  await edit(1, '待保存修改 金额 750 ✓'); await page.waitForFunction(() => [...document.querySelectorAll('.pdf-pending-note p')].some(node => node.textContent === '待保存修改 金额 750 ✓'))
  assert.equal((await ops()).length, 2); assert.equal((await ops())[0].text, 'same pending')
  await pending.first().getByRole('button', { name: '删除便签' }).click(); await waitPending(1)
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); await waitPending(2)
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); await waitPending(1)
  const edited = await ops(); await page.reload(); await waitPending(1); assert.deepEqual(await ops(), edited)
  readonly = true; await page.reload(); await waitPending(1)
  for (const control of await pending.first().locator('button').all()) assert.equal(await control.isDisabled(), true)
  await pending.first().getByRole('button', { name: '删除便签' }).evaluate(node => node.dispatchEvent(new MouseEvent('click', { bubbles: true })))
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('当前修订不支持')); assert.deepEqual(await ops(), edited)
  readonly = false; await page.reload(); await waitPending(1); await zoomHalf()
  await place(2, 'rotated pending', 80, 70); await waitPending(2)
  const withRotated = await ops(); assert.equal(withRotated[1].pageId, fixture.model.pages[1].pageId)
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click(); await waitPending(1)
  await page.locator('[data-pdf-ribbon-tab="home"]').click(); await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); await waitPending(2); assert.deepEqual(await ops(), withRotated)
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click()
  await page.locator('[data-pdf-ribbon-tab="home"]').click(); const jump = page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]'); await jump.fill('1'); await jump.press('Enter')
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click(); await waitPending(2)
  const final = await ops(); assert.equal(final.filter(op => op.kind === 'addTextAnnotation').length, 2); assert.ok(final.every(op => !['editNote', 'removeNote'].includes(op.kind)))
  await page.locator('[data-action="save"]').click(); await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 30000 })
  const link = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href'), downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], link)); assert.deepEqual(downloaded, revisions.get(2))
  await page.goto(`${base}/reports/v1/native/pending-notes-fixture/2`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 2 && document.querySelectorAll('.pdf-saved-note').length === 3, null, { timeout: 60000 })
  assert.equal(await pending.count(), 0)
  const reopened = inspect(downloaded); assert.deepEqual(reopened.pages[0].notes.map(note => note.contents), ['rotated pending']); assert.deepEqual(reopened.pages[1].notes.map(note => note.contents), ['keep note', '待保存修改 金额 750 ✓'])
  assert.deepEqual(errors, [])
  const evidence = { ok: true, browserVersion: browser.version(), sourceSha256: sha(source), downloadedSha256: sha(downloaded), identicalNotes: identical, finalOperations: final, staleDetachedControlRefused: true, modalCancelUndoRedoReload: true, readonlyForcedMutationRefused: true, pageDeleteUndoReverseIdentity: true, pendingBecomesSavedOnReopen: true, provenance: 'production static UI; substituted authorization/revision routes; actual packed engine, PDF.js and downloaded file; existing pending-only preview behavior unchanged, no byte-identical preview claim' }
  if (process.env.PDF_PENDING_NOTES_EVIDENCE_DIR) { const dir = process.env.PDF_PENDING_NOTES_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); await writeFile(`${dir}/source.pdf`, source); await writeFile(`${dir}/downloaded.pdf`, downloaded); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)); await page.screenshot({ path: `${dir}/saved-reopen.png`, fullPage: true }) }
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
