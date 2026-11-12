import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

// 设计 ▸ 页面颜色：真实 Python/Node DOCX 引擎检查、保存与独立 ZIP/XML 回读；授权与修订路由为显式 fixture。
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_PAGE_COLOR_SMOKE_PORT ?? 4231), base = `http://127.0.0.1:${port}`
const output = process.env.DOCX_PAGE_COLOR_SMOKE_OUTPUT ?? '/tmp/docx-page-color'
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
 d=Document();d.add_paragraph('页面颜色冒烟正文');d.add_paragraph('Second paragraph');d.sections[0].header.paragraphs[0].text='Untouched header'
 out=BytesIO();d.save(out);print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='inspect':print(json.dumps(inspect_docx(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':print(base64.b64encode(patch_docx(base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 a=ZipFile(BytesIO(base64.b64decode(p['before'])));b=ZipFile(BytesIO(base64.b64decode(p['after'])))
 names={n for n in a.namelist() if not n.endswith('/')};assert names=={n for n in b.namelist() if not n.endswith('/')}
 changed=sorted(n for n in names if a.read(n)!=b.read(n))
 root=etree.fromstring(b.read('word/document.xml'));settings=etree.fromstring(b.read('word/settings.xml'))
 bg=root.xpath('./w:background',namespaces=NS)
 body=lambda z:etree.tostring(etree.fromstring(z.read('word/document.xml')).find('{%s}body'%W))
 print(json.dumps({'changedParts':changed,'background':[e.get('{%s}color'%W) for e in bg],'displayBackgroundShape':bool(settings.xpath('./w:displayBackgroundShape',namespaces=NS)),
  'bodyExact':body(a)==body(b),'paragraphs':[x.text for x in Document(BytesIO(base64.b64decode(p['after']))).paragraphs],
  'header':Document(BytesIO(base64.b64decode(p['after']))).sections[0].header.paragraphs[0].text}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status) throw Error(result.stderr || result.stdout)
  return result.stdout.trim()
}
const source = Buffer.from(python({ mode: 'create' }), 'base64'), sourceModel = JSON.parse(python({ mode: 'inspect', bytes: source.toString('base64') }))
assert.deepEqual({ color: sourceModel.pageColor.color, editable: sourceModel.pageColor.editable }, { color: null, editable: true })
let saved, savedModel, payload, browser, page
const errors = []
const server = spawn(process.execPath, ['--input-type=module', '-e', `import { createServer } from 'vite'; const server = await createServer({ server: { host: '127.0.0.1', port: ${port}, strictPort: true, hmr: false } }); await server.listen()`], { cwd: frontend, stdio: 'ignore' })
try {
  for (let i = 0; i < 160; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, args: ['--disable-features=LocalNetworkAccessChecks'], ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
  page.on('pageerror', error => errors.push(error.message))
  const revision = route => Number(route.request().url().match(/page-color\/(\d+)\/api/)[1]), active = route => revision(route) === 1 ? source : saved
  await page.route('**/reports/v1/native/page-color/*/api/context', route => route.fulfill({ json: { context: { documentId: 'page-color', format: 'docx', revision: revision(route), parentRevision: revision(route) === 1 ? null : 1,
    scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'source.docx', size: active(route).length, sha256: sha(active(route)), mediaType: mime }, origin: 'upload' },
    editingEnabled: true, csrfToken: 'fixture', capabilities: { docx_editor: true } } }))
  await page.route('**/reports/v1/native/page-color/*/api/file', route => route.fulfill({ body: active(route), contentType: mime }))
  await page.route('**/reports/v1/native/page-color/*/api/preview', route => {
    assert.deepEqual(route.request().postDataJSON().operations, [])
    const model = revision(route) === 1 ? sourceModel : savedModel
    return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } })
  })
  await page.route('**/reports/v1/native/page-color/1/api/save', route => {
    payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, sha(source))
    saved = Buffer.from(python({ mode: 'patch', bytes: source.toString('base64'), operations: payload.operations }), 'base64')
    savedModel = JSON.parse(python({ mode: 'inspect', bytes: saved.toString('base64') }))
    return route.fulfill({ json: { documentId: 'page-color', revision: 2, parentRevision: 1, revisionRegistered: true, validation: { ok: false, issues: [{ code: 'fixture_review', message: 'GUI fixture soft warning' }] },
      artifacts: { word: { downloadUrl: '/page-color.docx', sha256: sha(saved), size: saved.length } }, editor: { openUrl: '/reports/v1/native/page-color/2' } } })
  })
  await page.route('**/page-color.docx', route => route.fulfill({ body: saved, contentType: mime }))
  await page.route(/\/reports\/v1\/native\/page-color\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const ready = async () => { await page.locator('.docx-ribbon [role="tablist"]').waitFor({ timeout: 60000 }); await page.getByRole('textbox', { name: 'Word 文档编辑区' }).getByText('页面颜色冒烟正文').waitFor() }
  const paper = () => page.getByRole('textbox', { name: 'Word 文档编辑区' }).evaluate(node => getComputedStyle(node).backgroundColor)
  const draft = () => page.evaluate(() => { const key = Object.keys(localStorage).find(item => item.startsWith('native-editor-draft:')); return key ? JSON.parse(localStorage.getItem(key)).operations : [] })
  const trigger = () => page.locator('[data-action="page-color"]')
  const design = () => page.locator('[data-tab-id="design"]').click()
  const pick = async value => { await design(); assert(await trigger().isEnabled(), await trigger().getAttribute('title')); await trigger().click(); await page.locator(`[data-action="page-color-${value}"]`).click() }
  const waitPaper = async expected => { for (let i = 0; i < 50 && await paper() !== expected; i++) await delay(100); assert.equal(await paper(), expected) }
  const open = async n => { await page.goto(`${base}/reports/v1/native/page-color/${n}`); await ready() }
  await open(1)
  await design(); assert.equal(await trigger().getAttribute('title'), '页面颜色：无颜色')
  assert.equal(await paper(), 'rgb(255, 255, 255)')
  await pick('FFC000'); await waitPaper('rgb(255, 192, 0)')
  assert.deepEqual(await draft(), [{ kind: 'setPageColor', expectedBackgroundSha256: sourceModel.pageColor.expectedBackgroundSha256, color: 'FFC000' }])
  await page.getByRole('textbox', { name: 'Word 文档编辑区' }).getByText('Second paragraph').click()
  await page.keyboard.press('Control+z'); await waitPaper('rgb(255, 255, 255)'); assert.deepEqual(await draft(), [])
  await page.keyboard.press('Control+Shift+z'); await waitPaper('rgb(255, 192, 0)')
  await pick('0E2841'); await waitPaper('rgb(14, 40, 65)')
  await design(); assert.equal(await trigger().getAttribute('title'), '页面颜色：#0E2841')
  await page.screenshot({ path: `${output}-draft.png` })
  // 选回“无颜色”等于来源值，撤回修改；再设回深色
  await pick('none'); await waitPaper('rgb(255, 255, 255)'); assert.deepEqual(await draft(), [])
  await pick('0E2841'); await waitPaper('rgb(14, 40, 65)')
  await page.reload(); await ready(); await waitPaper('rgb(14, 40, 65)')
  const restored = await draft(); assert.deepEqual(restored, [{ kind: 'setPageColor', expectedBackgroundSha256: sourceModel.pageColor.expectedBackgroundSha256, color: '0E2841' }])
  await page.locator('[data-action="save"]').click(); await page.getByRole('link', { name: '下载 Word', exact: true }).waitFor({ timeout: 60000 })
  assert.deepEqual(payload.operations, restored)
  const downloadUrl = await page.getByRole('link', { name: '下载 Word', exact: true }).getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.equal(sha(downloaded), sha(saved))
  writeFileSync(`${output}.docx`, downloaded)
  const readback = JSON.parse(python({ mode: 'verify', before: source.toString('base64'), after: downloaded.toString('base64') }))
  assert.deepEqual(readback.background, ['0E2841']); assert.equal(readback.displayBackgroundShape, true); assert.equal(readback.bodyExact, true)
  assert.deepEqual(readback.paragraphs, ['页面颜色冒烟正文', 'Second paragraph']); assert.equal(readback.header, 'Untouched header')
  assert.ok(readback.changedParts.every(name => ['word/document.xml', 'word/settings.xml', 'docProps/core.xml'].includes(name)), JSON.stringify(readback.changedParts))
  assert.equal(savedModel.pageColor.color, '0E2841')
  await open(2); await waitPaper('rgb(14, 40, 65)'); await design(); assert.equal(await trigger().getAttribute('title'), '页面颜色：#0E2841')
  assert.deepEqual(await draft(), [])
  await page.screenshot({ path: `${output}-reopened.png` })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, browser: browser.version(), sourceSha256: sha(source), savedSha256: sha(saved), operations: payload.operations, readback, undoRedo: true, withdrawToSource: true, draftRestored: true, revision2Reopened: true, pageErrors: errors }))
} catch (error) { await page?.screenshot({ path: `${output}-failed.png` }).catch(() => {}); console.error(JSON.stringify({ failed: true, message: String(error), pageErrors: errors })); throw error } finally { await browser?.close(); server.kill() }
