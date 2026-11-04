import { describe, expect, it } from 'vitest'

import { createBlankWorkbook } from '../src/blank'
import { applyCellEdits } from '../src/workbook-write'
import { applySparklines, readSparklines, SparklineError } from '../src/sparklines'
import { readWorkbook } from '../src/workbook-read'
import { createBufferEntrySource, inventoryXlsx } from '../src/zip'

describe('sparklines (迷你图)', () => {
  it('writes and reads back line and column sparklines', async () => {
    const bytes = await createBlankWorkbook()
    const written = await applySparklines(bytes, 'Sheet1', [
      { kind: 'line', source: 'B2:F2', target: 'G2', markers: true },
      { kind: 'column', source: 'B3:F3', target: 'G3', color: '#FF0000' },
    ])
    const model = await readWorkbook(written)
    const specs = model.sheets[0]?.sparklines ?? []
    expect(specs).toHaveLength(2)
    expect(specs[0]).toMatchObject({ kind: 'line', source: 'B2:F2', target: 'G2', markers: true })
    expect(specs[1]).toMatchObject({ kind: 'column', source: 'B3:F3', target: 'G3', color: '#FF0000' })

    // untouched package entries stay byte-identical (only the worksheet part changes)
    const before = await inventoryXlsx(bytes)
    const after = await inventoryXlsx(written)
    const changed = after.filter(
      (entry, index) => before[index]?.path === entry.path && before[index]?.sha256 !== entry.sha256,
    )
    expect(changed.map((entry) => entry.path)).toEqual(['xl/worksheets/sheet1.xml'])
  })

  it('replaces the set on re-apply and clears with an empty list', async () => {
    const bytes = await createBlankWorkbook()
    const once = await applySparklines(bytes, 'Sheet1', [
      { kind: 'line', source: 'B2:F2', target: 'G2' },
    ])
    const twice = await applySparklines(once, 'Sheet1', [
      { kind: 'winLoss', source: 'B3:F3', target: 'G3', showAxis: true },
    ])
    expect(await readSparklinesOf(twice)).toEqual([
      // the default series color materializes into the x14 group
      { kind: 'winLoss', source: 'B3:F3', target: 'G3', color: '#376092', showAxis: true },
    ])
    const cleared = await applySparklines(twice, 'Sheet1', [])
    expect(await readSparklinesOf(cleared)).toEqual([])
    const xml = await worksheetXmlOf(cleared)
    expect(xml).not.toContain('sparkline')
  })

  it('survives cell edits, refuses shifts, and rejects invalid specs', async () => {
    const bytes = await createBlankWorkbook()
    const withSparks = await applySparklines(bytes, 'Sheet1', [
      { kind: 'line', source: 'B2:F2', target: 'G2' },
    ])
    const edited = await applyCellEdits(withSparks, [
      { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 5 } },
    ])
    expect(await readSparklinesOf(edited)).toHaveLength(1)
    // structural ops refuse to shift around sparklines (fail-closed: the x14
    // references would silently desync otherwise)
    const { applyRowColumnOps } = await import('../src/sheet-ops')
    await expect(
      applyRowColumnOps(edited, 'Sheet1', [{ kind: 'insert-rows', index: 0, count: 1 }]),
    ).rejects.toThrow('cannot shift around')
    await expect(
      applySparklines(bytes, 'Sheet1', [{ kind: 'line', source: 'A1:ZZ1000', target: 'G2' }]),
    ).rejects.toThrow(SparklineError)
    await expect(
      applySparklines(bytes, 'Sheet1', [{ kind: 'line', source: 'B2:F2', target: 'G2:G3' }]),
    ).rejects.toThrow('单个单元格')
    await expect(
      applySparklines(bytes, 'Sheet1', [
        { kind: 'line', source: 'B2:F2', target: 'G2' },
        { kind: 'line', source: 'B3:F3', target: 'G2' },
      ]),
    ).rejects.toThrow('重复')
  })
})

const worksheetXmlOf = async (bytes: Uint8Array): Promise<string> =>
  (await createBufferEntrySource(bytes)).readText('xl/worksheets/sheet1.xml')

const readSparklinesOf = async (bytes: Uint8Array): Promise<unknown[]> =>
  readSparklines(await worksheetXmlOf(bytes))
