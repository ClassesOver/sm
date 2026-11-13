import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

// 设计 ▸ 页面边框（固定源 ribbon-design-tab + PageBorderDialog）：真实 Python/Node DOCX 引擎检查、保存与独立 ZIP/XML 回读；授权与修订路由为显式 fixture。
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_PAGE_BORDERS_SMOKE_PORT ?? 4233), base = `http://127.0.0.1:${port}`
const output = process.env.DOCX_PAGE_BORDERS_SMOKE_OUTPUT ?? '/tmp/docx-page-borders'
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
 from docx.enum.section import WD_SECTION
 d=Document();d.add_paragraph('页面边框冒烟正文');d.sections[0].header.paragraphs[0].text='Untouched header';d.add_section(WD_SECTION.NEW_PAGE);d.add_paragraph('Second section paragraph')
 out=BytesIO();d.save(out);print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='inspect':print(json.dumps(inspect_docx(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':print(base64.b64encode(patch_docx(base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 a=ZipFile(BytesIO(base64.b64decode(p['before'])));b=ZipFile(BytesIO(base64.b64decode(p['after'])))
 names={n for n in a.namelist() if not n.endswith('/')};assert names=={n for n in b.namelist() if not n.endswith('/')}
 changed=sorted(n for n in names if a.read(n)!=b.read(n))
 root=etree.fromstring(b.read('word/document.xml'))
 def border(sect):
  n=sect.find('{%s}pgBorders'%W)
  return None if n is None else {'attrs':{k.split('}')[1]:v for k,v in n.attrib.items()},'sides':{etree.QName(c).localname:{k.split('}')[1]:v for k,v in c.attrib.items()} for c in n}}
 import re as _re
 noborder=lambda z:_re.sub(rb'<w:pgBorders.*?</w:pgBorders>',b'',etree.tostring(etree.fromstring(z.read('word/document.xml')).find('{%s}body'%W)),flags=_re.S)
 print(json.dumps({'changedParts':changed,'borders':[border(s) for s in root.iter('{%s}sectPr'%W)],'bodyExceptBorders':noborder(a)==noborder(b),
  'paragraphs':[x.text for x in Document(BytesIO(base64.b64decode(p['after']))).paragraphs],
  'header':Document(BytesIO(base64.b64decode(p['after']))).sections[0].header.paragraphs[0].text}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status) throw Error(result.stderr || result.stdout)
  return result.stdout.trim()
}
const source = Buffer.from(python({ mode: 'create' }), 'base64'), sourceModel = JSON.parse(python({ mode: 'inspect', bytes: source.toString('base64') }))
assert.deepEqual(sourceModel.sections.map(section => section.settings.pageBorder), [false, false])
let saved, savedModel, payload, browser, page
const errors = []
const server = spawn(process.execPath, ['--input-type=module', '-e', `import { createServer } from 'vite'; const server = await createServer({ server: { host: '127.0.0.1', port: ${port}, strictPort: true, hmr: false } }); await server.listen()`], { cwd: frontend, stdio: 'ignore' })
try {
  for (let i = 0; i < 160; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, args: ['--disable-features=LocalNetworkAccessChecks'], ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
  page.on('pageerror', error => errors.push(error.message))
  const revision = route => Number(route.request().url().match(/page-borders\/(\d+)\/api/)[1]), active = route => revision(route) === 1 ? source : saved
  await page.route('**/reports/v1/native/page-borders/*/api/context', route => route.fulfill({ json: { context: { documentId: 'page-borders', format: 'docx', revision: revision(route), parentRevision: revision(route) === 1 ? null : 1,
    scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'source.docx', size: active(route).length, sha256: sha(active(route)), mediaType: mime }, origin: 'upload' },
    editingEnabled: true, csrfToken: 'fixture', capabilities: { docx_editor: true } } }))
  await page.route('**/reports/v1/native/page-borders/*/api/file', route => route.fulfill({ body: active(route), contentType: mime }))
  await page.route('**/reports/v1/native/page-borders/*/api/preview', route => {
    const model = revision(route) === 1 ? sourceModel : savedModel
    return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } })
  })
  await page.route('**/reports/v1/native/page-borders/1/api/save', route => {
    payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, sha(source))
    saved = Buffer.from(python({ mode: 'patch', bytes: source.toString('base64'), operations: payload.operations }), 'base64')
    savedModel = JSON.parse(python({ mode: 'inspect', bytes: saved.toString('base64') }))
    return route.fulfill({ json: { documentId: 'page-borders', revision: 2, parentRevision: 1, revisionRegistered: true, validation: { ok: false, issues: [{ code: 'fixture_review', message: 'GUI fixture soft warning' }] },
      artifacts: { word: { downloadUrl: '/page-borders.docx', sha256: sha(saved), size: saved.length } }, editor: { openUrl: '/reports/v1/native/page-borders/2' } } })
  })
  await page.route('**/page-borders.docx', route => route.fulfill({ body: saved, contentType: mime }))
  await page.route(/\/reports\/v1\/native\/page-borders\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const ready = async () => { await page.locator('.docx-ribbon [role="tablist"]').waitFor({ timeout: 60000 }); await page.getByRole('textbox', { name: 'Word 文档编辑区' }).getByText('页面边框冒烟正文').waitFor() }
  const draft = () => page.evaluate(() => { const key = Object.keys(localStorage).find(item => item.startsWith('native-editor-draft:')); return key ? JSON.parse(localStorage.getItem(key)).operations : [] })
  const layout = operations => operations.filter(operation => operation.kind === 'setSectionLayout')
  const waitDraft = async predicate => { for (let i = 0; i < 60; i++) { const ops = await draft(); if (predicate(ops)) return ops; await delay(100) } throw Error(`draft condition timed out: ${JSON.stringify(await draft())}`) }
  const trigger = () => page.locator('[data-action="page-borders"]')
  const design = () => page.locator('[data-tab-id="design"]').click()
  const menu = async action => { await design(); assert(await trigger().isEnabled(), await trigger().getAttribute('title')); await trigger().click(); await page.locator(`[data-action="${action}"]`).click() }
  const open = async n => { await page.goto(`${base}/reports/v1/native/page-borders/${n}`); await ready() }
  const [first, second] = sourceModel.sections
  await open(1)
  await design(); assert.equal(await trigger().getAttribute('title'), '为页面添加边框')
  // 方框(单实线)：当前节（第 1 节）
  await page.getByRole('textbox', { name: 'Word 文档编辑区' }).getByText('页面边框冒烟正文').click()
  await menu('page-borders-box')
  assert.deepEqual(layout(await waitDraft(ops => layout(ops).length === 1)), [{ kind: 'setSectionLayout', sectionId: first.sectionId, expectedSectionSha256: first.expectedSectionSha256, values: { pageBorder: true, pageBorderProps: null } }])
  await design(); assert.equal(await trigger().getAttribute('class').then(value => value.includes('active')), true)
  // 撤销 / 重做
  await page.getByRole('textbox', { name: 'Word 文档编辑区' }).getByText('页面边框冒烟正文').click()
  await page.keyboard.press('Control+z'); await waitDraft(ops => layout(ops).length === 0)
  await page.keyboard.press('Control+Shift+z'); await waitDraft(ops => layout(ops).length === 1)
  // 无 = 与来源一致，撤回
  await menu('page-borders-none'); await waitDraft(ops => layout(ops).length === 0)
  // 页面边框…：阴影、3 pt、#1F4E79、应用于整篇文档
  await menu('page-borders-dialog')
  const dialog = page.locator('.docx-page-border-dialog'); await dialog.waitFor({ state: 'visible' })
  await dialog.locator('[data-pb-setting="shadow"]').click()
  await dialog.getByLabel('边框宽度').selectOption('3')
  await dialog.getByLabel('边框颜色').fill('#1f4e79')
  await dialog.getByLabel('应用于').selectOption('whole:all')
  assert.equal(await dialog.locator('.pb-preview-border').count(), 1)
  await page.screenshot({ path: `${output}-dialog.png` })
  await dialog.locator('.btn-primary').click()
  const sides = Object.fromEntries(['top', 'bottom', 'left', 'right'].map(name => [name, { val: 'single', widthPt: 3, spacePt: 24, color: '1F4E79', shadow: true }]))
  const props = { offsetFrom: 'page', spacePt: 24, widthPt: 3, color: '1F4E79', sides }
  const whole = layout(await waitDraft(ops => layout(ops).length === 2))
  assert.deepEqual(whole, [first, second].map(section => ({ kind: 'setSectionLayout', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256, values: { pageBorder: true, pageBorderProps: props } })))
  // 分页预览显示待保存的边框
  await page.locator('[data-tab-id="view"]').click()
  const pagination = page.getByRole('button', { name: '分页预览' })
  if (await pagination.count()) { await pagination.first().click(); await page.waitForTimeout(1500); await page.screenshot({ path: `${output}-pagination.png` }); await page.keyboard.press('Escape') }
  await page.reload(); await ready()
  const restored = await draft(); assert.deepEqual(layout(restored), whole)
  await page.locator('[data-action="save"]').click(); await page.getByRole('link', { name: '下载 Word', exact: true }).waitFor({ timeout: 60000 })
  assert.deepEqual(payload.operations, restored)
  const downloadUrl = await page.getByRole('link', { name: '下载 Word', exact: true }).getAttribute('href')
  const downloaded = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.equal(sha(downloaded), sha(saved))
  writeFileSync(`${output}.docx`, downloaded)
  const readback = JSON.parse(python({ mode: 'verify', before: source.toString('base64'), after: downloaded.toString('base64') }))
  assert.equal(readback.borders.length, 2)
  for (const border of readback.borders) {
    assert.deepEqual(border.attrs, { offsetFrom: 'page' })
    for (const name of ['top', 'left', 'bottom', 'right']) assert.deepEqual(border.sides[name], { val: 'single', sz: '24', space: '24', color: '1F4E79', shadow: '1' })
  }
  assert.equal(readback.bodyExceptBorders, true)
  assert.ok(readback.paragraphs.includes('页面边框冒烟正文') && readback.paragraphs.includes('Second section paragraph'), JSON.stringify(readback.paragraphs))
  assert.equal(readback.header, 'Untouched header')
  assert.ok(readback.changedParts.every(name => ['word/document.xml', 'docProps/core.xml'].includes(name)), JSON.stringify(readback.changedParts))
  assert.deepEqual(savedModel.sections.map(section => section.settings.pageBorder), [true, true])
  await open(2); await design(); assert.equal(await trigger().getAttribute('class').then(value => value.includes('active')), true)
  assert.deepEqual(await draft(), [])
  await page.screenshot({ path: `${output}-reopened.png` })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, browser: browser.version(), sourceSha256: sha(source), savedSha256: sha(saved), operations: payload.operations.length, readback, undoRedo: true, withdrawToSource: true, draftRestored: true, revision2Reopened: true }))
} catch (error) { await page?.screenshot({ path: `${output}-failed.png` }).catch(() => {}); console.error(JSON.stringify({ failed: true, message: String(error), pageErrors: errors })); throw error } finally { await browser?.close(); server.kill() }
