import { expect, it } from 'vitest'
import { createBlankWorkbook, createBufferEntrySource } from '../packages/xlsx-engine/src/index'
import { applyWorkbookOperations } from './operations'

it('writes and clears standard editable ranges through the shared save protocol', async () => {
  const source = await createBlankWorkbook()
  const saved = await applyWorkbookOperations(source, [{ kind: 'setSheetEditableRanges', sheetName: 'Sheet1', ranges: [{ name: '录入', sqref: 'B2:C4' }] }])
  const xml = await (await createBufferEntrySource(saved)).readText('xl/worksheets/sheet1.xml')
  expect(xml).toContain('<protectedRange sqref="B2:C4" name="录入"/>')
  const cleared = await applyWorkbookOperations(saved, [{ kind: 'setSheetEditableRanges', sheetName: 'Sheet1', ranges: [] }])
  expect(await (await createBufferEntrySource(cleared)).readText('xl/worksheets/sheet1.xml')).not.toContain('<protectedRanges')
})

it('rejects malformed editable-range operations before writing', async () => {
  const bytes = await createBlankWorkbook()
  for (const ranges of [null, [{ name: '', sqref: 'A1' }], [{ name: 'x', sqref: 'A0' }], [{ name: 'x', sqref: 'A1', password: 'ignored' }]]) {
    await expect(applyWorkbookOperations(bytes, [{ kind: 'setSheetEditableRanges', sheetName: 'Sheet1', ranges }])).rejects.toThrow()
  }
})
