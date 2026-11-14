// 工作流和冻结报告材料由Python fixture提供；所有HTTP、会话及renderer实际执行。
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
const verification = '/management/api/v1/configuration/preferences/report-verification'
const editorApi = config.reportPath + '/api/preference-verification'
async function openGrant(path) {
  // APIRequestContext与页面共用Cookie存储，验证真实303换取限定路径HttpOnly Cookie。
  const response = await context.request.get(config.apiOrigin + path, { maxRedirects: 0 })
  assert.equal(response.status(), 303)
  assert.equal(response.headers().location, config.reportPath)
  const cookie = (await context.cookies(config.apiOrigin + config.reportPath)).find(item => item.name === 'report_editor_session')
  assert.ok(cookie && cookie.httpOnly && cookie.path === config.reportPath)
}
try {
  await openGrant(config.fullOpenPath)
  await page.goto(config.apiOrigin + '/management/preferences')
  await page.getByLabel('密码', { exact: true }).fill(config.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('heading', { name: '偏好管理', exact: true }).waitFor()
  await page.getByRole('tab', { name: '文本报告', exact: true }).click()
  await page.getByRole('button', { name: '实际报告验收', exact: true }).click()
  await page.getByRole('textbox', { name: '已打开的报告修订地址', exact: true }).fill(config.apiOrigin + config.reportPath)
  const [response] = await Promise.all([
    page.waitForResponse(response => response.url() === config.apiOrigin + verification + '/run' && response.request().method() === 'POST'),
    page.getByRole('button', { name: '关联并验收报告', exact: true }).click(),
  ])
  assert.equal(response.status(), 200)
  const payload = await response.json()
  assert.equal(payload.scope, 'server_bound_report_materials')
  assert.equal(payload.canApply, false)
  assert.equal(payload.bindingValid, true)
  assert.equal(payload.formats.md.readback.status, 'passed')
  for (const format of ['xlsx', 'pptx']) {
    assert.equal(payload.formats[format].availability, 'unavailable')
    assert.equal(payload.formats[format].artifact, null)
  }
  const formats = {}
  for (const [format, item] of Object.entries(payload.formats)) {
    formats[format] = { availability: item.availability, status: item.status, issues: item.issues,
      readback: item.readback, artifact: null }
    if (!item.artifact) continue
    const { base64, ...identity } = item.artifact
    const bytes = Buffer.from(base64, 'base64')
    assert.equal(bytes.length, identity.size)
    assert.equal(createHash('sha256').update(bytes).digest('hex'), identity.sha256)
    formats[format].artifact = identity
    await writeFile(config.output + '/' + identity.filename, bytes)
  }
  assert.ok(formats.md.artifact && formats.pdf.artifact && formats.word.artifact)
  await page.getByRole('region', { name: '实际报告验收结果', exact: true }).waitFor()
  assert.ok((await page.getByRole('dialog').innerText()).includes('仍未获应用批准')
    || (await page.getByRole('dialog').innerText()).includes('未通过或尚未完成'))
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: '读取当前格式验收产物', exact: true }).click(),
  ])
  await download.saveAs(config.output + '/report.md')
  const downloaded = await readFile(config.output + '/report.md')
  assert.equal(downloaded.length, formats.md.artifact.size)
  assert.equal(createHash('sha256').update(downloaded).digest('hex'), formats.md.artifact.sha256)
  const markdown = downloaded.toString('utf8'), start = '<!-- report-signature:v1 -->', end = '<!-- /report-signature:v1 -->'
  assert.ok(markdown.includes('冻结业务原值 1234.56。'))
  assert.equal(markdown.split(start).length, 2)
  assert.equal(markdown.split(end).length, 2)
  assert.ok(markdown.trimEnd().endsWith(end))
  assert.deepEqual(markdown.split(start)[1].split(end)[0].split('\n').map(line => line.trim())
    .filter(Boolean).map(line => line.replace(/\\([^\w\s])/g, '$1')), config.expectedMarkdownSignature)
  assert.ok((await page.getByRole('dialog').innerText()).includes('独立回读：通过'))
  await page.screenshot({ path: config.output + '/verification-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1))
  await page.screenshot({ path: config.output + '/verification-mobile.png', fullPage: true })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await writeFile(config.output + '/artifact-evidence.json', JSON.stringify({ report: payload.report,
    draftVersion: payload.draftVersion, contentHash: payload.contentHash, bindingHash: payload.bindingHash,
    bindingValid: payload.bindingValid, status: payload.status, canApply: payload.canApply,
    issues: payload.issues || [], formats, expectedMarkdownSignature: config.expectedMarkdownSignature,
    workflowMaterials: 'fixture', renderer: 'real' }, null, 2))

  await page.getByRole('dialog').locator('.ant-modal-close').click()
  await openGrant(config.limitedOpenPath)
  await page.getByRole('button', { name: '实际报告验收', exact: true }).click()
  await page.getByRole('textbox', { name: '已打开的报告修订地址', exact: true }).fill(config.apiOrigin + config.reportPath)
  const [rejected] = await Promise.all([
    page.waitForResponse(response => response.url() === config.apiOrigin + editorApi && response.request().method() === 'GET'),
    page.getByRole('button', { name: '关联并验收报告', exact: true }).click(),
  ])
  assert.equal(rejected.status(), 403)
  await page.getByRole('alert').filter({ hasText: '完整编辑权限' }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/management/preferences')
  assert.equal((await context.request.get(config.apiOrigin + '/management/api/v1/me')).status(), 200)
  const cookies = await context.cookies()
  const admin = cookies.find(item => item.name === 'report_management_session')
  const editor = cookies.find(item => item.name === 'report_editor_session')
  assert.ok(admin && admin.httpOnly && admin.path === '/management')
  assert.ok(editor && editor.httpOnly && editor.path === config.reportPath)
  await writeFile(config.output + '/cookie-path-evidence.json', JSON.stringify(cookies.map(({ name, path, httpOnly, sameSite, secure }) =>
    ({ name, path, httpOnly, sameSite, secure })), null, 2))
  assert.deepEqual(errors, [])
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ errors, authorized: true,
    restrictedRejected: true, cookiePathsVerified: true, workflowMaterials: 'fixture', renderer: 'real' }))
} catch (error) {
  await page.screenshot({ path: config.output + '/failure.png', fullPage: true })
  await writeFile(config.output + '/failure.json', JSON.stringify({ error: String(error), errors }, null, 2))
  throw error
} finally { await browser.close() }
