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
    sheet['A2'] = 'beta'; sheet['B1'] = 'wide'; sheet['C3'] = -1234.5; sheet['C1'] = 'gamma'; sheet['D5'] = '=A2'
    sheet.row_dimensions[2].height = 40
    sheet.column_dimensions['B'].width = 30
    if payload.get('case') == 'data-table':
        sheet['A1'] = None; sheet['B1'] = '=D1*2'; sheet['D1'] = 10
        sheet['A2'] = 3; sheet['A3'] = 5; sheet['B2'] = None; sheet['B3'] = None
    if payload.get('case') == 'goal-seek':
        sheet['B1'] = '=D1*2'; sheet['D1'] = 10; sheet['F1'] = '=D1*0+5'
    if payload.get('case') == 'consolidate':
        west = book.create_sheet('West Side')
        for row in [('Ada',2),('Bob',4),('Ada',6)]: west.append(row)
        other = book.create_sheet("O'Brien")
        for row in [('Bob',10),('Cara',20)]: other.append(row)
    if payload.get('case') == 'name-scope':
        from openpyxl.workbook.defined_name import DefinedName
        other = book.create_sheet('Other Sheet'); other['A1'] = 30
        book.defined_names.add(DefinedName('Rate', attr_text='10'))
        other.defined_names.add(DefinedName('Rate', attr_text='20', localSheetId=1))
        sheet.print_area = 'A1:B3'
    if payload.get('case') == 'dv':
        from openpyxl.worksheet.datavalidation import DataValidation
        rule = DataValidation(type='whole', operator='greaterThan', formula1='0', promptTitle='数量', prompt='填写正整数', showInputMessage=True)
        rule.add('B2:B5'); sheet.add_data_validation(rule)
    if payload.get('case') == 'dv-names':
        from openpyxl.worksheet.datavalidation import DataValidation
        from openpyxl.workbook.defined_name import DefinedName
        book.defined_names.add(DefinedName('Choices', attr_text='Alias'))
        book.defined_names.add(DefinedName('Alias', attr_text='Summary!$A$1:$A$2'))
        rule = DataValidation(type='list', formula1='=Choices', prompt='选择名称', showInputMessage=True)
        rule.add('C1:C3'); sheet.add_data_validation(rule)
    if payload.get('case') in ('dv-tables', 'table-headers', 'table-header-paste', 'table-name', 'table-resize', 'table-options', 'table-style-options'):
        from openpyxl.worksheet.datavalidation import DataValidation
        from openpyxl.worksheet.table import Table, TableStyleInfo
        sheet['A1'] = 'Name'; sheet['A2'] = 'Ada'; sheet['A3'] = 'Grace'
        table = Table(displayName='Staff', ref='A1:A3')
        if payload.get('case') == 'table-resize' and payload.get('totals'):
            sheet['A4'] = '=SUBTOTAL(103,A2:A3)'; sheet['A4'].font = Font(bold=True)
            table.ref = 'A1:A4'; table.totalsRowCount = 1
        table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium4', showRowStripes=True)
        if payload.get('case') == 'table-style-options':
            table.ref = 'A1:B3'
            sheet['B1'] = 'Qty'; sheet['B2'] = 3; sheet['B3'] = 7
            table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium4', showFirstColumn=True, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
        sheet.add_table(table)
        rule = DataValidation(type='list', formula1='=Staff[Name]', prompt='选择名称', showInputMessage=True)
        rule.add('C1:C3'); sheet.add_data_validation(rule)
        if payload.get('case') in ('table-headers', 'table-header-paste', 'table-name', 'table-resize', 'table-options', 'table-style-options'):
            from openpyxl.workbook.defined_name import DefinedName
            book.defined_names.add(DefinedName('Employees', attr_text='Staff[[Name]]'))
            sheet['D5'] = '=COUNTA(Staff[Name])'
    if payload.get('case') == 'table-create':
        from openpyxl.worksheet.table import Table, TableStyleInfo
        from openpyxl.styles import PatternFill
        for row, values in enumerate([('Name', 'Qty'), ('Ada', 3), ('Grace', 7)], 1):
            for column, value in enumerate(values, 1): sheet.cell(row, column, value)
        sheet['B2'].fill = PatternFill('solid', fgColor='FFCC00')
        sheet['B2'].font = Font(bold=True, color='008800')
        sheet['B2'].number_format = '0.00'
        sheet['A7'] = 'Jane'; sheet['B7'] = 11; sheet['A8'] = 'Lin'; sheet['B8'] = 13
        for row, values in enumerate([('Name', 'Qty'), ('Other', 17), ('Keep', 19)], 1):
            for column, value in enumerate(values, 6): sheet.cell(row, column, value)
        existing = Table(displayName='Staff', ref='F1:G3')
        existing.tableStyleInfo = TableStyleInfo(name='TableStyleMedium4', showFirstColumn=True, showRowStripes=True)
        sheet.add_table(existing)
    if payload.get('case') in ('table-convert', 'table-header-row', 'table-filter-button'):
        from openpyxl.worksheet.datavalidation import DataValidation
        from openpyxl.worksheet.table import Table, TableStyleInfo
        from openpyxl.worksheet.filters import AutoFilter, FilterColumn, Filters
        from openpyxl.workbook.defined_name import DefinedName
        from openpyxl.styles import PatternFill
        for row, values in enumerate([('Name', 'Qty'), ('Ada', 3), ('Grace', 7), ('Total', '=SUBTOTAL(109,B2:B3)')], 1):
            for column, value in enumerate(values, 1): sheet.cell(row, column, value)
        sheet['B2'].fill = PatternFill('solid', fgColor='FFCC00')
        sheet['B2'].font = Font(bold=True, color='008800')
        sheet['B2'].number_format = '0.00'
        staff = Table(displayName='Staff', ref='A1:B4', totalsRowCount=1)
        staff.tableStyleInfo = TableStyleInfo(name='TableStyleMedium23', showFirstColumn=True, showRowStripes=True, showColumnStripes=True)
        staff.autoFilter = AutoFilter(ref='A1:B3', filterColumn=[FilterColumn(colId=1, filters=Filters(filter=['3']))])
        sheet.add_table(staff)
        for row, values in enumerate([('Name', 'Qty'), ('Other', 11), ('Keep', 13)], 1):
            for column, value in enumerate(values, 6): sheet.cell(row, column, value)
        other = Table(displayName='Other', ref='F1:G3')
        other.tableStyleInfo = TableStyleInfo(name='TableStyleDark2', showRowStripes=True)
        sheet.add_table(other)
        sheet['D5'] = '=SUM(Staff[Qty])'
        sheet['D6'] = '=SUM(staff[Qty])'
        sheet['D7'] = '=SUM(Other[Qty])'
        rule = DataValidation(type='list', formula1='=Staff[Name]', prompt='保留结构化列表')
        rule.add('C1:C3'); sheet.add_data_validation(rule)
        book.defined_names.add(DefinedName('Employees', attr_text='Staff[[Name]]'))
    if payload.get('case') == 'dedupe':
        from openpyxl.comments import Comment
        for r, values in enumerate([('Name', 'Flag'), ('Ada', True), ('ADA', True), ('Grace', False), ('Grace', False)], 1):
            for c, value in enumerate(values, 1): sheet.cell(r, c, value)
        sheet['A3'].font = Font(bold=True)
        sheet['A3'].comment = Comment('保留位置批注', 'fixture')
    if payload.get('case') == 'split':
        sheet['A1'] = 'Ada,001,TRUE,=A9'; sheet['B1'] = None; sheet['C1'] = None
        sheet['A2'] = 'Grace,42,FALSE,'
        from openpyxl.comments import Comment
        sheet['B1'].comment = Comment('保留分列批注', 'fixture')
        sheet['B1'].font = Font(bold=True)
    if payload.get('case') == 'flash':
        sheet['A1'] = 'Ada'; sheet['B1'] = 'Lovelace'; sheet['C1'] = 'Ada Lovelace'
        sheet['A2'] = 'Grace'; sheet['B2'] = 'Hopper'; sheet['C2'].font = Font(bold=True)
        from openpyxl.comments import Comment
        sheet['C2'].comment = Comment('保留目标批注', 'fixture')
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
      'C2': [s['C2'].value, s['C2'].font.bold, s['C2'].comment.text if s['C2'].comment else None],
      'outlineSummary': [s.sheet_properties.outlinePr.summaryBelow, s.sheet_properties.outlinePr.summaryRight],
      'outlineRows': {str(k): [v.outlineLevel, v.collapsed, v.hidden] for k,v in s.row_dimensions.items()},
      'outlineCols': {str(k): [v.min, v.max, v.outlineLevel, v.collapsed, v.hidden] for k,v in s.column_dimensions.items()},
      'row1': s.row_dimensions[1].height, 'row2': [s.row_dimensions[2].height, s.row_dimensions[2].customHeight],
      'colB': round(s.column_dimensions['B'].width or 0, 2), 'colD': round(s.column_dimensions['D'].width or 0, 2),
      'A3': [s['A3'].value, s['A3'].font.bold, s['A3'].alignment.indent], 'B3': [s['B3'].value, s['B3'].font.bold, s['B3'].alignment.indent],
      'A4': [s['A4'].value, s['A4'].font.bold], 'A7': [s['A7'].value, s['A7'].font.bold],
      'createValues': [[s.cell(r,c).value for c in range(1,3)] for r in range(1,10)],
      'convertRefs': [s['D5'].value, s['D6'].value, s['D7'].value],
      'convertCells': [[s.cell(r,c).coordinate, s.cell(r,c).value, s.cell(r,c).style_id] for r in range(1,5) for c in range(1,3)],
      'convertExplicit': [s['B2'].value, s['B2'].font.bold, s['B2'].font.color.rgb if s['B2'].font.color and s['B2'].font.color.type == 'rgb' else None, s['B2'].fill.fgColor.rgb, s['B2'].number_format],
      'tableXml': {n: __import__('zipfile').ZipFile(BytesIO(base64.b64decode(payload['bytes']))).read(n).decode() for n in __import__('zipfile').ZipFile(BytesIO(base64.b64decode(payload['bytes']))).namelist() if __import__('re').match(r'xl/tables/table[0-9]+\.xml$', n)},
      'tableHeaders': {t.displayName: t.headerRowCount for t in s.tables.values()},
      'tableTotals': {t.displayName: t.totalsRowCount for t in s.tables.values()},
      'tableStyleOptions': {t.displayName: {'firstColumn': bool(t.tableStyleInfo.showFirstColumn), 'lastColumn': bool(t.tableStyleInfo.showLastColumn), 'bandedRows': bool(t.tableStyleInfo.showRowStripes), 'bandedColumns': bool(t.tableStyleInfo.showColumnStripes)} for t in s.tables.values()},
      'cellXml': __import__('re').findall(r'(?s)<c(?: [^>]*)?>.*?</c>|<c(?: [^>]*)?/>', __import__('zipfile').ZipFile(BytesIO(base64.b64decode(payload['bytes']))).read('xl/worksheets/sheet1.xml').decode()),
      'E1': [s['E1'].value, s['E1'].font.bold], 'F1': s['F1'].value, 'B1': s['B1'].value, 'D5': s['D5'].value,
      'dataTable': [s['D1'].value, s['B1'].value, s['B2'].value, s['B3'].value, s['B2'].data_type, s['B3'].data_type],
      'consolidateValues': [[s.cell(r,c).value for c in (5,6)] for r in (1,2,3)],
      'consolidateSourceXml': {name: __import__('zipfile').ZipFile(BytesIO(base64.b64decode(payload['bytes']))).read(name).decode() for name in ('xl/worksheets/sheet2.xml','xl/worksheets/sheet3.xml') if name in __import__('zipfile').ZipFile(BytesIO(base64.b64decode(payload['bytes']))).namelist()},
      'dedupeValues': [[s.cell(r, c).value for c in range(1, 3)] for r in range(1, 6)],
      'dedupeA3': [s['A3'].font.bold, s['A3'].comment.text if s['A3'].comment else None],
      'splitValues': [[s.cell(r, c).value for c in range(1, 5)] for r in range(1, 3)],
      'splitB1': [s['B1'].font.bold, s['B1'].comment.text if s['B1'].comment else None], 'splitD1type': s['D1'].data_type,
      'C3fmt': [s['C3'].value, s['C3'].number_format], 'showFormulas': bool(s.sheet_view.showFormulas), 'sheetProtected': bool(s.protection.sheet), 'structureLocked': bool(book.security and book.security.lockStructure),
      'validations': [{'range': str(d.sqref), 'type': d.type, 'formula1': d.formula1, 'prompt': d.prompt, 'allowBlank': d.allowBlank} for d in s.data_validations.dataValidation],
      'definedNames': {name: entry.attr_text for name, entry in book.defined_names.items()},
      'scopedNames': {sheet.title: {name: entry.attr_text for name, entry in sheet.defined_names.items()} for sheet in book},
      'printArea': str(s.print_area),
      'tableFilterButtons': {t.displayName: t.autoFilter is not None for t in s.tables.values()},
      'tables': [{'name': t.displayName, 'ref': t.ref, 'columns': [c.name for c in t.tableColumns], 'style': t.tableStyleInfo.name if t.tableStyleInfo else None} for t in s.tables.values()],
      'sheets': book.sheetnames, 'newSheetA1': [book.worksheets[-1]['A1'].value, book.worksheets[-1]['A1'].font.bold] if len(book.worksheets) > 1 else None}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
const sourceBytes = Buffer.from(python({ mode: 'create', case: process.env.WORKBOOK_RIBBON_CASE, totals: process.env.TABLE_RESIZE_TOTALS === '1' }), 'base64')
const sourceSha = createHash('sha256').update(sourceBytes).digest('hex')
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
let savedBytes, savePayload
const server = spawn('./node_modules/.bin/vite', [...(process.env.WORKBOOK_SMOKE_PREVIEW === '1' ? ['preview', ...(process.env.WORKBOOK_SMOKE_STATIC_ROOT ? ['--outDir', process.env.WORKBOOK_SMOKE_STATIC_ROOT] : [])] : []), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser
let diagnosticPage
try {
  for (let attempt = 0; attempt < 120; attempt++) { try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, args: ['--disable-features=LocalNetworkAccessChecks'], ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['clipboard-read', 'clipboard-write'] })
  const page = await context.newPage()
  diagnosticPage = page
  const pageErrors = []
  const whatIfChunks = []
  const consolidateChunks = []
  const outlineChunks = []
  page.on('response', response => {
    if (/\/lazy-workbook-what-if-[^/]+\.js$/.test(new URL(response.url()).pathname)) whatIfChunks.push({ url: response.url(), status: response.status() })
    if (/\/lazy-workbook-consolidate-[^/]+\.js$/.test(new URL(response.url()).pathname)) consolidateChunks.push({ url: response.url(), status: response.status() })
    if (/\/lazy-workbook-outline-[^/]+\.js$/.test(new URL(response.url()).pathname)) outlineChunks.push({ url: response.url(), status: response.status() })
  })
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()) })
  const runNativeAI = process.env.WORKBOOK_RIBBON_CASE === 'native-ai' ? await (await import('./workbook-native-ai-fixture.mjs')).installWorkbookNativeAIFixture({ page, sourceBytes, sourceSha, python }) : undefined
  const ctx = { documentId: 'fixture-gui', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' },
    sourceFile: { path: 'gui.xlsx', size: sourceBytes.length, sha256: sourceSha, mediaType: media }, origin: 'upload' }
  await page.route('**/reports/v1/native/fixture-gui/1/api/context', route => route.fulfill({ json: { context: ctx, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true, ...(runNativeAI ? { aiEnabled: true, ...(process.env.WORKBOOK_SMOKE_DOCK === '1' ? { officeReadAIEnabled:true } : {}) } : {}) } }))
  await page.route('**/reports/v1/native/fixture-gui/1/api/file', route => route.fulfill({ body: sourceBytes, contentType: media }))
  await page.route('**/reports/v1/native/fixture-gui/1/api/save', async route => {
    savePayload = route.request().postDataJSON()
    savedBytes = Buffer.from(python({ mode: 'patch', bytes: sourceBytes.toString('base64'), operations: savePayload.operations }), 'base64')
    await route.fulfill({ json: { documentId: 'fixture-gui', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { xlsx: { downloadUrl: '/fixture-gui-download.xlsx', size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } },
      editor: { openUrl: '/reports/v1/native/fixture-gui/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.route('**/fixture-gui-download.xlsx', route => route.fulfill({ body: savedBytes, contentType: media }))
  await page.route(/\/reports\/v1\/native\/fixture-gui\/1$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
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

  if (runNativeAI) {
    await runNativeAI({ command, browser, getSavedBytes: () => savedBytes, pageErrors })
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'outline-actions') {
    const source = JSON.parse(python({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    const go = async ref => {
      await page.locator('[data-ribbon-tab="Home"]').click(); await command('goto-open')
      await page.locator('[data-goto-reference]').fill(ref)
      await page.locator('.workbook-ribbon-goto-dialog .workbook-ribbon-format-apply').click()
      await page.locator('[data-ribbon-tab="Data"]').click()
    }
    await go('A2:B3'); await page.locator('#workbook-grid').evaluate(element => { element.tabIndex = -1; element.focus() }); await page.keyboard.press('Alt+Shift+ArrowRight')
    await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applySheetOutline' && op.rows?.some(row => row.index === 1 && row.level === 1))))
    await command('outline-summary-below'); await command('outline-summary-right')
    assert.equal(await page.locator('[data-ribbon-command="outline-summary-below"]').getAttribute('aria-pressed'), 'false')
    assert.equal(await page.locator('[data-ribbon-command="outline-summary-right"]').getAttribute('aria-pressed'), 'false')
    await command('outline-hide-detail:rows'); await command('outline-show-detail:rows')
    await go('A1'); await command('outline-clear')
    await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applySheetOutline' && op.summaryBelow === false && !op.rows?.some(row => row.level > 0))))
    await go('A2:B3'); await page.locator('#workbook-grid').evaluate(element => { element.tabIndex = -1; element.focus() }); await page.keyboard.press('Alt+Shift+ArrowRight')
    await command('outline-hide-detail:rows')
    await go('C1:D2'); await command('outline-group:cols'); await command('outline-hide-detail:cols')
    const waitFinal = () => page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applySheetOutline' && op.summaryBelow === false && op.summaryRight === false && op.rows?.some(row => row.index === 1 && row.hidden) && op.columns?.some(col => col.index === 2 && col.hidden))))
    await waitFinal(); await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelector('.save-state')?.getAttribute('aria-busy') === 'false'); await waitFinal()
    await page.locator('[data-ribbon-tab="Data"]').click()
    assert.equal(await page.locator('[data-ribbon-command="outline-summary-below"]').getAttribute('aria-pressed'), 'false')
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.outlineSummary, [false, false])
    assert.deepEqual(reopened.outlineRows['2'], [1, false, true]); assert.deepEqual(reopened.outlineRows['1'], [0, true, false])
    assert.deepEqual(reopened.outlineCols.C, [3,3,1,false,true]); assert.deepEqual(reopened.outlineCols.B, [2,2,0,true,false])
    assert.deepEqual(reopened.cellXml, source.cellXml); assert.equal(reopened.row2[0], 40); assert.equal(reopened.colB, 30)
    const revisionBytes = savedBytes, sha = createHash('sha256').update(revisionBytes).digest('hex')
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: revisionBytes.length, sha256: sha } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: revisionBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelector('.save-state')?.getAttribute('aria-busy') === 'false')
    await page.locator('[data-ribbon-tab="Data"]').click()
    assert.equal(await page.locator('[data-ribbon-command="outline-summary-right"]').getAttribute('aria-pressed'), 'false')
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'outline-actions', preview: process.env.WORKBOOK_SMOKE_PREVIEW === '1', browserVersion: browser.version(), keyboard: true, clear: true, draftRestored: true, revision2Reopened: true, summary: reopened.outlineSummary, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'outline') {
    const source = JSON.parse(python({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    const go = async ref => {
      await page.locator('[data-ribbon-tab="Home"]').click(); await command('goto-open')
      await page.locator('[data-goto-reference]').fill(ref)
      await page.locator('.workbook-ribbon-goto-dialog .workbook-ribbon-format-apply').click()
      await page.locator('[data-ribbon-tab="Data"]').click()
    }
    const waitOutline = () => page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applySheetOutline')))
    await go('A2:B3'); await command('outline-group:rows'); await waitOutline()
    await command('outline-hide-detail')
    await page.waitForFunction(() => document.querySelector('.workbook-feedback')?.textContent?.includes('分组设置已更新'))
    await page.locator('[data-ribbon-tab="File"]').click(); await command('undo'); await command('redo')
    await go('C:D'); await command('outline-group:cols'); await command('outline-hide-detail')
    await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applySheetOutline' && op.columns?.some(entry => entry.index === 4 && entry.collapsed) && op.columns?.some(entry => entry.index === 2 && entry.hidden))))
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelector('.save-state')?.getAttribute('aria-busy') === 'false')
    await waitOutline(); await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.outlineRows['2'], [1, false, true])
    assert.deepEqual(reopened.outlineRows['3'], [1, false, true])
    assert.deepEqual(reopened.outlineRows['4'], [0, true, false])
    assert.deepEqual(reopened.outlineCols.C, [3, 3, 1, false, true])
    assert.deepEqual(reopened.outlineCols.D, [4, 4, 1, false, true])
    assert.deepEqual(reopened.outlineCols.E, [5, 5, 0, true, false])
    assert.deepEqual(reopened.cellXml, source.cellXml)
    assert.equal(reopened.row2[0], 40); assert.equal(reopened.colB, 30)
    const revisionBytes = savedBytes, sha = createHash('sha256').update(revisionBytes).digest('hex')
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: revisionBytes.length, sha256: sha } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: revisionBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelector('.save-state')?.getAttribute('aria-busy') === 'false')
    await go('A4'); await command('outline-show-detail')
    await page.waitForFunction(() => document.querySelector('.workbook-feedback')?.textContent?.includes('分组设置已更新'))
    assert.deepEqual(pageErrors, [])
    if (process.env.WORKBOOK_SMOKE_PREVIEW === '1') { assert.ok(outlineChunks.length > 0); assert.ok(outlineChunks.every(chunk => chunk.status === 200)) }
    console.log(JSON.stringify({ ok: true, case: 'outline', outlineChunks, preview: process.env.WORKBOOK_SMOKE_PREVIEW === '1', browserVersion: browser.version(), nativeHiddenUndoRedo: true, draftRestored: true, revision2Reopened: true, rows: reopened.outlineRows, columns: reopened.outlineCols, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'consolidate') {
    const source = JSON.parse(python({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    await command('goto-open'); await page.locator('[data-goto-reference]').fill('E1')
    await page.locator('.workbook-ribbon-goto-dialog .workbook-ribbon-format-apply').click()
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('consolidate-open')
    const dialog = page.getByRole('dialog', { name: '合并计算', exact: true })
    assert.match(await dialog.innerText(), /Summary!E1/)
    const reference = dialog.getByRole('textbox', { name: '引用位置', exact: true })
    await reference.fill("'West Side'!A1:B3"); await dialog.getByRole('button', { name: '添加', exact: true }).click()
    await reference.fill("'O''Brien'!A1:B2"); await dialog.getByRole('checkbox', { name: '使用左列标签', exact: true }).check()
    await dialog.getByRole('button', { name: '确定', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
    const waitOutput = () => page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyCellEdits' && op.edits?.some(edit => edit.row === 2 && edit.column === 4 && edit.cell?.value === 'Cara'))))
    await waitOutput(); await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
    await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.length === 0))
    await command('redo'); await waitOutput()
    await page.reload(); await page.locator('.workbook-ribbon').waitFor(); await waitOutput()
    await page.waitForFunction(() => document.querySelector('.save-state')?.getAttribute('aria-busy') === 'false')
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.consolidateValues, [
      ['Ada', "=SUMIF('West Side'!$A$1:$A$3,$E1,'West Side'!B1:B3)"],
      ['Bob', "=SUMIF('West Side'!$A$1:$A$3,$E2,'West Side'!B1:B3)+SUMIF('O''Brien'!$A$1:$A$2,$E2,'O''Brien'!B1:B2)"],
      ['Cara', "=SUMIF('O''Brien'!$A$1:$A$2,$E3,'O''Brien'!B1:B2)"],
    ])
    assert.deepEqual(reopened.consolidateSourceXml, source.consolidateSourceXml)
    assert.equal(reopened.D5, source.D5)
    assert.deepEqual(savePayload.operations.map(op => op.kind), ['applyCellEdits'])
    const revisionBytes = savedBytes, sha = createHash('sha256').update(revisionBytes).digest('hex')
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: revisionBytes.length, sha256: sha } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: revisionBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`); await page.locator('.workbook-ribbon').waitFor()
    assert.deepEqual(pageErrors, [])
    if (process.env.WORKBOOK_SMOKE_PREVIEW === '1') { assert.ok(consolidateChunks.length > 0); assert.ok(consolidateChunks.every(chunk => chunk.status === 200)) }
    console.log(JSON.stringify({ ok: true, case: 'consolidate', preview: process.env.WORKBOOK_SMOKE_PREVIEW === '1', consolidateChunks, browserVersion: browser.version(), undoRedo: true, draftRestored: true, revision2Reopened: true, sourceSheetsPreserved: true, formulas: reopened.consolidateValues, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'goal-seek') {
    const waitInput = value => page.waitForFunction(expected => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyCellEdits' && op.edits?.some(edit => edit.row === 0 && edit.column === 3 && edit.cell?.value === expected))), value)
    const solve = async (setCell, target) => {
      await page.locator('[data-ribbon-tab="Data"]').click(); await command('goal-seek-open')
      const dialog = page.getByRole('dialog', { name: '单变量求解', exact: true })
      await dialog.getByRole('textbox', { name: '目标公式单元格', exact: true }).fill(setCell)
      await dialog.getByRole('textbox', { name: '目标值', exact: true }).fill(String(target))
      await dialog.getByRole('textbox', { name: '可变单元格', exact: true }).fill('D1')
      await dialog.getByRole('button', { name: '求解', exact: true }).click()
      return dialog
    }
    await page.locator('[data-ribbon-tab="Formulas"]').click()
    await page.locator('[data-ribbon-control="calc-mode"]').selectOption('manual')
    let dialog = await solve('B1', 30)
    await dialog.getByRole('status').filter({ hasText: '找到解：15' }).waitFor({ timeout: 30000 })
    await dialog.getByRole('button', { name: '关闭', exact: true }).click(); await waitInput(15)
    await page.locator('[data-ribbon-tab="File"]').click(); await command('undo'); await waitInput(11)
    await command('redo'); await waitInput(15)
    dialog = await solve('F1', 100)
    await dialog.getByRole('status').filter({ hasText: '未找到解' }).waitFor({ timeout: 30000 })
    await dialog.getByRole('button', { name: '关闭', exact: true }).click(); await waitInput(15)
    await page.reload(); await page.locator('.workbook-ribbon').waitFor(); await waitInput(15)
    await page.waitForFunction(() => document.querySelector('.save-state')?.getAttribute('aria-busy') === 'false')
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.dataTable.slice(0, 2), [15, '=D1*2'])
    assert.equal(reopened.F1, '=D1*0+5')
    assert.deepEqual(savePayload.operations.map(op => op.kind), ['applyCellEdits'])
    assert.deepEqual(savePayload.operations[0].edits.map(edit => [edit.row, edit.column, edit.cell.value]), [[0, 3, 15]])
    const revisionBytes = savedBytes, sha = createHash('sha256').update(revisionBytes).digest('hex')
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: revisionBytes.length, sha256: sha } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: revisionBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`); await page.locator('.workbook-ribbon').waitFor()
    assert.deepEqual(pageErrors, [])
    if (process.env.WORKBOOK_SMOKE_PREVIEW === '1') { assert.ok(whatIfChunks.length > 0); assert.ok(whatIfChunks.every(chunk => chunk.status === 200)) }
    console.log(JSON.stringify({ ok: true, case: 'goal-seek', browserVersion: browser.version(), preview: process.env.WORKBOOK_SMOKE_PREVIEW === '1', whatIfChunks, manual: true, undoRedo: true, failureRestored: true, draftRestored: true, revision2Reopened: true, operations: savePayload.operations, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'data-table') {
    const waitResults = () => page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyCellEdits' && op.edits?.some(edit => edit.row === 2 && edit.column === 1 && edit.cell?.value === 10))))
    await page.locator('[data-ribbon-tab="Formulas"]').click()
    await page.locator('[data-ribbon-control="calc-mode"]').selectOption('manual')
    await page.locator('[data-ribbon-tab="Data"]').click()
    await command('data-table-open')
    const dialog = page.getByRole('dialog', { name: '模拟运算表', exact: true })
    await dialog.getByRole('textbox', { name: '表格区域', exact: true }).fill('A1:B3')
    await dialog.getByRole('textbox', { name: '列输入单元格', exact: true }).fill('D1')
    await dialog.getByRole('button', { name: '确定', exact: true }).click()
    await dialog.getByRole('status').filter({ hasText: '已生成 2 个结果' }).waitFor({ timeout: 30000 })
    await waitResults()
    await dialog.getByRole('button', { name: '关闭', exact: true }).click()
    await page.locator('[data-ribbon-tab="File"]').click()
    await command('undo')
    await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.length === 0))
    await command('redo'); await waitResults()
    await page.reload(); await page.locator('.workbook-ribbon').waitFor(); await waitResults()
    await page.waitForFunction(() => document.querySelector('.save-state')?.getAttribute('aria-busy') === 'false')
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.dataTable, [10, '=D1*2', 6, 10, 'n', 'n'])
    assert.deepEqual(savePayload.operations.map(op => op.kind), ['applyCellEdits'])
    assert.deepEqual(savePayload.operations[0].edits.map(edit => [edit.row, edit.column]), [[1, 1], [2, 1]])
    const revisionBytes = savedBytes, sha = createHash('sha256').update(revisionBytes).digest('hex')
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: revisionBytes.length, sha256: sha } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: revisionBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`); await page.locator('.workbook-ribbon').waitFor()
    assert.deepEqual(pageErrors, [])
    if (process.env.WORKBOOK_SMOKE_PREVIEW === '1') { assert.ok(whatIfChunks.length > 0); assert.ok(whatIfChunks.every(chunk => chunk.status === 200)) }
    console.log(JSON.stringify({ ok: true, case: 'data-table', browserVersion: browser.version(), preview: process.env.WORKBOOK_SMOKE_PREVIEW === '1', whatIfChunks, manual: true, undoRedo: true, draftRestored: true, revision2Reopened: true, dataTable: reopened.dataTable, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'name-scope') {
    const source = JSON.parse(python({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    const waitName = value => page.waitForFunction(expected => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyDefinedNames' && op.plan.sets?.some(row => row.name === 'Rate' && row.scopeSheetName === 'Summary' && row.refersTo === expected))), value)
    const openNames = async () => { await page.locator('[data-ribbon-tab="Formulas"]').click(); await command('name-manager-open') }
    await openNames()
    const scope = page.getByRole('combobox', { name: '名称作用域', exact: true })
    await scope.selectOption({ label: 'Summary' })
    await page.locator('.workbook-defined-name-name').fill('Rate')
    await page.locator('.workbook-defined-name-ref').fill('30')
    await page.getByRole('button', { name: '新建', exact: true }).click()
    assert.equal(await page.locator('.workbook-defined-name-error').innerText(), '')
    await waitName('30')
    await page.getByRole('button', { name: '关闭名称管理器', exact: true }).click()
    await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
    await page.waitForFunction(() => Object.keys(localStorage).every(key => !key.startsWith('native-editor-draft:') || !JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyDefinedNames')))
    await command('redo'); await waitName('30')
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent?.includes('已恢复本地草稿'))
    await openNames()
    const list = page.locator('.workbook-defined-name-list')
    const localValue = await list.locator('option').evaluateAll(options => options.find(option => option.textContent.includes('Summary') && option.textContent.includes('Rate'))?.value)
    assert.ok(localValue)
    await list.selectOption(localValue)
    assert.equal(await scope.isDisabled(), true)
    await page.locator('.workbook-defined-name-ref').fill('40')
    await page.getByRole('button', { name: '更新', exact: true }).click()
    assert.equal(await page.locator('.workbook-defined-name-error').innerText(), '')
    await waitName('40')
    await page.getByRole('button', { name: '关闭名称管理器', exact: true }).click()
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.definedNames, { Rate: '10' })
    assert.deepEqual(reopened.scopedNames, { Summary: { Rate: '40' }, 'Other Sheet': { Rate: '20' } })
    assert.equal(reopened.printArea, source.printArea)
    assert.deepEqual(reopened.cellXml, source.cellXml)
    const savedSha = createHash('sha256').update(savedBytes).digest('hex')
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: savedBytes.length, sha256: savedSha } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: savedBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`); await page.locator('.workbook-ribbon').waitFor()
    await openNames()
    assert.equal(await list.locator('option').count(), 3)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'name-scope', browserVersion: browser.version(), undoRedo: true, draftReloaded: true, savedReopened: true, scopedNames: reopened.scopedNames, printAreaPreserved: true, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'table-filter-button') {
    const source = JSON.parse(python({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    const selectTable = async () => {
      await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false')
      await page.waitForFunction(() => {
        const rect = document.querySelector('.workbook-grid')?.getBoundingClientRect()
        return rect && document.elementFromPoint(rect.x + 90, rect.y + 109)?.getAttribute('data-u-comp') === 'render-canvas'
      })
      await clickCell(...A3); await page.locator('[data-ribbon-tab="Table Design"]').click()
    }
    const filter = () => page.getByRole('checkbox', { name: '筛选按钮', exact: true })
    const waitFlag = value => page.waitForFunction(expected => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits' && op.edits.some(edit => edit.tableName === 'Staff' && edit.filterButton === expected))), value)
    await selectTable(); assert.equal(await filter().isChecked(), true)
    await filter().uncheck(); await waitFlag(false)
    await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
    await selectTable(); assert.equal(await filter().isChecked(), true)
    await page.locator('[data-ribbon-tab="File"]').click(); await command('redo'); await waitFlag(false)
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await selectTable(); assert.equal(await filter().isChecked(), false)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 }).catch(async error => { console.error(JSON.stringify({ phase: 'filter-save', body: await page.locator('body').innerText(), savePayload, pageErrors })); throw error })
    const disabledBytes = savedBytes
    const disabled = JSON.parse(python({ mode: 'inspect', bytes: disabledBytes.toString('base64') }))
    assert.deepEqual(disabled.tableFilterButtons, { Staff: false, Other: true })
    assert.deepEqual(disabled.cellXml, source.cellXml)
    assert.deepEqual(disabled.tables, source.tables)
    const otherXml = Object.values(source.tableXml).find(xml => xml.includes('displayName="Other"'))
    assert.ok(Object.values(disabled.tableXml).includes(otherXml))
    assert.equal(savePayload.operations.some(op => op.kind === 'applyCellEdits'), false)
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: disabledBytes.length, sha256: createHash('sha256').update(disabledBytes).digest('hex') } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: disabledBytes, contentType: media }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/save', async route => {
      savePayload = route.request().postDataJSON()
      savedBytes = Buffer.from(python({ mode: 'patch', bytes: disabledBytes.toString('base64'), operations: savePayload.operations }), 'base64')
      await route.fulfill({ json: { documentId: 'fixture-gui', revision: 3, parentRevision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/fixture-gui-download.xlsx', size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } }, editor: { openUrl: '/reports/v1/native/fixture-gui/3' }, validation: { ok: true, issues: [] } } })
    })
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`); await page.locator('.workbook-ribbon').waitFor()
    await selectTable(); assert.equal(await filter().isChecked(), false)
    await filter().check(); await waitFlag(true)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 3', null, { timeout: 60000 })
    const enabled = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(enabled.tableFilterButtons, { Staff: true, Other: true })
    assert.deepEqual(enabled.cellXml, source.cellXml)
    assert.ok(Object.values(enabled.tableXml).includes(otherXml))
    const staffXml = Object.values(enabled.tableXml).find(xml => xml.includes('displayName="Staff"'))
    assert.match(staffXml, /<autoFilter\b[^>]*ref="A1:B3"/)
    assert.equal(staffXml.includes('<filterColumn'), false)
    const enabledBytes = savedBytes
    await page.route('**/reports/v1/native/fixture-gui/3/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 3, parentRevision: 2, sourceFile: { ...ctx.sourceFile, size: enabledBytes.length, sha256: createHash('sha256').update(enabledBytes).digest('hex') } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/3/api/file', route => route.fulfill({ body: enabledBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/3$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/3'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/3`); await page.locator('.workbook-ribbon').waitFor()
    await selectTable(); assert.equal(await filter().isChecked(), true)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'table-filter-button', browserVersion: browser.version(), revisions: [2, 3], undoRedo: true, draftReloaded: true, sourceCellsPreserved: true, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'table-header-row') {
    const source = JSON.parse(python({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    const selectTable = async () => {
      await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false')
      // canvas先创建，range-selector随后才交出命中层；必须等点击点实际由渲染canvas接收。
      await page.waitForFunction(() => {
        const grid = document.querySelector('.workbook-grid'), rect = grid?.getBoundingClientRect()
        return rect && document.elementFromPoint(rect.x + 90, rect.y + 109)?.getAttribute('data-u-comp') === 'render-canvas'
      })
      await clickCell(...A3)
      await page.locator('[data-ribbon-tab="Table Design"]').click()
    }
    const header = () => page.getByRole('checkbox', { name: '标题行', exact: true })
    const waitHeader = value => page.waitForFunction(expected => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits' && op.edits.some(edit => edit.tableName === 'Staff' && edit.headerRow === expected))), value)
    await selectTable(); assert.equal(await header().isChecked(), true)
    await header().uncheck({ timeout: 5000 }).catch(async error => { console.error(JSON.stringify({ phase: 'table-header-row-first-toggle', feedback: await feedback(), body: await page.locator('body').innerText(), pageErrors })); throw error }); await waitHeader(false)
    assert.equal(await page.locator('[data-ribbon-control="table-range"]').innerText(), 'A2:B4')
    await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
    await selectTable(); assert.equal(await header().isChecked(), true)
    assert.equal(await page.locator('[data-ribbon-control="table-range"]').innerText(), 'A1:B4')
    await page.locator('[data-ribbon-tab="File"]').click(); await command('redo'); await waitHeader(false)
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await selectTable(); assert.equal(await header().isChecked(), false)
    assert.equal(await page.getByRole('checkbox', { name: '汇总行', exact: true }).isChecked(), true)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 }).catch(async error => {
      console.error(JSON.stringify({ phase: 'table-header-row-save', body: await page.locator('body').innerText(), savePayload, pageErrors })); throw error
    })
    const hiddenBytes = savedBytes
    const hidden = JSON.parse(python({ mode: 'inspect', bytes: hiddenBytes.toString('base64') }))
    assert.equal(hidden.tableHeaders.Staff, 0)
    assert.equal(hidden.tables.find(table => table.name === 'Staff').ref, 'A2:B4')
    assert.deepEqual(hidden.tables.find(table => table.name === 'Staff').columns, ['Name', 'Qty'])
    assert.equal(hidden.tableTotals.Staff, 1)
    assert.equal(hidden.A1[0], null); assert.equal(hidden.B1, null)
    const originalData = source.cellXml.filter(xml => /r="[AB][2-4]"/.test(xml))
    assert.equal(originalData.length, 6)
    assert.deepEqual(hidden.cellXml.filter(xml => /r="[AB][2-4]"/.test(xml)), originalData)
    const otherXml = Object.values(source.tableXml).find(xml => xml.includes('displayName="Other"'))
    assert.ok(Object.values(hidden.tableXml).includes(otherXml))
    assert.ok(!Object.values(hidden.tableXml).find(xml => xml.includes('displayName="Staff"')).includes('<autoFilter'))
    const nextContext = { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: hiddenBytes.length, sha256: createHash('sha256').update(hiddenBytes).digest('hex') } }
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: nextContext, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: hiddenBytes, contentType: media }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/save', async route => {
      savePayload = route.request().postDataJSON()
      savedBytes = Buffer.from(python({ mode: 'patch', bytes: hiddenBytes.toString('base64'), operations: savePayload.operations }), 'base64')
      await route.fulfill({ json: { documentId: 'fixture-gui', revision: 3, parentRevision: 2, revisionRegistered: true,
        artifacts: { xlsx: { downloadUrl: '/fixture-gui-download.xlsx', size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } },
        editor: { openUrl: '/reports/v1/native/fixture-gui/3' }, validation: { ok: true, issues: [] } } })
    })
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`)
    await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await selectTable(); assert.equal(await header().isChecked(), false)
    await header().check(); await waitHeader(true)
    assert.equal(await page.locator('[data-ribbon-control="table-range"]').innerText(), 'A1:B4')
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 3', null, { timeout: 60000 }).catch(async error => {
      console.error(JSON.stringify({ phase: 'table-header-row-revision3-save', body: await page.locator('body').innerText(), savePayload, pageErrors })); throw error
    })
    const shown = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.ok(shown.tableHeaders.Staff === null || shown.tableHeaders.Staff === 1)
    assert.deepEqual(shown.tables, source.tables)
    assert.equal(shown.tableTotals.Staff, 1)
    assert.deepEqual(shown.cellXml.filter(xml => /r="[AB][2-4]"/.test(xml)), originalData)
    assert.equal(shown.A1[0], 'Name'); assert.equal(shown.B1, 'Qty')
    assert.deepEqual(shown.convertExplicit, source.convertExplicit)
    assert.ok(Object.values(shown.tableXml).includes(otherXml))
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'table-header-row', browserVersion: browser.version(), revisions: [2, 3], undoRedo: true, draftReloaded: true, hidden: { range: hidden.tables.find(table => table.name === 'Staff').ref, headers: hidden.tableHeaders.Staff }, sourceDataPreserved: true, otherTablePreserved: true, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'table-create') {

    const source = JSON.parse(python({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    const waitAdditions = count => page.waitForFunction(expected => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.filter(op => op.kind === 'applyTableAdditions').flatMap(op => op.additions).length === expected), count)
    const createTable = async (range, hasHeaders) => {
      await page.locator('[data-ribbon-tab="Insert"]').click()
      await page.getByRole('button', { name: '创建表格', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '创建表格', exact: true })
      await dialog.getByRole('textbox', { name: '表格范围', exact: true }).fill(range)
      await dialog.getByRole('checkbox', { name: '表包含标题', exact: true }).setChecked(hasHeaders)
      await dialog.getByRole('button', { name: '确定', exact: true }).click()
      await dialog.waitFor({ state: 'hidden' })
    }
    const selectFirst = async () => { await clickCell(90, 64); await page.locator('[data-ribbon-tab="Table Design"]').click() }
    await createTable('A1:B3', true); await waitAdditions(1)
    await selectFirst()
    assert.equal(await page.locator('[data-ribbon-control="table-name"]').inputValue(), 'Table1')
    await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
    await page.waitForFunction(() => Object.keys(localStorage).every(key => !key.startsWith('native-editor-draft:') || !JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableAdditions')))
    await command('redo'); await waitAdditions(1)
    await createTable('A7:B8', false); await waitAdditions(2)
    await selectFirst()
    await page.locator('[data-ribbon-control="table-style"]').selectOption('TableStyleDark3')
    await page.getByRole('checkbox', { name: '首列', exact: true }).check()
    await page.getByRole('checkbox', { name: '列条纹', exact: true }).check()
    await page.getByRole('checkbox', { name: '汇总行', exact: true }).check()
    await waitAdditions(2)
    await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits' && op.edits.some(edit => edit.tableName === 'Table1' && edit.totalsRow === true && edit.firstColumn === true && edit.bandedColumns === true))))
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await selectFirst()
    assert.equal(await page.locator('[data-ribbon-control="table-style"]').inputValue(), 'TableStyleDark3')
    for (const name of ['首列', '列条纹', '汇总行']) assert.equal(await page.getByRole('checkbox', { name, exact: true }).isChecked(), true)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 }).catch(async error => {
      console.error(JSON.stringify({ phase: 'table-create-save', body: await page.locator('body').innerText(), savePayload, pageErrors })); throw error
    })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.tables.find(table => table.name === 'Staff'), source.tables[0])
    assert.deepEqual(reopened.tables.find(table => table.name === 'Table1'), { name: 'Table1', ref: 'A1:B4', columns: ['Name', 'Qty'], style: 'TableStyleDark3' })
    assert.deepEqual(reopened.tables.find(table => table.name === 'Table2'), { name: 'Table2', ref: 'A6:B8', columns: ['Column1', 'Column2'], style: 'TableStyleMedium2' })
    assert.equal(reopened.tableTotals.Table1, 1)
    assert.deepEqual(reopened.tableStyleOptions.Table1, { firstColumn: true, lastColumn: false, bandedRows: true, bandedColumns: true })
    assert.deepEqual(reopened.createValues.slice(0, 3), source.createValues.slice(0, 3))
    assert.deepEqual(reopened.createValues.slice(6, 8), [['Jane', 11], ['Lin', 13]])
    assert.deepEqual(reopened.createValues[5], ['Column1', 'Column2'])
    assert.deepEqual(reopened.convertExplicit, source.convertExplicit)
    assert.ok(Object.values(reopened.tableXml).includes(Object.values(source.tableXml)[0]), 'source table XML must remain unchanged')
    const sourceDataCells = source.cellXml.filter(xml => /r="(?:[AB][1-3]|[AB][78])"/.test(xml))
    assert.equal(sourceDataCells.length, 10)
    assert.deepEqual(reopened.cellXml.filter(xml => /r="(?:[AB][1-3]|[AB][78])"/.test(xml)), sourceDataCells)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'table-create', browserVersion: browser.version(), undoRedo: true, draftReloaded: true, tables: reopened.tables, sourceCellsPreserved: true, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'table-convert') {

    const source = JSON.parse(python({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    assert.equal(source.tables.length, 2)
    assert.equal(source.tableTotals.Staff, 1)
    assert.ok(Object.values(source.tableXml).some(xml => xml.includes('filterColumn')))
    const selectTable = async (x = 90) => { await clickCell(x, 64); await page.locator('[data-ribbon-tab="Table Design"]').click() }
    const tableName = () => page.locator('[data-ribbon-control="table-name"]')
    const storedOperations = () => page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).flatMap(key => JSON.parse(localStorage.getItem(key)).operations ?? []))
    const waitRemoved = () => page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits' && op.edits.some(edit => edit.tableName === 'Staff' && edit.remove === true))))
    await selectTable()
    const originalName = await tableName().inputValue()
    assert.equal(originalName, 'Staff')
    const originalFlags = await page.getByRole('checkbox', { name: '行条纹', exact: true }).isChecked()
    let prompt
    page.once('dialog', async dialog => { prompt = dialog.message(); await dialog.accept() })
    await page.getByRole('button', { name: '转换为区域', exact: true }).click()
    await waitRemoved()
    assert.ok(prompt, 'conversion must ask for confirmation')
    for (const word of ['表格', '条纹', '筛选', '结构化引用', '失效']) assert.ok(prompt.includes(word), `conversion confirmation must explain ${word}`)
    const convertedOperations = await storedOperations()
    const removal = convertedOperations.filter(op => op.kind === 'applyTableEdits').flatMap(op => op.edits)
    assert.deepEqual(removal, [{ worksheetSheetName: 'Summary', tableName: 'Staff', remove: true }])
    await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
    await selectTable()
    assert.equal(await tableName().inputValue(), originalName)
    assert.equal(await page.getByRole('checkbox', { name: '汇总行', exact: true }).isChecked(), true)
    assert.equal(await page.getByRole('checkbox', { name: '行条纹', exact: true }).isChecked(), originalFlags)
    await page.waitForFunction(() => Object.keys(localStorage).every(key => !key.startsWith('native-editor-draft:') || !JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits')))
    await page.locator('[data-ribbon-tab="File"]').click(); await command('redo'); await waitRemoved()
    assert.deepEqual(await storedOperations(), convertedOperations)
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await clickCell(90, 64)
    assert.equal(await page.locator('[data-ribbon-tab="Table Design"]').count(), 0, 'restored draft must no longer expose the converted table')
    await waitRemoved()
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 }).catch(async error => {
      console.error(JSON.stringify({ phase: 'table-convert-save', body: await page.locator('body').innerText(), savePayload, pageErrors })); throw error
    })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.tables, source.tables.filter(table => table.name === 'Other'))
    assert.deepEqual(reopened.convertCells, source.convertCells)
    assert.deepEqual(reopened.convertExplicit, source.convertExplicit)
    assert.deepEqual(reopened.convertRefs, ['=SUM(#REF!)', '=SUM(staff[Qty])', '=SUM(Other[Qty])'])
    assert.deepEqual(reopened.validations, source.validations)
    assert.deepEqual(reopened.definedNames, source.definedNames)
    const otherXml = Object.values(source.tableXml).find(xml => xml.includes('displayName="Other"'))
    assert.ok(otherXml)
    assert.deepEqual(Object.values(reopened.tableXml), [otherXml], 'the other table XML must remain unchanged')
    const sourceTargetCells = source.cellXml.filter(xml => /r="[AB][1-4]"/.test(xml))
    assert.equal(sourceTargetCells.length, 8)
    assert.deepEqual(reopened.cellXml.filter(xml => /r="[AB][1-4]"/.test(xml)), sourceTargetCells)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'table-convert', browserVersion: browser.version(), undoRedo: true, draftReloaded: true, removedOnlyTarget: true, sourceCellsPreserved: true, references: reopened.convertRefs, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'table-style-options') {

    const labels = ['首列', '末列', '行条纹', '列条纹']
    const initial = [true, false, true, false], changed = initial.map(value => !value)
    const selectTable = async () => { await clickCell(90, 64); await page.locator('[data-ribbon-tab="Table Design"]').click() }
    const checkFlags = async expected => {
      for (let index = 0; index < labels.length; index++) assert.equal(await page.getByRole('checkbox', { name: labels[index], exact: true }).isChecked(), expected[index], labels[index])
    }
    const source = JSON.parse(python({ mode: 'inspect', bytes: sourceBytes.toString('base64') }))
    await selectTable(); await checkFlags(initial)
    for (let index = 0; index < labels.length; index++) await page.getByRole('checkbox', { name: labels[index], exact: true }).setChecked(changed[index])
    await checkFlags(changed)
    const waitFlags = () => page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits' && op.edits.some(edit => edit.firstColumn === false && edit.lastColumn === true && edit.bandedRows === false && edit.bandedColumns === true))))
    await waitFlags()
    await page.locator('[data-ribbon-tab="File"]').click()
    for (let index = 0; index < labels.length; index++) await command('undo')
    await page.locator('[data-ribbon-tab="Table Design"]').click(); await checkFlags(initial)
    await page.locator('[data-ribbon-tab="File"]').click()
    for (let index = 0; index < labels.length; index++) await command('redo')
    await page.locator('[data-ribbon-tab="Table Design"]').click(); await checkFlags(changed)
    await waitFlags()
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await selectTable(); await checkFlags(changed)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 }).catch(async error => {
      console.error(JSON.stringify({ phase: 'table-style-options-save', body: await page.locator('body').innerText(), savePayload, pageErrors })); throw error
    })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.tableStyleOptions.Staff, { firstColumn: false, lastColumn: true, bandedRows: false, bandedColumns: true })
    assert.deepEqual(reopened.tables, source.tables)
    assert.ok(source.cellXml.length >= 6, 'source identity inspection must cover the two-column fixture')
    assert.deepEqual(reopened.cellXml, source.cellXml, 'style option changes must retain every source cell XML')
    assert.equal(savePayload.operations.some(op => op.kind === 'applyCellEdits'), false)
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: savedBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`)
    await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await selectTable(); await checkFlags(changed)
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'table-style-options', browserVersion: browser.version(), revision2Reopened: true, styleOptions: reopened.tableStyleOptions.Staff, sourceCellsPreserved: true, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'table-options') {
    const selectTable = async () => { await clickCell(90, 64); await page.locator('[data-ribbon-tab="Table Design"]').click() }
    const totals = () => page.getByRole('checkbox', { name: '汇总行', exact: true })
    const style = () => page.getByRole('combobox', { name: '表格样式', exact: true })
    const waitDraft = async (enabled, name) => page.waitForFunction(({ enabled, name }) => Object.keys(localStorage).some(key => {
      if (!key.startsWith('native-editor-draft:')) return false
      const edits = JSON.parse(localStorage.getItem(key)).operations?.filter(op => op.kind === 'applyTableEdits').flatMap(op => op.edits) ?? []
      return edits.some(edit => edit.totalsRow === enabled && edit.style === name)
    }), { enabled, name })
    await selectTable()
    await totals().check()
    assert.equal(await totals().isChecked(), true, await feedback())
    assert.equal(await page.locator('[data-ribbon-control="table-range"]').innerText(), 'A1:A4')
    await style().selectOption('TableStyleDark3')
    await waitDraft(true, 'TableStyleDark3')
    await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
    await page.locator('[data-ribbon-tab="Table Design"]').click()
    assert.equal(await style().inputValue(), 'TableStyleMedium4')
    await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
    await page.locator('[data-ribbon-tab="Table Design"]').click()
    assert.equal(await totals().isChecked(), false)
    assert.equal(await page.locator('[data-ribbon-control="table-range"]').innerText(), 'A1:A3')
    await page.locator('[data-ribbon-tab="File"]').click(); await command('redo'); await command('redo')
    await waitDraft(true, 'TableStyleDark3')
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await selectTable()
    assert.equal(await totals().isChecked(), true)
    assert.equal(await style().inputValue(), 'TableStyleDark3')
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const enabledBytes = Buffer.from(savedBytes)
    const enabled = JSON.parse(python({ mode: 'inspect', bytes: enabledBytes.toString('base64') }))
    assert.deepEqual(enabled.tables, [{ name: 'Staff', ref: 'A1:A4', columns: ['Name'], style: 'TableStyleDark3' }])
    assert.equal(enabled.tableTotals.Staff, 1)
    assert.deepEqual(enabled.A4, ['=SUBTOTAL(103,A2:A3)', true])
    assert.equal(enabled.D5, '=COUNTA(Staff[Name])')
    assert.equal(enabled.definedNames.Employees, 'Staff[[Name]]')
    const nextContext = { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: enabledBytes.length, sha256: createHash('sha256').update(enabledBytes).digest('hex') } }
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: nextContext, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: enabledBytes, contentType: media }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/save', async route => {
      savePayload = route.request().postDataJSON()
      savedBytes = Buffer.from(python({ mode: 'patch', bytes: enabledBytes.toString('base64'), operations: savePayload.operations }), 'base64')
      await route.fulfill({ json: { documentId: 'fixture-gui', revision: 3, parentRevision: 2, revisionRegistered: true,
        artifacts: { xlsx: { downloadUrl: '/fixture-gui-download.xlsx', size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } },
        editor: { openUrl: '/reports/v1/native/fixture-gui/3' }, validation: { ok: true, issues: [] } } })
    })
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`)
    await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await selectTable()
    assert.equal(await totals().isChecked(), true)
    assert.equal(await style().inputValue(), 'TableStyleDark3')
    await totals().uncheck(); await style().selectOption('')
    await waitDraft(false, '')
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await selectTable()
    assert.equal(await totals().isChecked(), false)
    assert.equal(await style().inputValue(), '')
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 3', null, { timeout: 60000 }).catch(async error => {
      console.error(JSON.stringify({ phase: 'table-options-revision3-save', body: await page.locator('body').innerText(), savePayload, pageErrors }))
      throw error
    })
    const disabled = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(disabled.tables, [{ name: 'Staff', ref: 'A1:A3', columns: ['Name'], style: '' }])
    // OOXML未写totalsRowCount与0均表示无汇总行；openpyxl将缺省读为None。
    assert.equal(disabled.tableTotals.Staff ?? 0, 0)
    assert.deepEqual(disabled.A4, [null, false])
    assert.equal(disabled.D5, '=COUNTA(Staff[Name])')
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'table-options', browserVersion: browser.version(), revisions: [2, 3], enabled, disabled, pageErrors }))
  } else if (['dv-tables', 'table-headers', 'table-header-paste', 'table-name', 'table-resize'].includes(process.env.WORKBOOK_RIBBON_CASE)) {
    const headers = process.env.WORKBOOK_RIBBON_CASE !== 'dv-tables'
    const naming = process.env.WORKBOOK_RIBBON_CASE === 'table-name'
    const resizing = process.env.WORKBOOK_RIBBON_CASE === 'table-resize'
    const resizeRef = process.env.TABLE_RESIZE_TOTALS === '1' ? 'A1:B7' : 'A1:B5'
    const tableName = naming ? process.env.TABLE_DESIGN_NEW_NAME ?? 'People' : 'Staff'
    const columnName = headers && !naming && !resizing ? 'Employee' : 'Name'
    if (resizing) {
      await clickCell(90, 64)
      await page.locator('[data-ribbon-tab="Table Design"]').click()
      await page.locator('[data-ribbon-control="table-resize"]').click()
      await page.getByRole('textbox', { name: '新的表格范围', exact: true }).fill(resizeRef)
      await page.getByRole('dialog', { name: '调整表格范围', exact: true }).getByRole('button', { name: '确定', exact: true }).click()
      await page.waitForFunction(ref => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits' && op.edits.some(edit => edit.area?.endRow === (ref === 'A1:B7' ? 6 : 4)))), resizeRef)
      assert.equal(await page.locator('[data-ribbon-control="table-range"]').innerText(), resizeRef)
      await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
      await page.locator('[data-ribbon-tab="Table Design"]').click()
      assert.equal(await page.locator('[data-ribbon-control="table-range"]').innerText(), process.env.TABLE_RESIZE_TOTALS === '1' ? 'A1:A4' : 'A1:A3')
      await page.locator('[data-ribbon-tab="File"]').click(); await command('redo')
      await page.locator('[data-ribbon-tab="Table Design"]').click()
      assert.equal(await page.locator('[data-ribbon-control="table-range"]').innerText(), resizeRef)
    } else if (naming) {
      if (process.env.WORKBOOK_TABLE_STYLE_SCREENSHOT) { await clickCell(...E1); await page.locator('.workbook-grid').screenshot({ path: process.env.WORKBOOK_TABLE_STYLE_SCREENSHOT }) }
      await clickCell(90, 64)
      await page.locator('[data-ribbon-tab="Table Design"]').click()
      const input = page.getByRole('textbox', { name: '表格名称', exact: true })
      await input.fill(tableName); await input.press('Tab')
      await page.waitForFunction(name => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits' && op.edits.some(edit => edit.name === name))), tableName)
      await page.locator('[data-ribbon-tab="File"]').click(); await command('undo')
      await page.locator('[data-ribbon-tab="Table Design"]').click()
      assert.equal(await input.inputValue(), 'Staff')
      await page.locator('[data-ribbon-tab="File"]').click(); await command('redo')
      await page.locator('[data-ribbon-tab="Table Design"]').click()
      assert.equal(await input.inputValue(), tableName)
    } else if (headers) {
      await clickCell(...A1)
      if (process.env.WORKBOOK_RIBBON_CASE === 'table-header-paste') {
        const mode = process.env.TABLE_HEADER_PASTE_MODE ?? 'plain'
        if (mode === 'plain') await page.evaluate(() => navigator.clipboard.writeText('Employee'))
        else await page.evaluate(async () => {
          const html = '<table><tr><td><b>Employee</b></td><td>Department</td></tr></table>'
          await navigator.clipboard.write([new ClipboardItem({ 'text/html': new Blob([html], { type: 'text/html' }), 'text/plain': new Blob(['Employee\tDepartment'], { type: 'text/plain' }) })])
        })
        if (mode === 'format' || mode === 'formula') {
          await page.getByLabel('选择性粘贴', { exact: true }).selectOption('paste-special:' + mode)
          await page.waitForFunction(() => /已粘贴/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''))
          assert.equal(await page.evaluate(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits'))), false)
          await clickCell(...A1)
          await page.evaluate(() => navigator.clipboard.writeText('Employee'))
          await command('paste')
        } else if (['value', 'formula', 'besides-border'].includes(mode)) await page.getByLabel('选择性粘贴', { exact: true }).selectOption('paste-special:' + mode)
        else await command('paste')
      } else { await page.keyboard.type('Employee'); await page.keyboard.press('Enter') }
      await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'applyTableEdits')))
      await page.locator('[data-ribbon-tab="File"]').click(); await command('undo'); await command('redo')
    }
    await clickCell(...C1)
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('dv-open')
    await page.getByText('管理数据验证', { exact: true }).waitFor()
    await page.getByText('值必须是列表中的值', { exact: true }).click()
    await page.locator('input[value="Ada"]').waitFor()
    await page.getByText('忽略空值', { exact: true }).click()
    await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'replaceSheetDataValidations' && op.rules.some(item => item.rule.allowBlank === true))))
    await page.getByRole('button', { name: '确认', exact: true }).click()
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.workbook-grid canvas').length >= 1, null, { timeout: 60000 })
    await clickCell(...C1)
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('dv-open')
    await page.getByText('值必须是列表中的值', { exact: true }).waitFor().catch(async error => {
      console.error(JSON.stringify({ restoredBody: await page.locator('body').innerText(), pageErrors }))
      throw error
    })
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.validations, [{ range: 'C1:C3', type: 'list', formula1: `${tableName}[${columnName}]`, prompt: '选择名称', allowBlank: true }])
    assert.deepEqual(reopened.tables, [{ name: tableName, ref: resizing ? resizeRef : 'A1:A3', columns: resizing ? [columnName, 'wide'] : [columnName], style: 'TableStyleMedium4' }])
    if (resizing && process.env.TABLE_RESIZE_TOTALS === '1') {
      assert.deepEqual(reopened.A4, [null, false])
      assert.deepEqual(reopened.A7, ['=SUBTOTAL(103,A2:A6)', true])
      assert.equal(reopened.tableTotals.Staff, 1)
    }
    if (headers) {
      assert.equal(reopened.A1[0], columnName)
      assert.equal(reopened.definedNames.Employees, `${tableName}[[${columnName}]]`)
      assert.equal(reopened.D5, `=COUNTA(${tableName}[${columnName}])`)
    }
    assert.equal(savePayload.operations.filter(op => op.kind === 'replaceSheetDataValidations').length, 1)
    if (naming) assert.equal(savePayload.operations.some(op => op.kind === 'applyCellEdits' && op.edits.some(edit => edit.style && Object.keys(edit.style).length)), false, 'table theme rendering must not create cell format edits')
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: savedBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`)
    await page.locator('.workbook-ribbon').waitFor()
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('dv-open')
    await page.getByText('值必须是列表中的值', { exact: true }).waitFor()
    await page.getByText('值必须是列表中的值', { exact: true }).click()
    await page.locator('input[value="Ada"]').waitFor()
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: process.env.WORKBOOK_RIBBON_CASE, browserVersion: browser.version(), revision2Reopened: true, reopened, pageErrors }))
    await page.screenshot({ path: '/tmp/genoffice-dv-tables-panel.png' })
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'dv-names') {
    await page.locator('[data-ribbon-tab="Formulas"]').click(); await command('name-manager-open')
    await page.getByLabel('已定义名称', { exact: true }).selectOption('Alias')
    await page.locator('.workbook-defined-name-ref').fill('Summary!$A$2:$A$2')
    await page.getByRole('button', { name: '更新', exact: true }).click()
    await page.getByRole('button', { name: '关闭名称管理器', exact: true }).click()
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('dv-open')
    await page.getByText('管理数据验证', { exact: true }).waitFor()
    await page.getByText('值必须是列表中的值', { exact: true }).click()
    await page.locator('input[value="beta"]').waitFor()
    await page.getByText('忽略空值', { exact: true }).click()
    await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === 'replaceSheetDataValidations' && op.rules.some(item => item.rule.allowBlank === true))))
    await page.getByRole('button', { name: '确认', exact: true }).click()
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('dv-open')
    await page.getByText('值必须是列表中的值', { exact: true }).waitFor().catch(async error => {
      console.error(JSON.stringify({ restoredBody: await page.locator('body').innerText(), pageErrors }))
      throw error
    })
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.validations, [{ range: 'C1:C3', type: 'list', formula1: 'Choices', prompt: '选择名称', allowBlank: true }])
    assert.deepEqual(reopened.definedNames, { Choices: 'Alias', Alias: 'Summary!$A$2:$A$2' })
    assert.equal(savePayload.operations.filter(op => op.kind === 'replaceSheetDataValidations').length, 1)
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: savedBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`)
    await page.locator('.workbook-ribbon').waitFor()
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('dv-open')
    await page.getByText('值必须是列表中的值', { exact: true }).waitFor()
    await page.getByText('值必须是列表中的值', { exact: true }).click()
    await page.locator('input[value="beta"]').waitFor()
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'dv-names', browserVersion: browser.version(), revision2Reopened: true, reopened, pageErrors }))
    await page.screenshot({ path: '/tmp/genoffice-dv-names-panel.png' })
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'dv') {
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('dv-open')
    await page.getByText('管理数据验证', { exact: true }).waitFor()
    await page.getByText('整数 大于 0', { exact: true }).click()
    await page.getByPlaceholder('请输入值或公式', { exact: true }).fill('5')
    await page.getByRole('button', { name: '确认', exact: true }).click()
    await page.getByText('整数 大于 5', { exact: true }).waitFor().catch(async error => {
      console.error(JSON.stringify({ body: await page.locator('body').innerText(), feedback: await feedback(), pageErrors }))
      throw error
    })
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('dv-open')
    await page.getByText('整数 大于 5', { exact: true }).waitFor().catch(async error => {
      console.error(JSON.stringify({ restoredBody: await page.locator('body').innerText(), pageErrors }))
      throw error
    })
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: savedBytes.toString('base64') }))
    assert.deepEqual(reopened.validations, [{ range: 'B2:B5', type: 'whole', formula1: '5', prompt: '填写正整数', allowBlank: false }])
    assert.equal(savePayload.operations.filter(op => op.kind === 'replaceSheetDataValidations').length, 1)
    await page.route('**/reports/v1/native/fixture-gui/2/api/context', route => route.fulfill({ json: { context: { ...ctx, revision: 2, parentRevision: 1, sourceFile: { ...ctx.sourceFile, size: savedBytes.length, sha256: createHash('sha256').update(savedBytes).digest('hex') } }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
    await page.route('**/reports/v1/native/fixture-gui/2/api/file', route => route.fulfill({ body: savedBytes, contentType: media }))
    await page.route(/\/reports\/v1\/native\/fixture-gui\/2$/, async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
    await page.addInitScript(() => history.replaceState(null, '', '/reports/v1/native/fixture-gui/2'))
    await page.goto(`${baseUrl}/reports/v1/native/fixture-gui/2`)
    await page.locator('.workbook-ribbon').waitFor()
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('dv-open')
    await page.getByText('整数 大于 5', { exact: true }).waitFor()
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'dv', browserVersion: browser.version(), revision2Reopened: true, reopened, pageErrors }))
    await page.screenshot({ path: '/tmp/genoffice-dv-panel.png' })
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'dedupe') {
    await clickCell(...A1)
    await page.keyboard.down('Shift'); await page.keyboard.press('ArrowRight')
    for (let i = 0; i < 4; i++) await page.keyboard.press('ArrowDown')
    await page.keyboard.up('Shift')
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('remove-duplicates-open')
    await page.getByRole('dialog', { name: '删除重复值', exact: true }).getByRole('button', { name: '确定', exact: true }).click()
    assert.match(await feedback(), /已删除 2 行重复值/)
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
    assert.deepEqual(reopened.dedupeValues, [['Name', 'Flag'], ['Ada', true], ['Grace', false], [null, null], [null, null]])
    assert.deepEqual(reopened.dedupeA3, [true, '保留位置批注'])
    assert.equal(reopened.D5, '=A2'); assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'dedupe', browserVersion: browser.version(), reopened, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'split') {
    await clickCell(...A1); await page.keyboard.press('Shift+ArrowDown')
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('text-to-columns:2')
    assert.match(await feedback(), /文本分列已更新 8 个/)
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
    assert.deepEqual(reopened.splitValues, [['Ada', '001', true, '=A9'], ['Grace', 42, false, null]])
    assert.deepEqual(reopened.splitB1, [true, '保留分列批注'])
    assert.equal(reopened.splitD1type, 's'); assert.equal(reopened.D5, '=A2')
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'split', browserVersion: browser.version(), reopened, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'flash') {
    await clickCell(...C1)
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('flash-fill')
    assert.match(await feedback(), /快速填充已更新 1 个/)
    await page.reload(); await page.locator('.workbook-ribbon').waitFor()
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
    assert.deepEqual(reopened.C1, ['Ada Lovelace', false])
    assert.deepEqual(reopened.C2, ['Grace Hopper', true, '保留目标批注'])
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify({ ok: true, case: 'flash', browserVersion: browser.version(), reopened, pageErrors }))
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'numfmt') {
    // 设置单元格格式▸数字：C3 选货币、¥、负数括号；保存后 openpyxl 回读 number_format，值不变。
    await clickCell(...A1); await clickCell(393, 109); await command('format-cells')
    const dialog = page.locator('.workbook-ribbon-numfmt-dialog')
    await dialog.locator('[data-numfmt-category="currency"]').click()
    await dialog.locator('[data-numfmt-symbol]').selectOption('¥')
    await dialog.locator('[data-numfmt-negative]').selectOption('parens')
    assert.equal(await dialog.locator('[data-numfmt-preview]').innerText(), '(¥1,234.50)')
    await dialog.locator('.workbook-ribbon-format-apply').click()
    assert.match(await feedback(), /数字格式已设为/)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
    console.log(JSON.stringify({ ok: true, case: 'numfmt', browserVersion: browser.version(), operations: savePayload.operations, reopened, pageErrors }))
    assert.deepEqual(reopened.C3fmt, [-1234.5, '¥#,##0.00_);(¥#,##0.00)'])
    assert.deepEqual(pageErrors, [])
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'fill') {
    // 填充：A1:A3 向下（alpha 粗体到 A2/A3）；C1:D1 向左（以 D1 为源，空值覆盖 gamma）；定位到 B3。
    await clickCell(...A1); await page.keyboard.down('Shift'); await clickCell(...A3); await page.keyboard.up('Shift')
    await page.locator('[data-ribbon-menu="fill"]').selectOption('fill-down')
    await page.waitForFunction(() => /已向下填充/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''), null, { timeout: 15000 })
    await clickCell(...C1); await page.keyboard.down('Shift'); await clickCell(...D1); await page.keyboard.up('Shift')
    await page.locator('[data-ribbon-menu="fill"]').selectOption('fill-left')
    await page.waitForFunction(() => /已向左填充/.test(document.querySelector('.workbook-feedback')?.textContent ?? ''), null, { timeout: 15000 })
    await command('goto-open')
    await page.locator('[data-goto-reference]').fill('B3'); await page.locator('.workbook-ribbon-goto-dialog .workbook-ribbon-format-apply').click()
    assert.match(await feedback(), /已定位到 B3/)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
    console.log(JSON.stringify({ ok: true, case: 'fill', browserVersion: browser.version(), operationKinds: savePayload.operations.map(op => op.kind), reopened, pageErrors }))
    assert.deepEqual(reopened.A2.slice(0, 2), ['alpha', true])
    assert.deepEqual(reopened.A3.slice(0, 2), ['alpha', true])
    assert.deepEqual(reopened.C1, [null, false])
    assert.deepEqual(pageErrors, [])
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'sort') {
    // 数据▸自定义排序：A1:A2 不含标题、按 A 列降序（粗体随 alpha 移动）。
    await clickCell(...A1); await page.keyboard.down('Shift'); await clickCell(...A2); await page.keyboard.up('Shift')
    await page.locator('[data-ribbon-tab="Data"]').click(); await command('sort-custom-open')
    const dialog = page.locator('.workbook-ribbon-sort-dialog')
    await dialog.locator('[data-sort-header]').uncheck()
    await dialog.locator('[data-sort-level="0"] [data-sort-order]').selectOption('desc')
    await dialog.locator('.workbook-ribbon-format-apply').click()
    assert.match(await feedback(), /已按 1 个关键字排序/)
    await page.locator('[data-action="save"]').click()
    await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const download = await page.evaluate(async () => { const r = await fetch('/fixture-gui-download.xlsx'); return Array.from(new Uint8Array(await r.arrayBuffer())) })
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: Buffer.from(download).toString('base64') }))
    console.log(JSON.stringify({ ok: true, case: 'sort', browserVersion: browser.version(), operationKinds: savePayload.operations.map(op => op.kind), reopened, pageErrors }))
    assert.deepEqual(reopened.A1.slice(0, 2), ['beta', false])
    assert.deepEqual(reopened.A2.slice(0, 2), ['alpha', true])
    assert.equal(reopened.B1, 'wide')
    assert.deepEqual(pageErrors, [])
  } else if (process.env.WORKBOOK_RIBBON_CASE === 'formulas') {
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
} catch (error) {
  console.error(JSON.stringify({ failed: true, message: String(error), state: await diagnosticPage?.evaluate(() => ({ status: document.querySelector('.save-state-label')?.textContent, feedback: document.querySelector('.workbook-feedback')?.textContent, notice: document.querySelector('.native-notice')?.textContent, url: location.href })).catch(() => null), savePayload, saved: !!savedBytes }))
  throw error
} finally {
  await browser?.close()
  server.kill()
}
