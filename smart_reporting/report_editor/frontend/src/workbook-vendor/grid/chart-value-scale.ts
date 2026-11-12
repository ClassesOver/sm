import type { ChartReadSpec } from '@sheets-web/xlsx-engine'

type Scaling = NonNullable<NonNullable<ChartReadSpec['axes']>['value']['scaling']>
export type BarValueScale = { min: number; max: number; ticks: number[]; fraction: (value: number) => number }

// The pinned GenOffice valueAxisScale uses 5% headroom and 1/2/5 units.
// Bound every search; at floating-point extremes prefer finite data bounds
// over an overflowing rounded bound. Explicit endpoints remain exact.
function axisUnit(span: number): number {
  let exponent = Math.floor(Math.log10(span)) - 1
  for (let guard = 0; guard < 6; guard++, exponent++) {
    for (const base of [1, 2, 5]) {
      const unit = base * 10 ** exponent
      if (unit > 0 && Number.isFinite(unit) && span / unit <= 10 + 1e-9) return unit
    }
  }
  return span
}
function niceCeiling(value: number): number {
  let exponent = Math.floor(Math.log10(value)) - 1
  for (let guard = 0; guard < 8; guard++, exponent++) {
    for (const base of [1, 2, 2.5, 5]) {
      const step = base * 10 ** exponent
      if (!(step > 0) || !Number.isFinite(step)) continue
      const intervals = Math.ceil(value / step - 1e-9)
      if (intervals <= 9 && Number.isFinite(intervals * step)) return intervals * step
    }
  }
  return value
}
function axisTicks(min: number, max: number, unit: number): number[] {
  const span = max - min
  if (!(unit > 0) || !Number.isFinite(unit) || !Number.isFinite(span)) return min < 0 && max > 0 ? [min, 0, max] : [min, max]
  const intervals = Math.floor(span / unit + 1e-6)
  const stride = Math.max(1, Math.ceil(intervals / 10))
  const count = Math.min(12, Math.floor(intervals / stride) + 1)
  const ticks: number[] = []
  for (let index = 0; index < count; index++) {
    const raw = min + index * (unit * stride)
    // Precision cleanup must not move a narrow large-number domain's ticks
    // outside its actual endpoints or merge distinct representable values.
    const rounded = Number(raw.toPrecision(12))
    const tick = Math.abs(rounded - raw) <= unit * 1e-6 ? rounded : raw
    if (tick >= min && tick <= max && ticks.at(-1) !== tick) ticks.push(tick)
  }
  return ticks.length >= 2 ? ticks : [min, max]
}

/** Shared domain for labels, zero baseline and clipped bar geometry. */
export function barValueScale(slots: ReadonlyArray<ReadonlyArray<number | null>>, scaling?: Scaling): BarValueScale | undefined {
  if (scaling?.unsupported) return undefined
  let dataMin = 0, dataMax = 0
  for (const values of slots) for (const value of values) if (value !== null && Number.isFinite(value)) {
    dataMin = Math.min(dataMin, value); dataMax = Math.max(dataMax, value)
  }
  const paddedFloor = dataMin * 1.05
  const floorMagnitude = Number.isFinite(paddedFloor) ? -paddedFloor : -dataMin
  const majorUnit = scaling?.majorUnit
  if (majorUnit !== undefined && (!(majorUnit > 0) || !Number.isFinite(majorUnit))) return undefined
  const niceFloor = majorUnit ? Math.ceil(floorMagnitude / majorUnit) * majorUnit : niceCeiling(floorMagnitude)
  let min = scaling?.min ?? (dataMin < 0 ? -(Number.isFinite(niceFloor) ? niceFloor : -dataMin) : 0)
  const zeroTop = scaling?.max === undefined && dataMax <= 0
  const target = scaling?.max ?? (zeroTop ? 0 : Math.max(dataMax, min))
  const rawSpan = target - min
  const paddedSpan = scaling?.max === undefined && !zeroTop ? rawSpan * 1.05 : rawSpan
  let unit = majorUnit ?? axisUnit(paddedSpan)
  let max = scaling?.max ?? (zeroTop && min < 0 ? 0 : rawSpan > 0 ? min + Math.ceil(paddedSpan / unit - 1e-9) * unit : min + 1)
  if (!Number.isFinite(max)) max = dataMax
  if (!Number.isFinite(min) || !Number.isFinite(max)) return undefined
  if (min >= max) {
    if (scaling?.min !== undefined && scaling.max !== undefined) return undefined
    if (scaling?.max !== undefined) min = max - Math.max(1, Math.abs(max) * 0.1)
    else max = min + Math.max(1, Math.abs(min) * 0.1)
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || !(max > min)) return undefined
  if (!(rawSpan > 0)) unit = (max - min) / 5
  const span = max - min, magnitude = Math.max(Math.abs(min), Math.abs(max))
  const lo = min / magnitude, normalizedSpan = max / magnitude - lo
  const fraction = (value: number): number => {
    const clamped = Math.max(min, Math.min(max, value))
    const position = Number.isFinite(span) ? (clamped - min) / span : (clamped / magnitude - lo) / normalizedSpan
    return scaling?.reversed ? 1 - position : position
  }
  return { min, max, ticks: axisTicks(min, max, unit), fraction }
}
export function barValueFraction(slots: ReadonlyArray<ReadonlyArray<number | null>>, scaling?: Scaling): ((value: number) => number) | undefined {
  return barValueScale(slots, scaling)?.fraction
}
