import { describe, expect, it } from 'vitest'

import {
  applyCellEdits, applyRowColumnOps, applyTableAdditions, applySheetNotes, createBlankWorkbook,
  readWorkbook, type SheetFilterColumn,
} from '../src'
import { applySheetFilter, type SheetFilterState } from '../src/filters'
import { readSheetFilter } from '../src/filter-read'
import { createBufferEntrySource } from '../src/zip'

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

async function dataWorkbook(): Promise<Uint8Array> {
  const bytes = await createBlankWorkbook()
  return applyCellEdits(bytes, [
    ...['Name', 'Qty', 'Note'].map((value, column) => ({
      sheetName: 'Sheet1', row: 0, column, writeValue: true, cell: { value },
    })),
    ...Array.from({ length: 6 }, (_, index) => ({
      sheetName: 'Sheet1', row: index + 1, column: 0, writeValue: true,
      cell: { value: index === 2 ? null : `item${index + 1}` },
    })),
    ...Array.from({ length: 6 }, (_, index) => ({
      sheetName: 'Sheet1', row: index + 1, column: 1, writeValue: true,
      cell: { value: index + 1 },
    })),
  ])
}

const setRange = { startRow: 0, endRow: 6, startColumn: 0, endColumn: 2 }

describe('sheet autoFilter write', () => {
  it('sets the element after sheetData with value, blank and custom criteria; the model reads it back', async () => {
    const bytes = await dataWorkbook()
    const columns: SheetFilterColumn[] = [
      { colId: 0, values: ['item1', 'item2'], blank: true },
      { colId: 1, customs: { and: true, filters: [{ val: 5, operator: 'greaterThanOrEqual' }, { val: 3, operator: 'lessThan' }] } },
    ]
    const filtered = await applySheetFilter(bytes, 'Sheet1', {
      filter: { range: setRange, columns },
      hiddenRows: [2, 3],
    })
    const xml = await partOf(filtered, 'xl/worksheets/sheet1.xml')
    const at = xml.indexOf('<autoFilter')
    expect(at).toBeGreaterThan(xml.indexOf('</sheetData>'))
    expect(xml.slice(at)).toContain('<filterColumn colId="0"><filters blank="1"><filter val="item1"/><filter val="item2"/></filters></filterColumn>')
    expect(xml.slice(at)).toContain('<filterColumn colId="1"><customFilters and="1"><customFilter operator="greaterThanOrEqual" val="5"/><customFilter operator="lessThan" val="3"/></customFilters></filterColumn>')
    // Declarative visibility: rows 3/4 hidden, the header row untouched.
    expect(xml).toMatch(/<row r="3"[^>]*hidden="1"/)
    expect(xml).toMatch(/<row r="4"[^>]*hidden="1"/)
    expect(xml).not.toMatch(/<row r="1"[^>]*hidden="1"/)
    const model = (await readWorkbook(filtered)).sheets[0]!.filter!
    expect(model.readOnlyReason).toBeUndefined()
    expect(model.range).toEqual(setRange)
    // OOXML attributes are text: numeric custom values read back as strings.
    expect(model.columns).toEqual([
      { colId: 0, values: ['item1', 'item2'], blank: true },
      { colId: 1, customs: { and: true, filters: [{ val: '5', operator: 'greaterThanOrEqual' }, { val: '3', operator: 'lessThan' }] } },
    ])
  })

  it('replaces an existing element in place and un-hides rows dropped from hiddenRows', async () => {
    const bytes = await dataWorkbook()
    const first = await applySheetFilter(bytes, 'Sheet1', {
      filter: { range: setRange, columns: [{ colId: 0, values: ['item1'] }] },
      hiddenRows: [2],
    })
    const second = await applySheetFilter(first, 'Sheet1', {
      filter: { range: setRange, columns: [{ colId: 2, values: ['note'] }] },
      hiddenRows: [],
    })
    const xml = await partOf(second, 'xl/worksheets/sheet1.xml')
    expect((xml.match(/<autoFilter\b/g) ?? []).length).toBe(1)
    expect(xml).toContain('<filterColumn colId="2">')
    expect(xml).not.toContain('<filterColumn colId="0">')
    expect(xml).not.toContain('hidden="1"')
  })

  it('clears the element; hidden rows can be declared in the same snapshot', async () => {
    const bytes = await dataWorkbook()
    const filtered = await applySheetFilter(bytes, 'Sheet1', {
      filter: { range: setRange, columns: [{ colId: 0, values: ['item1'] }] },
      hiddenRows: [2, 3],
    })
    const cleared = await applySheetFilter(filtered, 'Sheet1', {
      filter: null, hiddenRows: [], visibilityRange: setRange,
    })
    expect(await partOf(cleared, 'xl/worksheets/sheet1.xml')).not.toContain('<autoFilter')
    expect(await partOf(cleared, 'xl/worksheets/sheet1.xml')).not.toContain('hidden="1"')
    // Pure removal (no visibility fields) keeps row flags untouched.
    const refiltered = await applySheetFilter(cleared, 'Sheet1', {
      filter: { range: setRange, columns: [] }, hiddenRows: [2],
    })
    expect(await partOf(refiltered, 'xl/worksheets/sheet1.xml')).toMatch(/<row r="3"[^>]*hidden="1"/)
    const stripped = await applySheetFilter(refiltered, 'Sheet1', { filter: null })
    expect(await partOf(stripped, 'xl/worksheets/sheet1.xml')).toMatch(/<row r="3"[^>]*hidden="1"/)
    expect(await partOf(stripped, 'xl/worksheets/sheet1.xml')).not.toContain('<autoFilter')
  })

  it('preserves notes and non-target parts byte-for-byte in both directions', async () => {
    const bytes = await dataWorkbook()
    const withNotes = await applySheetNotes(bytes, 'Sheet1', [
      { row: 1, column: 1, author: 'Alice', text: '核对' },
    ])
    const commentsBefore = await partOf(withNotes, 'xl/comments1.xml')
    const filtered = await applySheetFilter(withNotes, 'Sheet1', {
      filter: { range: setRange, columns: [{ colId: 0, values: ['item1'] }] },
    })
    expect(await partOf(filtered, 'xl/comments1.xml')).toBe(commentsBefore)
    expect(await partOf(filtered, 'xl/worksheets/_rels/sheet1.xml.rels')).toContain('comments')
    const refiltered = await applySheetFilter(filtered, 'Sheet1', {
      filter: { range: setRange, columns: [{ colId: 0, values: ['item2'] }] },
    })
    expect(await partOf(refiltered, 'xl/comments1.xml')).toBe(commentsBefore)
    const notesAfter = (await readWorkbook(refiltered)).sheets[0]!.notes!
    expect(notesAfter.readOnlyReason).toBeUndefined()
    expect(notesAfter.notes).toEqual([{ row: 1, column: 1, author: 'Alice', text: '核对' }])
  })

  it('rejects contradictory snapshots whole and leaves the source bytes untouched', async () => {
    const bytes = await dataWorkbook()
    const before = bytes.slice()
    const column = (extra: Record<string, unknown>): SheetFilterState => ({
      filter: { range: setRange, columns: [{ colId: 0, ...extra }] },
    })
    const contradictions: SheetFilterState[] = [
      { filter: { range: setRange, columns: [{ colId: 3, values: ['x'] }] } },
      { filter: { range: setRange, columns: [{ colId: 0, values: ['a'] }, { colId: 0, values: ['b'] }] } },
      { filter: { range: setRange, columns: [{ colId: 0 }] } },
      column({ customs: { filters: [{ val: 'a' }, { val: 'b' }, { val: 'c' }] } }),
      column({ customs: { filters: [{ val: 'a', operator: 'beginsWith' }] } }),
      { filter: { range: setRange, columns: [{ colId: 0, values: ['x'] }] }, hiddenRows: [7] },
      { filter: null, hiddenRows: [1] },
    ]
    for (const state of contradictions) {
      await expect(applySheetFilter(bytes, 'Sheet1', state)).rejects.toThrow(/筛选|隐藏/)
    }
    expect(bytes).toEqual(before)
    await expect(applySheetFilter(bytes, 'Missing', { filter: null })).rejects.toThrow('不存在')
  })

  it('writes date-group buckets alongside values and reads them back', async () => {
    const bytes = await dataWorkbook()
    const filtered = await applySheetFilter(bytes, 'Sheet1', {
      filter: {
        range: setRange,
        columns: [
          { colId: 0, values: ['item1'], dateGroups: [{ year: 2024, month: 1, day: 15, dateTimeGrouping: 'day' }] },
          { colId: 2, dateGroups: [{ year: 2023, dateTimeGrouping: 'year' }, { year: 2024, month: 2, day: 3, hour: 8, minute: 30, dateTimeGrouping: 'minute' }] },
        ],
      },
    })
    const xml = await partOf(filtered, 'xl/worksheets/sheet1.xml')
    const at = xml.indexOf('<autoFilter')
    expect(xml.slice(at)).toContain(
      '<filterColumn colId="0"><filters><filter val="item1"/><dateGroupItem year="2024" month="1" day="15" dateTimeGrouping="day"/></filters></filterColumn>',
    )
    expect(xml.slice(at)).toContain(
      '<filterColumn colId="2"><filters><dateGroupItem year="2023" dateTimeGrouping="year"/><dateGroupItem year="2024" month="2" day="3" hour="8" minute="30" dateTimeGrouping="minute"/></filters></filterColumn>',
    )
    const model = (await readWorkbook(filtered)).sheets[0]!.filter!
    expect(model.readOnlyReason).toBeUndefined()
    expect(model.columns).toEqual([
      { colId: 0, values: ['item1'], dateGroups: [{ year: 2024, month: 1, day: 15, dateTimeGrouping: 'day' }] },
      { colId: 2, dateGroups: [{ year: 2023, dateTimeGrouping: 'year' }, { year: 2024, month: 2, day: 3, hour: 8, minute: 30, dateTimeGrouping: 'minute' }] },
    ])
  })

  it('rejects illegal date-group combinations whole and leaves the source bytes untouched', async () => {
    const bytes = await dataWorkbook()
    const before = bytes.slice()
    const groups = [{ year: 2024, month: 1, day: 15, dateTimeGrouping: 'day' as const }]
    const columns: SheetFilterColumn[][] = [
      [{ colId: 0, dateGroups: groups, customs: { filters: [{ val: '5' }] } }],
      [{ colId: 0, dateGroups: [{ year: 2024, month: 13, dateTimeGrouping: 'month' }] }],
      [{ colId: 0, dateGroups: [{ year: 2024, dateTimeGrouping: 'day' }] }],
      [{ colId: 0, dateGroups: [{ year: 2024, month: 1, day: 1, hour: 1, dateTimeGrouping: 'month' }] }],
      [{ colId: 0, dateGroups: [{ year: 2024, month: 1, minute: 3, dateTimeGrouping: 'month' }] }],
      [{ colId: 0, dateGroups: [] }],
      [{ colId: 0, dateGroups: [{ year: 2024, month: 1, dateTimeGrouping: 'decade' as never }] }],
    ]
    for (const illegal of columns) {
      await expect(applySheetFilter(bytes, 'Sheet1', {
        filter: { range: setRange, columns: illegal },
      })).rejects.toThrow(/日期分组/)
    }
    expect(bytes).toEqual(before)
  })

  it('refuses to overwrite a filter carrying criteria this build cannot represent; removal stays allowed', async () => {
    const bytes = await dataWorkbook()
    const source = await createBufferEntrySource(bytes)
    const xml = await source.readText('xl/worksheets/sheet1.xml')
    const planted = await assembleBuffer(bytes, 'xl/worksheets/sheet1.xml',
      xml.replace('</sheetData>', '</sheetData><autoFilter ref="A1:C7"><filterColumn colId="0"><colorFilter dxfId="0"/></filterColumn></autoFilter>'))
    const before = planted.slice()
    await expect(applySheetFilter(planted, 'Sheet1', {
      filter: { range: setRange, columns: [{ colId: 0, values: ['x'] }] },
    })).rejects.toThrow('颜色')
    expect(planted).toEqual(before)
    expect((await readWorkbook(planted)).sheets[0]!.filter!.readOnlyReason).toContain('颜色')
    const cleared = await applySheetFilter(planted, 'Sheet1', { filter: null })
    expect(await partOf(cleared, 'xl/worksheets/sheet1.xml')).not.toContain('<autoFilter')
  })

  it('rejects filter ranges overlapping an Excel table', async () => {
    const bytes = await dataWorkbook()
    const withTable = await applyTableAdditions(bytes, [{
      worksheetSheetName: 'Sheet1', name: 'Inventory',
      area: { startRow: 0, startColumn: 0, endRow: 6, endColumn: 1 },
      columnNames: ['Name', 'Qty'], style: 'TableStyleMedium2', bandedRows: true,
    }])
    await expect(applySheetFilter(withTable, 'Sheet1', {
      filter: { range: { startRow: 0, endRow: 6, startColumn: 1, endColumn: 2 }, columns: [] },
    })).rejects.toThrow('表格')
    // A range outside the table still writes.
    const outside = await applySheetFilter(withTable, 'Sheet1', {
      filter: { range: { startRow: 8, endRow: 12, startColumn: 0, endColumn: 1 }, columns: [] },
    })
    expect((await readWorkbook(outside)).sheets[0]!.filter!.range).toEqual(
      { startRow: 8, endRow: 12, startColumn: 0, endColumn: 1 },
    )
  })
})

describe('autoFilter reads', () => {
  it('reads values/customs/date-groups and marks color/icon/top10/dynamic criteria readOnly without dropping the range', () => {
    const xml = '<worksheet><sheetData/></worksheet>'.replace(
      '</worksheet>',
      '<autoFilter ref="B2:E10">' +
      '<filterColumn colId="0"><filters blank="1"><filter val="a&amp;b"/><dateGroupItem year="2024" month="1" dateTimeGrouping="month"/></filters></filterColumn>' +
      '<filterColumn colId="1"><filters><dateGroupItem year="2024" month="1" day="2" hour="3" minute="4" second="5" dateTimeGrouping="second"/><dateGroupItem year="2023" dateTimeGrouping="year"/></filters></filterColumn>' +
      '<filterColumn colId="2"><customFilters><customFilter val="5"/></customFilters></filterColumn>' +
      '<filterColumn colId="3"><top10 val="3"/></filterColumn>' +
      '</autoFilter></worksheet>',
    )
    const model = readSheetFilter(xml)!
    expect(model.range).toEqual({ startRow: 1, endRow: 9, startColumn: 1, endColumn: 4 })
    expect(model.readOnlyReason).toContain('前十')
    expect(model.columns).toEqual([
      { colId: 0, values: ['a&b'], blank: true, dateGroups: [{ year: 2024, month: 1, dateTimeGrouping: 'month' }] },
      {
        colId: 1,
        dateGroups: [
          { year: 2024, month: 1, day: 2, hour: 3, minute: 4, second: 5, dateTimeGrouping: 'second' },
          { year: 2023, dateTimeGrouping: 'year' },
        ],
      },
      { colId: 2, customs: { filters: [{ val: '5' }] } },
    ])
  })

  it('marks a malformed date-group column readOnly instead of dropping it', () => {
    const xml = '<worksheet><sheetData/></worksheet>'.replace(
      '</worksheet>',
      '<autoFilter ref="A1:C5">' +
      '<filterColumn colId="0"><filters><dateGroupItem year="2024" month="13" dateTimeGrouping="month"/></filters></filterColumn>' +
      '<filterColumn colId="1"><filters><dateGroupItem month="1" dateTimeGrouping="month"/></filters></filterColumn>' +
      '<filterColumn colId="2"><dateGroupItem year="2024" dateTimeGrouping="year"/></filterColumn>' +
      '</autoFilter></worksheet>',
    )
    const model = readSheetFilter(xml)!
    expect(model.readOnlyReason).toContain('日期分组')
    expect(model.columns).toEqual([])
  })

  it('ignores customSheetViews copies and prefers the first sheet-level element', () => {
    const xml = '<worksheet><sheetData/></worksheet>'.replace(
      '</worksheet>',
      '<autoFilter ref="A1:B5"/>' +
      '<customSheetViews><customSheetView><autoFilter ref="Z9:Z99"/></customSheetView></customSheetViews>' +
      '</worksheet>',
    )
    expect(readSheetFilter(xml)!.range).toEqual({ startRow: 0, endRow: 4, startColumn: 0, endColumn: 1 })
    expect(readSheetFilter('<worksheet><sheetData/></worksheet>')).toBeNull()
  })
})

describe('structural edits follow the filter', () => {
  const criteria: SheetFilterColumn[] = [
    { colId: 0, values: ['item1'] },
    { colId: 2, customs: { filters: [{ val: '7' }] } },
  ]

  it('column inserts inside the range grow the ref and shift colIds at/after the insertion', async () => {
    const bytes = await applySheetFilter(await dataWorkbook(), 'Sheet1', {
      filter: { range: setRange, columns: criteria },
    })
    const shifted = await applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'insert-cols', index: 1, count: 2 }])
    const model = (await readWorkbook(shifted)).sheets[0]!.filter!
    expect(model.range).toEqual({ startRow: 0, endRow: 6, startColumn: 0, endColumn: 4 })
    expect(model.columns).toEqual([
      { colId: 0, values: ['item1'] },
      { colId: 4, customs: { filters: [{ val: '7' }] } },
    ])
  })

  it('column deletes inside the range drop the deleted colIds and rebase the rest', async () => {
    const bytes = await applySheetFilter(await dataWorkbook(), 'Sheet1', {
      filter: { range: setRange, columns: criteria },
    })
    const shifted = await applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'remove-cols', index: 0, count: 2 }])
    const model = (await readWorkbook(shifted)).sheets[0]!.filter!
    // A1:C7 shrinks to A1:A7; the values column (A) dies, the custom column (C → A) rebases to 0.
    expect(model.range).toEqual({ startRow: 0, endRow: 6, startColumn: 0, endColumn: 0 })
    expect(model.columns).toEqual([{ colId: 0, customs: { filters: [{ val: '7' }] } }])
  })

  it('column deletes before the range shift only the ref; row inserts shift the ref and keep colIds', async () => {
    const bytes = await applySheetFilter(await dataWorkbook(), 'Sheet1', {
      filter: { range: setRange, columns: criteria },
    })
    const colShifted = await applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'insert-cols', index: 0, count: 1 }])
    expect((await readWorkbook(colShifted)).sheets[0]!.filter).toEqual({
      ref: 'B1:D7', range: { startRow: 0, endRow: 6, startColumn: 1, endColumn: 3 }, columns: criteria,
    })
    const rowShifted = await applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'insert-rows', index: 0, count: 3 }])
    expect((await readWorkbook(rowShifted)).sheets[0]!.filter).toEqual({
      ref: 'A4:C10', range: { startRow: 3, endRow: 9, startColumn: 0, endColumn: 2 }, columns: criteria,
    })
  })

  it('deleting every range row drops the element', async () => {
    const bytes = await applySheetFilter(await dataWorkbook(), 'Sheet1', {
      filter: { range: setRange, columns: criteria },
    })
    const shifted = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'remove-rows', index: 0, count: 7 },
    ])
    expect((await readWorkbook(shifted)).sheets[0]!.filter).toBeUndefined()
    expect(await partOf(shifted, 'xl/worksheets/sheet1.xml')).not.toContain('<autoFilter')
  })

  it('column shifts rebase date-group colIds and ride the buckets along verbatim', async () => {
    const bytes = await applySheetFilter(await dataWorkbook(), 'Sheet1', {
      filter: {
        range: setRange,
        columns: [{ colId: 1, dateGroups: [{ year: 2024, month: 1, dateTimeGrouping: 'month' }] }],
      },
    })
    const shifted = await applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'insert-cols', index: 1, count: 1 }])
    expect((await readWorkbook(shifted)).sheets[0]!.filter!.columns).toEqual([
      { colId: 2, dateGroups: [{ year: 2024, month: 1, dateTimeGrouping: 'month' }] },
    ])
  })
})

async function assembleBuffer(bytes: Uint8Array, path: string, xml: string): Promise<Uint8Array> {
  const { assemblePackage } = await import('../src/zip')
  return (await assemblePackage(bytes, {
    replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(),
    removedEntries: [], addedEntries: [], touchedEntries: [path],
  })).buffer
}
