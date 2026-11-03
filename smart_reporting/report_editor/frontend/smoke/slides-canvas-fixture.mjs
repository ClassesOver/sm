import { createServer } from 'node:http'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { join, extname } from 'node:path'
import { chromium } from 'playwright'
import assert from 'node:assert/strict'

const engine = fileURLToPath(new URL('../../../reporting/slides_engine/', import.meta.url))
const staticRoot = fileURLToPath(new URL('../../static/slides/', import.meta.url))
const evidence = fileURLToPath(new URL('../../../../.superpowers/sdd/2026-11-03-pptx-completion/canvas-evidence/', import.meta.url))
await mkdir(evidence, { recursive: true })
const source = join(engine, 'packages/pptx-engine/tests/fixtures/01_standard_business.pptx')
let current = source
let revision = 1
function engineRun(script, input) {
  const request = join(evidence, 'request.json')
  const written = spawnSync('node', ['-e', 'require("fs").writeFileSync(process.argv[1],process.argv[2])', request, JSON.stringify(input)])
  assert.equal(written.status, 0)
  const process = spawnSync('node_modules/.bin/tsx', ['bridge/' + script, request], { cwd: engine, encoding: 'utf8' })
  assert.equal(process.status, 0, process.stderr)
  return JSON.parse(process.stdout)
}
let inspected = engineRun('edit-pptx.ts', { action: 'inspect', input: current })
const cookies = 'report_slides_csrf=fixture; Path=/'
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost')
    const send = value => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)) }
    if (url.pathname.includes('/assets/')) {
      const path = join(staticRoot, 'assets', url.pathname.split('/assets/')[1])
      res.setHeader('Content-Type', extname(path) === '.js' ? 'application/javascript' : 'text/css')
      res.end(await readFile(path)); return
    }
    if (url.pathname.endsWith('/api/deck')) return send({ ...inspected, sha256: 'a'.repeat(64), revision })
    if (url.pathname.endsWith('/api/render-tree')) {
      if (req.method === 'POST') {
        let body = ''; for await (const data of req) body += data
        const payload = JSON.parse(body)
        const output = join(evidence, 'preview.pptx')
        engineRun('edit-pptx.ts', { ...payload, action: 'edit', input: current, output })
        return send(engineRun('render-pptx.ts', { input: output }))
      }
      return send(engineRun('render-pptx.ts', { input: current }))
    }
    if (url.pathname.endsWith('/api/charts')) return send({ charts: [] })
    if (url.pathname.endsWith('/api/save')) {
      let body = ''; for await (const data of req) body += data
      const payload = JSON.parse(body)
      const output = join(evidence, 'saved.pptx')
      engineRun('edit-pptx.ts', { ...payload, action: 'edit', input: current, output })
      await writeFile(join(evidence, 'save-payload.json'), JSON.stringify(payload, null, 2))
      current = output; revision += 1
      inspected = engineRun('edit-pptx.ts', { action: 'inspect', input: current })
      return send({ revision, validation: { issues: [] }, pptx: { downloadUrl: '/download/saved.pptx' }, editor: { openUrl: '/reports/v1/slides/fixture/' + revision } })
    }
    if (url.pathname.includes('/api/')) { res.writeHead(404); res.end(); return }
    res.setHeader('Content-Type', 'text/html'); res.setHeader('Set-Cookie', cookies)
    res.end(await readFile(join(staticRoot, 'slides.html')))
  } catch (error) { res.writeHead(500); res.end(String(error)) }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = 'http://127.0.0.1:' + server.address().port
const browser = await chromium.launch({ headless: true })
const errors = []
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.on('pageerror', error => errors.push(String(error)))
  await page.goto(base + '/reports/v1/slides/fixture/1')
  await page.locator('.slides-canvas canvas').first().waitFor()
  await page.waitForTimeout(300)
  const original = inspected.slides[0].elements.find(item => item.editable && item.text.trim())
  assert.ok(original)
  await page.locator('#object-select').selectOption(original.id)
  const rect = await page.locator('.slides-canvas canvas').first().boundingBox()
  const scale = rect.width / (inspected.size.cx / 9525)
  const box = original.geometry
  const x = rect.x + (box.x + box.width / 2) * scale
  const y = rect.y + (box.y + box.height / 2) * scale
  await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + 40, y + 25, { steps: 10 }); await page.mouse.up()
  await page.waitForTimeout(150)
  const moved = Number(await page.locator('[name=x]').inputValue())
  assert.ok(moved > box.x + 10, 'real Konva drag must change object geometry')
  const newY = Number(await page.locator('[name=y]').inputValue())
  const anchorX = rect.x + (moved + box.width) * scale
  const anchorY = rect.y + (newY + box.height) * scale
  await page.mouse.move(anchorX, anchorY); await page.mouse.down(); await page.mouse.move(anchorX + 35, anchorY + 22, { steps: 10 }); await page.mouse.up()
  await page.waitForTimeout(150)
  const finalX = Number(await page.locator('[name=x]').inputValue())
  const resized = Number(await page.locator('[name=width]').inputValue())
  assert.ok(Math.abs(finalX - moved) <= 1, 'bottom-right resize keeps the top-left anchor')
  assert.ok(resized > box.width + 10, 'real Konva transformer must change width')
  const previewResponse = page.waitForResponse(response => response.url().endsWith('/api/render-tree') && response.request().method() === 'POST')
  await page.locator('#object-text').fill('浏览器实时文字预览验证')
  const previewTree = await (await previewResponse).json()
  const previewNode = previewTree.slides[0].nodes.find(node => node.sourceId === original.id)
  assert.ok(previewNode.text.lines.flatMap(line => line.runs).map(run => run.text).join('').includes('浏览器实时文字预览验证'))
  await page.waitForFunction(() => document.querySelector('.canvas-status').textContent.includes('点击对象选择'))
  assert.equal(await page.evaluate(() => document.elementsFromPoint(40, 40)[0].classList.contains('image-preview')), false)
  assert.ok(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1), 'desktop shell fits viewport')
  await page.screenshot({ path: join(evidence, 'desktop.png'), fullPage: true })
  await page.route('**/api/ai/start', route => route.fulfill({ json: { editId: 'preview-ai' } }))
  await page.route('**/api/ai/preview-ai?wait_ms=20000', route => route.fulfill({ json: { editId: 'preview-ai', status: 'succeeded', proposal: { summary: 'AI预览测试', edits: [{ slideIndex: 0, elementId: original.id, text: 'AI候选画布文字' }], order: inspected.slides.map(slide => slide.slideIndex) } } }))
  await page.route('**/api/ai/preview-ai/accept', route => route.fulfill({ json: { accepted: true } }))
  await page.locator('#ai-instruction').fill('更新标题')
  await page.locator('.ai-submit').click()
  await page.locator('.ai-preview').waitFor({ state: 'visible' })
  let aiPreviewResponse = page.waitForResponse(response => response.url().endsWith('/api/render-tree') && response.request().method() === 'POST')
  await page.locator('.ai-accept').click()
  let aiTree = await (await aiPreviewResponse).json()
  assert.ok(aiTree.slides[0].nodes.find(node => node.sourceId === original.id).text.lines.flatMap(line => line.runs).map(run => run.text).join('').includes('AI候选画布文字'))
  await page.waitForFunction(() => document.querySelector('.canvas-status').textContent.includes('点击对象选择'))
  aiPreviewResponse = page.waitForResponse(response => response.url().endsWith('/api/render-tree') && response.request().method() === 'POST')
  await page.locator('.undo-button').click()
  aiTree = await (await aiPreviewResponse).json()
  assert.ok(aiTree.slides[0].nodes.find(node => node.sourceId === original.id).text.lines.flatMap(line => line.runs).map(run => run.text).join('').includes('浏览器实时文字预览验证'))
  await page.waitForFunction(() => document.querySelector('.canvas-status').textContent.includes('点击对象选择'))
  let releaseSave
  await page.route('**/api/save', async route => { await new Promise(resolve => { releaseSave = resolve }); await route.continue() })
  await page.locator('[data-action=save]').click()
  await page.waitForFunction(() => document.querySelector('#report-editor').inert)
  assert.equal(await page.locator('#object-text').isDisabled(), true)
  releaseSave()

  await page.locator('.revision-link').waitFor()
  assert.equal(await page.locator('[data-action=save]').isDisabled(), true)
  await page.locator('.revision-link').click()
  await page.locator('.slides-canvas canvas').first().waitFor()
  await page.locator('#object-select').selectOption(original.id)
  assert.equal(Number(await page.locator('[name=x]').inputValue()), finalX)
  assert.equal(Number(await page.locator('[name=width]').inputValue()), resized)
  assert.ok((await page.locator('#object-text').inputValue()).includes('浏览器实时文字预览验证'))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(250)
  const mobileWidth = await page.evaluate(() => ({ viewport: innerWidth, page: document.documentElement.scrollWidth, canvas: document.querySelector('.slides-canvas canvas').getBoundingClientRect().width }))
  assert.ok(mobileWidth.page <= mobileWidth.viewport + 1, JSON.stringify(mobileWidth))
  assert.ok(mobileWidth.canvas > 300 && mobileWidth.canvas <= 390)
  await page.screenshot({ path: join(evidence, 'mobile.png'), fullPage: true })
  assert.deepEqual(errors, [])
  await writeFile(join(evidence, 'result.json'), JSON.stringify({ moved, resized, mobileWidth, errors, savedRevision: revision }, null, 2))
  console.log(JSON.stringify({ moved, resized, mobileWidth, savedRevision: revision }))
} finally { await browser.close(); server.close() }
