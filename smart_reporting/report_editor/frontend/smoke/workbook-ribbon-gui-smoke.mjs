// 真实浏览器验收（2026-11-08/09 对齐批次）：缩进、格式刷、行高/列宽对话框、自动调整行高、
// 复制粘贴。真实 Chromium + vite 前端 + Playwright 替身 context/file 路由；保存经真实
// Python patch_office（桥接 + 引擎），下载字节再由 openpyxl 独立回读。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd()
const repo = new URL('../../../', `file://${frontend}/`).pathname
const port = Number(process.env.WORKBOOK_SMOKE_PORT ?? 4191)
const baseUrl = `http://127.0.0.1:${port}`
const python = (input) => {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64, json, sys
from io import BytesIO
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
payload = json.load(sys.stdin)
if payload['mode'] == 'create':
    book = Workbook(); sheet = book.active; sheet.title = 'Summary'
    sheet['A1'] = 'alpha'; sheet['A1'].font = Font(bold=True)
    sheet['A2'] = 'beta'; sheet['B1'] = 'wide'; sheet['C1'] = 'gamma'; sheet['D5'] = '=A2'
    sheet.row_dimensions[2].height = 40
    sheet.column_dimensions['B'].width = 30
    stream = BytesIO(); book.save(stream); print(base64.b64encode(stream.getvalue()).decode())
elif payload['mode'] == 'patch':
    from smart_reporting.report_editor.native_office import patch_office
    print(base64.b64encode(patch_office('xlsx', base64.b64decode(payload['bytes']), payload['operations'])).decode())
else:
    book = load_workbook(BytesIO(base64.b64decode(payload['bytes']))); s = book['Summary']
    print(json.dumps({
      'A1': [s['A1'].value, s['A1'].font.bold, s['A1'].alignment.indent],
      'A2': [s['A2'].value, s['A2'].font.bold, s['A2'].alignment.indent],
      'C1': [s['C1'].value, s['C1'].font.bold],
      'row1': s.row_dimensions[1].height, 'row2': [s.row_dimensions[2].height, s.row_dimensions[2].customHeight],
      'colB': round(s.column_dimensions['B'].width or 0, 2), 'colD': round(s.column_dimensions['D'].width or 0, 2),
      'A3': [s['A3'].value, s['A3'].font.bold, s['A3'].alignment.indent], 'B3': [s['B3'].value, s['B3'].font.bold, s['B3'].alignment.indent],
      'E1': [s['E1'].value, s['E1'].font.bold], 'F1': s['F1'].value, 'B1': s['B1'].value, 'D5': s['D5'].value,
      'showFormulas': bool(s.sheet_view.showFormulas), 'sheetProtected': bool(s.protection.sheet), 'structureLocked': bool(book.security and book.security.lockStructure),
      'sheets': book.sheetnames, 'newSheetA1': [book.worksheets[-1]['A1'].value, book.worksheets[-1]['A1'].font.bold] if len(book.worksheets) > 1 else None}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
const sourceBytes = Buffer.from(python({ mode: 'create' }), 'base64')
const sourceSha = createHash('sha256').update(sourceBytes).digest('hex')
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
let savedBytes, savePayload
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 120; attempt++) { try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['clipboard-read', 'clipboard-write'] })
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()) })
  const ctx = { documentId: 'fixture-gui', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
    sourceFile: { path: 'gui.xlsx', size: sourceBytes.length, sha256: sourceSha, mediaType: media }, origin: 'upload' }
  await page.route('**/reports/v1/native/fixture-gui/1/api/context', route => route.fulfill({ json: { context: ctx, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
  await page.route('**/reports/v1/native/fixture-gui/1/api/file', route => route.fulfill({ body: sourceBytes, contentType: media }))
  await page.route('**/reports/v1/native/fixture-gui/1/api/save', async route => {
    savePayload = route.request().postDataJSON()
    savedBytes = Buffer.from(python({ mode: 'patch', bytes: sourceBytes.toString('base64'), operations: savePayload.operations }), 'base64')
    await route.fulfill({ json: { documentId: 'fixture-gui', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { xlsx: { downloadUrl: '/fixture-gui-download.xlsx', size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } },
      editor: { openUrl: '/reports/v1/native/fixture-gui/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/fixture-gui-download.xlsx', route => route.fulfill({ body: savedBytes, contentType: media }))
  await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/1'))
  await page.goto(`${baseUrl}/reports/v1/editor/assets/native.html`)
  await page.locator('.workbook-ribbon').waitFor({ timeout: 60000 })
  await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
  const feedback = () => page.locator('.workbook-feedback').innerText()
  const command = async id => { const button = page.locator(`[data-ribbon-command="${id}"]`); assert.equal(await button.isDisabled(), false, `${id} must be enabled`); await button.click() }
  // 网格内坐标（截图核对：行头宽 46px、列头高 20px；A 88px、B 为文件 30 字符宽、C/D 88px；
  // 第 2 行为文件 40 磅）。第 1 行改为 30 磅（40px）后第 2 行下移。
  const clickCell = async (x, y) => { await page.locator('.workbook-grid').click({ position: { x, y } }); await delay(300) }
  const A1 = [90, 32], A2 = [90, 70], A2_AFTER_ROW1 = [90, 88], C1 = [393, 32], D1 = [481, 32], A3 = [90, 109], B3 = [240, 109], E1 = [569, 32], B1 = [240, 32]

  if (process.env.WORKBOOK_RIBBON_CASE === 'formulas') {
    // 公式▸显示公式（保存为 sheetView/@showFormulas）、手动计算与开始计算（不产生保存操作）。
    await page.locator('[data-ribbon-tab="Formulas"]').click()
    await page.locator('[data-ribbon-control="calc-mode"]').selectOption('manual')
    assert.match(await feedback(), /计算模式为手动/)
    await command('calculate-now'); assert.match(await feedback(), /已重新计算工作簿/)
    await page.locator('[data-ribbon-control="calc-mode"]').selectOption('auto')
    await command('toggle-show-formulas')
    assert.equal(await page.locator('[data-ribbon-command="toggle-show-formulas"]').getAttribute('aria-pressed'), 'true')
    if (process.env.WORKBOOK_SMOKE_SCREENSHOT) await page.locator('.workbook-grid').screenshot({ path: process.env.WORKBOOK_SMOKE_SCREENSHOT })
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
    console.log(JSON.stringify({ ok: true, case: 'formulas', browserVersion: browser.version(), operations: savePayload.operations, reopened, pageErrors }))
    assert.deepEqual(savePayload.operations, [{ kind: 'applyPageSetups', setups: [{ sheetName: 'Summary', showFormulas: true }] }])
    assert.equal(reopened.showFormulas, true)
    assert.equal(reopened.D5, '=A2')
    assert.deepEqual(pageErrors, [])
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'protect') {
    // 先改 A2，再保护工作表与工作簿结构；保护后 A1 键入被拒绝。
    await clickCell(...A2); await page.keyboard.type('edited'); await page.keyboard.press('Enter'); await delay(500)
    await page.locator('[data-ribbon-tab="Review"]').click()
    await command('sheet-protect'); await command('workbook-protect')
    assert.equal(await page.locator('[data-ribbon-command="sheet-protect"]').innerText(), '撤销工作表保护')
    assert.equal(await page.locator('[data-ribbon-command="workbook-protect"]').getAttribute('aria-pressed'), 'true')
    await clickCell(...A1); await page.keyboard.type('blocked'); await page.keyboard.press('Enter'); await delay(500)
    assert.match(await feedback(), /工作表受保护/)
    await page.locator('[data-ribbon-tab="Home"]').click()
    assert.equal(await page.locator('[data-ribbon-command="bold"]').isDisabled(), true)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
    const operationKinds = savePayload.operations.map(op => op.kind)
    console.log(JSON.stringify({ ok: true, case: 'protect', browserVersion: browser.version(), operationKinds, reopened, pageErrors }))
    assert.deepEqual(operationKinds, ['applyCellEdits', 'protectSheet', 'protectWorkbookStructure'])
    assert.equal(reopened.A1[0], 'alpha')
    assert.equal(reopened.A2[0], 'edited')
    assert.equal(reopened.sheetProtected, true)
    assert.equal(reopened.structureLocked, true)
    assert.deepEqual(pageErrors, [])
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'cells') {
    // 插入单元格：A1 下移（对话框默认项）；删除单元格：B1 右侧左移。
    await clickCell(...A1); await command('insert-cells')
    await page.locator('.workbook-ribbon-cells-dialog input[value="shift-vertical"]').waitFor()
    assert.equal(await page.locator('.workbook-ribbon-cells-dialog input[value="shift-vertical"]').isChecked(), true)
    await page.locator('.workbook-ribbon-cells-dialog .workbook-ribbon-format-apply').click(); await delay(800)
    await clickCell(...B1); await command('delete-cells')
    await page.locator('.workbook-ribbon-cells-dialog input[value="shift-horizontal"]').check()
    await page.locator('.workbook-ribbon-cells-dialog .workbook-ribbon-format-apply').click(); await delay(800)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
    const operationKinds = savePayload.operations.map(op => op.kind)
    console.log(JSON.stringify({ ok: true, case: 'cells', browserVersion: browser.version(), operations: savePayload.operations.filter(op => op.kind === 'applyCellShift'), operationKinds, reopened, pageErrors }))
    assert.deepEqual(savePayload.operations.filter(op => op.kind === 'applyCellShift'), [
      { kind: 'applyCellShift', sheetName: 'Summary', range: 'A1', shift: 'down' },
      { kind: 'applyCellShift', sheetName: 'Summary', range: 'B1', shift: 'left' },
    ])
    assert.equal(reopened.A1[0], null)
    assert.deepEqual(reopened.A2.slice(0, 2), ['alpha', true])
    assert.equal(reopened.A3[0], 'beta')
    assert.equal(reopened.B1, 'gamma')
    assert.equal(reopened.D5, '=A3')
    assert.deepEqual(pageErrors, [])
  } else {

  // 1. 缩进：A1 增加两级。
  await clickCell(...A1); await command('indent-step:increase'); await command('indent-step:increase')
  // 2. 格式刷：A1（粗体+缩进 2）单击刷一次到 A2（键盘移动选区）。
  // Univer 在首次渲染 3 秒后（Steady）才安装格式刷默认钩子；此前按钮应禁用。
  await page.waitForFunction(() => !document.querySelector('[data-ribbon-command="format-painter"]')?.disabled, null, { timeout: 15000 })
  await clickCell(...A1); await command('format-painter')
  assert.equal(await page.locator('[data-ribbon-command="format-painter"]').getAttribute('aria-pressed'), 'true')
  await clickCell(...A2)
  assert.equal(await page.locator('[data-ribbon-command="format-painter"]').getAttribute('aria-pressed'), 'false', '单次格式刷应用后自动解除')
  // 2b. 锁定格式刷（双击）：A1 格式连续刷到 A3、B3，Esc 取消。
  await clickCell(...A1)
  await page.locator('[data-ribbon-command="format-painter"]').dblclick()
  await page.waitForFunction(() => /格式刷已锁定/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''), null, { timeout: 10000 })
  await clickCell(...A3); await clickCell(...B3)
  assert.equal(await page.locator('[data-ribbon-command="format-painter"]').getAttribute('aria-pressed'), 'true', '锁定格式刷连续应用后仍保持')
  await page.keyboard.press('Escape'); await delay(300)
  assert.equal(await page.locator('[data-ribbon-command="format-painter"]').getAttribute('aria-pressed'), 'false', 'Esc 取消锁定格式刷')
  // 2c. 外部富文本粘贴：系统剪贴板写入 HTML 表格，粘贴到 E1。
  await page.evaluate(async () => {
    const html = '<table><tr><td><b>外部</b></td><td>2</td></tr></table>'
    await navigator.clipboard.write([new ClipboardItem({ 'text/html': new Blob([html], { type: 'text/html' }), 'text/plain': new Blob(['外部\t2'], { type: 'text/plain' }) })])
  })
  await clickCell(...E1); await command('paste')
  await page.waitForFunction(() => /已粘贴|剪贴板|Cannot/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''), null, { timeout: 15000 })
  const externalPasteFeedback = await feedback()
  // 3. 行高对话框：第 1 行 30 磅。
  await clickCell(...A1); await command('row-height-open')
  await page.locator('.workbook-ribbon-axis-value').fill('30'); await page.locator('.workbook-ribbon-axis-dialog .workbook-ribbon-format-apply').click()
  assert.match(await feedback(), /行高已更新/)
  // 4. 列宽对话框：D 列 12 字符。
  await clickCell(...D1); await command('col-width-open')
  await page.locator('.workbook-ribbon-axis-value').fill('12,5'); await page.locator('.workbook-ribbon-axis-dialog .workbook-ribbon-format-apply').click()
  assert.match(await feedback(), /列宽已更新/)
  // 5. 自动调整行高：第 2 行（文件自定义 40 磅）回到自动。
  await clickCell(...A2_AFTER_ROW1); await command('autofit-row-height')
  await page.waitForFunction(() => /行高已按内容自动调整/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''), null, { timeout: 20000 })
  // 6. 复制 A1 → 粘贴到 C1（真实剪贴板权限）。
  await clickCell(...A1); await command('copy')
  await page.waitForFunction(() => /已复制/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''), null, { timeout: 10000 })
  await clickCell(...C1); await command('paste')
  await page.waitForFunction(() => /已粘贴|剪贴板|Cannot/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''), null, { timeout: 15000 })
  const pasteFeedback = await feedback()
  // 7. 跨工作表：A1 复制后新建工作表并粘贴到新表 A1。
  await clickCell(...A1); await command('copy')
  await page.waitForFunction(() => /已复制/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''), null, { timeout: 10000 })
  // 功能区无"插入工作表"按钮；用 Univer 工作表栏左下角的"+"新增工作表（新表成为活动表）。
  const grid = await page.locator('.workbook-grid').boundingBox()
  await page.mouse.click(grid.x + 35, grid.y + grid.height - 18); await delay(1000)
  await clickCell(...A1); await command('paste')
  await page.waitForFunction(() => /已粘贴|剪贴板|Cannot/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''), null, { timeout: 15000 })
  const crossSheetFeedback = await feedback()

  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
  const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
  const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
  const result = { ok: true, browserVersion: browser.version(), pasteFeedback, externalPasteFeedback, crossSheetFeedback, operationKinds: savePayload.operations.map(op => op.kind), reopened, pageErrors }
  console.log(JSON.stringify(result))
  assert.deepEqual(reopened.A1, ['alpha', true, 2])
  assert.deepEqual(reopened.A2, ['beta', true, 2])
  assert.equal(reopened.row1, 30)
  assert.deepEqual(reopened.row2, [null, false])
  // 12.5 字符按网格整像素取整（(round(12.5*7+5)-5)/7 = 12.57），与文件单位换算一致。
  assert.equal(reopened.colD, 12.57)
  assert.equal(reopened.colB, 30)
  assert.deepEqual(reopened.C1, ['alpha', true])
  assert.deepEqual(reopened.A3, [null, true, 2])
  assert.deepEqual(reopened.B3, [null, true, 2])
  assert.deepEqual(reopened.E1, ['外部', true])
  assert.equal(reopened.F1, 2)
  assert.deepEqual(reopened.sheets.length, 2)
  assert.deepEqual(reopened.newSheetA1, ['alpha', true])
  assert.deepEqual(pageErrors, [])
  }
} finally {
  await browser?.close()
  server.kill()
}
