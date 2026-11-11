import { expect, it } from 'vitest'
import { RangeThemeStyle } from '@univerjs/sheets'
import { IUniverInstanceService, LocaleType, Univer, UniverInstanceType, type Workbook } from '@univerjs/core'
import { UniverSheetsPlugin, SheetRangeThemeModel } from '@univerjs/sheets'
import { UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import { builtinTablePalette, installNativeTableStyleRendering, nativeTableTheme, nativeTableThemeId, nativeTableThemeResource, nativeTableThemes, withNativeTableThemes } from './workbook-table-styles'

const table = { id: '7', headerRowCount: 1, totalsRowCount: 1,
  style: { name: 'TableStyleMedium2', showRowStripes: true, showColumnStripes: false, showFirstColumn: false, showLastColumn: false } }
const styleAt = (source: any, row: number, column = 0, lastRow = false, lastColumn = false) => {
  const json = nativeTableTheme(source, undefined, 'theme')!
  return new RangeThemeStyle(json.name, json).getStyle(row, column, lastRow, lastColumn, false)
}

it('resolves all valid Light/Medium/Dark families against the workbook theme without inventing unknown styles', () => {
  const colors = ['#FFFFFF', '#111111', '#EEEEEE', '#222222', '#008800', '#DD0000', '#0000CC', '#ABABAB', '#FF8800', '#00FFFF']
  expect(builtinTablePalette('TableStyleMedium2', colors).headerFill).toBe('#008800')
  expect(builtinTablePalette('TableStyleLight2', colors)).toMatchObject({ headerFontColor: '#006600', stripeFill: '#B4FFB4' })
  expect(builtinTablePalette('TableStyleDark2', colors)).toMatchObject({ headerFill: '#111111', bodyFontColor: '#FFFFFF' })
  for (const [family, count] of [['Light', 21], ['Medium', 28], ['Dark', 11]] as const)
    for (let index = 1; index <= count; index++) expect(nativeTableTheme({ ...table, style: { ...table.style, name: `TableStyle${family}${index}` } }, colors, 'theme')).toBeDefined()
  for (const name of [undefined, '', 'CustomStyle', 'TableStyleLight22', 'TableStyleDark12', 'TableStyleMedium0'])
    expect(nativeTableTheme({ ...table, style: { ...table.style, name } }, colors, 'theme')).toBeUndefined()
})

it('uses the first data row for banding with and without headers and keeps totals outside banding', () => {
  expect(styleAt(table, 0)).toMatchObject({ bg: { rgb: '#4472C4' }, cl: { rgb: '#FFFFFF' }, bl: 1 })
  expect(styleAt(table, 1)).toMatchObject({ bg: { rgb: '#DAE3F3' } })
  expect(styleAt(table, 2)?.bg).toBeUndefined()
  expect(styleAt(table, 3, 0, true)).toMatchObject({ bl: 1, bd: { t: { s: 7 } } })
  expect(styleAt(table, 3, 0, true)?.bg?.rgb).toBe('')
  const headerless = { ...table, headerRowCount: 0, totalsRowCount: 0 }
  expect(styleAt(headerless, 0)).toMatchObject({ bg: { rgb: '#DAE3F3' } })
  expect(styleAt(headerless, 1)?.bg).toBeUndefined()
  expect(styleAt(headerless, 2, 0, true)).toMatchObject({ bg: { rgb: '#DAE3F3' } })
})

it('starts column stripes at the first column and only emphasizes requested edge columns', () => {
  const columns = { ...table, totalsRowCount: 0, style: { ...table.style, showRowStripes: false, showColumnStripes: true, showFirstColumn: true, showLastColumn: true } }
  expect(styleAt(columns, 1, 0)).toMatchObject({ bg: { rgb: '#DAE3F3' }, bl: 1 })
  expect(styleAt(columns, 1, 1)?.bg).toBeUndefined()
  expect(styleAt(columns, 1, 2, false, true)).toMatchObject({ bg: { rgb: '#DAE3F3' }, bl: 1 })
})

it('renders Light outlines and inner borders without marking ordinary edge columns bold', () => {
  const outlined = { ...table, totalsRowCount: 0, style: { ...table.style, name: 'TableStyleLight15' } }
  expect(styleAt(outlined, 0, 0)).toMatchObject({ bd: { t: { s: 1 }, l: { s: 1 } } })
  expect(styleAt(outlined, 1, 1)).toMatchObject({ bd: { t: { s: 1 }, b: { s: 1 }, l: { s: 1 }, r: { s: 1 } } })
  expect(styleAt(outlined, 2, 1, true, true)).toMatchObject({ bd: { b: { s: 1 }, r: { s: 1 } } })
  expect(styleAt(outlined, 1, 0)?.bl).toBeUndefined()
  const ruled = { ...outlined, style: { ...outlined.style, name: 'TableStyleLight2' } }
  expect(styleAt(ruled, 2, 0, true)).toMatchObject({ bd: { b: { s: 8 } } })
  const headerless = { ...ruled, headerRowCount: 0 }
  expect(styleAt(headerless, 0)).toMatchObject({ bd: { t: { s: 8 } } })
  expect(styleAt(headerless, 0)?.bl).toBeUndefined()
  expect(styleAt(headerless, 0)?.cl).toBeUndefined()
})

it('builds distinct table themes only for writable surviving sheets', () => {
  const model = { themePalette: undefined, sheets: [{ name: 'Data', tables: [table] }, { name: 'Unsafe', tablesReadOnlyReason: 'unsupported', tables: [table] }] } as any
  const themes = nativeTableThemes(model, { data: { id: 'data', name: 'Data' }, unsafe: { id: 'unsafe', name: 'Unsafe' } })
  expect(themes).toHaveLength(1)
  expect(themes[0].name).toBe(nativeTableThemeId('data', '7'))
  expect(nativeTableThemeId('a-b', 'c')).not.toBe(nativeTableThemeId('a', 'b-c'))
})

it('renders through the official table theme resource while retaining explicit cell styles and raw cells', () => {
  const darkTable = { ...table, id: '8', style: { ...table.style, name: 'TableStyleDark2' } }
  const model = { sheets: [{ name: 'Data', tables: [table, darkTable] }] } as any
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsTablePlugin)
    const cells = { 0: { 0: { v: 'Name', s: { bg: { rgb: '' }, cl: { rgb: '#000000' }, bl: 0 } }, 1: { v: 'Custom header', s: { bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' }, bl: 0 } }, 3: { v: 'Automatic filled header', s: { bg: { rgb: '#FF0000' }, cl: { rgb: '#000000' }, bl: 0 } }, 4: { v: 'Explicit filled header', s: { bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' } } } }, 1: { 0: { v: 'Ada' }, 1: { v: 'Custom', s: { bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' } } } } }
    const data = { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US,
      sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Data', rowCount: 20, columnCount: 20, cellData: structuredClone(cells) } },
      resources: [nativeTableThemeResource(model, { data: { id: 'data', name: 'Data' } }), { name: 'SHEET_TABLE_PLUGIN', data: JSON.stringify({ data: { tables: [{ id: 'file-table-data-7', name: 'Staff', range: { startRow: 0, endRow: 4, startColumn: 0, endColumn: 1 },
        options: { showHeader: true, showFooter: true, tableStyleId: nativeTableThemeId('data', '7') }, columns: [], meta: {}, filters: {} }], tableFilteredOutRows: [] } }) }] }
    const resource = JSON.parse(data.resources[1].data)
    resource.data.tables.push({ ...resource.data.tables[0], id: 'file-table-data-8', name: 'DarkStaff',
      range: { startRow: 0, endRow: 4, startColumn: 3, endColumn: 4 }, options: { showHeader: true, showFooter: true, tableStyleId: nativeTableThemeId('data', '8') } })
    data.resources[1].data = JSON.stringify(resource)
    const unit = univer.createUnit<object, Workbook>(UniverInstanceType.UNIVER_SHEET, withNativeTableThemes(data, model))
    const renderer = installNativeTableStyleRendering(univer.__getInjector())
    const themes = univer.__getInjector().get(SheetRangeThemeModel)
    expect(themes.getCellStyle('book', 'data', 0, 0)).toMatchObject({ bg: { rgb: '#4472C4' }, bl: 1 })
    expect(themes.getCellStyle('book', 'data', 1, 0)).toMatchObject({ bg: { rgb: '#DAE3F3' } })
    const sheet = unit.getSheetBySheetId('data')!
    expect(sheet.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '#4472C4' }, cl: { rgb: '#FFFFFF' }, bl: 1 })
    expect(sheet.getComposedCellStyle(0, 1)).toMatchObject({ bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' }, bl: 0 })
    expect(sheet.getComposedCellStyle(1, 0)).toMatchObject({ bg: { rgb: '#DAE3F3' } })
    expect(sheet.getComposedCellStyle(1, 1)).toMatchObject({ bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' } })
    expect(sheet.getComposedCellStyle(0, 3)).toMatchObject({ bg: { rgb: '#FF0000' }, cl: { rgb: '#FFFFFF' }, bl: 1 })
    expect(sheet.getComposedCellStyle(0, 4)).toMatchObject({ bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' } })
    expect(sheet.getComposedCellStyle(0, 4).bl).toBeUndefined()
    expect(sheet.getComposedCellStyle(1, 3)).toMatchObject({ bg: { rgb: '#2F5597' }, cl: { rgb: '#FFFFFF' } })
    expect(sheet.getCellMatrix().getData()).toEqual(cells)
    expect(themes.getCellStyle('book', 'data', 5, 0)).toBeUndefined()
    univer.__getInjector().get(IUniverInstanceService).disposeUnit('book')
    const restored = univer.createUnit<object, Workbook>(UniverInstanceType.UNIVER_SHEET, withNativeTableThemes(structuredClone(data), model))
    expect(restored.getSheetBySheetId('data')!.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '#4472C4' }, cl: { rgb: '#FFFFFF' } })
    expect(restored.getSheetBySheetId('data')!.getComposedCellStyle(0, 3)).toMatchObject({ bg: { rgb: '#FF0000' }, cl: { rgb: '#FFFFFF' }, bl: 1 })
    expect(restored.getSheetBySheetId('data')!.getCellMatrix().getData()).toEqual(cells)
    renderer.dispose()
    expect(restored.getSheetBySheetId('data')!.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '' }, cl: { rgb: '#000000' } })
  } finally { univer.dispose() }
})

it.each([
  ['TableStyleLight2', '#DAE3F3', undefined, undefined],
  ['TableStyleMedium23', '#B4C7E7', '#DAE3F3', undefined],
  ['TableStyleDark2', '#2F5597', '#4472C4', undefined],
  ['TableStyleMedium9', '#B4C7E7', '#DAE3F3', '#DAE3F3'],
] as const)('keeps row/column stripe precedence and whole-table fallback through the real Univer renderer: %s', (name, stripe, whole, secondRow) => {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsTablePlugin)
    const cells = { 0: { 0: { v: 'Name' }, 1: { v: 'Qty' } }, 1: { 0: { v: 'Ada' }, 1: { v: 3 } }, 2: { 0: { v: 'Grace' }, 1: { v: 7 } } }
    const unit = univer.createUnit<object, Workbook>(UniverInstanceType.UNIVER_SHEET, {
      id: 'stripes', name: 'stripes', appVersion: '0.25.1', locale: LocaleType.EN_US,
      sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Data', rowCount: 10, columnCount: 10, cellData: structuredClone(cells) } },
    })
    const themes = univer.__getInjector().get(SheetRangeThemeModel)
    const rendering = installNativeTableStyleRendering(univer.__getInjector())
    const sheet = unit.getSheetBySheetId('data')!
    const range = { unitId: 'stripes', subUnitId: 'data', range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 1 } }
    // 行条纹有颜色时优先；未定义第二行条纹时应露出列条纹，最后才使用整表底色。
    for (const [rows, columns, expected] of [
      [true, true, [[stripe, stripe], [secondRow ?? stripe, secondRow ?? whole]]],
      [true, false, [[stripe, stripe], [secondRow ?? whole, secondRow ?? whole]]],
      [false, true, [[stripe, whole], [stripe, whole]]],
    ] as const) {
      const json = nativeTableTheme({ headerRowCount: 1, totalsRowCount: 0,
        style: { name, showRowStripes: rows, showColumnStripes: columns, showFirstColumn: false, showLastColumn: false } }, undefined, 'stripe-theme')!
      themes.registerRangeThemeStyle('stripes', new RangeThemeStyle(json.name, json))
      themes.registerRangeThemeRule(json.name, range)
      for (let row = 1; row <= 2; row++) for (let column = 0; column <= 1; column++)
        expect(sheet.getComposedCellStyle(row, column)?.bg?.rgb,
          `${name}: rows=${rows}, columns=${columns}, row=${row}, column=${column}`).toBe(expected[row - 1]![column])
      expect(sheet.getCellMatrix().getData()).toEqual(cells)
      themes.removeRangeThemeRule(json.name, range)
    }
    rendering.dispose()
  } finally { univer.dispose() }
})
