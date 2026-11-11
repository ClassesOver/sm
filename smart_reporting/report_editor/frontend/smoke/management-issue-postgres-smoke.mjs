import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { spawn } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input)
const origin = 'http://127.0.0.1:5193'
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const vite = spawn('./node_modules/.bin/vite', ['--config', 'vite.management.config.ts', '--host', '127.0.0.1', '--port', '5193', '--strictPort'], { stdio: 'ignore' })
let browser
try {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(origin + '/management/management.html')).ok) break } catch {}
    await delay(100)
  }
  await mkdir(config.output, { recursive: true })
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 390, height: 1000 } })
  page.setDefaultTimeout(20000)
  await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
  await page.route('**/management/report-issues?**', route => route.fulfill({ contentType: 'text/html', body: html }))
  let signingPosts = 0, closingPosts = 0, closureReads = 0, approvalRequestId, closureRequestId
  const http = [], errors = []
  page.on('pageerror', error => errors.push(error.message))
  // 只桥接到本测试真实服务器；所有业务响应来自原路由和隔离PG。
  // 两次abort发生于服务器已返回200之后，用以验证真实提交后的未知结果恢复。
  await page.route('**/management/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url())
    const response = await route.fetch({ url: config.apiOrigin + url.pathname + url.search,
      headers: { ...request.headers(), ...(config.apiOriginHeader ? { origin: config.apiOriginHeader } : {}), cookie: 'report_management_session=' + config.token } })
    const body = await response.json()
    http.push({ path: url.pathname, method: request.method(), status: response.status(),
      body: url.pathname.endsWith('/me') ? { username: body.username } : body })
    if (request.method() === 'POST' && url.pathname.endsWith('/business-approvals')) {
      assert.equal(response.status(), 200, JSON.stringify(body))
      signingPosts++; approvalRequestId = body.request.requestId
      return route.abort('failed')
    }
    if (request.method() === 'POST' && url.pathname.endsWith('/resolutions')) {
      assert.equal(response.status(), 200, JSON.stringify(body))
      closingPosts++; closureRequestId = body.request.requestId
      return route.abort('failed')
    }
    if (url.pathname.includes('/resolutions/')) closureReads++
    await route.fulfill({ response })
  })
  const target = origin + '/management/report-issues?' + new URLSearchParams({ database: config.database, companyId: config.companyId })
  const openIssue = async () => { await page.getByRole('button', { name: '查看并裁定', exact: true }).click() }
  await page.goto(target)
  await openIssue()
  const signing = page.getByRole('region', { name: '业务预期签认', exact: true })
  await signing.getByRole('button', { name: '签认回归预期', exact: true }).click()
  await signing.getByRole('checkbox', { name: '签认' + (config.caseId ?? 'budget-total') + '的预期', exact: true }).and(page.locator('input:enabled')).check()
  await signing.getByRole('button', { name: '选择独立原件', exact: true }).click()
  await signing.getByRole('button', { name: '读取' + config.sourceTitle, exact: true }).click()
  await signing.getByRole('button', { name: '采用此原文位置', exact: true }).click()
  await signing.getByRole('textbox', { name: '签认理由与独立推导', exact: true }).fill(config.approvalReason ?? '独立原件预算100+200=300，与所选全部回归预期一致。本次为合成业务签认。')
  await signing.getByRole('checkbox', { name: '明确签认所选回归预期', exact: true }).check()
  await signing.getByRole('button', { name: '确认签认并登记', exact: true }).click()
  await signing.getByText('签认结果待确认', { exact: false }).waitFor()
  await page.reload(); await openIssue()
  await signing.getByRole('button', { name: '读取原签认结果', exact: true }).click()
  await signing.getByText('已确认原签认登记', { exact: false }).waitFor()
  await signing.getByRole('button', { name: '用于本次关闭准备检查', exact: true }).click()
  await page.getByRole('button', { name: '检查原件与新报告关系', exact: true }).click()
  await page.getByText('所选回归预期的显式签认本次有效；不等于整报告批准，问题未关闭。', { exact: true }).waitFor()
  const closure = page.getByRole('region', { name: '正式关闭报告问题', exact: true })
  await closure.getByRole('radio', { name: config.mode === 'recalculated' ? '已生成并核对新报告' : '本次不重算，明确裁定保留原报告', exact: true }).check()
  await closure.getByRole('textbox', { name: '关闭裁定理由', exact: true }).fill('已核对正式修复、原始对账及精确回归，结束本次合成问题。')
  if (config.mode !== 'recalculated') await closure.getByRole('textbox', { name: '本次不重算的理由', exact: true }).fill('本次只修复后续规则，原报告保留，不要求重新交付。')
  await closure.getByRole('checkbox', { name: '确认关闭并保留原报告', exact: true }).check()
  await closure.screenshot({ path: config.output + '/closing-form-390.png', animations: 'disabled' })
  await closure.getByRole('button', { name: '确认关闭问题', exact: true }).focus()
  await page.keyboard.press('Enter')
  await closure.getByText('关闭结果待确认', { exact: false }).waitFor()
  await page.reload(); await openIssue()
  const read = closure.getByRole('button', { name: '读取原关闭结果', exact: true })
  await read.waitFor()
  assert(await read.evaluate(node => node === document.activeElement))
  await page.keyboard.press('Enter')
  await closure.getByText('已确认原关闭登记', { exact: false }).waitFor()
  await page.getByText('关闭已登记，当前问题状态已读回。', { exact: true }).waitFor()
  await closure.screenshot({ path: config.output + '/closed-result-390.png', animations: 'disabled' })
  await page.reload(); await openIssue()
  await closure.getByRole('button', { name: '读取本问题关闭记录', exact: true }).click()
  await closure.getByText('已确认原关闭登记', { exact: false }).waitFor()
  await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
  const seriousOrCritical = await page.evaluate(async () => (await window.axe.run('main')).violations
    .filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  assert.equal(signingPosts, 1); assert.equal(closingPosts, 1); assert.equal(closureReads, 2)
  assert.deepEqual(errors, []); assert.deepEqual(seriousOrCritical, []); assert.equal(overflow, false)
  await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
  const evidence = { width: 390, signingPosts, closingPosts, closureReads, approvalRequestId, closureRequestId,
    seriousOrCritical, overflow, transport: '真实管理HTTP与同次隔离PostgreSQL；Vite桥接，无业务响应替身', businessSignoff: 'synthetic', mode: config.mode ?? 'not_recalculated' }
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify(evidence))
} finally {
  await browser?.close()
  vite.kill('SIGTERM')
}
