// 显式源码故障注入；只在 Vite 测试变换中抛错，不向产品增加测试开关。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const liveFrontend = fileURLToPath(new URL('../', import.meta.url)), repo = resolve(liveFrontend, '../../..')
const frontend = process.env.CHART_RELOAD_FRONTEND ?? liveFrontend
const out = process.env.CHART_RELOAD_DIRECTORY
assert(out, '显式设置 CHART_RELOAD_DIRECTORY'); await mkdir(out, { recursive: true })
const baseline = process.env.CHART_RELOAD_BASELINE, port = Number(process.env.CHART_RELOAD_PORT ?? 4482)
const origin = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
const python = 'from openpyxl import Workbook\nfrom openpyxl.chart import BarChart,Reference\nfrom io import BytesIO\nimport sys\nb=Workbook();s=b.active;s.title="Data";s.append(["季度","收入"]);s.append(["Q1",12]);s.append(["Q2",25]);c=BarChart();c.add_data(Reference(s,min_col=2,min_row=1,max_row=3),titles_from_data=True);c.set_categories(Reference(s,min_col=1,min_row=2,max_row=3));c.title="Original";s.add_chart(c,"F3");f=BytesIO();b.save(f);sys.stdout.buffer.write(f.getvalue())'
const fixture = spawnSync(join(repo, '.venv/bin/python'), ['-c', python]); assert.equal(fixture.status, 0, fixture.stderr.toString())
const bytes = fixture.stdout; await writeFile(join(out, 'source.xlsx'), bytes)
const productPath = baseline ?? join(frontend, 'src/workbook-main.ts')
const productSha256 = sha(await readFile(productPath)), transforms = []
const probe = `const __reloadProbe=(stage:string)=>{const fault=(globalThis as any).__officeReloadFault;if(fault?.stage===stage){fault.remaining--;if(fault.remaining<=0)delete (globalThis as any).__officeReloadFault;throw new Error('fixture reload '+stage+' failed')}};\n`
const serverCode = `import {createServer} from 'vite';import {readFile} from 'node:fs/promises';
const s=await createServer({root:${JSON.stringify(frontend)},cacheDir:${JSON.stringify(join(out, 'vite-cache'))},server:{host:'127.0.0.1',port:${port},strictPort:true},plugins:[{name:'explicit-reload-failure-fixture',enforce:'pre',async load(id){if(${JSON.stringify(baseline ?? '')}&&id.endsWith('/src/workbook-main.ts'))return readFile(${JSON.stringify(baseline ?? '')},'utf8')},transform(code,id){
if(id.endsWith('/src/workbook-main.ts')){code=${JSON.stringify(probe)}+code;for(const [from,to]of[
['await readWorkbookThemeSource(bytes)',"await (async()=>{__reloadProbe('read');return readWorkbookThemeSource(bytes)})()"],
['loadWorkbookData(runtime, data)',"loadWorkbookData(runtime, data);__reloadProbe('loaded')"],
['await waitForWorkbookRendered(runtime, () => disposed)',"await waitForWorkbookRendered(runtime, () => disposed);__reloadProbe('render')"]]){if(!code.includes(from))throw Error('fixture target missing: '+from);code=code.replace(from,to)}return code}
if(id.endsWith('/workbook-vendor/grid/sync.ts')){if(!code.includes('facade.createWorkbook(data)'))throw Error('fixture create target missing');return ${JSON.stringify(probe)}+code.replace('facade.createWorkbook(data)',"__reloadProbe('create');facade.createWorkbook(data)")}
}}]});await s.listen()`
const server = spawn(process.execPath, ['--input-type=module', '-e', serverCode], { cwd: frontend })
let log = '', browser, page; const errors = [], requests = [], cases = []
server.stdout.on('data', value => { log += value }); server.stderr.on('data', value => { log += value })
try {
  for (let i = 0; ; i++) { assert.equal(server.exitCode, null, log); try { if ((await fetch(origin + '/reports/v1/editor/assets/native.html')).ok) break } catch {} assert(i < 240, log); await delay(250) }
  browser = await chromium.launch({ headless: true }); page = await browser.newPage()
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => { if (/\/(workbook-main|sync)\.ts(?:\?|$)/.test(response.url())) transforms.push(response.body().then(body => ({ url: response.url(), sha256: sha(body) }))) })
  await page.route('**/reports/v1/native/chart-reload/1/api/**', route => {
    const path = new URL(route.request().url()).pathname; requests.push({ path, method: route.request().method() })
    if (path.endsWith('/context')) return route.fulfill({ json: { ok: true, context: { documentId: 'chart-reload', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'chart-reload.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, origin: 'upload' }, csrfToken: 'fixture', capabilities: { xlsx_editor: true }, editingEnabled: true } })
    if (path.endsWith('/file')) return route.fulfill({ body: bytes, contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    return route.fulfill({ status: 405, json: { error: '不允许保存发布' } })
  })
  await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/chart-reload/1'))
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).map(([key, value]) => [key, JSON.parse(value).operations]))
  const dialog = () => page.locator('[role="dialog"][aria-label="编辑图表设计"]')
  const views = process.env.CHART_RELOAD_VIEWPORTS?.split(',').map(value => value.split('x').map(Number)) ?? [[1440, 900], [390, 640]]
  for (const [width, height] of views) for (const stage of ['read', 'create', 'loaded', 'render']) {
    await page.setViewportSize({ width, height }); await page.goto(origin + '/reports/v1/editor/assets/native.html')
    await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 120000 })
    const name = page.locator('[data-u-comp="defined-name"] input')
    await name.fill('D20'); await name.press('Enter'); await page.keyboard.type('77'); await page.keyboard.press('Enter')
    await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(op => op.kind === 'applyCellEdits')))
    const before = await draft()
    await page.locator('[data-ribbon-tab="Chart Design"]').click(); await page.locator('[data-ribbon-command="chart-title"]').click()
    await dialog().getByLabel('图表标题', { exact: true }).fill('Retry retained')
    await page.evaluate(stage => { globalThis.__officeReloadFault = { stage, remaining: 1 } }, stage)
    await dialog().locator('[data-chart-design-submit]').click()
    await dialog().getByRole('alert').filter({ hasText: `fixture reload ${stage} failed` }).waitFor()
    assert.equal(await dialog().getByLabel('图表标题', { exact: true }).inputValue(), 'Retry retained'); assert.deepEqual(await draft(), before)
    const button = dialog().locator('[data-chart-design-submit]')
    const hit = await button.evaluate(node => { const r = node.getBoundingClientRect(); return node === document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) }); assert(hit)
    await page.screenshot({ path: join(out, `${stage}-${width}x${height}.png`), animations: 'disabled' })
    await button.click(); await dialog().waitFor({ state: 'hidden', timeout: 30000 })
    await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(op => op.kind === 'applyChartEdits')))
    const after = await draft(), operations = after.flatMap(([, ops]) => ops)
    assert(operations.some(op => op.kind === 'applyChartEdits')); assert(operations.some(op => op.kind === 'applyCellEdits' && op.edits.some(edit => edit.row === 19 && edit.column === 3 && edit.cell?.value === 77)))
    await page.locator('[data-ribbon-tab="File"]').click(); await page.locator('[data-ribbon-command="undo"]').click()
    await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && !(JSON.parse(value).operations ?? []).some(op => op.kind === 'applyChartEdits')))
    await page.locator('[data-ribbon-command="redo"]').click()
    await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(op => op.kind === 'applyChartEdits')))
    assert.deepEqual(await draft(), after); cases.push({ width, height, stage, errorRetained: true, retryHit: hit, retryCommitted: true, manualD20: 77, undoRedo: true }); await page.evaluate(() => localStorage.clear())
  }
  assert.deepEqual(errors, []); assert.equal(requests.filter(request => request.method !== 'GET').length, 0)
  const transformedResources = await Promise.all(transforms)
  await writeFile(join(out, 'evidence.json'), JSON.stringify({ scope: 'Source native host with explicit Vite-only failure injection; not a frozen bundle test', productSha256, productPath, baseline: baseline ?? null, sourceSha256: sha(bytes), cases, requests, errors, transformedResources }, null, 2))
  console.log(JSON.stringify({ ok: true, cases: cases.length, errors }))
} catch (error) {
  await page?.screenshot({ path: join(out, 'failure.png'), animations: 'disabled' }).catch(() => {})
  const draftState = await page?.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:'))).catch(() => [])
  await writeFile(join(out, 'failure.json'), JSON.stringify({ error: String(error), stack: error.stack, cases, requests, errors, draftState }, null, 2)); throw error
} finally { await browser?.close(); server.kill('SIGTERM'); await writeFile(join(out, 'server.log'), log) }
