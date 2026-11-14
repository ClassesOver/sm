// 本地固定构建验收：沿用现有 DOCX built smoke 的静态 fixture server + 替身 API；不代表生产鉴权。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { createServer } from 'node:http'
import { spawnSync } from 'node:child_process'
import { dirname, resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { inspectDocxNavigation } from './office-cross-format-navigation.mjs'

const fixtureRoot = dirname(fileURLToPath(import.meta.url)), repo = resolve(fixtureRoot, '../../../..')
const output = resolve(process.env.DOCX_TEST_OUTPUT ?? '/tmp/docx-navigation-search-smoke')
const staticRoot = process.env.DOCX_TEST_DIST ?? resolve(repo, 'smart_reporting/report_editor/static')
const runtime = process.env.DOCX_TEST_ENGINE ?? resolve(repo, 'smart_reporting/reporting/doc_engine')
const port = Number(process.env.DOCX_TEST_PORT ?? 4336), base = 'http://127.0.0.1:' + port
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
  'from smart_reporting.reporting.delivery.docx_native import inspect_docx',
  'doc=Document()',
  'doc.add_heading("导航搜索专项",1)',
  'doc.add_heading("目录章一",1);doc.add_heading("目录子节",2);doc.add_heading("目录章二",1)',
  'p=doc.add_paragraph();p.add_run("前😀ca").bold=True;p.add_run("t尾 cat ＣＡＴ ^p ^ .* <img src=x onerror=alert(1)>")',
  'table=doc.add_table(rows=1,cols=1);table.cell(0,0).text="表格 cat"',
  'doc.add_paragraph("动态 cat")',
  'doc.add_paragraph("边界前");doc.add_paragraph("边界后")',
  'doc.add_paragraph("cap "*503)',
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
    const browserContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    page = await browserContext.newPage()
    page.on('pageerror', error => errors.push(error.message))
    page.on('response', response => {
      const path = new URL(response.url()).pathname
      if (response.status() >= 400) errors.push(response.status() + ' ' + path)
      if (response.ok() && path.startsWith(prefix) && /\.(js|css)$/.test(path)) identities.push(response.body().then(async body => { assert.equal(sha(body), sha(await readFile(resolve(staticRoot, path.slice(prefix.length))))); chunks.set(path, sha(body)) }))
    })
    const docId = 'fixture-navigation-search-' + editingEnabled, pathBase = '/reports/v1/native/' + docId + '/1'
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
    const snapshot = () => editor.evaluate(node => ({ doc: node.editor.getJSON(), undo: node.editor.can().undo(), redo: node.editor.can().redo() }))
    const selected = () => editor.evaluate(node => { const editor = node.editor, selection = editor.state.selection; return { text: editor.state.doc.textBetween(selection.from, selection.to), from: selection.from, to: selection.to, depth: selection.$from.depth } })
    const before = await snapshot(), storageBefore = await page.evaluate(() => JSON.stringify(localStorage))
    await page.locator('[data-tab-id=home]').click(); await page.locator('[data-action=find]').click()
    await page.locator('[data-find-query]').fill('边界')
    assert.equal(await editor.locator('.search-hit').count(), 2)
    const originalHighlights = await editor.locator('.search-hit').allTextContents()
    await page.locator('[data-tab-id=view]').click(); await page.locator('[data-action=navigation-toggle]').click(); await panel.waitFor({ state: 'visible' })
    const query = panel.locator('[data-navigation-query]'), results = panel.locator('[data-navigation-search-result]')
    const action = name => panel.locator('[data-navigation-search-action="' + name + '"]')
    const count = () => panel.locator('[data-navigation-search-count]').textContent()
    await query.fill('cat'); assert.equal(await results.count(), 5); assert.equal(await count(), '0/5')
    const keyboardLayout = await inspectDocxNavigation(page, { output, phase: editingEnabled ? 'editable' : 'readonly' })
    await action('next').click(); assert.equal((await selected()).text, 'cat'); assert.equal(await count(), '1/5')
    await action('previous').click(); assert.equal(await count(), '5/5'); assert.equal((await selected()).text, 'cat')
    await results.nth(2).click(); assert.equal((await selected()).text, 'ＣＡＴ')
    await query.fill('😀cat'); assert.equal(await results.count(), 1); await query.press('Enter')
    const emoji = await selected(); assert.equal(emoji.text, '😀cat'); assert.equal(emoji.to - emoji.from, 5)
    await query.fill('cat'); await results.nth(3).click(); assert.equal((await selected()).depth, 4)
    await query.fill('^p'); assert.equal(await results.count(), 1); await results.first().click(); assert.equal((await selected()).text, '^p')
    await query.fill('^'); assert.equal(await results.count(), 2)
    await query.fill('.*'); assert.equal(await results.count(), 1); await results.first().click(); assert.equal((await selected()).text, '.*')
    await query.fill('<img'); assert.equal(await results.count(), 1); assert.equal(await panel.locator('img').count(), 0); assert.equal(await results.locator('mark').textContent(), '<img')
    await query.fill('边界前边界后'); assert.equal(await results.count(), 0); assert.equal(await count(), '0/0'); assert.equal(await action('next').isDisabled(), true)
    await action('clear').click(); assert.equal(await query.inputValue(), ''); assert.equal(await panel.locator('[role=tree]').isVisible(), true)
    await page.locator('[data-action=view-outline]').click(); assert.equal(await page.locator('.docx-navigation-layout').evaluate(node => node.classList.contains('view-outline')), true)
    await query.fill('cat'); assert.equal(await page.locator('.docx-navigation-layout').evaluate(node => node.classList.contains('view-outline')), true)
    await results.first().click(); assert.equal(await page.locator('.docx-navigation-layout').evaluate(node => node.classList.contains('view-outline')), false)
    assert.equal(await page.locator('[data-action=view-page]').getAttribute('aria-pressed'), 'true')
    assert.equal((await selected()).text, 'cat')
    await page.screenshot({ path: resolve(output, editingEnabled ? 'editable.png' : 'readonly.png'), fullPage: true })
    await query.fill('cap'); assert.equal(await results.count(), 500); assert.equal(await count(), '0/503'); await action('previous').click()
    assert.equal(await count(), '503/503'); assert.equal((await selected()).text, 'cap')
    assert.deepEqual(await editor.locator('.search-hit').allTextContents(), originalHighlights)
    await action('clear').click(); assert.deepEqual(await snapshot(), before); assert.equal(await page.evaluate(() => JSON.stringify(localStorage)), storageBefore)
    await query.fill('cat'); await panel.locator('[data-navigation-action=close]').click(); await page.locator('[data-action=navigation-toggle]').click(); assert.equal(await results.count(), 5)
    const geometry = await page.locator('.docx-navigation-layout').evaluate(node => { const p = node.querySelector('[data-docx-navigation]').getBoundingClientRect(), e = node.querySelector('.editor-scroll').getBoundingClientRect(); return { panelRight: p.right, editorLeft: e.left, right: e.right, width: innerWidth } })
    assert.ok(geometry.panelRight <= geometry.editorLeft + 1); assert.ok(geometry.right <= geometry.width + 1)
    actions.push({ editingEnabled, keyboardLayout, literalResults: 5, exactNonBmpSpan: emoji.to - emoji.from, cappedResults: 500, navigableMatches: 503, findHighlightsPreserved: true, outlineResultReturnsToPage: true, documentStorageUndoUnchanged: true, geometry })
    if (editingEnabled) {
      await results.last().click(); await editor.evaluate(node => node.editor.view.focus()); await page.keyboard.type('dog')
      await page.waitForFunction(() => document.querySelector('[data-navigation-search-count]')?.textContent.endsWith('/4'))
      const changed = await snapshot(), changedStorage = await page.evaluate(() => JSON.stringify(localStorage))
      await action('previous').click(); assert.deepEqual(await snapshot(), changed); assert.equal(await page.evaluate(() => JSON.stringify(localStorage)), changedStorage)
      actions.push({ realtimeSearchUpdate: true, existingDraftUndoPreserved: true })
    }
    await browserContext.close()
  }
  await Promise.all(identities); assert.deepEqual(errors, []); assert.equal(requests.filter(request => request.path.endsWith('/save') || request.path.endsWith('/export')).length, 0)
  assert.equal(sha(await readFile(manifestPath)), manifestSha256); assert.equal(sha(await readFile(bridgePath)), bridgeSha256)
  assert.equal(sha(await readFile(fixturePath)), fixture.model.sourceSha256)
  const evidence = { ok: true, manifestSha256, bridgeSha256, browser: browser.version(), sourceSha256: fixture.model.sourceSha256, routeIsFixture: true, productionAuthTested: false, actions, requests, chunks: Object.fromEntries(chunks), errors }
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, manifestSha256, bridgeSha256, loadedJs: chunks.size, errors, actions, evidence: resolve(output, 'evidence.json') }))
} catch (error) { await page?.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {}); throw error }
finally { await browser?.close(); await new Promise(resolve => server.close(resolve)) }
