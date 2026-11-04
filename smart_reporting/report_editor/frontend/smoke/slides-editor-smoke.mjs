import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright'

// 使用真实同源服务、授权和持久化；只有可废弃验收报告允许写入。
const config = process.env.REPORT_SLIDES_CONTEXT_FILE
  ? JSON.parse(await readFile(process.env.REPORT_SLIDES_CONTEXT_FILE, 'utf8')) : {}
const url = process.env.REPORT_EDITOR_URL ?? config.editorUrl
if (!url) throw new Error('请设置 REPORT_EDITOR_URL 或 REPORT_SLIDES_CONTEXT_FILE')
const allowMutation = process.env.REPORT_EDITOR_ALLOW_MUTATION === '1'
const output = resolve(process.env.REPORT_EDITOR_EVIDENCE_DIR ?? '../../../../output/slides-editor-smoke')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: process.env.HEADLESS !== '0' })
const result = { mutation: allowMutation, pageErrors: [], apiErrors: [], cspErrors: [], viewports: [] }
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.on('pageerror', error => result.pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && /Content Security Policy|violates.*directive/.test(message.text())) result.cspErrors.push(message.text()) })
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 500) result.apiErrors.push({ path: new URL(response.url()).pathname, status: response.status() }) })
  const opened = await page.goto(url)
  assert.equal(opened.status(), 200)
  assert.ok(opened.headers()['content-security-policy'])
  await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
  const deck = await page.evaluate(async () => {
    const response = await fetch(location.pathname + '/api/deck')
    if (!response.ok) throw new Error('读取幻灯片失败：' + response.status)
    return response.json()
  })
  result.sourceRevision = deck.revision
  result.slideCount = deck.slides.length
  const target = deck.slides[0].elements.find(item => item.editable && item.text.trim())
  assert.ok(target)
  await page.locator('#object-select').selectOption(target.id)
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 })
    await page.waitForFunction(() => document.querySelector('.slides-canvas canvas').getBoundingClientRect().width > 0)
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, page: document.documentElement.scrollWidth, canvas: document.querySelector('.slides-canvas canvas').getBoundingClientRect().width }))
    assert.ok(dimensions.page <= width + 1, JSON.stringify(dimensions))
    result.viewports.push(dimensions)
    await page.screenshot({ path: resolve(output, 'editor-' + width + '.png'), fullPage: true })
  }
  const boundary = await page.evaluate(async sha256 => {
    const denied = await fetch(location.pathname + '/api/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expectedSha256: sha256 }) })
    const foreign = await fetch(location.pathname.replace(/\/\d+$/, '/999999') + '/api/deck')
    return { noCsrf: denied.status, foreignRevision: foreign.status }
  }, deck.sha256)
  assert.equal(boundary.noCsrf, 403)
  assert.ok([403, 404].includes(boundary.foreignRevision))
  result.boundary = boundary
  if (process.env.REPORT_EDITOR_TEST_AI === '1') {
    const expected = '真实 AI 标题验收'
    await page.locator('#ai-instruction').fill('只把第1页的标题改为“' + expected + '”，保留其他文字、页面顺序、主题和对象位置。')
    await page.locator('.ai-submit').click()
    await page.locator('.ai-preview').waitFor({ state: 'visible', timeout: 180000 })
    assert.ok((await page.locator('.ai-edits').innerText()).includes(expected))
    await page.locator('.ai-accept').click()
    await page.waitForFunction(expected => document.querySelector('#object-text').value === expected, expected)
    await page.locator('.undo-button').click()
    assert.equal(await page.locator('#object-text').inputValue(), target.text)
    result.askAI = { candidate: true, accepted: true, undone: true }
  }
  if (process.env.REPORT_EDITOR_TEST_IMAGE === '1') {
    const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/ai/image'), { timeout: 130000 })
    await page.locator('#image-prompt').fill('一张简洁的医疗服务抽象插画，蓝绿色，白色背景，没有文字、数字或图表')
    await page.locator('.image-generate').click()
    const response = await responsePromise
    const payload = await response.json()
    result.imageAI = { status: response.status(), code: payload.detail?.code, reason: payload.detail?.message }
    if (!response.ok()) {
      const retained = await page.evaluate(async () => (await fetch(location.pathname + '/api/deck')).json())
      assert.equal(retained.sha256, deck.sha256)
      assert.equal(retained.revision, deck.revision)
      assert.equal(await page.locator('.image-pending li').count(), 0)
      result.imageAI.originalPreserved = true
      await page.screenshot({ path: resolve(output, 'image-failure.png'), fullPage: true })
    }
    assert.equal(response.status(), 200, payload.detail?.message)
    await page.locator('.image-candidate').waitFor({ state: 'visible' })
    assert.ok(payload.previewDataUrl.startsWith('data:image/'))
    await page.screenshot({ path: resolve(output, 'image-candidate.png'), fullPage: true })
    if (allowMutation) {
      const imageBytes = Buffer.from(payload.previewDataUrl.split(',')[1], 'base64')
      result.imageAI.sha256 = createHash('sha256').update(imageBytes).digest('hex')
      result.imageAI.size = imageBytes.length
      await page.locator('#image-target').selectOption('0')
      await page.locator('.image-add').click()
      assert.equal(await page.locator('.image-pending li').count(), 1)
      result.imageAI.accepted = true
    }
  }
  if (allowMutation) {
    await page.setViewportSize({ width: 1440, height: 1000 })
    const text = '真实 HTTP 编辑往返验收 r' + (deck.revision + 1)
    const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/render-tree') && response.request().method() === 'POST')
    await page.locator('#object-text').fill(text)
    const preview = await responsePromise
    assert.equal(preview.status(), 200)
    const tree = await preview.json()
    const node = tree.slides[0].nodes.find(item => item.sourceId === target.id)
    assert.ok(node.text.lines.flatMap(line => line.runs).map(run => run.text).join('').includes(text))
    await page.locator('#theme-select').selectOption('modern')
    await page.locator('#transition-select').selectOption('fade')
    await page.locator('#animation-effect').selectOption('flyIn')
    await page.locator('#animation-trigger').selectOption('afterPrev')
    await page.locator('#animation-duration').fill('1250')
    await page.locator('#animation-delay').fill('300')
    await page.locator('.animation-add').click()
    const savedPromise = page.waitForResponse(response => response.url().endsWith('/api/save') && response.request().method() === 'POST', { timeout: 120000 })
    await page.locator('[data-action=save]').click()
    const saved = await savedPromise
    assert.equal(saved.status(), 200)
    const receipt = await saved.json()
    assert.equal(receipt.revision, deck.revision + 1)
    assert.ok(receipt.pptx.downloadUrl && receipt.editor.openUrl)
    const download = await page.request.get(receipt.pptx.downloadUrl)
    assert.equal(download.status(), 200)
    const bytes = await download.body()
    assert.equal(createHash('sha256').update(bytes).digest('hex'), receipt.pptx.sha256)
    assert.equal(bytes.length, receipt.pptx.size)
    await writeFile(resolve(output, 'saved.pptx'), bytes)
    await page.locator('.revision-link').click()
    await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
    await page.locator('#object-select').selectOption(target.id)
    assert.equal(await page.locator('#object-text').inputValue(), text)
    assert.equal(await page.locator('#transition-select').inputValue(), 'fade')
    assert.equal(await page.locator('#animation-effect').inputValue(), 'flyIn')
    assert.equal(await page.locator('#animation-trigger').inputValue(), 'afterPrev')
    assert.equal(await page.locator('#animation-duration').inputValue(), '1250')
    assert.equal(await page.locator('#animation-delay').inputValue(), '300')
    if (result.imageAI?.accepted) {
      const reopenedDeck = await page.evaluate(async () => (await fetch(location.pathname + '/api/deck')).json())
      const pictures = slide => slide.elements.filter(item => item.type === 'picture').length
      assert.equal(pictures(reopenedDeck.slides[0]), pictures(deck.slides[0]) + 1)
      result.imageAI.reopened = true
    }
    await page.screenshot({ path: resolve(output, 'reopened-desktop.png'), fullPage: true })
    result.saved = { revision: receipt.revision, size: bytes.length, sha256: receipt.pptx.sha256, validation: receipt.validation }
    await writeFile(resolve(output, 'save-receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 })
  }
  assert.deepEqual(result.pageErrors, [])
  assert.deepEqual(result.apiErrors, [])
  assert.deepEqual(result.cspErrors, [])
  result.ok = true
} catch (error) {
  result.ok = false
  result.error = error.message
  throw error
} finally {
  await writeFile(resolve(output, 'browser-result.json'), JSON.stringify(result, null, 2))
  await browser.close()
}
console.log(JSON.stringify(result))
