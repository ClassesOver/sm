// 真实浏览器/Word 编辑器；本地 API 和 AI 建议为 fixture，不调用模型、不保存或导出。
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, extname } from 'node:path'
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import { chromium } from 'playwright'

const artifact = process.env.DOCX_COMPLEX_ARTIFACT ?? '/tmp/sr-word-complex-20261111'
const output = process.env.DOCX_COMPLEX_EVIDENCE ?? artifact + '/refresh-history'
const staticRoot = resolve(process.env.DOCX_TEST_DIST ?? new URL('../../static', import.meta.url).pathname)
const port = Number(process.env.DOCX_TEST_PORT ?? 4392), base = 'http://127.0.0.1:' + port
const prefix = '/reports/v1/editor/assets/', documentPath = '/reports/v1/native/fixture-pagination/1'
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const bytes = await readFile(resolve(artifact, 'downloaded-native.docx'))
const model = JSON.parse(await readFile(resolve(artifact, 'native-model.json'), 'utf8'))
assert.equal(sha(bytes), '7f4e32ee954f8eaaa98e97e904932369199971d323edf17b8cbbad578cde0391')
assert.equal(model.sourceSha256, sha(bytes))
const target = model.blocks.find(block => block.editable && block.text.startsWith('BODY101 '))
assert.ok(target)
const expectedManifestSha256 = process.env.DOCX_EXPECTED_MANIFEST_SHA256
assert.match(expectedManifestSha256 ?? '', /^[a-f0-9]{64}$/, '必须提供冻结静态目录的 DOCX_EXPECTED_MANIFEST_SHA256')
const manifestSha256 = sha(await readFile(resolve(staticRoot, '.vite/manifest.json')))
assert.equal(manifestSha256, expectedManifestSha256, '开始运行时静态 manifest 身份不符')
await mkdir(output, { recursive: true })
const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, base).pathname
    assert.ok(path.startsWith(prefix))
    const file = resolve(staticRoot, path.slice(prefix.length))
    assert.ok(file.startsWith(staticRoot + '/'))
    const body = await readFile(file)
    res.writeHead(200, { 'Content-Type': ({ '.js': 'application/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' })[extname(file)] ?? 'application/octet-stream' })
    res.end(body)
  } catch { res.writeHead(404); res.end('not found') }
})
await new Promise((ok, no) => { server.once('error', no); server.listen(port, '127.0.0.1', ok) })
let browser, currentPage
try {
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1500 } })
  currentPage = page
  const errors = [], chunks = {}, identities = [], saveExportRequests = [], aiRequests = [], cases = []
  let mode = 'accepted', candidate, accepted = 0
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) errors.push(response.status() + ' ' + path)
    if (response.ok() && path.startsWith(prefix) && path.endsWith('.js')) identities.push(response.body().then(async body => {
      assert.equal(sha(body), sha(await readFile(resolve(staticRoot, path.slice(prefix.length)))))
      chunks[path] = sha(body)
    }))
  })
  await page.route('**/favicon.ico', route => route.fulfill({ body: '', status: 200 }))
  await page.route('**' + documentPath, async route => route.fulfill({ body: await readFile(resolve(staticRoot, 'native.html')), contentType: 'text/html' }))
  await page.route('**' + documentPath + '/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/context')) return route.fulfill({ json: { context: { documentId: 'fixture-pagination', format: 'docx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'downloaded-native.docx', size: bytes.length, sha256: sha(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }, origin: 'report' }, csrfToken: 'fixture', capabilities: { docx_editor: true }, editingEnabled: true, aiEnabled: true } })
    if (path.endsWith('/file')) return route.fulfill({ body: bytes })
    if (path.endsWith('/preview')) return route.fulfill({ json: { sourceSha256: sha(bytes), draftSha256: sha(bytes), model } })
    if (path.endsWith('/ai/start')) {
      const request = route.request().postDataJSON()
      assert.ok(request.selection.some(selection => selection.blockId === target.blockId))
      aiRequests.push({ action: 'start', mode, request })
      candidate = { kind: 'replaceParagraph', blockId: mode === 'invalid' ? 'f'.repeat(64) : target.blockId, expectedObjectSha256: target.expectedObjectSha256, text: 'BODY101 REFRESH_BASELINE_' + (++accepted) }
      return route.fulfill({ json: { editId: 'refresh-' + accepted, status: 'succeeded', snapshotSha256: 'fixture-snapshot', proposal: { summary: '刷新历史专项候选', operations: [candidate] } } })
    }
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: 'id: 1\nevent: terminal\ndata: {"sequence":1,"kind":"terminal","status":"succeeded"}\n\n' })
    if (path.endsWith('/accept')) { aiRequests.push({ action: 'accept', mode, request: route.request().postDataJSON() }); return route.fulfill({ json: { operations: [candidate] } }) }
    if (path.endsWith('/cancel')) return route.fulfill({ json: { status: 'cancelled' } })
    saveExportRequests.push(path)
    return route.fulfill({ status: 500, json: { error: 'refresh smoke forbids save/export' } })
  })
  const body = page.locator('.editor-scroll .ProseMirror').first()
  const paragraph = () => body.locator('p').filter({ hasText: 'BODY101' }).first()
  const draft = () => page.evaluate(() => Object.fromEntries(Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:'))))
  const choose = async () => { await paragraph().click(); await page.locator('[data-tab-id=layout]').click() }
  const columns = () => page.locator('[data-source-action=layout-columns]')
  // 一次真实文本输入事件，避免复杂文档逐字渲染跨过 PM 的时间分组边界。
  const type = async text => { await paragraph().click(); await page.keyboard.press('End'); await page.keyboard.insertText(text) }
  const undo = async () => { await paragraph().click(); await page.keyboard.press('Control+z') }
  const redo = async () => { await paragraph().click(); await page.keyboard.press('Control+Shift+z') }
  const reset = async () => { await page.evaluate(() => localStorage.clear()); await page.reload(); await page.locator('.docx-source-home').waitFor({ timeout: 20000 }) }
  const adopt = async () => {
    await paragraph().click()
    await page.locator('.native-ai textarea').fill('刷新当前段落并以此建立历史基线')
    await page.locator('[data-ai=start]').click()
    await page.locator('[data-ai=accept]:not([disabled])').waitFor()
    await page.locator('[data-ai=accept]').click()
    if (mode === 'accepted') await page.waitForFunction(() => document.querySelector('.native-ai [role=status]')?.textContent?.startsWith('建议已进入草稿'))
    else await page.waitForFunction(() => !document.querySelector('[data-ai=accept]')?.disabled)
  }
  await page.goto(base + documentPath)
  await page.locator('.docx-source-home').waitFor({ timeout: 20000 })
  const firstEditor = await body.elementHandle()
  await type('_OLD_BODY')
  await choose(); await columns().selectOption('2')
  assert.equal(await columns().inputValue(), '2')
  await adopt()
  assert.equal(await body.evaluate((node, original) => node === original, firstEditor), true, '刷新必须保留同一 Editor DOM')
  const baseline = await body.innerText(), baselineDraft = await draft()
  assert.ok(baseline.includes('REFRESH_BASELINE_1')); assert.ok(!baseline.includes('_OLD_BODY'))
  await choose(); assert.equal(await columns().inputValue(), '1')
  await undo(); await redo()
  assert.equal(await body.innerText(), baseline); assert.deepEqual(await draft(), baselineDraft)
  await choose(); assert.equal(await columns().inputValue(), '1')
  cases.push({ name: 'old undo and native layout discarded after AI refresh', sameEditor: true })
  await page.screenshot({ path: resolve(output, '01-refreshed-baseline.png') })
  await type('_NEW_MANUAL')
  assert.ok((await body.innerText()).includes('_NEW_MANUAL'))
  await undo(); assert.equal(await body.innerText(), baseline)
  await redo(); assert.ok((await body.innerText()).includes('_NEW_MANUAL'))
  await undo(); await choose(); await columns().selectOption('2')
  await undo(); await choose(); assert.equal(await columns().inputValue(), '1')
  await redo(); await choose(); assert.equal(await columns().inputValue(), '2')
  await undo(); assert.equal(await body.innerText(), baseline)
  cases.push({ name: 'new body and native layout edits retain UndoRedo to refreshed baseline' })
  await page.screenshot({ path: resolve(output, '02-new-edit-history.png') })
  await reset()
  await type('_OLD_REDO')
  await choose(); await columns().selectOption('2')
  await undo(); await undo()
  assert.ok(!(await body.innerText()).includes('_OLD_REDO'))
  await adopt()
  const redoBaseline = await body.innerText(), redoDraft = await draft()
  await redo(); await undo()
  assert.equal(await body.innerText(), redoBaseline); assert.deepEqual(await draft(), redoDraft)
  await choose(); assert.equal(await columns().inputValue(), '1')
  cases.push({ name: 'redo-only old body and native layout discarded after AI refresh' })
  await page.screenshot({ path: resolve(output, '03-redo-boundary.png') })
  await reset(); mode = 'invalid'
  await type('_FAILED_REFRESH_KEPT')
  await choose(); await columns().selectOption('2')
  const beforeFailure = await body.innerText()
  await adopt()
  assert.equal(await body.innerText(), beforeFailure, '非法来源刷新不能替换当前正文')
  await choose(); assert.equal(await columns().inputValue(), '2')
  await undo(); await choose(); assert.equal(await columns().inputValue(), '1')
  await undo(); assert.ok(!(await body.innerText()).includes('_FAILED_REFRESH_KEPT'))
  cases.push({ name: 'failed replay preserves old body/native layout history' })
  await page.screenshot({ path: resolve(output, '04-failed-refresh-preserved-history.png') })
  await page.waitForLoadState('networkidle'); await Promise.all(identities)
  assert.deepEqual(errors, []); assert.deepEqual(saveExportRequests, [])
  assert.equal(sha(await readFile(resolve(staticRoot, '.vite/manifest.json'))), expectedManifestSha256, '结束运行时静态 manifest 身份不符')
  const evidence = { sourceSha256: sha(bytes), manifestSha256, expectedManifestSha256, fixtureAPI: true, fixtureAI: true, bridgeUsed: false, cases, aiRequests, chunks, errors, saveExportRequests }
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ok: true, output, manifestSha256, cases, errors, saveExportRequests }))
} catch (error) {
  await currentPage?.screenshot({ path: resolve(output, 'failure.png') })
  await writeFile(resolve(output, 'failure.json'), JSON.stringify({ message: error.message, stack: error.stack }, null, 2))
  throw error
} finally { await browser?.close(); await new Promise(ok => server.close(ok)) }
