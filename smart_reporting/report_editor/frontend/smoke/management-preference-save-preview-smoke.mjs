import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input)
await mkdir(config.output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const errors = [], requests = [], snapshots = [], sources = []
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => {
  if (request.url().includes('/configuration/')) requests.push({ method: request.method(), path: new URL(request.url()).pathname })
})
async function snapshot() {
  return { exactRoleCount: await page.getByRole('button', { name: '预览已保存草稿', exact: true }).count(),
    button: await page.locator('button').filter({ hasText: '预览已保存草稿' }).evaluate(element => ({
      html: element.outerHTML, parents: [...(function* () { for (let p = element; p; p = p.parentElement) yield p })()]
        .map(p => ({ tag: p.tagName, id: p.id, className: p.className, hidden: p.getAttribute('aria-hidden'),
          inert: p.inert, display: getComputedStyle(p).display, visibility: getComputedStyle(p).visibility })) })),
    accessibility: await page.locator('button').filter({ hasText: '预览已保存草稿' }).ariaSnapshot() }
}
try {
  await page.goto(config.apiOrigin + '/management/preferences')
  await page.getByLabel('密码', { exact: true }).fill(config.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('tab', { name: '文本报告', exact: true }).click()
  await page.getByRole('menuitem', { name: '语法样式', exact: true }).click()
  for (const step of [
    { table: 'HTML 表格', caption: true }, { table: '标准 Markdown 表格', caption: true },
    { caption: false }, { caption: true },
    { caption: true, references: false }, { caption: true, references: true },
    { caption: true, heading: 3 }, { caption: true, heading: 2 }, { caption: true, heading: 4 },
  ]) {
    if (step.table) {
      await page.getByRole('combobox', { name: '表格写法', exact: true }).click()
      await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').getByText(step.table, { exact: true }).click()
    } else if (step.heading) {
      await page.getByRole('combobox', { name: '章节起始级别', exact: true }).click()
      await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content')
        .getByText(({ 2: '二级（默认）', 3: '三级', 4: '四级' })[step.heading], { exact: true }).click()
    } else await page.getByRole('switch', { name: step.references === undefined ? '图片说明' : '引用编号', exact: true }).click()
    await page.getByRole('button', { name: '保存偏好草稿', exact: true }).click()
    await page.getByRole('button', { name: '保存草稿，暂不应用', exact: true }).click()
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    const version = sources.length + 2
    await page.getByText('偏好草稿 v' + version, { exact: true }).waitFor()
    const [response] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/configuration/preferences/preview/md') && response.request().method() === 'POST'),
      page.getByRole('button', { name: '预览已保存草稿', exact: true }).click({ timeout: 5000 }),
    ])
    assert.equal(response.status(), 200)
    const payload = await response.json()
    snapshots.push(await snapshot())
    assert.equal(snapshots.at(-1).exactRoleCount, 1, '加载图标不能改变预览按钮名称')
    assert.equal(payload.draftVersion, version)
    const source = Buffer.from(payload.artifact.base64, 'base64').toString('utf8')
    assert.equal(source.includes('*图表：示例图片说明*'), step.caption)
    assert.equal(source.includes('<abbr title="固定排版样例，非业务数据">\\[来源 001\\]</abbr>'), step.references ?? true)
    assert.equal(source.match(/\[\[citation:preview-source\]\]/g)?.length, 1, '引用显示不能丢失或重复来源身份')
    assert.match(source, new RegExp('^' + '#'.repeat(step.heading ?? 2) + ' 1\\. 样例概览(?: |$)', 'm'))
    assert.equal(source.includes('report-md-heading-level:'), Boolean(step.heading && step.heading !== 2))
    sources.push(source)
    await writeFile(config.output + '/saved-v' + version + '.md', source)
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.setViewportSize({ width: 1440, height: 900 })
  }
  assert.deepEqual(errors, [])
  assert.equal(requests.filter(request => request.path.endsWith('/preview/md')).length, 9)
  for (const [label, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height })
    assert.equal(await page.getByRole('switch', { name: '引用编号', exact: true }).getAttribute('aria-checked'), 'true')
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), '引用维护不能撑开页面')
    await page.screenshot({ path: config.output + '/heading-level-' + label + '.png', fullPage: true })
  }
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ errors, saved: sources.length, requests, snapshots }, null, 2))
} catch (error) {
  await writeFile(config.output + '/failure.json', JSON.stringify({ error: String(error), errors, requests, snapshots, current: await snapshot() }, null, 2))
  await page.screenshot({ path: config.output + '/failure.png', fullPage: true })
  throw error
} finally { await browser.close() }
