// Directed tests for the web-equivalent File ▸ Print subset (fixed source
// f8c17004: native File menu → openPrintPreviewHost → PrintDialog over
// print-paginate/print-html) and the File-tab undo/redo routing to the live
// Univer undo/redo stacks.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TextDecoration } from '@univerjs/core'
import {
  bandIndices, buildSheetPrintHtml, paperSizeInches, parsePrintAreas, parsePrintRange,
  parsePrintTitles, planSheetPrint, printSourceFromSnapshotSheet,
  type SheetPrintSetup, type SheetPrintSource,
} from './workbook-print'

afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })

const SETUP: SheetPrintSetup = {
  orientation: 'portrait', paperSize: 9, scale: 100, fitToPage: false, fitToWidth: 0, fitToHeight: 0,
  margins: { left: 0.7, right: 0.7, top: 0.75, bottom: 0.75 },
  printGridlines: false, printHeadings: false, printArea: null, printTitles: null,
  rowBreaks: [], colBreaks: [],
}

const sourceOf = (cells: SheetPrintSource['cells'], extra: Partial<SheetPrintSource> = {}): SheetPrintSource => ({
  name: 'Sheet', cells, merges: [], columnWidths: {}, rowHeights: {}, hiddenColumns: new Set(), hiddenRows: new Set(), ...extra,
})

describe('print page setup resolution', () => {
  it('resolves OOXML paper codes with orientation and falls back to A4', () => {
    expect(paperSizeInches(9, 'portrait')).toEqual({ widthIn: 8.27, heightIn: 11.69 })
    expect(paperSizeInches(9, 'landscape')).toEqual({ widthIn: 11.69, heightIn: 8.27 })
    expect(paperSizeInches(1, 'portrait')).toEqual({ widthIn: 8.5, heightIn: 11 })
    expect(paperSizeInches(999, 'portrait')).toEqual({ widthIn: 8.27, heightIn: 11.69 })
  })

  it('parses print areas and title rows/columns', () => {
    expect(parsePrintRange('$A$1:$B$4')).toEqual({ startRow: 0, endRow: 3, startColumn: 0, endColumn: 1 })
    expect(parsePrintRange('B4:A1')).toEqual({ startRow: 0, endRow: 3, startColumn: 0, endColumn: 1 })
    expect(parsePrintRange('nonsense')).toBeNull()
    expect(parsePrintAreas('A1:B2, C3:D4')).toHaveLength(2)
    expect(parsePrintTitles('1:2')).toEqual({ rows: { start: 0, end: 1 }, columns: null })
    expect(parsePrintTitles('A:B')).toEqual({ rows: null, columns: { start: 0, end: 1 } })
    expect(parsePrintTitles('1:2,A:B')).toEqual({ rows: { start: 0, end: 1 }, columns: { start: 0, end: 1 } })
  })

  it('keeps snapshot hidden flags as zero print size', () => {
    const source = printSourceFromSnapshotSheet({
      name: 'Sheet',
      cellData: { 0: { 0: { v: 'a' } }, 1: { 0: { v: 'b' } } },
      // Univer 0.25.1 快照键：w/h 像素，hd=1 隐藏。
      columnData: { 1: { hd: 1 }, 3: { w: 90 } },
      rowData: { 2: { h: 40, hd: 1 }, 4: { h: 30, hd: 0 } },
    })
    expect(source.hiddenColumns.has(1)).toBe(true)
    expect(source.hiddenRows.has(2)).toBe(true)
    expect(source.hiddenRows.has(4)).toBe(false)
    expect(source.columnWidths[3]).toBe(90)
    expect(source.rowHeights[2]).toBe(40)
    expect(printSourceFromSnapshotSheet(undefined).cells).toEqual({})
  })
})

describe('print pagination', () => {
  it('bands rows at page capacity without splitting a row', () => {
    const spans = bandIndices([0, 1, 2, 3], () => 30, 70, new Set())
    expect(spans).toEqual([{ start: 0, end: 1 }, { start: 2, end: 3 }])
  })

  it('ends a page at manual breaks', () => {
    const spans = bandIndices([0, 1, 2, 3], () => 10, 100, new Set([2]))
    expect(spans).toEqual([{ start: 0, end: 1 }, { start: 2, end: 3 }])
  })

  it('plans pages down-then-over with the print area clipped and titles repeated', () => {
    const source = sourceOf(
      { A1: { value: 't' }, A2: { value: 1 }, A3: { value: 2 }, A4: { value: 3 } },
      { columnWidths: { 0: 200, 1: 200, 2: 200 }, rowHeights: { 0: 20, 1: 20, 2: 20, 3: 20 } },
    )
    const plan = planSheetPrint(source, {
      ...SETUP,
      paperSize: 11, // A5 portrait: printable width ≈ (5.83 - 1.4) * 72 ≈ 319pt → two 150pt column bands
      printArea: 'A1:C4',
      printTitles: '1:1',
    })
    expect(plan).not.toBeNull()
    expect(plan!.titleRows).toEqual({ start: 0, end: 0 })
    const columnBands = new Set(plan!.pages.map(page => `${page.colStart}-${page.colEnd}`))
    expect(columnBands.size).toBeGreaterThan(1)
    expect(plan!.pages.every(page => page.rowStart >= 1)).toBe(true)
  })

  it('shrinks to fit with fit-to-page and never upscales', () => {
    const source = sourceOf(
      { A1: { value: 'x' } },
      { columnWidths: { 0: 1000 }, rowHeights: { 0: 20 } },
    )
    const plan = planSheetPrint(source, { ...SETUP, fitToPage: true, fitToWidth: 1, fitToHeight: 0 })
    expect(plan!.scale).toBeLessThan(100)
    expect(plan!.pages).toHaveLength(1)
  })

  it('returns null for empty content or oversized jobs', () => {
    expect(planSheetPrint(sourceOf({}), SETUP)).toBeNull()
    expect(planSheetPrint(sourceOf({ A1: { value: 1 } }), { ...SETUP, printArea: 'A1:GR300' })).toBeNull()
  })
})

describe('print document', () => {
  it('emits @page size, margins inset, gridline class and repeated title rows', () => {
    const source = sourceOf({ A1: { value: 'head' }, A2: { value: 'body' } })
    const html = buildSheetPrintHtml(source, { ...SETUP, printTitles: '1:1', printGridlines: true, printHeadings: true })
    expect(html).toContain('@page { size: 8.27in 11.69in; margin: 0; }')
    expect(html).toContain('left:0.7in;top:0.75in')
    expect(html).toContain('class="gridlines"')
    expect(html).toContain('>A</th>')
    expect(html!.match(/>head<\/td>/g)).toHaveLength(1)
    expect(html!.match(/style="height:/g)!.length).toBeGreaterThanOrEqual(2)
    expect(html).toContain('>head</td>')
    expect(html).toContain('>body</td>')
  })

  it('applies landscape paper swap and cell visual styles', () => {
    const source = sourceOf({ A1: { value: 'v', style: { bold: true, hAlign: 'center', fontSize: 14 } } })
    const html = buildSheetPrintHtml(source, { ...SETUP, orientation: 'landscape' })
    expect(html).toContain('@page { size: 11.69in 8.27in; margin: 0; }')
    expect(html).toContain('font-weight:700')
    expect(html).toContain('text-align:center')
    expect(html).toContain('font-size:14pt')
  })

  it('formats snapshot numbers and preserves independent underline and strike', () => {
    const source = printSourceFromSnapshotSheet({
      name: 'Live', cellData: { 0: { 0: { v: 1234.567, s: 'number' }, 1: { v: 'double', s: 'double' } } },
    }, {
      number: { n: { pattern: '#,##0.00' }, bl: 1 },
      double: { ul: { s: 1, t: TextDecoration.DOUBLE } },
    })
    const html = buildSheetPrintHtml(source, SETUP)!
    expect(html).toContain('>1,234.57</td>')
    expect(html).toContain('font-weight:700')
    expect(html).toContain('text-decoration-line:underline')
    expect(html).toContain('text-decoration-style:double')
    expect(html).not.toContain('line-through')
    const both = buildSheetPrintHtml(sourceOf({ A1: { value: 'both', style: {
      underline: true, underlineStyle: 'double', strikethrough: true,
    } } }), SETUP)!
    expect(both).toContain('text-decoration-line:underline line-through')
  })

  it('prints merged cells once and omits every covered cell', () => {
    const html = buildSheetPrintHtml(sourceOf({
      A1: { value: 'merged' }, B1: { value: 'covered-one' },
      A2: { value: 'covered-two' }, B2: { value: 'covered-three' },
    }, { merges: [{ startRow: 0, endRow: 1, startColumn: 0, endColumn: 1 }] }), SETUP)!
    const parsed = new DOMParser().parseFromString(html, 'text/html')
    expect(parsed.querySelectorAll('td')).toHaveLength(1)
    expect(parsed.querySelector('td')?.rowSpan).toBe(2)
    expect(parsed.querySelector('td')?.colSpan).toBe(2)
    expect(html).not.toContain('covered-')
  })

  it('omits hidden columns from body and repeated titles instead of printing their contents', () => {
    const source = sourceOf({ A1: { value: 'left' }, B1: { value: 'hidden-secret' }, C1: { value: 'right' } }, { hiddenColumns: new Set([1]) })
    for (const printTitles of [null, 'A:B']) {
      const html = buildSheetPrintHtml(source, { ...SETUP, printTitles, printHeadings: true })!
      expect(html).not.toContain('hidden-secret')
      expect(html).not.toContain('>B</th>')
      const parsed = new DOMParser().parseFromString(html, 'text/html')
      expect(parsed.querySelectorAll('td')).toHaveLength(2)
    }
  })

  it('counts only visible rows and columns in printed merge spans', () => {
    const html = buildSheetPrintHtml(sourceOf({ A1: { value: 'merged' }, C3: { value: 'covered' } }, {
      hiddenRows: new Set([1]), hiddenColumns: new Set([1]),
      merges: [{ startRow: 0, endRow: 2, startColumn: 0, endColumn: 2 }],
    }), SETUP)!
    const parsed = new DOMParser().parseFromString(html, 'text/html')
    expect(parsed.querySelectorAll('td')).toHaveLength(1)
    expect(parsed.querySelector('td')?.rowSpan).toBe(2)
    expect(parsed.querySelector('td')?.colSpan).toBe(2)
    expect(html).not.toContain('covered')
  })

  it('rejects print coordinates beyond XLSX row and column limits', () => {
    expect(parsePrintRange('A1:XFE2')).toBeNull()
    expect(parsePrintRange('A1:A1048577')).toBeNull()
  })

  it('returns null when there is nothing to print', () => {
    expect(buildSheetPrintHtml(sourceOf({}), SETUP)).toBeNull()
  })
})

describe('File tab routing', () => {
  it('dispatches print and undo/redo commands from the File tab', async () => {
    const { mountWorkbookRibbon } = await import('./workbook-ribbon')
    document.body.innerHTML = '<main></main>'
    const onCommand = vi.fn()
    const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand, {
      rotation: () => undefined, editable: () => true,
    })
    expect([...document.querySelectorAll('[role=tab]')].map(tab => tab.textContent)).toContain('文件')
    document.querySelector<HTMLButtonElement>('[data-ribbon-tab="File"]')!.click()
    const print = document.querySelector<HTMLButtonElement>('[data-ribbon-command="print"]')!
    const undo = document.querySelector<HTMLButtonElement>('[data-ribbon-command="undo"]')!
    const redo = document.querySelector<HTMLButtonElement>('[data-ribbon-command="redo"]')!
    expect(print.disabled).toBe(false)
    expect(undo.disabled).toBe(false)
    expect(redo.disabled).toBe(false)
    print.click()
    undo.click()
    redo.click()
    expect(onCommand.mock.calls).toEqual([['print'], ['undo'], ['redo']])
    ribbon.dispose()
  })

  it('keeps print available while read-only and disables undo/redo like other mutations', async () => {
    const { mountWorkbookRibbon } = await import('./workbook-ribbon')
    document.body.innerHTML = '<main></main>'
    const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), {
      rotation: () => undefined, editable: () => false,
    })
    document.querySelector<HTMLButtonElement>('[data-ribbon-tab="File"]')!.click()
    expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="print"]')!.disabled).toBe(false)
    expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="undo"]')!.disabled).toBe(true)
    expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="redo"]')!.disabled).toBe(true)
    ribbon.dispose()
  })
})
