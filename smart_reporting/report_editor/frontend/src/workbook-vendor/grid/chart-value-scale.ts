import type { ChartReadSpec } from '@sheets-web/xlsx-engine'

type Scaling = NonNullable<NonNullable<ChartReadSpec['axes']>['value']['scaling']>

/** A finite, clamped linear mapping. Preserve existing automatic bounds when
 * the file has none; never reinterpret logarithmic/invalid ranges as linear.
 */
export function barValueFraction(slots: ReadonlyArray<ReadonlyArray<number | null>>, scaling?: Scaling): ((value: number) => number) | undefined {
  if (scaling?.unsupported) return undefined
  let dataMin = 0, dataMax = 0
  for (const values of slots) for (const value of values) if (value !== null) {
    dataMin = Math.min(dataMin, value); dataMax = Math.max(dataMax, value)
  }
  let min = scaling?.min ?? dataMin, max = scaling?.max ?? dataMax
  if (!Number.isFinite(min) || !Number.isFinite(max)) return undefined
  if (min >= max) {
    if (scaling?.min !== undefined && scaling.max !== undefined) return undefined
    if (scaling?.max !== undefined) min = max - Math.max(1, Math.abs(max) * 0.1)
    else max = min + Math.max(1, Math.abs(min) * 0.1)
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || !(max > min)) return undefined
  const span = max - min, magnitude = Math.max(-min, max)
  const lo = min / magnitude, normalizedSpan = max / magnitude - lo
  return (value: number) => {
    const clamped = Math.max(min, Math.min(max, value))
    const fraction = Number.isFinite(span) ? (clamped - min) / span : (clamped / magnitude - lo) / normalizedSpan
    return scaling?.reversed ? 1 - fraction : fraction
  }
}
