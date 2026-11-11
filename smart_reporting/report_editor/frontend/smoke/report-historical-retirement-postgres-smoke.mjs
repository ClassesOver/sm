import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { spawn } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input)
const origin = 'http://127.0.0.1:5211'
const html = (await readFile(new URL('../index.html', import.meta.url), 'utf8'))
  .replace('src="/src/', 'src="/reports/v1/editor/assets/src/')
const vite = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', '5211', '--strictPort'], { stdio: 'ignore' })
let browser
try {
  let ready = false
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(origin + '/reports/v1/editor/assets/')).ok) { ready = true; break } } catch {}
    await delay(100)
  }
  assert(ready, 'Editor Vite server did not start')
  await mkdir(config.output, { recursive: true })
  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext()
  // 使用真实一次性授权交换；只把隔离服务桥接到同源开发资源，不替换业务响应。
  const opened = await context.request.get(config.apiOrigin + '/reports/v1/editor/open/' + config.grant, { maxRedirects: 0 })
  assert.equal(opened.status(), 303)
  const cookies = (await context.cookies(config.apiOrigin)).map(cookie => ({ ...cookie, domain: '127.0.0.1', secure: false }))
  await context.addCookies(cookies)
  const page = await context.newPage()
  page.setDefaultTimeout(25000)
  const path = '/reports/v1/editor/' + config.reportId + '/' + config.revision
  const http = [], errors = [], viewports = [], downloads = []
  let writes = 0, issuePosts = 0, submission = null, adoptionPosts = 0, adoptionRequest = null, adoptionSubmitted = null
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/reports/v1/editor/**', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.pathname.startsWith('/reports/v1/editor/assets/')) return route.continue()
    if (url.pathname === path) {
      const checked = await route.fetch({ url: config.apiOrigin + path })
      assert.equal(checked.status(), 200)
      return route.fulfill({ status: 200, contentType: 'text/html', body: html })
    }
    // POST 校验只读正文，events 只记观测；单独保留 HTTP 记录，不冒充报告写入。
    const observation = request.method() === 'POST' && ['/api/events', '/api/sources/validate'].some(suffix => url.pathname.endsWith(suffix))
    if (request.method() !== 'GET' && !observation) writes++
    const response = await route.fetch({ url: config.apiOrigin + url.pathname + url.search,
      headers: { ...request.headers(), origin: config.apiOrigin } })
    http.push({ path: url.pathname, method: request.method(), status: response.status(),
      ...(config.knowledge && url.pathname.endsWith('/sources/validate')
        ? { request: request.postDataJSON(), response: await response.json() } : {}) })
    if (config.feedback && request.method() === 'POST' && url.pathname.endsWith('/api/issue-reviews')) {
      assert.equal(response.status(), 200, await response.text())
      submission = request.postDataJSON(); issuePosts++
      return route.abort('failed')
    }
    if (config.adoption && request.method() === 'POST' && url.pathname.endsWith('/api/recalculations')) {
      assert.equal(response.status(), 202, await response.text())
      adoptionRequest = request.postDataJSON(); adoptionSubmitted = await response.json(); adoptionPosts++
      return route.abort('failed')
    }
    return route.fulfill({ response })
  })
  await page.goto(origin + path + (config.knowledge ? '?subject=' + encodeURIComponent(config.subjectId) : ''))
  await page.locator('.ProseMirror').waitFor()
  assert.match(await page.locator('.ProseMirror').innerText(), /70/)
  if (!config.knowledge) await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-shell:not([hidden])').waitFor()
  if (!config.knowledge) await page.locator('.evidence-directory-item').first().waitFor({ state: 'attached' })
  if (config.feedback) {
    const panel = page.locator('.evidence-report-issues')
    await panel.getByText('反馈报告问题', { exact: true }).click()
    await panel.getByRole('button', { name: '选择对象并反馈', exact: true }).click()
    await panel.getByLabel('问题关联对象').selectOption(config.subjectId)
    await panel.getByLabel('问题类型').selectOption('calculation')
    await panel.getByLabel('问题描述与核对依据').fill('本报告项目比率均值70%不代表总体190/300=63.33%，请核对统计方式。')
    await page.screenshot({ path: config.output + '/feedback-before-1440.png', fullPage: true })
    await panel.getByRole('button', { name: '确认提交问题', exact: true }).click()
    await panel.getByText('提交结果未知', { exact: false }).waitFor()
    await page.reload()
    await page.locator('.ProseMirror').waitFor()
    await page.locator('[data-action="sources"]').click()
    await panel.getByRole('button', { name: '读取原问题', exact: true }).click()
    await panel.getByRole('heading', { name: '待处理', exact: true }).waitFor()
    await panel.getByText('本报告项目比率均值70%不代表总体190/300=63.33%，请核对统计方式。', { exact: true }).last().waitFor()
    assert.equal(issuePosts, 1); assert.equal(writes, 1); assert.deepEqual(errors, [])
    await page.screenshot({ path: config.output + '/feedback-readback-1440.png', fullPage: true })
    await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
    await writeFile(config.output + '/browser-evidence.json', JSON.stringify({
      scope: '完整Editor真实入口提交及真实HTTP/隔离PG读回；200后主动丢响应，仅GET恢复，无自动重提',
      issuePosts, unknownResponseReadback: true, ...submission, writes, http, errors,
    }, null, 2))
  } else if (config.adoption) {
    const panel = page.locator('.evidence-directory > .evidence-policy-adoption')
    await panel.getByText('采用新业务口径', { exact: true }).click()
    await panel.getByRole('button', { name: '选择已发布口径', exact: true }).click()
    const policy = panel.getByLabel('目标口径（最新发布版本）')
    await policy.waitFor()
    const option = await policy.locator('option').evaluateAll(nodes => nodes.find(node => node.textContent.includes('C02合计执行率') && node.textContent.includes('v3'))?.value)
    assert.notEqual(option, undefined)
    await policy.selectOption(option)
    await panel.getByRole('button', { name: '核对变更与问题', exact: true }).click()
    const question = panel.locator('fieldset')
    await question.waitFor()
    const metric = question.locator('select')
    const metricOption = await metric.locator('option').evaluateAll(nodes => nodes.find(node => node.textContent.includes('预算执行率（合计比率）') && node.textContent.includes('v2'))?.value)
    assert.notEqual(metricOption, undefined)
    await metric.selectOption(metricOption)
    await question.locator('textarea').fill('使用合计比率，拒绝项目比率均值。')
    await page.screenshot({ path: config.output + '/adoption-confirmation-1440.png', fullPage: true })
    await panel.getByRole('button', { name: '确认采用并生成新报告', exact: true }).click()
    await panel.getByText('结果未知，请读取原请求进度', { exact: false }).waitFor()
    await page.reload()
    await page.locator('.ProseMirror').waitFor()
    await page.locator('[data-action="sources"]').click()
    await panel.getByRole('button', { name: '读取新口径任务进度', exact: true }).click()
    await panel.locator(':scope > details > p[role="status"]').filter({ hasText: /已生成文件可单独读取|新报告已生成/ }).waitFor()
    assert.equal(adoptionPosts, 1); assert.deepEqual(errors, [])
    await page.screenshot({ path: config.output + '/adoption-readback-1440.png', fullPage: true })
    await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
    await writeFile(config.output + '/browser-evidence.json', JSON.stringify({
      scope: '完整Editor读取实际发布候选/预检，逐题选择并确认；真实202后丢响应，刷新仅GET恢复同任务',
      adoptionPosts, unknownResponseReadback: true, request: adoptionRequest, submitted: adoptionSubmitted, writes, http, errors,
    }, null, 2))
  } else {
  let knowledge = null
  if (config.knowledge) {
    const panel = page.getByRole('region', { name: '业务知识依据', exact: true })
    const supportText = '当前正文支持关系：' + (config.expectedSupport === 'supported' ? '有依据' : '待核实')
    try { await panel.getByText(supportText, { exact: true }).waitFor() }
    catch (error) {
      await writeFile(config.output + '/failure-http.json', JSON.stringify(http, null, 2))
      await writeFile(config.output + '/failure-dom.json', JSON.stringify({ errors, text: await page.locator('.evidence-shell').innerText() }, null, 2))
      await page.screenshot({ path: config.output + '/failure.png', fullPage: true })
      throw error
    }
    const toggle = panel.locator('.evidence-knowledge-toggle')
    await toggle.click()
    await panel.locator('blockquote').getByText(config.quote, { exact: true }).waitFor()
    await toggle.focus(); await page.keyboard.press('Enter')
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false')
    await page.keyboard.press('Enter')
    await panel.locator('blockquote').getByText(config.quote, { exact: true }).waitFor()
    assert.equal(await toggle.getAttribute('aria-expanded'), 'true')
    assert(!((await panel.innerText()).includes(config.excludedQuote)))
    knowledge = { subjectId: config.subjectId, supportText: await panel.locator('.evidence-knowledge-status').innerText(),
      quote: await panel.locator('blockquote').innerText(), keyboardToggleVerified: true }
  } else {
  const factLink = page.locator('.evidence-directory-item').filter({ hasText: '预算执行率' }).first()
  await factLink.click()
  await page.locator('.evidence-fact-value').filter({ hasText: '70' }).waitFor()
  const metadata = page.locator('.evidence-fact-metadata')
  await metadata.getByText('rate · 版本 1', { exact: true }).waitFor()
  await metadata.getByText(config.basisId, { exact: true }).waitFor()
  }
  await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
  for (const width of [1440, 1280, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    const seriousOrCritical = await page.evaluate(async () => (await window.axe.run('main')).violations
      .filter(item => ['serious', 'critical'].includes(item.impact)).map(item => ({ id: item.id, nodes: item.nodes.map(node => ({ target: node.target, html: node.html, failure: node.failureSummary })) })))
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    await page.screenshot({ path: config.output + (config.knowledge ? '/knowledge-' : '/historical-fact-') + width + '.png', fullPage: true })
    viewports.push({ width, seriousOrCritical, overflow })
    await writeFile(config.output + '/axe-' + width + '.json', JSON.stringify(seriousOrCritical, null, 2))
    assert.equal(overflow, false); assert.deepEqual(seriousOrCritical, [])
  }
  for (const file of config.downloads) {
    const url = new URL(file.url)
    const response = await context.request.get(config.apiOrigin + url.pathname + url.search)
    assert.equal(response.status(), 200)
    const bytes = await response.body()
    const sha256 = createHash('sha256').update(bytes).digest('hex')
    assert.equal(bytes.length, file.size); assert.equal(sha256, file.sha256)
    await writeFile(config.output + '/historical.' + file.format, bytes)
    downloads.push({ format: file.format, size: bytes.length, sha256, status: response.status() })
  }
  await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
  assert.equal(writes, 0); assert.deepEqual(errors, [])
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({
    scope: '完整Editor真实入口、原会话授权、真实隔离HTTP/PG；受控模型和DuckDB原始行，不是StarRocks或业务签认',
    oldValue: '70', metricRevision: 1, basisId: config.basisId, writes, viewports, downloads, http, errors, knowledge,
  }, null, 2))
  console.log(JSON.stringify({ writes, viewports, downloads }))
  }
} finally {
  for (const context of browser?.contexts() ?? []) {
    for (const page of context.pages()) await page.unrouteAll({ behavior: 'wait' })
  }
  await browser?.close()
  vite.kill('SIGTERM')
  await new Promise(resolve => vite.exitCode !== null ? resolve() : vite.once('exit', resolve))
}
