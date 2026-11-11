// 本地固定构建验收：沿用现有 DOCX built smoke 的静态 fixture server + 替身 API；不代表生产鉴权。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { createServer } from 'node:http'
import { spawnSync } from 'node:child_process'
import { dirname, resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const fixtureRoot = dirname(fileURLToPath(import.meta.url)), repo = resolve(fixtureRoot, '../../../..')
const output = resolve(process.env.DOCX_TEST_OUTPUT ?? '/dev/shm/sr-word-ruler-pages-20261111/pages-browser')
const staticRoot = process.env.DOCX_TEST_DIST ?? resolve(repo, 'smart_reporting/report_editor/static')
const runtime = process.env.DOCX_TEST_ENGINE ?? resolve(repo, 'smart_reporting/reporting/doc_engine')
const port = Number(process.env.DOCX_TEST_PORT ?? 4347), base = 'http://127.0.0.1:' + port
const prefix = '/reports/v1/editor/assets/', mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestPath = resolve(staticRoot, '.vite/manifest.json'), bridgePath = resolve(runtime, 'dist/edit-docx.mjs')
const manifestSha256 = sha(await readFile(manifestPath)), bridgeSha256 = sha(await readFile(bridgePath))
assert.equal(manifestSha256, process.env.DOCX_EXPECTED_MANIFEST_SHA256, '必须由集成人员提供冻结构建 manifest 身份')
await mkdir(output, { recursive: true })
const fixturePath = resolve(output, 'source.docx')
const python = [
  'import base64,json,sys',
  'from pathlib import Path',
  'from docx import Document',
  'from docx.enum.style import WD_STYLE_TYPE',
  'from docx.oxml import OxmlElement',
  'from docx.oxml.ns import qn',
  'from smart_reporting.reporting.delivery.docx_native import inspect_docx',
  'doc=Document()',
  'for n in range(3):',
  '    h=doc.add_heading(["第一页标题","第二页标题","第三页标题"][n],1)',
  '    if n: h.paragraph_format.page_break_before=True',
  '    h.paragraph_format.space_before=0',
  '    for i in range(4): doc.add_paragraph("本页正文 "+str(n+1)+"-"+str(i))',
  'doc.save(sys.argv[1])',
  'raw=Path(sys.argv[1]).read_bytes()',
  'print(json.dumps({"bytes":base64.b64encode(raw).decode(),"model":inspect_docx(raw)},ensure_ascii=False))',
].join(String.fromCharCode(10))
const generated = spawnSync(resolve(repo, '.venv/bin/python'), ['-c', python, fixturePath], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime }, encoding: 'utf8', maxBuffer: 20 * 1024 * 1024, timeout: 120000 })
assert.equal(generated.status, 0, generated.stderr)
const fixture = JSON.parse(generated.stdout), bytes = Buffer.from(fixture.bytes, 'base64')
const requests = [], identities = [], chunks = new Map(), errors = [], actions = []
const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, base).pathname
    if (path === '/favicon.ico') { res.writeHead(204); res.end(); return }
    assert.ok(path.startsWith(prefix)); const file = resolve(staticRoot, path.slice(prefix.length)); assert.ok(file.startsWith(staticRoot + '/'))
    const mime = { '.js': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.html': 'text/html', '.svg': 'image/svg+xml', '.png': 'image/png' }
    res.writeHead(200, { 'Content-Type': mime[extname(file)] ?? 'application/octet-stream' }); res.end(await readFile(file))
  } catch { if (!res.headersSent) res.writeHead(404); res.end('not found') }
})
await new Promise((ok, no) => { server.once('error', no); server.listen(port, '127.0.0.1', ok) })
let browser, page
try {
  browser = await chromium.launch({ headless: true })
  for (const editingEnabled of [true, false]) {
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    page.on('pageerror', error => errors.push(error.message))
    page.on('response', response => {
      const path = new URL(response.url()).pathname
      if (response.status() >= 400) errors.push(response.status() + ' ' + path)
      if (response.ok() && path.startsWith(prefix) && path.endsWith('.js')) identities.push(response.body().then(async body => { assert.equal(sha(body), sha(await readFile(resolve(staticRoot, path.slice(prefix.length))))); chunks.set(path, sha(body)) }))
    })
    const docId = 'fixture-navigation-pages-' + editingEnabled, pathBase = '/reports/v1/native/' + docId + '/1'
    await page.route(base + pathBase, async route => route.fulfill({ body: await readFile(resolve(staticRoot, 'native.html')), contentType: 'text/html' }))
    await page.route('**' + pathBase + '/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      requests.push({ editingEnabled, method: request.method(), path })
      if (path.endsWith('/context')) return route.fulfill({ json: { context: { documentId: docId, format: 'docx', revision: 1, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'source.docx', size: bytes.length, sha256: fixture.model.sourceSha256, mediaType }, origin: 'upload' }, csrfToken: 'fixture-only', capabilities: { docx_editor: editingEnabled }, editingEnabled } })
      if (path.endsWith('/file')) return route.fulfill({ body: bytes, contentType: mediaType })
      if (path.endsWith('/preview')) return route.fulfill({ json: { sourceSha256: fixture.model.sourceSha256, draftSha256: fixture.model.sourceSha256, model: fixture.model } })
      return route.fulfill({ status: 409, json: { detail: '导航验收禁止写入' } })
    })
    await page.goto(base + pathBase); await page.locator('.docx-source-home').waitFor({ timeout: 60000 })
    const editor = page.getByRole('textbox', { name: 'Word 文档编辑区' }), panel = page.locator('[data-docx-navigation]')
    const before = await editor.evaluate(node => node.editor.getJSON()), storageBefore = await page.evaluate(() => JSON.stringify(localStorage))
    await page.locator('[data-tab-id=view]').click()
    await page.locator('[data-action=view-outline]').click()
    await page.locator('[data-action=navigation-toggle]').click(); await panel.waitFor({ state: 'visible' })
    await panel.locator('[data-navigation-tab=pages]').click()
    const thumbs = panel.locator('[data-navigation-page]')
    await thumbs.nth(2).waitFor({ timeout: 30000 })
    assert.equal(await thumbs.count(), 3)
    assert.equal(await page.locator('.docx-navigation-layout').evaluate(node => node.classList.contains('view-outline')), false)
    assert.equal(await panel.locator('.docx-navigation-page-paper .ProseMirror,.docx-navigation-page-paper .doc-page,.docx-navigation-page-paper [id],.docx-navigation-page-paper [contenteditable],.docx-navigation-page-paper [autofocus],.docx-navigation-page-paper script').count(), 0)
    assert.equal(await panel.locator('.docx-navigation-page-paper').evaluateAll(nodes => nodes.every(node => node.inert)), true)
    const focusProtected = await panel.locator('.docx-navigation-page-paper').first().evaluate(paper => {
      const prior = document.activeElement, input = document.createElement('input'); paper.append(input); input.focus()
      const preserved = document.activeElement === prior; input.remove(); return preserved
    })
    assert.equal(focusProtected, true)
    const pageContents = await panel.locator('.docx-navigation-page-paper').allTextContents()
    assert.match(pageContents[0], /第一页标题/); assert.doesNotMatch(pageContents[0], /第二页标题|第三页标题/)
    assert.match(pageContents[1], /第二页标题/); assert.doesNotMatch(pageContents[1], /第一页标题|第三页标题/)
    assert.match(pageContents[2], /第三页标题/)
    await thumbs.nth(1).click()
    assert.equal(await editor.evaluate(node => node.editor.state.selection.$from.parent.textContent), '第二页标题')
    assert.equal(await thumbs.nth(1).getAttribute('aria-current'), 'page')
    await panel.locator('[data-navigation-tab=headings]').click()
    assert.deepEqual(await panel.locator('[data-navigation-heading]').allTextContents(), ['第一页标题', '第二页标题', '第三页标题'])
    await panel.locator('[data-navigation-tab=pages]').click(); await thumbs.nth(2).waitFor({ timeout: 30000 })
    await page.locator('[data-action="view-缩放"]').click()
    await page.getByRole('spinbutton', { name: '显示比例（%）' }).fill('150')
    await page.getByRole('button', { name: '应用', exact: true }).click()
    await thumbs.nth(2).waitFor({ timeout: 30000 }); assert.equal(await thumbs.count(), 3)
    await thumbs.nth(2).click(); assert.equal(await editor.evaluate(node => node.editor.state.selection.$from.parent.textContent), '第三页标题')
    await page.locator('[data-action="view-outline"]').click()
    assert.equal(await panel.locator('[data-navigation-tab=headings]').getAttribute('aria-selected'), 'true')
    assert.equal(await panel.locator('[data-navigation-pages]').isVisible(), false)
    await panel.locator('[data-navigation-tab=pages]').click(); await thumbs.nth(2).waitFor({ timeout: 30000 })
    assert.equal(await page.locator('.docx-navigation-layout').evaluate(node => node.classList.contains('view-outline')), false)

    await panel.locator('[data-navigation-action=close]').click(); await page.locator('[data-action=navigation-toggle]').click()
    await thumbs.nth(2).waitFor({ timeout: 30000 })
    const geometry = await page.locator('.docx-navigation-layout').evaluate(node => { const p = node.querySelector('[data-docx-navigation]').getBoundingClientRect(), e = node.querySelector('.editor-scroll').getBoundingClientRect(); return { panelRight: p.right, editorLeft: e.left, right: e.right, width: innerWidth } })
    assert.ok(geometry.panelRight <= geometry.editorLeft + 1); assert.ok(geometry.right <= geometry.width + 1)
    assert.deepEqual(await editor.evaluate(node => node.editor.getJSON()), before)
    assert.equal(await page.evaluate(() => JSON.stringify(localStorage)), storageBefore)
    assert.equal(requests.filter(request => request.path.endsWith('/save') || request.path.endsWith('/export')).length, 0)
    await page.screenshot({ path: resolve(output, editingEnabled ? 'editable.png' : 'readonly.png'), fullPage: true })
    actions.push({ editingEnabled, documentUnchanged: true, storageUnchanged: true, saveRequests: 0, count: await thumbs.count(), at150Percent: true, outlinePrepared: true, inertFocusProtected: true, pageContents, geometry })
    await page.close()
  }
  await Promise.all(identities); assert.deepEqual(errors, [])
  assert.equal(sha(await readFile(manifestPath)), manifestSha256); assert.equal(sha(await readFile(bridgePath)), bridgeSha256)
  assert.equal(sha(await readFile(fixturePath)), fixture.model.sourceSha256)
  const evidence = { ok: true, manifestSha256, bridgeSha256, browser: browser.version(), sourceSha256: fixture.model.sourceSha256, routeIsFixture: true, productionAuthTested: false, actions, requests, chunks: Object.fromEntries(chunks), errors }
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify(evidence))
} catch (error) { await page?.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {}); throw error }
finally { await browser?.close(); await new Promise(resolve => server.close(resolve)) }
