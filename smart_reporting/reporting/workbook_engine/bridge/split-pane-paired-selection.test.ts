import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook } from '../packages/xlsx-engine/src/index'
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


it.each(['<selection pane="bottomRight" activeCell="C5" sqref="C5"></selection>', '<selection pane="bottomRight" activeCell="C5" sqref="C5"/>'])('removing split preserves unrelated selection after %s', async selection => {
  const unbound = '<selection activeCell="A1" sqref="A1"></selection>'
  const source = await withPane(SPLIT, selection + unbound)
  const before = (await readWorkbook(source)).sheets[0]!
  expect(before.splitPane).toEqual({xSplitTwips:2400,ySplitTwips:1200,topLeftCell:'C5'})
  const expected = {xSplitTwips:2400,ySplitTwips:1200,topLeftCell:'C5'}
  const saving = applyWorkbookOperations(source,[{kind:'removeSheetSplitPane',sheetName:'Report',expected}] as never)
  await expect(saving).resolves.toBeInstanceOf(Uint8Array)
  const saved = await saving
  const xml = await (await JSZip.loadAsync(saved)).file(SHEET)!.async('text')
  expect(xml).not.toMatch(/<pane\b|pane="/)
  expect(xml).toContain(unbound)
  expect(xml).toContain('zoomScale="120"')
  const beforeZip = await JSZip.loadAsync(source), afterZip = await JSZip.loadAsync(saved)
  for (const name of Object.keys(beforeZip.files).filter(name => name !== SHEET && !beforeZip.files[name]!.dir)) {
    expect(await afterZip.file(name)!.async('uint8array')).toEqual(await beforeZip.file(name)!.async('uint8array'))
  }
  expect((await readWorkbook(saved)).sheets[0]!.splitPane).toBeUndefined()
})
