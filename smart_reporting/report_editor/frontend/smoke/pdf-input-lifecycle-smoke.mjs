import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// 独立控制器验收：真实源码、浏览器焦点和指针几何，不涉及 PDF 后端或导出。
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const output = resolve(process.env.PDF_INPUT_EVIDENCE_DIR ?? '/dev/shm/office-pdf-input-lifecycle-verification-20261113')
await mkdir(output, { recursive: true })
const path = '/__pdf-input-lifecycle.html'
const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
body{margin:40px;font:16px sans-serif}#crop{width:260px;margin-top:30px}canvas{background:#edf3fa}button,input{margin:8px}
</style></head><body><main id="root"><button id="open">插入文字</button><input id="search" aria-label="搜索">
<div id="crop"></div></main><script type="module">
import { mountPdfCropCanvas } from '/src/pdf-crop-canvas.ts';
import { bindPdfStaticText } from '/src/pdf-static-text.ts';
import { NativeDraft } from '/src/native-draft.ts';
const root = document.querySelector('#root'), canvas = document.createElement('canvas'); canvas.width=400; canvas.height=500;
const changes=[], statuses=[], sha='a'.repeat(64), pageId='sha256:'+sha+':page:0';
const crop=mountPdfCropCanvas({host:document.querySelector('#crop'),canvas,enabled:()=>true,change:value=>changes.push(value)});
const draft=new NativeDraft({documentId:'pdf-input-lifecycle',revision:1,sourceSha256:sha,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}});
let active=false;
const text=bindPdfStaticText({root,draft,pages:()=>[{pageId,index:0,rotation:0,cropBox:{x:10,y:20,width:300,height:400},mediaBox:{x:0,y:0,width:400,height:500}}],unavailable:()=>null,start:()=>{active=true},stop:()=>{active=false},refresh:async()=>{},status:value=>statuses.push(value)});
document.querySelector('#open').addEventListener('click',()=>text.open());
window.app={crop,text,draft,changes,statuses,pageId,active:()=>active};
</script></body></html>`
const server = await createServer({ root: frontend, configFile: false, cacheDir: resolve(output, 'vite-cache'),
  optimizeDeps: { noDiscovery: true },
  server: { host: '127.0.0.1', port: Number(process.env.PDF_INPUT_PORT ?? 4294), strictPort: true },
  plugins: [{ name: 'pdf-input-fixture', configureServer(vite) { vite.middlewares.use((request, response, next) => {
    if (request.url !== path) return next(); response.setHeader('Content-Type', 'text/html; charset=utf-8'); response.end(html)
  }) } }],
})
let browser, page
const evidence = { errors: [], steps: [], failures: [] }
try {
  await server.listen()
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1000, height: 800 } })
  page.on('pageerror', error => evidence.errors.push(error.message))
  await page.goto(`http://127.0.0.1:${server.config.server.port}${path}`); await page.waitForFunction(() => window.app)
  const input = page.locator('#search'), stage = page.locator('[data-pdf-crop-canvas]'), handle = page.locator('[data-pdf-crop-handle="e"]')
  const geometry = await stage.boundingBox()
  assert.equal(geometry.width, 260); assert.equal(geometry.height, 325); assert.ok(geometry.x > 0 && geometry.y > 0)
  evidence.steps.push({ name: 'real-css-scaled-offset-canvas', geometry })
  async function escape(kind) {
    if (kind === 'consumed') {
      await input.evaluate(element => element.addEventListener('keydown', event => event.preventDefault(), { once: true }))
      await page.keyboard.press('Escape')
    } else if (kind === 'plain') await page.keyboard.press('Escape')
    else await input.evaluate((element, kind) => element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: kind === 'composition', keyCode: kind === '229' ? 229 : 27 })), kind)
  }
  for (const kind of ['consumed', 'composition', '229', 'plain']) {
    await page.evaluate(() => window.app.crop.setMargins([10, 20, 30, 40])); await input.focus()
    const bounds = await handle.boundingBox(), x = bounds.x + bounds.width / 2, y = bounds.y + bounds.height / 2
    await page.mouse.move(x, y); await page.mouse.down(); await escape(kind)
    await page.mouse.move(x + 26, y); await page.mouse.up()
    const actual = await page.evaluate(() => window.app.crop.margins()), expected = kind === 'plain' ? [10, 20, 30, 40] : [10, 20, 20, 40]
    evidence.steps.push({ name: 'crop-escape', kind, actual, expected })
    if (JSON.stringify(actual) !== JSON.stringify(expected)) evidence.failures.push({ component: 'crop', kind, actual, expected })
  }
  async function configure() {
    await page.locator('#open').click(); await page.locator('.pdf-static-text-dialog textarea').fill('Report')
    await page.locator('[data-pdf-static-text-confirm]').click()
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'open', '配置结束应恢复原生对话框打开按钮焦点')
  }
  for (const kind of ['consumed', 'composition', '229', 'plain']) {
    await page.evaluate(() => window.app.text.cancel()); await configure(); await input.focus(); await escape(kind)
    const actual = await page.evaluate(() => window.app.active()), expected = kind !== 'plain'
    evidence.steps.push({ name: 'static-text-escape', kind, active: actual, expected })
    if (actual !== expected) evidence.failures.push({ component: 'static-text', kind, actual, expected })
  }
  assert.deepEqual(evidence.failures, [], '目标消费及组合态 Escape 不应丢弃裁剪拖动或文字落点等待')
  assert.deepEqual(await page.evaluate(() => window.app.draft.operations), [])
  await configure()
  await page.evaluate(() => window.app.text.place(window.app.pageId, [75, 120]))
  const operation = await page.evaluate(() => window.app.draft.operations[0])
  assert.deepEqual(operation.origin, [75, 120]); assert.equal(operation.text, 'Report')
  evidence.steps.push({ name: 'offset-page-origin-retained', origin: operation.origin })
  await page.screenshot({ path: resolve(output, 'pdf-input-lifecycle.png') })
  await page.evaluate(() => { window.app.crop.dispose(); window.app.text.dispose() })
  assert.equal(await stage.count(), 0)
  assert.equal(await page.locator('.pdf-static-text-dialog').count(), 0)
  assert.deepEqual(evidence.errors, []); evidence.passed = true
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  await writeFile(resolve(output, 'pdf-input-lifecycle.json'), JSON.stringify(evidence, null, 2))
  await browser?.close(); await server.close()
}
