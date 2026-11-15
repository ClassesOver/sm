import { describe, expect, it } from 'vitest'
import { applyStructuralOp } from '../src/structural'

const cell = (address: string, row: number) => `<worksheet><sheetData><row r="${row}"><c r="${address}" t="inlineStr"><is><t>retain</t></is></c></row></sheetData></worksheet>`

describe('structural shifts preserve Excel grid bounds', () => {
  it('rejects pushing a populated final row out of the file grid', () => {
    expect(() => applyStructuralOp(cell('A1048576', 1048576), {kind:'insert-rows',index:0,count:1}, 'Source')).toThrow(/worksheet bounds/)
  })
  it('rejects pushing a populated final column out of the file grid', () => {
    expect(() => applyStructuralOp(cell('XFD1', 1), {kind:'insert-cols',index:0,count:1}, 'Source')).toThrow(/worksheet bounds/)
  })
  it.each([
    ['A1048576:B1048576', {kind:'insert-rows' as const,index:0,count:1}],
    ['XFC1:XFD1', {kind:'insert-cols' as const,index:0,count:1}],
  ])('rejects overflowing a merge even with no stored endpoint cell: %s', (ref, op) => {
    const xml = `<worksheet><sheetData></sheetData><mergeCells count="1"><mergeCell ref="${ref}"/></mergeCells></worksheet>`
    expect(() => applyStructuralOp(xml, op, 'Source')).toThrow(/worksheet bounds/)
  })
  it('allows movement to the last valid row and column and deletion at that edge', () => {
    const atRow = applyStructuralOp(cell('A1048575',1048575), {kind:'insert-rows',index:0,count:1}, 'Source')
    expect(atRow).toContain('r="A1048576"')
    const atCol = applyStructuralOp(cell('XFC1',1), {kind:'insert-cols',index:0,count:1}, 'Source')
    expect(atCol).toContain('r="XFD1"')
    const removed = applyStructuralOp(atCol, {kind:'remove-cols',index:16383,count:1}, 'Source')
    expect(removed).not.toContain('<c ')
  })
})
