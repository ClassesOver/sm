// 完整native宿主+真实PPTX/动画草稿；source和冻结资源明确区分，不将静态画面冒称播放。
import assert from 'node:assert/strict'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createSlidesPanelsNativeFixture } from './slides-panels-native-fixture.mjs'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = process.env.PPTX_ANIM_SOURCE_MODE === '1'
assert.ok(process.env.PPTX_ANIM_DIRECTORY && process.env.PPTX_ANIM_SOURCE, '显式指定PPTX_ANIM_DIRECTORY/PPTX_ANIM_SOURCE')
assert.ok(source || process.env.PPTX_ANIM_STATIC && process.env.PPTX_ANIM_MANIFEST, '冻结模式须指定static与manifest')
const output = resolve(process.env.PPTX_ANIM_DIRECTORY); await mkdir(output, { recursive: true })
let vite, browser, page, fixture
const evidence = { mode: source ? 'source' : 'frozen', cases: [], errors: [] }
let stage = 'setup'
try {
  let sourceOrigin
  if (source) {
    const { createServer } = await import('vite')
    vite = await createServer({ root: frontend, configFile: resolve(frontend, 'vite.config.ts'), cacheDir: resolve(output, 'vite-cache'), server: { host: '127.0.0.1', port: 0, cors: true } })
    await vite.listen(); sourceOrigin = `http://127.0.0.1:${vite.httpServer.address().port}`
  }
  fixture = await createSlidesPanelsNativeFixture({ frontend, sourceOrigin, staticRoot: source ? frontend : resolve(process.env.PPTX_ANIM_STATIC), expectedManifest: process.env.PPTX_ANIM_MANIFEST, sourcePath: resolve(process.env.PPTX_ANIM_SOURCE) })
  await fixture.server.listen(); browser = await chromium.launch({ headless: true }); page = await browser.newPage()
  await page.addInitScript(() => {
    window.__animationFrames = []
    let sampled = 0
    const sample = time => {
      if (time - sampled > 35) {
        sampled = time
        const canvas = document.querySelector('.slides-animation-preview canvas')
        if (canvas) {
          const { width, height } = canvas, p = canvas.getContext('2d').getImageData(0, 0, width, height).data
          let blue = 0, orange = 0, bx = 0
          for (let i = 0; i < p.length; i += 4) {
            if (p[i] < 100 && p[i + 1] > 60 && p[i + 1] < 180 && p[i + 2] > 150) { blue++; bx += (i / 4) % width }
            if (p[i] > 180 && p[i + 1] > 70 && p[i + 1] < 180 && p[i + 2] < 100) orange++
          }
          window.__animationFrames.push({ time, blue, orange, blueCenterX: blue ? bx / blue : null, width, height })
        }
      }
      requestAnimationFrame(sample)
    }
    requestAnimationFrame(sample)
  })
  page.on('pageerror', error => evidence.errors.push(error.message)); await fixture.setup(page)
  const opener = () => page.locator('[data-command="animationPreview"]')
  const overlay = () => page.locator('.slides-animation-preview')
  const clearFrames = () => page.evaluate(() => { window.__animationFrames = [] })
  const frames = () => page.evaluate(() => window.__animationFrames)
  const pixels = () => overlay().locator('canvas').first().evaluate(canvas => {
    const { width, height } = canvas, p = canvas.getContext('2d').getImageData(0, 0, width, height).data
    let blue = 0, orange = 0, bx = 0
    for (let i = 0; i < p.length; i += 4) {
      if (p[i] < 100 && p[i + 1] > 60 && p[i + 1] < 180 && p[i + 2] > 150) { blue++; bx += (i / 4) % width }
      if (p[i] > 180 && p[i + 1] > 70 && p[i + 1] < 180 && p[i + 2] < 100) orange++
    }
    return { blue, orange, blueCenterX: blue ? bx / blue : null, width, height }
  })
  const waitVisibleInk = async () => { for (let n = 0; n < 100; n++) { if (await overlay().count() === 0) throw Error('动画结束前未观察到真实彩色对象'); const value = await pixels(); if (value.blue > 200 && value.orange > 200) return value; await page.waitForTimeout(25) } throw Error('未观察到真实动画彩色对象') }
  const viewports = process.env.PPTX_ANIM_VIEWPORTS ? JSON.parse(process.env.PPTX_ANIM_VIEWPORTS) : [[1440, 900], [320, 640], [640, 360], [390, 320]]
  for (const [width, height] of viewports) {
    stage = `${width}x${height}:open`; await page.setViewportSize({ width, height }); await fixture.open(page)
    await page.locator('[data-ribbon-tab="animations"]').click(); assert.equal(await opener().isEnabled(), true)
    const before = await fixture.draft(page)
    stage = `${width}x${height}:source-play`; await clearFrames(); await opener().click(); await overlay().locator('canvas').first().waitFor()
    const initial = await pixels()
    const layout = await overlay().evaluate(node => {
      const exit = node.querySelector('button'), r = exit.getBoundingClientRect(), canvas = node.querySelector('canvas').getBoundingClientRect()
      return { exit: { x: r.x, y: r.y, right: r.right, bottom: r.bottom }, exitHit: exit === document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2), canvas: { x: canvas.x, y: canvas.y, right: canvas.right, bottom: canvas.bottom }, width: innerWidth, height: innerHeight }
    })
    await writeFile(resolve(output, `layout-${width}x${height}.json`), JSON.stringify(layout, null, 2))
    assert.ok(layout.exitHit && layout.exit.x >= 0 && layout.exit.y >= 0 && layout.exit.right <= width && layout.exit.bottom <= height, '结束控件必须完整位于视口且实际命中')
    const animated = await waitVisibleInk(); await page.screenshot({ path: resolve(output, `source-playing-${width}x${height}.png`) })
    await overlay().waitFor({ state: 'detached', timeout: 15000 }); assert.equal(await opener().evaluate(node => node === document.activeElement), true)
    const sourceFrames = await frames(); assert.ok(sourceFrames.some(frame => frame.blue === 0 && frame.orange === 0), '完整帧轨迹必须包含入口隐藏态')
    await writeFile(resolve(output, `source-frames-${width}x${height}.json`), JSON.stringify(sourceFrames))
    const moving = sourceFrames.filter(frame => frame.blue > 200), sourceArea = Math.max(...moving.map(frame => frame.blue))
    assert.ok(Math.max(...moving.map(frame => frame.blueCenterX)) - Math.min(...moving.map(frame => frame.blueCenterX)) > initial.width * .20, '真实动作路径须产生横向位移')
    assert.deepEqual(await fixture.draft(page), before)
    stage = `${width}x${height}:draft-add`; await page.locator('[data-command="animationEffect"]').selectOption('pulse'); await page.locator('[data-command="addAnimation"]').click()
    const draft = await fixture.draft(page); assert.equal(draft[0].animations.at(-1).effect, 'pulse'); assert.equal(draft[0].animations.at(-1).append, true)
    stage = `${width}x${height}:draft-play`; await clearFrames(); await opener().click(); await overlay().locator('canvas').first().waitFor(); const draftInitial = await pixels()
    const draftAnimated = await waitVisibleInk(); await page.keyboard.press('Delete'); await page.keyboard.press('Control+v'); assert.deepEqual(await fixture.draft(page), draft)
    await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab'); assert.equal(await overlay().locator('button').evaluate(node => node === document.activeElement), true)
    await page.keyboard.press('ArrowRight'); await page.keyboard.press('Delete'); await page.keyboard.press('Control+z'); assert.deepEqual(await fixture.draft(page), draft)
    await page.waitForFunction(area => window.__animationFrames.some(frame => frame.blue > area * 1.1), sourceArea, { timeout: 10000 })
    await page.screenshot({ path: resolve(output, `draft-playing-${width}x${height}.png`) }); await page.keyboard.press('Escape'); await overlay().waitFor({ state: 'detached' }); assert.equal(await opener().evaluate(node => node === document.activeElement), true)
    assert.deepEqual(await fixture.draft(page), draft)
    const draftFrames = await frames(); assert.ok(draftFrames.some(frame => frame.blue === 0), '草稿预览必须从入口隐藏态开始')
    stage = `${width}x${height}:restart`; await clearFrames(); await opener().click(); await overlay().locator('canvas').first().waitFor()
    await page.waitForFunction(() => window.__animationFrames.some(frame => frame.blue === 0), null, { timeout: 3000 })
    await overlay().locator('.anim-preview-overlay').click(); await overlay().waitFor({ state: 'detached' }); assert.deepEqual(await fixture.draft(page), draft)
    await page.waitForTimeout(1000); assert.equal(await overlay().count(), 0)
    evidence.cases.push({ width, height, initial, animated, draftInitial, draftAnimated, layout, sourceFrames, draftFrames, sourceArea, sourceAutoCompleted: true, sourceAndDraftRendered: true, motionPathMoved: true, draftPulseAreaChanged: true, escapeAndClickEnded: true, restartFresh: true, draftUnchanged: true })
  }
  assert.deepEqual(evidence.errors, []); evidence.native = await fixture.finish(); evidence.ok = true
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, mode: evidence.mode, cases: evidence.cases.length, resources: Object.keys(evidence.native.resources).length, saveRequests: evidence.native.saveRequests, downloadEvents: evidence.native.downloadEvents }))
} catch (error) {
  await page?.screenshot({ path: resolve(output, 'failure.png') }).catch(() => {})
  const diagnostics = await page?.evaluate(() => ({ frames: window.__animationFrames, currentDraft: Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')) })).catch(() => null)
  await writeFile(resolve(output, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, evidence, diagnostics }, null, 2)); throw error
} finally { await browser?.close(); await fixture?.server.close(); await vite?.close() }
