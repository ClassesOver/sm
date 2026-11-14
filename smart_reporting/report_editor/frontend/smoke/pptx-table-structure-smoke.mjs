import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { inspectPptxStructureLayout } from './office-pptx-structure-layout.mjs'

const frontend = process.cwd()
const staticRoot = resolve(frontend, '../static')
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestSha256 = sha(await readFile(resolve(staticRoot, '.vite/manifest.json')))
if (process.env.PPTX_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.PPTX_EXPECTED_MANIFEST_SHA256)
const chunks = new Map(), pendingAssets = []
const repo = new URL('../../../', `file://${frontend}/`).pathname
const port = Number(process.env.PPTX_SMOKE_PORT ?? 4209)
const baseUrl = `http://127.0.0.1:${port}`
const runPython = input => {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64, json, sys
from io import BytesIO
from pptx import Presentation
from pptx.util import Inches
from smart_reporting.report_editor.native_office import inspect_office, patch_office
payload = json.load(sys.stdin)
if payload['mode'] == 'create':
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = 'Untouched source object'
    table = slide.shapes.add_table(2, 3, Inches(1), Inches(3), Inches(6), Inches(2)).table
    for ri in range(2):
        for ci in range(3):
            cell = table.cell(ri, ci); cell.text = f'R{ri}C{ci}'
            cell.text_frame.paragraphs[0].runs[0].font.bold = True
    stream = BytesIO(); presentation.save(stream)
    print(base64.b64encode(stream.getvalue()).decode())
elif payload['mode'] == 'inspect':
    print(json.dumps(inspect_office('pptx', base64.b64decode(payload['bytes']))))
elif payload['mode'] == 'patch':
    content = base64.b64decode(payload['bytes'])
    edited = patch_office('pptx', content, payload['operations'])
    print(base64.b64encode(edited).decode())
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}

const sourceBytes = Buffer.from(runPython({ mode: 'create' }), 'base64')
const sourceIdentity = createHash('sha256').update(sourceBytes).digest('hex')
const sourceSha = sourceIdentity
let activeBytes = sourceBytes
let activeSha = sourceSha
let activeRevision = 1
const inspected = JSON.parse(runPython({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
let savedBytes
const previewPayloads = []
let lastTree
let savePayload
let saveReceipt
const saveAttempts = []
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 120; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
  const pageErrors = []
  const failedResponses = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('response', response => { if (response.status() >= 400) failedResponses.push({ status: response.status(), url: response.url() }) })
  page.on('response', response => {
    if (!new URL(response.url()).pathname.endsWith('.js')) return
    pendingAssets.push((async () => {
      const bytes = await response.body(), path = new URL(response.url()).pathname.replace('/reports/v1/editor/assets/', '')
      const disk = await readFile(resolve(staticRoot, path))
      assert.equal(sha(bytes), sha(disk), path)
      chunks.set(path, { path, size: bytes.length, sha256: sha(bytes) })
    })())
  })
  await page.route('**/favicon.ico', route => route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg"/>' }))

  await page.route('**/reports/v1/native/fixture-pptx/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'fixture-pptx', format: 'pptx', revision: activeRevision, parentRevision: activeRevision === 1 ? null : 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'fixture.pptx', size: activeBytes.length, sha256: activeSha, mediaType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }, origin: 'upload' },
    csrfToken: 'fixture-csrf', capabilities: { pptx_editor: true }, editingEnabled: true,
  } }))
  await page.route('**/reports/v1/native/fixture-pptx/*/api/file', route => route.fulfill({ body: activeBytes, contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }))
  await page.route('**/reports/v1/native/fixture-pptx/*/api/preview.pdf*', route => route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' }))
  await page.route('**/reports/v1/native/fixture-pptx/*/api/preview', async route => {
    const payload = route.request().postDataJSON()
    assert.equal(payload.expectedSha256, activeSha)
    const operations = payload.operations
    const receipt = await new Promise((resolve, reject) => {
      const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `import base64,json,sys\nfrom smart_reporting.report_editor.native_office import inspect_office,patch_office\np=json.load(sys.stdin); b=base64.b64decode(p['source']); b=patch_office('pptx',b,p['operations']) if p['operations'] else b; print(json.dumps({'model':inspect_office('pptx',b),'draftSha256':__import__('hashlib').sha256(b).hexdigest()}))`], {
        cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify({ source: activeBytes.toString('base64'), operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024,
      })
      result.status === 0 ? resolve(JSON.parse(result.stdout)) : reject(new Error(result.stderr))
    })
    await route.fulfill({ json: { sourceSha256: activeSha, draftSha256: receipt.draftSha256, model: receipt.model } })
  })
  await page.route('**/reports/v1/native/fixture-pptx/*/api/render-tree', async route => {
    const payload = route.request().postDataJSON(); previewPayloads.push(payload)
    assert.equal(payload.expectedSha256, activeSha)
    const operations = payload.operations
    const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `import base64,json,sys\nfrom smart_reporting.report_editor.native_office import patch_office\nfrom smart_reporting.report_editor.slides_render import render_pptx_tree\np=json.load(sys.stdin); b=base64.b64decode(p['source']); b=patch_office('pptx',b,p['operations']) if p['operations'] else b; print(json.dumps(render_pptx_tree(b)))`], {
      cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify({ source: activeBytes.toString('base64'), operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024,
    })
    if (result.status !== 0) return route.fulfill({ status: 500, body: result.stderr })
    lastTree = JSON.parse(result.stdout); await route.fulfill({ json: lastTree })
  })
  await page.route('**/reports/v1/native/fixture-pptx/1/api/save', async route => {
    savePayload = route.request().postDataJSON()
    assert.equal(savePayload.expectedSha256, sourceIdentity)
    saveAttempts.push(savePayload)
    savedBytes = Buffer.from(runPython({ mode: 'patch', bytes: sourceBytes.toString('base64'), operations: savePayload.operations }), 'base64')
    saveReceipt = { documentId: 'fixture-pptx', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { pptx: { downloadUrl: '/fixture-download.pptx', size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } },
      editor: { openUrl: '/reports/v1/native/fixture-pptx/2' }, validation: { ok: true, issues: [] } }
    await route.fulfill({ json: saveReceipt })
  })
  await page.route('**/fixture-download.pptx', route => route.fulfill({ body: savedBytes, contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }))
  await page.addInitScript(() => {
    if (location.origin !== 'null') history.replaceState(null, '', `/reports/v1/native/fixture-pptx/${new URL(location.href).searchParams.get('smokeRevision') === '2' ? 2 : 1}`)
  })
  await page.route(/\/reports\/v1\/native\/fixture-pptx\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
  await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
  try { await page.locator('.slides-native-ribbon').waitFor({ timeout: 60000 }) }
  catch { throw new Error(JSON.stringify({ url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1200), pageErrors, failedResponses })) }
  try { await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 }) }
  catch { throw new Error(JSON.stringify({ phase: 'canvas', body: (await page.locator('body').innerText()).slice(-2500), pageErrors, failedResponses })) }
  await page.waitForFunction(() => document.querySelector('.canvas-status')?.textContent.includes('点击对象选择'))

  const target=inspected.slides[0].elements.find(el=>el.type==='table')
  assert.equal(target.tableStructureEditable,true)
  await page.locator('#object-select').selectOption(target.id)
  await page.locator('[data-ribbon-tab="tableDesign"]').click()
  const structure=page.locator('[data-command="tableStructure"]')
  const readDraft=()=>page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.includes('fixture-pptx'))?.[1]??'{"operations":[]}').operations)
  let layout
  if (process.env.PPTX_STRUCTURE_VIEWPORTS) {
    const output = resolve(process.env.PPTX_SMOKE_EVIDENCE_DIR)
    await mkdir(output, { recursive: true })
    layout = await inspectPptxStructureLayout(page, { output, viewports: process.env.PPTX_STRUCTURE_VIEWPORTS, draft: readDraft })
    await page.setViewportSize({ width: 1440, height: 1000 })
  }
  await structure.click()
  const dialog=page.getByRole('dialog',{name:'调整表格行列'})
  await dialog.waitFor({state:'visible'})
  await dialog.getByLabel('参考行',{exact:true}).selectOption('1')
  await dialog.getByRole('button',{name:'在下方插入行',exact:true}).click()
  const expected=await readDraft()
  assert.deepEqual(expected[0].tableStructures,[{slideIndex:0,elementId:target.id,kind:'insert-row',index:1,before:false}])
  assert.equal(await structure.isDisabled(),true)
  assert.equal(await page.getByLabel('表格单元格 2 行 3 列',{exact:true}).isDisabled(),true)
  await page.locator('[data-source-action="onUndo"]').click();assert.deepEqual(await readDraft(),[])
  assert.equal(await structure.isEnabled(),true)
  await page.locator('[data-source-action="onRedo"]').click();assert.deepEqual(await readDraft(),expected)
  await page.reload();await page.locator('.slides-native-ribbon').waitFor();await page.locator('#object-select').selectOption(target.id)
  assert.equal(await page.locator('[data-command="tableStructure"]').isDisabled(),true)
  if(process.env.PPTX_NEW_SLIDE_SCREENSHOT) await page.screenshot({path:process.env.PPTX_NEW_SLIDE_SCREENSHOT})
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存',null,{timeout:60000})
  assert.deepEqual(savePayload.operations,expected)
  const url=await page.locator('[data-action="pptx-download"]').getAttribute('href')
  const downloaded=Buffer.from(await page.evaluate(async url=>[...new Uint8Array(await(await fetch(url)).arrayBuffer())],url))
  assert.deepEqual(downloaded,savedBytes)
  const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import sys,json
from io import BytesIO
from pptx import Presentation
p=Presentation(BytesIO(sys.stdin.buffer.read()));shape=p.slides[0].shapes[1];t=shape.table
assert len(t.rows)==3 and len(t.columns)==3
assert t.cell(0,0).text=='R0C0' and t.cell(1,2).text=='R1C2'
assert all(t.cell(2,c).text=='' for c in range(3))
assert shape.height==3*914400
assert p.slides[0].shapes[0].text=='Untouched source object'
print(json.dumps({'rows':len(t.rows),'columns':len(t.columns),'height':shape.height}))
`],{input:downloaded,encoding:'utf8'})
  assert.equal(result.status,0,result.stderr)
  activeBytes=savedBytes;activeSha=createHash('sha256').update(savedBytes).digest('hex');activeRevision=2
  await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html?smokeRevision=2`);await page.locator('.slides-native-ribbon').waitFor()
  const model=JSON.parse(runPython({mode:'inspect',bytes:downloaded.toString('base64')})),fresh=model.slides[0].elements.find(el=>el.type==='table')
  await page.locator('#object-select').selectOption(fresh.id)
  assert.equal(await page.locator('[data-table-cell]').count(),9)
  assert.equal(await page.locator('[data-command="tableStructure"]').isEnabled(),true)
  assert.deepEqual(pageErrors,[]);assert.deepEqual(failedResponses,[])
  await Promise.all(pendingAssets)
  assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))), manifestSha256)
  const receipt={ok:true,sourceSha,outputSha:activeSha,independent:JSON.parse(result.stdout),operation:expected[0],productionBuild:true,apiRoutesAreFixtures:true,manifestSha256,runtimeJavaScript:[...chunks.values()],layout,pageErrors,failedResponses}
  if(process.env.PPTX_SMOKE_EVIDENCE_DIR){const directory=resolve(process.env.PPTX_SMOKE_EVIDENCE_DIR);await mkdir(directory,{recursive:true});await writeFile(join(directory,'source.pptx'),sourceBytes);await writeFile(join(directory,'downloaded.pptx'),downloaded);await writeFile(join(directory,'evidence.json'),JSON.stringify(receipt,null,2))}
  console.log(JSON.stringify(receipt))
} finally {await browser?.close();server.kill('SIGTERM')}
