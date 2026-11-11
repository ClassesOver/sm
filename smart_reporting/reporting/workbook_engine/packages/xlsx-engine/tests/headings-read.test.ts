import { expect, it } from 'vitest'
import { applyPageSetups, createBlankWorkbook, readWorkbook } from '../src'

it('reads hidden row and column headings and restores the default through page setup', async () => {
  const source = await createBlankWorkbook()
  expect((await readWorkbook(source)).sheets[0]!.showHeadings).toBe(true)
  const hidden = await applyPageSetups(source, [{ sheetName: 'Sheet1', showHeadings: false }])
  expect((await readWorkbook(hidden)).sheets[0]!.showHeadings).toBe(false)
  const shown = await applyPageSetups(hidden, [{ sheetName: 'Sheet1', showHeadings: true }])
  expect((await readWorkbook(shown)).sheets[0]!.showHeadings).toBe(true)
})
