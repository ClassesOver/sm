import { expect, it } from 'vitest'
import { applyCellEdits, applySheetEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/zip'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { buildWorkbookPrintJob, printInputsForScope } from './workbook-print-preview'

async function fixture() {
  const bytes = await applyCellEdits(await applySheetEdits(await createBlankWorkbook(), {
    renames: [], additions: [{ name: 'Hidden' }, { name: 'VeryHidden' }, { name: 'Other' }], removals: [], order: ['Sheet1', 'Hidden', 'VeryHidden', 'Other'],
  }), ['Sheet1', 'Hidden', 'VeryHidden', 'Other'].map(sheetName => ({ sheetName, row: 0, column: 0, writeValue: true, cell: { value: `${sheetName} content` } })))
  const entries = await createBufferEntrySource(bytes), path = 'xl/workbook.xml'
  const xml = (await entries.readText(path)).replace('name="Hidden"', 'name="Hidden" state="hidden"').replace('name="VeryHidden"', 'name="VeryHidden" state="veryHidden"')
  return (await assemblePackage(bytes, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
}

it('carries file hidden/veryHidden states through the reader and excludes them from actual whole-workbook print HTML', async () => {
  const model = await readWorkbook(await fixture())
  expect(model.sheets[1]).toHaveProperty('hidden', true); expect(model.sheets[2]).toHaveProperty('hidden', true)
  const snapshot = buildWorkbookData(model, 'book', 'Book')
  const inputs = printInputsForScope(snapshot, model, 'workbook', 'sheet-0', null)
  expect(inputs.map(input => input.source.name)).toEqual(['Sheet1', 'Other'])
  const job = buildWorkbookPrintJob(inputs)!
  expect(job.pageCount).toBe(2); expect(job.html).toContain('Other content')
  expect(job.html).not.toContain('Hidden content'); expect(job.html).not.toContain('VeryHidden content')
})

it('projects the native hidden flag while leaving visible sheets at the existing default', async () => {
  const model = await readWorkbook(await fixture())
  const snapshot = buildWorkbookData({ ...model, sheets: model.sheets.map(sheet => ({ ...sheet, hidden: ['Hidden', 'VeryHidden'].includes(sheet.name) })) }, 'book', 'Book')
  expect(snapshot.sheets['sheet-1']).toHaveProperty('hidden', 1)
  expect(snapshot.sheets['sheet-2']).toHaveProperty('hidden', 1)
  expect(snapshot.sheets['sheet-0']).not.toHaveProperty('hidden')
  expect(snapshot.sheets['sheet-3']).not.toHaveProperty('hidden')
})
