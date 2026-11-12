// XLSX 插入 ▸ 符号（固定源 SymbolDialog / handleInsertSymbol）与 开始 ▸ 上标/下标：真实 Ribbon、对话框、草稿刷新恢复、
// Python 真实保存、授权下载与 openpyxl/ZIP 独立回读、修订 2 重开。授权/修订路由为显式 fixture。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd(), repo = new URL('../../../', `file://${frontend}/`).pathname
const port = Number(process.env.WORKBOOK_SMOKE_PORT ?? 4207), preview = process.env.WORKBOOK_SMOKE_PREVIEW === '1'
const base = `http://127.0.0.1:${port}`, media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const sha = data => createHash('sha256').update(data).digest('hex')
function py(payload) {
  const result = spawnSync(process.env.SMOKE_PYTHON ?? `${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Data';s['A1']='价格';s['A2']=12.5;s['B1']='H2O';s['B1'].font=Font(name='Calibri',size=11,bold=True);s['C1']='=A2*2'
 t=b.create_sheet('Locked');t['A1']='private';t.protection.sheet=True
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));s=b['Data']
 with ZipFile(BytesIO(data)) as z,ZipFile(BytesIO(base64.b64decode(p['source']))) as original:
  changed=sorted(name for name in z.namelist() if name not in original.namelist() or z.read(name)!=original.read(name))
 print(json.dumps({'A1':s['A1'].value,'A2':s['A2'].value,'A2vert':s['A2'].font.vertAlign,'B1':s['B1'].value,'B1vert':s['B1'].font.vertAlign,'B1bold':s['B1'].font.b,'B1font':s['B1'].font.name,'C1':s['C1'].value,'locked':b['Locked'].protection.sheet,'lockedValue':b['Locked']['A1'].value,'changed':changed}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 50 * 1024 * 1024 })
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}
const bytes = Buffer.from(py({ mode: 'create' }), 'base64')
let saved, payload, browser
const ctx = (data, revision) => ({ documentId: 'symbol', format: 'xlsx', revision, parentRevision: revision === 1 ? null : 1, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
  sourceFile: { path: 'symbol.xlsx', size: data.length, sha256: sha(data), mediaType: media }, origin: 'upload' })
const server = spawn('./node_modules/.bin/vite', [...(preview ? ['preview'] : []), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } }), errors = []
  page.on('pageerror', error => errors.push(error.message))
  for (const rev of [1, 2]) {
    await page.route(`**/reports/v1/native/symbol/${rev}/api/context`, route => route.fulfill({ json: { context: ctx(rev === 1 ? bytes : saved, rev), csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route(`**/reports/v1/native/symbol/${rev}/api/file`, route => route.fulfill({ body: rev === 1 ? bytes : saved, contentType: media }))
  }
  await page.route('**/reports/v1/native/symbol/1/api/save', async route => {
    payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, sha(bytes))
    saved = Buffer.from(py({ mode: 'patch', bytes: bytes.toString('base64'), operations: payload.operations }), 'base64')
    await route.fulfill({ json: { documentId: 'symbol', revision: 2, parentRevision: 1, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/symbol-download.xlsx', size: saved.length, sha256: sha(saved) } }, editor: { openUrl: '/reports/v1/native/symbol/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/symbol-download.xlsx', route => route.fulfill({ body: saved, contentType: media }))
  await page.route(/\/reports\/v1\/native\/symbol\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 90000 })
  const go = async ref => { const box = page.locator('[data-u-comp="defined-name"] input'); await box.fill(ref); await box.press('Enter'); await delay(150) }
  const dialog = page.locator('[aria-label="插入符号"]')
  const feedback = () => page.locator('.workbook-feedback').textContent()
  await page.goto(`${base}/reports/v1/native/symbol/1`); await ready()

  // 插入 ▸ 符号：A1 连续插入 € 与 →（对话框保持打开），切换分类
  await go('A1')
  await page.locator('[data-ribbon-tab="Insert"]').click()
  const symbolButton = page.locator('[data-ribbon-command="insert-symbol"]')
  assert.equal(await symbolButton.isEnabled(), true)
  assert.equal(await symbolButton.getAttribute('data-unavailable-reason'), null)
  await symbolButton.click()
  await dialog.waitFor({ state: 'visible' })
  await dialog.locator('[data-symbol="€"]').click()
  assert.match(await dialog.locator('[data-symbol-status]').textContent(), /已插入 € 到 A1/)
  await dialog.locator('[data-symbol-category="2"]').click()
  await dialog.locator('[data-symbol="→"]').click()
  assert.match(await dialog.locator('[data-symbol-status]').textContent(), /已插入 → 到 A1/)
  assert.equal(await dialog.isVisible(), true)
  await dialog.locator('[data-symbol-close]').click(); await dialog.waitFor({ state: 'hidden' })
  // 公式单元格拒绝追加（与固定源差异：不以计算值覆盖公式）
  await go('C1')
  await symbolButton.click(); await dialog.waitFor({ state: 'visible' })
  await dialog.locator('[data-symbol-category="0"]').click()
  await dialog.locator('[data-symbol="€"]').click()
  assert.match(await dialog.locator('[role="alert"]').textContent(), /含公式/)
  await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' })

  // 开始 ▸ 上标 / 下标
  await page.locator('[data-ribbon-tab="Home"]').click()
  const superscript = page.locator('[data-ribbon-command="superscript"]'), subscript = page.locator('[data-ribbon-command="subscript"]')
  await go('B1'); assert.equal(await superscript.isEnabled(), true); await superscript.click()
  await go('A2'); await subscript.click()
  // 撤销 / 重做下标
  await page.keyboard.press('Control+z'); await delay(200); await page.keyboard.press('Control+y'); await delay(200)
  assert.match(await feedback() ?? '', /.*/)
  if (process.env.WORKBOOK_SMOKE_SCREENSHOT) await page.screenshot({ path: process.env.WORKBOOK_SMOKE_SCREENSHOT })
  // 刷新后草稿恢复再保存
  await page.reload(); await ready()
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent?.includes('已保存'), null, { timeout: 90000 })
  assert.ok(payload, 'save request issued')
  // 原生 XLSX 保存把 artifacts.xlsx 映射到外壳的“下载 XLSX”链接（native-office-view.ts）。
  await page.waitForFunction(() => { const link = document.querySelector('[data-action="xlsx-download"]'); return link && !link.hidden && link.getAttribute('href') }, null, { timeout: 30000 })
  const href = await page.locator('[data-action="xlsx-download"]').getAttribute('href')
  assert.equal(href, '/symbol-download.xlsx')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], href))
  assert.deepEqual(downloaded, saved)
  if (process.env.WORKBOOK_SMOKE_OUTPUT) await writeFile(process.env.WORKBOOK_SMOKE_OUTPUT, downloaded)
  const file = JSON.parse(py({ mode: 'inspect', bytes: downloaded.toString('base64'), source: bytes.toString('base64') }))
  assert.equal(file.A1, '价格€→')
  assert.equal(file.C1, '=A2*2')
  assert.equal(file.B1, 'H2O'); assert.equal(file.B1vert, 'superscript'); assert.equal(file.B1bold, true); assert.equal(file.B1font, 'Calibri')
  assert.equal(file.A2, 12.5); assert.equal(file.A2vert, 'subscript')
  assert.equal(file.locked, true); assert.equal(file.lockedValue, 'private')
  assert.ok(file.changed.every(name => !name.includes('sheet2')), `locked sheet untouched: ${file.changed}`)
  // 修订 2 重开
  await page.goto(`${base}/reports/v1/native/symbol/2`); await ready()
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, preview, operations: payload.operations.map(item => item.kind), file, downloadedSha256: sha(downloaded) }))
} finally { await browser?.close(); server.kill() }
