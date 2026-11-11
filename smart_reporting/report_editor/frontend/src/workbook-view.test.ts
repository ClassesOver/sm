import { expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { withWorkbookView } from './workbook-view'

it('loads hidden headings without losing existing native header configuration', async () => {
  const data = { sheets: { first: { id: 'first', name: 'Sheet1', rowHeader: { width: 60 }, columnHeader: { height: 25 } } } }
  const model = await readWorkbook(await createBlankWorkbook())
  model.sheets[0]!.showHeadings = false
  withWorkbookView(data, model)
  expect(data.sheets.first.rowHeader).toEqual({ width: 60, hidden: 1 })
  expect(data.sheets.first.columnHeader).toEqual({ height: 25, hidden: 1 })
})

it('uses visible headings for source files that omit the view setting', async () => {
  const data = { sheets: { first: { id: 'first', name: 'Sheet1' } } }
  const model = await readWorkbook(await createBlankWorkbook())
  delete model.sheets[0]!.showHeadings
  const result = withWorkbookView(data, model)
  expect(result.sheets.first).toMatchObject({ rowHeader: { hidden: 0 }, columnHeader: { hidden: 0 } })
})
