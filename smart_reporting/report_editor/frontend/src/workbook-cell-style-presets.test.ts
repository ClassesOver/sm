import { expect, it } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { readBackSnapshot } from './workbook-vendor/grid/sync'
import { diffToEdits } from './workbook-vendor/core/session-core'
import { logicalStyleOf } from './workbook-vendor/core/style-map'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { applyWorkbookCellStyle } from './workbook-cell-style-presets'

// 固定源 app-constants.ts:232–285 的14个patch。未给出的属性必须保留原值。
const expected = {
 good: { fillColor: '#C6EFCE', fontColor: '#006100' }, bad: { fillColor: '#FFC7CE', fontColor: '#9C0006' },
 neutral: { fillColor: '#FFEB9C', fontColor: '#9C6500' },
 input: { fillColor: '#FFCC99', fontColor: '#3F3F76', borderTop: { style: 'thin', color: '#7F7F7F' }, borderBottom: { style: 'thin', color: '#7F7F7F' }, borderLeft: { style: 'thin', color: '#7F7F7F' }, borderRight: { style: 'thin', color: '#7F7F7F' } },
 output: { fillColor: '#F2F2F2', fontColor: '#3F3F3F', bold: true, borderTop: { style: 'thin', color: '#3F3F3F' }, borderBottom: { style: 'thin', color: '#3F3F3F' }, borderLeft: { style: 'thin', color: '#3F3F3F' }, borderRight: { style: 'thin', color: '#3F3F3F' } },
 calculation: { fillColor: '#F2F2F2', fontColor: '#FA7D00', bold: true, borderTop: { style: 'thin', color: '#7F7F7F' }, borderBottom: { style: 'thin', color: '#7F7F7F' }, borderLeft: { style: 'thin', color: '#7F7F7F' }, borderRight: { style: 'thin', color: '#7F7F7F' } },
 'warning-text': { fontColor: '#FF0000' }, title: { bold: true, fontSize: 18, fontColor: '#44546A' },
 'heading-1': { bold: true, fontSize: 15, fontColor: '#44546A', borderBottom: { style: 'thin', color: '#4472C4' } },
 'heading-2': { bold: true, fontSize: 13, fontColor: '#44546A', borderBottom: { style: 'thin', color: '#8EA9DB' } },
 total: { bold: true, borderTop: { style: 'thin', color: '#4472C4' } },
 'accent1-20': { fillColor: '#DDEBF7' }, 'accent1-40': { fillColor: '#BDD7EE' }, accent1: { fillColor: '#4472C4', fontColor: '#FFFFFF' },
}

it.each(Object.entries(expected))('applies source %s using real facade and existing style save/read chain', async (preset, target) => {
 const source = await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 2, formula: '=1+1' }, style: { italic: true, numberFormat: '0.00', borderBottom: { style: 'double', color: '#123456' } } }, { sheetName: 'Sheet1', row: 0, column: 2, writeValue: true, cell: { value: 'keep' } }])
 const model = await readWorkbook(source)
 const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } });univer.registerPlugin(UniverSheetsPlugin)
 const api = FUniver.newAPI(univer)
 try {
  const book = api.createWorkbook(buildWorkbookData(model, 'preset', 'Preset') as never);univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId())
  book.setActiveRange(book.getActiveSheet()!.getRange('A1:B2'))
  expect(applyWorkbookCellStyle({ univerAPI: api }, preset)).toBe(true)
  const snapshot = readBackSnapshot(book.getSnapshot())
  // 与生产collectOperations相同：公式计算缓存不属于用户值编辑。
  snapshot.sheets[0]!.cells.A1!.value = model.sheets[0]!.cells.A1!.value
  const edits = diffToEdits(model, snapshot)
  expect(edits).toHaveLength(4)
  expect(edits.find(edit => edit.row === 0 && edit.column === 0)?.writeValue).toBe(false)
  const reopened = await readWorkbook(await applyWorkbookOperations(source, [{ kind: 'applyCellEdits', edits }]))
  for (const address of ['A1', 'A2', 'B1', 'B2']) {
   const cell = reopened.sheets[0]!.cells[address]!
   const style = logicalStyleOf(reopened.styles, reopened.styles.cellXfs[cell.styleIndex!], reopened.themePalette)
   // top/bottom 命令只作用于整个选区的外缘，all 则含内边线。
   const perCell = { ...target } as Record<string, unknown>
   if (preset === 'total' && address.endsWith('2')) delete perCell.borderTop
   if (preset.startsWith('heading-') && address.endsWith('1')) delete perCell.borderBottom
   expect(style, address).toMatchObject(perCell)
   if (address === 'A1') { expect(style).toMatchObject({ italic: true, numberFormat: '0.00' });if (!('borderBottom' in perCell)) expect(style!.borderBottom).toEqual({ style: 'double', color: '#123456' }) }
  }
  expect(reopened.sheets[0]!.cells.A1!.formula).toBe('=1+1')
  expect(reopened.sheets[0]!.cells.C1!.value).toBe('keep')
  await api.undo()
  // 源预设由多个官方命令组成；最后一项撤销只撤销最后一次属性变更。
  expect(diffToEdits(model, readBackSnapshot(book.getSnapshot()))).not.toEqual(edits)
 } finally { univer.dispose() }
})

it('leaves the workbook unchanged for absent selection and unknown preset', () => {
 const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } });univer.registerPlugin(UniverSheetsPlugin)
 const api = FUniver.newAPI(univer)
 try {
  expect(applyWorkbookCellStyle({ univerAPI: api }, 'good')).toBe(false)
  const book = api.createWorkbook({ id: 'unknown', name: 'Unknown', sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Sheet1', rowCount: 10, columnCount: 10, cellData: { 0: { 0: { v: 'keep' } } } } } })
  univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId());book.setActiveRange(book.getActiveSheet()!.getRange('A1'))
  const before = book.getSnapshot()
  expect(applyWorkbookCellStyle({ univerAPI: api }, 'not-a-source-preset')).toBe(false)
  expect(applyWorkbookCellStyle({ univerAPI: api }, '__proto__')).toBe(false)
  expect(applyWorkbookCellStyle({ univerAPI: api }, 'constructor')).toBe(false)
  expect(book.getSnapshot()).toEqual(before)
 } finally { univer.dispose() }
})
