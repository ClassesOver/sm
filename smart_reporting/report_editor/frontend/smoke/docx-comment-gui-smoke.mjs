// 真实Chromium + 当前生产构建；context/file/preview/save HTTP路由为测试替身。
// 保存通过真实Python薄桥和当前生产（DOCX_COMMENT_ENGINE_DIR）或隔离打包Node bridge，下载以独立ZIP/lxml核对。
// 该证据不冒充真实FastAPI鉴权/HTTP发布链验收。失败后用打印的目录恢复，避免重复成功保存。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { access, mkdir, mkdtemp, readFile, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_COMMENT_SMOKE_PORT ?? 4198), baseUrl = 'http://127.0.0.1:' + port
const temporary = process.env.DOCX_COMMENT_SMOKE_DIR ?? await mkdtemp(join(tmpdir(), 'docx-comment-gui-'))
const checkpoint = join(temporary, 'checkpoint.json'), runtime = process.env.DOCX_COMMENT_ENGINE_DIR ?? join(temporary, 'engine')
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const buildManifestSha256 = sha256(await readFile(join(frontend, '../static/.vite/manifest.json')))
const changedText = '已核实的中文批注 😀', pendingText = '保存前未失焦的批注 😀'
console.log(JSON.stringify({ checkpointDirectory: temporary }))
await mkdir(temporary, { recursive: true })
try { await access(join(runtime, 'dist/edit-docx.mjs')) } catch {
  await mkdir(runtime, { recursive: true })
  for (const name of ['bridge', 'packages', 'node_modules', 'package.json']) {
    try { await access(join(runtime, name)) } catch { await symlink(join(repo, 'smart_reporting/reporting/doc_engine', name), join(runtime, name)) }
  }
  const bundled = spawnSync('npm', ['run', 'bundle:bridges'], { cwd: runtime, encoding: 'utf8', timeout: 120000 })
  assert.equal(bundled.status, 0, bundled.stderr)
}
const pythonSource = [
  'import base64, json, sys',
  'from io import BytesIO',
  'from pathlib import Path',
  'from zipfile import ZipFile',
  'from lxml import etree',
  'from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx',
  'from smart_reporting.reporting.tests.test_docx_comment_text_host import source',
  'p = json.load(sys.stdin)',
  'if p["mode"] == "create":',
  '    data = source(); Path(p["path"]).write_bytes(data)',
  '    print(json.dumps({"bytes": base64.b64encode(data).decode(), "model": inspect_docx(data)}))',
  'elif p["mode"] == "patch":',
  '    original = Path(p["source"]).read_bytes()',
  '    output = patch_docx(original, p["operations"])',
  '    Path(p["output"]).write_bytes(output)',
  '    print(json.dumps({"bytes": base64.b64encode(output).decode(), "model": inspect_docx(output)}))',
  'elif p["mode"] == "stale":',
  '    try: patch_docx(Path(p["source"]).read_bytes(), p["operations"])',
  '    except ValueError as error: print(json.dumps({"rejected": True, "reason": str(error)}))',
  '    else: raise AssertionError("stale comments accepted")',
  'else:',
  '    saved = base64.b64decode(p["bytes"])',
  '    with ZipFile(BytesIO(Path(p["source"]).read_bytes())) as before, ZipFile(BytesIO(saved)) as after:',
  '        assert after.testzip() is None; assert before.namelist() == after.namelist()',
  '        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]',
  '        assert changed == ["word/comments.xml"], changed',
  '        for name in after.namelist():',
  '            if name.endswith((".xml", ".rels")): etree.fromstring(after.read(name))',
  '        text = "".join(etree.fromstring(after.read("word/comments.xml")).xpath(".//w:t/text()", namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}))',
  '        assert text == p["expected"], text',
  '    print(json.dumps({"changed": changed, "text": text}))',
].join('\n')
const python = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', pythonSource], { cwd: repo, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024, timeout: 120000, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime } })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout.trim())
}
let state
try { state = JSON.parse(await readFile(checkpoint, 'utf8')) } catch (error) {
  if (error.code !== 'ENOENT') throw error
  state = { buildManifestSha256, revisions: { 1: python({ mode: 'create', path: join(temporary, 'revision-1.docx') }) }, payload: null }
  await writeFile(checkpoint, JSON.stringify(state))
}
assert.equal(state.buildManifestSha256, buildManifestSha256, 'checkpoint belongs to a different build; use a fresh directory and source')
let server, browser, debugPage
const viewportChecks = [], resumedSuccessfulSave = !!state.payload
try {
  server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  let serving = false
  for (let attempt = 0; attempt < 120; attempt++) {
    try { if ((await fetch(baseUrl + '/reports/v1/editor/assets/native.html')).ok) { serving = true; break } } catch {}
    await delay(250)
  }
  assert.equal(serving, true, 'built preview unavailable')
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } }), errors = [], chunks = new Map(), chunkChecks = []
  debugPage = page
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (!path.startsWith('/reports/v1/editor/assets/assets/') || !path.endsWith('.js')) return
    chunkChecks.push((async () => {
      assert.equal(response.status(), 200)
      const file = path.split('/').at(-1), actual = await response.body(), expected = await readFile(join(frontend, '../static/assets', file))
      assert.equal(sha256(actual), sha256(expected), file + ' must match current build')
      chunks.set(file, sha256(actual))
    })())
  })
  const revisionOf = request => Number(new URL(request.url()).pathname.split('/')[5])
  await page.route('**/reports/v1/native/fixture-comments/*/api/context', route => {
    const revision = revisionOf(route.request()), entry = state.revisions[revision], bytes = Buffer.from(entry.bytes, 'base64')
    return route.fulfill({ json: { context: { documentId: 'fixture-comments', format: 'docx', revision, parentRevision: revision > 1 ? revision - 1 : null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'revision-' + revision + '.docx', size: bytes.length, sha256: sha256(bytes), mediaType }, origin: 'report' }, csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: true } })
  })
  await page.route('**/reports/v1/native/fixture-comments/*/api/file', route => route.fulfill({ body: Buffer.from(state.revisions[revisionOf(route.request())].bytes, 'base64'), contentType: mediaType }))
  await page.route('**/reports/v1/native/fixture-comments/*/api/preview', route => {
    const model = state.revisions[revisionOf(route.request())].model
    return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } })
  })
  await page.route('**/reports/v1/native/fixture-comments/*/api/save', async route => {
    assert.equal(state.payload, null, 'checkpoint prevents repeating a successful source save')
    const revision = revisionOf(route.request()), payload = route.request().postDataJSON()
    assert.equal(payload.operations.length, 1); assert.equal(payload.operations[0].kind, 'editCommentText')
    assert.equal(payload.operations[0].text, pendingText)
    state.revisions[revision + 1] = python({ mode: 'patch', source: join(temporary, 'revision-' + revision + '.docx'), output: join(temporary, 'revision-' + (revision + 1) + '.docx'), operations: payload.operations })
    state.payload = payload
    await writeFile(checkpoint, JSON.stringify(state))
    const bytes = Buffer.from(state.revisions[revision + 1].bytes, 'base64')
    await route.fulfill({ json: { documentId: 'fixture-comments', revision: revision + 1, parentRevision: revision, revisionRegistered: true, artifacts: { word: { downloadUrl: '/comment-download.docx', size: bytes.length, sha256: sha256(bytes) } }, editor: { openUrl: '/reports/v1/native/fixture-comments/' + (revision + 1) }, validation: { ok: false, issues: [{ code: 'comment_review_pending', message: '批注版式验收待复核' }] } } })
  })
  await page.route('**/comment-download.docx', route => route.fulfill({ body: Buffer.from(state.revisions[2].bytes, 'base64'), contentType: mediaType }))
  await page.route(/\/reports\/v1\/native\/fixture-comments\/\d+$/, async route => route.fulfill({ response: await route.fetch({ url: baseUrl + '/reports/v1/editor/assets/native.html' }) }))
  const open = async revision => { await page.goto(baseUrl + '/reports/v1/native/fixture-comments/' + revision); await page.locator('.docx-source-home').waitFor({ timeout: 60000 }) }
  const panel = async () => {
    await page.locator('[data-tab-id="review"]').click()
    assert.equal(await page.locator('[data-action="comment-text-list"] svg path').count() > 0, true)
    await page.locator('[data-action="comment-text-list"]').click()
    // 必须在fill/locator自动滚动之前验收open本身的可见性与焦点。
    // 全站html使用smooth scroll；这里只等待open自己的滚动，不额外滚动任何控件。
    await page.waitForFunction(() => {
      const panel = document.querySelector('.docx-comment-panel'), input = panel?.querySelector('[data-comment-text]')
      if (!panel || panel.hidden || !input) return false
      const box = input.getBoundingClientRect()
      return box.top >= 0 && box.bottom <= innerHeight
    }, null, { timeout: 5000 })
    const visible = await page.evaluate(() => {
      const panel = document.querySelector('.docx-comment-panel'), input = panel.querySelector('[data-comment-text]'), save = document.querySelector('[data-action="save"]')
      const panelBox = panel.getBoundingClientRect(), inputBox = input.getBoundingClientRect(), saveBox = save.getBoundingClientRect()
      const hit = document.elementFromPoint(saveBox.x + saveBox.width / 2, saveBox.y + saveBox.height / 2)
      return { viewportHeight: innerHeight, panelTop: panelBox.top, inputTop: inputBox.top, inputBottom: inputBox.bottom, focused: document.activeElement === input, saveTop: saveBox.top, saveBottom: saveBox.bottom, saveEnabled: !save.disabled, saveHit: hit === save || save.contains(hit) }
    })
    assert.ok(visible.panelTop >= 0 && visible.panelTop < visible.viewportHeight, JSON.stringify(visible))
    assert.ok(visible.inputTop >= 0 && visible.inputBottom <= visible.viewportHeight, JSON.stringify(visible))
    assert.equal(visible.focused, true)
    assert.ok(visible.saveTop >= 0 && visible.saveBottom <= visible.viewportHeight, JSON.stringify(visible))
    assert.equal(visible.saveEnabled, true); assert.equal(visible.saveHit, true)
    viewportChecks.push(visible)
    await page.screenshot({ path: join(temporary, 'comments-open-viewport.png') })
    return page.getByRole('textbox', { name: '批注文字', exact: true })
  }
  if (!state.payload) {
    await open(1)
    const input = await panel()
    assert.equal(await input.isDisabled(), false); assert.equal(await input.inputValue(), 'Original note')
    await input.fill('明确放弃的输入'); await page.locator('[data-comment-reload]').click()
    assert.equal(await input.inputValue(), 'Original note')
    await input.fill(changedText); await page.locator('[data-comment-apply]').click()
    const editor = page.getByRole('textbox', { name: 'Word 文档编辑区' })
    await editor.click(); await page.keyboard.press('Control+z'); await page.waitForFunction(() => document.querySelector('[data-comment-text]')?.value === 'Original note')
    await page.keyboard.press('Control+Shift+z'); await page.waitForFunction(expected => document.querySelector('[data-comment-text]')?.value === expected, changedText)
    await page.reload(); await page.locator('.docx-source-home').waitFor({ timeout: 60000 })
    const restored = await panel(); assert.equal(await restored.inputValue(), changedText)
    await restored.fill(pendingText)
    assert.equal(await restored.evaluate(element => document.activeElement === element), true)
    // dispatch click不先blur，证明native-session本身flush，而非依赖浏览器焦点切换。
    await page.locator('[data-action="save"]').dispatchEvent('click')
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent.includes('已保存修订 2'), null, { timeout: 60000 })
    assert.equal(await restored.isDisabled(), true)
    assert.equal(await page.getByText('批注版式验收待复核', { exact: true }).count(), 1)
    assert.equal(await page.getByRole('link', { name: '下载 Word', exact: true }).count(), 1)
  } else { await open(2) }
  const downloaded = await page.evaluate(async url => { const response = await fetch(url); if (!response.ok) throw new Error('download failed'); return Array.from(new Uint8Array(await response.arrayBuffer())) }, baseUrl + '/comment-download.docx')
  const verified = python({ mode: 'verify', source: join(temporary, 'revision-1.docx'), bytes: Buffer.from(downloaded).toString('base64'), expected: pendingText })
  assert.equal(sha256(Buffer.from(downloaded)), sha256(Buffer.from(state.revisions[2].bytes, 'base64')))
  await open(2); assert.equal(await (await panel()).inputValue(), pendingText)
  assert.notEqual(state.revisions[2].model.comments.sourceId, state.revisions[1].model.comments.sourceId)
  const stale = python({ mode: 'stale', source: join(temporary, 'revision-2.docx'), operations: state.payload.operations })
  assert.equal(stale.rejected, true)
  await Promise.all(chunkChecks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  await page.screenshot({ path: join(temporary, 'comments-revision-2.png'), fullPage: true })
  const result = { ok: true, builtPreview: true, apiRoutesAreTestDoubles: true, realPythonNodeBridge: true, checkpointDirectory: temporary, engineRuntime: runtime, buildManifestSha256, nodeBridgeSha256: sha256(await readFile(join(runtime, 'dist/edit-docx.mjs'))), sourceSha256: state.revisions[1].model.sourceSha256, outputSha256: state.revisions[2].model.sourceSha256, resumedSuccessfulSave, viewportChecks, changedParts: verified.changed, savedText: verified.text, staleSourceRejected: true, loadedChunks: Object.fromEntries(chunks), errors }
  await writeFile(join(temporary, 'result.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result))
} catch (error) {
  await debugPage?.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(join(temporary, 'failure.json'), JSON.stringify({ message: String(error), stack: error.stack, savedCheckpoint: !!state.payload }, null, 2))
  throw error
} finally { await browser?.close(); server?.kill() }
