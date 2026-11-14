// XLSX 视图 ▸ 拆分窗口：文件中的拆分窗格（twips）不得被当作冻结行列加载；功能区“拆分窗口”只用于取消已有拆分窗格。
// 真实 Ribbon、浏览器内引擎重放、文件 ▸ 撤销/重做、刷新恢复草稿、Python 真实保存、授权下载与 openpyxl/ZIP 独立回读、修订 2 重开。
// 授权/修订路由为显式 fixture；开发服务器模式下暴露 Univer 运行时只用于读取冻结状态。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd(), repo = new URL('../../../', `file://${frontend}/`).pathname
const port = Number(process.env.WORKBOOK_SMOKE_PORT ?? 4213)
const base = `http://127.0.0.1:${port}`, media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const sha = data => createHash('sha256').update(data).digest('hex')
function py(payload) {
  const result = spawnSync(process.env.SMOKE_PYTHON ?? `${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from openpyxl.worksheet.views import Pane,Selection
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Data'
 s['A1']='标题';s['B2']=42;s.sheet_view.zoomScale=120
 s.sheet_view.pane=Pane(xSplit=2400,ySplit=1200,topLeftCell='C5',activePane='bottomRight',state='split')
 s.sheet_view.selection=[Selection(pane='bottomRight',activeCell='C5',sqref='C5')]
 t=b.create_sheet('冻结');t['A1']='保持不变';t.freeze_panes='B3'
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));s=b['Data'];t=b['冻结']
 with ZipFile(BytesIO(data)) as z,ZipFile(BytesIO(base64.b64decode(p['source']))) as original:
  changed=sorted(name for name in z.namelist() if name not in original.namelist() or z.read(name)!=original.read(name))
 print(json.dumps({'pane':None if s.sheet_view.pane is None else s.sheet_view.pane.state,'zoom':s.sheet_view.zoomScale,
  'values':[s['A1'].value,s['B2'].value],'frozen':[t.freeze_panes,t['A1'].value],'changed':changed}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 50 * 1024 * 1024 })
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}
const bytes = Buffer.from(py({ mode: 'create' }), 'base64')
let saved, payload, browser
const ctx = (data, revision) => ({ documentId: 'split', format: 'xlsx', revision, parentRevision: revision === 1 ? null : 1, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
  sourceFile: { path: 'split.xlsx', size: data.length, sha256: sha(data), mediaType: media }, origin: 'upload' })
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } }), errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/src/workbook-vendor/grid/create-univer.ts*', async route => {
    const response = await route.fetch(), body = await response.text(), marker = 'return { univer, univerAPI: FUniver.newAPI(univer) };'
    assert.ok(body.includes(marker))
    await route.fulfill({ response, body: body.replace(marker, 'return window.__splitRuntime = { univer, univerAPI: FUniver.newAPI(univer) };') })
  })
  for (const rev of [1, 2]) {
    await page.route(`**/reports/v1/native/split/${rev}/api/context`, route => route.fulfill({ json: { context: ctx(rev === 1 ? bytes : saved, rev), csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route(`**/reports/v1/native/split/${rev}/api/file`, route => route.fulfill({ body: rev === 1 ? bytes : saved, contentType: media }))
  }
  await page.route('**/reports/v1/native/split/1/api/save', async route => {
    payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, sha(bytes))
    saved = Buffer.from(py({ mode: 'patch', bytes: bytes.toString('base64'), operations: payload.operations }), 'base64')
    await route.fulfill({ json: { documentId: 'split', revision: 2, parentRevision: 1, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/split-download.xlsx', size: saved.length, sha256: sha(saved) } }, editor: { openUrl: '/reports/v1/native/split/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/split-download.xlsx', route => route.fulfill({ body: saved, contentType: media }))
  await page.route(/\/reports\/v1\/native\/split\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 90000 })
  const settled = () => page.waitForFunction(() => !document.querySelector('#report-editor')?.inert, null, { timeout: 90000 })
  const draft = () => page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).flatMap(key => JSON.parse(localStorage.getItem(key)).operations ?? []))
  const splitOps = async () => (await draft()).filter(op => op.kind === 'removeSheetSplitPane').map(op => [op.sheetName, op.expected])
  const freeze = name => page.evaluate(name => { const sheet = window.__splitRuntime.univerAPI.getActiveWorkbook().getSheetByName(name); const value = sheet.getFreeze(); return [value.xSplit, value.ySplit] }, name)
  const button = page.locator('[data-ribbon-command="split-window"]')
  const view = () => page.locator('[data-ribbon-tab="View"]').click()
  const expected = { xSplitTwips: 2400, ySplitTwips: 1200, topLeftCell: 'C5' }
  await page.goto(`${base}/reports/v1/native/split/1`); await ready()

  // 拆分窗格不再被当作 2400 列 × 1200 行冻结；同一工作簿中的真实冻结窗格保持行列数。
  assert.deepEqual(await freeze('Data'), [0, 0])
  assert.deepEqual(await freeze('冻结'), [1, 2])
  await view()
  assert.equal(await button.isEnabled(), true)
  assert.equal(await button.getAttribute('aria-pressed'), 'true')
  assert.equal(await button.getAttribute('title'), '取消文件中的拆分窗格')
  if (process.env.WORKBOOK_SMOKE_SCREENSHOT) await page.screenshot({ path: process.env.WORKBOOK_SMOKE_SCREENSHOT })
  await button.click(); await settled()
  await page.waitForFunction(() => document.querySelector('.workbook-feedback')?.textContent?.includes('已取消工作表“Data”的拆分窗格'), null, { timeout: 60000 })
  assert.deepEqual(await splitOps(), [['Data', expected]])
  await view()
  assert.equal(await button.isDisabled(), true)
  assert.equal(await button.getAttribute('aria-pressed'), 'false')
  assert.match(await button.getAttribute('title'), /固定源未提供拆分窗口/)
  // 文件 ▸ 撤销 / 重做
  await page.locator('[data-ribbon-tab="File"]').click()
  await page.locator('[data-ribbon-command="undo"]').click(); await settled()
  assert.deepEqual(await splitOps(), [])
  await view(); assert.equal(await button.isEnabled(), true)
  await page.locator('[data-ribbon-tab="File"]').click()
  await page.locator('[data-ribbon-command="redo"]').click(); await settled()
  assert.deepEqual(await splitOps(), [['Data', expected]])
  // 刷新后草稿恢复，再保存
  await page.reload(); await ready()
  assert.deepEqual(await splitOps(), [['Data', expected]])
  await view(); assert.equal(await button.isDisabled(), true)
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent?.includes('已保存'), null, { timeout: 90000 })
  assert.ok(payload, 'save request issued')
  assert.deepEqual(payload.operations.map(op => op.kind), ['removeSheetSplitPane'])
  await page.waitForFunction(() => { const link = document.querySelector('[data-action="xlsx-download"]'); return link && !link.hidden && link.getAttribute('href') }, null, { timeout: 30000 })
  const href = await page.locator('[data-action="xlsx-download"]').getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], href))
  assert.deepEqual(downloaded, saved)
  if (process.env.WORKBOOK_SMOKE_OUTPUT) await writeFile(process.env.WORKBOOK_SMOKE_OUTPUT, downloaded)
  const file = JSON.parse(py({ mode: 'inspect', bytes: downloaded.toString('base64'), source: bytes.toString('base64') }))
  assert.equal(file.pane, null)
  assert.equal(file.zoom, 120)
  assert.deepEqual(file.values, ['标题', 42])
  assert.deepEqual(file.frozen, ['B3', '保持不变'])
  assert.deepEqual(file.changed, ['xl/worksheets/sheet1.xml'])
  // 修订 2 重开：没有拆分窗格，按钮禁用并说明原因
  await page.goto(`${base}/reports/v1/native/split/2`); await ready()
  assert.deepEqual(await freeze('Data'), [0, 0])
  await view(); assert.equal(await button.isDisabled(), true)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, operations: payload.operations, file, downloadedSha256: sha(downloaded) }))
} finally { await browser?.close(); server.kill() }
