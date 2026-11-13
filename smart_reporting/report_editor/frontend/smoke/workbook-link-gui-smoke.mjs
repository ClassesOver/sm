// XLSX 插入 ▸ 链接（固定源 ExcelShell LinkDialog → set_hyperlink → xlsx-gateway xlsx-hyperlinks.ts）：真实 Ribbon 与对话框、
// 浏览器内引擎重放、文件 ▸ 撤销/重做、刷新恢复草稿、Python 真实保存、授权下载与 openpyxl/ZIP 独立回读、修订 2 重开。
// 授权/修订路由为显式 fixture。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd(), repo = new URL('../../../', `file://${frontend}/`).pathname
const port = Number(process.env.WORKBOOK_SMOKE_PORT ?? 4211), preview = process.env.WORKBOOK_SMOKE_PREVIEW === '1'
const base = `http://127.0.0.1:${port}`, media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const sha = data => createHash('sha256').update(data).digest('hex')
function py(payload) {
  const result = spawnSync(process.env.SMOKE_PYTHON ?? `${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Data'
 s['A1']='官网';s['B1']='跳转汇总';s['C1']='旧链接';s['C1'].hyperlink='https://old.example/'
 s['A2']=42
 t=b.create_sheet('汇总 表');t['A1']='目标'
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));s=b['Data']
 link=lambda ref:None if s[ref].hyperlink is None else {'target':s[ref].hyperlink.target,'location':s[ref].hyperlink.location}
 with ZipFile(BytesIO(data)) as z,ZipFile(BytesIO(base64.b64decode(p['source']))) as original:
  changed=sorted(name for name in z.namelist() if name not in original.namelist() or z.read(name)!=original.read(name))
 print(json.dumps({'A1':link('A1'),'B1':link('B1'),'C1':link('C1'),'values':[s[r].value for r in ('A1','B1','C1','A2')],
  'A1font':{'color':s['A1'].font.color.rgb if s['A1'].font.color else None,'underline':s['A1'].font.underline},
  'C1font':{'underline':s['C1'].font.underline},'other':b['汇总 表']['A1'].value,'changed':changed}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 50 * 1024 * 1024 })
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}
const bytes = Buffer.from(py({ mode: 'create' }), 'base64')
let saved, payload, browser
const ctx = (data, revision) => ({ documentId: 'link', format: 'xlsx', revision, parentRevision: revision === 1 ? null : 1, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
  sourceFile: { path: 'link.xlsx', size: data.length, sha256: sha(data), mediaType: media }, origin: 'upload' })
const server = spawn('./node_modules/.bin/vite', [...(preview ? ['preview'] : []), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } }), errors = []
  page.on('pageerror', error => errors.push(error.message))
  for (const rev of [1, 2]) {
    await page.route(`**/reports/v1/native/link/${rev}/api/context`, route => route.fulfill({ json: { context: ctx(rev === 1 ? bytes : saved, rev), csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route(`**/reports/v1/native/link/${rev}/api/file`, route => route.fulfill({ body: rev === 1 ? bytes : saved, contentType: media }))
  }
  await page.route('**/reports/v1/native/link/1/api/save', async route => {
    payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, sha(bytes))
    saved = Buffer.from(py({ mode: 'patch', bytes: bytes.toString('base64'), operations: payload.operations }), 'base64')
    await route.fulfill({ json: { documentId: 'link', revision: 2, parentRevision: 1, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/link-download.xlsx', size: saved.length, sha256: sha(saved) } }, editor: { openUrl: '/reports/v1/native/link/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/link-download.xlsx', route => route.fulfill({ body: saved, contentType: media }))
  await page.route(/\/reports\/v1\/native\/link\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 90000 })
  const settled = () => page.waitForFunction(() => !document.querySelector('#report-editor')?.inert, null, { timeout: 90000 })
  const draft = () => page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).flatMap(key => JSON.parse(localStorage.getItem(key)).operations ?? []))
  const linkOps = async () => (await draft()).filter(op => op.kind === 'applySheetHyperlinks').map(op => op.edits.map(edit => [edit.ref, edit.expectedTarget, edit.target]))
  const go = async ref => { const box = page.locator('[data-u-comp="defined-name"] input'); await box.fill(ref); await box.press('Enter'); await delay(150) }
  const feedback = () => page.locator('.workbook-feedback').textContent()
  const dialog = page.locator('.workbook-link-dialog'), address = dialog.locator('[data-link-address]'), ok = dialog.locator('[data-link-ok]')
  const linkButton = page.locator('[data-ribbon-command="link-open"]')
  const openLink = async ref => { await go(ref); await page.locator('[data-ribbon-tab="Insert"]').click(); await linkButton.click(); await dialog.waitFor({ state: 'visible' }) }
  await page.goto(`${base}/reports/v1/native/link/1`); await ready()

  // 插入 ▸ 链接：A1 外部网址（裸域名补 https://），对话框标题为“插入链接”
  await page.locator('[data-ribbon-tab="Insert"]').click()
  assert.equal(await linkButton.isEnabled(), true)
  assert.equal(await linkButton.getAttribute('data-unavailable-reason'), null)
  await openLink('A1')
  assert.equal(await dialog.locator('[data-link-title]').textContent(), '插入链接')
  assert.equal(await dialog.locator('[data-link-remove]').isHidden(), true)
  assert.equal(await ok.isDisabled(), true)
  await address.fill('javascript:alert(1)'); await ok.click()
  assert.match(await dialog.locator('[role="alert"]').textContent(), /请输入网址/)
  await address.fill('example.com/report?a=1&b=2'); await address.press('Enter'); await dialog.waitFor({ state: 'hidden' }); await settled()
  await page.waitForFunction(() => document.querySelector('.workbook-feedback')?.textContent?.includes('链接已保存'), null, { timeout: 60000 })
  // B1 文档内链接（带空格的工作表名）
  await openLink('B1')
  await address.fill("'汇总 表'!A1"); await ok.click(); await dialog.waitFor({ state: 'hidden' }); await settled()
  // C1 已有链接：编辑对话框显示来源地址并可删除
  await openLink('C1')
  assert.equal(await dialog.locator('[data-link-title]').textContent(), '编辑链接')
  assert.equal(await address.inputValue(), 'https://old.example/')
  await dialog.locator('[data-link-remove]').click(); await dialog.waitFor({ state: 'hidden' }); await settled()
  await page.waitForFunction(() => document.querySelector('.workbook-feedback')?.textContent?.includes('链接已删除'), null, { timeout: 60000 })
  assert.deepEqual(await linkOps(), [[['A1', null, 'https://example.com/report?a=1&b=2']], [['B1', null, "#'汇总 表'!A1"]], [['C1', 'https://old.example/', null]]])
  // 再次打开 A1：读取草稿重放后的链接
  await openLink('A1')
  assert.equal(await dialog.locator('[data-link-title]').textContent(), '编辑链接')
  assert.equal(await address.inputValue(), 'https://example.com/report?a=1&b=2')
  await dialog.locator('[data-link-cancel]').click(); await dialog.waitFor({ state: 'hidden' })
  // 文件 ▸ 撤销 / 重做
  // 链接与其蓝色下划线样式是同一历史步骤
  await page.locator('[data-ribbon-tab="File"]').click()
  await page.locator('[data-ribbon-command="undo"]').click(); await settled()
  assert.deepEqual(await linkOps(), [[['A1', null, 'https://example.com/report?a=1&b=2']], [['B1', null, "#'汇总 表'!A1"]]])
  await page.locator('[data-ribbon-command="redo"]').click(); await settled()
  assert.deepEqual((await linkOps()).length, 3)
  if (process.env.WORKBOOK_SMOKE_SCREENSHOT) await page.screenshot({ path: process.env.WORKBOOK_SMOKE_SCREENSHOT })
  // 刷新后草稿恢复，再保存
  await page.reload(); await ready()
  assert.deepEqual((await linkOps()).length, 3)
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent?.includes('已保存'), null, { timeout: 90000 })
  assert.ok(payload, 'save request issued')
  assert.deepEqual(payload.operations.filter(op => op.kind === 'applySheetHyperlinks').map(op => op.edits[0].ref), ['A1', 'B1', 'C1'])
  await page.waitForFunction(() => { const link = document.querySelector('[data-action="xlsx-download"]'); return link && !link.hidden && link.getAttribute('href') }, null, { timeout: 30000 })
  const href = await page.locator('[data-action="xlsx-download"]').getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], href))
  assert.deepEqual(downloaded, saved)
  if (process.env.WORKBOOK_SMOKE_OUTPUT) await writeFile(process.env.WORKBOOK_SMOKE_OUTPUT, downloaded)
  const file = JSON.parse(py({ mode: 'inspect', bytes: downloaded.toString('base64'), source: bytes.toString('base64') }))
  assert.deepEqual(file.A1, { target: 'https://example.com/report?a=1&b=2', location: null })
  assert.deepEqual(file.B1, { target: null, location: "'汇总 表'!A1" })
  assert.equal(file.C1, null)
  assert.deepEqual(file.values, ['官网', '跳转汇总', '旧链接', 42])
  assert.equal(file.other, '目标')
  assert.equal(file.A1font.color, 'FF0563C1'); assert.equal(file.A1font.underline, 'single')
  assert.equal(file.C1font.underline, null, '删除链接后清除下划线')
  assert.ok(file.changed.every(name => ['xl/worksheets/sheet1.xml', 'xl/worksheets/_rels/sheet1.xml.rels', 'xl/styles.xml'].includes(name)), JSON.stringify(file.changed))
  // 修订 2 重开：A1 链接从文件读取
  await page.goto(`${base}/reports/v1/native/link/2`); await ready()
  await openLink('A1')
  assert.equal(await address.inputValue(), 'https://example.com/report?a=1&b=2')
  await dialog.locator('[data-link-cancel]').click()
  if (process.env.WORKBOOK_SMOKE_SCREENSHOT) await page.screenshot({ path: process.env.WORKBOOK_SMOKE_SCREENSHOT.replace(/\.png$/, '-revision-2.png') })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, preview, operations: payload.operations.map(item => item.kind), file, downloadedSha256: sha(downloaded) }))
} finally { await browser?.close(); server.kill() }
