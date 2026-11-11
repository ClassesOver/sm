// 独立 built GUI 探针：真实 DOCX -> Chromium DOM 输入 -> 草稿刷新 -> 公开保存 -> Python patch -> 下载回读。
// 只启动 vite preview，不构建；调用前须由集成人员完成当前源码构建。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_NESTED_SMOKE_PORT ?? 4237)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-nested-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-nested-built-'))
const sourcePath = join(temporary, 'revision-1.docx')
const runPython = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', String.raw`
import base64, json, re, sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from hashlib import sha256
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
p=json.load(sys.stdin)
if p['mode']=='patch':
    data=patch_docx(Path(p['sourcePath']).read_bytes(),p['operations'])
    Path(p['outputPath']).write_bytes(data)
    print(base64.b64encode(data).decode())
else:
    data=Path(p['path']).read_bytes()
    with ZipFile(BytesIO(data)) as package:
        xml=package.read('word/document.xml').decode()
        # 按同名标签深度取完整片段，仅用于已知纯直属 fixture 的独立字节核对。
        def spans(text,tag):
            stack=[]; out=[]
            for m in re.finditer(r'</?w:'+tag+r'\b[^>]*>',text):
                if m.group().startswith('</'):
                    start,depth=stack.pop(); out.append((start,m.end(),depth))
                elif not m.group().endswith('/>'): stack.append((m.start(),len(stack)))
            return sorted(out)
        tables=[(a,b) for a,b,d in spans(xml,'tbl') if d==1]
        assert len(tables)==2
        a,b=tables[1]; inner=xml[a:b]
        ca,cb,_=spans(inner,'tc')[0]
        masked=xml[:a+ca]+'__TARGET_CELL__'+xml[a+cb:]
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        root=etree.fromstring(xml.encode())
        outer=root.find('w:body/w:tbl/w:tr/w:tc',ns)
        nested=outer.findall('w:tbl',ns)
        # w:t / w:tab / w:br 还原为协议字符，而非依赖 Word 的扁平 cell.text。
        def paras(cell):
            result=[]
            for para in cell.findall('w:p',ns):
                result.append(''.join((node.text or '') if node.tag=='{'+ns['w']+'}t' else '\t' if node.tag=='{'+ns['w']+'}tab' else '\n' if node.tag=='{'+ns['w']+'}br' else '' for node in para.iter()))
            return result
        details={'nested':[paras(t.find('w:tr/w:tc',ns)) for t in nested], 'outerParagraphs':paras(outer),
            'firstTableSha256':sha256(xml[tables[0][0]:tables[0][1]].encode()).hexdigest(),
            'nonTargetXmlSha256':sha256(masked.encode()).hexdigest(),
            'parts':{name:sha256(package.read(name)).hexdigest() for name in package.namelist() if name!='word/document.xml' and not name.endswith('/')}}
    print(json.dumps({'model':inspect_docx(data),'details':details},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server, browser, page, stage = 'setup'
try {
  await writeFile(sourcePath, await readFile(process.env.DOCX_NESTED_SOURCE ?? '/tmp/word-nested-anchor-resume/source.docx'))
  const sourceBytes = await readFile(sourcePath)
  const source = JSON.parse(runPython({ mode: 'inspect', path: sourcePath }))
  assert.deepEqual(source.details.nested, [['same'], ['same']])
  assert.deepEqual(source.details.outerParagraphs, ['before', 'after'])
  const anchor = source.model.blocks.find(block => block.type === 'table')
  assert.equal(anchor.nestedTables.length, 2, '当前真实 inspect 必须签发两张内层表来源')
  const [first, second] = anchor.nestedTables
  assert.notEqual(first.tableId, second.tableId)
  assert.notEqual(first.cells[0][0].cellId, second.cells[0][0].cellId)
  assert.equal(first.expectedObjectSha256, second.expectedObjectSha256)
  const revisions = new Map([[1, sourceBytes]])
  const inspections = new Map([[1, source]])
  const savePayloads = []
  let routeError
  server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
  let serverLog = ''
  server.stderr.on('data', chunk => { serverLog += chunk })
  for (let attempt = 0; ; attempt++) {
    if (server.exitCode !== null) throw new Error(`preview exited: ${serverLog}`)
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    if (attempt === 120) throw new Error(`preview timeout: ${serverLog}`)
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  const errors = [], checks = [], chunks = new Map()
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('dialog', dialog => dialog.accept())
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (!path.startsWith('/reports/v1/editor/assets/assets/') || !path.endsWith('.js')) return
    checks.push((async () => {
      assert.equal(response.status(), 200)
      const file = path.split('/').at(-1), actual = await response.body(), expected = await readFile(join(frontend, '../static/assets', file))
      assert.equal(sha256(actual), sha256(expected), `浏览器构建文件身份：${file}`)
      chunks.set(file, sha256(actual))
    })())
  })
  const revisionOf = request => Number(new URL(request.url()).pathname.split('/')[5])
  await page.route(`**/reports/v1/native/${documentId}/*/api/context`, route => {
    const revision = revisionOf(route.request()), bytes = revisions.get(revision)
    return route.fulfill({ json: { context: { documentId, format: 'docx', revision, parentRevision: revision === 1 ? null : revision - 1,
      scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: `revision-${revision}.docx`, size: bytes.length, sha256: sha256(bytes), mediaType }, origin: 'report' },
      csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: true } })
  })
  await page.route(`**/reports/v1/native/${documentId}/*/api/file`, route => route.fulfill({ body: revisions.get(revisionOf(route.request())), contentType: mediaType }))
  await page.route(`**/reports/v1/native/${documentId}/*/api/preview`, route => {
    const model = inspections.get(revisionOf(route.request())).model
    return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } })
  })
  await page.route(`**/reports/v1/native/${documentId}/*/api/save`, async route => {
    try {
      const revision = revisionOf(route.request()), next = revision + 1, payload = route.request().postDataJSON()
      savePayloads.push(payload)
      const outputPath = join(temporary, `revision-${next}.docx`)
      const bytes = Buffer.from(runPython({ mode: 'patch', sourcePath: join(temporary, `revision-${revision}.docx`), outputPath, operations: payload.operations }), 'base64')
      revisions.set(next, bytes); inspections.set(next, JSON.parse(runPython({ mode: 'inspect', path: outputPath })))
      await route.fulfill({ json: { documentId, revision: next, parentRevision: revision, revisionRegistered: true,
        artifacts: { word: { downloadUrl: `/nested-download-${next}.docx`, size: bytes.length, sha256: sha256(bytes) } }, editor: { openUrl: `/reports/v1/native/${documentId}/${next}` }, validation: { ok: true, issues: [] } } })
    } catch (error) { routeError = String(error); await route.fulfill({ status: 500, json: { detail: routeError } }) }
  })
  await page.route(/\/nested-download-\d+\.docx$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/-(\d+)\.docx$/)[1])), contentType: mediaType }))
  await page.route(new RegExp(`/reports/v1/native/${documentId}/\\d+$`), async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
  const open = async revision => { await page.goto(`${baseUrl}/reports/v1/native/${documentId}/${revision}`); await page.locator('.docx-source-home').waitFor({ timeout: 60000 }) }
  const islands = () => page.locator('.doc-nested-table')
  const cell = ordinal => islands().nth(ordinal).locator('td[contenteditable="true"]').first()
  const selectCellText = async () => {
    await page.keyboard.press('Control+a')
    assert.equal(await focusInsideSecond(), true, 'Ctrl+A 保持当前内层输入岛焦点')
    const selected = await page.evaluate(() => { const selection = window.getSelection(), td = document.querySelectorAll('.doc-nested-table')[1]?.querySelector('td'); return !!selection && !!td && td.contains(selection.anchorNode) && td.contains(selection.focusNode) })
    assert.equal(selected, true, 'Ctrl+A 只选择当前内层单元格文字')
  }
  const focusInsideSecond = () => page.evaluate(() => document.querySelectorAll('.doc-nested-table')[1]?.contains(document.activeElement))
  const readDraft = () => page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).map(key => JSON.parse(localStorage.getItem(key))))
  stage = 'open1'
  await open(1)
  assert.equal(await islands().count(), 2)
  stage = 'draft-input'
  await cell(1).click()
  await selectCellText(); await page.keyboard.type('草稿第二张')
  await page.getByRole('textbox', { name: 'Word 文档编辑区' }).locator('p').filter({ hasText: 'before' }).click()
  await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && localStorage.getItem(key).includes('replaceNestedCellText')))
  const drafts = await readDraft()
  assert.ok(JSON.stringify(drafts).includes(second.cells[0][0].cellId))
  stage = 'draft-refresh'
  await page.reload(); await page.locator('.docx-source-home').waitFor({ timeout: 60000 })
  assert.equal(await cell(0).innerText(), 'same')
  assert.equal(await cell(1).innerText(), '草稿第二张')
  stage = 'nested-command-guards'
  // 先让外层 PM 表格选区有效，再进入同一内层岛；命令不得沿用外层目标。
  await cell(1).click()
  await page.locator('[data-tab-id="tableLayout"]').evaluate(button => button.click())
  for (const action of ['table-repeat-header-rows', 'table-insert-row-after']) {
    await cell(1).click()
    const control = page.locator(`[data-action="${action}"]`)
    assert.equal(await control.isDisabled(), true, `${action} 在内层岛中必须明确拒绝`)
    assert.match(await control.getAttribute('title') ?? '', /嵌套/)
    await control.evaluate(button => button.click())
  }
  stage = 'focused-save'
  // 仅用浏览器键盘输入；Enter 应形成多段和尾空段。最后一次输入绝不通过 blur 提交。
  await cell(1).click(); await selectCellText(); await page.keyboard.type('第二张最终中文😀$&')
  await page.keyboard.press('Enter'); await page.keyboard.type('第二段')
  await page.keyboard.press('Enter')
  assert.equal(await focusInsideSecond(), true)
  await page.locator('[data-action="save"]').evaluate(button => button.click())
  await page.waitForFunction(() => (document.querySelector('.save-state-label')?.textContent ?? '').includes('已保存修订 2'), null, { timeout: 60000 }).catch(async error => { throw new Error(`${error}\nroute=${routeError}\nstatus=${await page.locator('.save-state-label').textContent()}`) })
  assert.equal(routeError, undefined)
  assert.equal(savePayloads.length, 1)
  const expectedParagraphs = ['第二张最终中文😀$&', '第二段', '']
  assert.deepEqual(savePayloads[0].operations, [{ kind: 'replaceNestedCellText', blockId: anchor.blockId, tableId: second.tableId, cellId: second.cells[0][0].cellId, expectedObjectSha256: second.cells[0][0].expectedObjectSha256, paragraphs: expectedParagraphs }])
  const downloaded = Buffer.from(await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/nested-download-2.docx')).arrayBuffer()))))
  assert.equal(sha256(downloaded), sha256(revisions.get(2)))
  await writeFile(join(temporary, 'downloaded-revision-2.docx'), downloaded)
  const reread = JSON.parse(runPython({ mode: 'inspect', path: join(temporary, 'downloaded-revision-2.docx') }))
  assert.deepEqual(reread.details.nested, [['same'], expectedParagraphs])
  for (const key of ['outerParagraphs', 'firstTableSha256', 'nonTargetXmlSha256', 'parts']) assert.deepEqual(reread.details[key], source.details[key], `保留非目标 ${key}`)
  stage = 'reopen2'
  await open(2)
  assert.equal(await cell(0).innerText(), 'same')
  assert.ok((await cell(1).innerText()).includes('第二张最终中文😀$&'))
  assert.deepEqual(inspections.get(2).model.blocks.find(block => block.type === 'table').nestedTables[1].cells[0][0].paragraphs, expectedParagraphs)
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  await page.screenshot({ path: join(temporary, 'revision-2-reopened.png'), fullPage: true })
  await writeFile(join(temporary, 'revision-2-reopened.html'), await page.content())
  console.log(JSON.stringify({ ok: true, browserVersion: browser.version(), temporary, sourceSha256: sha256(sourceBytes), downloadedSha256: sha256(downloaded), operation: savePayloads[0].operations[0], draftRefreshRestored: true, saveWithoutBlur: true, commandsRejected: true, nonTargetXmlAndPartsPreserved: true, reopened: reread.details.nested, loadedChunks: Object.fromEntries(chunks), errors }))
} catch (error) {
  if (page) {
    await writeFile(join(temporary, 'failure.html'), await page.content()).catch(() => {})
    await page.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }).catch(() => {})
    console.error(JSON.stringify({ stage, temporary, status: await page.locator('.save-state-label').textContent().catch(() => null) }))
  }
  throw error
} finally {
  await browser?.close()
  server?.kill()
}
