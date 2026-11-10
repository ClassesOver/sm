import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const engine = `${repo}/smart_reporting/reporting/pdf_engine`
const port = Number(process.env.PDF_DRAW_SMOKE_PORT ?? 4198)
const baseUrl = `http://127.0.0.1:${port}`
const mediaType = 'application/pdf'
const runBridge = (mode, bytes, operations = []) => {
  if (mode !== 'create') {
    const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin);b=base64.b64decode(p['bytes'])
if p['mode']=='inspect':print(json.dumps(inspect_pdf(b)))
else:
 r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify({ mode, bytes: bytes.toString('base64'), operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
    if (result.status !== 0) throw new Error(result.stderr)
    return JSON.parse(result.stdout)
  }
  const result = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', `
import { readFileSync } from 'node:fs'
import { PDFDocument, PDFName, PDFString, degrees } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './bridge/operations.ts'
const input = JSON.parse(readFileSync(0, 'utf8'))
const bytes = Buffer.from(input.bytes, 'base64')
let output
if (input.mode === 'create') {
  const pdf = await PDFDocument.create()
  pdf.setTitle('PDF properties smoke')
  pdf.setAuthor('Smart Reporting')
  pdf.addPage([612, 792])
  const secondPage = pdf.addPage([500, 400])
  pdf.addPage([320, 480]); pdf.addPage([700, 500])
  pdf.getPages().forEach((page, i) => { page.setRotation(degrees(i * 90)); const b=page.getMediaBox(); page.setCropBox(12, 24, b.width - 24, b.height - 48) })
  const note = pdf.context.register(pdf.context.obj({ Type: 'Annot', Subtype: 'Text', Rect: [30,60,50,78], Contents: PDFString.of('Keep native note') })); secondPage.node.set(PDFName.of('Annots'), pdf.context.obj([note]))
  const outlines = pdf.context.obj({ Type: 'Outlines', Count: 1 })
  const outlineRef = pdf.context.register(outlines)
  const item = pdf.context.obj({ Title: PDFString.of('Page Two'), Parent: outlineRef, Dest: [secondPage.ref, PDFName.of('Fit')] })
  const itemRef = pdf.context.register(item)
  outlines.set(PDFName.of('First'), itemRef)
  outlines.set(PDFName.of('Last'), itemRef)
  pdf.catalog.set(PDFName.of('Outlines'), outlineRef)
  const form = pdf.getForm()
  form.createTextField('contact.name').addToPage(pdf.getPages()[0], { x: 48, y: 700, width: 220, height: 24 })
  form.createCheckBox('consent').addToPage(pdf.getPages()[0], { x: 48, y: 650, width: 18, height: 18 })
  const radio = form.createRadioGroup('plan'); radio.addOptionToPage('basic', pdf.getPages()[0], { x: 48, y: 610, width: 18, height: 18 }); radio.addOptionToPage('pro', pdf.getPages()[0], { x: 100, y: 610, width: 18, height: 18 })
  const dropdown = form.createDropdown('region'); dropdown.addOptions(['north', 'south']); dropdown.addToPage(pdf.getPages()[0], { x: 48, y: 560, width: 160, height: 24 })
  output = { bytes: Buffer.from(await pdf.save()).toString('base64') }
} else if (input.mode === 'inspect') output = await inspectPdf(bytes)
else if (input.mode === 'patch') { const result = await patchPdfWithReceipt(bytes, input.operations, input.sha256); output = { bytes: Buffer.from(result.bytes).toString('base64'), sha256: result.sha256 } }
else throw new Error('unknown mode')
process.stdout.write(JSON.stringify(output))
`], { cwd: engine, input: JSON.stringify({ mode, bytes: bytes.toString('base64'), operations, sha256: createHash('sha256').update(bytes).digest('hex') }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `PDF bridge exited ${result.status}`)
  return JSON.parse(result.stdout)
}

const sourceBytes = Buffer.from(runBridge('create', Buffer.alloc(0)).bytes, 'base64')
const sourceSha = createHash('sha256').update(sourceBytes).digest('hex')
const sourceModel = runBridge('inspect', sourceBytes)
let savedBytes
let savePayload
let readOnly = false
// Prefer the production build: it has no Vite hot-reload WebSocket transport.
const production = process.env.PDF_DRAW_SMOKE_PRODUCTION !== '0'
const server = production
  ? spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  : spawn(process.execPath, ['--input-type=module', '-e', `import { createServer } from 'vite'; const server = await createServer({ server: { host: '127.0.0.1', port: ${port}, strictPort: true, hmr: false } }); await server.listen()`], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()) })
  await page.route('**/reports/v1/native/fixture-pdf/*/api/context', route => { const revision = route.request().url().includes('/1/api/') ? 1 : 2; const bytes = revision === 1 ? sourceBytes : savedBytes; return route.fulfill({ json: {
    context: { documentId: 'fixture-pdf', format: 'pdf', revision, parentRevision: revision === 1 ? null : 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'fixture.pdf', size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), mediaType }, origin: 'upload' },
    csrfToken: 'fixture-csrf', capabilities: { pdf_editor: true }, editingEnabled: !readOnly,
  } }) })
  await page.route('**/reports/v1/native/fixture-pdf/*/api/file', route => route.fulfill({ body: route.request().url().includes('/1/api/') ? sourceBytes : savedBytes, contentType: mediaType }))
  await page.route('**/reports/v1/native/fixture-pdf/*/api/preview', route => { const model = route.request().url().includes('/1/api/') ? sourceModel : runBridge('inspect', savedBytes); return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model, appliedOperationIndices: [], skippedOperations: [] } }) })
  await page.route('**/reports/v1/native/fixture-pdf/1/api/save', async route => {
    savePayload = route.request().postDataJSON()
    const patched = runBridge('patch', sourceBytes, savePayload.operations)
    savedBytes = Buffer.from(patched.bytes, 'base64')
    const sha256 = createHash('sha256').update(savedBytes).digest('hex')
    await route.fulfill({ json: { documentId: 'fixture-pdf', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { pdf: { downloadUrl: '/fixture-download.pdf', size: savedBytes.length, sha256 } },
      editor: { openUrl: '/reports/v1/native/fixture-pdf/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/fixture-download.pdf', route => route.fulfill({ body: savedBytes, contentType: mediaType }))
  await page.route(/\/reports\/v1\/native\/fixture-pdf\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/1`)
  try { await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 }) }
  catch { throw new Error(JSON.stringify({ url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1200), pageErrors })) }
  try { await page.waitForFunction(() => document.querySelector('[aria-label="contact.name"]') && document.querySelector('[aria-label="region"]'), null, { timeout: 8000 }) }
  catch { throw new Error(JSON.stringify({ body: (await page.locator('body').innerText()).slice(0, 1600), pageErrors })) }
  // 固定源 Annotate ▸ Draw Tools：矩形、椭圆、箭头、手绘在页面拖动绘制，颜色取标注调色板，保存后写入 PDF 批注。
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('fixture-pdf'))?.[1] ?? '{"operations":[]}').operations)
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  const content = page.locator('.pdf-page').first().locator('.pdf-page-content')
  await content.scrollIntoViewIfNeeded()
  const drag = async (shape, points) => {
    await page.locator(`[data-pdf-draw-shape="${shape}"]`).click()
    assert.equal(await page.locator(`[data-pdf-draw-shape="${shape}"]`).getAttribute('aria-pressed'), 'true')
    const box = await content.boundingBox()
    const at = ([x, y]) => [box.x + box.width * x, box.y + box.height * y]
    await page.mouse.move(...at(points[0])); await page.mouse.down()
    for (const point of points.slice(1)) await page.mouse.move(...at(point), { steps: 4 })
    await page.mouse.up()
  }
  await drag('rect', [[0.55, 0.55], [0.8, 0.7]])
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 1, null, { timeout: 30000 })
  await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.color"]').selectOption('blue')
  await drag('ellipse', [[0.55, 0.75], [0.8, 0.9]])
  await drag('arrow', [[0.1, 0.8], [0.4, 0.9]])
  await drag('ink', [[0.1, 0.6], [0.2, 0.65], [0.3, 0.6], [0.4, 0.7]])
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 4, null, { timeout: 30000 })
  // 多边形：逐点点击，双击完成；插入符号：单击放置。
  await page.locator('[data-pdf-draw-shape="polygon"]').click()
  const clickAt = async ([x, y], options) => { const box = await content.boundingBox(); await page.mouse.click(box.x + box.width * x, box.y + box.height * y, options) }
  await clickAt([0.45, 0.62]); await clickAt([0.52, 0.62])
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('已放置 2 个顶点'))
  await clickAt([0.48, 0.72], { clickCount: 2 })
  await page.locator('[data-pdf-draw-shape="caret"]').click()
  await clickAt([0.3, 0.5])
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 6, null, { timeout: 30000 })
  // 编辑链接：拖出区域后在对话框中填写网址或页码（二选一，不安全协议被拒绝）。
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  const addLink = async (from, to, fill) => {
    // 工具保持激活（与固定源一致，再点一次为关闭），只在未激活时点击。
    if (await page.locator('[data-pdf-draw-shape="link"]').getAttribute('aria-pressed') !== 'true') await page.locator('[data-pdf-draw-shape="link"]').click()
    const box = await content.boundingBox()
    await page.mouse.move(box.x + box.width * from[0], box.y + box.height * from[1]); await page.mouse.down()
    await page.mouse.move(box.x + box.width * to[0], box.y + box.height * to[1], { steps: 3 }); await page.mouse.up()
    await page.locator('.pdf-link-dialog').waitFor({ state: 'visible' })
    await fill()
    await page.locator('.pdf-link-dialog').getByRole('button', { name: '确定' }).click()
  }
  await addLink([0.45, 0.3], [0.75, 0.35], async () => {
    await page.getByLabel('链接网址').fill('javascript:alert(1)')
    await page.locator('.pdf-link-dialog').getByRole('button', { name: '确定' }).click()
    assert.match(await page.locator('.pdf-link-dialog [role=alert]').textContent(), /http\/https\/mailto/)
    await page.getByLabel('链接网址').fill('www.example.com/report')
  })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 7, null, { timeout: 30000 })
  await addLink([0.45, 0.4], [0.75, 0.45], async () => page.getByLabel('链接页码').fill('2'))
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 8, null, { timeout: 30000 })
  // 插入图像：选择 PNG 后在页面上拖出区域，保存为 Stamp 批注。
  const pngBytes = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64')
  await page.locator('input[aria-label="选择要插入的图像"]').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: pngBytes })
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('已选择图像 logo.png'))
  {
    const box = await content.boundingBox()
    await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.15); await page.mouse.down()
    await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.22, { steps: 3 }); await page.mouse.up()
  }
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 9, null, { timeout: 30000 })
  // 签名（固定源 SignatureDialog）：手写笔迹放置为 Ink；键入签名栅格化后放置为图像。
  const placeSignature = async (from, to) => {
    const box = await content.boundingBox()
    await page.mouse.move(box.x + box.width * from[0], box.y + box.height * from[1]); await page.mouse.down()
    await page.mouse.move(box.x + box.width * to[0], box.y + box.height * to[1], { steps: 3 }); await page.mouse.up()
  }
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.annotate.signature.sign"]').click()
  const pad = page.locator('.pdf-sign-pad')
  const padBox = await pad.boundingBox()
  await page.mouse.move(padBox.x + 40, padBox.y + 100); await page.mouse.down()
  for (const [x, y] of [[90, 40], [140, 110], [200, 50], [260, 100]]) await page.mouse.move(padBox.x + x * padBox.width / 480, padBox.y + y * padBox.height / 160, { steps: 3 })
  await page.mouse.up()
  await page.locator('.pdf-sign-dialog').getByRole('button', { name: '确定' }).click()
  await placeSignature([0.62, 0.15], [0.9, 0.22])
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 10, null, { timeout: 30000 })
  await page.locator('[data-source-command-id="genoffice.pdf.annotate.signature.sign"]').click()
  await page.locator('.pdf-sign-dialog').getByRole('button', { name: '键入' }).click()
  await page.getByLabel('键入签名').fill('张三 Zhang')
  await page.locator('.pdf-sign-dialog').getByRole('button', { name: '确定' }).click()
  await placeSignature([0.62, 0.24], [0.9, 0.29])
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 11, null, { timeout: 30000 })
  // 测量（固定源 measure.ts + MeasureScaleDialog）：首条线为参考线标定比例，之后按会话比例自动写标签；再次点击工具 = 重新标定，取消丢弃参考线。
  await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.color"]').selectOption('green')
  const measureLine = async (from, to) => {
    const box = await content.boundingBox()
    await page.mouse.move(box.x + box.width * from[0], box.y + box.height * from[1]); await page.mouse.down()
    await page.mouse.move(box.x + box.width * to[0], box.y + box.height * to[1], { steps: 3 }); await page.mouse.up()
  }
  await page.locator('[data-pdf-draw-shape="measure"]').click()
  assert.equal(await page.locator('[data-pdf-draw-shape="measure"]').getAttribute('aria-pressed'), 'true')
  await measureLine([0.1, 0.4], [0.4, 0.4])
  await page.locator('.pdf-measure-dialog').waitFor({ state: 'visible' })
  assert.equal(await page.getByLabel('测量单位').inputValue(), 'm')
  await page.getByLabel('参考线实际长度').fill('0')
  await page.locator('.pdf-measure-dialog').getByRole('button', { name: '确定' }).click()
  assert.match(await page.locator('.pdf-measure-dialog [role=alert]').textContent(), /大于 0/)
  await page.getByLabel('参考线实际长度').fill('3'); await page.getByLabel('测量单位').fill('米')
  await page.locator('.pdf-measure-dialog').getByRole('button', { name: '确定' }).click()
  assert.match(await page.locator('.pdf-measure-dialog [role=alert]').textContent(), /英文/)
  await page.getByLabel('测量单位').fill('m')
  await page.locator('.pdf-measure-dialog').getByRole('button', { name: '确定' }).click()
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 12, null, { timeout: 30000 })
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('测量比例已标定：1 m ='))
  await measureLine([0.1, 0.46], [0.25, 0.46])
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 13, null, { timeout: 30000 })
  assert.equal(await page.locator('.pdf-measure-dialog').isVisible(), false)
  await page.locator('[data-pdf-draw-shape="measure"]').click()
  assert.equal(await page.locator('[data-pdf-draw-shape="measure"]').getAttribute('aria-pressed'), 'true')
  assert.match(await page.locator('.pdf-editor-message').textContent(), /重新标定/)
  await measureLine([0.1, 0.52], [0.3, 0.52])
  await page.locator('.pdf-measure-dialog').waitFor({ state: 'visible' })
  await page.locator('.pdf-measure-dialog').getByRole('button', { name: '取消' }).click()
  assert.equal((await readDraft()).filter(op => op.shape === 'measure').length, 2)
  assert.deepEqual(await page.locator('[data-pdf-measure-label]').allTextContents(), ['3.00 m', '1.50 m'])
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  // 水印与页眉页脚（固定源 StampDialog）：水印文字 + 默认页码，按当前页序渲染位图覆盖全部页面。
  await page.locator('[data-source-command-id="genoffice.pdf.edit.objects.watermark"]').click()
  await page.locator('.pdf-stamp-dialog').waitFor({ state: 'visible' })
  assert.equal(await page.getByLabel('页脚居中显示页码（第 n / 共 N 页）').isChecked(), true)
  await page.getByLabel('水印文字').fill('机密 Confidential')
  await page.locator('.pdf-stamp-dialog').getByRole('button', { name: '确定' }).click()
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-stamps [data-pdf-stamp]').length >= 2, null, { timeout: 30000 })
  const drafted = await readDraft()
  const stampsOp = drafted.at(-1)
  assert.equal(stampsOp.kind, 'setStamps')
  assert.equal(stampsOp.watermark.text, '机密 Confidential')
  assert.equal(stampsOp.headerFooter.pageNumber, true)
  assert.deepEqual([...new Set(stampsOp.stamps.map(stamp => stamp.pageId))], sourceModel.pages.map(item => item.pageId))
  // 设置水印后不能再删页（页码依赖页面结构）
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click()
  await page.waitForFunction(() => document.querySelector('.pdf-editor-message')?.textContent?.includes('已设置水印/页眉页脚'))
  assert.equal((await readDraft()).length, drafted.length)
  assert.deepEqual(drafted.slice(0, 11).map(op => op.shape), ['rect', 'ellipse', 'arrow', 'ink', 'polygon', 'caret', 'link', 'link', 'image', 'ink', 'image'])
  assert.deepEqual(drafted[9].color, [0.15, 0.15, 0.15])
  assert.deepEqual(drafted.slice(11, 13).map(op => [op.shape, op.label, op.color]), [['measure', '3.00 m', [0.13, 0.65, 0.35]], ['measure', '1.50 m', [0.13, 0.65, 0.35]]])
  assert.ok(drafted[9].paths[0].length >= 10)
  assert.equal(drafted[6].url, 'https://www.example.com/report')
  assert.equal(drafted[7].destPage, 2)
  assert.equal(drafted[4].vertices.length, 3)
  assert.ok(drafted.slice(0, 8).every(op => op.kind === 'addDrawing' && op.pageId === sourceModel.pages[0].pageId && op.width === 2))
  assert.ok(drafted.find(op => op.shape === 'ink').paths[0].length >= 8)
  // 固定源 DRAW_COLORS：默认红色，切换后为蓝色
  assert.deepEqual(drafted.slice(0, 6).map(op => op.color), [[0.86, 0.22, 0.18], ...Array(5).fill([0.17, 0.4, 1])])
  if (process.env.PDF_DRAW_SCREENSHOT) await page.screenshot({ path: process.env.PDF_DRAW_SCREENSHOT })
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.equal((await readDraft()).length, drafted.length - 1)
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); assert.deepEqual(await readDraft(), drafted)
  await page.reload(); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  assert.deepEqual(await readDraft(), drafted)
  await page.waitForFunction(() => document.querySelectorAll('.pdf-pending-drawings [data-pdf-drawing]').length === 13, null, { timeout: 30000 })
  await page.locator('[data-action="save"]').click()
  try { await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 }) }
  catch { if (process.env.PDF_DRAW_SCREENSHOT) await page.screenshot({ path: process.env.PDF_DRAW_SCREENSHOT + '.fail.png' }); throw new Error(JSON.stringify({ saveDisabled: await page.locator('[data-action="save"]').isDisabled(), saveTitle: await page.locator('[data-action="save"]').getAttribute('title'), saved: !!savePayload, label: await page.locator('.save-state-label').textContent(), status: await page.locator('.pdf-editor-message').textContent(), pageErrors })) }
  assert.deepEqual(savePayload.operations, drafted)
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloadedBytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.deepEqual(downloadedBytes, savedBytes)
  if (process.env.PDF_DRAW_OUTPUT) await writeFile(process.env.PDF_DRAW_OUTPUT, downloadedBytes)
  // 独立 pypdf 回读：第 1 页新增 Square/Circle/Line/Ink 批注，颜色与草稿一致，原有便签/表单控件保留。
  const readback = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); print(json.dumps([[str(a.get_object().get("/Subtype")),[round(float(v),2) for v in (a.get_object().get("/C") or [])],str(a.get_object().get("/Contents") or "")] for a in (r.pages[0].get("/Annots") or [])]+[["page2",[str(a.get_object().get("/Subtype")) for a in (r.pages[1].get("/Annots") or [])]]]))'], { input: downloadedBytes, encoding: 'utf8' })
  if (readback.status !== 0) throw new Error(readback.stderr)
  const annots = JSON.parse(readback.stdout)
  const drawn = annots.filter(([subtype, color]) => ['/Square', '/Circle', '/Line', '/Ink', '/Polygon', '/Caret'].includes(subtype) && !(subtype === '/Ink' && JSON.stringify(color) === '[0.15,0.15,0.15]') && JSON.stringify(color) !== '[0.13,0.65,0.35]')
  assert.deepEqual(annots.filter(([subtype, color]) => subtype === '/Line' && JSON.stringify(color) === '[0.13,0.65,0.35]').map(item => item[2]), ['3.00 m', '1.50 m'])
  assert.deepEqual(drawn.map(([subtype]) => subtype).sort(), ['/Caret', '/Circle', '/Ink', '/Line', '/Polygon', '/Square'])
  const subtypeOf = { rect: '/Square', ellipse: '/Circle', arrow: '/Line', ink: '/Ink', polygon: '/Polygon', caret: '/Caret' }
  assert.equal(annots.filter(([subtype]) => subtype === '/Link').length, 2)
  assert.equal(annots.filter(([subtype]) => subtype === '/Stamp').length, 2)
  assert.equal(annots.filter(([subtype]) => subtype === '/Ink').length, 2)
  const xobjects = spawnSync(`${repo}/.venv/bin/python`, ['-c', 'import json,sys; from io import BytesIO; from pypdf import PdfReader; r=PdfReader(BytesIO(sys.stdin.buffer.read())); print(json.dumps([len((p.get("/Resources") or {}).get("/XObject") or {}) for p in r.pages]))'], { input: downloadedBytes, encoding: 'utf8' })
  if (xobjects.status !== 0) throw new Error(xobjects.stderr)
  assert.ok(JSON.parse(xobjects.stdout).every(count => count >= 2), `every page carries watermark + footer images: ${xobjects.stdout}`)
  for (const op of drafted.slice(0, 6)) assert.deepEqual(drawn.find(([subtype]) => subtype === subtypeOf[op.shape])[1], op.color.map(value => Math.round(value * 100) / 100))
  assert.ok(annots.filter(([subtype]) => subtype === '/Widget').length >= 4, 'form widgets retained')
  assert.deepEqual(annots.at(-1), ['page2', ['/Text']])
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  assert.deepEqual(pageErrors.filter(message => !/WebSocket|\[vite\]/.test(message)), [])
  console.log(JSON.stringify({ ok: true, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), drawn, productionBuild: production }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
