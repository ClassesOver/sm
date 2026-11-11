import { expect, it } from 'vitest'
import { CellValueType, LocaleType, Univer, UniverInstanceType, type Workbook } from '@univerjs/core'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverSheetsNumfmtPlugin } from '@univerjs/sheets-numfmt'
import { UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import { installCalculation } from './workbook-calculation'
import { installNativeTableStyleRendering } from './workbook-table-styles'
import { withWorkbookTables, workbookTableConfig } from './workbook-tables'

it('keeps native table styles and raw formulas while toggling formatted cells into formula view', () => {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsNumfmtPlugin)
    univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
    const model = { sheets: [{ name: 'Data', tables: [{ id: '1', name: 'Staff', displayName: 'Staff',
      range: { startRow: 0, endRow: 3, startColumn: 0, endColumn: 1 }, headerRowCount: 1, totalsRowCount: 0,
      columns: [{ id: '1', name: 'Value' }, { id: '2', name: 'Explicit' }],
      style: { name: 'TableStyleMedium2', showRowStripes: true, showColumnStripes: false, showFirstColumn: false, showLastColumn: false } }] }] }
    const data = { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US,
      sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Data', rowCount: 20, columnCount: 20,
        cellData: { 0: { 0: { v: 'Value', t: CellValueType.STRING }, 1: { v: 'Explicit', t: CellValueType.STRING } },
          1: { 0: { f: '=1+1', v: 2, t: CellValueType.NUMBER, s: { n: { pattern: '0.00' } } },
            1: { f: '=2+2', v: 4, t: CellValueType.NUMBER, s: { bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' } } } } } } } }
    const workbook = univer.createUnit<object, Workbook>(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(data as any, model as any))
    const rendering = installNativeTableStyleRendering(univer.__getInjector())
    let formulaView = false
    const calculation = installCalculation({ univer }, () => formulaView)
    const sheet = workbook.getSheetBySheetId('data')!, before = structuredClone(sheet.getCellMatrix().getData())
    const beforeStyles = structuredClone(workbook.getSnapshot().styles)
    const normalStyle = structuredClone(sheet.getComposedCellStyle(1, 0))
    expect(normalStyle).toMatchObject({ bg: { rgb: '#DAE3F3' }, n: { pattern: '0.00' } })
    expect(sheet.getCell(1, 0)?.v).toBe('2.00')
    formulaView = true; calculation.syncFormulaView(true)
    expect(sheet.getCell(1, 0)).toMatchObject({ v: '=1+1', t: CellValueType.STRING, p: null })
    expect(sheet.getCell(1, 1)).toMatchObject({ v: '=2+2', t: CellValueType.STRING })
    expect(sheet.getComposedCellStyle(1, 0)).toEqual(normalStyle)
    expect(sheet.getComposedCellStyle(1, 1)).toMatchObject({ bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' } })
    expect(sheet.getCellMatrix().getData()).toEqual(before)
    expect(workbook.getSnapshot().styles).toEqual(beforeStyles)
    formulaView = false; calculation.syncFormulaView(false)
    expect(sheet.getCell(1, 0)?.v).toBe('2.00')
    expect(sheet.getComposedCellStyle(1, 0)).toEqual(normalStyle)
    expect(sheet.getCellMatrix().getData()).toEqual(before)
    expect(workbook.getSnapshot().styles).toEqual(beforeStyles)
    calculation.dispose(); rendering.dispose()
  } finally { univer.dispose() }
})
