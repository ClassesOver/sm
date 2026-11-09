import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_VIEW_SMOKE_PORT ?? 4202), base = `http://127.0.0.1:${port}`
const fixture = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,base64;from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture;from smart_reporting.reporting.delivery.pdf_native import inspect_pdf;b=size_fixture();print(json.dumps({"bytes":base64.b64encode(b).decode(),"model":inspect_pdf(b)}))'], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, encoding: 'utf8' })
if (fixture.status !== 0) throw new Error(fixture.stderr)
const sourceData = JSON.parse(fixture.stdout), source = Buffer.from(sourceData.bytes, 'base64'), model = sourceData.model, sha = bytes => createHash('sha256').update(bytes).digest('hex')
let browser
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = []
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  await page.addInitScript(() => { window.print = () => { window.__pdfPrintReceipt = [...document.querySelectorAll('.pdf-print-document canvas')].map(canvas => ({ filter: getComputedStyle(canvas).filter, pixel: [...canvas.getContext('2d').getImageData(0, 0, 1, 1).data] })); } })
  await page.route('**/reports/v1/native/view-fixture/1/api/context', route => route.fulfill({ json: {
    context: { documentId: 'view-fixture', revision: 1, parentRevision: null, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'view.pdf', size: source.length, sha256: sha(source), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: false,
  } }))
  await page.route('**/reports/v1/native/view-fixture/1/api/file', route => route.fulfill({ body: source, contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/view-fixture/1/api/preview', route => { assert.deepEqual(route.request().postDataJSON().operations, []); return route.fulfill({ json: { sourceSha256: sha(source), draftSha256: sha(source), model, appliedOperationIndices: [], skippedOperations: [] } }) })
  await page.route('**/reports/v1/native/view-fixture/1', async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  await page.goto(`${base}/reports/v1/native/view-fixture/1`)
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page-content canvas') && !document.querySelector('[data-source-command-id="genoffice.pdf.view.navigation.nightMode"]')?.disabled, null, { timeout: 60000 })
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.includes('view-fixture')).map(([, value]) => JSON.parse(value).operations))
  const originalDraft = await draft(), zoom = page.getByLabel('页面缩放', { exact: true }), observed = []
  const waitZoom = async value => { await page.waitForFunction(value => Math.abs(Number(document.querySelector('[aria-label="页面缩放"]')?.value) - value) < 1e-8 && Math.abs(parseFloat(document.querySelector('.pdf-page-content')?.style.width || '') - 380 * value) < 1e-6, value); observed.push(value) }
  await page.locator('[data-pdf-ribbon-tab="view"]').click()
  const night = page.locator('[data-source-command-id="genoffice.pdf.view.navigation.nightMode"]')
  const navigation = await night.locator('..').locator('[data-source-command-id]').evaluateAll(nodes => nodes.map(node => ({ id: node.dataset.sourceCommandId, disabled: node.disabled, title: node.title })))
  assert.deepEqual(navigation.map(row => row.id.split('.').at(-1)), ['thumbnails', 'outline', 'comments', 'compare', 'attachments', 'search', 'pageSpread', 'nightMode'])
  for (const id of ['compare', 'attachments']) assert.ok(navigation.find(row => row.id.endsWith(`.${id}`)).disabled && navigation.find(row => row.id.endsWith(`.${id}`)).title)
  await night.click(); assert.equal(await night.getAttribute('aria-pressed'), 'true')
  const filters = await page.locator('.pdf-page-content canvas').evaluateAll(nodes => nodes.map(node => getComputedStyle(node).filter))
  assert.ok(filters.every(filter => filter.includes('invert(1)') && filter.includes('180deg')))
  assert.equal(await page.locator('.pdf-document-pages').evaluate(node => getComputedStyle(node).backgroundColor), 'rgb(30, 30, 30)')
  await page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.zoomOut"]').click(); await waitZoom(.9)
  await page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.zoomIn"]').click(); await waitZoom(1)
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  assert.equal(await zoom.locator('option').count(), 18)
  await page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.zoomIn"]').click(); await waitZoom(1.1)
  await page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.zoomOut"]').click(); await waitZoom(1)
  await zoom.selectOption('0.1'); await waitZoom(.1)
  await zoom.selectOption('8'); await waitZoom(8)
  const slider = page.locator('[data-source-command-id="genoffice.pdf.view.status.zoomSlider"]')
  assert.equal(await slider.getAttribute('min'), '10'); assert.equal(await slider.getAttribute('max'), '800'); assert.equal(await slider.getAttribute('step'), '5')
  await slider.evaluate(node => { node.value = '135'; node.dispatchEvent(new Event('input', { bubbles: true })) }); await waitZoom(1.35)
  await page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.zoomOut"]').click(); await waitZoom(1.25)
  await zoom.selectOption('1'); await waitZoom(1)
  await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3)
  await page.locator('.pdf-document-pages').evaluate(node => { node.scrollTop = 220 })
  const anchor = await page.locator('.pdf-document-pages').evaluate(node => {
    const viewport = node.getBoundingClientRect(), page = node.querySelector('.pdf-page-content').getBoundingClientRect()
    const x = Math.min(page.right - 10, Math.max(page.left + 10, viewport.left + viewport.width / 2)), y = Math.min(page.bottom - 10, Math.max(page.top + 10, viewport.top + 100))
    return { x, y, pageX: x - page.left, pageY: y - page.top }
  })
  await page.mouse.move(anchor.x, anchor.y); await page.keyboard.down('Control'); await page.mouse.wheel(0, -25); await page.keyboard.up('Control'); await waitZoom(1.15)
  await page.waitForFunction(anchor => { const page = document.querySelector('.pdf-page-content').getBoundingClientRect(); return Math.abs((anchor.x - page.left) / 1.15 - anchor.pageX) < 2 && Math.abs((anchor.y - page.top) / 1.15 - anchor.pageY) < 2 }, anchor)
  const anchorAfter = await page.locator('.pdf-page-content').first().evaluate((node, anchor) => { const box = node.getBoundingClientRect(); return { x: (anchor.x - box.left) / 1.15, y: (anchor.y - box.top) / 1.15 } }, anchor)
  await page.locator('[data-source-command-id="genoffice.pdf.home.print.print"]').click()
  await page.waitForFunction(() => window.__pdfPrintReceipt?.length === 3)
  const print = await page.evaluate(() => window.__pdfPrintReceipt)
  await page.emulateMedia({ media: 'print' })
  const printLayout = await page.evaluate(() => ({ host: getComputedStyle(document.querySelector('.pdf-print-document')).display, footer: getComputedStyle(document.querySelector('.pdf-view-status')).display, pageFilters: [...document.querySelectorAll('.pdf-print-document canvas')].map(canvas => getComputedStyle(canvas).filter) }))
  assert.equal(printLayout.host, 'block'); assert.equal(printLayout.footer, 'none'); assert.ok(printLayout.pageFilters.every(filter => filter === 'none'))
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint'))); await page.emulateMedia({ media: 'screen' })
  assert.ok(print.every(row => row.filter === 'none' && row.pixel[0] === 255 && row.pixel[1] === 255 && row.pixel[2] === 255))
  await page.locator('[data-pdf-ribbon-tab="view"]').click(); assert.equal(await night.getAttribute('aria-pressed'), 'true'); await night.click()
  assert.equal(await night.getAttribute('aria-pressed'), 'false'); assert.equal(await page.locator('.pdf-page-content canvas').first().evaluate(node => getComputedStyle(node).filter), 'none')
  const downloaded = Buffer.from(await page.evaluate(async () => [...new Uint8Array(await (await fetch('/reports/v1/native/view-fixture/1/api/file')).arrayBuffer())]))
  assert.equal(sha(downloaded), sha(source)); assert.deepEqual(await draft(), originalDraft)
  assert.ok((await draft()).every(operations => !operations?.length)); assert.deepEqual(errors, [])
  const evidence = { ok: true, browserVersion: browser.version(), sourceSha256: sha(source), downloadedSha256: sha(downloaded), nightFilters: filters, zoomSequence: observed, anchor, anchorAfter, print, printLayout, draftUnchanged: true, readonlyViewControls: true, provenance: 'production static UI; substituted auth/preview route; actual packed source inspection and PDF.js rendering; browser print call intercepted', desktopPrintVerified: false }
  if (process.env.PDF_VIEW_EVIDENCE_DIR) { const dir = process.env.PDF_VIEW_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); await writeFile(`${dir}/source.pdf`, source); await writeFile(`${dir}/downloaded.pdf`, downloaded); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)) }
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
