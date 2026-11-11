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
const port = Number(process.env.DOCX_CELL_SHAPE_SMOKE_PORT ?? 4239)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-cell-shape-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-cell-shape-built-'))
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
if p['mode']=='fixture':
    from docx import Document
    doc=Document(); buf=BytesIO();doc.save(buf)
    def para(t,empty=False):
        return '<w:p w:rsidR="00ABCDEF"><w:pPr><w:keepNext/></w:pPr>'+('' if empty else '<w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr><w:t>'+t+'</w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>混合😀</w:t></w:r>')+'</w:p>'
    def cell(t): return '<w:tc><w:tcPr><w:tcW w:w="2401" w:type="dxa"/><w:shd w:val="pct20" w:color="AABBCC" w:fill="112233" w:themeFill="accent2" w:themeFillTint="99"/></w:tcPr>'+para(t)+para(t+'第二段')+para('',True)+'</w:tc>'
    table='<w:tbl><w:tblPr><w:tblW w:w="4802" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="2401"/><w:gridCol w:w="2401"/></w:tblGrid><w:tr>'+cell('A1中文')+cell('B1中文')+'</w:tr><w:tr>'+cell('A2中文')+cell('B2中文')+'</w:tr></w:tbl>'
    with ZipFile(BytesIO(buf.getvalue())) as zin, ZipFile(p['outputPath'],'w') as zout:
        for name in zin.namelist():
            data=zin.read(name)
            if name=='word/document.xml':
                xml=data.decode();xml=re.sub(r'(<w:body>)[\s\S]*?(<w:sectPr\b)',lambda m:m[1]+para('外部前')+table+para('外部后')+m[2],xml,count=1);data=xml.encode()
            zout.writestr(name,data)
    print('ok')
elif p['mode']=='patch':
    data=patch_docx(Path(p['sourcePath']).read_bytes(),p['operations'])
    Path(p['outputPath']).write_bytes(data)
    print(base64.b64encode(data).decode())
else:
    data=Path(p['path']).read_bytes()
    with ZipFile(BytesIO(data)) as package:
        xml=package.read('word/document.xml').decode()
        a=xml.index('<w:tbl>'); b=xml.index('</w:tbl>',a)+len('</w:tbl>');table=xml[a:b]
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        root=etree.fromstring(xml.encode()).find('w:body/w:tbl',ns)
        widths=[int(e.get('{'+ns['w']+'}w')) for e in root.findall('w:tblGrid/w:gridCol',ns)]
        paragraphs=re.findall(r'<w:p(?:\s[^>]*)?>[\s\S]*?</w:p>',table)
        model=inspect_docx(data);anchor=next(x for x in model['blocks'] if x['type']=='table')
        details={'widths':widths,'paragraphs':paragraphs,'cells':anchor['cellShapeCells'],
          'nonTargetXmlSha256':sha256((xml[:a]+'__TABLE__'+xml[b:]).encode()).hexdigest(),
          'parts':{name:sha256(package.read(name)).hexdigest() for name in package.namelist() if name!='word/document.xml' and not name.endswith('/')}}
    print(json.dumps({'model':model,'details':details},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server, browser, page, stage = 'setup'
try {
  runPython({ mode: 'fixture', outputPath: sourcePath })
  const sourceBytes = await readFile(sourcePath)
  const source = JSON.parse(runPython({ mode: 'inspect', path: sourcePath }))
  const anchor = source.model.blocks.find(block => block.type === 'table')
  assert.equal(anchor.cellShapeEditable, true)
  assert.equal(anchor.cellShapeCells.length, 4)
  assert.equal(source.details.paragraphs.length, 12)
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
        artifacts: { word: { downloadUrl: `/cell-shape-download-${next}.docx`, size: bytes.length, sha256: sha256(bytes) } }, editor: { openUrl: `/reports/v1/native/${documentId}/${next}` }, validation: { ok: true, issues: [] } } })
    } catch (error) { routeError = String(error); await route.fulfill({ status: 500, json: { detail: routeError } }) }
  })
  await page.route(/\/cell-shape-download-\d+\.docx$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/-(\d+)\.docx$/)[1])), contentType: mediaType, headers:{'Content-Disposition':'attachment; filename=cell-shape.docx'} }))
  await page.route(new RegExp(`/reports/v1/native/${documentId}/\\d+$`), async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
  const open = async revision => { await page.goto(`${baseUrl}/reports/v1/native/${documentId}/${revision}`); await page.locator('.docx-source-home').waitFor({ timeout: 60000 }) }
  const table = () => page.getByRole('textbox', { name: 'Word 文档编辑区' }).locator('table').first()
  const controls = action => page.locator(`[data-action="${action}"]`)
  const cells = () => table().locator('td,th')
  const dragAll = async () => {
    const first = await cells().first().boundingBox(), last = await cells().last().boundingBox()
    assert.ok(first && last)
    await page.mouse.move(first.x + 12, first.y + 12); await page.mouse.down()
    await page.mouse.move(last.x + last.width - 12, last.y + 14, { steps: 24 }); await page.mouse.up()
    await page.locator('[data-tab-id="tableLayout"]').click()
    await page.waitForFunction(() => document.querySelectorAll('.selectedCell').length === 4)
  }
  const split = async (rows, columns) => {
    await cells().first().locator('p').first().click()
    await page.locator('[data-tab-id="tableLayout"]').click()
    assert.equal(await controls('table-split-cells').isEnabled(), true)
    await controls('table-split-cells').click()
    const dialog = page.getByRole('dialog', { name: '拆分单元格', exact: true })
    assert.equal(await dialog.getByLabel('行数', { exact: true }).inputValue(), '1')
    assert.equal(await dialog.getByLabel('列数', { exact: true }).inputValue(), '2')
    assert.equal(await dialog.locator('[type="checkbox"]').isChecked(), true)
    if (rows !== undefined) await dialog.getByLabel('行数', { exact: true }).fill(String(rows))
    if (columns !== undefined) await dialog.getByLabel('列数', { exact: true }).fill(String(columns))
    await dialog.getByRole('button', { name: '确定', exact: true }).click()
    await dialog.waitFor({ state: 'detached' })
  }
  const history = async redo => { await page.keyboard.press(redo ? 'Control+Shift+z' : 'Control+z') }
  const saveAndDownload = async (revision, before) => {
    await controls('save').click()
    await page.waitForFunction(next => (document.querySelector('.save-state-label')?.textContent ?? '').includes(`已保存修订 ${next}`), revision + 1, { timeout: 60000 }).catch(async error => { throw new Error(`${error} route=${routeError} status=${await page.locator('.save-state-label').textContent()}`) })
    assert.equal(routeError, undefined)
    const link = page.getByRole('link', { name: '下载 Word', exact: true })
    await link.waitFor()
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()])
    const downloaded = await readFile(await download.path())
    assert.equal(sha256(downloaded), sha256(revisions.get(revision + 1)))
    const path = join(temporary, `downloaded-revision-${revision + 1}.docx`); await writeFile(path, downloaded)
    const reread = JSON.parse(runPython({ mode: 'inspect', path }))
    assert.deepEqual(reread.details.widths, [2401, 2401])
    assert.deepEqual(reread.details.parts, before.details.parts)
    assert.equal(reread.details.nonTargetXmlSha256, before.details.nonTargetXmlSha256)
    assert.deepEqual(reread.details.paragraphs.slice(0, 12), source.details.paragraphs, '全部原段落片段及顺序逐字保留')
    return { downloaded, reread }
  }
  stage = 'open1'; await open(1)
  stage = 'drag-select-merge'; await dragAll()
  assert.equal(await controls('table-merge-cells').isEnabled(), true)
  await controls('table-merge-cells').click(); assert.equal(await cells().count(), 1)
  stage = 'undo-redo'; await history(false); assert.equal(await cells().count(), 4)
  await history(true); assert.equal(await cells().count(), 1)
  stage = 'default-split'; await split(); assert.equal(await cells().count(), 2)
  assert.deepEqual(await cells().evaluateAll(list => list.map(cell => [cell.colSpan, cell.rowSpan])), [[1, 2], [1, 2]])
  await history(false); assert.equal(await cells().count(), 1)
  stage = 'explicit-split'; await split(2, 2); assert.equal(await cells().count(), 4)
  await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && localStorage.getItem(key).includes('reshapeTableCells')))
  stage = 'draft-refresh'; await page.reload(); await page.locator('.docx-source-home').waitFor({ timeout: 60000 }); assert.equal(await cells().count(), 4)
  stage = 'public-save'; const { downloaded, reread } = await saveAndDownload(1, source)
  assert.equal(savePayloads.length, 1)
  assert.deepEqual(savePayloads[0].operations.map(op => op.kind), ['reshapeTableCells'])
  assert.deepEqual(savePayloads[0].operations[0].steps.map(step => step.kind), ['mergeTableCells', 'splitTableCells'])
  assert.deepEqual(reread.details.cells.map(({ top,left,bottom,right }) => ({ top,left,bottom,right })), [{top:0,left:0,bottom:1,right:1},{top:0,left:1,bottom:1,right:2},{top:1,left:0,bottom:2,right:1},{top:1,left:1,bottom:2,right:2}])
  stage = 'reopen2'; await open(2); assert.equal(await cells().count(), 4)
  assert.ok((await cells().first().innerText()).includes('B2中文'))
  // 独立原始合并来源：先用真实Python协议生成ZIP，再作为新来源打开。
  const mergedPath = join(temporary, 'revision-10.docx')
  const mergedBytes = Buffer.from(runPython({ mode:'patch', sourcePath, outputPath:mergedPath, operations:[{kind:'reshapeTableCells',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,steps:[{kind:'mergeTableCells',rect:{top:0,left:0,bottom:2,right:2}}]}] }), 'base64')
  const mergedSource = JSON.parse(runPython({mode:'inspect',path:mergedPath})); revisions.set(10,mergedBytes);inspections.set(10,mergedSource)
  assert.equal(mergedSource.model.blocks.find(block=>block.type==='table').cellShapeEditable,true)
  stage = 'open-merged-source';await open(10);assert.equal(await cells().count(),1)
  await split(2,2)
  stage = 'save-merged-source';const secondSaved = await saveAndDownload(10,mergedSource)
  await open(11);assert.equal(await cells().count(),4)
  assert.deepEqual(savePayloads[1].operations[0].steps.map(step=>step.kind),['splitTableCells'])
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  await page.screenshot({ path: join(temporary, 'revision-11-reopened.png'), fullPage: true })
  await writeFile(join(temporary, 'revision-11-reopened.html'), await page.content())
  console.log(JSON.stringify({ ok:true,browserVersion:browser.version(),temporary,sourceSha256:sha256(sourceBytes),downloadedSha256:sha256(downloaded),mergedSourceSha256:sha256(mergedBytes),mergedDownloadedSha256:sha256(secondSaved.downloaded),operations:savePayloads.map(p=>p.operations),draftRefreshRestored:true,realMouseCellSelection:true,undoRedo:true,defaultAndExplicitSplit:true,originalParagraphBytesAndPartsPreserved:true,loadedChunks:Object.fromEntries(chunks),errors }))
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
