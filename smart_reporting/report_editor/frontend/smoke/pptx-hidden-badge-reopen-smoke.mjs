import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd(), repo = resolve('../../..'), port = Number(process.env.PPTX_BADGE_PORT || 4241)
const base = 'http://127.0.0.1:' + port, evidence = process.env.PPTX_BADGE_EVIDENCE_DIR || '/tmp/pptx-hidden-badge-reopen'
const sourcePath = process.env.PPTX_BADGE_SOURCE || '/tmp/pptx-hidden-built-final2-20261111/downloaded.pptx'
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const source = await readFile(sourcePath), sourceSha256 = sha(source)
const manifestSha256 = sha(await readFile('../static/.vite/manifest.json'))
if (process.env.PPTX_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.PPTX_EXPECTED_MANIFEST_SHA256)
await mkdir(evidence, { recursive: true })
const generated = spawnSync(join(repo, '.venv/bin/python'), ['-c', [
 'import json,sys',
 'from pathlib import Path',
 'from smart_reporting.report_editor.native_office import inspect_office',
 'from smart_reporting.report_editor.slides_render import render_pptx_tree',
 'b=Path(sys.argv[1]).read_bytes()',
 'print(json.dumps({"model":inspect_office("pptx",b),"renderTree":render_pptx_tree(b)}))',
].join('\n'), sourcePath], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
assert.equal(generated.status, 0, generated.stderr)
const actual = JSON.parse(generated.stdout)
assert.deepEqual(actual.model.slides.map(slide => slide.hidden), [false, true])
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser, page
const receipt = { ok: false, mode: 'readonly-hidden-badge-reopen', sourcePath, sourceSha256, manifestSha256, realInspect: true, realRender: true }
const pageErrors = [], failedResponses = [], saveRequests = [], exportRequests = [], runtimeAssets = new Map(), assetReads = []
try {
 for (let i = 0; i < 120; i++) {
  try { if ((await fetch(base + '/reports/v1/editor/assets/native.html')).ok) break } catch {}
  await delay(250)
 }
 browser = await chromium.launch({ headless: true })
 page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
 page.on('pageerror', error => pageErrors.push(error.message))
 page.on('request', request => {
  if (/\/api\/save(?:$|\?)/.test(request.url())) saveRequests.push({ method: request.method(), url: request.url() })
  if (/\/api\/export(?:$|\?)/.test(request.url())) exportRequests.push({ method: request.method(), url: request.url() })
 })
 page.on('response', response => {
  const path = new URL(response.url()).pathname
  if (response.status() >= 400) failedResponses.push({ status: response.status(), path })
  if (path.startsWith('/reports/v1/editor/assets/') && /\.(js|css)$/.test(path)) assetReads.push((async () => {
   assert.equal(response.status(), 200)
   const bytes = await response.body(), sha256 = sha(bytes)
   assert.equal(sha256, sha(await readFile('../static/' + path.slice('/reports/v1/editor/assets/'.length))))
   runtimeAssets.set(path, { path, size: bytes.length, sha256 })
  })())
 })
 const nativePath = '**/reports/v1/native/hidden-badge/2/api/'
 await page.route(nativePath + 'context', route => route.fulfill({ json: {
  context: { documentId: 'hidden-badge', format: 'pptx', revision: 2, parentRevision: 1, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'downloaded.pptx', size: source.length, sha256: sourceSha256, mediaType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }, origin: 'upload' },
  csrfToken: 'fixture-csrf', capabilities: { pptx_editor: true }, editingEnabled: true,
 } }))
 await page.route(nativePath + 'file', route => route.fulfill({ body: source, contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }))
 await page.route(nativePath + 'preview.pdf*', route => route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' }))
 await page.route(nativePath + 'preview', route => {
  const payload = route.request().postDataJSON()
  assert.equal(payload.expectedSha256, sourceSha256)
  assert.deepEqual(payload.operations, [])
  return route.fulfill({ json: { sourceSha256, draftSha256: sourceSha256, model: actual.model } })
 })
 await page.route(nativePath + 'render-tree', route => {
  const payload = route.request().postDataJSON()
  assert.equal(payload.expectedSha256, sourceSha256)
  assert.deepEqual(payload.operations, [])
  return route.fulfill({ json: actual.renderTree })
 })
 await page.addInitScript(() => { if (location.pathname.endsWith('/native.html')) history.replaceState(null, '', '/reports/v1/native/hidden-badge/2') })
 await page.goto(base + '/reports/v1/editor/assets/native.html')
 await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
 await page.locator('[data-ribbon-tab="slideShow"]').click()
 const hide = page.locator('[data-command="hideSlide"]')
 assert.match(await hide.textContent(), /隐藏幻灯片/)
 assert.equal(await hide.locator('svg').count(), 1)
 assert.equal(await hide.getAttribute('aria-pressed'), 'false')
 await page.locator('.slide-open').nth(1).click()
 assert.equal(await hide.getAttribute('aria-pressed'), 'true')
 const geometry = await page.locator('.slide-row[data-hidden="true"]').evaluate(row => {
  const box = node => { const rect = node.getBoundingClientRect(); return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height } }
  const badge = row.querySelector('.slide-hidden-badge'), range = document.createRange()
  range.selectNodeContents(badge)
  return { row: box(row), badge: box(badge), lines: [...range.getClientRects()].map(rect => ({ x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height })), title: box(row.querySelector('.slide-title')), visibleTitle: box(document.querySelector('.slide-row[data-hidden="false"] .slide-title')), buttons: [...row.querySelectorAll(':scope > button:not(.slide-open)')].map(button => ({ label: button.getAttribute('aria-label'), ...box(button) })) }
 })
 const drafts = await page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations || []))
 await Promise.all(assetReads)
 Object.assign(receipt, { browserVersion: browser.version(), geometry, draftOperations: drafts, saveRequests, exportRequests, pageErrors, failedResponses, runtimeJavaScript: [...runtimeAssets.values()].filter(asset => asset.path.endsWith('.js')), runtimeCss: [...runtimeAssets.values()].filter(asset => asset.path.endsWith('.css')) })
 await page.screenshot({ path: join(evidence, 'revision-2-layout.png'), fullPage: true })
 assert.equal(geometry.lines.length, 1, '隐藏标签必须保持一行')
 assert(geometry.badge.x >= geometry.row.x && geometry.badge.right <= geometry.row.right && geometry.badge.y >= geometry.row.y && geometry.badge.bottom <= geometry.row.bottom, '隐藏标签必须位于行边界内')
 assert(geometry.title.width >= geometry.visibleTitle.width - 1 && geometry.title.width >= 20, '隐藏标签不得挤占页标题宽度')
 const overlaps = (a, b) => a.x < b.right && a.right > b.x && a.y < b.bottom && a.bottom > b.y
 assert(!overlaps(geometry.badge, geometry.title), '隐藏标签不得覆盖页标题')
 assert(geometry.buttons.every(button => !overlaps(geometry.badge, button)), '隐藏标签不得覆盖操作按钮')
 assert.deepEqual(drafts, [])
 assert.deepEqual(saveRequests, [])
 assert.deepEqual(exportRequests, [])
 assert.deepEqual(pageErrors, [])
 assert.deepEqual(failedResponses, [])
 assert(receipt.runtimeJavaScript.some(asset => /slides-main-/.test(asset.path)))
 receipt.ok = true
 await writeFile(join(evidence, 'evidence.json'), JSON.stringify(receipt, null, 2) + '\n')
 console.log(JSON.stringify(receipt))
} catch (error) {
 receipt.error = String(error)
 await writeFile(join(evidence, 'failure.json'), JSON.stringify(receipt, null, 2) + '\n')
 if (page) await page.screenshot({ path: join(evidence, 'failure.png'), fullPage: true }).catch(() => {})
 throw error
} finally {
 await browser?.close()
 server.kill()
}
