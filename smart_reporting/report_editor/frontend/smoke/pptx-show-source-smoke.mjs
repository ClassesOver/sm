// 固定源真实放映native验证：授权/修订为显式夹具，动画数据经实际PPTX桥读取。
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createSlidesPanelsNativeFixture } from './slides-panels-native-fixture.mjs'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = process.env.PPTX_SHOW_SOURCE_MODE === '1'
assert.ok(process.env.PPTX_SHOW_DIRECTORY && process.env.PPTX_SHOW_SOURCE, '显式指定证据目录与来源PPTX')
assert.ok(source || process.env.PPTX_SHOW_STATIC && process.env.PPTX_SHOW_MANIFEST, '冻结模式须显式指定static和manifest')
const output = resolve(process.env.PPTX_SHOW_DIRECTORY); await mkdir(output, { recursive: true })
const evidence = { mode: source ? 'source' : 'frozen', cases: [], errors: [] }
let browser, page, fixture, vite, stage = 'setup'
try {
  let sourceOrigin
  if (source) {
    const { createServer, loadConfigFromFile } = await import('vite')
    const loaded = await loadConfigFromFile({ command: 'serve', mode: 'development' }, resolve(frontend, 'vite.config.ts'))
    vite = await createServer({ ...loaded.config, root: frontend, configFile: false, cacheDir: resolve(output, 'vite-cache'), server: { host: '127.0.0.1', port: 0, cors: true, hmr: false, watch: { ignored: ['**/vite.config.ts', '**/vite.slides-react.ts'] } } })
    await vite.listen(); sourceOrigin = `http://127.0.0.1:${vite.httpServer.address().port}`
  }
  fixture = await createSlidesPanelsNativeFixture({ frontend, sourceOrigin, staticRoot: source ? frontend : resolve(process.env.PPTX_SHOW_STATIC), expectedManifest: process.env.PPTX_SHOW_MANIFEST, sourcePath: resolve(process.env.PPTX_SHOW_SOURCE) })
  await fixture.server.listen(); browser = await chromium.launch({ headless: true }); page = await browser.newPage()
  page.setDefaultTimeout(30000)
  page.on('pageerror', error => evidence.errors.push(error.message)); await fixture.setup(page)
  await page.addInitScript(() => {
    window.__showFrames = []
    let previous = 0
    const sample = time => {
      if (time - previous > 35) {
        previous = time
        const canvas = document.querySelector('.slides-show .ss-frame canvas')
        if (canvas) {
          const { width, height } = canvas, p = canvas.getContext('2d').getImageData(0, 0, width, height).data
          let blue = 0, orange = 0, bx = 0
          for (let i = 0; i < p.length; i += 4) {
            if (p[i] < 100 && p[i + 1] > 60 && p[i + 1] < 180 && p[i + 2] > 150) { blue++; bx += (i / 4) % width }
            if (p[i] > 180 && p[i + 1] > 70 && p[i + 1] < 180 && p[i + 2] < 100) orange++
          }
          const frame = canvas.closest('.ss-frame'), css = getComputedStyle(frame)
          window.__showFrames.push({ time, blue, orange, blueCenterX: blue ? bx / blue : null, width, height,
            counter: document.querySelector('[aria-label="放映页码"]')?.textContent, className: frame.className,
            transform: css.transform, opacity: css.opacity, clipPath: css.clipPath,
            animations: frame.getAnimations().map(a => ({ currentTime: a.currentTime, playState: a.playState })) })
        }
      }
      requestAnimationFrame(sample)
    }
    requestAnimationFrame(sample)
  })
  const overlay = () => page.locator('.slides-show')
  const counter = () => page.locator('[aria-label="放映页码"]').textContent()
  const clear = () => page.evaluate(() => { window.__showFrames = [] })
  const frames = () => page.evaluate(() => window.__showFrames)
  const key = value => page.keyboard.press(value)
  let currentOpener
  const open = async command => {
    currentOpener = command
    console.log(stage, command)
    await page.locator('[data-ribbon-tab="slideShow"]').click()
    await page.locator(`[data-command="${command}"]`).click()
    await overlay().locator('.ss-frame canvas').first().waitFor({ timeout: 90000 })
    await page.waitForTimeout(100)
  }
  const menu = async () => { await overlay().locator('.slideshow').click({ button: 'right', position: { x: 30, y: 30 } }); await overlay().locator('.ctx-menu').first().waitFor() }
  const choose = label => overlay().locator('.ctx-item').filter({ hasText: label }).click()
  const exit = async expectedIndex => {
    await overlay().getByRole('button', { name: '退出放映', exact: true }).click(); await overlay().waitFor({ state: 'detached' })
    if (expectedIndex !== undefined) assert.equal(await page.locator('.slide-row[data-selected="true"] .slide-open').getAttribute('data-slide-index'), String(expectedIndex), '退出应返回最后查看的原始页')
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('data-command')), currentOpener)
  }
  const assertCounter = async text => { await page.waitForFunction(value => document.querySelector('[aria-label="放映页码"]')?.textContent === value, text) }
  const waitInk = async () => { await page.waitForFunction(() => window.__showFrames.some(f => f.blue > 200 && f.orange > 200), null, { timeout: 10000 }) }
  const viewports = process.env.PPTX_SHOW_VIEWPORTS ? JSON.parse(process.env.PPTX_SHOW_VIEWPORTS) : [[1440, 900], [320, 640], [640, 360], [390, 320]]
  for (const [width, height] of viewports) {
    stage = `${width}x${height}:open`; await page.setViewportSize({ width, height }); await fixture.open(page)
    const before = await fixture.draft(page); await clear(); await open('startShow')
    await assertCounter('1 / 3')
    const layout = await overlay().evaluate(node => {
      const exit = node.querySelector('[aria-label="退出放映"]'), r = exit.getBoundingClientRect(), c = node.querySelector('canvas').getBoundingClientRect()
      return { exit: { x: r.x, y: r.y, right: r.right, bottom: r.bottom }, exitHit: exit === document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2), canvas: { x: c.x, y: c.y, right: c.right, bottom: c.bottom } }
    })
    assert.ok(layout.exitHit && layout.exit.x >= 0 && layout.exit.y >= 0 && layout.exit.right <= width && layout.exit.bottom <= height, '退出按钮应在视口内且真实命中')
    assert.ok(layout.canvas.x >= 0 && layout.canvas.y >= 0 && layout.canvas.right <= width + 1 && layout.canvas.bottom <= height + 1, '真实放映画布应在视口内')
    const background = await overlay().locator('.ss-frame canvas').first().evaluate(canvas => {
      const p = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data; let white = 0
      for (let i = 0; i < p.length; i += 4) if (p[i] > 250 && p[i + 1] > 250 && p[i + 2] > 250 && p[i + 3] === 255) white++
      return white / (canvas.width * canvas.height)
    })
    assert.ok(background > .98, '入口隐藏态白色来源背景必须覆盖整张画布，不得二次缩放')
    if (process.env.PPTX_SHOW_LAYOUT_ONLY === '1') {
      assert.ok(source, 'layout-only仅用于source修复预探针')
      await page.screenshot({ path: resolve(output, `background-${width}x${height}.png`) })
      await key('End'); await assertCounter('3 / 3'); await exit(3)
      evidence.cases.push({ width, height, layout, background, lastViewedIndexRestored: true }); continue
    }
    stage = `${width}x${height}:source-animation`; console.log(stage); await key('ArrowRight'); await waitInk(); await page.waitForTimeout(1250)
    await assertCounter('1 / 3'); const sourceFrames = await frames()
    assert.ok(sourceFrames.some(f => f.blue === 0 && f.orange === 0), '首次点击前对象应隐藏')
    const ink = sourceFrames.filter(f => f.blue > 200), sourceArea = Math.max(...ink.map(f => f.blue))
    assert.ok(Math.max(...ink.map(f => f.blueCenterX)) - Math.min(...ink.map(f => f.blueCenterX)) > ink[0].width * .20, '来源动作路径应真实改变横向几何')
    await page.screenshot({ path: resolve(output, `source-${width}x${height}.png`) })
    stage = `${width}x${height}:push`; await clear(); await key('ArrowRight'); await assertCounter('2 / 3'); await page.waitForTimeout(120)
    await page.screenshot({ path: resolve(output, `push-${width}x${height}.png`) }); await page.waitForTimeout(500)
    const pushFrames = await frames(), pushed = pushFrames.filter(f => f.className.includes('ss-anim-push'))
    assert.ok(pushed.length >= 3 && new Set(pushed.map(f => f.transform)).size >= 3 && pushed.some(f => f.animations.some(a => a.currentTime > 0 && a.currentTime < 500)), 'push应有实际CSS时间和变换轨迹')
    stage = `${width}x${height}:morph`; await clear(); await key('ArrowRight'); await assertCounter('3 / 3'); await page.waitForTimeout(160)
    await page.screenshot({ path: resolve(output, `morph-${width}x${height}.png`) }); await page.waitForTimeout(600)
    const morphFrames = await frames(), moved = morphFrames.filter(f => f.blue > 200)
    assert.ok(new Set(moved.map(f => Math.round(f.blueCenterX))).size >= 4 && Math.max(...moved.map(f => f.blueCenterX)) - Math.min(...moved.map(f => f.blueCenterX)) > moved[0].width * .20, 'Morph应有至少四个中间位置')
    stage = `${width}x${height}:navigation`; await key('ArrowRight'); await overlay().locator('.ss-end').waitFor(); await key('ArrowLeft'); assert.equal(await overlay().locator('.ss-end').count(), 0)
    await key('Home'); await assertCounter('1 / 3'); await key('2'); await key('Enter'); await assertCounter('2 / 3')
    await key('b'); await overlay().locator('.ss-black').waitFor(); await key('ArrowRight'); assert.equal(await overlay().locator('.ss-black').count(), 0); await assertCounter('2 / 3')
    await key('w'); await overlay().locator('.ss-white').waitFor(); await overlay().locator('.ss-white').click(); await assertCounter('2 / 3')
    stage = `${width}x${height}:menus`; await menu(); assert.equal(await overlay().locator('.ctx-menu').first().evaluate(node => node.contains(document.activeElement)), true)
    await key('End'); assert.match(await page.evaluate(() => document.activeElement.textContent), /结束放映/); await assertCounter('2 / 3')
    await key('Home'); assert.match(await page.evaluate(() => document.activeElement.textContent), /下一页/)
    await key('Shift+Tab'); assert.match(await page.evaluate(() => document.activeElement.textContent), /结束放映/); await key('Tab'); assert.match(await page.evaluate(() => document.activeElement.textContent), /下一页/)
    await choose('屏幕'); await overlay().locator('.ctx-submenu').waitFor(); await choose('黑屏'); await overlay().locator('.ss-black').waitFor(); await key('b')
    await menu(); await choose('查看所有幻灯片'); assert.equal(await overlay().locator('.ss-grid-item').count(), 3)
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains('ss-grid-cur')), true)
    await key('Escape'); assert.equal(await overlay().locator('.ss-grid').count(), 0); assert.equal(await overlay().count(), 1)
    await menu(); await choose('查看所有幻灯片'); await overlay().locator('.ss-grid-item').nth(2).click(); await assertCounter('3 / 3')
    await menu(); await choose('上次查看'); await assertCounter('2 / 3'); await menu(); await choose('上一页'); await assertCounter('1 / 3')
    await menu(); await key('Escape'); assert.equal(await overlay().locator('.ctx-menu').count(), 0); assert.equal(await overlay().evaluate(node => node.contains(document.activeElement)), true)
    await exit(0); assert.deepEqual(await fixture.draft(page), before)
    stage = `${width}x${height}:draft`; await page.locator('.slide-open[data-slide-index="0"]').click(); await page.locator('#object-select').selectOption('sp_0')
    await page.locator('[data-ribbon-tab="animations"]').click(); await page.locator('[data-command="animationEffect"]').selectOption('pulse'); await page.locator('[data-command="addAnimation"]').click()
    const draft = await fixture.draft(page); assert.equal(draft.at(-1).animations.at(-1).effect, 'pulse')
    await clear(); await open('startShow'); await key('ArrowRight'); await waitInk(); await page.waitForTimeout(1250); await assertCounter('1 / 3')
    await clear(); await key('ArrowRight'); await page.waitForFunction(area => window.__showFrames.some(f => f.blue > area * 1.1), sourceArea, { timeout: 5000 }); await assertCounter('1 / 3')
    await page.screenshot({ path: resolve(output, `draft-${width}x${height}.png`) }); const draftFrames = await frames()
    await key('Tab'); await key('Shift+Tab'); await key('Delete'); await key('Control+v'); await key('Control+z'); assert.deepEqual(await fixture.draft(page), draft)
    await page.waitForTimeout(800); await key('ArrowRight'); await assertCounter('2 / 3'); await exit(2); assert.deepEqual(await fixture.draft(page), draft)
    stage = `${width}x${height}:restart`; await clear(); await open('startShow'); await page.waitForFunction(() => window.__showFrames.some(f => f.blue === 0 && f.orange === 0)); await exit(0); await page.waitForTimeout(700); assert.equal(await overlay().count(), 0)
    stage = `${width}x${height}:hidden-current`; await page.locator('.slide-open[data-slide-index="1"]').click(); await open('startShowCurrent'); await assertCounter('2 / 4'); await key('End'); await assertCounter('4 / 4'); await exit(3); assert.deepEqual(await fixture.draft(page), draft)
    evidence.cases.push({ width, height, layout, background, sourceArea, sourceFrames, pushFrames, morphFrames, draftFrames, sourceAndDraftAnimated: true, pushActuallyAnimated: true, morphActuallyTweened: true, navigationMenuFocusAndBlankPassed: true, hiddenCurrentPlayed: true, draftUnchanged: true, freshRestart: true, lastViewedIndexRestored: true })
  }
  assert.deepEqual(evidence.errors, []); evidence.native = await fixture.finish(); evidence.ok = true
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, mode: evidence.mode, cases: evidence.cases.length, resources: Object.keys(evidence.native.resources).length, saveRequests: evidence.native.saveRequests, downloadEvents: evidence.native.downloadEvents }))
} catch (error) {
  await page?.screenshot({ path: resolve(output, 'failure.png') }).catch(() => {})
  const diagnostics = await page?.evaluate(() => ({ frames: window.__showFrames, currentDraft: Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')), html: document.querySelector('.slides-show')?.outerHTML, body: document.body.innerText, url: location.href })).catch(() => null)
  await writeFile(resolve(output, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, evidence, diagnostics }, null, 2)); throw error
} finally { await browser?.close(); await fixture?.server.close(); await vite?.close() }
