// 实际函数目录组件或冻结 native 宿主；不确认函数、不保存文件。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { spawnSync } from 'node:child_process'
import { extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = resolve(frontend, '../../..')
const out = process.env.WORKBOOK_FUNCTION_NAVIGATION_DIRECTORY
assert(out, '显式指定 WORKBOOK_FUNCTION_NAVIGATION_DIRECTORY')
await mkdir(out, { recursive: true })
const staticRoot = process.env.WORKBOOK_FUNCTION_STATIC_ROOT
const sourceRoot = process.env.WORKBOOK_FUNCTION_SOURCE_ROOT ?? (staticRoot ? null : frontend)
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
let bytes, manifestSha
if (staticRoot) {
  manifestSha = sha(await readFile(join(staticRoot, '.vite/manifest.json')))
  if (process.env.WORKBOOK_FUNCTION_MANIFEST_SHA) assert.equal(manifestSha, process.env.WORKBOOK_FUNCTION_MANIFEST_SHA)
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', 'from openpyxl import Workbook\nfrom io import BytesIO\nimport sys\nb=Workbook();b.active["A1"]=2;b.active["A2"]=3;f=BytesIO();b.save(f);sys.stdout.buffer.write(f.getvalue())'], { cwd: repo })
  assert.equal(result.status, 0, result.stderr?.toString())
  bytes = result.stdout
} else {
  const source = `import React from 'react';import {createRoot} from 'react-dom/client';
import {InsertFunctionDialog} from './src/workbook-function-catalog-dialog';
import './src/style.css';import './src/office-theme.css';import './src/workbook.css';import './src/workbook-insert-function.css';
const root=createRoot(document.querySelector('#component'));let commits=0,cancels=0;
const catalog=['SUM','SUMIF','SUMIFS'].map(name=>({name,category:'Math',syntax:name+'(number1)',abstract:'求和',description:'函数说明',params:[]}));
document.querySelector('#open').onclick=()=>root.render(React.createElement(InsertFunctionDialog,{targetLabel:'A1',catalog,recent:[],initialCategory:'All',onPick:()=>commits++,onClose:()=>{cancels++;root.render(null)}}));
window.functionProbe={stats:()=>({commits,cancels})};`
  const result = await build({ absWorkingDir: frontend, stdin: { contents: source, resolveDir: frontend, loader: 'tsx' }, bundle: true, format: 'esm', outfile: join(out, 'component.js'), loader: { '.woff': 'dataurl', '.woff2': 'dataurl', '.svg': 'dataurl', '.png': 'dataurl' }, metafile: true })
  await writeFile(join(out, 'metafile.json'), JSON.stringify(result.metafile, null, 2))
}
const requests = [], errors = [], cases = [], failures = [], assets = new Map(), pending = []
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const server = createServer(async (request, response) => {
  try {
    const path = new URL(request.url, 'http://localhost').pathname
    requests.push({ method: request.method, path })
    if (request.method !== 'GET') { response.writeHead(405); response.end(); return }
    if (path.endsWith('/api/context')) {
      response.setHeader('content-type', 'application/json')
      response.end(JSON.stringify({ context: { documentId: 'function-navigation', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: '函数导航.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'upload' }, csrfToken: 'fixture', capabilities: { xlsx_editor: true }, editingEnabled: true }))
      return
    }
    if (path.endsWith('/api/file')) { response.setHeader('content-type', media); response.end(bytes); return }
    if (!staticRoot && path === '/') {
      response.setHeader('content-type', 'text/html; charset=utf-8')
      response.end('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><link rel="stylesheet" href="/component.css"></head><body class="editor-format-xlsx"><button id="open">插入函数</button><div id="component" class="workbook-function-root"></div><script type="module" src="/component.js"></script></body></html>')
      return
    }
    const relative = staticRoot ? path.startsWith('/reports/v1/editor/assets/') ? path.slice('/reports/v1/editor/assets/'.length) : path === '/reports/v1/native/function-navigation/1' ? 'native.html' : null : path.slice(1)
    const root = resolve(staticRoot ?? out), file = relative && resolve(root, relative)
    if (!file || !file.startsWith(root + '/')) { response.writeHead(404); response.end(); return }
    response.setHeader('content-type', ({ '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.json': 'application/json' })[extname(file)] ?? 'application/octet-stream')
    response.end(await readFile(file))
  } catch { response.writeHead(404); response.end() }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()
page.on('pageerror', error => errors.push(error.message))
if (staticRoot) page.on('response', response => pending.push((async () => {
  const path = new URL(response.url()).pathname
  if (!path.startsWith('/reports/v1/editor/assets/') || !/\.(js|css)$/.test(path)) return
  assert.equal(response.status(), 200)
  const relative = path.slice('/reports/v1/editor/assets/'.length), disk = await readFile(join(staticRoot, relative))
  assert.equal(sha(await response.body()), sha(disk)); assets.set(relative, sha(disk))
})()))
const check = (ok, label) => { if (!ok) failures.push(label) }
try {
  await page.goto(`http://127.0.0.1:${server.address().port}${staticRoot ? '/reports/v1/native/function-navigation/1' : '/'}`)
  if (staticRoot) await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 120000 })
  for (const [width, height] of [[1440, 900], [320, 640], [640, 360], [390, 320]]) {
    await page.setViewportSize({ width, height })
    if (staticRoot) {
      await page.locator('[data-ribbon-tab="Formulas"]').click()
      await page.locator('[data-ribbon-command="insert-function-open"]').click()
    } else await page.locator('#open').click()
    const dialog = page.locator('.insert-function-dialog')
    await dialog.waitFor()
    if (staticRoot) await dialog.locator('.fn-filter-row input').fill('SUM')
    const options = dialog.locator('.fn-list [role="option"]')
    assert(await options.count() >= 3)
    const row = { width, height, protections: [], ordinary: [] }
    for (const protection of ['composing', 'legacy229', 'consumed']) for (const key of ['ArrowDown', 'ArrowUp', 'Home', 'End']) {
      const result = await dialog.evaluate((element, { protection, key }) => {
        const options = element.querySelectorAll('[role="option"]'), target = options[1]
        target.focus()
        const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composing', keyCode: protection === 'legacy229' ? 229 : 0 })
        if (protection === 'consumed') event.preventDefault()
        target.dispatchEvent(event)
        return { sameFocus: document.activeElement === target, defaultPrevented: event.defaultPrevented }
      }, { protection, key })
      row.protections.push({ protection, key, ...result })
      check(result.sameFocus && result.defaultPrevented === (protection === 'consumed'), `${width}x${height} ${protection}/${key}`)
    }
    await options.first().focus()
    const count = await options.count()
    for (const [key, index] of [['ArrowDown', 1], ['End', count - 1], ['Home', 0], ['ArrowUp', 0]]) {
      await page.keyboard.press(key)
      const result = await options.nth(index).evaluate(element => ({ focus: document.activeElement === element, selected: element.getAttribute('aria-selected'), tabIndex: element.tabIndex }))
      row.ordinary.push({ key, index, ...result })
      check(result.focus && result.selected === 'true' && result.tabIndex === 0, `${width}x${height} ordinary ${key}`)
    }
    await dialog.locator('.primary-action').focus(); await page.keyboard.press('Tab')
    check(await dialog.locator('.fn-filter-row input').evaluate(element => document.activeElement === element), `${width}x${height} Tab wraps`)
    await page.keyboard.press('Shift+Tab')
    check(await dialog.locator('.primary-action').evaluate(element => document.activeElement === element), `${width}x${height} ShiftTab wraps`)
    await page.screenshot({ path: join(out, `catalog-${width}x${height}.png`) })
    await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'detached' })
    cases.push(row)
  }
  await Promise.all(pending)
  assert.equal(requests.filter(request => request.method !== 'GET').length, 0)
  const stats = staticRoot ? null : await page.evaluate(() => window.functionProbe.stats())
  if (stats) assert.deepEqual(stats, { commits: 0, cancels: 4 })
  const evidence = { ok: !failures.length && !errors.length, scope: staticRoot ? 'Frozen full native workbook host' : 'Actual React function catalog; explicit component fixture', keyboard: 'Protection events synthetic; ordinary Arrow/Home/End/Tab/Escape real Chromium', manifestSha, sourceMetadataRoot: sourceRoot, sources: sourceRoot ? await Promise.all(['src/workbook-function-catalog-dialog.tsx', 'src/workbook-modal-dialog.ts'].map(async file => ({ file, sha256: sha(await readFile(join(sourceRoot, file))) }))) : [], cases, errors, failures, stats, requests, assets: Object.fromEntries(assets) }
  await writeFile(join(out, 'evidence.json'), JSON.stringify(evidence, null, 2))
  assert.deepEqual(errors, []); assert.deepEqual(failures, [])
  console.log(JSON.stringify({ ok: true, cases: cases.length, assets: assets.size, manifestSha }))
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)) }
