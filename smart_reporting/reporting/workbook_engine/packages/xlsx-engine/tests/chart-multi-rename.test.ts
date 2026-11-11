import { expect, it } from 'vitest'
import { applySheetEdits, createBlankWorkbook } from '../src'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

it('composes multiple sheet renames in the same chart without losing earlier updates', async () => {
  const base = await applySheetEdits(await createBlankWorkbook(), { renames: [{ sheetName: 'Sheet1', newName: 'Source' }], additions: [{ name: 'Other' }], removals: [], order: ['Source', 'Other'] })
  const path = 'xl/charts/chart1.xml'
  const chart = '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:f>Source!A1</c:f><c:f>Other!B1</c:f><c:ext>untouched</c:ext></c:chartSpace>'
  const input = (await assemblePackage(base, { replaced: new Map(), added: new Map([[path, chart]]), addedBinary: new Map(), removedEntries: [], addedEntries: [path], touchedEntries: [path] })).buffer
  const changed = await applySheetEdits(input, { renames: [{ sheetName: 'Source', newName: 'Data' }, { sheetName: 'Other', newName: 'View' }], additions: [], removals: [], order: ['Data', 'View'] })
  const source = await createBufferEntrySource(changed), before = await createBufferEntrySource(input)
  expect(await source.readText(path)).toBe(chart.replace('Source!A1', 'Data!A1').replace('Other!B1', 'View!B1'))
  for (const survivor of ['xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml', 'xl/styles.xml']) {
    expect(await source.readText(survivor)).toBe(await before.readText(survivor))
  }
})
