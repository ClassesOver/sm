import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { applyPageSetups, createBlankWorkbook, readWorkbook } from '../packages/xlsx-engine/src/index'
import { applyWorkbookOperations } from './operations'

const SHEET = 'xl/worksheets/sheet1.xml'
async function withPane(pane: string, selection = '') {
  const zip = await JSZip.loadAsync(await createBlankWorkbook('Report'))
  const xml = (await zip.file(SHEET)!.async('text')).replace(/<sheetView\b[^>]*?\/>|<sheetView\b[^>]*>[\s\S]*?<\/sheetView>/, `<sheetView tabSelected="1" zoomScale="120" workbookViewId="0">${pane}${selection}</sheetView>`)
  expect(xml).toContain(pane)
  zip.file(SHEET, xml)
  return zip.generateAsync({ type: 'uint8array' })
}
const SPLIT = '<pane xSplit="2400" ySplit="1200" topLeftCell="C5" activePane="bottomRight"/>'

it('reads state-less and split panes as split twips, never as frozen rows/columns', async () => {
  const sheet = async (bytes: Uint8Array) => (await readWorkbook(bytes)).sheets[0]!
  const split = await sheet(await withPane(SPLIT))
  expect(split.freeze).toBeNull()
  expect(split.splitPane).toEqual({ xSplitTwips: 2400, ySplitTwips: 1200, topLeftCell: 'C5' })
  const explicit = await sheet(await withPane('<pane ySplit="900.5" topLeftCell="A4" activePane="bottomLeft" state="split"/>'))
  expect(explicit.freeze).toBeNull()
  expect(explicit.splitPane).toEqual({ xSplitTwips: 0, ySplitTwips: 900.5, topLeftCell: 'A4' })
  const frozen = await sheet(await withPane('<pane xSplit="1" ySplit="2" topLeftCell="B3" activePane="bottomRight" state="frozen"/>'))
  expect(frozen.freeze).toEqual({ frozenRows: 2, frozenColumns: 1 }); expect(frozen.splitPane).toBeUndefined()
  const frozenSplit = await sheet(await withPane('<pane ySplit="3" topLeftCell="A4" activePane="bottomLeft" state="frozenSplit"/>'))
  expect(frozenSplit.freeze).toEqual({ frozenRows: 3, frozenColumns: 0 })
})

it('removes only the split pane bound to its current identity and keeps the rest of the view', async () => {
  const source = await withPane(SPLIT, '<selection pane="bottomRight" activeCell="C5" sqref="C5"/>')
  const expected = { xSplitTwips: 2400, ySplitTwips: 1200, topLeftCell: 'C5' }
  const saved = await applyWorkbookOperations(source, [{ kind: 'removeSheetSplitPane', sheetName: 'Report', expected }] as never)
  const before = await JSZip.loadAsync(source), after = await JSZip.loadAsync(saved)
  const xml = await after.file(SHEET)!.async('text')
  expect(xml).not.toMatch(/<pane\b|pane="/)
  expect(xml).toContain('<sheetView tabSelected="1" zoomScale="120" workbookViewId="0">')
  for (const name of Object.keys(before.files).filter(name => name !== SHEET && !before.files[name]!.dir)) {
    expect(await after.file(name)!.async('uint8array')).toEqual(await before.file(name)!.async('uint8array'))
  }
  const sheet = (await readWorkbook(saved)).sheets[0]!
  expect(sheet.splitPane).toBeUndefined(); expect(sheet.freeze).toBeNull()

  const run = (op: object, bytes = source) => applyWorkbookOperations(bytes, [{ kind: 'removeSheetSplitPane', ...op }] as never)
  await expect(run({ sheetName: 'Report', expected: { ...expected, xSplitTwips: 2401 } })).rejects.toThrow(/identity_changed/)
  await expect(run({ sheetName: 'Report', expected }, saved)).rejects.toThrow(/split_pane_missing/)
  await expect(run({ sheetName: 'Missing', expected })).rejects.toThrow(/sheet_missing/)
  await expect(run({ sheetName: 'Report', expected, extra: 1 })).rejects.toThrow()
  await expect(run({ sheetName: 'Report', expected: { ...expected, topLeftCell: 'c5' } })).rejects.toThrow()
  // 冻结写回仍按 Excel 行为以冻结窗格替换拆分窗格。
  const frozen = await applyPageSetups(source, [{ sheetName: 'Report', frozenRows: 1, frozenColumns: 0 }])
  const frozenSheet = (await readWorkbook(frozen)).sheets[0]!
  expect(frozenSheet.freeze).toEqual({ frozenRows: 1, frozenColumns: 0 }); expect(frozenSheet.splitPane).toBeUndefined()
})
