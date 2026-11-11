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
const port = Number(process.env.FORMULA_TRACE_SMOKE_PORT ?? 4261)
const base = `http://127.0.0.1:${port}`
const temporary = mkdtempSync(join(tmpdir(), 'formula-trace-built-'))
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
function fixture() {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64
from io import BytesIO
from openpyxl import Workbook
from openpyxl.worksheet.pagebreak import Break
b=Workbook();b.remove(b.active)
for name in ['Plain','Frozen','Zoom150','RTL','RTL150Frozen','RTLHiddenEnd','RTLMerge','Hidden','Editable','Other']:
 s=b.create_sheet(name)
 s['A1']=2;s['B1']=3;s['B4']=5;s['D6']='=SUM(A1:B1)+B4';s['E8']='=D6*2';s['H14']='extent'
 s['B10']="='Other'!A1";s['B11']='=INDIRECT("A1")';s['B12']='=SUM(Table1[A1])'
 if name=='Frozen':s.freeze_panes='C3';s.row_dimensions[1].height=32;s.column_dimensions['A'].width=18
 if name=='Zoom150':s.sheet_view.zoomScale=150
 if name.startswith('RTL'):s.sheet_view.rightToLeft=True
 if name=='RTL150Frozen':s.sheet_view.zoomScale=150;s.freeze_panes='C3'
 if name=='RTLHiddenEnd':s.column_dimensions['B'].hidden=True;s['A4']=5;s['D6']='=SUM(A1:B1)+A4'
 if name=='RTLMerge':s.merge_cells('A1:B1')
 if name=='Hidden':s.row_dimensions[3].hidden=True;s.column_dimensions['C'].hidden=True
 s.protection.sheet=name!='Editable'
f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
`], { cwd: repo, encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  return Buffer.from(result.stdout.trim(), 'base64')
}
const bytes = fixture()
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context = { documentId: 'formula-trace', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'formula-trace.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'upload' }
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
// Serve API bytes over real HTTP: Chromium cancels route-fulfilled downloads.
const downloadServer = createServer(async (request, response) => {
  if (request.url === '/reports/v1/native/formula-trace/1/api/file') { response.writeHead(200, { 'Content-Type': media, 'Content-Disposition': 'attachment; filename=formula-trace.xlsx', 'Content-Length': bytes.length }); response.end(bytes); return }
  if (request.url === '/reports/v1/native/formula-trace/1/api/context') { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify({ context, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true })); return }
  try { const upstream = await fetch(`${base}${request.url === '/reports/v1/native/formula-trace/1' ? '/reports/v1/editor/assets/native.html' : request.url}`); response.writeHead(upstream.status, Object.fromEntries([...upstream.headers].filter(([key]) => !['content-encoding', 'content-length', 'transfer-encoding'].includes(key)))); response.end(Buffer.from(await upstream.arrayBuffer())) }
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
  await page.route('**/reports/v1/native/formula-trace/1/api/save', route => { saveCount++; return route.fulfill({ status: 500, json: { detail: 'Reading view must never save' } }) })
  await page.addInitScript(() => { if (window === window.top) history.replaceState(null, '', '/reports/v1/native/formula-trace/1') })
  const ready = async () => { await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 }); await page.locator('[data-ribbon-tab="Home"]').waitFor() }
  const goto = async reference => { await page.locator('[data-ribbon-tab="Home"]').click(); await page.locator('[data-ribbon-command="goto-open"]').click(); await page.locator('[data-goto-reference]').fill(reference); await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click(); await delay(250) }
  const view = () => page.locator('[data-ribbon-tab="View"]').click()
  const formulas = () => page.locator('[data-ribbon-tab="Formulas"]').click()
  const command = async id => { await formulas(); await page.locator(`[data-ribbon-command="${id}"]`).click(); await delay(200) }
  const clean = async () => {
    await formulas()
    const remove = page.locator('[data-ribbon-command="remove-arrows"]')
    if (await remove.isEnabled()) await remove.click()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-formula-trace-arrow,.workbook-formula-trace-box').length === 0)
  }
  const geometry = () => page.locator('.workbook-formula-trace-arrow').evaluateAll(items => items.filter(item => getComputedStyle(item).display!=='none').map(item => {
    const rect = item.getBoundingClientRect(), svg = item
    return { rect: { x: rect.x,y: rect.y,width: rect.width,height: rect.height }, viewBox: svg.getAttribute('viewBox'), origin: {x:Number(svg.querySelector('circle').getAttribute('cx')), y:Number(svg.querySelector('circle').getAttribute('cy'))}, tip: svg.querySelector('polygon').getAttribute('points').split(' ')[0].split(',').map(Number) }
  }))
  const state = async () => {
    await page.locator('[data-ribbon-tab="File"]').click()
    return { storage: await page.evaluate(() => ({ ...localStorage })), label: await page.locator('.save-state-label').textContent(), undo: await page.locator('[data-ribbon-command="undo"]').isDisabled(), redo: await page.locator('[data-ribbon-command="redo"]').isDisabled() }
  }
  const sourceHash = async () => sha(Buffer.from(await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/reports/v1/native/formula-trace/1/api/file')).arrayBuffer())))))
  const downloadHash = async suffix => { const [download] = await Promise.all([page.waitForEvent('download'), page.locator('[data-action="xlsx-download"]').click()]); const path = await download.path(); assert(path, String(await download.failure())); const downloaded = readFileSync(path); writeFileSync(join(temporary, `downloaded-${suffix}.xlsx`), downloaded); return sha(downloaded) }
  const canvasSelection=async(name,suffix)=>{
    const selectedPath=join(temporary,`${name}-${suffix}-selection.png`);await page.screenshot({path:selectedPath})
    const selectionProbe=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import json,sys
from PIL import Image
im=Image.open(sys.argv[1]).convert('RGB'); points=set()
for y in range(365,min(im.height,1000)):
 for x in range(45,min(im.width-60,1440)):
  r,g,b=im.getpixel((x,y))
  if r<175 and g<195 and b>=225 and b-r>65 and b-g>45:points.add((x,y))
components=[]
while points:
 p=points.pop(); todo=[p]; group=[p]
 while todo:
  x,y=todo.pop()
  for q in [(x+dx,y+dy) for dx in range(-2,3) for dy in range(-2,3) if dx or dy]:
   if q in points:points.remove(q);todo.append(q);group.append(q)
 if len(group)>15:
  xs,ys=zip(*group);components.append(dict(x=min(xs),y=min(ys),width=max(xs)-min(xs),height=max(ys)-min(ys),n=len(group)))
print(json.dumps(sorted(components,key=lambda c:c['n'],reverse=True)))
`,selectedPath],{encoding:'utf8'})
    assert.equal(selectionProbe.status,0,selectionProbe.stderr)
    const selection=JSON.parse(selectionProbe.stdout).find(r=>r.width>10&&r.height>10)
    assert(selection,`${name}: actual canvas selection border missing`)
    return selection
  }
  await page.goto(`${applicationBase}/reports/v1/editor/assets/native.html`); await ready()
  await goto('Plain!D6')
  const baseline = await state(), beforeHash = await sourceHash()
  assert.equal(beforeHash, sha(bytes)); assert.equal(await downloadHash('before'), beforeHash)
  const cases=['Plain','Frozen','Zoom150','RTL','RTL150Frozen','RTLHiddenEnd','Hidden'];const resume=process.env.FORMULA_TRACE_FROM
  for (const name of cases.slice(resume==='tail'?cases.length:resume?Math.max(cases.indexOf(resume),0):0)) {
    stage = name
    await goto(`${name}!D6`)
    if(!['Frozen','RTL150Frozen'].includes(name)){await page.mouse.move(1000,700);await page.mouse.wheel(name.startsWith('RTL')?0:-2000,-2000);await delay(400)}
    const selection=await canvasSelection(name,'before')
    await command('trace-precedents')
    await page.locator('.workbook-formula-trace-arrow:visible').first().waitFor()
    assert.equal(await page.locator('.workbook-formula-trace-box').count(), 2)
    const precedents = await geometry()
    assert.equal(await page.locator('.workbook-formula-trace-arrow').count(),2)
    assert(precedents.length>=1)
    for (const arrow of precedents) { assert(arrow.rect.width>0&&arrow.rect.height>0); assert(arrow.tip.every(Number.isFinite)); assert(arrow.tip[1] > arrow.origin.y) }
    for(const arrow of precedents){
      const [vx,vy]=arrow.viewBox.split(' ').slice(2).map(Number)
      const tip={x:arrow.rect.x+arrow.tip[0]/vx*arrow.rect.width,y:arrow.rect.y+arrow.tip[1]/vy*arrow.rect.height}
      assert(Math.abs(tip.x-(selection.x+selection.width/2))<7&&Math.abs(tip.y-(selection.y+selection.height/2))<7,`${name}: arrow tip ${JSON.stringify(tip)} must match canvas selection ${JSON.stringify(selection)}`)
    }
    assert(precedents.every(arrow => name.startsWith('RTL') ? arrow.tip[0] < arrow.origin.x : arrow.tip[0] > arrow.origin.x), `${name}: actual arrow direction`)
    await page.screenshot({path:join(temporary,`${name}-precedents.png`),fullPage:true})
    if(name==='RTL150Frozen'||name==='Frozen'){
      await page.mouse.move(1000,700);await page.mouse.wheel(0,name==='RTL150Frozen'?20:-40);await delay(400)
      const scrolledSelection=await canvasSelection(name,'scrolled'),scrolled=await geometry()
      assert.equal(scrolled.length,2,`${name}: offscreen arrow must reappear at current coordinates after scrolling back into view`)
      assert(scrolledSelection.y!==selection.y,`${name}: real canvas selection must scroll`)
      for(const arrow of scrolled){const [vx,vy]=arrow.viewBox.split(' ').slice(2).map(Number);const x=arrow.rect.x+arrow.tip[0]/vx*arrow.rect.width,y=arrow.rect.y+arrow.tip[1]/vy*arrow.rect.height;assert(Math.abs(x-(scrolledSelection.x+scrolledSelection.width/2))<7&&Math.abs(y-(scrolledSelection.y+scrolledSelection.height/2))<7,`RTL frozen scroll arrow must follow real canvas selection: ${JSON.stringify({x,y,scrolledSelection})}`)}
      await page.screenshot({path:join(temporary,`${name}-scrolled.png`),fullPage:true})
      await page.mouse.wheel(0,name==='RTL150Frozen'?-20:40);await delay(400)
    }

    await clean(); await command('trace-dependents')
    await page.locator('.workbook-formula-trace-arrow:visible').first().waitFor()
    assert.equal(await page.locator('.workbook-formula-trace-box').count(), 0)
    const dependents = await geometry(); assert.equal(dependents.length, 1)
    await page.screenshot({path:join(temporary,`${name}-dependents.png`),fullPage:true})
    await clean(); assert.deepEqual(await state(), baseline, `${name}: reading overlays must not mutate draft/history/status`)
    results.push({name,precedents,dependents,clear:true});writeFileSync(join(temporary,'cases.json'),JSON.stringify(results,null,2));console.log(JSON.stringify({name,precedents:precedents.length,dependents:dependents.length,clear:true}))
  }
  stage='merged-anchor-refused'
  await goto('RTLMerge!D6');await command('trace-precedents')
  assert.equal(await page.locator('.workbook-formula-trace-arrow').count(),0)
  assert.match(await page.locator('.workbook-feedback').textContent(),/合并单元格/)
  stage='cross-sheet-count'
  await goto('Plain!B10'); await command('trace-precedents')
  assert.equal(await page.locator('.workbook-formula-trace-arrow').count(),0)
  assert.match(await page.locator('.workbook-feedback').textContent(),/跨工作表引用.*仅计数/)
  stage='complex-formulas-no-pseudo-arrows'
  for (const reference of ['B11','B12']) {
    await goto(`Plain!${reference}`); await command('trace-precedents')
    assert.equal(await page.locator('.workbook-formula-trace-arrow').count(),0)
    assert.equal(await page.locator('.workbook-formula-trace-box').count(),0)
    assert.match(await page.locator('.workbook-feedback').textContent(),/未绘制.*不代表完整/)
  }
  stage='worksheet-identity-clear'
  await goto('Plain!D6'); await command('trace-precedents'); await page.locator('.workbook-formula-trace-arrow:visible').first().waitFor()
  await goto('Frozen!D6'); await formulas()
  await page.waitForFunction(()=>document.querySelectorAll('.workbook-formula-trace-arrow,.workbook-formula-trace-box').length===0)
  await goto('Plain!D6'); await formulas(); assert.equal(await page.locator('.workbook-formula-trace-arrow').count(),0)
  assert.deepEqual(await state(),baseline);assert.equal(await downloadHash('after-reading'),beforeHash)
  stage='editable-mutation-clear'
  await goto('Editable!D6');await page.mouse.move(1000,700);await page.mouse.wheel(-2000,-2000);await delay(400);await command('trace-precedents');await page.locator('.workbook-formula-trace-arrow:visible').first().waitFor()
  await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="insert-row-here"]').click()
  await page.waitForFunction(()=>document.querySelectorAll('.workbook-formula-trace-arrow,.workbook-formula-trace-box').length===0)
  // Undo restores the authored workbook; reading overlays add no Undo element of their own.
  await page.locator('[data-ribbon-tab="File"]').click();await page.locator('[data-ribbon-command="undo"]').click()
  await delay(400)
  assert.equal(saveCount,0);assert.equal(await sourceHash(),beforeHash)
  writeFileSync(join(temporary,'cases.json'),JSON.stringify(results,null,2))
  const assets = await Promise.all(scripts); assert(assets.some(asset => /workbook-main-/.test(asset.path))); assert.deepEqual(errors, [])
  writeFileSync(join(temporary, 'source.xlsx'), bytes)
  writeFileSync(join(temporary,'assets.json'),JSON.stringify(assets,null,2))
  console.log(JSON.stringify({ok:true,temporary,builtJs200AndSha:assets.length,cases:results.map(item=>item.name),protectedReadingStateUnchanged:true,complexFormulasRefused:true,crossSheetCountOnly:true,worksheetAndMutationClear:true,sourceAndReadingDownloadSha256:beforeHash,saveCount,pageErrors:errors}))
} catch (error) {
  await page?.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }).catch(() => {})
  console.error(JSON.stringify({ stage, temporary })); throw error
} finally { await browser?.close(); server.kill(); downloadServer.close() }
