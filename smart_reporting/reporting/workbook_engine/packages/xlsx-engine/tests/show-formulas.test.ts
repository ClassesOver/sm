import { expect, it } from 'vitest'

import { applyPageSetups, createBlankWorkbook, readWorkbook } from '../src'

it('reads sheetView showFormulas written by applyPageSetups and clears it', async () => {
  const blank = await createBlankWorkbook()
  expect((await readWorkbook(blank)).sheets[0]!.showFormulas).toBeUndefined()
  const shown = await applyPageSetups(blank, [{ sheetName: 'Sheet1', showFormulas: true }])
  expect((await readWorkbook(shown)).sheets[0]!.showFormulas).toBe(true)
  const hidden = await applyPageSetups(shown, [{ sheetName: 'Sheet1', showFormulas: false }])
  expect((await readWorkbook(hidden)).sheets[0]!.showFormulas).toBeUndefined()
})
