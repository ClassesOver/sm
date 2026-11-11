import { expect, it } from 'vitest'
import { createBlankWorkbook } from '@sheets-web/xlsx-engine'
import { protectSheet, setSheetEditableRanges } from '@sheets-web/xlsx-engine/protection'
import { createEditableRangesPlan, editableRangeContains, protectedValueCommandContext, readWorkbookEditableRanges } from './workbook-editable-ranges'
import { assertProtectionRespected, planProtection, protectionBlockReason } from './workbook-protection'
import type { WorkbookModel } from '@sheets-web/xlsx-engine'

const input = [{ name: 'Input', sqref: 'B2:C4 E2:E4' }]
const range = { startRow: 1, endRow: 3, startColumn: 1, endColumn: 2 }
it('previews actual OOXML ranges and reads them after reopening without claiming protected range creation', async () => {
  const blank = await createBlankWorkbook(), plan = await createEditableRangesPlan(blank, 'Sheet1', input)
  expect(plan.operations).toEqual([{ kind: 'setSheetEditableRanges', sheetName: 'Sheet1', ranges: input }])
  const bytes = await setSheetEditableRanges(blank, 'Sheet1', input)
  expect((await readWorkbookEditableRanges(bytes)).get('Sheet1')).toEqual(input)
  await expect(createEditableRangesPlan(await protectSheet(bytes, 'Sheet1', true), 'Sheet1', [])).rejects.toThrow(/撤销/)
})
it('requires full coverage including unions and excludes restricted ranges', () => {
  expect(editableRangeContains(range, input)).toBe(true)
  expect(editableRangeContains({ ...range, endColumn: 4 }, input)).toBe(false)
  expect(editableRangeContains(range, [{ name: 'Top', sqref: 'B2:C2' }, { name: 'Bottom', sqref: 'B3:C4' }])).toBe(true)
  expect(editableRangeContains(range, input.map(item => ({ ...item, readonlyReason: '密码' })))).toBe(false)
})
it('checks all concrete value writes rather than trusting a smaller claimed range', () => {
  const native = { v: 'keyboard', f: null, t: undefined, p: null, si: null }
  expect(protectedValueCommandContext({ range, value: native }, undefined, input)).toBeDefined()
  expect(protectedValueCommandContext({ range, value: { ...native, f: '=1+1', v: null } }, undefined, input)).toBeDefined()
  expect(protectedValueCommandContext({ range, value: { ...native, p: { body: {} } } }, undefined, input)).toBeUndefined()
  expect(protectedValueCommandContext({ range, value: { ...native, si: 'shared' } }, undefined, input)).toBeUndefined()
  const mixed = { range, value: { ...native, s: { ff: 'Calibri', fs: 11, cl: { rgb: '#000000' } } } }
  expect(protectedValueCommandContext(mixed, undefined, input)?.safeValue).toEqual(native)
  expect(mixed.value.s).toEqual({ ff: 'Calibri', fs: 11, cl: { rgb: '#000000' } }) // 预检不更改原请求。
  expect(protectedValueCommandContext({ range, value: { s: { bl: 1 } } }, undefined, input)).toBeUndefined()
  expect(protectedValueCommandContext({ range, value: { v: 1 } }, undefined, input)).toBeDefined()
  expect(protectedValueCommandContext({ range, value: [[{ v: 1 }, { f: '=1+1' }], [{ v: null }, { v: 2 }], [{ v: 3 }, { t: 2, v: 4 }]] }, undefined, input)).toBeDefined()
  expect(protectedValueCommandContext({ range, value: { '1': { '1': { v: 1 } }, '10': { '10': { v: 2 } } } }, undefined, input)).toBeUndefined()
  expect(protectedValueCommandContext({ range, value: { v: 1, s: 'style' } }, undefined, input)?.safeValue).toEqual({ v: 1 })
  expect(protectedValueCommandContext({ range, value: { '1': { '1': { v: 1, p: {} } } } }, undefined, input)).toBeUndefined()
  expect(protectedValueCommandContext({ range, value: [] }, undefined, input)).toBeUndefined()
  expect(protectedValueCommandContext({ value: { v: 1 } }, undefined, input)).toBeUndefined()
  expect(protectionBlockReason('sheet.command.set-range-values', true, false, { range, ranges: input })).toBeUndefined()
  expect(protectionBlockReason('sheet.command.set-range-font-weight', true, false, { range, ranges: input })).toMatch(/受保护/)
})
it('save enforcement permits value edits only in original allowed areas and rejects styling or extension of permission', () => {
  const model = { sheets: [{ name: 'Sheet1', protection: { protected: true, hasPassword: false } }] } as unknown as WorkbookModel
  const plan = planProtection(model, new Map(), undefined, () => 'Sheet1', new Map([['Sheet1', input]]))
  const edit = { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 9 } }
  expect(() => assertProtectionRespected([{ kind: 'applyCellEdits', edits: [edit] }], plan, false)).not.toThrow()
  for (const edits of [[{ ...edit, column: 3 }], [{ ...edit, style: { bold: true } }], [{ ...edit, styleReset: true }], [{ ...edit, writeValue: false }]])
    expect(() => assertProtectionRespected([{ kind: 'applyCellEdits', edits }], plan, false)).toThrow(/受保护/)
  expect(() => assertProtectionRespected([{ kind: 'setSheetEditableRanges', sheetName: 'Sheet1', ranges: [] }], plan, false)).toThrow(/受保护/)
})
