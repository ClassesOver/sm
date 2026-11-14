import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input)
await mkdir(config.output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const errors = [], downloads = [], layouts = []
page.on('pageerror', error => errors.push(error.message))
async function select(label, option) {
  await page.getByRole('combobox', { name: label, exact: true }).click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').getByText(option, { exact: true }).click()
}
async function savedDraft() {
  const response = await page.request.get(config.apiOrigin + '/management/api/v1/configuration/preferences')
  assert.equal(response.status(), 200)
  return (await response.json()).draft
}
async function save(summary) {
  assert.equal(await page.getByRole('button', { name: '预览已保存草稿', exact: true }).isDisabled(), true)
  await page.getByRole('button', { name: '保存偏好草稿', exact: true }).click()
  assert.match(await page.getByRole('dialog').innerText(), summary)
  const response = page.waitForResponse(response => response.url().endsWith('/configuration/preferences/draft') && response.request().method() === 'PUT')
  await page.getByRole('button', { name: '保存草稿，暂不应用', exact: true }).click()
  assert.equal((await response).status(), 200)
  const { version } = await (await response).json()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })
  await page.getByText('偏好草稿 v' + version, { exact: true }).waitFor()
  return version
}
async function checkLayouts(label) {
  for (const [screen, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height })
    // 等待原生页签指示条完成响应式测量及动画，避免截图停在跨格式过渡帧。
    await page.waitForFunction(() => {
      const tab = document.querySelector('.global-format-tabs > .ant-tabs-nav .ant-tabs-tab-active')?.getBoundingClientRect()
      const ink = document.querySelector('.global-format-tabs > .ant-tabs-nav .ant-tabs-ink-bar')?.getBoundingClientRect()
      return tab && ink && Math.abs(tab.left - ink.left) < 1 && Math.abs(tab.width - ink.width) < 1
    })
    const layout = await page.evaluate(() => ({ width: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth, nestedForms: document.querySelectorAll('form form').length }))
    assert.ok(layout.scroll <= layout.width + 1, label + ': ' + JSON.stringify(layout))
    assert.equal(layout.nestedForms, 0)
    layouts.push({ label, screen, ...layout })
    await page.screenshot({ path: config.output + '/' + label + '-' + screen + '.png', fullPage: true })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
}
try {
  await page.goto(config.apiOrigin + '/management/preferences')
  await page.getByLabel('密码', { exact: true }).fill(config.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('heading', { name: '偏好管理', exact: true }).waitFor()
  const before = await savedDraft()

  // 四个维护入口必须真实保存，再从下载按钮读取同一份原生工作簿。
  await page.getByRole('tab', { name: '电子表格', exact: true }).click()
  await page.getByRole('menuitem', { name: '页眉页脚', exact: true }).click()
  const enabled = page.getByRole('switch', { name: '启用页眉页脚', exact: true })
  if (await enabled.getAttribute('aria-checked') !== 'true') await enabled.click()
  const style = page.getByRole('button', { name: '页眉页脚样式', exact: true })
  assert.equal(await style.getAttribute('aria-expanded'), 'false')
  assert.equal(await page.getByRole('spinbutton', { name: '页眉页脚字号', exact: true }).count(), 0)
  await style.click()
  for (const name of ['页眉页脚字体', '页眉页脚字号', '页眉页脚颜色', '页眉页脚加粗'])
    assert.equal(await page.getByLabel(name, { exact: true }).count(), 1)
  assert.equal(await page.locator('.preference-style-fields').getByRole('spinbutton').count(), 1)
  assert.equal(await page.getByRole('spinbutton', { name: '首行缩进（磅）', exact: true }).count(), 0)
  await select('页眉页脚字体', '衬线（Noto Serif CJK SC）')
  await page.getByRole('spinbutton', { name: '页眉页脚字号', exact: true }).fill('14')
  await page.getByRole('textbox', { name: '页眉页脚颜色', exact: true }).fill('#345678')
  const bold = page.getByRole('switch', { name: '页眉页脚加粗', exact: true })
  if (await bold.getAttribute('aria-checked') !== 'true') await bold.click()
  await page.getByRole('textbox', { name: '页眉左侧', exact: true }).fill('页眉样式验证')
  await checkLayouts('workbook-header-footer')
  const version = await save(/电子表格/)
  const afterWorkbook = await savedDraft()
  assert.deepEqual(afterWorkbook.document.xlsx.print.headerFooter.style,
    { ...before.document.xlsx.print.headerFooter.style, font: 'serif', size: 14, color: '#345678', bold: true })
  for (const format of ['md', 'pptx', 'word', 'pdf']) assert.deepEqual(afterWorkbook.document[format], before.document[format])
  const [previewResponse] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/configuration/preferences/preview/xlsx') && response.request().method() === 'POST'),
    page.getByRole('button', { name: '预览已保存草稿', exact: true }).click(),
  ])
  assert.equal(previewResponse.status(), 200)
  const payload = await previewResponse.json()
  assert.equal(payload.draftVersion, version)
  assert.ok(payload.pdf && payload.pages.length, '保存后的样式须生成实际打印预览')
  await page.getByRole('img', { name: '实际样例第 1 页', exact: true }).evaluate(image => image.decode())
  const [download] = await Promise.all([
    page.waitForEvent('download'), page.getByRole('button', { name: '读取原生样例', exact: true }).click(),
  ])
  const filename = 'workbook-header-footer.xlsx'
  await download.saveAs(config.output + '/' + filename)
  const bytes = await readFile(config.output + '/' + filename)
  assert.ok(bytes.equals(Buffer.from(payload.artifact.base64, 'base64')))
  assert.equal(bytes.length, payload.artifact.size)
  assert.equal(createHash('sha256').update(bytes).digest('hex'), payload.artifact.sha256)
  downloads.push({ filename, size: bytes.length, sha256: payload.artifact.sha256, version })
  await writeFile(config.output + '/workbook-header-footer.pdf', Buffer.from(payload.pdf.base64, 'base64'))
  for (const [index, page] of payload.pages.entries())
    await writeFile(config.output + '/workbook-header-footer-page-' + (index + 1) + '.png', Buffer.from(page.base64, 'base64'))
  await checkLayouts('workbook-header-footer-preview')
  await page.getByRole('button', { name: '设置', exact: true }).click()

  // 从其他格式的落款发起校验，必须回到 PPTX 页脚真实错误字段。
  await page.getByRole('tab', { name: '演示文稿', exact: true }).click()
  await page.getByRole('button', { name: '页脚样式', exact: true }).click()
  await page.getByRole('textbox', { name: '页脚颜色', exact: true }).fill('invalid')
  await page.getByRole('tab', { name: 'PDF', exact: true }).click()
  await page.getByRole('menuitem', { name: '落款', exact: true }).click()
  await page.getByRole('button', { name: '保存偏好草稿', exact: true }).click()
  assert.equal(await page.getByRole('tab', { name: '演示文稿', exact: true }).getAttribute('aria-selected'), 'true')
  assert.equal(await page.locator('.global-settings-directory .ant-menu-item-selected').innerText(), '页眉页脚')
  assert.ok(await page.getByRole('textbox', { name: '页脚颜色', exact: true }).evaluate(element => element === document.activeElement))
  await checkLayouts('pptx-footer-error')
  await page.getByRole('textbox', { name: '页脚颜色', exact: true }).fill('#345678')
  await save(/演示文稿 · 页脚 · 文字颜色/)

  for (const [label, format] of [['文字文档', 'word'], ['PDF', 'pdf']]) {
    await page.getByRole('tab', { name: label, exact: true }).click()
    await page.getByRole('menuitem', { name: '页面与排版', exact: true }).click()
    const details = page.locator('.preference-typography-details')
    assert.equal(await details.getAttribute('open'), null)
    await details.locator('summary').click()
    assert.equal(await page.getByRole('switch', { name: '图注编号', exact: true }).count(), 0)
    await select('排版对象', '图注')
    assert.equal(await page.getByRole('button', { name: '段落细节', exact: true }).getAttribute('aria-expanded'), 'false')
    const numbering = page.getByRole('switch', { name: '图注编号', exact: true })
    assert.equal(await numbering.getAttribute('aria-checked'), String(before.document[format].charts.captionNumbering))
    await numbering.click()
    await checkLayouts(format + '-caption-numbering')
  }
  await save(/图注编号/)
  const after = await savedDraft()
  for (const format of ['word', 'pdf']) assert.equal(after.document[format].charts.captionNumbering, !before.document[format].charts.captionNumbering)
  assert.deepEqual(after.document.xlsx, afterWorkbook.document.xlsx)
  assert.deepEqual(errors, [])
  await writeFile(config.output + '/download-evidence.json', JSON.stringify(downloads, null, 2))
  await writeFile(config.output + '/layout-evidence.json', JSON.stringify(layouts, null, 2))
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ errors, saved: true }))
} catch (error) {
  await page.screenshot({ path: config.output + '/failure.png', fullPage: true })
  await writeFile(config.output + '/failure.json', JSON.stringify({ error: String(error), errors, layouts }, null, 2))
  throw error
} finally { await browser.close() }
