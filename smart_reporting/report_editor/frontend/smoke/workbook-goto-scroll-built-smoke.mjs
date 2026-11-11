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
const port = Number(process.env.GOTO_SCROLL_SMOKE_PORT ?? 4243)
const base = `http://127.0.0.1:${port}`
const temporary = mkdtempSync(join(tmpdir(), 'goto-scroll-built-'))
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const preference = 'report-editor-cross-highlight'
const colors = { corner: [208, 214, 220], row: [232, 192, 184], column: [222, 220, 172], primaryRow: [218, 186, 218], primaryColumn: [182, 222, 194] }
function python(payload) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import json,sys,base64
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import PatternFill
from PIL import Image
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();b.remove(b.active)
 for name in ['Plain','Frozen','Zoom150','RTL','Far']:
  s=b.create_sheet(name)
  for cell,key in [('A1','corner'),('A5','row'),('C1','column'),('A6','primaryRow'),('D1','primaryColumn')]:
   s[cell].fill=PatternFill('solid',fgColor='FF'+''.join('%02X'%v for v in p['colors'][key]))
  s['C5']='target';s['D6']='primary';s['H12']='extent'
  if name=='Frozen':
   s.freeze_panes='C3';s.row_dimensions[1].height=42;s.row_dimensions[2].height=35;s.column_dimensions['A'].width=18;s.column_dimensions['B'].width=22
  if name=='Zoom150':s.sheet_view.zoomScale=150
  if name=='RTL':s.sheet_view.rightToLeft=True
  s['AA26010']='far extent sentinel';s.protection.sheet=True
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
else:
 images=[Image.open(BytesIO(base64.b64decode(p[k]))).convert('RGB') for k in ['off','on','restored']]
 a,b,c=images;assert a.size==b.size==c.size
 def near(x,y):return all(abs(v-w)<=2 for v,w in zip(x,y))
 def blend(color):return tuple(round(v*.93+t*.07) for v,t in zip(color,(31,90,168)))
 proof={}
 if p['markers']:
  for name,expected in p['markers'].items():
   color=tuple(p['colors'][name]);points=[(x,y) for y in range(a.height) for x in range(a.width) if a.getpixel((x,y))==color]
   assert len(points)>100,(name,'source marker not visible',len(points))
   # Exclude the authored marker boundary: highlight deliberately strokes its edges.
   points=[(x,y) for x,y in points if x>=2 and y>=2 and x<a.width-2 and y<a.height-2 and all(a.getpixel((x+dx,y+dy))==color for dx,dy in [(-2,0),(2,0),(0,-2),(0,2)])]
   target=blend(color) if expected else color
   ratio=sum(near(b.getpixel(point),target) for point in points)/len(points)
   restore=sum(c.getpixel(point)==color for point in points)/len(points)
   assert ratio>.96,(name,'actual canvas blend',ratio,target)
   assert restore>.995,(name,'off residual',restore)
   proof[name]={'pixels':len(points),'expectedHighlight':expected,'actualColor':target,'matchedRatio':ratio,'restoredRatio':restore,'bounds':[min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points)]}
 else:
  # Far blank viewport: measure actual blue overlay over previously white pixels.
  counts_x=[0]*a.width;counts_y=[0]*a.height;points=[];single=blend((255,255,255));double=blend(single)
  for y in range(a.height):
   for x in range(a.width):
    if a.getpixel((x,y))==(255,255,255) and (near(b.getpixel((x,y)),single) or near(b.getpixel((x,y)),double)):
     counts_x[x]+=1;counts_y[y]+=1;points.append((x,y))
  assert len(points)>10000,('far visible overlay',len(points))
  assert max(counts_x)>200 and max(counts_y)>600,('far actual row and column bands',max(counts_x),max(counts_y))
  restore=sum(c.getpixel(point)==a.getpixel(point) for point in points)/len(points)
  assert restore>.995,('far residual',restore)
  proof={'pixels':len(points),'maxColumnPixels':max(counts_x),'maxRowPixels':max(counts_y),'restoredRatio':restore}
 print(json.dumps(proof))
`], { cwd: repo, input: JSON.stringify(payload), encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}
const bytes = Buffer.from(python({ mode: 'create', colors }), 'base64')
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context = { documentId: 'goto-scroll', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'goto-scroll.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'upload' }
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
// Serve API bytes over real HTTP: Chromium cancels route-fulfilled downloads.
const downloadServer = createServer(async (request, response) => {
  if (request.url === '/reports/v1/native/goto-scroll/1/api/file') { response.writeHead(200, { 'Content-Type': media, 'Content-Disposition': 'attachment; filename=goto-scroll.xlsx', 'Content-Length': bytes.length }); response.end(bytes); return }
  if (request.url === '/reports/v1/native/goto-scroll/1/api/context') { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify({ context, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true })); return }
  try { const upstream = await fetch(`${base}${request.url === '/reports/v1/native/goto-scroll/1' ? '/reports/v1/editor/assets/native.html' : request.url}`); response.writeHead(upstream.status, Object.fromEntries([...upstream.headers].filter(([key]) => !['content-encoding', 'content-length', 'transfer-encoding'].includes(key)))); response.end(Buffer.from(await upstream.arrayBuffer())) }
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
      return url.pathname
    })())
  })
  await page.route('**/reports/v1/native/goto-scroll/1/api/save', route => { saveCount++; return route.fulfill({ status: 500, json: { detail: 'Reading view must never save' } }) })
  await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/goto-scroll/1'))
  const ready = async () => { await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 }); await page.locator('[data-ribbon-tab="Home"]').waitFor() }
  const goto = async reference => { await page.locator('[data-ribbon-tab="Home"]').click(); await page.locator('[data-ribbon-command="goto-open"]').click(); await page.locator('[data-goto-reference]').fill(reference); await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click(); await delay(250) }
  const view = () => page.locator('[data-ribbon-tab="View"]').click()
  const toggle = async enabled => { await view(); const button = page.locator('[data-ribbon-command="toggle-cross-highlight"]'); if ((await button.getAttribute('aria-pressed')) !== String(enabled)) await button.click(); await page.waitForFunction(enabled => document.querySelector('[data-ribbon-command="toggle-cross-highlight"]')?.getAttribute('aria-pressed') === String(enabled), enabled); await delay(300) }
  const state = async () => { await page.locator('[data-ribbon-tab="File"]').click(); return { storage: await page.evaluate(key => Object.fromEntries(Object.entries(localStorage).filter(([name]) => name !== key)), preference), label: await page.locator('.save-state-label').textContent(), undo: await page.locator('[data-ribbon-command="undo"]').isDisabled(), redo: await page.locator('[data-ribbon-command="redo"]').isDisabled() } }
  const sourceHash = async () => sha(Buffer.from(await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/reports/v1/native/goto-scroll/1/api/file')).arrayBuffer())))))
  const downloadHash = async suffix => { const [download] = await Promise.all([page.waitForEvent('download'), page.locator('[data-action="xlsx-download"]').click()]); const path = await download.path(); assert(path, String(await download.failure())); const downloaded = readFileSync(path); writeFileSync(join(temporary, `downloaded-${suffix}.xlsx`), downloaded); return sha(downloaded) }
  await page.goto(`${applicationBase}/reports/v1/editor/assets/native.html`); await ready()
  await goto('Plain!C5'); await delay(600)
  const baseline = await state(), beforeHash = await sourceHash()
  assert.equal(beforeHash, sha(bytes)); assert.equal(await downloadHash('before'), beforeHash); console.log(JSON.stringify({ phase: 'baseline', baseline }))
  const check = async (name, reference, markers, reverse = false) => {
    stage = name; await toggle(false); await goto(reference)
    await page.getByText(`已定位到 ${reference}，目标已显示。`, { exact: true }).waitFor()
    if (reverse) {
      await page.keyboard.press('Shift+ArrowLeft'); await page.keyboard.press('Shift+ArrowUp')
      const sentinel = `cross-selection-${Date.now()}`
      await page.evaluate(text => navigator.clipboard.writeText(text), sentinel); await page.keyboard.press('Control+c')
      let matrix = sentinel
      for (let attempt = 0; attempt < 80 && matrix === sentinel; attempt++) { await delay(50); matrix = await page.evaluate(() => navigator.clipboard.readText()) }
      assert.equal(matrix.replace(/\r\n/g, '\n').trimEnd(), 'target\t\n\tprimary', 'real native copy must confirm reverse C5:D6 selection')
      await page.keyboard.press('Escape')
    }
    await view(); await delay(300)
    const capture = async suffix => { const buffer = await page.locator('#workbook-grid').screenshot(); writeFileSync(join(temporary, `${name}-${suffix}.png`), buffer); return buffer.toString('base64') }
    const off = await capture('off'); await toggle(true); const on = await capture('on'); await toggle(false); const restored = await capture('restored')
    const pixels = JSON.parse(python({ mode: 'pixels', off, on, restored, colors, markers }))
    assert.deepEqual(await state(), baseline, `${name}: preference must not change draft, history or save state`)
    results.push({ name, reference, reverseSelection: reverse, pixels }); console.log(JSON.stringify(results.at(-1)))
  }
  for (const name of ['Plain', 'Frozen', 'Zoom150', 'RTL', 'Far']) await check(`${name.toLowerCase()}-distant`, `${name}!Z25001`, null)
  stage = 'preference-reopen'; await toggle(true); assert.equal(await page.evaluate(key => localStorage.getItem(key), preference), '1')
  await page.reload(); await ready(); await view(); assert.equal(await page.locator('[data-ribbon-command="toggle-cross-highlight"]').getAttribute('aria-pressed'), 'true')
  await toggle(false); assert.deepEqual(await state(), baseline)
  assert.equal(await sourceHash(), beforeHash); assert.equal(await downloadHash('after'), beforeHash); assert.equal(saveCount, 0)
  const assets = await Promise.all(scripts); assert(assets.some(path => /workbook-main-/.test(path))); assert.deepEqual(errors, [])
  writeFileSync(join(temporary, 'source.xlsx'), bytes)
  console.log(JSON.stringify({ ok: true, temporary, builtJs200AndSha: assets.length, cases: results.map(result => result.name), preferenceReload: true, protectedReadonlySheets: true, gotoWithoutKeyboardWorkaround: true, draftHistoryAndSaveStateUnchanged: true, sourceAndDownloadedSha256Unchanged: beforeHash, saveCount, pageErrors: errors }))
} catch (error) {
  await page?.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }).catch(() => {})
  console.error(JSON.stringify({ stage, temporary })); throw error
} finally { await browser?.close(); server.kill(); downloadServer.close() }
