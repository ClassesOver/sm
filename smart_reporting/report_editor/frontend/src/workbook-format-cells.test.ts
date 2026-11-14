import { expect, it } from 'vitest'
import { parseStylesheet } from '@sheets-web/xlsx-engine/style-read'
import { fromUniverStyle, logicalStyleOf, toUniverStyle } from './workbook-vendor/core/style-map'

it('reads explicit protection flags for the Protection tab without assuming defaults for explicit false', () => {
  const styles = parseStylesheet('<styleSheet><cellXfs count="2"><xf/><xf applyProtection="1"><protection locked="0" hidden="1"/></xf></cellXfs></styleSheet>')
  expect(styles.cellXfs[1]).toMatchObject({ protection: { locked: false, hidden: true } })
})
it('keeps distributed alignment distinct from justified alignment in import and save projection', () => {
  const styles = parseStylesheet('<styleSheet><cellXfs count="1"><xf><alignment horizontal="distributed"/></xf></cellXfs></styleSheet>')
  const logical = logicalStyleOf(styles, styles.cellXfs[0], undefined)!
  expect(logical.hAlign).toBe('distributed')
  expect(toUniverStyle(logical).ht).toBe(6)
  expect(fromUniverStyle({ ht: 6 }).hAlign).toBe('distributed')
})

import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { formatCellsOperation, selectedFormatCellsDraft, validateFormatCellsTarget, validateFormatCellsBudget, type FormatCellsTarget } from './workbook-format-cells'
import { formatCellsCommands } from './vendor/genoffice-sheets-format/format-cells'
import { captureNumberFormatTarget, type FormatWorkbook } from './workbook-format'
import { NativeDraft } from './native-draft'

function target(styles = [{ fs: 11, bl: 1 }, { fs: 12, bl: 0 }]) {
  const core = {}, range = { getRow: () => 0, getColumn: () => 0, getHeight: () => styles.length, getWidth: () => 1, setNumberFormat() {} }
  const sheet = { getSheetId: () => 'sheet-0', getSheetName: () => 'Sheet1', getSelection: () => ({ getActiveRange: () => range }), getRange: (row: number) => ({ getCellStyleData: () => styles[row] }) }
  const workbook: FormatWorkbook = { getWorkbook: () => core, getActiveSheet: () => sheet, getSheetBySheetId: () => sheet }
  return { target: captureNumberFormatTarget(workbook)!, workbook }
}
it('aggregates independently and echoes actual saved protection flags, with untouched mixed fields emitting nothing', async () => {
  const bytes = await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 0, cell: { value: 7 }, writeValue: true, style: { protectionLocked: false, protectionHidden: true } }])
  const model = await readWorkbook(bytes)
  const draft = selectedFormatCellsDraft(target().target, model)
  expect(draft).toMatchObject({ size: '', bold: '', locked: '', hidden: '' })
  expect(formatCellsCommands(draft, draft)).toEqual([])
  const single = selectedFormatCellsDraft(target([{ fs: 11, bl: 1 }]).target, model)
  expect(single).toMatchObject({ locked: 'off', hidden: 'on', size: '11', bold: 'on' })
  expect(formatCellsCommands(draft, { ...draft, noFill: true })).toEqual(['fill:none'])
})
it('rejects invalid later commands before any effect, unknown commands, stale targets and over-budget drafts', () => {
  const f = target()
  for (const commands of [ ['bold:on', 'font-size:999'], ['fill:#123456', 'indent:-1'], ['format:[invalid]0'], ['border:all:#xxxxxx:thin'], ['cellprot:locked-off:typo'], ['bold:maybe'], ['unknown:on'] ]) expect(() => formatCellsOperation(f.target, commands)).toThrow()
  expect(formatCellsOperation(f.target, [])).toEqual({ kind: 'applyCellEdits', edits: [] })
  expect(() => validateFormatCellsTarget(f.target, { ...f.workbook, getWorkbook: () => ({}) }, true)).toThrow('原选区')
  expect(() => validateFormatCellsTarget(f.target, f.workbook, false)).toThrow('不可编辑')
  expect(() => validateFormatCellsBudget(Array.from({ length: 501 }, () => ({ kind: 'applyCellEdits', edits: [] })))).toThrow('预算')
})
it('writes a complete six-tab batch through the existing package writer with values, formulas and neighbours intact', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 12.3 }, style: { italic: true, fillColor: '#ffff00' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 24.6, formula: '=A1*2' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: '邻接' }, style: { bold: true, fontColor: '#123456' } },
  ])
  const operation = formatCellsOperation(target().target, ['format:0.000', 'align:distributed', 'valign:middle', 'wrap:on', 'rotate:-45', 'indent:2', 'font-family:Arial', 'font-size:16', 'bold:on', 'italic:off', 'underline:on', 'strike:on', 'font-color:#c00000', 'fill:none', 'border:outer:#0070c0:double', 'cellprot:locked-off:hidden-on'])
  const bytes = await applyWorkbookOperations(source, [operation]), model = await readWorkbook(bytes)
  const cell = model.sheets[0]!.cells.A1!, formula = model.sheets[0]!.cells.A2!
  expect(cell.value).toBe(12.3); expect(formula.formula).toBe('=A1*2')
  const style = model.styles.cellXfs[cell.styleIndex!]!, logical = logicalStyleOf(model.styles, style, model.themePalette)!
  expect(logical).toMatchObject({ hAlign: 'distributed', vAlign: 'middle', wrap: true, textRotation: 135, indent: 2, fontSize: 16, fontFamily: 'Arial', bold: true, underline: true, strikethrough: true, fontColor: '#C00000', numberFormat: '0.000', borderTop: { style: 'double', color: '#0070C0' } })
  expect(style.protection).toEqual({ locked: false, hidden: true })
  expect(logical.fillColor).toBeUndefined(); expect(logical.italic).toBeUndefined()
  const before = await readWorkbook(source)
  expect(model.sheets[0]!.cells.B1).toEqual(before.sheets[0]!.cells.B1)
  expect(operation.edits.every(edit => edit.writeValue === false)).toBe(true)
})
it('keeps outer borders at the rectangle edge, and explicit none clears all edges', () => {
  const t = { ...target().target, width: 2 } as FormatCellsTarget
  const outer = formatCellsOperation(t, ['border:outer:#000000:thin'])
  expect(outer.edits[0]!.style).toEqual({ borderTop: { style: 'thin', color: '#000000' }, borderLeft: { style: 'thin', color: '#000000' } })
  expect(outer.edits[3]!.style).toEqual({ borderBottom: { style: 'thin', color: '#000000' }, borderRight: { style: 'thin', color: '#000000' } })
  expect(formatCellsOperation(t, ['border:none:#000000:thin']).edits[0]!.style).toEqual({ borderTop: null, borderBottom: null, borderLeft: null, borderRight: null })
})
it('uses one draft history entry for the combined batch and recovers it after refresh', async () => {
  const memory = new Map<string, string>(), storage = { getItem: (key: string) => memory.get(key) ?? null, setItem: (key: string, value: string) => { memory.set(key, value) }, removeItem: (key: string) => { memory.delete(key) } }
  const identity = { documentId: 'format-cells', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
  const draft = new NativeDraft(identity, storage), op = formatCellsOperation(target().target, ['bold:on', 'cellprot:locked-off:hidden-on'])
  draft.setOperations([op]); draft.undo(); expect(draft.operations).toEqual([])
  draft.redo(); expect(new NativeDraft(identity, storage).operations).toEqual([op])
})
