// 真实 XLSX + 产品原生宿主；授权/修订接口为路由夹具，不代表生产服务端验收。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = resolve(frontend, '../../..')
const output = resolve(process.env.OFFICE_WORKBOOK_PANEL_OUTPUT ?? '/tmp/office-workbook-panels-20261112')
const port = Number(process.env.OFFICE_WORKBOOK_PANEL_PORT ?? 4295), base = `http://127.0.0.1:${port}`
const modes = process.env.OFFICE_WORKBOOK_PANEL_CASES?.split(',') ?? ['dv-empty', 'dv-list', 'cf-empty', 'cf-list']
const dvTypes = { any: '任意值', whole: '整数', decimal: '数字', length: '文本长度', date: '日期', checkbox: '复选框', list: '下拉菜单', multi: '下拉菜单-多选', formula: '自定义公式' }
const cfTypes = { highlight: '突出显示单元格', rank: '最前/最后/平均值', bar: '数据条', scale: '色阶', formula: '自定义公式', icons: '图标集' }
const widths = process.env.OFFICE_WORKBOOK_PANEL_VIEWPORTS?.split(',').map(item => item.split('x').map(Number)) ?? (process.env.OFFICE_WORKBOOK_PANEL_DISCOVERY ? [[1440, 900]] : [[1440, 900], [768, 1024], [390, 844], [320, 640], [640, 360], [390, 320]])
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const generated = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64,json
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import CellIsRule,ColorScaleRule
result={}
for name in ['empty','configured']:
 book=Workbook();sheet=book.active;sheet.title='经营数据'
 for row in range(1,11):sheet.cell(row,1,row*20);sheet.cell(row,2,'经营数据'+str(row))
 if name=='configured':
  validation=DataValidation(type='whole',operator='between',formula1=0,formula2=100,allow_blank=True);validation.promptTitle='经营数据录入';validation.prompt='请输入0到100的整数。';validation.showInputMessage=True;sheet.add_data_validation(validation);validation.add('A1:A10')
  sheet.conditional_formatting.add('A1:A10',CellIsRule(operator='greaterThan',formula=['100'],fill=PatternFill('solid',fgColor='FFFF6666')))
  sheet.conditional_formatting.add('B1:B10',ColorScaleRule(start_type='min',start_color='FF63BE7B',end_type='max',end_color='FFF8696B'))
 stream=BytesIO();book.save(stream);result[name]=base64.b64encode(stream.getvalue()).decode()
print(json.dumps(result))
`], { cwd: repo, encoding: 'utf8' })
assert.equal(generated.status, 0, generated.stderr)
const sources = Object.fromEntries(Object.entries(JSON.parse(generated.stdout)).map(([key, value]) => [key, Buffer.from(value, 'base64')]))
const dist = process.env.OFFICE_WORKBOOK_PANEL_DIST
const manifestPath = dist ? join(resolve(frontend, dist), '.vite/manifest.json') : null
const manifestSha256 = manifestPath ? sha(await readFile(manifestPath)) : null
const server = spawn('./node_modules/.bin/vite', [...(dist ? ['preview', '--outDir', dist] : []), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
let serverLog = '', browser
server.stdout.on('data', data => { serverLog += data }); server.stderr.on('data', data => { serverLog += data })
const evidence = { kind: 'real-xlsx-native-host-route-fixture', productionBuild:!!dist, manifestSha256, cases: [], failures: [], pageErrors: [] }
try {
  await mkdir(output, { recursive: true })
  for (let attempt = 0; ; attempt++) {
    if (server.exitCode !== null) throw Error(serverLog)
    try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    if (attempt > 120) throw Error(serverLog)
    await delay(250)
  }
  browser = await chromium.launch({ headless: true })
  for (const mode of modes) {
    for (const [width, height] of widths) {
      let phase = 'opening'
      const page = await browser.newPage()
      await page.addInitScript(() => localStorage.clear())
      page.on('pageerror', error => evidence.pageErrors.push({ mode, width, height, phase, message: error.message, stack: error.stack }))
      page.on('dialog', dialog => dialog.type() === 'beforeunload' ? dialog.accept() : dialog.dismiss())
      const bytes = sources[mode.endsWith('empty') || mode.endsWith('add') ? 'empty' : 'configured']
      const identity = { documentId: 'ui-' + mode, revision: 1, parentRevision: null, format: 'xlsx', origin: 'upload',
        scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
        sourceFile: { path: 'office-panel.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' } }
      await page.route('**/favicon.ico', route => route.fulfill({ body: '', status: 200 }))
      await page.route('**/api/context', route => route.fulfill({ json: { context: identity, csrfToken: 'fixture', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
      await page.route('**/api/file', route => route.fulfill({ body: bytes, contentType: identity.sourceFile.mediaType }))
      await page.route('**/api/save', route => route.fulfill({ status: 500, json: { detail: '布局检查不保存文件' } }))
      await page.route(`**/reports/v1/native/${identity.documentId}/1`, async route => {
        const response = await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }); await route.fulfill({ response })
      })
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.goto(`${base}/reports/v1/native/${identity.documentId}/1`)
      await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 90000 })
      await page.locator(`[data-ribbon-tab="${mode.startsWith('dv') ? 'Data' : 'Home'}"]`).click()
      await page.locator(`[data-ribbon-command="${mode.startsWith('dv') ? 'dv-open' : 'cf-open'}"]`).click()
      const panel = page.locator('[data-u-comp=sidebar][aria-expanded=true]')
      await panel.waitFor({ timeout: 30000 })
      const closeFocus = await panel.getByRole('button', { name: 'Close sidebar' }).evaluate(node => ({ active: document.activeElement === node, outline: getComputedStyle(node).outlineWidth }))
      if (mode === 'dv-edit' || mode === 'dv-types' || mode === 'dv-advanced' || mode === 'dv-message' || mode.startsWith('dv-type-')) await panel.getByText('整数 介于 0 和 100 之间', { exact: true }).click()
      if (mode === 'dv-add') await panel.getByRole('button', { name: '新建规则', exact: true }).click()
      if (mode === 'cf-edit' || mode === 'cf-types' || mode.startsWith('cf-type-')) await panel.getByText('大于100', { exact: true }).click()
      if (mode === 'cf-add') await panel.locator('a:has(.univerjs-icon-increase-icon)').click()
      if (mode === 'dv-advanced' || mode === 'dv-message') await panel.getByText('高级设置', { exact: true }).click()
      if (mode === 'dv-message') await panel.getByText('显示所选单元格的提示文字', { exact: true }).click()
      const typeLabel = mode.startsWith('dv-type-') ? dvTypes[mode.slice(8)] : mode.startsWith('cf-type-') ? cfTypes[mode.slice(8)] : null
      if (typeLabel) {
        await panel.locator('[data-u-comp=select]').first().click()
        await page.getByRole('menuitemradio', { name: typeLabel, exact: true }).click()
      }
      if (mode.endsWith('-types')) await panel.locator('[data-u-comp=select]').first().click()
      await page.setViewportSize({ width, height })
      phase = 'layout'
      await page.evaluate(() => document.fonts.ready)
      await delay(200)
      const measurement = await panel.evaluate(element => {
        const bounds = element.getBoundingClientRect(), style = getComputedStyle(element)
        return { x: bounds.x, y: bounds.y, width: bounds.width, right: bounds.right, bottom: bounds.bottom, font: style.fontFamily,
          overflow: element.scrollWidth > element.clientWidth + 1,
          components: [...element.querySelectorAll('[data-u-comp]')].map(node => node.dataset.uComp),
          controls: [...element.querySelectorAll('input,textarea,button,[role=combobox],[data-u-comp=select]')].filter(node => { const rect = node.getBoundingClientRect(); return rect.width > 0 && rect.height > 0 }).map(node => {
            const rect = node.getBoundingClientRect(), computed = getComputedStyle(node)
            return { tag: node.tagName, role: node.getAttribute('role'), component: node.dataset.uComp, label: node.getAttribute('aria-label'), text: node.textContent.trim(), x: rect.x, right: rect.right, width: rect.width, height: rect.height, font: computed.fontFamily, color: computed.color, background: computed.backgroundColor }
          }), primary: [...element.querySelectorAll('button.univer-bg-primary-600')].filter(node => node.getClientRects().length).map(node => getComputedStyle(node).backgroundColor),
          text: element.textContent }
      })
      const check = (condition, message) => { if (!condition) evidence.failures.push(`${mode} ${width}×${height}: ${message}`) }
      check(measurement.x >= -1 && measurement.right <= width + 1 && !measurement.overflow, '侧边栏横向溢出视口')
      check(measurement.bottom <= height + 1, '侧边栏底部超出视口')
      check(measurement.font.includes('Noto Sans'), '侧边栏字体未沿用编辑器主题')
      check(closeFocus.active && closeFocus.outline === '2px', '打开面板未聚焦关闭按钮或缺少焦点环')
      check(measurement.controls.every(control => control.x >= measurement.x - 1 && control.right <= measurement.right + 1), '面板字段或按钮横向裁切')
      check(measurement.primary.every(color => color === 'rgb(11, 79, 138)'), '框架主操作未沿用 Office 主题色')
      check(measurement.controls.filter(control => control.label === 'Close sidebar').every(control => control.width >= 28 && control.height >= 28), '侧边栏关闭按钮过小')
      check(measurement.controls.filter(control => control.tag === 'INPUT' || control.tag === 'TEXTAREA' || control.component === 'select').every(control => control.height >= 30 && control.font.includes('Noto Sans')), '框架字段尺寸或字体与设置主题不一致')
      const menu = page.getByRole('menu')
      if (mode.endsWith('-types')) {
        await menu.waitFor()
        measurement.menu = await menu.evaluate(node => { const rect = node.getBoundingClientRect(), style = getComputedStyle(node); return { x:rect.x, right:rect.right, y:rect.y, bottom:rect.bottom, font:style.fontFamily, accent:style.getPropertyValue('--univer-primary-600').trim(), text: node.textContent, html: node.outerHTML } })
        check(measurement.menu.x >= -1 && measurement.menu.right <= width + 1 && measurement.menu.y >= -1 && measurement.menu.bottom <= height + 1, '类型菜单超出视口')
        check(measurement.menu.font.includes('Noto Sans') && measurement.menu.accent === '#0b4f8a', '类型菜单未沿用主题')
      }
      await page.screenshot({ path: join(output, `${mode}-${width}x${height}.png`) })
      await writeFile(join(output, `${mode}-${width}x${height}.html`), await panel.evaluate(node => node.outerHTML))
      if (!mode.endsWith('-types')) {
        const lastButton = panel.locator('button:visible').last()
        await lastButton.scrollIntoViewIfNeeded()
        measurement.lastAction = await lastButton.evaluate(node => { const rect = node.getBoundingClientRect(), middle = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2); return { text:node.textContent, top:rect.top, bottom:rect.bottom, reachable:node.contains(middle) } })
        check(measurement.lastAction.reachable && measurement.lastAction.top >= 0 && measurement.lastAction.bottom <= height + 1, '底部操作无法滚动访问')
        if (height <= 360) await page.screenshot({ path: join(output, `${mode}-${width}x${height}-scrolled.png`) })
      }
      evidence.cases.push({ mode, width, height, sourceSha256: sha(bytes), measurement })
      if (mode === 'cf-list' && width === 1440) {
        const resize = panel.getByRole('separator', { name:'Resize sidebar' })
        await resize.focus(); await page.keyboard.press('ArrowRight')
        const expandedWidth = await panel.evaluate(node => node.getBoundingClientRect().width)
        check(expandedWidth === measurement.width + 20, '桌面键盘调整侧栏宽度失效')
        await page.keyboard.press('ArrowLeft')
        measurement.resize = { original:measurement.width, expanded:expandedWidth, restored:await panel.evaluate(node => node.getBoundingClientRect().width) }
        check(measurement.resize.restored === measurement.width, '桌面侧栏宽度未能恢复')
      }
      phase = 'closing'
      if (process.env.OFFICE_WORKBOOK_PANEL_TEARDOWN !== 'open') {
        await page.keyboard.press('Escape')
        if (mode.endsWith('-types') && await panel.count()) await page.keyboard.press('Escape')
        check(await panel.count() === 0, 'Escape 未关闭侧边栏')
      }
      phase = 'disposing'
      if (['1', 'open'].includes(process.env.OFFICE_WORKBOOK_PANEL_TEARDOWN)) {
        // 保留当前JS上下文观察卸载后的异步异常，避免page.close立即销毁上下文而漏报。
        // 这里显式触发真实宿主的pagehide处理器，不冒称真实浏览器导航。
        measurement.teardown = await page.evaluate(async () => {
          const host = document.querySelector('#report-editor')
          const before = host?.querySelectorAll('canvas').length ?? 0
          const sidebarOpen = !!document.querySelector('[data-u-comp=sidebar][aria-expanded=true]')
          if (host) host.style.width = `${Math.max(200, innerWidth - 37)}px`
          await new Promise(resolve => requestAnimationFrame(resolve))
          window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false }))
          await new Promise(resolve => setTimeout(resolve, 500))
          return { explicitPagehide: true, sidebarOpen, canvasBefore: before, canvasAfter: host?.querySelectorAll('canvas').length ?? 0 }
        })
        check(measurement.teardown.canvasBefore > 0, '卸载检查前未挂载真实工作簿画布')
        check(measurement.teardown.canvasAfter === 0, '卸载后仍保留工作簿画布')
        check(measurement.teardown.sidebarOpen === (process.env.OFFICE_WORKBOOK_PANEL_TEARDOWN === 'open'), '卸载前侧栏状态与检查要求不符')
      }
      await page.close()
    }
  }
} finally {
  await browser?.close(); server.kill('SIGTERM')
  if (manifestPath && sha(await readFile(manifestPath)) !== manifestSha256) evidence.failures.push('检查期间生产构建身份发生变化')
  await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
}
assert.deepEqual(evidence.pageErrors, [])
assert.deepEqual(evidence.failures, [])
console.log(JSON.stringify({ output, cases: evidence.cases.length, failures: evidence.failures }))
