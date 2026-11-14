import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import AxeBuilder from '@axe-core/playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const directory = resolve(process.env.OFFICE_DIALOG_OUTPUT ?? '/tmp/office-dialog-layout-20261111')
const port = Number(process.env.OFFICE_DIALOG_PORT ?? 4287)
const base = `http://127.0.0.1:${port}/reports/v1/editor/assets/`
const viewports = process.env.OFFICE_DIALOG_VIEWPORTS?.split(',').map(value => value.split('x').map(Number)) ?? [[1440,900],[768,1024],[390,844],[320,640],[640,360],[390,320]]
const objectChrome = process.env.OFFICE_PDF_OBJECT_CHROME === '1'
const readDrafts = page => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).map(([key,value]) => [key,JSON.parse(value).operations]))
let pdfFixture = null
if (!process.env.OFFICE_DIALOG_CASES || process.env.OFFICE_DIALOG_CASES.includes('pdf')) {
  const repo = fileURLToPath(new URL('../../../../', import.meta.url))
  const source = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64,hashlib,json,zipfile
from io import BytesIO
from reportlab.pdfgen.canvas import Canvas
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
buffer=BytesIO();canvas=Canvas(buffer,pagesize=(612,792))
for n in range(2):
 canvas.drawString(72,700,'Office dialog source '+str(n+1));canvas.showPage()
canvas.save();data=buffer.getvalue();out=BytesIO()
with zipfile.ZipFile(out,'w') as archive:
 archive.writestr('page-1.png',base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='))
zipdata=out.getvalue()
print(json.dumps(dict(bytes=base64.b64encode(data).decode(),model=inspect_pdf(data),zip=base64.b64encode(zipdata).decode(),zipSha256=hashlib.sha256(zipdata).hexdigest())))
`], { cwd: repo, encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 })
  if (source.status !== 0) throw new Error(source.stderr || 'PDF 来源构造失败')
  pdfFixture = JSON.parse(source.stdout)
}
const fixtureHtml = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><script>window.officePdfFixtureContent=' + JSON.stringify(pdfFixture) + '</script><script type="module" src="./smoke/office-dialog-fixture.mjs"></script></body></html>'
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
let log = '', browser
server.stderr.on('data', chunk => { log += chunk })
server.stdout.on('data', chunk => { log += chunk })
const evidence = { kind: 'product-component-fixture', failures: [], cases: [], pageErrors: [] }
try {
  await mkdir(directory, { recursive: true })
  for (let attempt = 0; ; attempt++) {
    if (server.exitCode !== null) throw new Error(log)
    try { if ((await fetch(base)).ok) break } catch {}
    if (attempt > 120) throw new Error('Vite 启动超时：' + log)
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const discovery = await browser.newPage()
  await discovery.route('**/office-dialog-fixture.html?*', route => route.fulfill({ contentType: 'text/html', body: fixtureHtml }))
  await discovery.goto(`${base}office-dialog-fixture.html?format=docx`)
  await discovery.waitForSelector('html[data-fixture-ready="true"]')
  const available = await discovery.evaluate(() => window.officeDialogCases)
  evidence.available = available
  const formats = process.env.OFFICE_DIALOG_CASES?.split(',') ?? available
  assert(formats.every(format => available.includes(format)), '存在未注册的弹窗夹具')
  await discovery.close()
  for (const format of formats) {
    const context = await browser.newContext()
    const page = await context.newPage()
    page.on('pageerror', error => evidence.pageErrors.push({ format, message: error.message }))
    await page.route('**/office-dialog-fixture.html?*', route => route.fulfill({ contentType: 'text/html', body: fixtureHtml }))
    for (const [width, height] of viewports) {
      await page.setViewportSize(format.startsWith('pdf-host-') ? { width: 1440, height: 900 } : { width, height })
      await page.goto(`${base}office-dialog-fixture.html?format=${format}`)
      await page.waitForSelector('html[data-fixture-ready="true"]')
      await page.getByRole('button', { name: '打开设置' }).click()
      if (format.startsWith('pdf-host-')) {
        await page.waitForSelector('html[data-pdf-host-ready="true"]')
        const draw = await page.evaluate(() => document.documentElement.dataset.pdfHostDraw)
        if (draw) {
          await page.locator(`[data-pdf-ribbon-tab="${draw === 'link' ? 'edit' : 'annotate'}"]`).click()
          const tool = page.locator(`[data-pdf-draw-shape="${draw}"]`)
          await tool.click()
          await tool.evaluate(element => { window.officeDialogFocusTarget = element })
          await page.waitForFunction(() => document.querySelector('.pdf-page-content')?.onpointerdown)
          const bounds = await page.locator('.pdf-page-content').first().boundingBox()
          await page.mouse.move(bounds.x + 100, bounds.y + 90)
          await page.mouse.down()
          await page.mouse.move(bounds.x + 220, bounds.y + 120, { steps: 5 })
          await page.mouse.up()
        }
        await page.setViewportSize({ width, height })
      }
      const dialog = page.locator('[role=dialog]:visible, dialog[open]')
      await dialog.waitFor()
      if (format.startsWith('xlsx-function-catalog') && format.endsWith('-selected')) await dialog.locator('.fn-list [role=option]').first().click()
      if (format.startsWith('xlsx-print-preview')) {
        await page.waitForFunction(format => {
          const card = document.querySelector('[role=dialog]:not([hidden])')
          if (format.endsWith('-pending')) return card?.querySelector('[data-print-submit]')?.disabled
          if (format.endsWith('-error')) return card?.querySelector('[data-print-error]')?.textContent.trim()
          return card?.querySelector('[data-print-preview]')?.srcdoc.includes('class="page"') && !card.querySelector('[data-print-submit]').disabled
        }, format)
      }
      if (format.startsWith('xlsx-queries') && !format.endsWith('-pending')) await page.waitForFunction(() => document.querySelector('[data-query-loading]')?.hidden)
      const requiresPrimary = await page.evaluate(() => document.documentElement.dataset.primaryAction !== 'none')
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(300)
      const check = (condition, message) => { if (!condition) evidence.failures.push(`${format} ${width}×${height}: ${message}`) }
      if (format === 'docx-table-properties') {
        // 五页均使用真实组件；逐页确认操作区可见、Tab 焦点留在弹窗，并以取消验证没有内容事务。
        const before = await page.evaluate(() => JSON.stringify(window.officeTablePropertiesEditor.getJSON()))
        evidence.tableProperties ??= []
        for (let index = 0; index < 5; index++) {
          await dialog.getByRole('tab').nth(index).click()
          const state = await dialog.evaluate(element => {
            const bounds = element.getBoundingClientRect(), body = element.querySelector('.table-properties-body')
            body.scrollTop = body.scrollHeight
            const actions = [...element.querySelectorAll('.modal-actions button')].map(button => button.getBoundingClientRect())
            return { tab: element.querySelector('[aria-selected=true]').textContent, contained: bounds.left >= 7 && bounds.right <= innerWidth - 7 && bounds.top >= 7 && bounds.bottom <= innerHeight - 7,
              actionsVisible: actions.every(rect => rect.top >= bounds.top && rect.bottom <= bounds.bottom), bodyScrollHeight: body.scrollHeight, bodyHeight: body.clientHeight }
          })
          check(state.contained && state.actionsVisible, `表格属性页不可达：${state.tab}`)
          await dialog.locator('.modal-actions button').first().focus(); await page.keyboard.press('Tab')
          check(await dialog.evaluate(element => element.contains(document.activeElement)), `表格属性焦点越界：${state.tab}`)
          await page.screenshot({ path: join(directory, `${format}-${width}x${height}-tab-${index}.png`) })
          evidence.tableProperties.push({ width, height, ...state })
        }
        await dialog.locator('.modal-actions button').first().click()
        await page.waitForFunction(() => !document.querySelector('.table-properties-dialog'))
        check(before === await page.evaluate(() => JSON.stringify(window.officeTablePropertiesEditor.getJSON())), '取消表格属性产生内容事务')
        await page.getByRole('button', { name: '打开设置' }).click(); await dialog.waitFor()
      }
      if (process.env.OFFICE_PDF_CROP_KEYBOARD === '1' && format === 'pdf-host-crop') {
        const before = await readDrafts(page)
        const preview = dialog.getByRole('img', { name: /^裁切预览：/ })
        await preview.waitFor()
        const labels = ['左侧裁去 (%)', '顶部裁去 (%)', '右侧裁去 (%)', '底部裁去 (%)'], values = ['10', '20', '30', '10']
        for (const [index, label] of labels.entries()) {
          const input = dialog.getByRole('spinbutton', { name: label, exact: true })
          for (let step = 0; step < 12 && !await input.evaluate(node => node === document.activeElement); step++) await page.keyboard.press('Tab')
          check(await input.evaluate(node => node === document.activeElement), `裁切字段Tab不可达：${label}`)
          await page.keyboard.press('ControlOrMeta+A'); await page.keyboard.type(values[index])
          check(await input.evaluate(node => document.getElementById(node.getAttribute('aria-describedby'))?.textContent.includes('键盘操作可直接填写')), `裁切字段缺少等效路径说明：${label}`)
        }
        check(await preview.getAttribute('aria-label') === '裁切预览：左侧裁去 10%，顶部裁去 20%，右侧裁去 30%，底部裁去 10%', '键盘输入后裁切预览说明未同步')
        const geometry = await dialog.locator('[data-pdf-crop-region]').evaluate(node => ({ hidden: node.getAttribute('aria-hidden'), width: node.style.width, height: node.style.height, unnamedHandles: [...node.querySelectorAll('[data-pdf-crop-handle]')].every(handle => !handle.hasAttribute('aria-label')) }))
        check(geometry.hidden === 'true' && geometry.width === '60%' && geometry.height === '70%' && geometry.unnamedHandles, '裁切视觉范围未与键盘输入同步或控制柄语义仍错误')
        assert.deepEqual(await readDrafts(page), before)
        evidence.cropKeyboard ??= []
        evidence.cropKeyboard.push({ width, height, values, geometry, draftUnchanged: true })
      }
      if (process.env.OFFICE_WORD_CELL_MARGINS === '1' && ['docx-cell-margins-custom', 'docx-cell-margins-mixed', 'docx-cell-margins-error'].includes(format)) {
        const structure = await dialog.evaluate(element => {
          const card = element.querySelector('.modal-card'), body = card.querySelector('.docx-cell-margins-body'), header = card.querySelector('header'), footer = card.querySelector('footer')
          if (!body || !header || !footer) return { structured: false }
          const values = [...card.querySelectorAll('[data-margin]')].map(node => node.value), before = { top: header.getBoundingClientRect().top, bottom: footer.getBoundingClientRect().bottom }
          body.scrollTop = body.scrollHeight
          const rect = card.getBoundingClientRect(), controls = [...footer.querySelectorAll('button')].map(node => node.getBoundingClientRect())
          return { structured: true, stable: header.getBoundingClientRect().top === before.top && footer.getBoundingClientRect().bottom === before.bottom,
            actionsVisible: controls.every(control => control.top >= rect.top && control.bottom <= rect.bottom),
            fieldsUnchanged: JSON.stringify(values) === JSON.stringify([...card.querySelectorAll('[data-margin]')].map(node => node.value)),
            restoreCompact: footer.querySelector('[data-action=inherit]').getBoundingClientRect().width < footer.clientWidth / 2 }
        })
        check(structure.structured && structure.stable && structure.actionsVisible && structure.fieldsUnchanged && structure.restoreCompact, '单元格边距缺少固定标题/操作区、独立滚动或紧凑恢复操作')
        for (const name of ['来源边距状态', '边距设置说明', ...(format.endsWith('-error') ? ['边距设置错误'] : [])]) {
          const region = dialog.getByLabel(name, { exact: true })
          check(await region.count() === 1 && await region.getAttribute('tabindex') === '0', `单元格边距缺少键盘阅读入口：${name}`)
          if (await region.count() === 1) {
            for (let step = 0; step < 16 && !await region.evaluate(node => node === document.activeElement); step++) await page.keyboard.press('Tab')
            const reading = await region.evaluate(node => {
              const rect = node.getBoundingClientRect(), body = node.closest('.docx-cell-margins-body').getBoundingClientRect()
              return { focused: node === document.activeElement, visibleHeight: Math.min(rect.bottom, body.bottom, innerHeight) - Math.max(rect.top, body.top, 0), outline: parseFloat(getComputedStyle(node).outlineWidth) }
            })
            check(reading.focused && reading.visibleHeight >= 20 && reading.outline >= 2, `单元格边距阅读区不可见或焦点不清晰：${name}`)
            evidence.cellMarginReading ??= []
            evidence.cellMarginReading.push({ format, width, height, name, ...reading })
          }
        }
      }
      if (process.env.OFFICE_FUNCTION_KEYBOARD === '1' && format === 'xlsx-function-catalog') {
        const search = dialog.getByRole('textbox', { name: '搜索函数' })
        const options = dialog.locator('.fn-list [role="option"]')
        const count = await options.count(), steps = []
        await search.focus()
        await page.keyboard.press('Tab')
        check(await dialog.getByLabel('函数类别').evaluate(node => node === document.activeElement), '搜索框Tab未进入函数类别')
        await page.keyboard.press('Tab')
        for (const [key, index] of [[null, 0], ['ArrowDown', 1], ['End', count - 1], ['ArrowDown', count - 1], ['ArrowUp', count - 2], ['Home', 0], ['ArrowUp', 0]]) {
          if (key) await page.keyboard.press(key)
          const state = await options.nth(index).evaluate(node => {
            const rect = node.getBoundingClientRect(), list = node.parentElement.getBoundingClientRect()
            return { focused: node === document.activeElement, selected: node.getAttribute('aria-selected') === 'true', visible: rect.top >= list.top - 1 && rect.bottom <= list.bottom + 1,
              row: { top: rect.top, bottom: rect.bottom, height: rect.height }, list: { top: list.top, bottom: list.bottom, height: list.height },
              tabStops: [...node.parentElement.querySelectorAll('[role=option]')].filter(item => item.tabIndex === 0).length }
          })
          steps.push({ key, index, ...state })
          if (!state.visible) await page.screenshot({ path: join(directory, `${format}-${width}x${height}-keyboard-${key ?? 'entry'}.png`) })
          check(state.focused && state.selected && state.visible && state.tabStops === 1, `函数列表键盘导航失败：${key ?? 'Tab入口'}`)
        }
        await page.keyboard.press('Tab')
        const description = dialog.getByRole('region', { name: '函数说明', exact: true })
        check(await description.evaluate(node => node === document.activeElement), '函数列表Tab未进入可滚动说明')
        if (await description.evaluate(node => node.scrollHeight > node.clientHeight + 1)) {
          await page.keyboard.press('End')
          await page.waitForFunction(() => { const node = document.querySelector('.fn-syntax'); return node && node.scrollTop + node.clientHeight >= node.scrollHeight - 2 })
          check(await description.evaluate(node => node === document.activeElement), '滚动长函数说明后焦点丢失')
          await page.keyboard.press('Home')
        }
        await page.keyboard.press('Tab')
        check(await dialog.getByRole('button', { name: '取消', exact: true }).evaluate(node => node === document.activeElement), '函数列表Tab未直接进入操作区')
        await page.keyboard.press('Shift+Tab')
        check(await dialog.getByRole('region', { name: '函数说明', exact: true }).evaluate(node => node === document.activeElement), 'Shift+Tab未返回函数说明')
        await page.keyboard.press('Shift+Tab')
        check(await options.first().evaluate(node => node === document.activeElement), 'Shift+Tab未返回当前函数')
        await dialog.getByLabel('函数类别').selectOption('Recent')
        check(await dialog.getByRole('button', { name: '确定', exact: true }).isDisabled(), '分类变化后仍能确认旧函数')
        await dialog.getByLabel('函数类别').selectOption('All')
        check(await options.count() === count && await dialog.getByRole('button', { name: '确定', exact: true }).isDisabled(), '恢复分类后未清除旧选择')
        evidence.functionKeyboard ??= []
        evidence.functionKeyboard.push({ format, width, height, steps })
      }
      if (format === 'pptx-chart-design') {
        await dialog.getByLabel('配色方案').selectOption('warm')
        const preview = dialog.getByRole('group', { name: '配色预览' })
        check(await preview.count() === 1, '图表配色预览缺少具名分组')
        const colors = await preview.getByRole('img').evaluateAll(nodes => nodes.map(node => ({ label: node.getAttribute('aria-label'), color: node.getAttribute('title') })))
        check(colors.length === 5 && colors.every(item => item.label && item.label === item.color), '图表配色色块缺少可读颜色值')
      }
      if (process.env.OFFICE_DIALOG_AXE === '1') {
        const { violations } = await new AxeBuilder({ page }).include('[role="dialog"], dialog[open]').analyze()
        evidence.accessibility ??= []
        evidence.accessibility.push({ format, width, height, violations })
        check(violations.length === 0, `无障碍检查失败：${violations.map(issue => issue.id).join(', ')}`)
      }
      const draftsBefore = objectChrome ? await readDrafts(page) : null
      if (format.startsWith('pdf-host-signature-')) {
        const typed = format.endsWith('-type')
        check(await dialog.locator('.pdf-sign-type').isVisible() === typed && await dialog.locator('.pdf-sign-pad').isVisible() !== typed, '签名模式显隐与当前标签不一致')
        check(await dialog.getByRole('button', { name: typed ? '键入' : '手写', exact: true }).getAttribute('aria-pressed') === 'true', '签名模式标签状态错误')
      }
      if (format.endsWith('-portal')) {
        await page.keyboard.press('Tab')
        for (const field of await dialog.locator('input:not([disabled]),select:not([disabled]),textarea:not([disabled])').all()) {
          await field.focus()
          check(await field.evaluate(element => parseFloat(getComputedStyle(element).outlineWidth) >= 2), '挂载在正文宿主之外的 Word 字段缺少键盘焦点环')
        }
      }
      const transitions = []
      if (format === 'docx-line-multiple') {
        for (const rule of ['exact', 'atLeast', 'multiple']) {
          await dialog.getByLabel('行距类型').selectOption(rule)
          const multiple = await dialog.locator('[data-spacing-multiple]').isVisible()
          const points = await dialog.locator('[data-spacing-points]').isVisible()
          transitions.push({ rule, multiple, points })
          check(multiple === (rule === 'multiple') && points === (rule !== 'multiple'), '行距切换后字段显隐错误')
        }
      }
      if (format === 'docx-indent-chars') {
        for (const kind of ['hanging', 'none', 'firstLine']) {
          await dialog.getByLabel('特殊缩进类型').selectOption(kind)
          const unit = dialog.getByLabel('特殊缩进单位')
          const value = dialog.locator('input')
          const state = { kind, unit: await unit.inputValue(), unitDisabled: await unit.isDisabled(), valueDisabled: await value.isDisabled(), warning: await dialog.locator('[data-character-warning]').isVisible() }
          transitions.push(state)
          check(state.unit === 'pt' && state.unitDisabled === (kind !== 'firstLine') && state.valueDisabled === (kind === 'none') && !state.warning, '特殊缩进切换后单位或禁用状态错误')
        }
        await dialog.getByLabel('特殊缩进单位').selectOption('chars')
        check(await dialog.getByLabel('缩进值（字符）').isEnabled() && await dialog.locator('[data-character-warning]').isVisible(), '恢复字符缩进后字段或提示错误')
      }
      let busyState = null
      if (format.endsWith('-busy')) {
        busyState = await dialog.evaluate(element => ({ busy: element.getAttribute('aria-busy') === 'true',
          disabled: [...element.querySelectorAll('button,input,select,textarea')].every(control => control.disabled) }))
        check(busyState.busy && busyState.disabled, '繁忙状态未禁用重复操作')
        await page.screenshot({ path: join(directory, `${format}-${width}x${height}-pending.png`) })
        await page.keyboard.press('Escape')
        check(await dialog.isVisible(), '繁忙期间 Esc 意外关闭弹窗')
        await page.evaluate(() => window.officeDialogRelease())
        await page.waitForFunction(() => !document.querySelector('[aria-busy=true]'))
      }
      if (format.endsWith('-error') || busyState) {
        await page.waitForFunction(() => [...(document.querySelector('dialog[open],[role=dialog]:not([hidden])')?.querySelectorAll('[role=alert],[role=status]') ?? [])].some(node => node.textContent.trim()))
      }
      if (/^pdf-(convert|image-export)-(pending|error|result)$/.test(format)) {
        const state = format.slice(format.lastIndexOf('-') + 1)
        await page.waitForFunction(state => {
          const dialog = document.querySelector('dialog[open]'), status = dialog?.querySelector('[role=status]')?.textContent ?? ''
          return state === 'pending' ? status.includes('正在') && !!dialog.querySelector('button:disabled')
            : state === 'error' ? status.startsWith('PDF 操作失败：') : !!dialog?.querySelector('a')
        }, state)
      }
      const measurement = await dialog.evaluate(element => {
        const card = element.querySelector('.modal-card') ?? element
        const wordDialog = card.closest('.docx-native') || card.matches('.docx-table-property-dialog,.docx-settings-dialog')
        const rect = card.getBoundingClientRect(), style = getComputedStyle(card)
        const controls = [...card.querySelectorAll('button, input, select, textarea')].filter(control => control.getClientRects().length)
        const scrollers = [...card.querySelectorAll('*')].filter(node =>
          /auto|scroll/.test(getComputedStyle(node).overflowX) && node.scrollWidth > node.clientWidth + 1)
        const clipped = controls.filter(control => {
          const inner = control.getBoundingClientRect()
          return (inner.left < rect.left - 1 || inner.right > rect.right + 1) && !scrollers.some(scroller => scroller.contains(control))
        }).map(control => control.getAttribute('aria-label') || control.textContent.trim() || control.tagName)
        const primary = card.querySelector('.primary-action, .ui-button--primary, [value=ok], button[type=submit], [data-pdf-extract-apply], [data-pdf-protection-apply], [data-pdf-export-text-apply], [data-pdf-external-pages-apply], [data-pdf-static-text-confirm], [data-pdf-convert-office-apply], [data-pdf-image-export-apply], [data-pdf-existing-image-confirm], [data-chart-confirm], [data-link-confirm], [data-caption-confirm], .pdf-link-actions button:last-child, [data-pdf-dialog-confirm], .workbook-defined-name-add, [data-print-submit]')
        return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height,
          font: style.fontFamily, color: style.color, radius: style.borderRadius, shadow: style.boxShadow,
          scrollWidth: card.scrollWidth, clientWidth: card.clientWidth, scrollHeight: card.scrollHeight, clientHeight: card.clientHeight, clipped,
          parameterInputWidths: [...card.querySelectorAll('.fn-args-row input')].map(input => input.getBoundingClientRect().width),
          checkboxSizes: [...card.querySelectorAll('input[type=checkbox]')].map(input => {
            const bounds = input.getBoundingClientRect()
            return { width: bounds.width, height: bounds.height }
          }),
          pdfFields: controls.filter(control => card.matches('dialog[class*="pdf-"]') && control.matches('input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=color]),select,textarea')).map(control => ({ height: control.getBoundingClientRect().height, minimumHeight: card.matches('.pdf-extract-dialog,.pdf-existing-image-dialog,.pdf-stamp-dialog,.pdf-link-dialog') ? 28 : 32, font: getComputedStyle(control).fontFamily })),
          pdfDesktopLabels: card.matches('dialog[class*="pdf-"]') ? [...card.querySelectorAll('label')].filter(label => label.getClientRects().length).flatMap(label => {
            const field = label.querySelector('input:not([type=checkbox]):not([type=radio]),select,textarea')
            const text = [...label.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()) ?? label.querySelector('span')
            if (!field || !text) return []
            const range = document.createRange(); range.selectNodeContents(text)
            const textBounds = range.getBoundingClientRect(), bounds = field.getBoundingClientRect()
            return [bounds.left >= textBounds.right + 6 && bounds.top < textBounds.bottom && bounds.bottom > textBounds.top]
          }) : [],
          pdfActions: card.matches('dialog[class*="pdf-"]') ? (() => { const actions = card.querySelector('.pdf-layout-actions,.pdf-link-actions'); return actions ? getComputedStyle(actions).justifyContent : null })() : null,
          pdfAccessibleName: card.matches('dialog[class*="pdf-"]') ? card.getAttribute('aria-label') : null,
          wordFields: controls.filter(control => wordDialog && control.matches('input:not([type=checkbox]):not([type=radio]),select,textarea')).map(control => ({ height: control.getBoundingClientRect().height, font: getComputedStyle(control).fontFamily })),
          wordButtons: controls.filter(control => wordDialog && control.matches('button')).map(control => ({ height: control.getBoundingClientRect().height, font: getComputedStyle(control).fontFamily })),
          wordHiddenFields: wordDialog ? [...card.querySelectorAll('[hidden]')].filter(field => field.getClientRects().length).length : 0,
          wordDesktopLabels: wordDialog ? [...card.querySelectorAll('label')].filter(label => label.getClientRects().length).flatMap(label => {
            const field = label.querySelector('input:not([type=checkbox]):not([type=radio]),select,textarea')
            const text = [...label.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()) ?? label.querySelector('[data-value-label]')
            if (!field || !text) return []
            const range = document.createRange(); range.selectNodeContents(text)
            const textBounds = range.getBoundingClientRect(), bounds = field.getBoundingClientRect()
            return [{ aligned: bounds.left >= textBounds.right + 6 && bounds.top < textBounds.bottom && bounds.bottom > textBounds.top, left: bounds.left }]
          }) : [],
          workbookFields: controls.filter(control => control.matches(':is(.workbook-ribbon-format-dialog,.workbook-ribbon-note-dialog) :is(input:not([type=checkbox]):not([type=radio]),select,textarea),[data-print-scope]')).map(control => ({
            height: control.getBoundingClientRect().height, minimumHeight: card.matches('.workbook-zoom-dialog,.workbook-consolidate-dialog,.workbook-advanced-filter-dialog,.workbook-goal-seek-dialog,.workbook-data-table-dialog,.workbook-editable-ranges-dialog') ? 28 : 32, font: getComputedStyle(control).fontFamily,
          })),
          workbookDesktopLabels: [...card.querySelectorAll('.workbook-ribbon-format-form label,.workbook-ribbon-note-form label')].filter(label => label.getClientRects().length && !label.querySelector('[data-header-footer-field]')).flatMap(label => {
            const field = label.querySelector('input:not([type=checkbox]):not([type=radio]),select,textarea')
            if (card.closest('.docx-native') && field?.matches('textarea')) return []
            const text = [...label.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()) ?? label.querySelector('span')
            if (!field || !text) return []
            const range = document.createRange(); range.selectNodeContents(text)
            const textBounds = range.getBoundingClientRect(), bounds = field.getBoundingClientRect()
            return [bounds.left >= textBounds.right + 6 && bounds.top < textBounds.bottom && bounds.bottom > textBounds.top]
          }),
          visibleHiddenFields: [...card.querySelectorAll('.workbook-ribbon-format-dialog [hidden]')].filter(field => field.getClientRects().length).map(field => field.textContent.trim()),
          numfmtFields: [...card.querySelectorAll('[data-numfmt-field]')].filter(field => field.getClientRects().length).map(field => field.dataset.numfmtField),
          numfmtSelectionDistinct: (() => {
            const active = card.querySelector('[data-numfmt-category][aria-selected=true]'), other = card.querySelector('[data-numfmt-category][aria-selected=false]')
            return !active || getComputedStyle(active).backgroundColor !== getComputedStyle(other).backgroundColor
          })(),
          pivotControlGaps: [...card.querySelectorAll('.workbook-pivot-dialog fieldset > select + button, .workbook-pivot-dialog fieldset > input + button')].filter(button => button.getClientRects().length).map(button => {
            const previous = button.previousElementSibling.getBoundingClientRect(), bounds = button.getBoundingClientRect()
            return Math.max(bounds.top - previous.bottom, bounds.left - previous.right)
          }),
          workbookCheckboxRows: controls.filter(control => control.matches('.workbook-ribbon-format-dialog input[type=checkbox]')).map(control => {
            const label = control.closest('label'), text = [...label.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())
            if (!text) return true
            const range = document.createRange(); range.selectNodeContents(text)
            const textBounds = range.getBoundingClientRect(), bounds = control.getBoundingClientRect()
            return bounds.top < textBounds.bottom && bounds.bottom > textBounds.top
          }),
          primaryBackground: primary ? getComputedStyle(primary).backgroundColor : null,
          primaryImage: primary ? getComputedStyle(primary).backgroundImage : null,
          primaryDisabled: primary?.disabled === true,
          disabledPrimaryStyled: primary?.matches('.ui-button--primary:disabled') === true,
          workbookSettingButtons: controls.filter(control => control.matches(':is(.workbook-ribbon-format-dialog,.workbook-ribbon-note-dialog,.workbook-queries-dialog) button,[data-print-prev],[data-print-next],[data-print-submit],[data-print-cancel]')).map(control => ({ height: control.getBoundingClientRect().height, font: getComputedStyle(control).fontFamily })),
          headerFooterFields: [...card.querySelectorAll('[data-header-footer-field]')].map(field => ({ width: field.getBoundingClientRect().width, height: field.getBoundingClientRect().height })),
          definedNameListHeight: card.querySelector('.workbook-defined-name-list')?.getBoundingClientRect().height ?? null,
          gotoListHeight: card.querySelector('[data-goto-names]:not([hidden])')?.getBoundingClientRect().height ?? null,
          seriesGroupsSideBySide: (() => { const groups = [...card.querySelectorAll('[data-fill-group]')].map(group => group.getBoundingClientRect()); return groups.length !== 3 || groups.every(group => Math.abs(group.top - groups[0].top) < 2) })(),
          workbookDisabledPrimaryStyled: !!card.closest('.workbook-function-root,.workbook-ribbon-format-dialog,.workbook-ribbon-note-dialog') && primary?.disabled === true && Number(getComputedStyle(primary).opacity) < 1,
          pdfDisabledPrimaryStyled: card.matches('dialog.pdf-layout-dialog') && primary?.disabled === true && Number(getComputedStyle(primary).opacity) < 1,
          primaryReachable: (() => {
            if (!primary) return false
            const scrollHost = card.matches('.pdf-object-dialog') ? card.querySelector('form') : card
            const previous = scrollHost.scrollTop
            scrollHost.scrollTop = scrollHost.scrollHeight
            const bounds = primary.getBoundingClientRect()
            const visible = scrollHost.getBoundingClientRect()
            scrollHost.scrollTop = previous
            return bounds.top >= Math.max(rect.top,visible.top) && bounds.bottom <= Math.min(rect.bottom,visible.bottom) + 1
          })(),
          horizontalScrollers: scrollers.map(scroller => {
            const previous = scroller.scrollLeft
            scroller.scrollLeft = scroller.scrollWidth
            const reachable = scroller.scrollLeft >= scroller.scrollWidth - scroller.clientWidth - 1
            scroller.scrollLeft = previous
            const bounds = scroller.getBoundingClientRect()
            return { reachable, contained: bounds.left >= rect.left && bounds.right <= rect.right + 1 }
          }),
          pageOverflow: document.documentElement.scrollWidth > innerWidth + 1 }
      })
      evidence.cases.push({ format, viewport: { width, height }, busyState, transitions, ...measurement })
      check(measurement.x >= 7 && measurement.right <= width - 7, '弹窗超出窗口横向边界')
      check(measurement.y >= 7 && measurement.bottom <= height - 7, '弹窗超出窗口纵向边界')
      check(measurement.scrollWidth <= measurement.clientWidth + 1 && !measurement.clipped.length, '字段横向溢出：' + measurement.clipped.join('、'))
      check(!measurement.pageOverflow, '页面横向溢出')
      check(measurement.font.includes('Noto Sans'), '弹窗字体未沿用编辑器主题')
      if (requiresPrimary) {
        if (measurement.primaryDisabled) {
          check(measurement.disabledPrimaryStyled && measurement.primaryBackground === 'rgb(157, 180, 200)' && measurement.primaryImage === 'none'
            || (measurement.pdfDisabledPrimaryStyled || measurement.workbookDisabledPrimaryStyled) && measurement.primaryBackground === 'rgb(11, 79, 138)', '禁用主操作未沿用主题禁用态')
        } else {
          check(measurement.primaryBackground === 'rgb(11, 79, 138)' || measurement.primaryImage?.includes('rgb(11, 79, 138)'), '主操作未沿用 Office 主题色')
        }
        check(measurement.primaryReachable, '滚动至末端后仍无法完整访问主操作')
      }
      check(measurement.horizontalScrollers.every(scroller => scroller.reachable && scroller.contained), '内部横向滚动区域无法完整访问或超出弹窗')
      check(measurement.parameterInputWidths.every(value => value >= 140), '函数参数输入区域过窄')
      check(measurement.checkboxSizes.every(bounds => bounds.width <= 24 && bounds.height <= 24), '复选框被文本输入框尺寸拉伸')
      check(measurement.pdfFields.every(field => field.height >= field.minimumHeight && field.font.includes('Noto Sans')), 'PDF 字段尺寸或字体未沿用设置主题')
      if (format.startsWith('pdf') && width >= 1000) check(measurement.pdfDesktopLabels.every(Boolean), 'PDF PC 设置未保持左标签右字段')
      if (format === 'pdf-host-stamp' && width >= 1000) check(measurement.width >= 700, '印章桌面宽弹窗被旧样式覆盖')
      if (format === 'pdf-host-crop' && width >= 1000) check(measurement.scrollHeight <= measurement.clientHeight + 1, 'PC 裁切窗口需要滚动才能查看全部设置')
      if (format.startsWith('pdf') && requiresPrimary) check(measurement.pdfActions === 'flex-end', 'PDF 主操作未放入右对齐操作区')
      if (format.startsWith('pdf')) check(!!measurement.pdfAccessibleName?.trim(), 'PDF 弹窗缺少无障碍名称')
      check(measurement.wordFields.every(field => field.height >= 32 && field.font.includes('Noto Sans')), 'Word 字段尺寸或字体未沿用设置界面主题')
      check(measurement.wordButtons.every(button => button.height >= 28 && button.font.includes('Noto Sans')), 'Word 操作按钮尺寸或字体未沿用设置界面主题')
      check(measurement.wordHiddenFields === 0, 'Word 隐藏字段仍然可见')
      if (format.startsWith('docx-') && width >= 1000) {
        const rows = measurement.wordDesktopLabels
        check(rows.every(row => row.aligned) && (!rows.length || Math.max(...rows.map(row => row.left)) - Math.min(...rows.map(row => row.left)) <= 2), 'Word PC 设置未保持左标签右字段及字段起点对齐')
      }
      check(measurement.workbookFields.every(field => field.height >= field.minimumHeight && field.font.includes('Noto Sans')), 'Excel 字段尺寸或字体未沿用设置界面主题')
      check(measurement.workbookSettingButtons.every(button => button.height >= 28 && button.font.includes('Noto Sans')), 'Excel 设置按钮尺寸或字体未沿用主题')
      check(measurement.headerFooterFields.every(field => field.width >= 180 && field.height >= 64), 'Excel 页眉页脚编辑区域过窄或过矮')
      check(measurement.definedNameListHeight === null || measurement.definedNameListHeight >= 120, 'Excel 名称管理器列表被压成单行')
      check(measurement.gotoListHeight === null || measurement.gotoListHeight <= 260, 'Excel 定位名称列表未限定内部滚动高度')
      if (format.startsWith('xlsx-header-footer') && width >= 1000) check(measurement.width >= 700, 'Excel 页眉页脚未使用桌面宽弹窗')
      if (format.startsWith('xlsx-fill-') && width >= 1000) check(measurement.seriesGroupsSideBySide, 'Excel 序列分组选项未采用桌面并列布局')
      if (width >= 1000) check(measurement.workbookDesktopLabels.every(Boolean), 'PC 设置界面未采用左标签右字段布局')
      check(measurement.visibleHiddenFields.length === 0, 'Excel 分类隐藏字段仍然可见：' + measurement.visibleHiddenFields.join('、'))
      check(measurement.workbookCheckboxRows.every(Boolean), 'Excel 复选框未与标签同行')
      check(measurement.numfmtSelectionDistinct, '数字格式当前分类缺少选中态')
      check(measurement.pivotControlGaps.every(gap => gap >= 6), '透视字段控件与添加按钮缺少间距')
      if (['xlsx-pivot-empty', 'xlsx-pivot-configured'].includes(format) && width >= 1000) {
        check(measurement.width >= 700, '透视配置桌面宽弹窗被基础格式弹窗样式覆盖')
      }
      if (format.startsWith('xlsx-numfmt-')) {
        const fields = { general: [], number: ['decimals', 'thousands', 'negative'], currency: ['decimals', 'symbol', 'negative'], accounting: ['decimals', 'symbol'],
          date: ['date'], time: ['time'], percentage: ['decimals'], fraction: ['fraction'], scientific: ['decimals'], text: [], custom: ['custom'] }
        check(JSON.stringify(measurement.numfmtFields) === JSON.stringify(fields[format.slice('xlsx-numfmt-'.length)]), '数字格式分类展示了不对应的字段')
      }
      if(objectChrome){
        const close=dialog.locator('[data-pdf-object-close]'),title=dialog.getByRole('heading')
        check(await title.count()===1&&await title.textContent()===await dialog.getAttribute('aria-label'),'缺少与窗口名称对应的可见标题')
        check(await close.count()===1,'缺少标题关闭按钮')
        if(width>=1000)check(measurement.width===560,'对象编辑窗口未采用560px桌面宽度')
        const last=dialog.locator('form button').last();await last.focus();await last.scrollIntoViewIfNeeded()
        await page.keyboard.press('Tab')
        check(await dialog.evaluate(node=>node.contains(document.activeElement)),'从最后操作按Tab离开窗口')
        if(await close.count()){
          check(await close.evaluate(node=>document.activeElement===node),'Tab未返回标题关闭')
          await page.keyboard.press('Shift+Tab');check(await last.evaluate(node=>document.activeElement===node),'Shift+Tab未返回最后操作')
          const bounds=await close.evaluate(node=>{const r=node.getBoundingClientRect(),d=node.closest('dialog').getBoundingClientRect();return {inside:r.y>=d.y&&r.bottom<=d.bottom,hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}})
          check(bounds.inside&&bounds.hit,'滚动到操作区后标题关闭被裁切或遮挡')
        }
      }
      await page.keyboard.press('Tab')
      const focus = await dialog.evaluate(element => {
        const active = document.activeElement
        return { contained: element.contains(active), outlineWidth: parseFloat(getComputedStyle(active).outlineWidth) }
      })
      evidence.cases.at(-1).keyboard = focus
      check(focus.contained && focus.outlineWidth >= 2, '键盘焦点越界或焦点环不清晰')
      if (/^pdf-(convert|image-export)-pending$/.test(format)) {
        const pendingKeyboard = []
        for (const key of ['Tab', 'Shift+Tab', 'Tab']) {
          await page.keyboard.press(key)
          const contained = await dialog.evaluate(element => element.contains(document.activeElement) && document.activeElement.textContent === '关闭')
          pendingKeyboard.push({ key, contained }); check(contained, 'PDF 处理中仅剩关闭按钮时 Tab 焦点离开弹窗')
        }
        evidence.cases.at(-1).pendingKeyboard = pendingKeyboard
      }
      await page.screenshot({ path: join(directory, `${format}-${width}x${height}.png`) })
      if (process.env.OFFICE_MODAL_IME === '1') {
        const field = dialog.locator('textarea:visible:not([disabled]),input:visible:not([disabled]):not([type=checkbox]):not([type=radio])').first()
        assert.equal(await field.count(), 1, `IME probe needs an editable field: ${format}`)
        await field.focus()
        const value = await field.inputValue(), events = []
        for (const protection of ['composition', 'legacy', 'handled']) {
          const result = await field.evaluate((node, protection) => {
            const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
            if (protection === 'handled') event.preventDefault()
            node.dispatchEvent(event)
            return { protection, connected: node.isConnected, focused: document.activeElement === node, defaultPrevented: event.defaultPrevented }
          }, protection)
          assert.equal(await dialog.isVisible(), true, `${format}: ${protection} Escape closed the dialog`)
          assert.equal(await field.inputValue(), value)
          assert(result.connected && result.focused, JSON.stringify(result))
          events.push(result)
        }
        await field.evaluate(node => node.addEventListener('keydown', event => { if (event.key === 'Escape') event.preventDefault() }, { once: true }))
        await field.press('Escape')
        assert.equal(await dialog.isVisible(), true, `${format}: consumed trusted Escape closed the dialog`)
        assert.equal(await field.inputValue(), value)
        if (['pptx-link', 'pptx-find-ime'].includes(format)) {
          for (const protection of ['composition', 'legacy', 'handled']) {
            const result = await field.evaluate((node, protection) => {
              const dialog = node.closest('dialog'), before = dialog.textContent
              const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
              if (protection === 'handled') event.preventDefault()
              node.dispatchEvent(event)
              return { key: 'Enter', protection, connected: node.isConnected, focused: document.activeElement === node, contentUnchanged: dialog.textContent === before }
            }, protection)
            assert.equal(await dialog.isVisible(), true, `${format}: ${protection} Enter submitted the dialog`)
            assert(result.connected && result.focused && result.contentUnchanged, JSON.stringify(result))
            assert.equal(await field.inputValue(), value)
            events.push(result)
          }
        }
        evidence.ime ??= []
        evidence.ime.push({ format, width, height, events, consumedTrustedEscapePreserved: true, fieldUnchanged: true })
      }
      const previousScroll = await dialog.evaluate(element => {
        const card = element.querySelector('.modal-card') ?? element
        if (card.scrollHeight <= card.clientHeight + 1) return null
        const previous = card.scrollTop; card.scrollTop = card.scrollHeight; return previous
      })
      if (previousScroll !== null) {
        await page.screenshot({ path: join(directory, `${format}-${width}x${height}-actions.png`) })
        await dialog.evaluate((element, previous) => { (element.querySelector('.modal-card') ?? element).scrollTop = previous }, previousScroll)
      }
      await page.keyboard.press('Escape')
      check(await dialog.count() === 0 || !await dialog.isVisible(), 'Esc 未关闭弹窗')
      check(await page.evaluate(() => (window.officeDialogFocusTarget ?? [...document.querySelectorAll('button')].find(button => button.textContent === '打开设置')) === document.activeElement), '关闭后焦点未回到入口')
      if(objectChrome){
        const opener=format==='pdf-host-note-edit'?page.locator('.pdf-pending-note button').first():page.locator('.pdf-pending-drawings-panel').getByRole('button',{name:format==='pdf-host-drawing-move'?'移动所选绘图':'缩放所选图像',exact:true})
        await opener.scrollIntoViewIfNeeded()
        evidence.cases.at(-1).objectEntry=await opener.evaluate(node=>{
          const r=node.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)
          const parents=[];for(let parent=node.parentElement;parent;parent=parent.parentElement){const b=parent.getBoundingClientRect(),s=getComputedStyle(parent);parents.push({class:parent.className,y:b.y,bottom:b.bottom,height:b.height,scrollHeight:parent.scrollHeight,clientHeight:parent.clientHeight,overflowY:s.overflowY,flex:s.flex})}
          return {x:r.x,y:r.y,bottom:r.bottom,accessible:node.contains(hit),hit:hit?.outerHTML.slice(0,300),parents}
        })
        await page.screenshot({path:join(directory,`${format}-${width}x${height}-entry.png`)})
        await opener.click({timeout:5000});await dialog.waitFor()
        const field=dialog.locator('textarea,input').first();await field.fill(format==='pdf-host-note-edit'?'取消后不应保存的正文':'12')
        const close=dialog.locator('[data-pdf-object-close]')
        const hasTitleClose=await close.count()===1
        if(hasTitleClose)await close.click();else await dialog.getByRole('button',{name:'取消',exact:true}).click()
        await dialog.waitFor({state:'hidden'})
        check(await opener.evaluate(node=>document.activeElement===node),'标题关闭后未返回实际产品入口')
        assert.deepEqual(await readDrafts(page),draftsBefore)
        evidence.cases.at(-1).objectChrome={titleCloseChecked:hasTitleClose,draftUnchanged:true}
      }
    }
    console.log(JSON.stringify({ checked: format, cases: viewports.length }))
    await context.close()
  }
  assert.deepEqual(evidence.pageErrors, [])
  assert.deepEqual(evidence.failures, [])
  console.log(JSON.stringify({ cases: evidence.cases.length, failures: evidence.failures, directory }))
} catch (error) {
  evidence.error = String(error)
  throw error
} finally {
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2))
  await browser?.close()
  server.kill('SIGTERM')
}
