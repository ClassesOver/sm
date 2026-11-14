// 完整原生宿主的图表提交回执：源模式仅在现有bridge边界注入延迟/失败。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = resolve(frontend, '../../..')
const out = process.env.CHART_DIALOG_COMMIT_DIRECTORY
assert(out, '显式指定 CHART_DIALOG_COMMIT_DIRECTORY')
await mkdir(out, { recursive: true })
const staticRoot = process.env.CHART_DIALOG_COMMIT_STATIC_ROOT
const baseline = process.env.CHART_DIALOG_COMMIT_BASELINE_DIRECTORY
const port = Number(process.env.CHART_DIALOG_COMMIT_PORT ?? 4471), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', 'from openpyxl import Workbook\nfrom openpyxl.chart import BarChart,Reference\nfrom io import BytesIO\nimport sys\nb=Workbook();s=b.active;s.title="Data";s.append(["季度","营收"]);s.append(["Q1",12]);s.append(["Q2",25]);s["D1"]="保留来源";c=BarChart();c.add_data(Reference(s,min_col=2,min_row=1,max_row=3),titles_from_data=True);c.set_categories(Reference(s,min_col=1,min_row=2,max_row=3));c.title="原始标题";s.add_chart(c,"F3");f=BytesIO();b.save(f);sys.stdout.buffer.write(f.getvalue())'], { cwd: repo })
assert.equal(result.status, 0, result.stderr.toString())
const bytes = result.stdout, media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
await writeFile(join(out, 'source.xlsx'), bytes)
const manifestSha256 = staticRoot ? sha(await readFile(join(staticRoot, '.vite/manifest.json'))) : null
if (process.env.CHART_DIALOG_COMMIT_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.CHART_DIALOG_COMMIT_MANIFEST_SHA256)
const faultCode = '\nif (typeof window !== "undefined" && (window as any).__chartCommitFault && operations.some(op => op.kind === "applyChartEdits")) { const probe = (window as any).__chartCommitFault; probe.calls++; if (probe.hold) await new Promise<void>((resolve,reject) => { probe.resolve=resolve;probe.reject=reject }); }\n'
const reloadFault = 'if (typeof window !== "undefined" && (window as any).__chartCommitFault?.holdReload) await new Promise<void>(resolve => { (window as any).__chartCommitFault.releaseReload = resolve });\n'
const serverCode = `import {createServer,preview} from 'vite';import {readFile} from 'node:fs/promises';
const root=${JSON.stringify(frontend)},baseline=${JSON.stringify(baseline ?? null)},staticRoot=${JSON.stringify(staticRoot ?? null)};
if(staticRoot){await preview({root,build:{outDir:staticRoot},preview:{host:'127.0.0.1',port:${port},strictPort:true}})}else{
const server=await createServer({root,cacheDir:${JSON.stringify(join(out, 'vite-cache'))},server:{host:'127.0.0.1',port:${port},strictPort:true},plugins:[{name:'explicit-chart-commit-fault-fixture',enforce:'pre',async load(id){if(baseline&&['workbook-main.ts','workbook-chart-design-dialog.ts'].some(name=>id.endsWith('/src/'+name)))return readFile(baseline+'/'+id.split('/').at(-1),'utf8')},transform(code,id){if(id.endsWith('/src/workbook-main.ts')){const marker='await loadOperations(next, undefined, replayedBytes)';if(!code.includes(marker))throw Error('Chart reload boundary marker changed');return code.replace(marker,${JSON.stringify(reloadFault)}+marker)}if(!id.endsWith('/workbook_engine/bridge/operations.ts'))return;const marker='export async function applyWorkbookOperations(bytes: Uint8Array, operations: readonly Record<string, any>[]): Promise<Uint8Array> {';if(!code.includes(marker))throw Error('Chart commit boundary marker changed');return code.replace(marker,marker+${JSON.stringify(faultCode)})}}]});await server.listen();}`
const server = spawn(process.execPath, ['--input-type=module', '-e', serverCode], { cwd: frontend, stdio: ['ignore', 'pipe', 'pipe'] })
let log = '', browser, page
server.stdout.on('data', value => { log += value }); server.stderr.on('data', value => { log += value })
const errors = [], requests = [], cases = [], assetChecks = [], assets = new Map()
try {
  for (let i = 0; ; i++) {
    assert.equal(server.exitCode, null, log)
    try { if ((await fetch(origin + '/reports/v1/editor/assets/native.html')).ok) break } catch {}
    assert(i < 240, log); await delay(250)
  }
  browser = await chromium.launch({ headless: true })
  page = await browser.newPage()
  page.on('pageerror', error => errors.push(error.message))
  if (staticRoot) page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (!path.startsWith('/reports/v1/editor/assets/') || !/\.(js|css)$/.test(path)) return
    assetChecks.push((async () => { const relative = path.slice('/reports/v1/editor/assets/'.length); assert.equal(response.status(), 200); const disk = await readFile(join(staticRoot, relative)); assert.equal(sha(await response.body()), sha(disk)); assets.set(relative, sha(disk)) })())
  })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname; requests.push({ method: route.request().method(), path })
    if (path.endsWith('/api/context')) return route.fulfill({ json: { context: { documentId: 'chart-commit', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: '图表回执.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'upload' }, csrfToken: 'fixture', capabilities: { xlsx_editor: true }, editingEnabled: true } })
    if (path.endsWith('/api/file')) return route.fulfill({ body: bytes, contentType: media })
    return route.fulfill({ status: 405, json: { error: '此夹具禁止保存和发布' } })
  })
  await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/chart-commit/1'))
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')))
  const open = async () => { await page.locator('[data-ribbon-tab="Chart Design"]').click(); await page.locator('[data-ribbon-command="chart-title"]').click(); await page.locator('[role="dialog"][aria-label="编辑图表设计"]').waitFor() }
  const viewports = process.env.CHART_DIALOG_COMMIT_VIEWPORTS?.split(',').map(value => value.split('x').map(Number)) ?? [[1440, 900], [320, 640], [640, 360], [390, 320]]
  for (const [width, height] of viewports) {
    await page.setViewportSize({ width, height }); await page.goto(origin + '/reports/v1/editor/assets/native.html')
    await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 120000 })
    const before = await draft(); await open()
    const dialog = page.locator('[role="dialog"][aria-label="编辑图表设计"]'), input = dialog.getByLabel('图表标题', { exact: true })
    const title = `真实回执 ${width}×${height}`
    assert.equal(await input.inputValue(), '原始标题'); await input.fill(title)
    if (!staticRoot) {
      await page.evaluate(() => { window.__chartCommitFault = { calls: 0, hold: true } })
      await dialog.locator('[data-chart-design-submit]').click()
      await page.waitForFunction(() => window.__chartCommitFault?.calls === 1)
      const pending = await page.evaluate(() => {
        const overlay = document.querySelector('[role="dialog"][aria-label="编辑图表设计"]'), card = overlay.querySelector('.workbook-ribbon-format-dialog')
        return { visible: !overlay.hidden, retained: card.querySelector('[aria-label="图表标题"]').value, busy: card.getAttribute('aria-busy'), submitDisabled: card.querySelector('[data-chart-design-submit]').disabled }
      })
      await writeFile(join(out, `pending-${width}x${height}.json`), JSON.stringify(pending, null, 2))
      assert(pending.visible && pending.busy === 'true' && pending.submitDisabled, JSON.stringify(pending))
      for (const key of ['Tab', 'Shift+Tab']) {
        await page.keyboard.press(key)
        const focus = await page.evaluate(() => ({ contained: document.querySelector('[role="dialog"][aria-label="编辑图表设计"]').contains(document.activeElement), active: document.activeElement.outerHTML.slice(0, 300) }))
        await writeFile(join(out, `pending-focus-${width}x${height}-${key.replace('+', '-')}.json`), JSON.stringify(focus, null, 2))
        assert(focus.contained, JSON.stringify(focus))
      }
      await dialog.locator('form').dispatchEvent('submit'); await page.keyboard.press('Escape')
      assert(await dialog.isVisible()); assert.equal(await page.evaluate(() => window.__chartCommitFault.calls), 1)
      await page.evaluate(() => window.__chartCommitFault.reject(new Error('受控图表写回失败')))
      await page.waitForFunction(() => document.querySelector('[role="dialog"][aria-label="编辑图表设计"] [role="alert"]')?.textContent.includes('受控图表写回失败'))
      assert.equal(await input.inputValue(), title); assert(await dialog.isVisible()); assert.deepEqual(await draft(), before)
      assert(await dialog.locator('[data-chart-design-submit]').isEnabled())
      await page.screenshot({ path: join(out, `failed-${width}x${height}.png`) })
      await page.evaluate(() => { window.__chartCommitFault.hold = false; window.__chartCommitFault.holdReload = true })
    }
    await dialog.locator('[data-chart-design-submit]').click()
    if (!staticRoot) {
      await page.waitForFunction(() => !!window.__chartCommitFault.releaseReload)
      for (const key of ['Tab', 'Shift+Tab']) {
        await page.evaluate(() => { window.__chartCommitTab = null; const listener = event => { if (event.key !== 'Tab') return; window.removeEventListener('keydown', listener); queueMicrotask(() => { window.__chartCommitTab = { prevented: event.defaultPrevented, active: document.activeElement.outerHTML.slice(0, 300) } }) }; window.addEventListener('keydown', listener) })
        await page.keyboard.press(key)
        const tab = await page.evaluate(() => window.__chartCommitTab)
        await writeFile(join(out, `locked-focus-${width}x${height}-${key.replace('+', '-')}.json`), JSON.stringify(tab, null, 2))
        assert(tab.prevented, JSON.stringify(tab))
      }
      await page.evaluate(() => window.__chartCommitFault.releaseReload())
    }
    await dialog.waitFor({ state: 'hidden' })
    await page.waitForFunction(title => [...window.__sheetsWebCharts.store.values()].flat().some(chart => chart.title === title), title)
    const after = await draft()
    assert(after.some(([, value]) => JSON.parse(value).operations.some(operation => operation.kind === 'applyChartEdits' && operation.edits.some(edit => edit.title === title))))
    await open(); assert.equal(await input.inputValue(), title)
    await input.fill('取消的修改'); await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' }); assert.deepEqual(await draft(), after)
    cases.push({ width, height, asyncRejection: !staticRoot, pendingNoDuplicate: !staticRoot, actualWriterRetry: true, reopenedTitle: title, cancelDraftUnchanged: true })
    await page.evaluate(() => localStorage.clear())
  }
  await Promise.all(assetChecks)
  assert.deepEqual(errors, []); assert.equal(requests.filter(request => request.method !== 'GET').length, 0)
  await writeFile(join(out, 'evidence.json'), JSON.stringify({ ok: true, scope: staticRoot ? 'Frozen complete native host: actual writer success, reopen and cancel; no injected failure' : 'Complete native source host; existing actual bridge entry has explicit delayed rejection injection; retry runs real writer and reload', baseline, manifestSha256, sourceSha256: sha(bytes), cases, requests, errors, assets: Object.fromEntries(assets) }, null, 2))
  console.log(JSON.stringify({ ok: true, cases: cases.length, assets: assets.size, manifestSha256 }))
} catch (error) {
  await page?.screenshot({ path: join(out, 'failure.png') }).catch(() => undefined)
  await writeFile(join(out, 'failure.json'), JSON.stringify({ error: String(error), stack: error.stack, cases, errors, requests }, null, 2)); throw error
} finally {
  await browser?.close(); server.kill('SIGTERM')
  await new Promise(resolve => { if (server.exitCode !== null) resolve(); else server.once('exit', resolve) })
  await writeFile(join(out, 'server.log'), log)
}
