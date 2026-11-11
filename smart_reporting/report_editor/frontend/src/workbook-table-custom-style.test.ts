import { expect, it } from 'vitest'
import { applyTableAdditions, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/zip'
import { nativeTableTheme, nativeTableThemeResource } from './workbook-table-styles'

// 固定GenOffice f8c17004：native/xlsx-engine/src/tests.rs 自定义MyStyle fixture。
// 源只支持读取已有自定义DXF配色；图库仅内置样式，不要求新建自定义样式UI。
async function fixture(extraDxfs = '', extraElements = '') {
  const bytes = await applyTableAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1', name: 'CustomTable', area: { startRow: 0, endRow: 3, startColumn: 0, endColumn: 1 }, columnNames: ['Name', 'Qty'], style: 'TableStyleMedium2', bandedRows: true }])
  const source = await createBufferEntrySource(bytes), paths = await source.paths(), tablePath = paths.find(path => /^xl\/tables\/[^/]+\.xml$/.test(path))!
  const baseCustom = '<dxfs count="3"><dxf><font><color rgb="FFFF0000"/></font><fill><patternFill><bgColor rgb="FF5B9BD5"/></patternFill></fill></dxf><dxf><fill><patternFill><bgColor rgb="FFDEEBF7"/></patternFill></fill></dxf><dxf><fill><patternFill><bgColor rgb="FFFFC000"/></patternFill></fill></dxf></dxfs><tableStyles count="1"><tableStyle name="MyStyle" pivot="0" count="3"><tableStyleElement type="headerRow" dxfId="0"/><tableStyleElement type="firstRowStripe" dxfId="1"/><tableStyleElement type="totalRow" dxfId="2"/></tableStyle></tableStyles>'
  const custom = baseCustom.replace('</dxfs>', extraDxfs + '</dxfs>').replace('count="3"', `count="${3 + (extraDxfs.match(/<dxf>/g)?.length ?? 0)}"`).replace('</tableStyle>', extraElements + '</tableStyle>')
  const styles = (await source.readText('xl/styles.xml')).replace(/<dxfs\b[^>]*(?:\/>|>[\s\S]*?<\/dxfs>)/g, '').replace(/<tableStyles\b[^>]*(?:\/>|>[\s\S]*?<\/tableStyles>)/g, '').replace('</styleSheet>', custom + '</styleSheet>')
  const tableXml = (await source.readText(tablePath)).replace('TableStyleMedium2', 'MyStyle')
  const customBytes = (await assemblePackage(bytes, { replaced: new Map([['xl/styles.xml', styles], [tablePath, tableXml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: ['xl/styles.xml', tablePath] })).buffer
  return { bytes: customBytes, custom }
}

it('imports existing custom DXF table header and stripe colors', async () => {
  const { bytes: customBytes, custom } = await fixture()
  const model = await readWorkbook(customBytes), table = model.sheets[0]!.tables![0]!
  expect(table.style?.name).toBe('MyStyle')
  await expect((await createBufferEntrySource(customBytes)).readText('xl/styles.xml')).resolves.toContain(custom)
  const theme = nativeTableTheme(table, model.themePalette, 'custom-theme')
  expect(theme?.headerRowStyle).toMatchObject({ bg: { rgb: '#5B9BD5' }, cl: { rgb: '#FF0000' } })
  expect(theme?.firstRowStyle).toMatchObject({ bg: { rgb: '#DEEBF7' } })
  const resource = JSON.parse(nativeTableThemeResource(model, { 'sheet-0': { id: 'sheet-0', name: 'Sheet1' } }).data)
  expect(Object.keys(resource.rangeThemeStyleMapJson)).toHaveLength(1)
})


it('renders real custom table cells, preserves explicit fills, rebuilds options with undo and saves original ZIP style bytes', async () => {
  const { Univer, LocaleType, IUniverInstanceService, UniverInstanceType } = await import('@univerjs/core')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverSheetsTablePlugin, TableManager } = await import('@univerjs/sheets-table')
  const { UniverFormulaEnginePlugin } = await import('@univerjs/engine-formula')
  const { UniverSheetsFormulaPlugin } = await import('@univerjs/sheets-formula')
  await import('@univerjs/sheets/facade'); await import('@univerjs/sheets-table/facade')
  const { withWorkbookTables, workbookTableConfig, workbookTableOperations } = await import('./workbook-tables')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { installNativeTableStyleRendering } = await import('./workbook-table-styles')
  const { installTableStyleEdit } = await import('./workbook-table-style-edit')
  const { installTableTotals } = await import('./workbook-table-totals')
  const { installTableHeaderRow } = await import('./workbook-table-header-row')
  const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
  const { applyCellEdits } = await import('@sheets-web/xlsx-engine')
  const source = await fixture(), bytes = await applyCellEdits(source.bytes, [{ sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 'Keep' }, style: { fillColor: '#ABCDEF', fontColor: '#990099' } }])
  const model = await readWorkbook(bytes), univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  let rendering: ReturnType<typeof installNativeTableStyleRendering> | undefined, styles: ReturnType<typeof installTableStyleEdit> | undefined, totals: ReturnType<typeof installTableTotals> | undefined, headers: ReturnType<typeof installTableHeaderRow> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin); univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
    const data = withWorkbookTables(buildWorkbookData(model, 'custom', 'custom'), model), api = FUniver.newAPI(univer)
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, data)
    const injector = univer.__getInjector(); injector.get(IUniverInstanceService).focusUnit('custom')
    rendering = installNativeTableStyleRendering(injector); styles = installTableStyleEdit({ univer, univerAPI: api }); totals = installTableTotals({ univer, univerAPI: api })
    const workbook = api.getActiveWorkbook()!, sheet = workbook.getActiveSheet()!.getSheet(), table = injector.get(TableManager).getTableList('custom')[0]!, id = table.id
    headers = installTableHeaderRow({ univer, univerAPI: api })
    const matrix = structuredClone(sheet.getCellMatrix().getData())
    expect(sheet.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '#5B9BD5' }, cl: { rgb: '#FF0000' }, bl: 1 })
    expect(sheet.getComposedCellStyle(1, 0)).toMatchObject({ bg: { rgb: '#DEEBF7' } })
    expect(sheet.getComposedCellStyle(2, 0)?.bg?.rgb).toBeUndefined()
    expect(sheet.getComposedCellStyle(1, 1)).toMatchObject({ bg: { rgb: '#ABCDEF' }, cl: { rgb: '#990099' } })
    styles.setOption(id, 'showRowStripes', false)
    expect(sheet.getComposedCellStyle(1, 0)?.bg?.rgb).toBeUndefined()
    await api.undo(); expect(sheet.getComposedCellStyle(1, 0)?.bg?.rgb).toBe('#DEEBF7')
    await api.redo(); expect(sheet.getComposedCellStyle(1, 0)?.bg?.rgb).toBeUndefined()
    styles.setOption(id, 'showRowStripes', true)
    expect(sheet.getCellMatrix().getData()).toEqual(matrix)
    headers.setHeaderRow(id, false)
    expect(sheet.getComposedCellStyle(1, 0)?.bg?.rgb).toBe('#DEEBF7')
    await api.undo(); expect(sheet.getComposedCellStyle(0, 0)?.bg?.rgb).toBe('#5B9BD5')
    totals.setTotals(id, true)
    expect(sheet.getComposedCellStyle(4, 0)?.bg?.rgb).toBe('#FFC000')
    const operations = workbookTableOperations(model, workbook), saved = await applyWorkbookOperations(bytes, operations), reopened = await readWorkbook(saved)
    expect(reopened.sheets[0]!.tables![0]!.customStyle).toEqual(model.sheets[0]!.tables![0]!.customStyle)
    const originalZip = await createBufferEntrySource(bytes), savedZip = await createBufferEntrySource(saved)
    for (const path of await originalZip.paths()) if (!path.startsWith('xl/tables/') && path !== 'xl/workbook.xml') expect(await savedZip.readText(path), path).toBe(await originalZip.readText(path))
    api.disposeUnit('custom')
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(buildWorkbookData(reopened, 'custom', 'custom'), reopened))
    injector.get(IUniverInstanceService).focusUnit('custom')
    const reopenedSheet = api.getActiveWorkbook()!.getActiveSheet()!.getSheet()
    expect(reopenedSheet.getComposedCellStyle(0, 0)?.bg?.rgb).toBe('#5B9BD5')
    expect(reopenedSheet.getComposedCellStyle(1, 0)?.bg?.rgb).toBe('#DEEBF7')
    expect(reopenedSheet.getComposedCellStyle(4, 0)?.bg?.rgb).toBe('#FFC000')
    styles.setStyle(id, 'TableStyleDark2')
    expect(reopenedSheet.getComposedCellStyle(0, 0)?.bg?.rgb).toBe('#000000')
    await api.undo(); expect(reopenedSheet.getComposedCellStyle(0, 0)?.bg?.rgb).toBe('#5B9BD5')
  } finally { headers?.dispose(); totals?.dispose(); styles?.dispose(); rendering?.dispose(); univer.dispose() }
}, 20000)

it('projects custom outline, inner borders, column bands and first-header text at their exact cells', async () => {
  const { Univer, LocaleType, IUniverInstanceService, UniverInstanceType } = await import('@univerjs/core')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverSheetsTablePlugin, TableManager } = await import('@univerjs/sheets-table')
  await import('@univerjs/sheets/facade'); await import('@univerjs/sheets-table/facade')
  const { withWorkbookTables, workbookTableConfig } = await import('./workbook-tables')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { installNativeTableStyleRendering } = await import('./workbook-table-styles')
  const { installTableStyleEdit } = await import('./workbook-table-style-edit')
  const source = await fixture('<dxf><fill><patternFill><bgColor rgb="FFEEEEEE"/></patternFill></fill><border><left style="medium"><color rgb="FF112233"/></left><horizontal style="dotted"><color rgb="FF445566"/></horizontal><vertical style="dashed"><color rgb="FF778899"/></vertical></border></dxf><dxf><fill><patternFill><bgColor rgb="FF00FF00"/></patternFill></fill></dxf><dxf><fill><patternFill><bgColor rgb="FFFFFF00"/></patternFill></fill></dxf><dxf><font><color rgb="FF990099"/></font></dxf><dxf><fill><patternFill><bgColor rgb="FF0000FF"/></patternFill></fill></dxf>',
    '<tableStyleElement type="wholeTable" dxfId="3"/><tableStyleElement type="firstColumn" dxfId="4"/><tableStyleElement type="lastColumn" dxfId="5"/><tableStyleElement type="firstHeaderCell" dxfId="6"/><tableStyleElement type="firstColumnStripe" dxfId="7"/>')
  const { applyCellEdits } = await import('@sheets-web/xlsx-engine')
  const bytes = await applyCellEdits(source.bytes, [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' }, style: {
    fontColor: '#006600', borderTop: { style: 'thick', color: '#EE0000' }, borderBottom: { style: 'double', color: '#EE0000' }, borderLeft: { style: 'dashed', color: '#EE0000' }, borderRight: { style: 'dotted', color: '#EE0000' },
  } }])
  const model = await readWorkbook(bytes), univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  let rendering: ReturnType<typeof installNativeTableStyleRendering> | undefined, styles: ReturnType<typeof installTableStyleEdit> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
    const api = FUniver.newAPI(univer), injector = univer.__getInjector()
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(buildWorkbookData(model, 'custom-corners', 'custom'), model)); injector.get(IUniverInstanceService).focusUnit('custom-corners')
    rendering = installNativeTableStyleRendering(injector); styles = installTableStyleEdit({ univer, univerAPI: api })
    const sheet = api.getActiveWorkbook()!.getActiveSheet()!.getSheet(), tableId = injector.get(TableManager).getTableList('custom-corners')[0]!.id
    expect(sheet.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '#5B9BD5' }, cl: { rgb: '#006600' }, bd: { t: { s: 8, cl: { rgb: '#112233' } }, l: { s: 8, cl: { rgb: '#112233' } }, b: { s: 3, cl: { rgb: '#445566' } }, r: { s: 4, cl: { rgb: '#778899' } } } })
    const originalCells = structuredClone(sheet.getCellMatrix().getData())
    expect(sheet.getComposedCellStyle(2, 0)?.bg?.rgb).toBe('#EEEEEE')
    styles.setOption(tableId, 'showFirstColumn', true)
    expect(sheet.getComposedCellStyle(0, 0)?.cl?.rgb).toBe('#006600')
    expect(sheet.getComposedCellStyle(1, 0)?.bg?.rgb).toBe('#00FF00')
    styles.setOption(tableId, 'showLastColumn', true)
    expect(sheet.getComposedCellStyle(1, 1)?.bg?.rgb).toBe('#FFFF00')
    await api.undo(); expect(sheet.getComposedCellStyle(1, 1)?.bg?.rgb).toBe('#DEEBF7')
    styles.setOption(tableId, 'showFirstColumn', false); styles.setOption(tableId, 'showRowStripes', false); styles.setOption(tableId, 'showColumnStripes', true)
    expect(sheet.getComposedCellStyle(1, 0)?.bg?.rgb).toBe('#0000FF')
    expect(sheet.getComposedCellStyle(1, 1)?.bg?.rgb).toBe('#EEEEEE')
    expect(sheet.getCellMatrix().getData()).toEqual(originalCells)
    styles.setOption(tableId, 'showFirstColumn', true)
    api.getActiveWorkbook()!.getActiveSheet()!.getRange(0, 0).setFontColor('#000000')
    expect(sheet.getComposedCellStyle(0, 0)?.cl?.rgb).toBe('#990099')
    expect(sheet.getComposedCellStyle(3, 1)?.bd).toMatchObject({ b: { s: 8, cl: { rgb: '#112233' } }, r: { s: 8, cl: { rgb: '#112233' } } })
  } finally { styles?.dispose(); rendering?.dispose(); univer.dispose() }
})
