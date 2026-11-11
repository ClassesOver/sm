import { expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { planSheetPrint, type SheetPrintSource, type SheetPrintSetup } from './workbook-print'
import { installPageBreakOverlay, planPageBreakPreview } from './workbook-page-break-preview'

const source: SheetPrintSource = { name: 'Data', cells: { A1: { value: 'head' }, D20: { value: 20 } }, merges: [], columnWidths: {}, rowHeights: {}, hiddenRows: new Set(), hiddenColumns: new Set() }
const setup: SheetPrintSetup = { paperSize: 9, orientation: 'portrait', margins: { left: .7, right: .7, top: .75, bottom: .75 }, scale: 100, fitToPage: false, fitToWidth: 0, fitToHeight: 0, printGridlines: false, printHeadings: false, printArea: null, printTitles: null, rowBreaks: [10], colBreaks: [2] }
it('uses exact print planner pages and manual versus automatic boundary kinds', () => {
  const result = planPageBreakPreview(source, setup)
  expect(result.status).toBe('ready'); if (result.status !== 'ready') return
  expect(result.printPlan).toEqual(planSheetPrint(source, setup))
  expect(result.layers.filter(layer => layer.kind === 'page').map(layer => layer.page)).toEqual([1, 2, 3, 4])
  expect(result.layers.filter(layer => layer.kind === 'row')).toEqual([{ kind: 'row', manual: true, range: { startRow: 10, endRow: 10, startColumn: 0, endColumn: 3 } }])
  expect(result.layers.filter(layer => layer.kind === 'column')[0]?.manual).toBe(true)
})
it('follows custom margins, hidden geometry, print areas, titles, scale and fit on both axes', () => {
  const live = { ...source, rowHeights: { 4: 160 }, columnWidths: { 2: 250 }, hiddenRows: new Set([2]), hiddenColumns: new Set([1]) }
  for (const patch of [{ scale: 180 }, { fitToPage: true, fitToWidth: 1, fitToHeight: 2 }, { margins: { left: 1.2, right: .3, top: .4, bottom: 1.1 }, printTitles: '1:2' }, { printArea: 'C5:D20' }]) {
    const current = { ...setup, ...patch }, result = planPageBreakPreview(live, current)
    expect(result.status).toBe('ready'); if (result.status === 'ready') expect(result.printPlan).toEqual(planSheetPrint(live, current))
  }
})
it('returns a transparent reason for empty and print-budget sources, and caps rendering without changing the print plan', () => {
  expect(planPageBreakPreview({ ...source, cells: {} }, setup)).toMatchObject({ status: 'unavailable', reason: expect.stringContaining('可预览') })
  expect(planPageBreakPreview(source, { ...setup, printArea: 'A1:Z2001' })).toMatchObject({ status: 'unavailable', reason: expect.stringContaining('50000') })
  const many = { ...setup, printArea: 'A1:A70', rowBreaks: Array.from({ length: 69 }, (_, index) => index + 1), colBreaks: [] }
  const result = planPageBreakPreview(source, many)
  expect(result.status).toBe('ready'); if (result.status !== 'ready') return
  expect(result.printPlan.pages).toHaveLength(70); expect(result.layers.filter(layer => layer.kind === 'page')).toHaveLength(60)
  expect(result.issues.join('')).toContain('60'); expect(result.issues.join('')).toContain('70')
})
it('keeps disjoint print areas separate and uses current effective break coordinates after a structural change', () => {
  const before = planPageBreakPreview(source, { ...setup, printArea: 'A1:B20,D1:D20', colBreaks: [] })
  const after = planPageBreakPreview(source, { ...setup, printArea: 'A1:B22,D1:D22', rowBreaks: [12], colBreaks: [] })
  expect(before.status).toBe('ready'); expect(after.status).toBe('ready')
  if (before.status !== 'ready' || after.status !== 'ready') return
  expect(before.layers.filter(layer => layer.kind === 'outline')).toHaveLength(2)
  expect(after.layers.filter(layer => layer.kind === 'row').every(layer => layer.range.startRow === 12)).toBe(true)
})
it('installs official pass-through range layers, RTL boundary edges, and disposes all registered resources', () => {
  const components: Array<() => React.ReactNode> = [], releases: string[] = []
  const runtime = { univerAPI: { registerComponent: vi.fn((key: string, component: any) => { components.push(component); return { dispose: () => { releases.push(key) } } }) } }
  const sheet = { getRange: vi.fn((...bounds: number[]) => bounds), addFloatDomToRange: vi.fn((_range, _layer, _layout, key) => ({ dispose: () => { releases.push(key + '-float') } })) }
  const result = planPageBreakPreview(source, setup); if (result.status !== 'ready') throw Error('expected ready')
  const handle = installPageBreakOverlay(runtime, sheet, result, 'host-a', true)
  expect(sheet.addFloatDomToRange.mock.calls.every(call => call[1].eventPassThrough === true && call[1].allowTransform === false)).toBe(true)
  const markup = components.map(component => renderToStaticMarkup(component() as any)).join('')
  expect(markup).toContain('border-right:2px solid'); expect(markup).toContain('pointer-events:none'); expect(markup).toContain('第 1 页')
  handle.dispose(); handle.dispose(); expect(releases).toHaveLength(result.layers.length * 2)
})
it('cleans partial registration when an official float cannot be installed', () => {
  const release = vi.fn(), runtime = { univerAPI: { registerComponent: () => ({ dispose: release }) } }
  const sheet = { getRange: () => 'range', addFloatDomToRange: () => null }
  const result = planPageBreakPreview(source, setup); if (result.status !== 'ready') throw Error('expected ready')
  expect(() => installPageBreakOverlay(runtime, sheet, result, 'failed')).toThrow('浮层')
  expect(release).toHaveBeenCalledOnce()
})
it('reports line and extent caps explicitly while preserving the full print plan', () => {
  expect(planPageBreakPreview(source, { ...setup, printArea: 'A1:A20001' })).toMatchObject({ status: 'unavailable', reason: expect.stringContaining('20000') })
  const result = planPageBreakPreview(source, { ...setup, printArea: 'A1:A250', rowBreaks: Array.from({ length: 249 }, (_, index) => index + 1) })
  expect(result.status).toBe('ready'); if (result.status !== 'ready') return
  expect(result.printPlan.pages).toHaveLength(250)
  expect(result.layers.filter(layer => layer.kind === 'row')).toHaveLength(200)
  expect(result.issues.join('')).toContain('200 条')
})
it('releases both successful and failed registration resources on a later float exception', () => {
  const release = vi.fn(), remove = vi.fn(), add = vi.fn().mockReturnValueOnce({ dispose: remove }).mockImplementationOnce(() => { throw Error('render failed') })
  const runtime = { univerAPI: { registerComponent: () => ({ dispose: release }) } }, sheet = { getRange: () => 'range', addFloatDomToRange: add }
  const result = planPageBreakPreview(source, setup); if (result.status !== 'ready') throw Error('expected ready')
  expect(() => installPageBreakOverlay(runtime, sheet, result, 'failed-later')).toThrow('render failed')
  expect(release).toHaveBeenCalledTimes(2); expect(remove).toHaveBeenCalledOnce()
})
it('places automatic boundaries at planner body-band starts after a manual break', () => {
  const result = planPageBreakPreview({ ...source, cells: { A100: { value: 100 } } }, { ...setup, rowBreaks: [30], colBreaks: [] })
  expect(result.status).toBe('ready'); if (result.status !== 'ready') return
  expect(result.layers.filter(layer => layer.kind === 'row').map(layer => [layer.range.startRow, layer.manual])).toEqual([[30, true], [78, false]])
})
