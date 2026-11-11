import { describe, expect, it } from 'vitest'
import { buildSheetPrintHtml, printSourceFromSnapshotSheet, type SheetPrintSetup } from './workbook-print'

const setup: SheetPrintSetup = {
  orientation: 'portrait', paperSize: 9, scale: 100, fitToPage: false, fitToWidth: 0, fitToHeight: 0,
  margins: { left: 0.7, right: 0.7, top: 0.75, bottom: 0.75 },
  printGridlines: false, printHeadings: false, printArea: null, printTitles: null, rowBreaks: [], colBreaks: [],
}
const render = (sheet: unknown, options: Partial<SheetPrintSetup> = {}) =>
  new DOMParser().parseFromString(buildSheetPrintHtml(printSourceFromSnapshotSheet(sheet), { ...setup, ...options })!, 'text/html')

describe('print cell borders from live snapshot', () => {
  it('preserves valid RGB and RGBA colors accepted by the pinned renderer', () => {
    const doc = render({ cellData: { 0: { 0: { v: 'RGB', s: { bd: {
      t: { s: 1, cl: { rgb: 'rgb(255, 0, 0)' } },
      b: { s: 1, cl: { rgb: 'rgba(0, 0, 255, 0.5)' } },
    } } } } } })
    const shadow = doc.querySelector('td')!.style.boxShadow
    expect(shadow).toContain('rgb(255, 0, 0)')
    expect(shadow).toContain('rgba(0, 0, 255, 0.5)')
  })

  it('resolves shared edge ownership to the neighbouring merged anchor', () => {
    const doc = render({ cellData: {
      0: { 0: { v: 'Merged', s: { bd: { r: { s: 13, cl: { rgb: '#ff0000' } } } } },
        2: { v: 'Right', s: { bd: { l: { s: 1, cl: { rgb: '#0000ff' } } } } } },
    }, mergeData: [{ startRow: 0, endRow: 0, startColumn: 0, endColumn: 1 }] })
    const cells = [...doc.querySelectorAll('td')]
    expect(cells[0]!.style.boxShadow).toContain('inset -2.25pt 0 0 #ff0000')
    expect(cells[1]!.style.boxShadow).not.toContain('#0000ff')
  })

  it('resolves the upper merged anchor when sharing a horizontal edge', () => {
    const doc = render({ cellData: {
      0: { 0: { v: 'Merged', s: { bd: { b: { s: 13, cl: { rgb: '#ff0000' } } } } } },
      2: { 0: { v: 'Below', s: { bd: { t: { s: 1, cl: { rgb: '#0000ff' } } } } } },
    }, mergeData: [{ startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }] })
    const cells = [...doc.querySelectorAll('td')]
    expect(cells[0]!.style.boxShadow).toContain('inset 0 -2.25pt 0 #ff0000')
    expect(cells[1]!.style.boxShadow).not.toContain('#0000ff')
  })

  it('paints four edges with source weights without consuming cell geometry', () => {
    const doc = render({ cellData: { 0: { 0: { v: 'Edges', s: { bd: {
      t: { s: 1, cl: { rgb: '#123456' } }, b: { s: 8, cl: { rgb: '#abcdef' } },
      l: { s: 13 }, r: { s: 7, cl: { rgb: '#654321' } },
    } } } } } })
    const cell = doc.querySelector('td')!
    expect(cell.style.boxShadow).toBe('inset 0 0.75pt 0 #123456,inset 0 -1.5pt 0 #abcdef,inset 2.25pt 0 0 #000000,inset -0.75pt 0 0 #654321')
    expect(cell.style.borderWidth).toBe('')
    expect(doc.querySelector('tr')!.style.height).toBe('15pt')
  })

  it('gives upper and left custom edges precedence over conflicting neighbours', () => {
    const doc = render({ cellData: {
      0: { 0: { v: 'Owner', s: { bd: { b: { s: 1, cl: { rgb: '#ff0000' } }, r: { s: 1, cl: { rgb: '#ff0000' } } } } },
        1: { v: 'Right', s: { bd: { l: { s: 13, cl: { rgb: '#0000ff' } } } } } },
      1: { 0: { v: 'Below', s: { bd: { t: { s: 13, cl: { rgb: '#0000ff' } } } } } },
    } }, { printGridlines: true })
    const cells = [...doc.querySelectorAll('td')]
    expect(cells[0]!.style.boxShadow).toContain('inset -0.75pt 0 0 #ff0000')
    expect(cells[1]!.style.boxShadow).not.toContain('#0000ff')
    expect(cells[2]!.style.boxShadow).not.toContain('#0000ff')
  })

  it('paints neighbour-only edges and scales medium dash patterns as solid lines', () => {
    const doc = render({ cellData: { 0: { 0: { v: 'Left' }, 1: { v: 'Right', s: { bd: { l: { s: 10, cl: { rgb: '#112233' } } } } } } } }, { scale: 50, printGridlines: true })
    const cells = [...doc.querySelectorAll('td')]
    expect(cells[0]!.style.boxShadow).not.toContain('inset -')
    expect(cells[1]!.style.boxShadow).toContain('inset 0.75pt 0 0 #112233')
  })

  it('ignores NONE and constrains border colors to the source syntax', () => {
    const doc = render({ cellData: { 0: { 0: { v: 'Safe', s: { bd: { t: { s: 0 }, b: { s: 1, cl: { rgb: 'red;position:fixed' } } } } } } } })
    const cell = doc.querySelector('td')!
    expect(cell.style.boxShadow).toBe('inset 0 -0.75pt 0 #000')
    expect(cell.style.position).toBe('')
  })

  it('keeps anchor borders around a page-contained merged cell', () => {
    const doc = render({ cellData: { 0: { 0: { v: 'Merged', s: { bd: { r: { s: 13, cl: { rgb: '#009900' } } } } }, 1: { v: 'Covered' } }, 1: { 2: { v: 'Extent' } } },
      mergeData: [{ startRow: 0, endRow: 1, startColumn: 0, endColumn: 1 }] })
    const cell = doc.querySelector('td')!
    expect(cell.rowSpan).toBe(2)
    expect(cell.colSpan).toBe(2)
    expect(cell.style.boxShadow).toContain('inset -2.25pt 0 0 #009900')
    expect(doc.body.textContent).not.toContain('Covered')
  })
})
