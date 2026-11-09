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
// insert（默认）：封面/分页/空白页/表格；followup：封面替换+改标题+表格，修订 2 上改表格单元格并删除封面。
const smokeCase = process.env.DOCX_INSERT_CASE ?? 'insert'
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
  const revisions = new Map([[1, sourceBytes]])
  const inspections = new Map([[1, sourceInspection]])
  const savePayloads = new Map()
  let savedBytes, savePayload
  server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  for (let attempt = 0; attempt < 120; attempt++) { try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && !/WebSocket|\[vite\] failed to connect/.test(message.text())) pageErrors.push(message.text()) })
  const revisionOf = request => Number(new URL(request.url()).pathname.split('/')[5])
  await page.route('**/reports/v1/native/fixture-insert/*/api/context', route => { const revision = revisionOf(route.request()), bytes = revisions.get(revision); return route.fulfill({ json: {
    context: { documentId: 'fixture-insert', format: 'docx', revision, parentRevision: revision === 1 ? null : revision - 1, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
      sourceFile: { path: `revision-${revision}.docx`, size: bytes.length, sha256: sha256(bytes), mediaType }, origin: 'report' },
    csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: true } }) })
  await page.route('**/reports/v1/native/fixture-insert/*/api/file', route => route.fulfill({ body: revisions.get(revisionOf(route.request())), contentType: mediaType }))
  await page.route('**/reports/v1/native/fixture-insert/*/api/preview', route => { const model = inspections.get(revisionOf(route.request())).model; return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } }) })
  await page.route('**/reports/v1/native/fixture-insert/*/api/save', async route => {
    const revision = revisionOf(route.request()), next = revision + 1
    savePayload = route.request().postDataJSON(); savePayloads.set(revision, savePayload)
    const input = join(temporary, `revision-${revision}.docx`), output = join(temporary, `revision-${next}.docx`)
    await import('node:fs/promises').then(fs => fs.writeFile(input, revisions.get(revision)))
    savedBytes = Buffer.from(runPython({ mode: 'patch', sourcePath: input, outputPath: output, operations: savePayload.operations }), 'base64')
    revisions.set(next, savedBytes); inspections.set(next, JSON.parse(runPython({ mode: 'inspect', bytes: savedBytes.toString('base64') })))
    await route.fulfill({ json: { documentId: 'fixture-insert', revision: next, parentRevision: revision, revisionRegistered: true,
      artifacts: { word: { downloadUrl: `/fixture-insert-download-${next}.docx`, size: savedBytes.length, sha256: sha256(savedBytes) } },
      editor: { openUrl: `/reports/v1/native/fixture-insert/${next}` }, validation: { ok: true, issues: [] } } })
  })
  await page.route(/\/fixture-insert-download-\d+\.docx$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/-(\d+)\.docx$/)[1])), contentType: mediaType }))
  await page.route(/\/reports\/v1\/native\/fixture-insert\/\d+$/, async route => { await route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }) })
  const open = async revision => { await page.goto(`${baseUrl}/reports/v1/native/fixture-insert/${revision}`); await page.locator('.docx-source-home').waitFor({ timeout: 60000 }) }
  await open(1)
  const editor = page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const insert = async action => {
    const button = page.locator(`.docx-source-insert [data-action="${action}"]`)
    await delay(300)
    assert.equal(await button.isDisabled(), false, `${action} must be enabled: ${await button.getAttribute('title')}`)
    await button.click()
  }
  await page.locator('[data-tab-id="insert"]').click()
  const save = async revision => {
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(expected => (document.querySelector('.save-state-label')?.textContent ?? '').includes(`已保存修订 ${expected}`), revision, { timeout: 60000 })
    const download = await page.evaluate(async url => { const r = await fetch(url); return Array.from(new Uint8Array(await r.arrayBuffer())) }, `/fixture-insert-download-${revision}.docx`)
    return JSON.parse(runPython({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
  }
  if (smokeCase === 'followup') {
    // 修订 1：经典封面 → 替换为色带封面 → 改标题占位；第三段末尾插入 1×2 表格。
    await editor.locator('p').filter({ hasText: '第一段正文' }).click()
    await insert('insert-cover-page'); await page.locator('[data-cover-preset="classic"]').click()
    await insert('insert-cover-page'); await page.locator('[data-cover-preset="banded"]').click()
    await editor.locator('p').filter({ hasText: '文档标题' }).click(); await page.keyboard.press('End'); await page.keyboard.press('Shift+Home')
    await page.keyboard.type('年度经营报告')
    await editor.locator('p').filter({ hasText: '第三段' }).click(); await page.keyboard.press('End')
    await insert('insert-table'); await page.locator('[data-table-size="1x2"]').click()
    const revision2 = await save(2)
    // 修订 2：重开后编辑已保存表格首格；删除封面。
    await open(2)
    await page.locator('[data-tab-id="insert"]').click()
    await editor.locator('td p, th p').first().click(); await page.keyboard.type('后填')
    await delay(500)
    await insert('insert-cover-page'); await page.locator('[data-action="remove-cover-page"]').click()
    const revision3 = await save(3)
    console.log(JSON.stringify({ ok: true, case: smokeCase, browserVersion: browser.version(), rev2Ops: savePayloads.get(1).operations.map(op => op.kind), rev3Ops: savePayloads.get(2).operations.map(op => op.kind), rev2: revision2.body, rev2Bookmarks: revision2.bookmarks, rev3: revision3.body, rev3Bookmarks: revision3.bookmarks, pageErrors }))
    const rev2Cover = revision2.body.slice(0, revision2.body.findIndex(item => item[1] === '第一段正文'))
    assert.ok(rev2Cover.some(item => item[1] === '年度经营报告'), '修订 2 封面标题为编辑后的文字')
    assert.ok(!rev2Cover.some(item => item[1] === '文档标题'), '替换后不残留旧封面')
    assert.equal(revision2.bookmarks.filter(name => name === '_GenOfficeCoverPage').length, 1, '只有一个封面')
    assert.deepEqual(revision2.body.slice(-2), [['tbl', 1, 2, ['', '']], ['p', '', false]])
    assert.deepEqual(revision3.body, [['p', '第一段正文', false], ['p', '第二段前半第二段后半', false], ['p', '第三段', false], ['tbl', 1, 2, ['后填', '']], ['p', '', false]])
    assert.ok(!revision3.bookmarks.includes('_GenOfficeCoverPage'))
    assert.deepEqual(pageErrors, [])
    process.exitCode = 0
  } else {

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

  const reopened = await save(2)
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
  }
} finally {
  await browser?.close()
  server?.kill()
}
