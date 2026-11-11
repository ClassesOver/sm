import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.ERROR_CHECKING_SMOKE_PORT ?? 4265)
const base = `http://127.0.0.1:${port}`
const temporary = mkdtempSync(join(tmpdir(), 'error-checking-built-'))
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
function fixture() {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64
from io import BytesIO
from openpyxl import Workbook
b=Workbook();b.remove(b.active)
for name in ['Protected','Editable','Other','Clean']:
 s=b.create_sheet(name)
 s['A1']='start';s['Z220']='extent'
 if name!='Clean':
  s['B2']='=1/0';s['D4']='=#REF!';s['F6']="='Other'!B2" if name!='Other' else '=1/0'
  s['H8']='#REF!suffix';s['I9']='#FIELD!';s['I9'].data_type='s'
  s['J10']='=1/0';s['J10'].data_type='s'
  s['Z220']='#REF!';s['Z220'].data_type='s'
 s.protection.sheet=name=='Protected'
f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
`], { cwd: repo, encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  return Buffer.from(result.stdout.trim(), 'base64')
}
const bytes = fixture()
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context = { documentId: 'error-checking', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'error-checking.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'upload' }
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
// Serve API bytes over real HTTP: Chromium cancels route-fulfilled downloads.
const downloadServer = createServer(async (request, response) => {
  if (request.url === '/reports/v1/native/error-checking/1/api/file') { response.writeHead(200, { 'Content-Type': media, 'Content-Disposition': 'attachment; filename=error-checking.xlsx', 'Content-Length': bytes.length }); response.end(bytes); return }
  if (request.url === '/reports/v1/native/error-checking/1/api/context') { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify({ context, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true })); return }
  try { const upstream = await fetch(`${base}${request.url === '/reports/v1/native/error-checking/1' ? '/reports/v1/editor/assets/native.html' : request.url}`); response.writeHead(upstream.status, Object.fromEntries([...upstream.headers].filter(([key]) => !['content-encoding', 'content-length', 'transfer-encoding'].includes(key)))); response.end(Buffer.from(await upstream.arrayBuffer())) }
  catch { response.writeHead(502); response.end() }
})
await new Promise(resolve => downloadServer.listen(0, '127.0.0.1', resolve))
const applicationBase = `http://127.0.0.1:${downloadServer.address().port}`
let browser, page, stage = 'setup', saveCount = 0
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1500, height: 1100 }, colorScheme: 'light', acceptDownloads: true, permissions: ['clipboard-read', 'clipboard-write'] })
  const errors = [], scripts = [], results = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => {
    const url = new URL(response.url())
    if (url.pathname.startsWith('/reports/v1/editor/assets/') && url.pathname.endsWith('.js')) scripts.push((async () => {
      assert.equal(response.status(), 200)
      assert.equal(sha(await response.body()), sha(readFileSync(join(frontend, '../static', url.pathname.slice('/reports/v1/editor/assets/'.length)))))
      return {path:url.pathname,status:response.status(),sha256:sha(await response.body())}
    })())
  })
  await page.route('**/reports/v1/native/error-checking/1/api/save', route => { saveCount++; return route.fulfill({ status: 500, json: { detail: 'Reading view must never save' } }) })
  await page.addInitScript(() => { if (window === window.top) history.replaceState(null, '', '/reports/v1/native/error-checking/1') })
  const ready = async () => { await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 }); await page.locator('[data-ribbon-tab="Home"]').waitFor() }
  const goto = async reference => { await page.locator('[data-ribbon-tab="Home"]').click(); await page.locator('[data-ribbon-command="goto-open"]').click(); await page.locator('[data-goto-reference]').fill(reference); await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click(); await delay(250) }
  const view = () => page.locator('[data-ribbon-tab="View"]').click()
  const formulas = () => page.locator('[data-ribbon-tab="Formulas"]').click()
  const command = async id => { await formulas(); await page.locator(`[data-ribbon-command="${id}"]`).click(); await delay(200) }
  const state = async () => {
    await page.locator('[data-ribbon-tab="File"]').click()
    return {storage:await page.evaluate(()=>({...localStorage})),label:await page.locator('.save-state-label').textContent(),undo:await page.locator('[data-ribbon-command="undo"]').isDisabled(),redo:await page.locator('[data-ribbon-command="redo"]').isDisabled(),save:await page.locator('[data-action="save"]').isDisabled()}
  }
  const download = async name => {const [d]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);const data=readFileSync(await d.path());writeFileSync(join(temporary,`download-${name}.xlsx`),data);return sha(data)}
  const feedback=()=>page.locator('.workbook-feedback')
  const checkpoint=async(name,detail={})=>{stage=name;const path=join(temporary,`${name}.png`);await page.screenshot({path,fullPage:true});results.push({name,...detail,screenshot:path,screenshotSha256:sha(readFileSync(path))});writeFileSync(join(temporary,'cases.json'),JSON.stringify(results,null,2));console.log(JSON.stringify({name,...detail}))}
  // Read only painted pixels; no runtime handles, debug API, synthetic selections or DOM scrolling.
  const canvasSelection=async name=>{
    const path=join(temporary,`${name}-selection.png`);await page.screenshot({path})
    const probe=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys
from PIL import Image
im=Image.open(sys.argv[1]).convert('RGB'); points=set()
for y in range(365,min(im.height,1000)):
 for x in range(45,min(im.width-60,1440)):
  r,g,b=im.getpixel((x,y))
  if r<175 and g<195 and b>=225 and b-r>65 and b-g>45:points.add((x,y))
components=[]
while points:
 p=points.pop();todo=[p];group=[p]
 while todo:
  x,y=todo.pop()
  for q in [(x+dx,y+dy) for dx in range(-2,3) for dy in range(-2,3) if dx or dy]:
   if q in points:points.remove(q);todo.append(q);group.append(q)
 if len(group)>15:
  xs,ys=zip(*group);components.append(dict(x=min(xs),y=min(ys),width=max(xs)-min(xs),height=max(ys)-min(ys)))
print(json.dumps(components))
`,path],{encoding:'utf8'});assert.equal(probe.status,0,probe.stderr);const selection=JSON.parse(probe.stdout).find(r=>r.width>10&&r.height>10);assert(selection,'actual canvas selection must be visible');return selection
  }
  const check=async(count,address,value)=>{
    stage=`check-${address}`;await command('error-checking')
    const expected=`当前工作表发现 ${count} 个错误：${address} ${value}（按当前计算结果检查）。`
    await page.waitForFunction(text=>document.querySelector('.workbook-feedback')?.textContent===text,expected,{timeout:15000})
    assert.equal(await page.locator('[data-u-comp="defined-name"] input').inputValue(),address,'官方名称框必须同步真实活动选区')
    const selection=await canvasSelection(`${results.length}-${address}`)
    await checkpoint(`${results.length}-${address}`,{feedback:await feedback().textContent(),selection})
  }
  await page.goto(`${applicationBase}/reports/v1/editor/assets/native.html`);await ready()
  await goto('Protected!A1');await delay(1800)
  const baseline=await state();assert.equal(await download('before'),sha(bytes))
  // Strict row-major next skips current error, wraps; suffix/formula text excluded, modern FIELD included.
  for(const [address,value]of [['B2','#DIV/0!'],['D4','#REF!'],['F6','#DIV/0!'],['I9','#FIELD!'],['Z220','#REF!'],['B2','#DIV/0!']])await check(5,address,value)
  assert.deepEqual(await state(),baseline);assert.equal(saveCount,0);assert.equal(await download('protected-after'),sha(bytes));await checkpoint('protected-readonly-unchanged')
  await goto('Clean!A1');await command('error-checking');await page.waitForFunction(()=>document.querySelector('.workbook-feedback')?.textContent==='当前工作表未发现错误（按当前计算结果检查）。');await checkpoint('current-sheet-clean',{feedback:await feedback().textContent()});assert.deepEqual(await state(),baseline)
  await goto('Other!A1');await check(5,'B2','#DIV/0!');assert.deepEqual(await state(),baseline);assert.equal(saveCount,0)
  await goto('Editable!A1');await check(5,'B2','#DIV/0!')
  // Only this explicit user edit may change history/draft. Checking after repair must be neutral.
  await goto('Editable!B2');await page.keyboard.type('7');await page.keyboard.press('Enter');await delay(1500)
  const edited=await state();assert.equal(edited.undo,false);assert.notDeepEqual(edited,baseline)
  await goto('Editable!A1');await check(4,'D4','#REF!');await check(4,'F6','#DIV/0!');await check(4,'I9','#FIELD!');await check(4,'Z220','#REF!');await check(4,'D4','#REF!')
  assert.deepEqual(await state(),edited);assert.equal(saveCount,0);assert.equal(await download('after-user-repair'),sha(bytes));await checkpoint('repair-rescan-neutral')
  await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="undo"]').click();await delay(1500);await goto('Editable!A1');await check(5,'B2','#DIV/0!')
  const undone=await state();await check(5,'D4','#REF!');assert.deepEqual(await state(),undone);assert.equal(saveCount,0)
  await Promise.all(scripts);assert.deepEqual(errors,[]);writeFileSync(join(temporary,'source.xlsx'),bytes)
  const manifest={ok:true,temporary,browserVersion:browser.version(),sourceSha256:sha(bytes),cases:results,assets:await Promise.all(scripts),saveCount,pageErrors:errors};writeFileSync(join(temporary,'result.json'),JSON.stringify(manifest,null,2));console.log(JSON.stringify({ok:true,temporary,cases:results.length,assets:manifest.assets.length,saveCount,pageErrors:errors}))
}catch(error){await page?.screenshot({path:join(temporary,'failure.png'),fullPage:true}).catch(()=>{});if(page)writeFileSync(join(temporary,'failure.html'),await page.content());console.error(JSON.stringify({stage,temporary}));throw error}
finally{await browser?.close();server.kill();downloadServer.close()}
