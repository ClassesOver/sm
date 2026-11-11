// 缩放到选区独立真实产品按钮验收：冻结窗格、草稿、保存与修订重开。
// 真实 Chromium + vite 前端 + Playwright 替身 context/file 路由；保存经真实
// Python patch_office（桥接 + 引擎），下载字节再由 openpyxl 独立回读。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { readFile } from 'node:fs/promises'

const frontend = process.cwd()
const repo = new URL('../../../', `file://${frontend}/`).pathname
const port = Number(process.env.WORKBOOK_SMOKE_PORT ?? 4191)
const baseUrl = `http://127.0.0.1:${port}`
const python = (input) => {
 const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();s=b.active;s.title='Summary';s['A1']='kept';s['D5']='=1+2';s.freeze_panes='C3';s.row_dimensions[2].height=40;s.column_dimensions['B'].width=30
 o=BytesIO();b.save(o);print(base64.b64encode(o.getvalue()).decode())
elif p['mode']=='patch':
 from smart_reporting.report_editor.native_office import patch_office
 print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 raw=base64.b64decode(p['bytes']);s=load_workbook(BytesIO(raw)).active;z=ZipFile(BytesIO(raw))
 print(json.dumps({'zoom':s.sheet_view.zoomScale,'freeze':s.freeze_panes,'row2':s.row_dimensions[2].height,'colB':s.column_dimensions['B'].width,'values':[s['A1'].value,s['D5'].value],'parts':{n:base64.b64encode(z.read(n)).decode() for n in z.namelist()}}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(input),encoding:'utf8',maxBuffer:20*1024*1024})
 if(result.status)throw Error(result.stderr);return result.stdout.trim()
}
const sourceBytes = Buffer.from(python({ mode: 'create', case: process.env.WORKBOOK_RIBBON_CASE, totals: process.env.TABLE_RESIZE_TOTALS === '1' }), 'base64')
const sourceSha = createHash('sha256').update(sourceBytes).digest('hex')
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
let savedBytes, savePayload
const server = spawn('./node_modules/.bin/vite', [...(process.env.WORKBOOK_SMOKE_PREVIEW === '1' ? ['preview'] : []), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser
let diagnosticPage
try {
  for (let attempt = 0; attempt < 120; attempt++) { try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, args: ['--disable-features=LocalNetworkAccessChecks'], ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['clipboard-read', 'clipboard-write'] })
  const page = await context.newPage()
  diagnosticPage = page
  const pageErrors = [], assetChecks = []
  page.on('response', response => {
    const name = new URL(response.url()).pathname.split('/').at(-1)
    if (!/^lazy-workbook-(?:main|zoom-selection)-[^/]+\.js$/.test(name)) return
    assetChecks.push((async () => {
      const bytes = await response.body(), local = await readFile(`${frontend}/../static/assets/${name}`)
      const sha256 = createHash('sha256').update(bytes).digest('hex')
      assert.equal(response.status(), 200);assert.equal(sha256,createHash('sha256').update(local).digest('hex'))
      return {name,status:response.status(),sha256,staticMatch:true}
    })())
  })
  page.on('pageerror', error => pageErrors.push(error.message))


  const ctx = { documentId: 'fixture-gui', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
    sourceFile: { path: 'gui.xlsx', size: sourceBytes.length, sha256: sourceSha, mediaType: media }, origin: 'upload' }
  await page.route('**/reports/v1/native/fixture-gui/1/api/context', route => route.fulfill({ json: { context: ctx, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
  await page.route('**/reports/v1/native/fixture-gui/1/api/file', route => route.fulfill({ body: sourceBytes, contentType: media }))
  await page.route('**/reports/v1/native/fixture-gui/1/api/save', async route => {
    savePayload = route.request().postDataJSON()
    savedBytes = Buffer.from(python({ mode: 'patch', bytes: sourceBytes.toString('base64'), operations: savePayload.operations }), 'base64')
    await route.fulfill({ json: { documentId: 'fixture-gui', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { xlsx: { downloadUrl: '/fixture-gui-download.xlsx', size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } },
      editor: { openUrl: '/reports/v1/native/fixture-gui/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/fixture-gui-download.xlsx', route => route.fulfill({ body: savedBytes, contentType: media }))
  await page.route(/\/reports\/v1\/native\/fixture-gui\/1$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
  await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/1'))
  await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
  await page.locator('.workbook-ribbon').waitFor({ timeout: 60000 })
  await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
  const feedback = () => page.locator('.workbook-feedback').innerText()
  const command = async id => { const button = page.locator(`[data-ribbon-command="${id}"]`); assert.equal(await button.isDisabled(), false, `${id} must be enabled`); await button.click() }
  await page.waitForFunction(()=>document.querySelector('.save-state')?.getAttribute('aria-busy')==='false')
  const source=JSON.parse(python({mode:'inspect',bytes:sourceBytes.toString('base64')}))
  const go=async ref=>{await page.locator('[data-ribbon-tab="Home"]').click();await command('goto-open');await page.locator('[data-goto-reference]').fill(ref);await page.locator('.workbook-ribbon-goto-dialog .workbook-ribbon-format-apply').click();await page.locator('[data-ribbon-tab="View"]').click()}
  await go('D5:J24');await delay(500);await command('zoom-to-selection')
  await page.waitForFunction(()=>document.querySelector('.workbook-feedback')?.textContent?.includes('缩放已调整为'))
  const first=await feedback()
  const waitZoom=()=>page.waitForFunction(()=>Object.keys(localStorage).some(k=>k.startsWith('native-editor-draft:')&&JSON.parse(localStorage.getItem(k)).operations?.some(op=>op.kind==='applyPageSetups'&&op.setups?.some(s=>s.zoomScale!==undefined))))
  await waitZoom()
  const draft=await page.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).map(k=>JSON.parse(localStorage.getItem(k)))[0])
  const percent=draft.operations.find(op=>op.kind==='applyPageSetups').setups.find(s=>s.zoomScale!==undefined).zoomScale
  assert.ok(percent>=10&&percent<=400);assert.notEqual(percent,100);assert.equal(percent,132)
  await page.reload();await page.locator('.workbook-ribbon').waitFor();await page.waitForFunction(()=>document.querySelector('.save-state')?.getAttribute('aria-busy')==='false');await waitZoom()
  await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
  const reopened=JSON.parse(python({mode:'inspect',bytes:savedBytes.toString('base64')}))
  assert.equal(reopened.zoom,percent);assert.equal(reopened.freeze,source.freeze);assert.equal(reopened.row2,40);assert.equal(reopened.colB,30);assert.deepEqual(reopened.values,source.values)
  assert.deepEqual(Object.keys(reopened.parts),Object.keys(source.parts));for(const name of Object.keys(source.parts))if(name!=='xl/worksheets/sheet1.xml')assert.equal(reopened.parts[name],source.parts[name],name)
  const sha=createHash('sha256').update(savedBytes).digest('hex')
  await page.route('**/reports/v1/native/fixture-gui/2/api/context',r=>r.fulfill({json:{context:{...ctx,revision:2,parentRevision:1,sourceFile:{...ctx.sourceFile,size:savedBytes.length,sha256:sha}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
  await page.route('**/reports/v1/native/fixture-gui/2/api/file',r=>r.fulfill({body:savedBytes,contentType:media}))
  await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/,async r=>r.fulfill({response:await r.fetch({url:`${baseUrl}/reports/v1/editor/assets/native.html`})}))
  await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/fixture-gui/2'))
  await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`);await page.locator('.workbook-ribbon').waitFor();await page.waitForFunction(()=>document.querySelector('.save-state')?.getAttribute('aria-busy')==='false')
  await page.waitForFunction(value=>document.body.innerText.includes(`${value}%`),percent)
  const restoredZoomLabel=await page.locator('body').innerText();assert.ok(restoredZoomLabel.includes(`${percent}%`))
  assert.deepEqual(pageErrors,[]);await page.screenshot({path:'/tmp/workbook-zoom-selection-reopened.png'})
  const assets=await Promise.all(assetChecks)
  if(process.env.WORKBOOK_SMOKE_PREVIEW==='1'){assert.ok(assets.some(a=>a.name.startsWith('lazy-workbook-main-')));assert.ok(assets.some(a=>a.name.startsWith('lazy-workbook-zoom-selection-')))}
  console.log(JSON.stringify({ok:true,preview:process.env.WORKBOOK_SMOKE_PREVIEW==='1',assets,first,percent,draftRestored:true,revision2Reopened:true,freeze:reopened.freeze,geometryPreserved:true,untouchedZIP:true,pageErrors}))
} catch (error) {
  console.error(JSON.stringify({ failed: true, message: String(error), state: await diagnosticPage?.evaluate(() => ({ status: document.querySelector('.save-state-label')?.textContent, feedback: document.querySelector('.workbook-feedback')?.textContent, notice: document.querySelector('.native-notice')?.textContent, url: location.href })).catch(() => null), savePayload, saved: !!savedBytes }))
  throw error
} finally {
  await browser?.close()
  server.kill()
}
