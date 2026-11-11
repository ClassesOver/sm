// 只启动 preview；冻结源码并统一构建后执行。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
assert.match(process.env.DOCX_EXPECTED_MANIFEST_SHA256 ?? '', /^[a-f0-9]{64}$/, '必须提供 DOCX_EXPECTED_MANIFEST_SHA256 冻结构建身份')
const staticRoot = resolve(process.env.DOCX_TEST_DIST ?? join(frontend, '../static'))
const runtime = resolve(process.env.DOCX_TEST_ENGINE ?? join(repo, 'smart_reporting/reporting/doc_engine'))
const manifestPath = join(staticRoot, '.vite/manifest.json'), bridgePath = join(runtime, 'dist/edit-docx.mjs')
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const manifest = await readFile(manifestPath), bridgeSha256 = hash(await readFile(bridgePath))
assert.equal(hash(manifest), process.env.DOCX_EXPECTED_MANIFEST_SHA256, '冻结 manifest 身份不一致')
const port = Number(process.env.DOCX_TEST_PORT ?? process.env.DOCX_OUTLINE_SMOKE_PORT ?? 4274)
const base = 'http://127.0.0.1:' + port
const temporary = process.env.DOCX_TEST_OUTPUT ? resolve(process.env.DOCX_TEST_OUTPUT) : await mkdtemp(join(tmpdir(), 'docx-outline-view-'))
await mkdir(temporary, { recursive: true })
const fixture = spawnSync(join(repo, '.venv/bin/python'), ['-c', [
  'import base64,json', 'from io import BytesIO', 'from docx import Document', 'from docx.oxml.ns import qn', 'from docx.enum.section import WD_SECTION_START',
  'from smart_reporting.reporting.delivery.docx_native import inspect_docx', 'doc=Document()',
  "doc.add_heading('OUTLINE-A',1)", "doc.add_paragraph('BODY-PRESERVED-A')",
  "doc.add_heading('OUTLINE-CHILD',2)", "doc.add_paragraph('BODY-PRESERVED-CHILD')",
  "doc.add_heading('OUTLINE-B',1)", "doc.add_paragraph('BODY-PRESERVED-B')",
  "table=doc.add_table(rows=1,cols=1);table.cell(0,0).text='TABLE-PRESERVED'",
  "cols=doc.sections[0]._sectPr.find(qn('w:cols'));cols.set(qn('w:num'),'2')",
  'buf=BytesIO();doc.save(buf);data=buf.getvalue()',
  "uniform={'base64':base64.b64encode(data).decode(),'model':inspect_docx(data)}",
  "sec=doc.add_section(WD_SECTION_START.CONTINUOUS);sec._sectPr.find(qn('w:cols')).set(qn('w:num'),'1')",
  "doc.add_heading('OUTLINE-C',1);doc.add_paragraph('MIXED-SECTION-PRESERVED')",
  'buf=BytesIO();doc.save(buf);data=buf.getvalue()',
  "print(json.dumps({'uniform':uniform,'mixed':{'base64':base64.b64encode(data).decode(),'model':inspect_docx(data)}}))",
].join('\n')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime }, encoding: 'utf8', maxBuffer: 10 * 1024 * 1024, timeout: 120000 })
assert.equal(fixture.status, 0, fixture.stderr)
const sources = JSON.parse(fixture.stdout)
const sourceFor = url => sources[url.includes('fixture-outline-mixed') ? 'mixed' : 'uniform']
const bytesFor = url => Buffer.from(sourceFor(url).base64, 'base64')
let server, browser, page, stage = 'start'
const errors = [], chunkChecks = [], chunks = new Map(), savePayloads = []
try {
  server = spawn('./node_modules/.bin/vite', ['preview', '--outDir', staticRoot, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
  let log = ''; server.stderr.on('data', chunk => { log += chunk })
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, log)
    try { if ((await fetch(base + '/reports/v1/editor/assets/native.html')).ok) break } catch {}
    if (attempt === 120) throw new Error('preview timeout: ' + log)
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    const prefix = '/reports/v1/editor/assets/'
    if (!path.startsWith(prefix) || !path.endsWith('.js')) return
    chunkChecks.push((async () => {
      assert.equal(response.status(), 200)
      const file = path.slice(prefix.length), actual = await response.body()
      const diskPath = resolve(staticRoot, file)
      assert.ok(diskPath.startsWith(staticRoot + '/'), 'JS 必须位于冻结目录')
      assert.equal(hash(actual), hash(await readFile(diskPath)), '浏览器 JS 身份 ' + file)
      chunks.set(file, hash(actual))
    })())
  })
  await page.route('**/reports/v1/native/fixture-outline-*/1/api/context', route => { const bytes = bytesFor(route.request().url()); return route.fulfill({ json: {
    context: { documentId: new URL(route.request().url()).pathname.split('/')[4], format: 'docx', revision: 1, parentRevision: null,
      scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'outline.docx', size: bytes.length, sha256: hash(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }, origin: 'report' },
    csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: !route.request().url().includes('readonly'),
  } }) })
  await page.route('**/reports/v1/native/fixture-outline-*/1/api/file', route => route.fulfill({ body: bytesFor(route.request().url()), contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
  await page.route('**/reports/v1/native/fixture-outline-*/1/api/preview', route => { const model = sourceFor(route.request().url()).model; return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } }) })
  await page.route('**/reports/v1/native/fixture-outline-*/1/api/save', route => { savePayloads.push(route.request().postDataJSON()); return route.fulfill({ status: 500, json: { detail: '纯视图不应签发保存' } }) })
  await page.route(/\/reports\/v1\/native\/fixture-outline-[a-z]+\/1$/, async route => route.fulfill({ response: await route.fetch({ url: base + '/reports/v1/editor/assets/native.html' }) }))
  const body = () => page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const snapshot = () => page.evaluate(() => ({
    draft: Object.fromEntries(Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:'))),
    text: document.querySelector('[aria-label="Word 文档编辑区"]')?.textContent,
    columnCount: getComputedStyle(document.querySelector('[aria-label="Word 文档编辑区"]')).columnCount,
    style: document.querySelector('[aria-label="Word 文档编辑区"]')?.getAttribute('style'),
    status: document.querySelector('.save-state-label')?.textContent,
  }))
  const outlineGeometry = async label => {
    const headings = await body().locator('h1,h2,h3,h4,h5,h6').evaluateAll(nodes => nodes.filter(node => getComputedStyle(node).display !== 'none').map(node => {
      const rect = node.getBoundingClientRect(), css = getComputedStyle(node)
      return { text: node.textContent, top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, transform: css.transform, width: css.width }
    }))
    await writeFile(join(temporary, label + '-geometry.json'), JSON.stringify(headings, null, 2))
    for (let index = 1; index < headings.length; index++) assert.ok(headings[index].top >= headings[index - 1].bottom - 0.5, label + ' 大纲标题必须按普通文档流排列且不重叠：' + JSON.stringify(headings))
    return headings
  }
  const results = []
  for (const mode of process.env.DOCX_OUTLINE_CASE ? [process.env.DOCX_OUTLINE_CASE] : ['editable', 'readonly', 'mixed']) {
    stage = mode
    await page.goto(base + '/reports/v1/native/fixture-outline-' + mode + '/1')
    await page.locator('.docx-source-home').waitFor({ timeout: 60000 })
    await body().locator('h1').first().waitFor()
    await page.evaluate(async () => { await document.fonts.ready })
    const before = await snapshot()
    await page.locator('[data-tab-id="view"]').click()
    const outline = page.locator('[data-action="view-outline"]')
    const paged = page.locator('[data-action="view-page"]')
    assert.equal(await outline.isEnabled(), true); await outline.click()
    assert.equal(await outline.getAttribute('aria-pressed'), 'true')
    assert.equal(await body().locator('p').first().isVisible(), false)
    assert.equal(await body().locator('table').isVisible(), false)
    assert.equal(await body().evaluate(node => getComputedStyle(node).columnCount), 'auto')
    const expandedGeometry = await outlineGeometry(mode + '-expanded')
    const handle = body().locator('h1 .outline-handle').first(), child = body().locator('h2')
    assert.equal(await child.isVisible(), true); await handle.click()
    assert.equal(await child.isVisible(), false); assert.equal(await handle.textContent(), '⊕')
    const foldedGeometry = await outlineGeometry(mode + '-folded')
    await handle.click(); assert.equal(await child.isVisible(), true)
    await handle.click(); assert.equal(await child.isVisible(), false)
    await page.screenshot({ path: join(temporary, mode + '-outline.png'), fullPage: true })
    await paged.click()
    assert.equal(await paged.getAttribute('aria-pressed'), 'true')
    assert.equal(await body().locator('p').first().isVisible(), true); assert.equal(await body().locator('table').isVisible(), true)
    assert.equal(await child.isVisible(), true); assert.equal(await body().locator('.outline-handle,.outline-collapsed').count(), 0)
    assert.deepEqual(await snapshot(), before, '视图往返正文/分栏/原生草稿/保存状态不变')
    await outline.click(); assert.equal(await child.isVisible(), true); await paged.click()
    assert.deepEqual(await snapshot(), before)
    if (mode === 'editable') {
      await outline.click()
      const leaf = body().locator('h1').last()
      await leaf.click(); await page.keyboard.press('End'); await page.keyboard.type(' EDIT')
      await page.waitForFunction(() => [...document.querySelectorAll('[aria-label="Word 文档编辑区"] h1')].some(node => node.textContent.includes('OUTLINE-B EDIT')))
      assert.ok(Object.values(await page.evaluate(() => Object.fromEntries(Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:'))))).some(value => JSON.parse(value).operations.length > 0), '真实编辑仍生成正文草稿')
      await page.keyboard.press('Control+z'); await paged.click()
      assert.equal((await snapshot()).text, before.text, '真实标题编辑可撤销恢复')
    }
    results.push({ mode, draftUnchanged: true, columnsRestored: true, foldExpandRestored: true, expandedGeometry, foldedGeometry })
  }
  assert.deepEqual(savePayloads, [])
  await Promise.all(chunkChecks)
  assert.ok([...chunks.keys()].some(file => file.startsWith('assets/lazy-docx-main-') && file.endsWith('.js')))
  assert.equal(hash(await readFile(manifestPath)), hash(manifest), 'smoke 期间构建身份不变')
  const bridgeAfterSha256 = hash(await readFile(bridgePath))
  assert.equal(bridgeAfterSha256, bridgeSha256, 'smoke 期间 engine 身份不变')
  assert.deepEqual(errors, [])
  const result = { ok: true, temporary, staticRoot, runtime, sourceSha256: Object.fromEntries(Object.entries(sources).map(([key, value]) => [key, value.model.sourceSha256])), manifestSha256: hash(manifest), bridgeSha256, bridgeAfterSha256, loadedChunks: Object.fromEntries(chunks), results, savePayloads, errors }
  await writeFile(join(temporary, 'result.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result))
} catch (error) {
  if (page) { await writeFile(join(temporary, 'failure.html'), await page.content()); await page.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }) }
  console.error(JSON.stringify({ stage, temporary })); throw error
} finally { await browser?.close(); server?.kill() }
