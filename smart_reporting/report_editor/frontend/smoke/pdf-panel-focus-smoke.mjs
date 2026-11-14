import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createServer, preview } from 'vite'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = resolve(frontend, '../../..')
const directory = resolve(process.env.PDF_PANEL_FOCUS_OUTPUT ?? '/dev/shm/office-pdf-panels-review-20261113/red')
await mkdir(directory, { recursive: true })
const staticRoot = process.env.PDF_PANEL_FOCUS_STATIC_ROOT ? resolve(process.env.PDF_PANEL_FOCUS_STATIC_ROOT) : null
const sourceRoot = process.env.PDF_PANEL_FOCUS_SOURCE_ROOT ? resolve(process.env.PDF_PANEL_FOCUS_SOURCE_ROOT) : frontend
const digest = bytes => createHash('sha256').update(bytes).digest('hex')
const sourceHashes = {}
for (const file of ['src/pdf-form-settings-panel.ts', 'src/pdf-form-design.ts', 'src/pdf-main.ts']) sourceHashes[file] = digest(await readFile(resolve(sourceRoot, file)))
let manifestSha256 = null
if (staticRoot) {
  assert.ok(process.env.PDF_PANEL_FOCUS_MANIFEST_SHA256 && process.env.PDF_PANEL_FOCUS_SOURCE_ROOT, '冻结模式显式指定manifest SHA和源码快照目录')
  manifestSha256 = digest(await readFile(resolve(staticRoot, '.vite/manifest.json')))
  assert.equal(manifestSha256, process.env.PDF_PANEL_FOCUS_MANIFEST_SHA256)
}
const sourcePdf = process.env.PDF_PANEL_FOCUS_SOURCE_PDF ? resolve(process.env.PDF_PANEL_FOCUS_SOURCE_PDF) : null
const generated = spawnSync(resolve(repo, '.venv/bin/python'), ['-c', `
import base64,json,runpy,sys
from pathlib import Path
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
if len(sys.argv)>1:data=Path(sys.argv[1]).read_bytes()
else:
 factory=runpy.run_path('smart_reporting/report_editor/frontend/smoke/office-pdf-form-settings-server.py')['settings_source']
 data=factory()
print(json.dumps(dict(bytes=base64.b64encode(data).decode(),model=inspect_pdf(data))))
`, ...(sourcePdf ? [sourcePdf] : [])], { cwd: repo, encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 })
assert.equal(generated.status, 0, generated.stderr)
const source = JSON.parse(generated.stdout), bytes = Buffer.from(source.bytes, 'base64')
await writeFile(resolve(directory, 'source.pdf'), bytes)
const port = Number(process.env.PDF_PANEL_FOCUS_PORT ?? 4461)
const server = staticRoot
  ? await preview({ root: frontend, configFile: resolve(frontend, 'vite.config.ts'), build: { outDir: staticRoot }, preview: { host: '127.0.0.1', port, strictPort: true } })
  : await createServer({ root: frontend, configFile: resolve(frontend, 'vite.config.ts'), cacheDir: resolve(directory, 'vite-cache'), server: { host: '127.0.0.1', port, strictPort: true } })
if (!staticRoot) await server.listen()
const base = new URL(server.resolvedUrls.local[0]).origin
const path = '/reports/v1/native/pdf-panel-focus/1', requests = [], errors = [], results = [], failures = [], assets = new Map(), assetChecks = [], assetErrors = []
const modes = [
  ['create', 'addTextField', '.pdf-form-create-panel'],
  ['text-properties', 'textProperties', '.pdf-form-text-properties-panel'],
  ['radio-append', 'addRadioOption', '.pdf-form-radio-extension-panel'],
  ['design', 'deleteField', '.pdf-form-design-panel'],
].filter(([mode]) => !process.env.PDF_PANEL_FOCUS_MODES || process.env.PDF_PANEL_FOCUS_MODES.split(',').includes(mode))
const viewports = process.env.PDF_PANEL_FOCUS_VIEWPORTS?.split(',').map(value => value.split('x').map(Number)) ?? [[1440,900]]
let browser
try {
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  if (staticRoot) page.on('response', response => {
    const url = new URL(response.url()), prefix = '/reports/v1/editor/assets/'
    if (!url.pathname.startsWith(prefix) || !/\.(?:m?js|css)$/.test(url.pathname)) return
    assetChecks.push((async () => {
      const path = decodeURIComponent(url.pathname.slice(prefix.length))
      assert.ok(!path.split('/').includes('..'))
      assert.equal(response.status(), 200)
      const bytes = await response.body(), sha256 = digest(bytes)
      assert.equal(sha256, digest(await readFile(resolve(staticRoot, path))), path)
      assets.set(path, { path, size: bytes.length, sha256 })
    })().catch(error => assetErrors.push(String(error))))
  })
  await page.addInitScript(() => localStorage.clear())
  await page.route(`**${path}/api/**`, async route => {
    const operation = new URL(route.request().url()).pathname.split('/').at(-1)
    requests.push({ operation, method: route.request().method() })
    if (operation === 'context') return route.fulfill({ json: { context: {
      documentId: 'pdf-panel-focus', revision: 1, parentRevision: null, format: 'pdf', origin: 'upload',
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: 'panel-focus.pdf', size: bytes.length, sha256: source.model.sourceSha256, mediaType: 'application/pdf' },
    }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: true } })
    if (operation === 'file') return route.fulfill({ body: bytes, contentType: 'application/pdf' })
    if (operation === 'preview') {
      assert.deepEqual(route.request().postDataJSON().operations, [])
      return route.fulfill({ json: { sourceSha256: source.model.sourceSha256, model: source.model, appliedOperationIndices: [], skippedOperations: [] } })
    }
    return route.fulfill({ status: 500, json: { detail: '面板检查不保存或发布' } })
  })
  await page.route(`**${path}`, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  await page.goto(new URL(path, base).href)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false' && document.querySelector('.pdf-page-content canvas'), null, { timeout: 60000 })
  const operations = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).map(([key,value]) => [key,JSON.parse(value).operations]))
  const before = await operations()
  for (const [width,height] of viewports) for (const [mode,id,selector] of modes) for (const action of ['click','Escape']) {
    await page.setViewportSize({width,height})
    const key = `${mode}-${action}-${width}x${height}`, entry = page.locator(`[data-source-command-id="genoffice.pdf.formDesign.${id}"]`)
    const tab = page.locator('[data-pdf-ribbon-tab="formDesign"]'), home = page.locator('[data-pdf-ribbon-tab="home"]'), panel = page.locator(selector)
    await tab.click(); await entry.click(); await panel.waitFor()
    // 原入口仍可见时的对照。
    await panel.locator('header button').click()
    assert.ok(await entry.evaluate(node => document.activeElement === node))
    await entry.click(); await panel.waitFor(); await home.click()
    const header = panel.locator('header button')
    await header.scrollIntoViewIfNeeded()
    const hit = await header.evaluate(node => {
      const r = node.getBoundingClientRect()
      return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))
    })
    await page.screenshot({path:resolve(directory,`${key}-before.png`)})
    if (action === 'click') await header.click()
    else { await header.focus(); await page.keyboard.press('Escape') }
    assert.ok(await panel.isHidden())
    const focus = await home.evaluate(node => ({ returned: document.activeElement === node, active: document.activeElement?.outerHTML.slice(0,300), selected: node.getAttribute('aria-selected') }))
    await page.screenshot({path:resolve(directory,`${key}-closed.png`)})
    assert.deepEqual(await operations(), before)
    results.push({key,hit,focus,visibleEntryControl:true,draftUnchanged:true})
    if (!hit || !focus.returned) failures.push({key,hit,focus})
  }
  assert.deepEqual(errors, [])
  assert.ok(requests.every(request => ['context','file','preview'].includes(request.operation)))
  await Promise.all(assetChecks)
  assert.deepEqual(assetErrors, [])
  if (staticRoot) {
    assert.equal(digest(await readFile(resolve(staticRoot, '.vite/manifest.json'))), manifestSha256)
    const manifest = JSON.parse(await readFile(resolve(staticRoot, '.vite/manifest.json'), 'utf8'))
    const pdf = Object.values(manifest).find(entry => entry.name === 'pdf-main' && entry.isDynamicEntry)
    assert.ok(pdf && assets.has(pdf.file), '实际PDF模块必须来自所指定冻结构建')
    assert.ok([...assets.keys()].some(path => path.endsWith('.css')))
  }
  const build = { staticRoot, manifestSha256, sourceRoot, sourceHashes }
  await writeFile(resolve(directory,'evidence.json'),JSON.stringify({scope:'real native host / real source PDF and inspect_pdf / styled product panes; HTTP identity-source routes are explicit fixtures; no save/publication',build,source:{input:sourcePdf,sha256:digest(bytes),size:bytes.length,pages:source.model.pages.length},results,failures,requests,assets:[...assets.values()],assetErrors,errors},null,2))
  console.log(JSON.stringify({cases:results.length,failures,requests,errors},null,2))
  assert.deepEqual(failures, [], '切换功能区后关闭非模态面板应回到当前可见页签')
} catch (error) {
  await writeFile(resolve(directory,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,build:{staticRoot,manifestSha256,sourceRoot,sourceHashes},results,failures,requests,assets:[...assets.values()],assetErrors,errors},null,2))
  throw error
} finally {
  await browser?.close()
  if (staticRoot) await new Promise(resolve => server.httpServer.close(resolve))
  else await server.close()
}
