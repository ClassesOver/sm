import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync, mkdtempSync, mkdirSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { inspectWatchWindow } from './office-workbook-watch-layout.mjs'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.WATCH_WINDOW_SMOKE_PORT ?? 4263)
const base = `http://127.0.0.1:${port}`
const temporary = process.env.WATCH_WINDOW_OUTPUT ?? mkdtempSync(join(tmpdir(), 'watch-window-built-'))
if(process.env.WATCH_WINDOW_OUTPUT)mkdirSync(temporary)
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifest=readFileSync(join(frontend,'../static/.vite/manifest.json'))
if(process.env.WATCH_WINDOW_EXPECTED_MANIFEST)assert.equal(sha(manifest),process.env.WATCH_WINDOW_EXPECTED_MANIFEST)
function fixture() {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64
from io import BytesIO
from openpyxl import Workbook
from openpyxl.worksheet.pagebreak import Break
b=Workbook();b.remove(b.active)
for name in ['Protected','Editable','Other']:
 s=b.create_sheet(name)
 for row in range(1,6):
  for column in range(1,7):s.cell(row,column,row*10+column)
 s['A1']=2;s['B1']='=A1*3';s['C1']=0.125;s['C1'].number_format='0.0%'
 s.protection.sheet=name=='Protected'
 if ${process.env.WATCH_WINDOW_VIEWPORTS ? 'True' : 'False'}:
  s['D5']='很长的监视单元格内容，逐字保留用于核对。'*18
  s['F5']='='+'+'.join(['A1']*60)
f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
`], { cwd: repo, encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  return Buffer.from(result.stdout.trim(), 'base64')
}
const bytes = fixture()
writeFileSync(join(temporary,'source.xlsx'),bytes)
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context = { documentId: 'watch-window', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'watch-window.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'upload' }
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
// Serve API bytes over real HTTP: Chromium cancels route-fulfilled downloads.
const downloadServer = createServer(async (request, response) => {
  if(request.url==='/watch-saved-harness'){
    const assets=readdirSync(join(frontend,'../static/assets')),main=assets.find(name=>/^lazy-workbook-main-.*\.js$/.test(name)),shell=assets.find(name=>/^lazy-shell-.*\.js$/.test(name))
    const css=assets.filter(name=>name.endsWith('.css')).map(name=>`<link rel="stylesheet" href="/reports/v1/editor/assets/assets/${name}">`).join('')
    response.writeHead(200,{'Content-Type':'text/html'});response.end(`<!doctype html><html><head>${css}</head><body><main id="app"></main><script type="module">
import {createWorkbookEditorView} from '/reports/v1/editor/assets/assets/${main}';import {createEditorShell} from '/reports/v1/editor/assets/assets/${shell}';
const shell=createEditorShell(document.querySelector('#app'),'full','xlsx');
await createWorkbookEditorView(shell,{file:async()=>({bytes:await(await fetch('/reports/v1/native/watch-window/1/api/file')).arrayBuffer(),sha256:'${sha(bytes)}'}),request:async(path,payload)=>{const response=await fetch('/watch-save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});return response.json()}});
</script></body></html>`);return
  }
  if(request.url==='/watch-save'){saveCount++;response.writeHead(200,{'Content-Type':'application/json'});response.end(JSON.stringify({revision:2,revisionRegistered:true,xlsx:{},validation:{ok:true,issues:[]}}));return}

  if (/^\/reports\/v1\/native\/watch-window\/[12]\/api\/file$/.test(request.url)) { response.writeHead(200, { 'Content-Type': media, 'Content-Disposition': 'attachment; filename=watch-window.xlsx', 'Content-Length': bytes.length }); response.end(bytes); return }
  if (/^\/reports\/v1\/native\/watch-window\/[12]\/api\/context$/.test(request.url)) { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify({ context:{...context,revision:request.url.includes('/2/')?2:1}, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true })); return }
  try { const upstream = await fetch(`${base}${/^\/reports\/v1\/native\/watch-window\/[12]$/.test(request.url) ? '/reports/v1/editor/assets/native.html' : request.url}`); response.writeHead(upstream.status, Object.fromEntries([...upstream.headers].filter(([key]) => !['content-encoding', 'content-length', 'transfer-encoding'].includes(key)))); response.end(Buffer.from(await upstream.arrayBuffer())) }
  catch { response.writeHead(502); response.end() }
})
await new Promise(resolve => downloadServer.listen(0, '127.0.0.1', resolve))
const applicationBase = `http://127.0.0.1:${downloadServer.address().port}`
let browser, page, stage = 'setup', saveCount = 0
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1500, height: 1100 }, colorScheme: 'light', acceptDownloads: true, permissions: ['clipboard-read', 'clipboard-write'] })
  const errors = [], consoleErrors=[], failedResponses=[], scripts = [], results = [], assets=[], layouts=[]
  page.on('pageerror', error => errors.push(error.message))
  page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
  page.on('dialog',dialog=>dialog.type()==='beforeunload'?dialog.accept():dialog.dismiss())
  page.on('response', response => {
    const url = new URL(response.url())
    if(response.status()>=400)failedResponses.push({path:url.pathname,status:response.status()})
    if (url.pathname.startsWith('/reports/v1/editor/assets/') && url.pathname.endsWith('.js')) scripts.push((async () => {
      assert.equal(response.status(), 200)
      const data=await response.body()
      assert.equal(sha(data), sha(readFileSync(join(frontend, '../static', url.pathname.slice('/reports/v1/editor/assets/'.length)))))
      const asset={path:url.pathname,status:response.status(),size:data.length,sha256:sha(data)};assets.push(asset);writeFileSync(join(temporary,'assets.json'),JSON.stringify(assets,null,2));return asset
    })())
  })
  await page.route('**/reports/v1/native/watch-window/1/api/save', route => { saveCount++; return route.fulfill({ status: 500, json: { detail: 'Reading view must never save' } }) })
  await page.addInitScript(() => { if (window === window.top && !location.pathname.startsWith('/reports/v1/native/watch-window/')&&!location.pathname.startsWith('/watch-saved-harness')) history.replaceState(null, '', '/reports/v1/native/watch-window/1') })
  const ready = async () => { await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 }); await page.locator('[data-ribbon-tab="Home"]').waitFor() }
  const goto = async reference => { await page.locator('[data-ribbon-tab="Home"]').click(); await page.locator('[data-ribbon-command="goto-open"]').click(); await page.locator('[data-goto-reference]').fill(reference); await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click(); await delay(250) }
  const view = () => page.locator('[data-ribbon-tab="View"]').click()
  const formulas = () => page.locator('[data-ribbon-tab="Formulas"]').click()
  const command = async id => { await formulas(); await page.locator(`[data-ribbon-command="${id}"]`).click(); await delay(200) }
  const rows=()=>page.locator('[data-watch-row]'),panel=()=>page.locator('[data-watch-window]')
  const add=()=>page.locator('[data-watch-add]').click(),toggle=()=>command('watch-window')
  const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
  const history=async id=>{await page.locator('[data-ribbon-tab="File"]').click();await page.locator(`[data-ribbon-command="${id}"]`).click();await delay(900)}
  const state=async()=>{await page.locator('[data-ribbon-tab="File"]').click();return {storage:await page.evaluate(()=>({...localStorage})),label:await page.locator('.save-state-label').textContent(),undo:await page.locator('[data-ribbon-command="undo"]').isDisabled(),redo:await page.locator('[data-ribbon-command="redo"]').isDisabled()}}
  const checkpoint=async(name,detail={})=>{stage=name;const screenshot=join(temporary,`${name}.png`);await page.screenshot({path:screenshot,fullPage:true});results.push({name,detail,rows:await rows().allTextContents(),screenshot,sha256:sha(readFileSync(screenshot))});writeFileSync(join(temporary,'cases.json'),JSON.stringify(results,null,2));console.log(JSON.stringify({name,detail}))}
  const download=async suffix=>{const [result]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);const path=await result.path();assert(path);const data=readFileSync(path);writeFileSync(join(temporary,`download-${suffix}.xlsx`),data);return sha(data)}
  if(process.env.WATCH_WINDOW_FROM==='saved'){
    await page.goto(`${applicationBase}/watch-saved-harness`);await ready();await goto('Editable!A1:B1');await toggle();await add();assert.equal(await rows().count(),2)
    await goto('Editable!A1');await page.keyboard.type('7');await page.keyboard.press('Enter');await delay(1000)
    await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.workbook-grid')?.inert===true);assert.equal(saveCount,1)
    assert.equal(await page.locator('#report-editor').evaluate(element=>element.inert),false);const before=await state();await page.locator('[data-watch-remove]').first().click();assert.equal(await rows().count(),1);await add();assert.equal(await rows().count(),2)
    await page.locator('[data-watch-close]').click();await toggle();assert.equal(await rows().count(),2);assert.deepEqual(await state(),before);await checkpoint('saved-host-interactive')
    assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(failedResponses,[]);await Promise.all(scripts);assert.deepEqual(readFileSync(join(frontend,'../static/.vite/manifest.json')),manifest)
    const evidence={ok:true,temporary,mode:'saved-host-fixture',cases:results.map(item=>item.name),assets:assets.length,manifestSha256:sha(manifest),sourceSha256:sha(bytes),saveCount,pageErrors:errors,consoleErrors,failedResponses}
    writeFileSync(join(temporary,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence));
  }else{
  await page.goto(`${applicationBase}/reports/v1/editor/assets/native.html`);await ready()
  if(process.env.WATCH_WINDOW_FROM!=='tail'){
  stage='protected-add'
  await goto('Protected!A1:F5');const baseline=await state();assert.equal(await download('before'),sha(bytes))
  await toggle()
  if(process.env.WATCH_WINDOW_VIEWPORTS)layouts.push(await inspectWatchWindow(page,{output:temporary,phase:'empty',open:toggle,viewports:process.env.WATCH_WINDOW_VIEWPORTS}))
  await add();assert.equal(await rows().count(),20);await checkpoint('protected-first20')
  await add();assert.equal(await rows().count(),30);await add();assert.equal(await rows().count(),30)
  assert((await rows().allTextContents()).some(row=>row.includes('12.5%')))
  await page.locator('[data-watch-remove]').first().focus();await delay(1000);assert.equal(await page.locator('[data-watch-remove]').first().evaluate(element=>element===document.activeElement),true)
  await checkpoint('protected30-dedupe-focus')
  if(process.env.WATCH_WINDOW_VIEWPORTS){
    layouts.push(await inspectWatchWindow(page,{output:temporary,phase:'populated',open:toggle,viewports:process.env.WATCH_WINDOW_VIEWPORTS}))
    assert.deepEqual(layouts.flatMap(layout=>layout.failures),[])
  }
  await page.locator('[data-watch-close]').click();await toggle();assert.equal(await rows().count(),30)
  const nextWatch=await page.locator('[data-watch-remove]').nth(1).getAttribute('data-watch-remove')
  await page.locator('[data-watch-remove]').first().press('Enter');assert.equal(await rows().count(),29)
  assert.equal(await page.locator(`[data-watch-remove="${nextWatch}"]`).evaluate(node=>node===document.activeElement),true)
  await goto('Other!A1');await delay(900);assert((await rows().allTextContents()).every(row=>row.startsWith('Protected')))
  assert.deepEqual(await state(),baseline);assert.equal(await download('after-reading'),sha(bytes));assert.equal(saveCount,0)
  await checkpoint('protected-reading-unchanged')
  stage='editable-live'
  await page.locator('[data-watch-close]').click();await goto('Editable!A1:B1');await toggle();await add();assert.equal(await rows().count(),31)
  const editable=()=>rows().filter({hasText:'Editable'}),b1=()=>editable().filter({hasText:'B1'})
  await goto('Editable!A1');await page.keyboard.type('7');await page.keyboard.press('Enter');await delay(1700)
  assert.match(await b1().textContent(),/21=A1\*3/);await checkpoint('editable-live-value')
  await history('undo');assert.match(await b1().textContent(),/6=A1\*3/)
  await checkpoint('editable-undo')
  await goto('Editable!A1');await page.locator('[data-ribbon-command="insert-row-here"]').click();await delay(1000)
  assert((await editable().allTextContents()).some(row=>row.includes('A1删除')));await checkpoint('coordinate-insert-row')
  await history('undo');assert.match(await b1().textContent(),/6=A1\*3/)
  stage='rename-delete'
  await tab('Editable').dblclick();const nameEditor=page.locator('[data-u-comp="slide-tab-item"] [contenteditable="true"]');await nameEditor.fill('Renamed');await nameEditor.press('Enter');await tab('Renamed').waitFor();await delay(1000)
  assert.equal(await rows().filter({hasText:'Renamed'}).count(),2);await checkpoint('stable-id-rename')
  }
  if(process.env.WATCH_WINDOW_FROM==='tail'){
    await goto('Editable!A1:B1');await toggle();await add();await tab('Editable').dblclick();const editor=page.locator('[data-u-comp="slide-tab-item"] [contenteditable="true"]');await editor.fill('Renamed');await editor.press('Enter');await tab('Renamed').waitFor();await delay(900)
  }
  // 公开 facade 删除单独由真实main定向覆盖；官方context popup当前隐藏，浏览器不伪称UI删除。
  await page.reload();await ready();await toggle();assert.equal(await rows().count(),0);await checkpoint('reload-clears-session')
  await goto('Other!A1');await add();assert.equal(await rows().count(),1)
  await page.goto(`${applicationBase}/reports/v1/native/watch-window/2`);await ready();await toggle();assert.equal(await rows().count(),0);await checkpoint('revision-isolated')
  assert.equal(saveCount,0);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(failedResponses,[]);await Promise.all(scripts);writeFileSync(join(temporary,'source.xlsx'),bytes)
  assert.deepEqual(readFileSync(join(frontend,'../static/.vite/manifest.json')),manifest)
  const evidence={ok:true,temporary,cases:results.map(item=>item.name),layouts,assets:assets.length,manifestSha256:sha(manifest),sourceSha256:sha(bytes),saveCount,pageErrors:errors,consoleErrors,failedResponses}
  writeFileSync(join(temporary,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence))
  }
} catch(error){if(page)writeFileSync(join(temporary,'menu-diagnostic.json'),JSON.stringify(await page.locator('.univer-min-w-52.univer-overscroll-contain').evaluateAll(items=>items.map(item=>({html:item.outerHTML,rect:item.getBoundingClientRect().toJSON()}))),null,2));await page?.screenshot({path:join(temporary,'failure.png'),fullPage:true}).catch(()=>{});console.error(JSON.stringify({stage,temporary}));throw error}
finally{await browser?.close();server.kill();downloadServer.close()}
