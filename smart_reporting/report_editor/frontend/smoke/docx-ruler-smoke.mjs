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
const port = Number(process.env.DOCX_TEST_PORT ?? process.env.DOCX_RULER_SMOKE_PORT ?? 4287)
const base = 'http://127.0.0.1:' + port
const temporary = process.env.DOCX_TEST_OUTPUT ? resolve(process.env.DOCX_TEST_OUTPUT) : await mkdtemp(join(tmpdir(), 'docx-ruler-'))
await mkdir(temporary, { recursive: true })
const fixture = spawnSync(join(repo, '.venv/bin/python'), ['-c', [
  'import base64,json', 'from io import BytesIO', 'from docx.shared import Twips', 'from docx import Document', 'from docx.oxml.ns import qn', 'from docx.enum.section import WD_SECTION_START',
  'from smart_reporting.reporting.delivery.docx_native import inspect_docx', 'doc=Document()', 'doc.sections[0].page_width=Twips(12240);doc.sections[0].left_margin=Twips(1440);doc.sections[0].right_margin=Twips(1440)',
  "doc.add_heading('RULER-A',1)", "doc.add_paragraph('BODY-PRESERVED-A')",
  "doc.add_heading('RULER-CHILD',2)", "doc.add_paragraph('BODY-PRESERVED-CHILD')",
  "doc.add_heading('RULER-B',1)", "doc.add_paragraph('BODY-PRESERVED-B')",
  "table=doc.add_table(rows=1,cols=1);table.cell(0,0).text='TABLE-PRESERVED'",
  'buf=BytesIO();doc.save(buf);data=buf.getvalue()',
  "uniform={'base64':base64.b64encode(data).decode(),'model':inspect_docx(data)}",
  "sec=doc.add_section(WD_SECTION_START.CONTINUOUS);sec._sectPr.find(qn('w:cols')).set(qn('w:num'),'1')",
  "doc.add_heading('RULER-C',1);doc.add_paragraph('MIXED-SECTION-PRESERVED')",
  'buf=BytesIO();doc.save(buf);data=buf.getvalue()',
  "print(json.dumps({'uniform':uniform,'mixed':{'base64':base64.b64encode(data).decode(),'model':inspect_docx(data)}}))",
].join('\n')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime }, encoding: 'utf8', maxBuffer: 10 * 1024 * 1024, timeout: 120000 })
assert.equal(fixture.status, 0, fixture.stderr)
const sources = JSON.parse(fixture.stdout)
let saved
for (const [name, value] of Object.entries(sources)) await writeFile(join(temporary, 'source-' + name + '.docx'), Buffer.from(value.base64, 'base64'))
const sourceFor = url => url.includes('/2') ? saved : sources.uniform
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
  await page.route('**/reports/v1/native/fixture-ruler-*/*/api/context', route => { const bytes = bytesFor(route.request().url()), revision = route.request().url().includes('/2/') ? 2 : 1; return route.fulfill({ json: {
    context: { documentId: new URL(route.request().url()).pathname.split('/')[4], format: 'docx', revision, parentRevision: revision === 2 ? 1 : null,
      scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'ruler.docx', size: bytes.length, sha256: hash(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }, origin: 'report' },
    csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: !route.request().url().includes('readonly'),
  } }) })
  await page.route('**/reports/v1/native/fixture-ruler-*/*/api/file', route => route.fulfill({ body: bytesFor(route.request().url()), contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
  await page.route('**/reports/v1/native/fixture-ruler-*/*/api/preview', route => { const model = sourceFor(route.request().url()).model; return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } }) })
  await page.route('**/reports/v1/native/fixture-ruler-editable/1/api/save', route => {
    const payload = route.request().postDataJSON(); savePayloads.push(payload)
    const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', [
      'import base64,json,sys', 'from io import BytesIO', 'from docx import Document',
      'from smart_reporting.reporting.delivery.docx_native import patch_docx,inspect_docx',
      'p=json.load(sys.stdin);data=patch_docx(base64.b64decode(p["base64"]),p["operations"])',
      'doc=Document(BytesIO(data));sec=doc.sections[0]',
      'print(json.dumps({"base64":base64.b64encode(data).decode(),"model":inspect_docx(data),"right":doc.paragraphs[1].paragraph_format.right_indent.twips,"left":sec.left_margin.twips,"marginRight":sec.right_margin.twips,"text":[p.text for p in doc.paragraphs]}))',
    ].join('\n')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime }, input: JSON.stringify({ base64: sources.uniform.base64, operations: payload.operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024, timeout: 120000 })
    assert.equal(result.status, 0, result.stderr); saved = JSON.parse(result.stdout)
    assert.equal(saved.right, 90); assert.equal(saved.left, 1530); assert.equal(saved.marginRight, 1440)
    assert.equal(payload.operations.filter(op => op.kind === 'setParagraphRightIndent').length, 1)
    assert.equal(payload.operations.filter(op => op.kind === 'setSectionLayout').length, 1)
    assert.equal(payload.operations.length, 2)
    return route.fulfill({ json: { documentId: 'fixture-ruler-editable', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { word: { downloadUrl: '/fixture-ruler-revision-2.docx', size: Buffer.from(saved.base64, 'base64').length, sha256: saved.model.sourceSha256 } },
      editor: { openUrl: '/reports/v1/native/fixture-ruler-editable/2' }, validation: { ok: false, issues: [{ code: 'fixture_review', message: '尺规验收待复核，保留 Word 下载' }] } } })
  })
  await page.route('**/fixture-ruler-revision-2.docx', route => route.fulfill({ body: Buffer.from(saved.base64, 'base64'), contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers: { 'Content-Disposition': 'attachment; filename="ruler-revision-2.docx"' } }))
  await page.route(/\/reports\/v1\/native\/fixture-ruler-[a-z]+\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: base + '/reports/v1/editor/assets/native.html' }) }))
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
  const geometry = () => page.evaluate(() => {
    const ruler = document.querySelector('.ruler').getBoundingClientRect(), paper = document.querySelector('[aria-label="Word 文档编辑区"]').getBoundingClientRect()
    return { ruler: { left: ruler.left, width: ruler.width }, paper: { left: paper.left, width: paper.width } }
  })
  const assertAligned = async () => { const g = await geometry(); assert.ok(Math.abs(g.ruler.left - g.paper.left) < 2, JSON.stringify(g)); assert.ok(Math.abs(g.ruler.width - g.paper.width) < 2, JSON.stringify(g)); return g }
  const results = []
  for (const mode of process.env.DOCX_RULER_CASE ? [process.env.DOCX_RULER_CASE] : ['readonly', 'editable']) {
    stage = mode
    await page.goto(base + '/reports/v1/native/fixture-ruler-' + mode + '/1')
    await page.locator('.docx-source-home').waitFor({ timeout: 60000 }); await body().locator('p').first().waitFor()
    await body().locator('p').first().click(); await page.locator('[data-tab-id="view"]').click()
    const toggle = page.locator('[data-action="ruler-toggle"]'), before = await snapshot()
    assert.equal(await toggle.isEnabled(), true); await toggle.click()
    await page.locator('.ruler').waitFor(); assert.equal(await toggle.getAttribute('aria-pressed'), 'true')
    assert.deepEqual(await snapshot(), before, '显示尺规不改正文、草稿与保存状态')
    const initial = await assertAligned()
    for (const selector of ['.ruler-tab-type', '.ruler-ind-left', '.ruler-ind-firstLine', '.ruler-ind-hanging']) {
      const marker = page.locator(selector); assert.equal(await marker.getAttribute('aria-disabled'), 'true'); assert.ok(await marker.getAttribute('title'))
    }
    await page.locator('.ruler-ind-left').dispatchEvent('keydown', { key: 'ArrowRight' })
    await page.locator('.ruler').dispatchEvent('click', { clientX: 400 })
    assert.deepEqual(await snapshot(), before, '未支持标记不可绕过键鼠锁定')
    await page.locator('[data-action="view-放大"]').click()
    const zoomed = await assertAligned(); assert.ok(zoomed.ruler.width > initial.ruler.width)
    await page.locator('[data-action="view-100%"]').click(); await assertAligned()
    await page.screenshot({ path: join(temporary, mode + '-ruler.png'), fullPage: true })
    if (mode === 'readonly') {
      assert.equal(await page.locator('.ruler-ind-right').getAttribute('aria-disabled'), 'true')
      await page.locator('.ruler-ind-right').dispatchEvent('keydown', { key: 'ArrowLeft' })
      await page.locator('.ruler-margin-handle[data-side="left"]').dispatchEvent('keydown', { key: 'ArrowRight' })
      assert.deepEqual(await snapshot(), before)
    } else {
      assert.equal(await page.locator('.ruler-ind-right').getAttribute('aria-disabled'), 'false')
      await page.locator('.ruler-ind-right').press('ArrowLeft')
      await body().focus(); await page.keyboard.press('Control+z')
      assert.equal(await page.locator('.ruler-ind-right').getAttribute('aria-valuenow'), '10800')
      await body().focus(); await page.keyboard.press('Control+Shift+z')
      assert.equal(await page.locator('.ruler-ind-right').getAttribute('aria-valuenow'), '10710')
      await page.locator('.ruler-margin-handle[data-side="left"]').press('ArrowRight')
      assert.equal(await page.locator('.ruler-margin-handle[data-side="left"]').getAttribute('aria-valuenow'), '1530')
      await page.locator('[data-action="save"]').click()
      await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2')
      await page.getByText('尺规验收待复核，保留 Word 下载', { exact: true }).waitFor()
      const event = page.waitForEvent('download'); await page.getByRole('link', { name: '下载 Word', exact: true }).click()
      const download = await event, path = join(temporary, 'ruler-revision-2.docx'); await download.saveAs(path)
      assert.equal(hash(await readFile(path)), saved.model.sourceSha256)
      await page.goto(base + '/reports/v1/native/fixture-ruler-editable/2')
      await page.locator('.docx-source-home').waitFor({ timeout: 60000 }); await body().locator('p').first().click()
      await page.locator('[data-tab-id="view"]').click(); await page.locator('[data-action="ruler-toggle"]').click()
      assert.equal(await page.locator('.ruler-ind-right').getAttribute('aria-valuenow'), '10710')
      assert.equal(await page.locator('.ruler-margin-handle[data-side="left"]').getAttribute('aria-valuenow'), '1530')
      await assertAligned(); await page.screenshot({ path: join(temporary, 'reopened-ruler.png'), fullPage: true })
    }
    results.push({ mode, initial, zoomed, sourceMarkers: true, unsupportedWritesBlocked: true, ...(mode === 'editable' ? { savedRightTwips: saved.right, savedMarginLeft: saved.left, downloadedAndReopened: true } : { readonlyWritesBlocked: true }) })
  }
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
