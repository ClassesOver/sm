import { afterEach, expect, it, vi } from 'vitest'
import { createChartDataDialog, hydrateChartDataSeries, readChartDataVector, transposeChartDataSeries } from './workbook-chart-data-dialog'

const entries = [
  { name: 'North', values: [10, 20], valuesRef: "'Data'!$B$2:$B$3", categories: ['Q1', 'Q2'], categoriesRef: "'Data'!$A$2:$A$3", color: '#123456' },
  { name: 'South', values: [30, 40], valuesRef: "'Data'!$C$2:$C$3", categories: ['Q1', 'Q2'], categoriesRef: "'Data'!$A$2:$A$3" },
]
const active: ReturnType<typeof createChartDataDialog>[] = []
afterEach(() => { active.splice(0).forEach(dialog => dialog.dispose()); document.body.innerHTML = '' })
const setup = (readVector = vi.fn(async (_range: string) => ({ vector: [8, 'bad', null, '9'], ref: "'Other'!$D$1:$D$4" })), apply = vi.fn(async (_series: unknown) => {})) => {
  const dialog = createChartDataDialog(document.body, { readVector, apply }); active.push(dialog)
  dialog.open(entries)
  return { dialog, readVector, apply }
}
const row = (index: number) => document.querySelectorAll<HTMLElement>('[data-chart-data-row]')[index]!
const input = (index: number, field: string, value: string) => { const node = row(index).querySelector<HTMLInputElement>(`[data-chart-data-${field}]`)!; node.value = value; node.dispatchEvent(new Event('input', { bubbles: true })) }
const submit = () => document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
const click = (selector: string) => document.querySelector<HTMLButtonElement>(selector)!.click()

it('combo Select Data keeps source plot/axis tags, cancels changes, and moves the tags with reordered rows', async () => {
  const { dialog, apply } = setup(), combo = [{ ...entries[0]!, plot: 'barChart' as const, secondaryAxis: false }, { ...entries[1]!, plot: 'lineChart' as const, secondaryAxis: true }]
  dialog.open(combo, true)
  expect(row(0).querySelector<HTMLSelectElement>('[data-chart-data-plot]')?.value).toBe('barChart')
  expect(row(1).querySelector<HTMLInputElement>('[data-chart-data-secondary]')?.checked).toBe(true)
  const plot = row(0).querySelector<HTMLSelectElement>('[data-chart-data-plot]')!; plot.value = 'lineChart'; plot.dispatchEvent(new Event('change'))
  click('[data-chart-data-cancel]'); expect(apply).not.toHaveBeenCalled()
  dialog.open(combo, true); row(1).querySelector<HTMLButtonElement>('[data-chart-data-up]')!.click()
  const secondary = row(0).querySelector<HTMLInputElement>('[data-chart-data-secondary]')!; secondary.checked = false; secondary.dispatchEvent(new Event('change'))
  submit(); await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(1))
  expect(apply.mock.calls[0]![0]).toEqual([{ ...combo[1], secondaryAxis: false }, combo[0]])
})

it('combo transpose uses source last-series line/secondary defaults and new rows default to primary bars', async () => {
  const { dialog, apply } = setup(); dialog.open(entries, true); click('[data-chart-data-add]'); input(2, 'values', 'D1:D4'); submit()
  await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(1))
  expect((apply.mock.calls[0]![0] as any[])[2]).toMatchObject({ plot: 'barChart', secondaryAxis: false })
  dialog.open(entries, true); click('[data-chart-data-switch]'); await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(2))
  expect(apply.mock.calls[1]![0]).toEqual([{ name: 'Q1', values: [10, 30], categories: ['North', 'South'], plot: 'barChart', secondaryAxis: false }, { name: 'Q2', values: [20, 40], categories: ['North', 'South'], plot: 'lineChart', secondaryAxis: true }])
})

it('hydrates combo plot and secondary tags from the actual reader instead of assigning the last row as line', () => {
  const series = hydrateChartDataSeries({ kind: 'combo', series: [{ name: 'Line first', valuesRef: '', values: [1, 2], plot: 'lineChart', secondaryAxis: false }, { name: 'Bar last', valuesRef: '', values: [300, 400], plot: 'barChart', secondaryAxis: true }] } as never, () => { throw Error('literal') })
  expect(series).toMatchObject([{ plot: 'lineChart', secondaryAxis: false }, { plot: 'barChart', secondaryAxis: true }])
})

it('opens a cancellable draft with source placeholders and never changes input series', () => {
  const { dialog, apply } = setup(); expect(row(0).querySelector<HTMLInputElement>('[data-chart-data-values]')!.placeholder).toBe(entries[0]!.valuesRef)
  input(0, 'name', 'Unapplied'); click('[data-chart-data-cancel]'); expect(apply).not.toHaveBeenCalled()
  dialog.open(entries); expect(row(0).querySelector<HTMLInputElement>('[data-chart-data-name]')!.value).toBe('North')
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); expect(apply).not.toHaveBeenCalled(); expect(entries[0]!.name).toBe('North')
})

it('renames, removes, adds and reorders series; blank names preserve originals or use numbered defaults', async () => {
  const { apply } = setup(); input(0, 'name', '  Renamed  '); click('[data-chart-data-add]'); input(2, 'values', 'D1:D4')
  row(2).querySelector<HTMLButtonElement>('[data-chart-data-up]')!.click(); row(2).querySelector<HTMLButtonElement>('[data-chart-data-remove]')!.click()
  submit(); await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(1))
  expect(apply.mock.calls[0]![0]).toEqual([{ ...entries[0], name: 'Renamed' }, { name: '系列 2', values: [8, 0, 0, 9], valuesRef: "'Other'!$D$1:$D$4" }])
})

it('keeps source values/ref/color unless a corresponding vector is explicitly changed', async () => {
  const readVector = vi.fn(async () => ({ vector: ['A', null, 'B'], ref: "'Other'!$A$1:$A$3" })), { apply } = setup(readVector as never)
  input(0, 'name', ''); input(0, 'categories', "'Other'!A1:A3"); submit(); await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(1))
  expect(apply.mock.calls[0]![0]).toEqual([{ ...entries[0], categories: ['A', '', 'B'], categoriesRef: "'Other'!$A$1:$A$3" }, entries[1]])
})

it('caps added rows at 24 and requires values for new rows and at least one remaining series', async () => {
  const { dialog, apply } = setup(); dialog.open(Array.from({ length: 24 }, () => entries[0]!)); expect(document.querySelector<HTMLButtonElement>('[data-chart-data-add]')!.disabled).toBe(true)
  dialog.open([]); expect(document.querySelector<HTMLButtonElement>('[data-chart-data-submit]')!.disabled).toBe(true)
  click('[data-chart-data-add]'); submit(); await vi.waitFor(() => expect(document.querySelector('[role=alert]')!.textContent).toContain('数值区域')); expect(apply).not.toHaveBeenCalled()
})

it('transposes initial chart data exactly as the source, including literals and the 24-category cap', async () => {
  expect(transposeChartDataSeries([])).toBeNull()
  const source = [{ name: '', values: [1], categories: Array.from({ length: 30 }, (_, index) => index ? `Q${index}` : '') }]
  const result = transposeChartDataSeries(source)!; expect(result).toHaveLength(24); expect(result[0]).toEqual({ name: '系列 1', values: [1], categories: ['系列 1'] }); expect(result[1]!.values).toEqual([0])
  const { apply } = setup(); input(0, 'name', 'Unapplied'); click('[data-chart-data-switch]'); await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(1))
  expect(apply.mock.calls[0]![0]).toEqual([{ name: 'Q1', values: [10, 30], categories: ['North', 'South'] }, { name: 'Q2', values: [20, 40], categories: ['North', 'South'] }])
})

it('drops results after cancel/dispose and blocks duplicate commits while applying', async () => {
  let resolve!: (value: { vector: number[]; ref: string }) => void
  const read = vi.fn(() => new Promise<{ vector: number[]; ref: string }>(done => { resolve = done })), { apply, dialog: first } = setup(read as never)
  input(0, 'values', 'A1'); submit(); click('[data-chart-data-cancel]'); resolve({ vector: [1], ref: "'Data'!$A$1:$A$1" }); await Promise.resolve(); await Promise.resolve(); expect(apply).not.toHaveBeenCalled()
  first.dispose(); let complete!: () => void
  const pending = vi.fn(() => new Promise<void>(done => { complete = done })), { dialog } = setup(undefined, pending)
  submit(); await vi.waitFor(() => expect(pending).toHaveBeenCalledTimes(1)); submit(); expect(pending).toHaveBeenCalledTimes(1); expect(document.querySelector<HTMLButtonElement>('[data-chart-data-cancel]')!.disabled).toBe(true)
  dialog.dispose(); complete(); await Promise.resolve()
})

it('retains the draft and displays read/apply failures without pretending they succeeded', async () => {
  const apply = vi.fn(async () => { throw Error('图表目标已变化') }); setup(undefined, apply); submit()
  await vi.waitFor(() => expect(document.querySelector('[role=alert]')!.textContent).toContain('图表目标已变化'))
  expect(document.querySelector<HTMLButtonElement>('[data-chart-data-submit]')!.disabled).toBe(false)
})

it('reads current raw one-dimensional values across quoted sheets, normalizes refs and rejects unsafe or oversized ranges', () => {
  const getRange = vi.fn(() => ({ getRawValues: () => [[11], ['12']] }))
  const book = { getSheets: () => [{ getSheetName: () => "O'Brien Data", getRange }] }
  expect(readChartDataVector(book, "O'Brien Data", "'o''brien data'!$b$2:$b$3")).toEqual({ vector: [11, '12'], ref: "'O''Brien Data'!$B$2:$B$3" })
  expect(() => readChartDataVector(book, "O'Brien Data", 'A1:B2')).toThrow(/一行或一列/)
  expect(() => readChartDataVector(book, "O'Brien Data", 'A1:A1001')).toThrow(/1000/)
  expect(() => readChartDataVector(book, "O'Brien Data", "'[foreign.xlsx]Data'!A1")).toThrow()
  expect(() => readChartDataVector(book, "O'Brien Data", 'Missing!A1')).toThrow(/工作表/)
  expect(() => readChartDataVector(book, "O'Brien Data", 'XFE1')).toThrow()
})


it('keeps keyboard focus on the moved series and adjacent series after removal, then Add when empty', () => {
  const { apply } = setup()
  const up = row(1).querySelector<HTMLButtonElement>('[data-chart-data-up]')!; up.focus(); up.click()
  expect(document.activeElement).toBe(row(0).querySelector('[data-chart-data-name]'))
  expect((document.activeElement as HTMLInputElement).value).toBe('South')
  expect(row(0).querySelector<HTMLButtonElement>('[data-chart-data-up]')!.disabled).toBe(true)
  const down = row(0).querySelector<HTMLButtonElement>('[data-chart-data-down]')!; down.focus(); down.click()
  expect(document.activeElement).toBe(row(1).querySelector('[data-chart-data-name]'))
  expect((document.activeElement as HTMLInputElement).value).toBe('South')
  expect(row(1).querySelector<HTMLButtonElement>('[data-chart-data-down]')!.disabled).toBe(true)
  const remove = row(1).querySelector<HTMLButtonElement>('[data-chart-data-remove]')!; remove.focus(); remove.click()
  expect(document.activeElement).toBe(row(0).querySelector('[data-chart-data-name]'))
  expect((document.activeElement as HTMLInputElement).value).toBe('North')
  row(0).querySelector<HTMLButtonElement>('[data-chart-data-remove]')!.click()
  expect(document.activeElement).toBe(document.querySelector('[data-chart-data-add]'))
  expect(document.querySelectorAll('[data-chart-data-row]')).toHaveLength(0)
  expect(document.querySelector<HTMLButtonElement>('[data-chart-data-submit]')!.disabled).toBe(true)
  expect(apply).not.toHaveBeenCalled()
})

it('focuses the following series when deleting the first row and preserves draft values', async () => {
  const { dialog, apply } = setup(); dialog.open([...entries, { name: 'West', values: [50, 60] }])
  input(1, 'name', 'South edited')
  row(0).querySelector<HTMLButtonElement>('[data-chart-data-remove]')!.click()
  expect(document.activeElement).toBe(row(0).querySelector('[data-chart-data-name]'))
  expect((document.activeElement as HTMLInputElement).value).toBe('South edited')
  expect(apply).not.toHaveBeenCalled()
  submit(); await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(1))
  expect(apply.mock.calls[0]![0]).toEqual([{ ...entries[1], name: 'South edited' }, { name: 'West', values: [50, 60] }])
})


it('focuses the next series after removing a middle row without applying the draft', () => {
  const { dialog, apply } = setup(); dialog.open([...entries, { name: 'West', values: [50, 60] }])
  input(2, 'name', 'West edited')
  row(1).querySelector<HTMLButtonElement>('[data-chart-data-remove]')!.click()
  expect(document.activeElement).toBe(row(1).querySelector('[data-chart-data-name]'))
  expect((document.activeElement as HTMLInputElement).value).toBe('West edited')
  expect(row(0).querySelector<HTMLInputElement>('[data-chart-data-name]')!.value).toBe('North')
  expect(apply).not.toHaveBeenCalled()
})
