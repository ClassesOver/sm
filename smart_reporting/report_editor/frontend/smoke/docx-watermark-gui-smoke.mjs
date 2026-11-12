import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

// 设计 ▸ 水印：真实 Python/Node DOCX 引擎检查、保存与独立 ZIP/XML 回读；授权与修订路由为显式 fixture。
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_WATERMARK_SMOKE_PORT ?? 4233), base = `http://127.0.0.1:${port}`
const output = process.env.DOCX_WATERMARK_SMOKE_OUTPUT ?? '/tmp/docx-watermark'
const mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', sha = bytes => createHash('sha256').update(bytes).digest('hex')
const python = (input, venv = process.env.DOCX_SMOKE_PYTHON ?? `${repo}/.venv/bin/python`) => {
  const result = spawnSync(venv, ['-c', `
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from docx import Document
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';NS={'w':W}
p=json.load(sys.stdin)
if p['mode']=='create':
 d=Document();d.add_paragraph('水印冒烟正文');d.add_paragraph('Second paragraph');d.sections[0].header.paragraphs[0].text='Untouched header'
 out=BytesIO();d.save(out);print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='inspect':print(json.dumps(inspect_docx(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':print(base64.b64encode(patch_docx(base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 a=ZipFile(BytesIO(base64.b64decode(p['before'])));b=ZipFile(BytesIO(base64.b64decode(p['after'])))
 names={n for n in a.namelist() if not n.endswith('/')};assert names=={n for n in b.namelist() if not n.endswith('/')}
 changed=sorted(n for n in names if a.read(n)!=b.read(n))
 body=lambda z:etree.tostring(etree.fromstring(z.read('word/document.xml')).find('{%s}body'%W))
 hdr=[n for n in sorted(names) if n.startswith('word/header')]
 V='urn:schemas-microsoft-com:vml'
 marks=[]
 for n in hdr:
  x=etree.fromstring(b.read(n))
  for shape in x.iter('{%s}shape'%V):
   tp=shape.find('{%s}textpath'%V)
   if tp is not None: marks.append({'part':n,'string':tp.get('string'),'tpStyle':tp.get('style'),'style':shape.get('style'),'fill':shape.get('fillcolor'),'opacity':(shape.find('{%s}fill'%V).get('opacity') if shape.find('{%s}fill'%V) is not None else None),
    'gallery':bool(x.xpath('.//w:docPartGallery[@w:val="Watermarks"]',namespaces=NS))})
 h=Document(BytesIO(base64.b64decode(p['after']))).sections[0].header
 print(json.dumps({'changedParts':changed,'watermarks':marks,'bodyExact':body(a)==body(b),'paragraphs':[x.text for x in Document(BytesIO(base64.b64decode(p['after']))).paragraphs],
  'headerTexts':[x.text for x in h.paragraphs if x.text]}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status) throw Error(result.stderr || result.stdout)
  return result.stdout.trim()
}
const source = Buffer.from(python({ mode: 'create' }), 'base64'), sourceModel = JSON.parse(python({ mode: 'inspect', bytes: source.toString('base64') }))
assert.deepEqual({ text: sourceModel.watermark.text, editable: sourceModel.watermark.editable }, { text: null, editable: true })
let saved, savedModel, payload, browser, page
const errors = []
const server = spawn(process.execPath, ['--input-type=module', '-e', `import { createServer } from 'vite'; const server = await createServer({ server: { host: '127.0.0.1', port: ${port}, strictPort: true, hmr: false } }); await server.listen()`], { cwd: frontend, stdio: 'ignore' })
try {
  for (let i = 0; i < 160; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, args: ['--disable-features=LocalNetworkAccessChecks'], ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
  page.on('pageerror', error => errors.push(error.message))
  const revision = route => Number(route.request().url().match(/watermark\/(\d+)\/api/)[1]), active = route => revision(route) === 1 ? source : saved
  await page.route('**/reports/v1/native/watermark/*/api/context', route => route.fulfill({ json: { context: { documentId: 'watermark', format: 'docx', revision: revision(route), parentRevision: revision(route) === 1 ? null : 1,
    scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'source.docx', size: active(route).length, sha256: sha(active(route)), mediaType: mime }, origin: 'upload' },
    editingEnabled: true, csrfToken: 'fixture', capabilities: { docx_editor: true } } }))
  await page.route('**/reports/v1/native/watermark/*/api/file', route => route.fulfill({ body: active(route), contentType: mime }))
  await page.route('**/reports/v1/native/watermark/*/api/preview', route => {
    assert.deepEqual(route.request().postDataJSON().operations, [])
    const model = revision(route) === 1 ? sourceModel : savedModel
    return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } })
  })
  await page.route('**/reports/v1/native/watermark/1/api/save', route => {
    payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, sha(source))
    saved = Buffer.from(python({ mode: 'patch', bytes: source.toString('base64'), operations: payload.operations }), 'base64')
    savedModel = JSON.parse(python({ mode: 'inspect', bytes: saved.toString('base64') }))
    return route.fulfill({ json: { documentId: 'watermark', revision: 2, parentRevision: 1, revisionRegistered: true, validation: { ok: false, issues: [{ code: 'fixture_review', message: 'GUI fixture soft warning' }] },
      artifacts: { word: { downloadUrl: '/watermark.docx', sha256: sha(saved), size: saved.length } }, editor: { openUrl: '/reports/v1/native/watermark/2' } } })
  })
  await page.route('**/watermark.docx', route => route.fulfill({ body: saved, contentType: mime }))
  await page.route(/\/reports\/v1\/native\/watermark\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const ready = async () => { await page.locator('.docx-ribbon [role="tablist"]').waitFor({ timeout: 60000 }); await page.getByRole('textbox', { name: 'Word 文档编辑区' }).getByText('水印冒烟正文').waitFor() }
  const mark = () => page.evaluate(() => document.querySelector('.doc-page')?.getAttribute('data-watermark') ?? null)
  const draft = () => page.evaluate(() => { const key = Object.keys(localStorage).find(item => item.startsWith('native-editor-draft:')); return key ? JSON.parse(localStorage.getItem(key)).operations : [] })
  const trigger = () => page.locator('[data-action="watermark"]')
  const design = () => page.locator('[data-tab-id="design"]').click()
  const menu = async () => { await design(); assert(await trigger().isEnabled(), await trigger().getAttribute('title')); await trigger().click() }
  const waitMark = async expected => { for (let i = 0; i < 50 && await mark() !== expected; i++) await delay(100); assert.equal(await mark(), expected) }
  const open = async n => { await page.goto(`${base}/reports/v1/native/watermark/${n}`); await ready() }
  const anchor = sourceModel.watermark.expectedHeadersSha256
  await open(1)
  await design(); assert.equal(await trigger().getAttribute('title'), '水印：无')
  assert.equal(await mark(), null)
  // 预设：机密 → 撤销 / 重做
  await menu(); await page.locator('[data-action="watermark-preset-机密"]').click(); await waitMark('机密')
  assert.deepEqual(await draft(), [{ kind: 'setWatermark', expectedHeadersSha256: anchor, watermark: { text: '机密' } }])
  await page.getByRole('textbox', { name: 'Word 文档编辑区' }).getByText('Second paragraph').click()
  await page.keyboard.press('Control+z'); await waitMark(null); assert.deepEqual(await draft(), [])
  await page.keyboard.press('Control+Shift+z'); await waitMark('机密')
  // 删除水印 = 与来源（无水印）相同，撤回修改
  await menu(); await page.locator('[data-action="watermark-remove"]').click(); await waitMark(null); assert.deepEqual(await draft(), [])
  // 自定义水印…：文字、字体、字号 72、粗体、透明度 60%、颜色、水平
  await menu(); await page.locator('[data-action="watermark-custom"]').click()
  const dialog = page.locator('.docx-watermark-dialog'); await dialog.waitFor({ state: 'visible' })
  await dialog.locator('input[name=mode][value=text]').check()
  await page.getByLabel('水印文字', { exact: true }).fill('内部资料')
  await page.getByLabel('水印字体', { exact: true }).selectOption('Arial')
  await page.getByLabel('水印字号').selectOption('72')
  await dialog.locator('input[name=bold]').check()
  await page.getByLabel('水印透明度').fill('60')
  await page.getByLabel('水印字体颜色').fill('#c00000')
  await dialog.locator('input[name=layout][value=horizontal]').check()
  await dialog.locator('button[value=ok]').click(); await waitMark('内部资料')
  const custom = (await draft())[0]
  assert.equal(custom.kind, 'setWatermark'); assert.equal(custom.expectedHeadersSha256, anchor)
  assert.deepEqual({ ...custom.watermark, boxPt: undefined }, { text: '内部资料', fontFamily: 'Arial', colorHex: 'C00000', opacity: 0.4, diagonal: false, bold: true, sizePt: 72, boxPt: undefined })
  assert.ok(custom.watermark.boxPt.widthPt > 100 && custom.watermark.boxPt.heightPt > 30, JSON.stringify(custom.watermark.boxPt))
  await design(); assert.equal(await trigger().getAttribute('title'), '水印：内部资料')
  await page.screenshot({ path: `${output}-draft.png` })
  await page.reload(); await ready(); await waitMark('内部资料')
  const restored = await draft(); assert.deepEqual(restored, [custom])
  await page.locator('[data-action="save"]').click(); await page.getByRole('link', { name: '下载 Word', exact: true }).waitFor({ timeout: 60000 })
  assert.deepEqual(payload.operations, restored)
  const downloadUrl = await page.getByRole('link', { name: '下载 Word', exact: true }).getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.equal(sha(downloaded), sha(saved))
  writeFileSync(`${output}.docx`, downloaded)
  const readback = JSON.parse(python({ mode: 'verify', before: source.toString('base64'), after: downloaded.toString('base64') }))
  assert.equal(readback.watermarks.length, 1)
  const [wm] = readback.watermarks
  assert.equal(wm.string, '内部资料'); assert.equal(wm.gallery, true); assert.equal(wm.fill, '#C00000'); assert.equal(wm.opacity, '0.4')
  assert.match(wm.tpStyle, /font-family:"Arial";font-size:1pt;font-weight:bold/); assert.doesNotMatch(wm.style, /rotation/)
  assert.match(wm.style, new RegExp(`width:${custom.watermark.boxPt.widthPt}pt;height:${custom.watermark.boxPt.heightPt}pt`))
  assert.equal(readback.bodyExact, true)
  assert.deepEqual(readback.paragraphs, ['水印冒烟正文', 'Second paragraph']); assert.deepEqual(readback.headerTexts, ['Untouched header'])
  assert.ok(readback.changedParts.every(name => name === wm.part || name === 'docProps/core.xml'), JSON.stringify(readback.changedParts))
  assert.equal(savedModel.watermark.text, '内部资料')
  await open(2); await waitMark('内部资料'); await design(); assert.equal(await trigger().getAttribute('title'), '水印：内部资料')
  assert.deepEqual(await draft(), [])
  assert.deepEqual(savedModel.watermark.style, { fontFamily: 'Arial', colorHex: 'C00000', opacity: 0.4, diagonal: false, bold: true })
  // 修订 2 的预览与对话框默认值来自文件中回读的样式（固定源 textFromDocImage）
  const vars = await page.evaluate(() => { const style = getComputedStyle(document.querySelector('.doc-page')); return ['--watermark-color', '--watermark-rotate', '--watermark-opacity', '--watermark-weight'].map(name => style.getPropertyValue(name).trim()) })
  assert.deepEqual(vars, ['#C00000', '0deg', '0.4', 'bold'])
  await menu(); await page.locator('[data-action="watermark-custom"]').click(); await dialog.waitFor({ state: 'visible' })
  assert.equal(await page.getByLabel('水印字体颜色').inputValue(), '#c00000'); assert.equal(await page.getByLabel('水印字体', { exact: true }).inputValue(), 'Arial')
  assert.equal(await dialog.locator('input[name=layout][value=horizontal]').isChecked(), true); assert.equal(await page.getByLabel('水印透明度').inputValue(), '60')
  await dialog.locator('button[value=cancel]').click(); assert.deepEqual(await draft(), [])
  await page.screenshot({ path: `${output}-reopened.png` })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, browser: browser.version(), sourceSha256: sha(source), savedSha256: sha(saved), operations: payload.operations, readback, undoRedo: true, withdrawToSource: true, draftRestored: true, revision2Reopened: true, pageErrors: errors }))
} catch (error) { await page?.screenshot({ path: `${output}-failed.png` }).catch(() => {}); console.error(JSON.stringify({ failed: true, message: String(error), pageErrors: errors })); throw error } finally { await browser?.close(); server.kill() }
