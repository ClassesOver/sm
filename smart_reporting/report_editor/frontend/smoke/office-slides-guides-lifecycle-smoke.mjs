// 真实 Chromium + 产品标尺/参考线模块的隔离组件夹具；不代表整机 Office 或发布/保存验收。
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import AxeBuilder from '@axe-core/playwright'
import { chromium } from 'playwright'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const output = resolve(process.env.REPORT_EDITOR_EVIDENCE_DIR ?? '/tmp/office-slides-guides-keyboard-20261112')
await mkdir(output, { recursive: true })
const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>参考线生命周期组件验收</title></head><body>
<main><h1>幻灯片参考线</h1><div class="slides-stage"><div class="slides-canvas"></div></div></main>
<script type="module">
import '/src/style.css'; import '/src/office-theme.css'; import '/src/slides.css';
import { mountSlidesGuides } from '/src/slides-guides.ts'; import { mountSlidesRuler } from '/src/slides-ruler.ts';
let host = document.querySelector('.slides-canvas'); const stage = document.querySelector('.slides-stage');
const guides = mountSlidesGuides(() => host, () => ({width:1000,height:500}), 'fixture-guides', () => {});
const ruler = mountSlidesRuler(stage, () => host, () => ({width:1000,height:500}), 'cm', (a,c,d) => guides.pull(a,c,d), () => guides.cancelPull());
guides.setVisible(true); ruler.setVisible(true);
window.view = { guides, ruler, switchHost() { const next = host.cloneNode(false); host.replaceWith(next); host=next; ruler.update(); guides.render() } };
</script><style>body{margin:8px;min-width:0;min-height:0}h1{font-size:18px;margin:0 0 8px}.slides-stage{display:block;min-height:0;width:100%;height:calc(100vh - 64px);padding:38px;overflow:hidden}.slides-canvas{position:relative;width:100%;height:100%;min-height:0;background:white;box-shadow:0 0 0 1px #aaa}</style></body></html>`
const server = await createServer({ root, configFile: false, optimizeDeps: { noDiscovery: true, include: [] }, server: { host: '127.0.0.1', port: 0 }, plugins: [{ name: 'guides-fixture', configureServer(server) {
  server.middlewares.use(async (req, res, next) => {
    if (req.url !== '/guides-fixture') return next()
    res.setHeader('Content-Type', 'text/html'); res.end(await server.transformIndexHtml('/guides-fixture', html))
  })
} }] })
await server.listen()
const url = `http://127.0.0.1:${server.httpServer.address().port}/guides-fixture`
const browser = await chromium.launch({ headless: true })
const evidence = { scope: 'isolated product modules with real pointer capture; no document save', scenarios: [], errors: [], sources: {} }
try {
  for (const viewport of [{width:1440,height:900},{width:640,height:360},{width:390,height:320},{width:320,height:640}]) {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    page.on('pageerror', error => evidence.errors.push(error.message))
    await page.goto(url); await page.waitForFunction(() => window.view && document.querySelector('.ruler-num'))
    await page.keyboard.press('Tab')
    assert.equal(await page.evaluate(() => document.activeElement.matches('.ruler-h .ruler-add')), true)
    await page.evaluate(() => window.view.ruler.update())
    await page.waitForFunction(() => document.querySelector('.ruler-num'))
    assert.equal(await page.evaluate(() => document.activeElement.matches('.ruler-h .ruler-add')), true)
    await page.keyboard.press('Enter')
    assert.equal(await page.evaluate(() => window.view.guides.guides().length), 3)
    await page.keyboard.press('Tab'); await page.keyboard.press('Space')
    assert.equal(await page.evaluate(() => window.view.guides.guides().length), 4)
    await page.keyboard.press('Tab')
    assert.equal(await page.evaluate(() => document.activeElement.matches('.guide-v[role=slider]')), true)
    const protectedKeys=await page.evaluate(()=>{
      const line=document.activeElement,before=JSON.stringify(window.view.guides.guides()),stored=localStorage.getItem('fixture-guides'),records=[]
      for(const key of ['ArrowLeft','ArrowRight','Home','End','Delete','Backspace'])for(const protection of ['composition','legacy','handled']){
        const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();line.dispatchEvent(event)
        records.push({key,protection,preserved:JSON.stringify(window.view.guides.guides())===before&&localStorage.getItem('fixture-guides')===stored,focused:line===document.activeElement,prevented:event.defaultPrevented})
      }
      return records
    })
    for(const record of protectedKeys)assert.ok(record.preserved&&record.focused&&record.prevented===(record.protection==='handled'),JSON.stringify(record))
    await page.evaluate(()=>document.activeElement.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true}));await page.keyboard.press('ArrowRight')
    assert.equal(await page.evaluate(()=>window.view.guides.guides()[0].pos),.5)
    await page.keyboard.press('ArrowRight'); await page.keyboard.press('Shift+ArrowLeft')
    assert.ok(Math.abs(await page.evaluate(() => window.view.guides.guides()[0].pos) - .491) < .00001)
    await page.keyboard.press('Shift+ArrowRight'); await page.keyboard.press('ArrowLeft')
    const focusStyle = await page.evaluate(() => ({width:getComputedStyle(document.activeElement).outlineWidth,style:getComputedStyle(document.activeElement).outlineStyle}))
    assert.equal(focusStyle.width, '2px'); assert.equal(focusStyle.style, 'solid')
    const accessibility = await new AxeBuilder({page}).analyze()
    assert.deepEqual(accessibility.violations, [])
    await page.screenshot({path:resolve(output, `keyboard-${viewport.width}x${viewport.height}.png`)})
    for (let i=0;i<4;i++) await page.keyboard.press('Delete')
    assert.equal(await page.evaluate(() => window.view.guides.guides().length), 0)
    assert.equal(await page.evaluate(() => document.activeElement.matches('.slides-canvas')), true)
    await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Space')
    assert.equal(await page.evaluate(() => window.view.guides.guides().length), 1)
    // 为下面的鼠标生命周期场景重开一个默认夹具，不把测试复位写入产品接口。
    await page.evaluate(() => localStorage.clear()); await page.reload()
    await page.waitForFunction(() => window.view && document.querySelector('.ruler-num'))
    // 位置提示贴近右下边缘时也必须完整可见（直接调用产品拉线预览）。
    await page.evaluate(() => window.view.guides.pull('v', {x:innerWidth-2,y:innerHeight-2}, false))
    const bubble = await page.locator('.ruler-bubble').boundingBox()
    assert.ok(bubble.x >= 0 && bubble.y >= 0 && bubble.x + bubble.width <= viewport.width && bubble.y + bubble.height <= viewport.height, JSON.stringify({viewport,bubble}))
    await page.evaluate(() => window.view.guides.cancelPull())
    const box = await page.locator('.slides-canvas').boundingBox()
    const x = box.x + box.width / 2, y = box.y + box.height * .3
    // 真正鼠标拖动提交，以实际页面比例定位。
    await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(box.x + box.width * .7, y, {steps: 5}); await page.mouse.up()
    const stored = await page.evaluate(() => localStorage.getItem('fixture-guides'))
    assert.ok(Math.abs(JSON.parse(stored)[0].pos - .7) < .015)
    // 真实捕获中的拖动预览：受保护 Escape 保留，普通 Escape 撤回，不写本机存储。
    const protectedDrags=[]
    for(const protection of ['composition','legacy','handled']){
      const current=await page.locator('.guide-v').boundingBox();await page.mouse.move(current.x+current.width/2,y);await page.mouse.down();await page.mouse.move(box.x+box.width*.85,y,{steps:5})
      const preview=await page.evaluate(()=>window.view.guides.guides())
      await page.evaluate(protection=>{const event=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();window.dispatchEvent(event)},protection)
      assert.deepEqual(await page.evaluate(()=>window.view.guides.guides()),preview);assert.equal(await page.locator('.ruler-bubble').isVisible(),true);assert.equal(await page.evaluate(()=>localStorage.getItem('fixture-guides')),stored)
      await page.evaluate(()=>window.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true}));await page.keyboard.press('Escape');assert.deepEqual(await page.evaluate(()=>window.view.guides.guides()),preview)
      await page.keyboard.press('Escape');await page.mouse.up();assert.equal(await page.evaluate(()=>localStorage.getItem('fixture-guides')),stored);assert.deepEqual(await page.evaluate(()=>window.view.guides.guides()),JSON.parse(stored));protectedDrags.push({protection,preview,ordinaryEscapeRolledBack:true,consumedEscapePreserved:true})
    }
    for (const action of ['cancel', 'hide', 'switch', 'render', 'escape']) {
      const before = await page.evaluate(() => window.view.guides.guides())
      const current = await page.locator('.guide-v').boundingBox()
      await page.mouse.move(current.x + current.width / 2, y); await page.mouse.down(); await page.mouse.move(box.x + box.width * .85, y, {steps: 5})
      assert.equal(await page.locator('.ruler-bubble').isVisible(), true)
      if (action === 'escape') await page.keyboard.press('Escape')
      await page.evaluate(action => {
        if (action === 'hide') window.view.guides.setVisible(false)
        if (action === 'switch') window.view.switchHost()
        if (action === 'render') window.view.guides.render()
        if (action === 'cancel') {
          const line = document.querySelector('.guide-v');
          // 取消事件没有鼠标API等价物；使用当前真实捕获的鼠标pointerId。
          line.dispatchEvent(new PointerEvent('pointercancel', {bubbles:true,pointerId:1}))
        }
      }, action)
      await page.mouse.move(box.x + box.width * .9, y); await page.mouse.up()
      assert.deepEqual(await page.evaluate(() => window.view.guides.guides()), before)
      assert.equal(await page.evaluate(() => localStorage.getItem('fixture-guides')), stored)
      assert.equal(await page.locator('.ruler-bubble').isVisible(), false)
      await page.evaluate(() => window.view.guides.setVisible(true))
    }
    // 从标尺拉出一条线，再用真实 pointerup 提交。
    const strip = await page.locator('.ruler-h').boundingBox()
    await page.mouse.move(box.x + box.width * .3, strip.y + 10); await page.mouse.down()
    await page.mouse.move(box.x + box.width * .3, box.y + box.height * .4, {steps: 5})
    const rulerProtected=[]
    for(const protection of ['composition','legacy','handled']){
      await page.evaluate(protection=>{const event=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();window.dispatchEvent(event)},protection)
      assert.equal(await page.locator('.ruler-bubble').isVisible(),true);assert.equal(await page.evaluate(()=>localStorage.getItem('fixture-guides')),stored);rulerProtected.push(protection)
    }
    await page.evaluate(()=>window.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true}));await page.keyboard.press('Escape');assert.equal(await page.locator('.ruler-bubble').isVisible(),true)
    await page.mouse.up()
    assert.equal(await page.evaluate(() => window.view.guides.guides().length), 3)
    const committed = await page.evaluate(() => localStorage.getItem('fixture-guides'))
    await page.mouse.move(box.x + box.width * .3, strip.y + 10); await page.mouse.down()
    await page.mouse.move(box.x + box.width * .3, box.y + box.height * .6, {steps:5})
    await page.keyboard.press('Escape'); await page.mouse.up()
    assert.equal(await page.evaluate(() => localStorage.getItem('fixture-guides')), committed)
    assert.equal(await page.locator('.ruler-bubble').isVisible(), false)

    await page.mouse.move(box.x + box.width * .3, strip.y + 10); await page.mouse.down()
    await page.mouse.move(box.x + box.width * .3, box.y + box.height * .6, {steps: 5})
    await page.evaluate(() => window.view.ruler.setVisible(false)); await page.mouse.up()
    assert.equal(await page.locator('.ruler-bubble').isVisible(), false)
    assert.equal(await page.evaluate(() => localStorage.getItem('fixture-guides')), committed)
    await page.evaluate(() => { window.view.ruler.setVisible(true); document.querySelector('.slides-canvas').style.width='75%'; window.view.ruler.update() })
    await page.waitForFunction(() => Math.abs(Number(document.querySelector('.ruler-h').dataset.rulerZoom) - document.querySelector('.slides-canvas').getBoundingClientRect().width/1000) < .0001)
    await page.screenshot({path:resolve(output, `${viewport.width}x${viewport.height}.png`)})
    await page.evaluate(() => { window.view.ruler.dispose(); window.view.guides.dispose() })
    assert.equal(await page.locator('.ruler,.ruler-corner,.guide-line,.ruler-bubble').count(), 0)
    evidence.scenarios.push({viewport, protectedKeys,protectedDrags,rulerProtected,committedMove:true, rollback:['cancel','hide','switch','render','escape'], keyboard:{add:true,move:true,delete:true,focus:true,axeViolations:accessibility.violations.length}, bubbleInViewport:true, rulerPull:true, rulerEscape:true, hiddenPullCancelled:true, zoom:true, disposal:true})
    await context.close()
  }
  assert.deepEqual(evidence.errors, [])
  for (const file of ['src/slides-guides.ts','src/slides-ruler.ts','src/slides-main.ts','src/slides.css']) evidence.sources[file] = createHash('sha256').update(await readFile(resolve(root,file))).digest('hex')
  evidence.ok = true
} finally {
  await writeFile(resolve(output,'evidence.json'), JSON.stringify(evidence,null,2))
  await browser.close(); await server.close()
}
console.log(JSON.stringify(evidence))
