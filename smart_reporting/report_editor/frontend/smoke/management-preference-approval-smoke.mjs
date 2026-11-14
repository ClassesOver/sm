// 仅工作流/材料为fixture；使用生产构建、真实HTTP/renderer和SQL留存，不拦截响应。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input)
await mkdir(config.output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
const page = await context.newPage(), errors = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(120000)
const endpoint = '/management/api/v1/configuration/preferences/report-verification'
const hash = content => createHash('sha256').update(content).digest('hex')
async function noOverflow() {
  assert.ok(await page.evaluate(() => {
    const dialog = document.querySelector('[role="dialog"]')
    return document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1
      && (!dialog || dialog.scrollWidth <= dialog.clientWidth + 1)
  }), '页面或验收对话框不应有横向溢出')
}
try {
  const opened = await context.request.get(config.apiOrigin + config.fullOpenPath, { maxRedirects: 0 })
  assert.equal(opened.status(), 303)
  assert.equal(opened.headers().location, config.reportPath)
  await page.goto(config.apiOrigin + '/management/preferences')
  await page.getByLabel('密码', { exact: true }).fill(config.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('heading', { name: '偏好管理', exact: true }).waitFor()
  await page.getByRole('tab', { name: '文本报告', exact: true }).click()
  await page.getByRole('button', { name: '实际报告验收', exact: true }).click()
  await page.getByRole('textbox', { name: '已打开的报告修订地址', exact: true }).fill(config.apiOrigin + config.reportPath)
  const [generated] = await Promise.all([
    page.waitForResponse(response => response.url() === config.apiOrigin + endpoint + '/run' && response.request().method() === 'POST'),
    page.getByRole('button', { name: '关联并验收报告', exact: true }).click(),
  ])
  assert.equal(generated.status(), 200)
  const payload = await generated.json()
  assert.equal(payload.scope, 'server_bound_report_materials')
  assert.equal(payload.bindingValid, true)
  assert.equal(payload.canApply, false)
  assert.match(payload.verificationReceipt.id, /^[0-9a-f-]{36}$/)
  const formats = {}
  for (const [format, entry] of Object.entries(payload.formats)) {
    formats[format] = { status: entry.status, availability: entry.availability,
      issues: entry.issues || [], artifact: null, pdf: null }
    for (const role of ['artifact', 'pdf']) {
      if (!entry[role]) continue
      const { base64, ...identity } = entry[role]
      const bytes = Buffer.from(base64, 'base64')
      assert.equal(bytes.length, identity.size)
      assert.equal(hash(bytes), identity.sha256)
      formats[format][role] = identity
      await writeFile(config.output + '/' + format + '-' + role + '-' + identity.filename, bytes)
    }
  }
  for (const format of ['md', 'pdf', 'word']) assert.ok(formats[format].artifact)
  const result = page.getByRole('region', { name: '实际报告验收结果', exact: true })
  const summary = page.getByRole('region', { name: '全局偏好验收汇总', exact: true })
  await result.waitFor()
  await summary.getByText('已关联 1 条验收记录', { exact: true }).waitFor()
  assert.equal(await summary.locator('details').count(), 0, '汇总仅按需请求，不应自动生成摘要')
  const [prepared] = await Promise.all([
    page.waitForResponse(response => response.url() === config.apiOrigin + endpoint + '/prepare' && response.request().method() === 'POST'),
    summary.getByRole('button', { name: '汇总当前草稿验收', exact: true }).click(),
  ])
  assert.equal(prepared.status(), 200)
  const assessment = await prepared.json()
  assert.equal(assessment.status, 'incomplete')
  assert.equal(assessment.canApply, false)
  assert.ok(assessment.missingRequirements.length > 0)
  assert.equal(assessment.evidenceReferences.length, 1)
  assert.equal(assessment.evidenceReferences[0].id, payload.verificationReceipt.id)
  assert.ok(assessment.missingRequirements.some(gap => gap.reason === 'coverage_missing'))
  assert.ok(assessment.missingRequirements.every(gap => typeof gap.message === 'string' && gap.message.length > 0))
  await summary.getByText(new RegExp(`验收规则版本 ${assessment.contractVersion}`)).waitFor()
  assert.ok((await summary.innerText()).includes('尚未具备全局应用批准'))
  const details = summary.locator('details')
  await details.waitFor()
  assert.equal(await details.locator('summary').innerText(), `查看 ${new Set(assessment.missingRequirements.map(gap => gap.requirementId)).size} 类要求的 ${assessment.missingRequirements.length} 项待验证项`)
  assert.equal(await details.evaluate(element => element.open), false, '缺项默认折叠，避免纵向堆叠')
  assert.equal(await page.getByRole('button', { name: '应用已批准偏好', exact: true }).count(), 0)
  assert.equal(await page.getByRole('button', { name: '确认应用偏好', exact: true }).count(), 0)
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: '读取当前格式验收产物', exact: true }).click(),
  ])
  await download.saveAs(config.output + '/downloaded-report.md')
  const downloaded = await readFile(config.output + '/downloaded-report.md')
  assert.equal(downloaded.length, formats.md.artifact.size)
  assert.equal(hash(downloaded), formats.md.artifact.sha256)
  assert.ok(downloaded.toString('utf8').includes('冻结业务原值 1234.56。'))
  await noOverflow()
  await page.screenshot({ path: config.output + '/approval-desktop-collapsed.png', fullPage: true })
  await details.locator('summary').click()
  assert.equal(await details.locator('li').count(), assessment.missingRequirements.length)
  assert.ok((await details.innerText()).includes(assessment.missingRequirements[0].message))
  assert.ok(await details.locator('ul').evaluate(element => element.clientHeight <= 241))
  await noOverflow()
  await page.screenshot({ path: config.output + '/approval-desktop-expanded.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await noOverflow()
  await page.screenshot({ path: config.output + '/approval-mobile-expanded.png', fullPage: true })
  const cookies = await context.cookies()
  const admin = cookies.find(item => item.name === 'report_management_session')
  const editor = cookies.find(item => item.name === 'report_editor_session')
  assert.ok(admin && admin.httpOnly && admin.path === '/management')
  assert.ok(editor && editor.httpOnly && editor.path === config.reportPath)
  await writeFile(config.output + '/cookie-path-evidence.json', JSON.stringify(cookies.map(({ name, path, httpOnly, sameSite, secure }) =>
    ({ name, path, httpOnly, sameSite, secure })), null, 2))
  await writeFile(config.output + '/approval-evidence.json', JSON.stringify({
    report: payload.report, draftVersion: payload.draftVersion, contentHash: payload.contentHash,
    bindingHash: payload.bindingHash, bindingValid: payload.bindingValid, status: payload.status,
    canApply: payload.canApply, issues: payload.issues || [], verificationReceipt: payload.verificationReceipt,
    formats, summary: assessment, downloadedMarkdown: { size: downloaded.length, sha256: hash(downloaded) },
    workflowMaterials: 'fixture', renderer: 'real', artifactStore: 'actual_sql_chunks',
  }, null, 2))
  assert.deepEqual(errors, [])
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ errors, actualRuns: 1, receiptCount: 1,
    productionIncomplete: true, applyUnavailable: true, cookiePathsVerified: true, workflowMaterials: 'fixture', renderer: 'real' }))
} catch (error) {
  await page.screenshot({ path: config.output + '/failure.png', fullPage: true })
  const secrets = [config.password, config.fullOpenPath.split('/').at(-1),
    ...(await context.cookies()).map(cookie => cookie.value)].filter(Boolean)
  const redact = value => secrets.reduce((text, secret) => text.replaceAll(secret, '[已隐藏]'), String(value))
  const message = redact(error)
  await writeFile(config.output + '/failure.json', JSON.stringify({ error: message, errors: errors.map(redact) }, null, 2))
  throw new Error(message)
} finally { await browser.close() }
