import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// 隔离真实产品参考线与CSS；验证鼠标到键盘的焦点交接，不是PPTX保存或桌面实机验收。
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const output = resolve(process.env.SLIDES_GUIDES_EVIDENCE_DIR ?? '/dev/shm/office-slides-guides-pointer-focus-verification-20261113')
await mkdir(output, { recursive: true })
const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>参考线指针焦点</title></head><body>
<main><h1>参考线指针焦点</h1><input id="outside" aria-label="外部文字输入"><div class="slides-stage"><div class="slides-canvas"></div></div></main>
<script type="module">
import '/src/style.css';import '/src/office-theme.css';import '/src/slides.css';
import {mountSlidesGuides} from '/src/slides-guides.ts';import {mountSlidesRuler} from '/src/slides-ruler.ts';
const host=document.querySelector('.slides-canvas'),stage=document.querySelector('.slides-stage');
const guides=mountSlidesGuides(()=>host,()=>({width:1000,height:500}),'pointer-focus-guides',()=>{});
const ruler=mountSlidesRuler(stage,()=>host,()=>({width:1000,height:500}),'cm',(a,c,d)=>guides.pull(a,c,d),()=>guides.cancelPull());
guides.setVisible(true);ruler.setVisible(true);window.view={guides,ruler};
</script><style>body{margin:24px;min-width:0}h1{font-size:20px}.slides-stage{display:block;position:relative;width:760px;height:520px;min-height:0;padding:40px;margin-top:20px}.slides-canvas{position:relative;width:500px;height:250px;min-height:0;background:white}</style></body></html>`
const server = await createServer({ root: frontend, configFile: false, cacheDir: resolve(output, 'vite-cache'), optimizeDeps: { noDiscovery: true }, server: { host: '127.0.0.1', port: 0 },
  plugins: [{ name: 'guide-pointer-focus', configureServer(vite) { vite.middlewares.use((request, response, next) => {
    if (request.url !== '/guide-pointer-focus') return next(); response.setHeader('Content-Type', 'text/html; charset=utf-8'); response.end(html)
  }) } }],
})
let browser, page
const evidence = { errors: [], cases: [], failures: [] }
try {
  await server.listen()
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  page.on('pageerror', error => evidence.errors.push(error.message))
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/guide-pointer-focus`)
  await page.waitForFunction(() => window.view && document.querySelector('.ruler-num'))
  for (const axis of ['v', 'h']) for (const gesture of ['click', 'drag']) {
    await page.reload(); await page.waitForFunction(() => window.view && document.querySelector('.ruler-num'))
    await page.locator('#outside').focus()
    const canvas = await page.locator('.slides-canvas').boundingBox(), line = page.locator(`.guide-${axis}`), bounds = await line.boundingBox()
    const x = axis === 'v' ? bounds.x + bounds.width / 2 : canvas.x + canvas.width * .25
    const y = axis === 'h' ? bounds.y + bounds.height / 2 : canvas.y + canvas.height * .25
    const index = axis === 'v' ? 0 : 1, direction = axis === 'v' ? 'ArrowRight' : 'ArrowDown'
    await page.mouse.move(x, y); await page.mouse.down()
    const capture = await line.evaluate(element => element.hasPointerCapture(1))
    if (gesture === 'drag') await page.mouse.move(axis === 'v' ? canvas.x + canvas.width * .7 : x, axis === 'h' ? canvas.y + canvas.height * .7 : y, { steps: 5 })
    await page.mouse.up()
    const before = await page.evaluate(index => window.view.guides.guides()[index].pos, index)
    const focused = await page.evaluate(axis => document.activeElement.matches(`.guide-${axis}[role=slider]`), axis)
    await page.keyboard.press(direction)
    const after = await page.evaluate(index => window.view.guides.guides()[index].pos, index)
    const expected = before + (axis === 'v' ? .001 : .002)
    const record = { axis, gesture, canvas, capture, focused, before, after, expected }
    evidence.cases.push(record)
    if (!capture || !focused || Math.abs(after - expected) > .000001) evidence.failures.push(record)
  }
  assert.deepEqual(evidence.failures, [], '鼠标点击/拖动参考线后方向键应归属于该参考线')
  await page.screenshot({ path: resolve(output, 'guide-pointer-focus.png') })
  await page.evaluate(() => { window.view.ruler.dispose(); window.view.guides.dispose() })
  assert.equal(await page.locator('.ruler,.guide-line,.ruler-bubble').count(), 0)
  assert.deepEqual(evidence.errors, []); evidence.passed = true
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  await writeFile(resolve(output, 'result.json'), JSON.stringify(evidence, null, 2))
  await browser?.close(); await server.close()
}
