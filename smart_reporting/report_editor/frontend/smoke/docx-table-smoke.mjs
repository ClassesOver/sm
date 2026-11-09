import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, writeFile, mkdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_SMOKE_PORT ?? 4192), baseUrl = `http://127.0.0.1:${port}`
const temporary = await mkdtemp(join(tmpdir(), 'docx-table-smoke-')), sourcePath = join(temporary, 'source.docx'), savedPath = join(temporary, 'saved.docx')
const sha = bytes => createHash('sha256').update(bytes).digest('hex'), mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const python = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64,json,sys
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
p=json.load(sys.stdin)
if p['mode']=='create':
 d=Document();d.add_paragraph('Untouched before')
 for k in range(5):
  t=d.add_table(rows=3,cols=3);t.autofit=False
  t._tbl.tblPr.find(qn('w:tblW')).set(qn('w:type'),'dxa');t._tbl.tblPr.find(qn('w:tblW')).set(qn('w:w'),'9000')
  for g,w in zip(t._tbl.tblGrid,[2401,3000,3599]):g.set(qn('w:w'),str(w))
  for r,row in enumerate(t.rows):
   if r==0:row._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
   for c,cell in enumerate(row.cells):
    cell._tc.get_or_add_tcPr().find(qn('w:tcW')).set(qn('w:w'),str([2401,3000,3599][c]))
    para=cell.paragraphs[0];para._p.set(qn('w:rsidR'),f'{k+1:02X}{r+1:02X}{c+1:04X}');para._p.get_or_add_pPr().append(OxmlElement('w:mirrorIndents'))
    para.add_run(f'T{k}R{r}C{c}').bold=True
  if k==4:t.cell(0,0).merge(t.cell(0,1))
 d.add_paragraph('Untouched after');d.sections[0].header.paragraphs[0].text='Untouched header';d.save(p['path'])
 print(base64.b64encode(Path(p['path']).read_bytes()).decode())
elif p['mode']=='inspect':print(json.dumps(inspect_docx(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 b=patch_docx(Path(p['source']).read_bytes(),p['operations']);Path(p['output']).write_bytes(b);print(base64.b64encode(b).decode())
else:
 before=Document(p['source']);after=Document(p['output']);report=[]
 for k,t in enumerate(after.tables):
  if k==4:
   assert etree.tostring(t._tbl,method='c14n')==etree.tostring(before.tables[k]._tbl,method='c14n');continue
  expected=[[f'T{k}R{r}C{c}' for c in range(3)] for r in range(3)]
  widths=[2401,3000,3599]
  if k==0:
   expected.insert(1,['','',''])
   for row in expected:row.insert(2,'')
   expected[2][2]='NEWCELL';widths=[2401,3000,1799,1800]
  if k==1:expected.pop(1)
  if k==2:
   for row in expected:row.insert(1,'')
   widths=[2401,1500,1500,3599]
  if k==3:
   for row in expected:row.pop(1)
   widths=[2401,6599]
  matrix=[[cell.text for cell in row.cells] for row in t.rows]
  assert matrix==expected,(k,matrix,expected)
  assert [int(g.get(qn('w:w'))) for g in t._tbl.tblGrid]==widths
  original={cell.text:etree.tostring(cell.paragraphs[0]._p,method='c14n') for row in before.tables[k].rows for cell in row.cells}
  for row in t.rows:
   for cell in row.cells:
    if cell.text in original:assert etree.tostring(cell.paragraphs[0]._p,method='c14n')==original[cell.text]
  report.append({'table':k,'matrix':matrix,'widthsTwips':widths})
 assert [p.text for p in after.paragraphs]==[p.text for p in before.paragraphs]
 with ZipFile(p['source']) as a,ZipFile(p['output']) as b:
  names={n for n in a.namelist() if not n.endswith('/')};assert names=={n for n in b.namelist() if not n.endswith('/')}
  for n in names-{'word/document.xml','docProps/core.xml'}:assert a.read(n)==b.read(n),n
 print(json.dumps(report))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || result.stdout)
  return result.stdout.trim()
}
const source = Buffer.from(python({ mode: 'create', path: sourcePath }), 'base64'), sourceModel = JSON.parse(python({ mode: 'inspect', bytes: source.toString('base64') }))
let saved, savedModel, payload
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(baseUrl + '/reports/v1/editor/assets/native.html')).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true }), errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/favicon.ico', route => route.fulfill({ status: 200, body: '' }))
  const revision = route => route.request().url().includes('/1/api/') ? 1 : 2
  await page.route('**/reports/v1/native/table-fixture/*/api/context', route => {
    const rev = revision(route), bytes = rev === 1 ? source : saved
    return route.fulfill({ json: { context: { documentId: 'table-fixture', revision: rev, parentRevision: rev === 1 ? null : 1, format: 'docx', sourceFile: { path: 'source.docx', size: bytes.length, sha256: sha(bytes), mediaType: mime }, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, origin: 'upload' }, editingEnabled: true, csrfToken: 'fixture', capabilities: { docx_editor: true } } })
  })
  await page.route('**/reports/v1/native/table-fixture/*/api/file', route => route.fulfill({ body: revision(route) === 1 ? source : saved, contentType: mime }))
  await page.route('**/reports/v1/native/table-fixture/*/api/preview', route => {
    const model = revision(route) === 1 ? sourceModel : savedModel
    assert.deepEqual(route.request().postDataJSON().operations, [])
    return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } })
  })
  await page.route('**/reports/v1/native/table-fixture/1/api/save', route => {
    payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, sha(source))
    saved = Buffer.from(python({ mode: 'patch', source: sourcePath, output: savedPath, operations: payload.operations }), 'base64')
    savedModel = JSON.parse(python({ mode: 'inspect', bytes: saved.toString('base64') }))
    return route.fulfill({ json: { documentId: 'table-fixture', revision: 2, parentRevision: 1, revisionRegistered: true, validation: { ok: false, issues: [{ code: 'fixture_review', message: '保留下载' }] }, artifacts: { word: { downloadUrl: '/table-download.docx', sha256: sha(saved), size: saved.length } }, editor: { openUrl: '/reports/v1/native/table-fixture/2' } } })
  })
  await page.route('**/table-download.docx', route => route.fulfill({ body: saved, contentType: mime, headers: { 'Content-Disposition': 'attachment; filename="table.docx"' } }))
  await page.route(/\/reports\/v1\/native\/table-fixture\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: baseUrl + '/reports/v1/editor/assets/native.html' }) }))
  const open = async rev => { await page.goto(baseUrl + `/reports/v1/native/table-fixture/${rev}`); try { await page.locator('.docx-source-home').waitFor({ timeout: 60000 }) } catch { throw new Error(JSON.stringify({ errors, body: await page.locator('body').innerText() })) } }
  const table = k => page.getByRole('textbox', { name: 'Word 文档编辑区' }).locator('table').nth(k)
  const locate = async (k, cell = 'R1C1') => { await table(k).getByText(`T${k}${cell}`, { exact: true }).click(); await page.locator('[data-tab-id="tableLayout"]').click() }
  const control = action => page.locator(`[data-action="${action}"]`)
  await open(1)
  await page.evaluate(() => { window.tableEvents = []; for (const name of ['mousedown', 'mouseup', 'click']) document.addEventListener(name, event => window.tableEvents.push([name, event.target.closest('[data-action]')?.getAttribute('data-action'), event.target.tagName]), true) })
  for (const [k, action] of [[0, 'table-insert-row-before'], [1, 'table-delete-row'], [2, 'table-insert-column-before'], [3, 'table-delete-column']]) {
    await locate(k)
    assert.equal(await control(action).isEnabled(), true, `${action}: ${await control(action).getAttribute('title')}`)
    if (k === 0 || k === 2) {
      await control(k === 0 ? 'table-insert-row-after' : 'table-insert-column-after').click()
      await page.keyboard.press('Control+z'); await locate(k)
    }
    await control(action).click()
    // 多步：同表结构修改后仍可继续修改（不必保存重开）。
    assert.equal(await control('table-insert-row-before').isEnabled(), true, JSON.stringify({ k, live: await page.evaluate(() => document.querySelector('.tiptap').editor.getJSON().content.filter(node => node.type === 'docTable').map(node => node.attrs.nativeTableStructure)), events: await page.evaluate(() => window.tableEvents), rows: await table(k).locator('tr').count(), notice: await page.locator('.docx-notice').innerText(), title: await control('table-insert-row-before').getAttribute('title'), html: (await table(k).innerHTML()).slice(0, 250) }))
    if (k === 0) {
      await page.keyboard.press('Control+z'); assert.equal(await table(0).locator('tr').count(), 3)
      await page.keyboard.press('Control+Shift+z'); assert.equal(await table(0).locator('tr').count(), 4)
      await page.reload(); await page.locator('.docx-source-home').waitFor({ timeout: 60000 })
      assert.equal(await table(0).locator('tr').count(), 4)
      // 刷新后草稿恢复，继续第二步：在 T0R1C1 右侧插入列并在新单元格输入。
      await locate(0); assert.equal(await control('table-insert-column-after').isEnabled(), true)
      await control('table-insert-column-after').click()
      await page.keyboard.type('NEWCELL')
      assert.equal(await table(0).locator('tr').nth(2).locator('td, th').nth(2).innerText(), 'NEWCELL')
    }
  }
  await locate(4, 'R1C1'); assert.equal(await control('table-delete-row').isDisabled(), true)
  assert.equal(await control('table-merge-cells').isDisabled(), true)
  const save = page.locator('[data-action="save"]')
  await save.click(); await page.getByRole('link', { name: '下载 Word', exact: true }).waitFor({ timeout: 60000 })
  assert.deepEqual(payload.operations.map(op => [op.kind, op.steps, op.texts]), [
    ['restructureTable', [{ kind: 'insertTableRow', index: 1 }, { kind: 'insertTableColumn', index: 2 }], [{ row: 2, column: 2, text: 'NEWCELL' }]],
    ['restructureTable', [{ kind: 'deleteTableRow', index: 1 }], undefined],
    ['restructureTable', [{ kind: 'insertTableColumn', index: 1 }], undefined],
    ['restructureTable', [{ kind: 'deleteTableColumn', index: 1 }], undefined],
  ])
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: '下载 Word', exact: true }).click()])
  const bytes = await readFile(await download.path()); assert.equal(sha(bytes), sha(saved))
  const readback = JSON.parse(python({ mode: 'verify', source: sourcePath, output: savedPath }))
  assert.equal(sha(await readFile(sourcePath)), sha(source))
  await open(2); await locate(0)
  assert.equal(await control('table-delete-row').isEnabled(), true)
  assert.equal(await table(0).locator('tr').count(), 4)
  assert.deepEqual(errors, [])
  const evidence = { ok: true, browserVersion: browser.version(), sourceSha256: sha(source), downloadedSha256: sha(saved), revision: 2, operations: payload.operations, readback, desktopVerified: false, provenance: 'browser routes substitute authorization/revisions; real packed bridge and independent file readback' }
  if (process.env.DOCX_SMOKE_EVIDENCE_DIR) { const dest = process.env.DOCX_SMOKE_EVIDENCE_DIR; await mkdir(dest, { recursive: true }); await writeFile(join(dest, 'source.docx'), source); await writeFile(join(dest, 'downloaded.docx'), saved); await writeFile(join(dest, 'evidence.json'), JSON.stringify(evidence, null, 2)) }
  console.log(JSON.stringify(evidence))
} finally { if (browser) await browser.close(); server.kill(); await rm(temporary, { recursive: true, force: true }) }
