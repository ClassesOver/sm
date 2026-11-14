// 最终最小overlay只读验收：保留原完整保存链，实际下载文件经原授权宿主导入，零签发。
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { probeCanvasTextRendering } from './canvas-font-preflight.mjs'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const directory = process.env.WORKBOOK_CHART_DATA_DIRECTORY, previous = process.env.WORKBOOK_CHART_DATA_READONLY_FROM
const staticDirectory = process.env.PDF_SMOKE_STATIC_DIRECTORY, engineDirectory = process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
assert(directory && previous && staticDirectory && engineDirectory)
const port = Number(process.env.WORKBOOK_CHART_DATA_PORT ?? 4422), origin = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: false })
const previousEvidence = JSON.parse(await readFile(join(previous, 'evidence.json'), 'utf8')), source = await readFile(join(previous, 'selected-data.xlsx'))
assert.equal(sha(source), previousEvidence.saved.artifacts.xlsx.sha256)
const manifest = await readFile(join(staticDirectory, '.vite/manifest.json')), nativeHtml = await readFile(join(staticDirectory, 'native.html')), engine = await readFile(join(engineDirectory, 'dist/cli.mjs'))
const backendPaths = ['smart_reporting/reporting/delivery/office_engine.py', ...['native_office.py', 'native.py', 'native_api.py'].map(name => `smart_reporting/report_editor/${name}`)]
const identities = async () => Object.fromEntries(await Promise.all(backendPaths.map(async path => [path, sha(await readFile(join(repo, path)))])))
const backend = await identities(); await writeFile(join(directory, 'backend-start-identities.json'), JSON.stringify(backend, null, 2))
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', directory, '--port', String(port), '--source', join(previous, 'selected-data.xlsx')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', bytes => { serverLog += bytes }); server.stderr.on('data', bytes => { serverLog += bytes })
const errors = [], consoleErrors = [], httpErrors = [], assetErrors = [], checks = [], assets = new Map()
try {
  for (let i = 0; ; i++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })).ok) break } catch {}
    assert(i < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8')); assert.equal(info.sourceSha256, sha(source))
  browser = await chromium.launch({ headless: true }); const preflight = await probeCanvasTextRendering(browser); assert.equal(preflight.ok, true)
  page = await browser.newPage({ viewport: { width: 1760, height: 1100 } })
  const cdp = await page.context().newCDPSession(page); await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  page.on('pageerror', error => errors.push(error.message)); page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(js|css)$/.test(path)) checks.push((async () => {
      const bytes = await response.body(), disk = await readFile(join(staticDirectory, path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(response.status(), 200); assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })().catch(error => assetErrors.push({ path, error: String(error) })))
  })
  stage = 'authorized-import'; const response = await page.goto(origin + info.openPath); assert(response && response.status() === 200)
  const html = await response.text(); await writeFile(join(directory, 'served-host.html'), html); assert.equal(sha(html), sha(nativeHtml), '实际宿主HTML应与最终native.html字节一致')
  const manifestData = JSON.parse(manifest.toString()), htmlScripts = [...html.matchAll(/<script\b[^>]*\bsrc="([^"]+)"[^>]*><\/script>/g)].map(match => match[1])
  assert(htmlScripts.length > 0)
  for (const path of htmlScripts) { assert(path.startsWith('/reports/v1/editor/assets/')); const file = path.slice('/reports/v1/editor/assets/'.length); assert.equal(Object.values(manifestData).filter(entry => entry.file === file).length, 1, `HTML脚本应唯一匹配最终manifest: ${file}`) }
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  const loaded = await page.request.get(page.url() + '/api/file'); assert.equal(loaded.status(), 200); assert.equal(sha(await loaded.body()), sha(source))
  stage = 'literal-render'; await page.waitForFunction(() => window.__sheetsWebCharts?.draws > 0)
  const literal = await page.evaluate(() => [...window.__sheetsWebCharts.store.values()].flat()[0])
  assert.deepEqual(literal.series.map(entry => ({ name: entry.name, valuesRef: entry.valuesRef, values: entry.values, categories: entry.categories })), [
    { name: 'A', valuesRef: '', values: [11, 5], categories: ['Added', 'Renamed'] }, { name: 'B', valuesRef: '', values: [12, 8], categories: ['Added', 'Renamed'] }])
  const palette = literal.palette?.slice(0, 2) ?? ['#4472c4', '#ed7d31']
  // 检查实际可见canvas的连通柱形，不能仅凭读取模型宣布字面图表已显示。
  const pixels = await page.evaluate(palette => palette.map(color => {
    const rgb = color.replace('#', '').match(/../g).map(value => parseInt(value, 16))
    const candidates = [...document.querySelectorAll('.workbook-grid canvas')].filter(canvas => canvas.width && canvas.height).map(canvas => {
      const width = canvas.width, height = canvas.height, data = canvas.getContext('2d')?.getImageData(0, 0, width, height).data
      if (!data) return []
      const seen = new Uint8Array(width * height), bars = [], matches = at => data[at * 4] === rgb[0] && data[at * 4 + 1] === rgb[1] && data[at * 4 + 2] === rgb[2] && data[at * 4 + 3] === 255
      for (let at = 0; at < seen.length; at++) {
        if (seen[at] || !matches(at)) continue
        const queue = [at]; seen[at] = 1; let left = width, right = 0, top = height, bottom = 0
        for (let position = 0; position < queue.length; position++) {
          const current = queue[position], x = current % width, y = Math.floor(current / width)
          left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y)
          for (const next of [x ? current - 1 : -1, x + 1 < width ? current + 1 : -1, y ? current - width : -1, y + 1 < height ? current + width : -1]) if (next >= 0 && !seen[next] && matches(next)) { seen[next] = 1; queue.push(next) }
        }
        if (queue.length > 500) bars.push({ left, right, top, bottom, pixels: queue.length })
      }
      return bars.sort((a, b) => a.left - b.left)
    })
    return { color, bars: candidates.sort((a, b) => b.reduce((sum, bar) => sum + bar.pixels, 0) - a.reduce((sum, bar) => sum + bar.pixels, 0))[0] ?? [] }
  }), palette)
  for (const [index, result] of pixels.entries()) { assert.equal(result.bars.length, 2, JSON.stringify(pixels)); const heights = result.bars.map(bar => bar.bottom - bar.top + 1); assert(Math.abs(heights[0] / heights[1] - [11 / 5, 12 / 8][index]) < 0.05) }
  await page.screenshot({ path: join(directory, 'literal-render.png'), fullPage: true })
  stage = 'SelectData'; await page.locator('[data-ribbon-tab="Chart Design"]').click(); await page.locator('[data-ribbon-command="chart-select-data"]').click()
  const dialog = page.getByRole('dialog', { name: '选择数据源', exact: true }); await dialog.waitFor(); const rows = dialog.locator('[data-chart-data-row]'); assert.equal(await rows.count(), 2)
  assert.equal(await rows.nth(0).locator('[data-chart-data-name]').inputValue(), 'A'); assert.equal(await rows.nth(1).locator('[data-chart-data-name]').inputValue(), 'B')
  await page.screenshot({ path: join(directory, 'readonly-dialog.png'), fullPage: true }); await page.setViewportSize({ width: 390, height: 844 })
  await dialog.locator('[data-chart-data-cancel]').scrollIntoViewIfNeeded(); const cancel = await dialog.locator('[data-chart-data-cancel]').boundingBox(); assert(cancel && cancel.y >= 0 && cancel.y + cancel.height <= 844)
  await page.screenshot({ path: join(directory, 'readonly-mobile.png'), fullPage: true }); await dialog.locator('[data-chart-data-cancel]').click()
  const ops = await page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? [])); assert.deepEqual(ops, [])
  await Promise.all(checks); assert(assets.size > 0); assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, []); assert.deepEqual(assetErrors, [])
  for (const path of htmlScripts) assert(assets.has(path), `HTML模块入口应已实际加载且字节匹配: ${path}`)
  const backendEnd = await identities(); assert.deepEqual(backendEnd, backend); assert.equal(sha(await readFile(join(staticDirectory, '.vite/manifest.json'))), sha(manifest)); assert.equal(sha(await readFile(join(engineDirectory, 'dist/cli.mjs'))), sha(engine))
  await writeFile(join(directory, 'backend-end-identities.json'), JSON.stringify(backendEnd, null, 2))
  const state = await (await page.request.get(origin + '/__smoke__/state')).json(); assert.equal(state.plannerCalls, 0); assert.equal(state.savedRevisions, 0); assert(!state.requests.some(request => request.method === 'POST'))
  const evidence = { ok: true, mode: 'zero-save final minimal frontend overlay readback; original complete save chain remains separate', previous, originalFullChainManifest: previousEvidence.manifestSha256, artifactSha256: sha(source), browserVersion: browser.version(), preflight,
    manifestSha256: sha(manifest), engineSha256: sha(engine), htmlSha256: sha(html), htmlScripts, assets: Object.fromEntries(assets), backendExecution: 'live workspace; before/after identities verified', backend, backendEnd, literal, pixels, ops, errors, consoleErrors, httpErrors, assetErrors, state }
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, directory, artifactSha256: sha(source), savedRevisions: state.savedRevisions }))
} catch (error) {
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, errors, consoleErrors, httpErrors, assetErrors }, null, 2)); await page?.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {}); throw error
} finally { await browser?.close(); server.kill('SIGTERM'); await writeFile(join(directory, 'server.log'), serverLog) }
