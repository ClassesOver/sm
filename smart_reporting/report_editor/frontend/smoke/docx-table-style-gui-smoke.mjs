// 表格设计 ▸ 表格样式库 / 内置样式 / 表格样式选项：真实浏览器 + 真实 inspect_docx/patch_docx 冒烟。
// HTTP 路由只替代授权与修订登记；所有修改均通过可见 Ribbon 按钮与样式库对话框完成。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url)), port = 4197, base = `http://127.0.0.1:${port}`
const out = process.env.SMOKE_OUT_DIR ?? '/tmp'
const mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from lxml import etree
from docx import Document
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';NS={'w':W}
p=json.load(sys.stdin)
if p['mode']=='create':
 d=Document();d.add_paragraph('表格样式冒烟')
 t=d.add_table(rows=4,cols=3);t.style='Table Grid'
 for r,row in enumerate(t.rows):
  for c,cell in enumerate(row.cells):cell.text=['项目','金额','备注'][c] if r==0 else f'R{r}C{c}'
 d.add_paragraph('Untouched after')
 o=BytesIO();d.save(o);print(base64.b64encode(o.getvalue()).decode())
elif p['mode']=='inspect':print(json.dumps(inspect_docx(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':print(base64.b64encode(patch_docx(base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);a=ZipFile(BytesIO(base64.b64decode(p['before'])));b=ZipFile(BytesIO(raw))
 changed=sorted(n for n in a.namelist() if a.read(n)!=b.read(n))
 tbl=etree.fromstring(b.read('word/document.xml')).xpath('//w:tbl',namespaces=NS)[0]
 look=tbl.xpath('./w:tblPr/w:tblLook',namespaces=NS)
 doc=Document(BytesIO(raw))
 print(json.dumps({'changedParts':changed,'tblStyle':tbl.xpath('./w:tblPr/w:tblStyle/@w:val',namespaces=NS),
  'tblLook':{k:look[0].get('{%s}%s'%(W,k)) for k in ('firstRow','lastRow','firstColumn','lastColumn','noHBand','noVBand')} if look else None,
  'fills':[[(c.xpath('./w:tcPr/w:shd/@w:fill',namespaces=NS) or [None])[0] for c in r.xpath('./w:tc',namespaces=NS)] for r in tbl.xpath('./w:tr',namespaces=NS)],
  'borderColors':sorted(set(tbl.xpath('./w:tr/w:tc/w:tcPr/w:tcBorders/*/@w:color',namespaces=NS))),
  'pythonDocxStyle':doc.tables[0].style.style_id if doc.tables[0].style is not None else None,
  'pythonDocxText':[[c.text for c in r.cells] for r in doc.tables[0].rows]}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status) throw Error(result.stderr || result.stdout)
  return result.stdout.trim()
}
const revisions = new Map([[1, Buffer.from(python({ mode: 'create' }), 'base64')]]), models = new Map([[1, JSON.parse(python({ mode: 'inspect', bytes: revisions.get(1).toString('base64') }))]])
const payloads = new Map(), errors = []
let browser, page
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let i = 0; i < 160; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE || undefined, args: ['--disable-features=LocalNetworkAccessChecks'] })
  page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
  page.on('pageerror', error => errors.push(error.message))
  const revision = route => Number(route.request().url().match(/table-style\/(\d+)/)[1])
  await page.route('**/reports/v1/native/table-style/*/api/context', route => { const n = revision(route), bytes = revisions.get(n); return route.fulfill({ json: { context: { documentId: 'table-style', format: 'docx', revision: n, parentRevision: n === 1 ? null : n - 1, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'source.docx', size: bytes.length, sha256: sha(bytes), mediaType: mime }, origin: 'upload' }, editingEnabled: true, csrfToken: 'fixture', capabilities: { docx_editor: true } } }) })
  await page.route('**/reports/v1/native/table-style/*/api/file', route => route.fulfill({ body: revisions.get(revision(route)), contentType: mime }))
  await page.route('**/reports/v1/native/table-style/*/api/preview', route => { assert.deepEqual(route.request().postDataJSON().operations, []); const model = models.get(revision(route)); return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } }) })
  await page.route('**/reports/v1/native/table-style/*/api/save', route => {
    const n = revision(route), payload = route.request().postDataJSON(), source = revisions.get(n)
    assert.equal(payload.expectedSha256, sha(source)); payloads.set(n, payload)
    const saved = Buffer.from(python({ mode: 'patch', bytes: source.toString('base64'), operations: payload.operations }), 'base64')
    revisions.set(n + 1, saved); models.set(n + 1, JSON.parse(python({ mode: 'inspect', bytes: saved.toString('base64') })))
    return route.fulfill({ json: { documentId: 'table-style', revision: n + 1, parentRevision: n, revisionRegistered: true, validation: { ok: false, issues: [{ code: 'fixture_review', message: 'GUI fixture soft warning' }] }, artifacts: { word: { downloadUrl: `/table-style-${n + 1}.docx`, sha256: sha(saved), size: saved.length } }, editor: { openUrl: `/reports/v1/native/table-style/${n + 1}` } } })
  })
  await page.route(/\/reports\/v1\/native\/table-style\/\d+$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const editorBox = () => page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const table = () => editorBox().locator('table').first()
  const ready = async () => { await page.locator('.docx-source-home').waitFor({ timeout: 60000 }); await table().waitFor() }
  const open = async n => { await page.goto(`${base}/reports/v1/native/table-style/${n}`); await ready() }
  const caret = async () => { await table().getByText('R1C1', { exact: true }).click(); await page.locator('[data-tab-id="tableDesign"]').click() }
  const button = action => page.locator(`[data-action="${action}"]`)
  const press = async action => { const control = button(action); assert(await control.isEnabled(), `${action}: ${await control.getAttribute('title')}`); await control.click(); await delay(150) }
  const tableAttrs = () => table().evaluate(node => ({ style: node.getAttribute('data-tbl-style'), noHBand: node.hasAttribute('data-tbl-nohband'), noFirstRow: node.hasAttribute('data-tbl-nofirstrow') }))
  const colors = () => table().locator('td,th').evaluateAll(nodes => nodes.map(node => getComputedStyle(node).backgroundColor))
  const save = async n => { await page.locator('[data-action="save"]').click(); await page.getByRole('link', { name: '下载 Word', exact: true }).waitFor({ timeout: 60000 }); assert(revisions.has(n + 1)) }

  // 第 1 轮：样式库选择文档样式 + 关闭镶边行、打开末行；草稿恢复后保存
  await open(1); await caret()
  assert.deepEqual(await tableAttrs(), { style: 'TableGrid', noHBand: false, noFirstRow: false })
  assert.equal(await button('table-look-first-row').getAttribute('aria-pressed'), 'true')
  await press('table-style-custom')
  const gallery = page.locator('select[aria-label="文档表格样式"]')
  const choices = await gallery.locator('option').evaluateAll(nodes => nodes.map(node => node.value))
  assert(choices.includes('TableGrid') && choices.includes('LightGrid-Accent1'), JSON.stringify(choices))
  await gallery.selectOption('LightGrid-Accent1'); await page.getByRole('button', { name: '应用', exact: true }).click(); await delay(150)
  await press('table-look-banded-rows'); await press('table-look-last-row')
  assert.deepEqual(await tableAttrs(), { style: 'LightGrid-Accent1', noHBand: true, noFirstRow: false })
  assert.equal(await button('table-look-banded-rows').getAttribute('aria-pressed'), 'false')
  assert.equal(await button('table-look-last-row').getAttribute('aria-pressed'), 'true')
  await page.screenshot({ path: `${out}/docx-table-style-gallery.png` })
  await page.reload(); await ready()
  assert.deepEqual(await tableAttrs(), { style: 'LightGrid-Accent1', noHBand: true, noFirstRow: false })
  await save(1)
  { const ops = payloads.get(1).operations; assert.equal(ops.length, 1); assert.equal(ops[0].kind, 'setTableStyle'); assert.equal(ops[0].styleId, 'LightGrid-Accent1'); assert.deepEqual(ops[0].look, { firstRow: true, lastRow: true, firstColumn: true, lastColumn: false, bandedRows: false, bandedColumns: false }); assert.equal(ops[0].preset, undefined) }
  const readback2 = JSON.parse(python({ mode: 'verify', before: revisions.get(1).toString('base64'), bytes: revisions.get(2).toString('base64') }))
  console.log(JSON.stringify({ phase: 'gallery+look saved', operations: payloads.get(1).operations, readback: readback2 }))

  // 第 2 轮：重开修订 2，内置“蓝色带状”预设
  await open(2); await caret()
  assert.deepEqual(await tableAttrs(), { style: 'LightGrid-Accent1', noHBand: true, noFirstRow: false })
  await press('table-style-blue-banded')
  assert.equal(await button('table-style-blue-banded').getAttribute('aria-pressed'), 'true')
  const previewColors = await colors()
  assert.deepEqual(previewColors.slice(0, 3), Array(3).fill('rgb(189, 215, 238)'))
  assert.deepEqual(previewColors.slice(3, 6), Array(3).fill('rgb(221, 235, 247)'))
  await page.screenshot({ path: `${out}/docx-table-style-preset.png` })
  await save(2)
  const readback3 = JSON.parse(python({ mode: 'verify', before: revisions.get(2).toString('base64'), bytes: revisions.get(3).toString('base64') }))
  await open(3)
  assert.deepEqual((await colors()).slice(0, 6), previewColors.slice(0, 6))
  await page.screenshot({ path: `${out}/docx-table-style-reopened.png` })
  writeFileSync(`${out}/docx-table-style-rev3.docx`, revisions.get(3))
  writeFileSync(`${out}/docx-table-style-rev2.docx`, revisions.get(2))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, browser: browser.version(), operations: { 1: payloads.get(1).operations, 2: payloads.get(2).operations }, readback2, readback3, pageErrors: errors, provenance: 'HTTP routes substitute authorization/revisions; preview uses real inspect_docx and save uses real patch_docx; all edits use visible ribbon buttons and gallery dialog.' }))
} catch (error) { await page?.screenshot({ path: `${out}/docx-table-style-failed.png` }).catch(() => {}); console.error(JSON.stringify({ failed: true, message: String(error), pageErrors: errors })); throw error } finally { await browser?.close(); server.kill() }
