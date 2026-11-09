/**
 * Home ▸ Editing ▸ Fill ▸ Series… (fixed source GenOffice f8c17004
 * `fill-series.ts` — ported verbatim below the marker except the date-offset
 * import — plus `fill-series-apply.ts`, `FillSeriesDialog.tsx` and
 * `ExcelShell.tsx` fillSeriesDefaultType). Writes are ordinary set-values
 * edits, so they undo like typing and the save diff picks them up.
 */
import { CellValueType } from '@univerjs/core'
import { createModal } from './modal'

// ── fixed source fill-series.ts ──────────────────────────────────────────
/** fixed source numfmt-fix.ts: 1904 date system offset in days. */
const DATE_1904_OFFSET = 1462

export type FillSeriesDirection = 'rows' | 'columns'
export type FillSeriesType = 'linear' | 'growth' | 'date' | 'autofill'
export type FillSeriesDateUnit = 'day' | 'weekday' | 'month' | 'year'

export interface FillSeriesOptions {
  readonly direction: FillSeriesDirection
  readonly type: FillSeriesType
  readonly dateUnit: FillSeriesDateUnit
  readonly trend: boolean
  readonly step: number
  readonly stop: number | null
  /// Workbook uses the 1904 date system (serial 0 = 1904-01-01).
  readonly date1904?: boolean
}

/// Longest run a single-cell selection with a stop value may extend to.
export const FILL_SERIES_OPEN_ENDED_LIMIT = 10_000

const DAY_MS = 86_400_000
/// Excel 1900-system serial 0 = 1899-12-30 (valid for serials >= 61).
const SERIAL_EPOCH_MS = Date.UTC(1899, 11, 30)

function epochMs(date1904: boolean): number {
  return SERIAL_EPOCH_MS + (date1904 ? DATE_1904_OFFSET * DAY_MS : 0)
}

function serialToDate(serial: number, date1904: boolean): Date {
  return new Date(epochMs(date1904) + Math.floor(serial) * DAY_MS)
}

function dateToSerial(date: Date, fraction: number, date1904: boolean): number {
  return (date.getTime() - epochMs(date1904)) / DAY_MS + fraction
}

function addMonths(serial: number, months: number, date1904: boolean): number {
  const fraction = serial - Math.floor(serial)
  const date = serialToDate(serial, date1904)
  const day = date.getUTCDate()
  const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + months, 1))
  const lastDay = new Date(
    Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0),
  ).getUTCDate()
  target.setUTCDate(Math.min(day, lastDay))
  return dateToSerial(target, fraction, date1904)
}

function addWeekdays(serial: number, count: number, date1904: boolean): number {
  const sign = Math.sign(count)
  let remaining = Math.abs(count)
  let current = serial
  while (remaining > 0) {
    current += sign
    const weekday = serialToDate(current, date1904).getUTCDay()
    if (weekday !== 0 && weekday !== 6) remaining -= 1
  }
  return current
}

export function stepDate(
  serial: number,
  unit: FillSeriesDateUnit,
  step: number,
  date1904 = false,
): number {
  switch (unit) {
    case 'day':
      return serial + step
    case 'weekday':
      return addWeekdays(serial, step, date1904)
    case 'month':
      return addMonths(serial, step, date1904)
    case 'year':
      return addMonths(serial, step * 12, date1904)
  }
}

/// Least-squares line through (0, y0), (1, y1), …; a single point keeps the
/// requested step as its slope.
function linearFit(values: readonly number[], fallbackSlope: number): [number, number] {
  const n = values.length
  if (n < 2) return [values[0] ?? 0, fallbackSlope]
  const meanX = (n - 1) / 2
  const meanY = values.reduce((sum, value) => sum + value, 0) / n
  let numerator = 0
  let denominator = 0
  values.forEach((value, index) => {
    numerator += (index - meanX) * (value - meanY)
    denominator += (index - meanX) ** 2
  })
  const slope = numerator / denominator
  return [meanY - slope * meanX, slope]
}

function passesStop(value: number, stop: number | null, ascending: boolean): boolean {
  if (stop === null) return false
  return ascending ? value > stop : value < stop
}

/// Values for one row/column of the fill: `seeds` are the leading numeric
/// cells (at least one), `length` the cells in the line. The result covers
/// the line from its first cell and may be shorter when a stop value cuts it.
export function fillSeriesLine(
  seeds: readonly number[],
  length: number,
  options: FillSeriesOptions,
): number[] {
  const start = seeds[0]
  if (start === undefined || length <= 0) return []
  const { type, step, stop } = options
  if (options.trend && (type === 'linear' || type === 'growth')) {
    if (type === 'growth' && seeds.some((value) => value <= 0)) return [...seeds]
    const [intercept, slope] = linearFit(
      type === 'growth' ? seeds.map(Math.log) : seeds,
      type === 'growth' ? Math.log(step > 0 ? step : 1) : step,
    )
    const fitted: number[] = []
    for (let index = 0; index < length; index += 1) {
      const raw = intercept + slope * index
      const value = type === 'growth' ? Math.exp(raw) : raw
      const previous = fitted[fitted.length - 1]
      if (
        !Number.isFinite(value) ||
        (previous !== undefined && passesStop(value, stop, value >= previous))
      ) {
        break
      }
      fitted.push(value)
    }
    return fitted
  }
  const values: number[] = [start]
  if (type === 'autofill') {
    const inferred = seeds.length >= 2 ? (seeds[1] ?? start) - start : 1
    values.push(...seeds.slice(1))
    while (values.length < length) {
      const next = (values[values.length - 1] ?? start) + inferred
      if (passesStop(next, stop, inferred >= 0)) break
      values.push(next)
    }
    return values
  }
  let current = start
  for (let index = 1; index < length; index += 1) {
    const previous = current
    switch (type) {
      case 'linear':
        current += step
        break
      case 'growth':
        current *= step
        break
      case 'date':
        // Month/year steps count from the start so a clamped month end
        // (Jan 31 -> Feb 29) does not shorten every later month.
        current =
          options.dateUnit === 'month' || options.dateUnit === 'year'
            ? stepDate(start, options.dateUnit, step * index, options.date1904 ?? false)
            : stepDate(current, options.dateUnit, step, options.date1904 ?? false)
        break
    }
    // Direction comes from the actual movement, so a negative growth seed
    // (-1, -2, -4, …) still stops on its way down.
    if (!Number.isFinite(current) || passesStop(current, stop, current >= previous)) break
    values.push(current)
  }
  return values
}

/// Dialog number fields accept a plain number, or for date series a
/// calendar date (parsed as local time, converted to a serial).
export function parseSeriesNumber(
  text: string,
  allowDate: boolean,
  date1904 = false,
): number | null {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const numeric = Number(trimmed.replace(',', '.'))
  if (Number.isFinite(numeric)) return numeric
  if (!allowDate) return null
  // Date-only ISO text is UTC per spec; everything else parses as local time.
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed)
  const parsed = new Date(trimmed)
  if (Number.isNaN(parsed.getTime())) return null
  const utc = iso
    ? Date.UTC(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]))
    : Date.UTC(parsed.getFullYear(), parsed.getMonth(), parsed.getDate())
  return (utc - epochMs(date1904)) / DAY_MS
}

export type FillSeriesCell = number | string | boolean | null | undefined

export interface FillSeriesWrite {
  readonly row: number
  readonly column: number
  readonly values: readonly (readonly number[])[]
}

/// Plans the writes for a selection whose raw values are `grid` (row-major).
/// Lines whose first cell is not a number are skipped; seeds stay untouched
/// unless a trend replaces them. `extent` lengthens a single-cell selection
/// with a stop value along the fill direction.
export function planFillSeries(
  grid: readonly (readonly FillSeriesCell[])[],
  options: FillSeriesOptions,
  extent = 0,
): FillSeriesWrite[] {
  const rows = grid.length
  const columns = grid[0]?.length ?? 0
  if (rows === 0 || columns === 0) return []
  const byRows = options.direction === 'rows'
  const lineCount = byRows ? rows : columns
  const openEnded = rows === 1 && columns === 1 && options.stop !== null && !options.trend
  const length = openEnded ? Math.max(1, extent) : byRows ? columns : rows
  if (length < 2) return []
  const writes: FillSeriesWrite[] = []
  for (let line = 0; line < lineCount; line += 1) {
    const cellAt = (index: number): FillSeriesCell =>
      byRows ? grid[line]?.[index] : grid[index]?.[line]
    const seeds: number[] = []
    for (let index = 0; index < length; index += 1) {
      const value = cellAt(index)
      if (typeof value !== 'number' || !Number.isFinite(value)) break
      seeds.push(value)
    }
    if (seeds.length === 0) continue
    const values = fillSeriesLine(seeds, length, options)
    const keep = options.trend ? 0 : options.type === 'autofill' ? seeds.length : 1
    const tail = values.slice(keep)
    if (tail.length === 0) continue
    writes.push({
      row: byRows ? line : keep,
      column: byRows ? keep : line,
      values: byRows ? [tail] : tail.map((value) => [value]),
    })
  }
  return writes
}

// ── fixed source fill-series-apply.ts (facade-typed) ─────────────────────
type FillRange = {
  getRange(): { startRow: number; startColumn: number }
  getCellDatas(): ({ v?: unknown; t?: number; f?: unknown; si?: unknown; s?: unknown } | null | undefined)[][]
  getValues(): unknown[][]
  getHeight(): number
  getWidth(): number
}
type FillSheet = {
  getMaxRows(): number
  getMaxColumns(): number
  insertRows(index: number, count: number): unknown
  insertColumns(index: number, count: number): unknown
  getRange(row: number, column: number, rows: number, columns: number): { setValues(values: unknown[][]): unknown }
}

/** Writes the series into `active` on `sheet`; returns a user-facing error or null. */
export function applyFillSeries(sheet: FillSheet, active: FillRange, options: FillSeriesOptions): string | null {
  const { startRow, startColumn } = active.getRange()
  const cells = active.getCellDatas()
  const computed = active.getValues()
  // Seeds: raw numbers, numeric text typed as NUMBER, or a formula's result.
  const grid = cells.map((row, r) =>
    row.map((cell, c) => {
      const v = cell?.v
      if (typeof v === 'number') return v
      if (typeof v === 'string' && cell?.t === CellValueType.NUMBER && v.trim() !== '') {
        const numeric = Number(v)
        if (Number.isFinite(numeric)) return numeric
      }
      if (cell?.f !== undefined || cell?.si !== undefined) {
        const result = computed[r]?.[c]
        if (typeof result === 'number') return result
      }
      return (v ?? null) as FillSeriesCell
    }),
  )
  const writes = planFillSeries(grid, options, FILL_SERIES_OPEN_ENDED_LIMIT)
  if (writes.length === 0) return '所选区域没有可作为序列起点的数字'
  const needRows = Math.max(...writes.map(write => startRow + write.row + write.values.length))
  const needColumns = Math.max(...writes.map(write => startColumn + write.column + (write.values[0]?.length ?? 0)))
  if (needRows > sheet.getMaxRows()) sheet.insertRows(sheet.getMaxRows(), needRows - sheet.getMaxRows())
  if (needColumns > sheet.getMaxColumns()) sheet.insertColumns(sheet.getMaxColumns(), needColumns - sheet.getMaxColumns())
  for (const write of writes) {
    // Filled cells take their line's seed format so a date series keeps showing dates.
    const seedStyle = options.direction === 'rows' ? cells[write.row]?.[0]?.s : cells[0]?.[write.column]?.s
    // Series replaces the target cells outright: setValues merges, so formulas and rich text are cleared explicitly.
    const matrix = write.values.map(row => row.map(v => ({ v, t: CellValueType.NUMBER, f: null, si: null, p: null, ...(seedStyle ? { s: seedStyle } : {}) })))
    sheet.getRange(startRow + write.row, startColumn + write.column, matrix.length, matrix[0]?.length ?? 1).setValues(matrix)
  }
  return null
}

/** Series in follows the selection shape (taller than wide = Columns). */
export const fillSeriesDirection = (active: { getHeight(): number; getWidth(): number }): FillSeriesDirection =>
  active.getHeight() > active.getWidth() ? 'columns' : 'rows'
/** fixed source fillSeriesDefaultType: a date-formatted selection defaults to a date series. */
export const fillSeriesDefaultType = (dateFormatted: boolean): FillSeriesType => dateFormatted ? 'date' : 'linear'

// ── fixed source FillSeriesDialog.tsx (DOM) ──────────────────────────────
const DIRECTIONS: readonly [FillSeriesDirection, string][] = [['rows', '行'], ['columns', '列']]
const TYPES: readonly [FillSeriesType, string][] = [['linear', '等差序列'], ['growth', '等比序列'], ['date', '日期'], ['autofill', '自动填充']]
const DATE_UNITS: readonly [FillSeriesDateUnit, string][] = [['day', '日'], ['weekday', '工作日'], ['month', '月'], ['year', '年']]

export function createFillSeriesDialog(root: HTMLElement, apply: (options: FillSeriesOptions) => string | null) {
  const group = (name: string, label: string, choices: readonly [string, string][]) => `<fieldset class="workbook-ribbon-fill-group" data-fill-group="${name}"><legend>${label}</legend>${
    choices.map(([value, text]) => `<label><input type="radio" name="workbook-fill-${name}" value="${value}">${text}</label>`).join('')}</fieldset>`
  const modal = createModal({ root, label: '序列', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog workbook-ribbon-fill-dialog', closeLabel: '关闭', content: `
    <h2>序列</h2><form class="workbook-ribbon-format-form">
      ${group('direction', '序列产生在', DIRECTIONS)}${group('type', '类型', TYPES)}${group('unit', '日期单位', DATE_UNITS)}
      <label><input type="checkbox" data-fill-trend>预测趋势</label>
      <label>步长值<input type="text" data-fill-step autocomplete="off"></label>
      <label>终止值<input type="text" data-fill-stop autocomplete="off"></label>
      <p class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" class="workbook-ribbon-format-cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">确定</button></div>
    </form>` })
  const card = modal.card
  const error = card.querySelector<HTMLElement>('[role="alert"]')!
  const trend = card.querySelector<HTMLInputElement>('[data-fill-trend]')!
  const step = card.querySelector<HTMLInputElement>('[data-fill-step]')!, stop = card.querySelector<HTMLInputElement>('[data-fill-stop]')!
  const submit = card.querySelector<HTMLButtonElement>('.workbook-ribbon-format-apply')!
  const value = (name: string) => card.querySelector<HTMLInputElement>(`input[name="workbook-fill-${name}"]:checked`)?.value
  const read = () => {
    const type = value('type') as FillSeriesType, trendable = type === 'linear' || type === 'growth'
    return { type, trendable, stepValue: parseSeriesNumber(step.value, false), stopValue: parseSeriesNumber(stop.value, type === 'date') }
  }
  const sync = () => {
    const { type, trendable, stepValue, stopValue } = read()
    card.querySelector<HTMLFieldSetElement>('[data-fill-group="unit"]')!.disabled = type !== 'date'
    trend.disabled = !trendable
    const trending = trend.checked && trendable
    step.disabled = stop.disabled = trending
    submit.disabled = !(trending || (stepValue !== null && (stop.value.trim() === '' || stopValue !== null)))
  }
  card.addEventListener('input', sync); card.addEventListener('change', sync)
  card.querySelector('.workbook-ribbon-format-cancel')!.addEventListener('click', modal.close)
  card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    const { type, trendable, stepValue, stopValue } = read()
    const trending = trend.checked && trendable
    try {
      const failure = apply({ direction: value('direction') as FillSeriesDirection, type, dateUnit: value('unit') as FillSeriesDateUnit,
        trend: trending, step: stepValue ?? 1, stop: trending ? null : stopValue, date1904: false })
      if (failure) error.textContent = failure; else modal.close()
    } catch (cause) { error.textContent = (cause as Error).message }
  })
  const check = (name: string, choice: string) => { for (const input of card.querySelectorAll<HTMLInputElement>(`input[name="workbook-fill-${name}"]`)) input.checked = input.value === choice }
  return {
    open(direction: FillSeriesDirection, type: FillSeriesType) {
      check('direction', direction); check('type', type); check('unit', 'day')
      trend.checked = false; step.value = '1'; stop.value = ''; error.textContent = ''
      sync(); modal.open(step)
    },
    dispose: modal.remove,
  }
}
