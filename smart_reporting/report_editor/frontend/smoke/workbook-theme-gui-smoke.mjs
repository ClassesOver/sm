// XLSX 页面布局 ▸ 主题 / 颜色 / 字体（固定源 page-layout-actions theme / theme-colors / theme-fonts）：真实 Ribbon 菜单、
// 浏览器内引擎重放预览、文件 ▸ 撤销/重做、刷新恢复草稿、Python 真实保存、授权下载与 openpyxl/ZIP 独立回读、修订 2 重开。
// 授权/修订路由为显式 fixture。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd(), repo = new URL('../../../', `file://${frontend}/`).pathname
const port = Number(process.env.WORKBOOK_SMOKE_PORT ?? 4209), preview = process.env.WORKBOOK_SMOKE_PREVIEW === '1'
const base = `http://127.0.0.1:${port}`, media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const sha = data => createHash('sha256').update(data).digest('hex')
function py(payload) {
  const result = spawnSync(process.env.SMOKE_PYTHON ?? `${repo}/.venv/bin/python`, ['-c', `
import base64,json,re,sys
from io import BytesIO
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill
from openpyxl.styles.colors import Color
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Data'
 s['A1']='主题强调色';s['A1'].font=Font(color=Color(theme=4),scheme='minor',bold=True);s['A1'].fill=PatternFill('solid',fgColor=Color(theme=5))
 s['B1']='显式 RGB';s['B1'].font=Font(color='FF123456')
 s['A2']=42
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes']);b=load_workbook(BytesIO(data));s=b['Data']
 with ZipFile(BytesIO(data)) as z,ZipFile(BytesIO(base64.b64decode(p['source']))) as original:
  changed=sorted(name for name in z.namelist() if name not in original.namelist() or z.read(name)!=original.read(name))
  theme=z.read('xl/theme/theme1.xml').decode()
 accents=[re.search(r'<a:accent%d><a:srgbClr val="([0-9A-F]{6})"/>'%i,theme) for i in (1,2)]
 print(json.dumps({'clrScheme':re.search(r'<a:clrScheme name="([^"]*)"',theme).group(1),'fontScheme':re.search(r'<a:fontScheme name="([^"]*)"',theme).group(1),
  'major':re.search(r'<a:majorFont>.*?<a:latin typeface="([^"]*)"',theme,re.S).group(1),'minor':re.search(r'<a:minorFont>.*?<a:latin typeface="([^"]*)"',theme,re.S).group(1),
  'accent1':accents[0].group(1) if accents[0] else None,'accent2':accents[1].group(1) if accents[1] else None,
  'A1theme':s['A1'].font.color.theme,'A1fill':s['A1'].fill.fgColor.theme,'A1scheme':s['A1'].font.scheme,'B1rgb':s['B1'].font.color.rgb,'A2':s['A2'].value,'changed':changed}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 50 * 1024 * 1024 })
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}
const bytes = Buffer.from(py({ mode: 'create' }), 'base64')
let saved, payload, browser
const ctx = (data, revision) => ({ documentId: 'theme', format: 'xlsx', revision, parentRevision: revision === 1 ? null : 1, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
  sourceFile: { path: 'theme.xlsx', size: data.length, sha256: sha(data), mediaType: media }, origin: 'upload' })
const server = spawn('./node_modules/.bin/vite', [...(preview ? ['preview'] : []), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } }), errors = []
  page.on('pageerror', error => errors.push(error.message))
  for (const rev of [1, 2]) {
    await page.route(`**/reports/v1/native/theme/${rev}/api/context`, route => route.fulfill({ json: { context: ctx(rev === 1 ? bytes : saved, rev), csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route(`**/reports/v1/native/theme/${rev}/api/file`, route => route.fulfill({ body: rev === 1 ? bytes : saved, contentType: media }))
  }
  await page.route('**/reports/v1/native/theme/1/api/save', async route => {
    payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, sha(bytes))
    saved = Buffer.from(py({ mode: 'patch', bytes: bytes.toString('base64'), operations: payload.operations }), 'base64')
    await route.fulfill({ json: { documentId: 'theme', revision: 2, parentRevision: 1, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/theme-download.xlsx', size: saved.length, sha256: sha(saved) } }, editor: { openUrl: '/reports/v1/native/theme/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/theme-download.xlsx', route => route.fulfill({ body: saved, contentType: media }))
  await page.route(/\/reports\/v1\/native\/theme\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 90000 })
  const settled = () => page.waitForFunction(() => !document.querySelector('#report-editor')?.inert, null, { timeout: 90000 })
  const draft = () => page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).flatMap(key => JSON.parse(localStorage.getItem(key)).operations ?? []))
  const themeOps = async () => (await draft()).filter(op => op.kind === 'setThemePart')
  const feedback = () => page.locator('.workbook-feedback').textContent()
  const menu = id => page.locator(`[data-ribbon-menu="${id}"]`)
  const pick = async (id, value) => { await menu(id).selectOption(value); await settled() }
  await page.goto(`${base}/reports/v1/native/theme/1`); await ready()

  await page.locator('[data-ribbon-tab="Page Layout"]').click()
  for (const id of ['theme', 'theme-colors', 'theme-fonts']) assert.equal(await menu(id).isEnabled(), true, id)
  assert.equal(await menu('theme-colors').getAttribute('title'), '颜色（当前：Office）')
  assert.equal(await page.locator('[data-ribbon-command="theme-effects"]').isDisabled(), true)
  assert.equal(await page.locator('[data-ribbon-command="theme-effects"]').getAttribute('title'), '固定源未提供主题效果写入')

  // 主题 ▸ Ember：配色 + 字体（固定源 FONT_BY_THEME：Ember → Trebuchet MS）
  await pick('theme', 'ember')
  await page.waitForFunction(() => document.querySelector('.workbook-feedback')?.textContent?.includes('主题已设为「Ember」'), null, { timeout: 60000 })
  assert.equal(await menu('theme').inputValue(), '', 'menu snaps back to its title')
  assert.equal(await menu('theme-colors').getAttribute('title'), '颜色（当前：Ember）')
  assert.equal(await menu('theme-fonts').getAttribute('title'), '字体（当前：Trebuchet MS）')
  let ops = await themeOps()
  assert.deepEqual(ops.map(op => [op.state.colors?.name, op.state.fonts?.name]), [['Ember', 'Trebuchet MS']])
  // 颜色 ▸ Forest（只换配色，字体保持）
  await pick('theme-colors', 'forest')
  await page.waitForFunction(() => document.querySelector('.workbook-feedback')?.textContent?.includes('主题颜色已设为「Forest」'), null, { timeout: 60000 })
  assert.equal(await menu('theme-fonts').getAttribute('title'), '字体（当前：Trebuchet MS）')
  // 文件 ▸ 撤销 / 重做
  await page.locator('[data-ribbon-tab="File"]').click(); await page.locator('[data-ribbon-command="undo"]').click(); await settled()
  assert.deepEqual((await themeOps()).map(op => op.state.colors?.name), ['Ember'])
  await page.locator('[data-ribbon-command="redo"]').click(); await settled()
  assert.deepEqual((await themeOps()).map(op => op.state.colors?.name), ['Ember', 'Forest'])
  // 字体 ▸ Georgia
  await page.locator('[data-ribbon-tab="Page Layout"]').click()
  await pick('theme-fonts', 'georgia')
  await page.waitForFunction(() => document.querySelector('.workbook-feedback')?.textContent?.includes('主题字体已设为「Georgia」'), null, { timeout: 60000 })
  ops = await themeOps()
  assert.deepEqual(ops.map(op => [op.state.colors?.name ?? null, op.state.fonts?.name ?? null]), [['Ember', 'Trebuchet MS'], ['Forest', null], [null, 'Georgia']])
  if (process.env.WORKBOOK_SMOKE_SCREENSHOT) await page.screenshot({ path: process.env.WORKBOOK_SMOKE_SCREENSHOT })
  // 刷新后草稿恢复（重放到同一主题）再保存
  await page.reload(); await ready()
  await page.locator('[data-ribbon-tab="Page Layout"]').click()
  assert.equal(await menu('theme-colors').getAttribute('title'), '颜色（当前：Forest）')
  assert.equal(await menu('theme-fonts').getAttribute('title'), '字体（当前：Georgia）')
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent?.includes('已保存'), null, { timeout: 90000 })
  assert.ok(payload, 'save request issued')
  assert.deepEqual(payload.operations.filter(op => op.kind === 'setThemePart').map(op => op.themePath), ['xl/theme/theme1.xml', 'xl/theme/theme1.xml', 'xl/theme/theme1.xml'])
  await page.waitForFunction(() => { const link = document.querySelector('[data-action="xlsx-download"]'); return link && !link.hidden && link.getAttribute('href') }, null, { timeout: 30000 })
  const href = await page.locator('[data-action="xlsx-download"]').getAttribute('href')
  assert.equal(href, '/theme-download.xlsx')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], href))
  assert.deepEqual(downloaded, saved)
  if (process.env.WORKBOOK_SMOKE_OUTPUT) await writeFile(process.env.WORKBOOK_SMOKE_OUTPUT, downloaded)
  const file = JSON.parse(py({ mode: 'inspect', bytes: downloaded.toString('base64'), source: bytes.toString('base64') }))
  assert.equal(file.clrScheme, 'Forest'); assert.equal(file.accent1, '217346'); assert.equal(file.accent2, '4EA72E')
  assert.equal(file.fontScheme, 'Georgia'); assert.equal(file.major, 'Georgia'); assert.equal(file.minor, 'Georgia')
  // 单元格仍引用主题槽位，显式 RGB 与数值不变；只改主题部件
  assert.equal(file.A1theme, 4); assert.equal(file.A1fill, 5); assert.equal(file.A1scheme, 'minor')
  assert.equal(file.B1rgb, 'FF123456'); assert.equal(file.A2, 42)
  assert.deepEqual(file.changed, ['xl/theme/theme1.xml'])
  // 修订 2 重开：菜单显示保存后的主题
  await page.goto(`${base}/reports/v1/native/theme/2`); await ready()
  await page.locator('[data-ribbon-tab="Page Layout"]').click()
  assert.equal(await menu('theme-colors').getAttribute('title'), '颜色（当前：Forest）')
  if (process.env.WORKBOOK_SMOKE_SCREENSHOT) await page.screenshot({ path: process.env.WORKBOOK_SMOKE_SCREENSHOT.replace(/\.png$/, '-revision-2.png') })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, preview, operations: payload.operations.map(item => item.kind), file, downloadedSha256: sha(downloaded) }))
} finally { await browser?.close(); server.kill() }
