import { SaxesParser } from 'saxes'

type LabelMode = 'none' | 'value' | 'percent' | 'category-percent' | 'category-value-percent'
type Flags = Map<string, string>
export interface ScatterLabelModes {
  readonly mode?: LabelMode
  readonly firstSeriesMode?: LabelMode
  readonly unsupported?: boolean
}

function modeOf(flags: Flags): LabelMode {
  const shown = (key: string) => ['1', 'true'].includes(flags.get(key) ?? '')
  if (shown('delete')) return 'none'
  if (shown('showPercent')) {
    return shown('showCatName') ? shown('showVal') ? 'category-value-percent' : 'category-percent' : 'percent'
  }
  return shown('showVal') ? 'value' : 'none'
}

/** Pinned GenOffice charts.rs data_labels_node/mode: only the first series
 * supplies a fallback, and only direct flags define its mode. Input is the
 * normalized scatter plot body; point and extension labels never participate. */
export function scatterLabelModes(inner: string): ScatterLabelModes {
  const uri = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
  const parser = new SaxesParser({ xmlns: true })
  let depth = 0, firstSeriesSeen = false, inFirstSeries = false, invalid = false
  let root: Flags | undefined, series: Flags | undefined
  let active: { depth: number; flags: Flags } | undefined
  parser.on('doctype', () => { throw new Error('DOCTYPE') })
  parser.on('opentag', tag => {
    if (depth === 1 && tag.uri === uri && tag.local === 'ser') {
      inFirstSeries = !firstSeriesSeen
      firstSeriesSeen = true
    }
    if (tag.uri === uri && tag.local === 'dLbls' && (depth === 1 || (depth === 2 && inFirstSeries))) {
      const flags: Flags = new Map()
      if (depth === 1) { if (root) invalid = true; root = flags }
      else { if (series) invalid = true; series = flags }
      active = { depth: depth + 1, flags }
    } else if (active && depth === active.depth && tag.uri === uri &&
      ['delete', 'showVal', 'showCatName', 'showPercent'].includes(tag.local) && !active.flags.has(tag.local)) {
      active.flags.set(tag.local, tag.attributes.val?.value ?? '')
    }
    depth++
  })
  parser.on('closetag', () => {
    depth--
    if (active && depth < active.depth) active = undefined
    if (depth === 1) inFirstSeries = false
  })
  try {
    parser.write(`<c:scatterChart xmlns:c="${uri}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:foreign="urn:foreign">${inner}</c:scatterChart>`).close()
  } catch { return { unsupported: true } }
  if (invalid) return { unsupported: true }
  const rootMode = root && modeOf(root), firstSeriesMode = series && modeOf(series)
  const mode = rootMode === undefined || rootMode === 'none' ? firstSeriesMode ?? rootMode : rootMode
  return { ...(mode === undefined ? {} : { mode }), ...(firstSeriesMode === undefined ? {} : { firstSeriesMode }) }
}
