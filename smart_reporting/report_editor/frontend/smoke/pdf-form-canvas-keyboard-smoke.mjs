import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'
import { inspectPdfFormCanvasKeys } from './pdf-form-canvas-keyboard-check.mjs'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const output = resolve(process.env.PDF_FORM_KEYS_DIRECTORY ?? '/dev/shm/office-pdf-form-canvas-keys-verification-20261113/component')
const base = '/reports/v1/editor/assets/', path = `${base}__form-canvas-keys.html`
await mkdir(output, { recursive: true })
const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>PDF 字段画布</title></head><body><main id="editor"><div id="host"></div></main><script type="module">
import { mountPdfFormCanvas } from '${base}src/pdf-form-canvas.ts';
import { NativeDraft } from '${base}src/native-draft.ts';
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0',editor=document.querySelector('#editor'),host=document.querySelector('#host');
const draft=new NativeDraft({documentId:'form-keys',revision:1,sourceSha256:sha,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}});
const model={sourceSha256:sha,pages:[{pageId,index:0,rotation:0,cropBox:{x:10,y:10,width:200,height:300}}],formDesignWidgets:[{fieldName:'customer',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),pageIndex:0,rect:[20,30,100,54],required:false,removable:true,removalReason:null,designEditable:true}],capabilities:{editFormWidget:true}};
let selected;const controller=mountPdfFormCanvas({editor,host,pageId,viewport:{width:200,height:300,convertToViewportPoint:(x,y)=>[x-10,310-y]},model:()=>model,operations:()=>draft.operations,current:()=>true,selected:()=>selected,select:value=>{selected=value},commit:ops=>{draft.setOperations(ops);controller.sync()},error:error=>{throw error}});
const svg=host.querySelector('svg');svg.style.cssText='display:block;background:#fff;border:1px solid #777';svg.querySelector('rect').style.cssText='fill:#e5f0ff;stroke:#135b92;stroke-width:2';
window.fixture={draft,controller};</script></body></html>`
const server = await createServer({ root: frontend, configFile: resolve(frontend, 'vite.config.ts'), cacheDir: resolve(output, 'vite-cache'), optimizeDeps: { entries: [] }, server: { host: '127.0.0.1', port: Number(process.env.PDF_FORM_KEYS_PORT ?? 4396), strictPort: true }, plugins: [{ name: 'form-canvas-key-fixture', configureServer(vite) { vite.middlewares.use((req, res, next) => { if (req.url?.split('?')[0] !== path) return next(); res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(html) }) } }] })
let browser, page
const evidence = { cases: [], errors: [] }
try {
  await server.listen(); browser = await chromium.launch({ headless: true })
  page = await browser.newPage(); page.on('pageerror', error => evidence.errors.push(error.message))
  await page.goto(`http://127.0.0.1:${server.config.server.port}${path}`); await page.waitForFunction(() => window.fixture)
  const operations = () => page.evaluate(() => structuredClone(window.fixture.draft.operations))
  for (const [width, height] of [[1440, 900], [320, 640], [640, 360], [390, 320]]) {
    await page.setViewportSize({ width, height })
    const rect = page.locator('[data-pdf-form-canvas-widget]')
    const events = await inspectPdfFormCanvasKeys(page, rect, operations)
    await rect.focus(); await page.keyboard.press('Enter'); await page.keyboard.press('ArrowRight')
    assert.deepEqual((await operations())[0].rect, [21, 30, 101, 54])
    await page.keyboard.press('ArrowLeft'); assert.deepEqual(await operations(), [])
    await page.keyboard.press('Escape'); assert.equal(await rect.getAttribute('aria-pressed'), 'false')
    await page.screenshot({ path: resolve(output, `canvas-${width}x${height}.png`) })
    evidence.cases.push({ width, height, events, ordinaryNudgeAndReverse: true })
  }
  await page.evaluate(() => window.fixture.controller.dispose()); assert.equal(await page.locator('svg').count(), 0)
  assert.deepEqual(evidence.errors, []); evidence.ok = true
} catch (error) {
  evidence.error = String(error); await page?.screenshot({ path: resolve(output, 'failure.png') }).catch(() => {}); throw error
} finally {
  await writeFile(resolve(output, 'result.json'), JSON.stringify(evidence, null, 2)); await browser?.close(); await server.close()
}
