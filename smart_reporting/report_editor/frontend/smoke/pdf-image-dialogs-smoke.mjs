import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import AxeBuilder from '@axe-core/playwright'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const engine = `${repo}/smart_reporting/reporting/pdf_engine`
const port = Number(process.env.PDF_IMAGE_BAKE_SMOKE_PORT ?? 4213)
const baseUrl = `http://127.0.0.1:${port}`
const mediaType = 'application/pdf'
const bakeMode = process.env.PDF_IMAGE_BAKE_MODE ?? 'crop'
assert.ok(['crop', 'cutout'].includes(bakeMode), `未知像素编辑模式 ${bakeMode}`)
const runBridge = (mode, bytes, operations = []) => {
  if (mode !== 'create') {
    const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt,read_pdf_image_pixels
p=json.load(sys.stdin);b=base64.b64decode(p['bytes'])
if p['mode']=='inspect':print(json.dumps(inspect_pdf(b)))
elif p['mode']=='pixels':print(json.dumps(read_pdf_image_pixels(b,p['operations'])))
else:
 r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify({ mode, bytes: bytes.toString('base64'), operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
    if (result.status !== 0) throw new Error(result.stderr)
    return JSON.parse(result.stdout)
  }
  const result = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', `
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
import { PDFDocument, PDFName, PDFString, StandardFonts } from 'pdf-lib'
import { inspectPdf, patchPdfWithReceipt } from './bridge/operations.ts'
const input = JSON.parse(readFileSync(0, 'utf8'))
const bytes = Buffer.from(input.bytes, 'base64')
let output
if (input.mode === 'create') {
  const pdf = await PDFDocument.create()
  const font = await pdf.embedFont(StandardFonts.Helvetica)
  const page = pdf.addPage([612, 792])
  page.drawText('Image bake fixture', { x: 72, y: 720, size: 20, font })
  // 独立绿色图像必须保留；目标图像用四象限区分水平与竖直翻转。
  const solid = (r, g, b) => { const { deflateSync } = require('node:zlib'); const raw = Buffer.from([0, r, g, b, r, g, b, 0, r, g, b, r, g, b]); const crc = buf => { let c = ~0; for (const x of buf) { c ^= x; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1 } return ~c >>> 0 }; const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const body = Buffer.concat([Buffer.from(t), d]); const s = Buffer.alloc(4); s.writeUInt32BE(crc(body)); return Buffer.concat([l, body, s]) }; const h = Buffer.alloc(13); h.writeUInt32BE(2, 0); h.writeUInt32BE(2, 4); h[8] = 8; h[9] = 2; return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', h), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]) }
  const split = (() => { const { deflateSync } = require('node:zlib'); const raw = Buffer.concat(Array.from({ length: 8 }, (_, y) => Buffer.from([0, ...Array.from({ length: 8 }, (_, x) => x>=2&&x<6&&y>=2&&y<6 ? [15,15,15] : (y < 4 ? (x < 4 ? [220, 30, 30] : [31, 79, 216]) : (x < 4 ? [230, 180, 20] : [150, 40, 170]))).flat()]))); const crc = buf => { let c = ~0; for (const x of buf) { c ^= x; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1 } return ~c >>> 0 }; const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const body = Buffer.concat([Buffer.from(type), data]); const sum = Buffer.alloc(4); sum.writeUInt32BE(crc(body)); return Buffer.concat([len, body, sum]) }; const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(8, 0); ihdr.writeUInt32BE(8, 4); ihdr[8] = 8; ihdr[9] = 2; return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]) })()
  page.drawImage(await pdf.embedPng(split), { x: 72, y: 420, width: 200, height: 150 })
  page.drawImage(await pdf.embedPng(solid(30, 160, 60)), { x: 340, y: 420, width: 150, height: 150 })
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
let saveCount=0
const pixelRequests=[]
let readOnly = false
const shotDir = process.env.PDF_IMAGE_BAKE_SHOTS ?? '/tmp'
await mkdir(shotDir, { recursive: true })
const staticRoot = process.env.PDF_IMAGE_BAKE_STATIC_ROOT
await writeFile(resolve(shotDir, 'source.pdf'), sourceBytes, { flag: 'wx' })
// Prefer the production build: it has no Vite hot-reload WebSocket transport.
const production = process.env.PDF_IMAGE_BAKE_SMOKE_PRODUCTION !== '0'
const server = production
  ? spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort', ...(staticRoot ? ['--outDir', staticRoot] : [])], { cwd: frontend, stdio: 'ignore' })
  : spawn(process.execPath, ['--input-type=module', '-e', `import { createServer } from 'vite'; const server = await createServer({ server: { host: '127.0.0.1', port: ${port}, strictPort: true, hmr: false } }); await server.listen()`], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
  const page = await context.newPage()
  const pageErrors = []
  const assetChecks = []
  const assets = []
  if (staticRoot) page.on('response', response => {
    const pathname = new URL(response.url()).pathname
    const prefix = '/reports/v1/editor/assets/'
    if (response.status() !== 200 || !pathname.startsWith(prefix) || !/\.(js|css)$/.test(pathname)) return
    assetChecks.push((async () => {
      const relative = pathname.slice(prefix.length)
      const actual = createHash('sha256').update(await response.body()).digest('hex')
      const expected = createHash('sha256').update(await readFile(resolve(staticRoot, relative))).digest('hex')
      assert.equal(actual, expected, relative)
      assets.push({ file: relative, sha256: actual })
    })())
  })
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()) })
  await page.route('**/reports/v1/native/fixture-pdf/*/api/context', route => { const revision = route.request().url().includes('/1/api/') ? 1 : 2; const bytes = revision === 1 ? sourceBytes : savedBytes; return route.fulfill({ json: {
    context: { documentId: 'fixture-pdf', format: 'pdf', revision, parentRevision: revision === 1 ? null : 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'fixture.pdf', size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), mediaType }, origin: 'upload' },
    csrfToken: 'fixture-csrf', capabilities: { pdf_editor: true }, editingEnabled: !readOnly,
  } }) })
  await page.route('**/reports/v1/native/fixture-pdf/*/api/file', route => route.fulfill({ body: route.request().url().includes('/1/api/') ? sourceBytes : savedBytes, contentType: mediaType }))
  await page.route('**/reports/v1/native/fixture-pdf/1/api/image-pixels',route=>{
    const target=route.request().postDataJSON();pixelRequests.push(target)
    assert.equal(route.request().headers()['x-csrf-token'],'fixture-csrf')
    return route.fulfill({json:runBridge('pixels',sourceBytes,target)})
  })
  const previewCalls = []
  await page.route('**/reports/v1/native/fixture-pdf/*/api/preview', route => {
    const { operations } = route.request().postDataJSON()
    if (!operations.length || !route.request().url().includes('/1/api/')) { const model = route.request().url().includes('/1/api/') ? sourceModel : runBridge('inspect', savedBytes); return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model, appliedOperationIndices: [], skippedOperations: [] } }) }
    previewCalls.push(operations)
    const receipt = runBridge('patch', sourceBytes, operations), bytes = Buffer.from(receipt.bytes, 'base64')
    return route.fulfill({ json: { sourceSha256: sourceSha, draftSha256: receipt.sha256, model: runBridge('inspect', bytes), previewDigest: receipt.previewDigest, appliedOperationIndices: receipt.appliedOperationIndices, skippedOperations: receipt.skippedOperations } })
  })
  await page.route('**/reports/v1/native/fixture-pdf/1/api/preview.pdf', route => {
    const receipt = runBridge('patch', sourceBytes, route.request().postDataJSON().operations)
    return route.fulfill({ body: Buffer.from(receipt.bytes, 'base64'), contentType: mediaType, headers: { 'X-Native-Preview-Digest': receipt.previewDigest } })
  })
  await page.route('**/reports/v1/native/fixture-pdf/1/api/save', async route => {
    saveCount++;savePayload = route.request().postDataJSON()
    const patched = runBridge('patch', sourceBytes, savePayload.operations)
    savedBytes = Buffer.from(patched.bytes, 'base64')
    const sha256 = createHash('sha256').update(savedBytes).digest('hex')
    await route.fulfill({ json: { documentId: 'fixture-pdf', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { pdf: { downloadUrl: '/fixture-download.pdf', size: savedBytes.length, sha256 } },
      editor: { openUrl: '/reports/v1/native/fixture-pdf/2' }, validation: { ok: false, issues: [{ code: 'pixel_review_pending', message: '像素编辑专项验收待复核，文件已生成。' }] } } })
  })
  await page.route('**/fixture-download.pdf', route => route.fulfill({ body: savedBytes, contentType: mediaType, headers: { 'Content-Disposition': 'attachment; filename="pixels.pdf"' } }))
  await page.route(/\/reports\/v1\/native\/fixture-pdf\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/1`)
  try { await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 }) }
  catch { throw new Error(JSON.stringify({ url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1200), pageErrors })) }
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  // 编辑 ▸ 编辑图像 ▸ 像素编辑（固定源 flip / crop / opacity 烘焙 → replaceImage）：桥接取图像自身像素，单独保存，先核对实际预览。
  const readDraft = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations)
  const draftLength = n => page.waitForFunction(count => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations.length === count, n)
  const targets = sourceModel.existingImages
  const target = targets.find(item => item.rect[0] === 72)
  assert.ok(target.bakeable, JSON.stringify(target))
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  const openDialog = async () => {
    await page.locator('[data-source-command-id="genoffice.pdf.edit.objects.editImage"]').click()
    const dialog = page.getByRole('dialog', { name: '编辑已有图像', exact: true })
    await dialog.waitFor({ state: 'visible' })
    await dialog.getByLabel('已有图像选择', { exact: true }).selectOption(String(targets.filter(item => item.editable).indexOf(target)))
    return dialog
  }
  const layouts=[]
  for(const viewport of [{width:1440,height:900},{width:640,height:360},{width:390,height:320}]){
    await page.setViewportSize(viewport)
    for(const kind of ['crop','cutout']){
      const parent=await openDialog();await parent.locator('[data-pdf-image-visual='+kind+']').click()
      const nested=page.locator('.pdf-image-source-dialog');await nested.waitFor({state:'visible',timeout:60000})
      await nested.locator('.pdf-modal-actions button.primary:not([disabled])').waitFor({timeout:30000})
      if(kind==='crop'){await nested.getByLabel('可视裁剪裁去左侧百分比').fill('10');await nested.getByLabel('可视裁剪裁去右侧百分比').fill('20')}
      else{await nested.locator('input[type=range]').fill('35');assert.equal(await nested.locator('input[type=range]').inputValue(),'35')}
      const apply=nested.locator('.pdf-modal-actions button.primary');await apply.focus()
      const geometry=await apply.evaluate(node=>{const r=node.getBoundingClientRect();return {hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===node,focused:document.activeElement===node}})
      assert.ok(geometry.hit&&geometry.focused,JSON.stringify({viewport,kind,geometry}))
      await page.screenshot({path:resolve(shotDir,kind+'-'+viewport.width+'x'+viewport.height+'.png')})
      await page.keyboard.press('Escape');await nested.waitFor({state:'detached'})
      assert.deepEqual(await readDraft(),[]);assert.equal(saveCount,0)
      assert.equal(await parent.locator('[data-pdf-image-visual='+kind+']').evaluate(node=>document.activeElement===node),true)
      await parent.getByRole('button',{name:'取消',exact:true}).click()
      layouts.push({viewport,kind,...geometry,cancelNoWrite:true})
    }
  }
  await page.setViewportSize({width:1440,height:900})
  let parent=await openDialog();await parent.locator('[data-pdf-image-visual=crop]').click()
  let nested=page.locator('.pdf-image-source-dialog');await nested.locator('.pdf-modal-actions button.primary:not([disabled])').waitFor({timeout:60000})
  const east=nested.locator('div[style*="cursor: ew-resize"]').first();const handle=await east.boundingBox();assert.ok(handle)
  await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await page.mouse.down();await page.mouse.move(handle.x-80,handle.y+handle.height/2,{steps:8});await page.mouse.up()
  const right=Number(await nested.getByLabel('可视裁剪裁去右侧百分比').inputValue());assert.ok(right>0&&right<100)
  await nested.locator('.pdf-modal-actions button.primary').click();await draftLength(1)
  const gesture=await readDraft();assert.ok(gesture[0].image);assert.ok(gesture[0].rect[2]<target.rect[2])
  await page.locator('[data-pdf-ribbon-tab=home]').click();await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await draftLength(0)
  await page.locator('[data-pdf-ribbon-tab=edit]').click()
  parent=await openDialog();await parent.locator('[data-pdf-image-visual='+bakeMode+']').click()
  nested=page.locator('.pdf-image-source-dialog');await nested.locator('.pdf-modal-actions button.primary:not([disabled])').waitFor({timeout:60000})
  if(bakeMode==='crop'){
    await nested.getByLabel('可视裁剪裁去右侧百分比').fill('50');await page.keyboard.press('Enter')
  }else{await nested.locator('input[type=range]').fill('25');await nested.locator('.pdf-modal-actions button.primary').click()}
  await draftLength(1)
  const staged=await readDraft(),expectedRect=bakeMode==='crop'?[target.rect[0],target.rect[1],target.rect[0]+(target.rect[2]-target.rect[0])/2,target.rect[3]]:target.rect
  assert.deepEqual(staged[0].rect,expectedRect);assert.ok(staged[0].image.startsWith('iVBORw0KGgo'));assert.equal(staged[0].bake,undefined)
  // 撤销 / 重做 / 刷新恢复
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click()
  await draftLength(0)
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click()
  await draftLength(1)
  await page.reload(); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 })
  assert.deepEqual(await readDraft(), staged)
  // 实际预览确认后保存
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  await page.getByRole('button', { name: '校验当前修改', exact: true }).click()
  await page.locator('.pdf-preview-review input[type="checkbox"]').waitFor({ state: 'visible', timeout: 60000 })
  await page.locator('.pdf-preview-review input[type="checkbox"]').check()
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  await page.screenshot({ path: `${shotDir}/bake-preview.png` })
  assert.ok(previewCalls.some(operations => JSON.stringify(operations) === JSON.stringify(staged)))
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
  await page.getByText('已保存修订 2；验收待复核或未通过', { exact: true }).waitFor()
  await page.getByText('像素编辑专项验收待复核，文件已生成。', { exact: false }).waitFor()
  assert.deepEqual(savePayload.operations, staged)
  assert.match(savePayload.confirmedPreviewDigest ?? '', /^[a-f0-9]{64}$/)
  const downloadUrl = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href')
  const downloadedBytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], downloadUrl))
  assert.deepEqual(downloadedBytes, savedBytes)
  const downloading = page.waitForEvent('download')
  await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).click()
  const download = await downloading
  assert.equal(await download.failure(), null)
  await download.saveAs(resolve(shotDir, 'browser-downloaded.pdf'))
  assert.deepEqual(await readFile(resolve(shotDir, 'browser-downloaded.pdf')), savedBytes)
  await writeFile(resolve(shotDir, 'saved-operations.json'), JSON.stringify(savePayload, null, 2))
  const outputPath = process.env.PDF_IMAGE_BAKE_OUTPUT ?? resolve(shotDir, 'downloaded.pdf')
  await writeFile(outputPath, downloadedBytes, { flag: 'wx' })
  const verification=spawnSync(`${repo}/.venv/bin/python`, [resolve(frontend,'smoke/pdf-image-dialogs-verify.py'),resolve(shotDir,'source.pdf'),outputPath,bakeMode],{encoding:'utf8'})
  assert.equal(verification.status,0,verification.stderr)
  const independent=JSON.parse(verification.stdout)
  await writeFile(resolve(shotDir,'independent-fidelity.json'),JSON.stringify(independent,null,2))
  assert.equal(saveCount,1)
  assert.equal(createHash('sha256').update(sourceBytes).digest('hex'), sourceSha)
  const reopened = runBridge('inspect', savedBytes)
  const baked = reopened.existingImages.find(item => Math.abs(item.rect[0] - 72) < .05)
  assert.ok(baked && baked.rect.every((value, index) => Math.abs(value - expectedRect[index]) < .05), 'footprint matches requested crop or original placement')
  await page.goto(`${baseUrl}/reports/v1/native/fixture-pdf/2`); await page.locator('.pdf-ribbon').waitFor({ timeout: 60000 }).catch(async error=>{await writeFile(resolve(shotDir,'reopen-failure.json'),JSON.stringify({url:page.url(),body:await page.locator('body').innerText(),pageErrors},null,2));throw error})
  await page.waitForFunction(() => { const canvas = document.querySelector('.pdf-page canvas'); return canvas && canvas.width > 0 }, null, { timeout: 30000 })
  assert.deepEqual(pageErrors, [])
  await Promise.all(assetChecks)
  if (staticRoot) assert.ok(assets.length > 0, '必须核对实际加载的构建资源')
  const evidence = { ok: true, scope: 'Full editor with explicit HTTP authorization/revision fixtures; real PDF patch, preview, browser download and independent pypdf/PyMuPDF readback; no production database or desktop Office claim', bakeMode, sourceSha, outputSha: createHash('sha256').update(downloadedBytes).digest('hex'), independent, productionBuild: production, staticRoot, engineRoot: process.env.AGENT_REPORTING_PDF_ENGINE_DIR ?? engine, assets, layouts,saveCount,pixelRequests,gesture, pageErrors, validationWarningPreserved: true }
  await writeFile(resolve(shotDir, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ...evidence, assets: assets.length }))
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
