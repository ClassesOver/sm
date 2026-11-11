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
const port = Number(process.env.DOCX_TEST_PORT ?? process.env.DOCX_GRIDLINES_SMOKE_PORT ?? 4276)
const base = 'http://127.0.0.1:' + port
const temporary = process.env.DOCX_TEST_OUTPUT ? resolve(process.env.DOCX_TEST_OUTPUT) : await mkdtemp(join(tmpdir(), 'docx-gridlines-'))
await mkdir(temporary, { recursive: true })
const fixture = spawnSync(join(repo, '.venv/bin/python'), ['-c', [
  'import base64,json', 'from io import BytesIO', 'from docx import Document', 'from docx.oxml.ns import qn', 'from docx.enum.section import WD_SECTION_START',
  'from smart_reporting.reporting.delivery.docx_native import inspect_docx', 'doc=Document()',
  "doc.add_heading('GRID-A',1)", "doc.add_paragraph('BODY-PRESERVED-A')",
  "doc.add_heading('GRID-CHILD',2)", "doc.add_paragraph('BODY-PRESERVED-CHILD')",
  "doc.add_heading('GRID-B',1)", "doc.add_paragraph('BODY-PRESERVED-B')",
  "table=doc.add_table(rows=1,cols=1);table.cell(0,0).text='TABLE-PRESERVED'",
  "cols=doc.sections[0]._sectPr.find(qn('w:cols'));cols.set(qn('w:num'),'2')",
  'buf=BytesIO();doc.save(buf);data=buf.getvalue()',
  "uniform={'base64':base64.b64encode(data).decode(),'model':inspect_docx(data)}",
  "sec=doc.add_section(WD_SECTION_START.CONTINUOUS);sec._sectPr.find(qn('w:cols')).set(qn('w:num'),'1')",
  "doc.add_heading('GRID-C',1);doc.add_paragraph('MIXED-SECTION-PRESERVED')",
  'buf=BytesIO();doc.save(buf);data=buf.getvalue()',
  "print(json.dumps({'uniform':uniform,'mixed':{'base64':base64.b64encode(data).decode(),'model':inspect_docx(data)}}))",
].join('\n')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime }, encoding: 'utf8', maxBuffer: 10 * 1024 * 1024, timeout: 120000 })
assert.equal(fixture.status, 0, fixture.stderr)
const sources = JSON.parse(fixture.stdout)
const sourceFor = url => sources[url.includes('fixture-gridlines-mixed') ? 'mixed' : 'uniform']
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
  await page.route('**/reports/v1/native/fixture-gridlines-*/1/api/context', route => { const bytes = bytesFor(route.request().url()); return route.fulfill({ json: {
    context: { documentId: new URL(route.request().url()).pathname.split('/')[4], format: 'docx', revision: 1, parentRevision: null,
      scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'outline.docx', size: bytes.length, sha256: hash(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }, origin: 'report' },
    csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: !route.request().url().includes('readonly'),
  } }) })
  await page.route('**/reports/v1/native/fixture-gridlines-*/1/api/file', route => route.fulfill({ body: bytesFor(route.request().url()), contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
  await page.route('**/reports/v1/native/fixture-gridlines-*/1/api/preview', route => { const model = sourceFor(route.request().url()).model; return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } }) })
  for (const action of ['save', 'export']) await page.route('**/reports/v1/native/fixture-gridlines-*/1/api/' + action, route => { savePayloads.push({ action, payload: route.request().postDataJSON() }); return route.fulfill({ status: 500, json: { detail: '网格视图不应保存或导出' } }) })
  await page.route(/\/reports\/v1\/native\/fixture-gridlines-[a-z]+\/1$/, async route => route.fulfill({ response: await route.fetch({ url: base + '/reports/v1/editor/assets/native.html' }) }))
  const body = () => page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const snapshot = () => page.evaluate(() => ({
    draft: Object.fromEntries(Object.entries(localStorage)),
    text: document.querySelector('[aria-label="Word 文档编辑区"]')?.textContent,
    columnCount: getComputedStyle(document.querySelector('[aria-label="Word 文档编辑区"]')).columnCount,
    style: document.querySelector('[aria-label="Word 文档编辑区"]')?.getAttribute('style'),
    status: document.querySelector('.save-state-label')?.textContent,
    // PM 移除 decoration 后可能留下 style=""；比较 CSS 声明，避免把它与无 style 属性误判为布局变化。
    layout: [...document.querySelector('[aria-label="Word 文档编辑区"]').children].map(node => ({ idx: node.getAttribute('data-idx'), style: node.style.cssText, text: node.textContent })),
  }))
  const paint = () => body().evaluate(node => {
    const css = getComputedStyle(node)
    return { image: css.backgroundImage, size: css.backgroundSize, origin: css.backgroundOrigin, clip: css.backgroundClip, gridColor: css.getPropertyValue('--docs-paper-grid').trim() }
  })
  const expectSourceGrid = async () => {
    const value = await paint()
    assert.equal(value.image.split('linear-gradient(').length - 1, 2, '复用源两方向对齐网格')
    for (const size of value.size.split(',')) assert.equal(size.trim(), '24px 24px')
    for (const origin of value.origin.split(',')) assert.equal(origin.trim(), 'content-box')
    for (const clip of value.clip.split(',')) assert.equal(clip.trim(), 'content-box')
    assert.ok(value.gridColor, '沿用源 docs-paper-grid 主题变量')
    return value
  }
  const results = []
  for (const mode of process.env.DOCX_GRIDLINES_CASE ? [process.env.DOCX_GRIDLINES_CASE] : ['editable', 'readonly', 'mixed']) {
    stage = mode
    await page.goto(base + '/reports/v1/native/fixture-gridlines-' + mode + '/1')
    await page.locator('.docx-source-home').waitFor({ timeout: 60000 })
    await body().locator('h1').first().waitFor()
    await page.evaluate(async () => { await document.fonts.ready })
    await page.locator('[data-tab-id="view"]').click()
    const grid = page.locator('[data-action="gridlines-toggle"]')
    const outline = page.locator('[data-action="view-outline"]'), paged = page.locator('[data-action="view-page"]')
    assert.equal(await grid.isEnabled(), true); assert.equal(await grid.getAttribute('aria-pressed'), 'false')
    const before = await snapshot(), beforePaint = await paint()
    await grid.click(); assert.equal(await grid.getAttribute('aria-pressed'), 'true')
    const gridPaint = await expectSourceGrid()
    assert.deepEqual(await snapshot(), before, '网格切换不改正文/分栏/NativeDraft/全部storage/保存状态')
    await page.screenshot({ path: join(temporary, mode + '-grid.png'), fullPage: true })
    await outline.click(); assert.equal(await grid.getAttribute('aria-pressed'), 'true'); await expectSourceGrid()
    assert.equal(await body().locator('p').first().isVisible(), false)
    await page.screenshot({ path: join(temporary, mode + '-outline-grid.png'), fullPage: true })
    await paged.click(); assert.equal(await grid.getAttribute('aria-pressed'), 'true'); await expectSourceGrid()
    assert.equal(await body().locator('p').first().isVisible(), true)
    assert.deepEqual(await snapshot(), before, '大纲返回页面保留独立网格开关，原内容/分栏/存储不变')
    await grid.click(); assert.equal(await grid.getAttribute('aria-pressed'), 'false')
    assert.deepEqual(await paint(), beforePaint); assert.deepEqual(await snapshot(), before)
    let undoRedo = null
    if (mode === 'editable') {
      await body().locator('p').first().click(); await page.keyboard.press('End'); await page.keyboard.type(' GRIDEDIT')
      await page.waitForFunction(() => document.querySelector('[aria-label="Word 文档编辑区"]').textContent.includes(' GRIDEDIT'))
      const changed = await snapshot()
      assert.ok(Object.entries(changed.draft).filter(([key]) => key.startsWith('native-editor-draft:')).some(([, value]) => JSON.parse(value).operations.length > 0))
      await grid.click(); await grid.click(); assert.deepEqual(await snapshot(), changed, '已有正文草稿不被网格切换改写')
      await page.keyboard.press('Control+z'); assert.equal((await snapshot()).text, before.text)
      await grid.click(); await page.keyboard.press('Control+Shift+z'); assert.equal((await snapshot()).text, changed.text)
      await page.keyboard.press('Control+z'); assert.equal((await snapshot()).text, before.text)
      await grid.click(); undoRedo = true
    }
    results.push({ mode, gridPaint, draftStorageUnchanged: true, pageAndColumnsRestored: true, outlineGridPreserved: true, undoRedo })
  }
  assert.deepEqual(savePayloads, [])
  await Promise.all(chunkChecks)
  assert.ok([...chunks.keys()].some(file => file.startsWith('assets/lazy-docx-main-') && file.endsWith('.js')))
  assert.equal(hash(await readFile(manifestPath)), hash(manifest), 'smoke 期间构建身份不变')
  const bridgeAfterSha256 = hash(await readFile(bridgePath))
  assert.equal(bridgeAfterSha256, bridgeSha256, 'smoke 期间 engine 身份不变')
  assert.deepEqual(errors, [])
  const result = { ok: true, temporary, staticRoot, runtime, sourceSha256: Object.fromEntries(Object.entries(sources).map(([key, value]) => [key, value.model.sourceSha256])), manifestSha256: hash(manifest), bridgeSha256, bridgeAfterSha256, loadedChunks: Object.fromEntries(chunks), results, saveExportRequests: savePayloads, errors }
  await writeFile(join(temporary, 'result.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result))
} catch (error) {
  if (page) { await writeFile(join(temporary, 'failure.html'), await page.content()); await page.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }) }
  console.error(JSON.stringify({ stage, temporary })); throw error
} finally { await browser?.close(); server?.kill() }
