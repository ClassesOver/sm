// 真实浏览器验收（2026-11-08/09 对齐批次，Word 插入页签）：封面、分页符、空白页、插入表格并在
// 新表格内输入。真实 Chromium + vite 前端；context/file/preview 为替身路由，保存经真实
// Python patch_docx（桥接 + 引擎），下载字节由 python-docx/XML 独立回读。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_SMOKE_PORT ?? 4193)
const baseUrl = `http://127.0.0.1:${port}`
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-insert-gui-'))
const sourcePath = join(temporary, 'revision-1.docx'), savedPath = join(temporary, 'revision-2.docx')
const runPython = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64, json, sys
from io import BytesIO
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
payload = json.load(sys.stdin)
if payload['mode'] == 'create':
    document = Document()
    for text in ['第一段正文', '第二段前半第二段后半', '第三段']:
        document.add_paragraph(text)
    document.save(payload['path'])
    print(base64.b64encode(Path(payload['path']).read_bytes()).decode())
elif payload['mode'] == 'patch':
    result = patch_docx(Path(payload['sourcePath']).read_bytes(), payload['operations'])
    Path(payload['outputPath']).write_bytes(result)
    print(base64.b64encode(result).decode())
else:
    content = base64.b64decode(payload['bytes'])
    document = Document(BytesIO(content))
    body = []
    for child in document.element.body:
        tag = child.tag.split('}')[1]
        if tag == 'p':
            ppr = child.find(qn('w:pPr'))
            pbb = ppr is not None and ppr.find(qn('w:pageBreakBefore')) is not None
            body.append(['p', ''.join(t.text or '' for t in child.iter(qn('w:t'))), pbb])
        elif tag == 'tbl':
            rows = child.findall(qn('w:tr'))
            body.append(['tbl', len(rows), len(rows[0].findall(qn('w:tc'))), [''.join(t.text or '' for t in tc.iter(qn('w:t'))) for tc in rows[0].findall(qn('w:tc'))]])
    marks = [b.get(qn('w:name')) for b in document.element.body.iter(qn('w:bookmarkStart'))]
    print(json.dumps({'model': inspect_docx(content), 'body': body, 'bookmarks': marks}, ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server, browser
try {
  const sourceBytes = Buffer.from(runPython({ mode: 'create', path: sourcePath }), 'base64')
  const sourceInspection = JSON.parse(runPython({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
  let savedBytes, savePayload
  server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  for (let attempt = 0; attempt < 120; attempt++) { try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && !/WebSocket|\[vite\] failed to connect/.test(message.text())) pageErrors.push(message.text()) })
  await page.route('**/reports/v1/native/fixture-insert/1/api/context', route => route.fulfill({ json: {
    context: { documentId: 'fixture-insert', format: 'docx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
      sourceFile: { path: 'revision-1.docx', size: sourceBytes.length, sha256: sha256(sourceBytes), mediaType }, origin: 'report' },
    csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: true } }))
  await page.route('**/reports/v1/native/fixture-insert/1/api/file', route => route.fulfill({ body: sourceBytes, contentType: mediaType }))
  await page.route('**/reports/v1/native/fixture-insert/1/api/preview', route => route.fulfill({ json: { sourceSha256: sourceInspection.model.sourceSha256, draftSha256: sourceInspection.model.sourceSha256, model: sourceInspection.model } }))
  await page.route('**/reports/v1/native/fixture-insert/1/api/save', async route => {
    savePayload = route.request().postDataJSON()
    savedBytes = Buffer.from(runPython({ mode: 'patch', sourcePath, outputPath: savedPath, operations: savePayload.operations }), 'base64')
    await route.fulfill({ json: { documentId: 'fixture-insert', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { word: { downloadUrl: '/fixture-insert-download.docx', size: savedBytes.length, sha256: sha256(savedBytes) } },
      editor: { openUrl: '/reports/v1/native/fixture-insert/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/fixture-insert-download.docx', route => route.fulfill({ body: savedBytes, contentType: mediaType }))
  await page.route(/\/reports\/v1\/native\/fixture-insert\/1$/, async route => { await route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }) })
  await page.goto(`${baseUrl}/reports/v1/native/fixture-insert/1`)
  await page.locator('.docx-source-home').waitFor({ timeout: 60000 })
  const editor = page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const insert = async action => {
    const button = page.locator(`.docx-source-insert [data-action="${action}"]`)
    await delay(300)
    assert.equal(await button.isDisabled(), false, `${action} must be enabled: ${await button.getAttribute('title')}`)
    await button.click()
  }
  await page.locator('[data-tab-id="insert"]').click()

  // 1. 封面（经典）。
  await editor.locator('p').filter({ hasText: '第一段正文' }).click()
  await insert('insert-cover-page'); await page.locator('[data-cover-preset="classic"]').click()
  // 2. 分页符：第二段"第二段前半|第二段后半"。
  await editor.locator('p').filter({ hasText: '第二段前半' }).click(); await page.keyboard.press('Home')
  for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight')
  await insert('insert-page-break')
  // 3. 空白页：第三段末尾（文档末尾，不加尾随分页）。
  await editor.locator('p').filter({ hasText: '第三段' }).click(); await page.keyboard.press('End')
  await insert('insert-blank-page')
  // 4. 插入表格：光标在空白页空段 → 表格插在其上；首格输入文字。
  await insert('insert-table'); await page.locator('[data-table-size="2x3"]').click()
  await page.keyboard.type('单元格甲')
  await delay(500)

  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => /已保存修订 2/.test(document.querySelector('.save-state-label')?.textContent ?? ''), null, { timeout: 60000 })
  const download = await page.evaluate(async () => { const r = await fetch('/fixture-insert-download.docx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
  const reopened = JSON.parse(runPython({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
  console.log(JSON.stringify({ ok: true, browserVersion: browser.version(), operationKinds: savePayload.operations.map(op => op.kind), body: reopened.body, bookmarks: reopened.bookmarks, pageErrors }))
  const body = reopened.body
  const firstBody = body.findIndex(item => item[0] === 'p' && item[1] === '第一段正文')
  assert.ok(firstBody > 0, '封面位于正文之前')
  assert.equal(body[firstBody - 1][2], true, '封面以分页段结束')
  assert.deepEqual(reopened.bookmarks.slice(0, 2), ['_GenOfficeCoverPage', '_GenOfficeCoverPageEnd'])
  assert.deepEqual(body.slice(firstBody), [
    ['p', '第一段正文', false], ['p', '第二段前半', false], ['p', '第二段后半', true], ['p', '第三段', false],
    ['tbl', 2, 3, ['单元格甲', '', '']], ['p', '', true],
  ])
  assert.deepEqual(pageErrors, [])
} finally {
  await browser?.close()
  server?.kill()
}
