// 产品设置组件夹具：替换宿主/运算回调，不冒充实际保存、生产授权或 Excel 桌面验收。
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { createBlankWorkbook, assemblePackage } from '@sheets-web/xlsx-engine'
import { createNameManagerDialog } from '../src/workbook-defined-names'
import { createGoToDialog } from '../src/workbook-goto'
import { createFillSeriesDialog } from '../src/workbook-fill-series'
import { createCellsDialog } from '../src/workbook-cell-shift'
import { createAxisSizeDialog } from '../src/workbook-axis-size'
import { createDedupeDialog } from '../src/workbook-dedupe'
import { createHeaderFooterDialog, headerFooterEditorState } from '../src/workbook-header-footer-editor'
import { createPrintScaleDialog } from '../src/workbook-print-scale'
import { createPrintPreviewDialog, buildWorkbookPrintJob } from '../src/workbook-print-preview'
import { createNoteDialog } from '../src/workbook-notes'
import { createNumberFormatDialog } from '../src/workbook-format'
import { createWorkbookQueriesDialog } from '../src/workbook-queries'
import { InsertFunctionDialog } from '../src/workbook-function-catalog-dialog'

export const workbookSettingsModes = [
  'name-manager-empty', 'name-manager-selected', 'name-manager-error', 'goto-empty', 'goto-names', 'goto-error',
  'fill-linear', 'fill-date', 'fill-trend', 'fill-error', 'cells-insert', 'cells-delete',
  'axis-row', 'axis-col', 'axis-error', 'dedupe', 'dedupe-error',
  'header-footer', 'header-footer-variants', 'header-footer-error', 'print-scale', 'print-scale-fit', 'print-scale-error',
  'print-preview', 'print-preview-error', 'print-preview-pending', 'note', 'note-readonly', 'note-error',
  'custom-format', 'custom-format-mixed', 'custom-format-error', 'queries', 'queries-empty', 'queries-error', 'queries-pending',
  'function-catalog', 'function-catalog-empty', 'function-catalog-selected',
]
const failure = '工作表状态已变化：' + '请保留当前编辑，重新读取来源后再重试。'.repeat(16)
const reject = () => { throw new Error(failure) }
const submit = root => root.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))

async function queryBytes() {
  const source = await createBlankWorkbook('经营数据汇总')
  const ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
  const rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
  const replaced = new Map([
    ['xl/connections.xml', `<connections xmlns="${ns}"><connection id="1" name="季度经营数据查询_${'长名称'.repeat(18)}"><webPr url="https://example.test/${'data/'.repeat(24)}"/></connection><connection id="2" name="仅连接的数据库查询"/></connections>`],
    ['xl/workbook.xml', `<workbook xmlns="${ns}" xmlns:r="${rel}"><sheets><sheet name="经营数据汇总" sheetId="1" r:id="rId1"/></sheets><definedNames><definedName name="ExternalData_1" localSheetId="0">'经营数据汇总'!$A$1:$C$5</definedName></definedNames></workbook>`],
    ['xl/_rels/workbook.xml.rels', `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="${rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>`],
    ['xl/worksheets/_rels/sheet1.xml.rels', `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="q1" Type="${rel}/queryTable" Target="../queryTables/queryTable1.xml"/></Relationships>`],
    ['xl/queryTables/queryTable1.xml', `<queryTable xmlns="${ns}" name="ExternalData_1" connectionId="1"/>`],
  ])
  return (await assemblePackage(source, { replaced, added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [] })).buffer
}

function printJob(scope) {
  const setup = { orientation: 'portrait', paperSize: 9, scale: 100, fitToPage: false, fitToWidth: 0, fitToHeight: 0,
    margins: { left: .7, right: .7, top: .75, bottom: .75 }, printGridlines: true, printHeadings: false,
    printArea: null, printTitles: null, rowBreaks: [], colBreaks: [], headerFooter: { oddHeader: '&C季度经营数据', oddFooter: '&C&P / &N' } }
  const inputs = ['经营数据汇总', '部门收入明细'].slice(0, scope === 'workbook' ? 2 : 1).map((name, index) => ({
    sheetId: 'sheet' + index, setup, source: { name, merges: [], columnWidths: {}, rowHeights: {}, hiddenRows: new Set(), hiddenColumns: new Set(),
      cells: Object.fromEntries(Array.from({ length: 70 }, (_, row) => ['A' + (row + 1), { value: name + ' · 第 ' + (row + 1) + ' 行' }])) },
  }))
  return buildWorkbookPrintJob(inputs, { now: new Date('2026-11-12T00:00:00+08:00') })
}

export async function openWorkbookSettings(root, mode) {
  const errorMode = mode.endsWith('-error')
  if (mode.startsWith('name-manager')) {
    const rows = mode.endsWith('-empty') ? [] : Array.from({ length: 32 }, (_, i) => ({ name: 'RegionalRevenue_' + i + '_LongName'.repeat(8), refersTo: "'经营数据汇总'!$A$1:$D$80", ...(i % 2 ? { scopeSheetId: 'sheet2' } : {}) }))
    createNameManagerDialog(root, { sheets: () => [{ id: 'sheet1', name: '经营数据汇总' }, { id: 'sheet2', name: '部门收入明细' }], rows: () => rows, apply: () => failure }).open({ ref: "'经营数据汇总'!$A$1:$D$80" })
    if (mode.endsWith('-selected')) {
      const list = root.querySelector('.workbook-defined-name-list'); list.selectedIndex = 1; list.dispatchEvent(new Event('change'))
    }
    if (errorMode) { root.querySelector('.workbook-defined-name-name').value = 'NewRevenue'; root.querySelector('.workbook-defined-name-add').click() }
  } else if (mode.startsWith('goto-')) {
    createGoToDialog(root, () => failure).open(mode.endsWith('-empty') ? [] : Array.from({ length: 30 }, (_, i) => ({ name: 'QuarterlyRevenue_' + i + '_LongName'.repeat(9), ref: "'经营数据汇总'!$A$1:$D$80" })))
    if (errorMode) { const input = root.querySelector('[data-goto-reference]'); input.value = 'A2'; input.dispatchEvent(new Event('input')); submit(root) }
  } else if (mode.startsWith('fill-')) {
    createFillSeriesDialog(root, () => failure).open('columns', mode === 'fill-date' ? 'date' : 'linear')
    if (mode === 'fill-trend') root.querySelector('[data-fill-trend]').click()
    if (errorMode) submit(root)
  } else if (mode.startsWith('cells-')) createCellsDialog(root, reject).open(mode.slice(6))
  else if (mode.startsWith('axis-')) {
    createAxisSizeDialog(root, reject).open({ axis: mode === 'axis-col' ? 'col' : 'row', start: 0, count: 32, sheetId: 'sheet1' })
    if (errorMode) { root.querySelector('input').value = '24'; submit(root) }
  } else if (mode.startsWith('dedupe')) { createDedupeDialog(root, reject).open(); if (errorMode) submit(root) }
  else if (mode.startsWith('header-footer')) {
    createHeaderFooterDialog(root, reject).open(headerFooterEditorState({ oddHeader: '&L季度经营报告&C&P / &N&R&A', oddFooter: '&C财务审核', differentFirst: mode.endsWith('-variants'), differentOddEven: mode.endsWith('-variants') }), { book: {}, sheet: {}, sheetId: 'sheet1' })
    if (errorMode) { root.querySelector('textarea').value = 'New header'; submit(root) }
  } else if (mode.startsWith('print-scale')) {
    createPrintScaleDialog(root, reject).open({ scale: 85, fitToPage: mode.endsWith('-fit') }, { book: {}, sheet: {}, sheetId: 'sheet1' })
    if (errorMode) submit(root)
  } else if (mode.startsWith('print-preview')) {
    createPrintPreviewDialog(root, { buildJob: async scope => errorMode ? reject() : mode.endsWith('-pending') ? new Promise(() => {}) : printJob(scope), print: () => false }).open({ hasSelection: true, sheetCount: 2 })
  } else if (mode.startsWith('note')) {
    const note = { id: 'note1', row: 0, col: 0, note: '经营数据已复核，请核对本季度收入。'.repeat(15), width: 160, height: 100 }
    const workbook = { getSheetBySheetId: () => ({ getRange: () => ({ getNote: () => note }) }) }
    createNoteDialog(root, reject).open({ workbook, sheetId: 'sheet1', row: 0, column: 0, before: '' }, { notes: [{ row: 0, column: 0, author: '财务部_' + '长作者名称'.repeat(24), text: note.note }] }, mode !== 'note-readonly')
    if (errorMode) submit(root)
  } else if (mode.startsWith('custom-format')) {
    createNumberFormatDialog(root, { initial: () => mode.endsWith('-mixed') ? { kind: 'mixed' } : { kind: 'value', value: '#,##0.000' }, apply: reject }).open(undefined)
    if (errorMode) submit(root)
  } else if (mode.startsWith('queries')) {
    document.documentElement.dataset.primaryAction = 'none'
    const book = {}
    const dialog = createWorkbookQueriesDialog(root, { getWorkbook: () => book, getBytes: async () => errorMode ? reject() : mode.endsWith('-pending') ? new Promise(() => {}) : mode.endsWith('-empty') ? createBlankWorkbook() : queryBytes(), onGo: () => failure })
    if (mode.endsWith('-pending')) void dialog.open(); else await dialog.open()
  } else if (mode.startsWith('function-catalog')) {
    root.className = 'workbook-function-root'
    const react = createRoot(root)
    const catalog = Array.from({ length: 18 }, (_, i) => ({ name: 'SUM' + (i || ''), category: 'Math', syntax: 'SUM' + (i || '') + '(number1, [number2], …)', abstract: '返回指定数值或单元格区域的总和。'.repeat(5), description: '用于汇总工作表中的经营数据。'.repeat(10), params: [] }))
    react.render(createElement(InsertFunctionDialog, { targetLabel: '经营数据汇总!A1', catalog: mode.endsWith('-empty') ? [] : catalog, recent: ['SUM'], initialCategory: 'All', onPick() {}, onClose: () => react.unmount() }))
    if (mode.endsWith('-selected')) document.documentElement.dataset.catalogSelect = 'true'
  } else throw new Error('未知工作簿设置模式：' + mode)
  document.documentElement.dataset.workbookSettingsReady = 'true'
}
