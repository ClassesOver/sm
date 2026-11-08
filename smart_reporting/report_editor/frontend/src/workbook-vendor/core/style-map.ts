import { ooxmlRotationToUniver, univerRotationToOoxml } from '../../workbook-rotation'
/// Style mapping between the engine's stylesheet model and Univer's
/// IStyleData, through a renderer-neutral LogicalStyle both sides share.
/// Import: OOXML xf → LogicalStyle → Univer style entry.
/// Save diff: Univer style entry → LogicalStyle, compared against the import
/// snapshot to emit WorkbookStyleEdit deltas.

import {
  fillDisplayColor,
  resolveStyleColor,
  type FillSpec,
  type StyleColor,
} from '@sheets-web/xlsx-engine/style-color'
import {
  formatCodeFor,
  type Stylesheet,
  type XfInfo,
} from '@sheets-web/xlsx-engine/style-read'
import type { WorkbookStyleEdit } from '@sheets-web/xlsx-engine/edit-schemas'

/// Renderer-neutral style projection; undefined = the file's default.
export interface LogicalStyle {
  bold?: boolean | undefined
  italic?: boolean | undefined
  underline?: boolean | undefined
  strikethrough?: boolean | undefined
  fontSize?: number | undefined
  fontFamily?: string | undefined
  /// resolved #RRGGBB
  fontColor?: string | undefined
  fillColor?: string | undefined
  hAlign?: 'left' | 'center' | 'right' | 'justify' | undefined
  vAlign?: 'top' | 'middle' | 'bottom' | undefined
  textRotation?: number | undefined
  wrap?: boolean | undefined
  numberFormat?: string | undefined
  /// border edges; undefined edge = none/inherited
  borderTop?: LogicalBorderEdge | undefined
  borderBottom?: LogicalBorderEdge | undefined
  borderLeft?: LogicalBorderEdge | undefined
  borderRight?: LogicalBorderEdge | undefined
}

export interface LogicalBorderEdge {
  style: string
  color?: string | undefined
}

/// OOXML border style names ↔ Univer BorderStyleTypes numbers.
const UNIVER_BORDER_STYLE: ReadonlyMap<string, number> = new Map([
  ['thin', 1],
  ['hair', 2],
  ['dotted', 3],
  ['dashed', 4],
  ['dashDot', 5],
  ['dashDotDot', 6],
  ['double', 7],
  ['medium', 8],
  ['mediumDashed', 9],
  ['mediumDashDot', 10],
  ['mediumDashDotDot', 11],
  ['slantDashDot', 12],
  ['thick', 13],
])

const OOXML_BORDER_STYLE_BY_UNIVER: ReadonlyMap<number, string> = new Map(
  [...UNIVER_BORDER_STYLE].map(([name, id]) => [id, name]),
)

export function univerBorderStyleId(style: string): number | undefined {
  return UNIVER_BORDER_STYLE.get(style)
}

export function ooxmlBorderStyleName(id: number): string | undefined {
  return OOXML_BORDER_STYLE_BY_UNIVER.get(id)
}

/// OOXML xf + stylesheet → LogicalStyle (theme colors resolved to rgb).
export function logicalStyleOf(
  styles: Stylesheet,
  xf: XfInfo | undefined,
  palette: readonly string[] | undefined,
): LogicalStyle | undefined {
  if (!xf) return undefined
  const font = styles.fonts[xf.fontId]
  const fill = styles.fills[xf.fillId] ?? null
  const alignment = xf.alignment
  const style: LogicalStyle = {}
  if (font?.bold) style.bold = true
  if (font?.italic) style.italic = true
  if (font?.underline && font.underline !== 'none') style.underline = true
  if (font?.strikethrough) style.strikethrough = true
  if (font?.size !== undefined) style.fontSize = font.size
  if (font?.family) style.fontFamily = font.family
  if (font?.color !== undefined) style.fontColor = resolveStyleColor(font.color, palette)
  if (fill) {
    const display = fillDisplayColor(fill as FillSpec)
    if (display !== undefined) style.fillColor = resolveStyleColor(display, palette)
  }
  if (alignment?.horizontal) {
    style.hAlign =
      alignment.horizontal === 'center'
        ? 'center'
        : alignment.horizontal === 'right'
          ? 'right'
          : alignment.horizontal === 'justify' || alignment.horizontal === 'distributed'
            ? 'justify'
            : 'left'
  }
  if (alignment?.vertical) {
    style.vAlign =
      alignment.vertical === 'center' ? 'middle' : alignment.vertical === 'bottom' ? 'bottom' : 'top'
  }
  if (alignment?.textRotation !== undefined) style.textRotation = alignment.textRotation
  if (alignment?.wrapText) style.wrap = true
  const border = styles.borders[xf.borderId]
  if (border?.left) style.borderLeft = logicalEdge(border.left, palette)
  if (border?.right) style.borderRight = logicalEdge(border.right, palette)
  if (border?.top) style.borderTop = logicalEdge(border.top, palette)
  if (border?.bottom) style.borderBottom = logicalEdge(border.bottom, palette)
  const code = formatCodeFor(styles, xf)
  if (code !== 'General') style.numberFormat = code
  return Object.keys(style).length > 0 ? style : undefined
}

function logicalEdge(
  edge: { style: string; color: StyleColor | undefined },
  palette: readonly string[] | undefined,
): LogicalBorderEdge {
  return {
    style: edge.style,
    ...(edge.color !== undefined ? { color: resolveStyleColor(edge.color, palette) } : {}),
  }
}

/// Univer's IStyleData shape (subset the importer writes and the diff reads).
export interface UniverStyleData {
  ff?: string | undefined
  fs?: number | undefined
  it?: number | undefined
  bl?: number | undefined
  ul?: { s?: number | undefined } | undefined
  st?: { s?: number | undefined } | undefined
  cl?: { rgb?: string | undefined } | undefined
  bg?: { rgb?: string | undefined } | undefined
  ht?: number | undefined
  vt?: number | undefined
  tr?: { a?: number; v?: number } | undefined
  tb?: number | undefined
  n?: { pattern?: string | undefined } | undefined
  bd?: UniverBorderData | undefined
}

export interface UniverBorderData {
  t?: UniverBorderEdge | undefined
  r?: UniverBorderEdge | undefined
  b?: UniverBorderEdge | undefined
  l?: UniverBorderEdge | undefined
}

export interface UniverBorderEdge {
  s?: number | undefined
  cl?: { rgb?: string | undefined } | undefined
}

const HORIZ_FROM_UNIVER: Record<number, LogicalStyle['hAlign']> = {
  1: 'left',
  2: 'center',
  3: 'right',
  4: 'justify',
  5: 'justify',
  6: 'justify',
}
const VERT_FROM_UNIVER: Record<number, LogicalStyle['vAlign']> = {
  1: 'top',
  2: 'middle',
  3: 'bottom',
}

/// LogicalStyle → Univer style entry. Wrap is written as wrap-word (2).
export function toUniverStyle(style: LogicalStyle): UniverStyleData {
  const out: UniverStyleData = {}
  if (style.bold !== undefined) out.bl = style.bold ? 1 : 0
  if (style.italic !== undefined) out.it = style.italic ? 1 : 0
  if (style.underline !== undefined) out.ul = style.underline ? { s: 1 } : { s: 0 }
  if (style.strikethrough !== undefined) out.st = style.strikethrough ? { s: 1 } : { s: 0 }
  if (style.fontSize !== undefined) out.fs = style.fontSize
  if (style.fontFamily !== undefined) out.ff = style.fontFamily
  if (style.fontColor !== undefined) out.cl = { rgb: style.fontColor }
  if (style.fillColor !== undefined) out.bg = { rgb: style.fillColor }
  if (style.hAlign !== undefined) {
    out.ht =
      style.hAlign === 'left' ? 1 : style.hAlign === 'center' ? 2 : style.hAlign === 'right' ? 3 : 4
  }
  if (style.vAlign !== undefined) {
    out.vt = style.vAlign === 'top' ? 1 : style.vAlign === 'middle' ? 2 : 3
  }
  if (style.textRotation !== undefined) out.tr = ooxmlRotationToUniver(style.textRotation)
  if (style.wrap !== undefined) out.tb = style.wrap ? 2 : 1
  if (style.numberFormat !== undefined) out.n = { pattern: style.numberFormat }
  const bd = toUniverBorder(style)
  if (bd !== undefined) out.bd = bd
  return out
}

function toUniverBorder(style: LogicalStyle): UniverBorderData | undefined {
  const edge = (value: LogicalBorderEdge | undefined): UniverBorderEdge | undefined => {
    if (value === undefined) return undefined
    const id = univerBorderStyleId(value.style)
    return {
      ...(id !== undefined ? { s: id } : {}),
      ...(value.color !== undefined ? { cl: { rgb: value.color } } : {}),
    }
  }
  const bd: UniverBorderData = {
    ...(edge(style.borderTop) !== undefined ? { t: edge(style.borderTop) } : {}),
    ...(edge(style.borderRight) !== undefined ? { r: edge(style.borderRight) } : {}),
    ...(edge(style.borderBottom) !== undefined ? { b: edge(style.borderBottom) } : {}),
    ...(edge(style.borderLeft) !== undefined ? { l: edge(style.borderLeft) } : {}),
  }
  return Object.keys(bd).length > 0 ? bd : undefined
}

/// Univer style entry → LogicalStyle (for the save-time diff).
export function fromUniverStyle(data: UniverStyleData): LogicalStyle {
  const style: LogicalStyle = {}
  if (data.bl !== undefined) style.bold = data.bl === 1
  if (data.it !== undefined) style.italic = data.it === 1
  if (data.ul?.s !== undefined) style.underline = data.ul.s === 1
  if (data.st?.s !== undefined) style.strikethrough = data.st.s === 1
  if (data.fs !== undefined) style.fontSize = data.fs
  if (data.ff !== undefined) style.fontFamily = data.ff
  if (data.cl?.rgb !== undefined) style.fontColor = data.cl.rgb
  if (data.bg?.rgb !== undefined) style.fillColor = data.bg.rgb
  if (data.ht !== undefined && HORIZ_FROM_UNIVER[data.ht] !== undefined) {
    style.hAlign = HORIZ_FROM_UNIVER[data.ht]
  }
  if (data.vt !== undefined && VERT_FROM_UNIVER[data.vt] !== undefined) {
    style.vAlign = VERT_FROM_UNIVER[data.vt]
  }
  const rotation = univerRotationToOoxml(data.tr)
  if (rotation !== undefined) style.textRotation = rotation
  if (data.tb !== undefined) style.wrap = data.tb === 2
  if (data.n?.pattern !== undefined && data.n.pattern !== 'General') {
    style.numberFormat = data.n.pattern
  }
  const edge = (value: UniverBorderEdge | undefined): LogicalBorderEdge | undefined => {
    if (value === undefined || value.s === 0) return undefined
    const name = value.s === undefined ? undefined : ooxmlBorderStyleName(value.s)
    if (name === undefined) return undefined
    return {
      style: name,
      ...(value.cl?.rgb !== undefined ? { color: value.cl.rgb } : {}),
    }
  }
  const top = edge(data.bd?.t)
  const right = edge(data.bd?.r)
  const bottom = edge(data.bd?.b)
  const left = edge(data.bd?.l)
  if (top !== undefined) style.borderTop = top
  if (right !== undefined) style.borderRight = right
  if (bottom !== undefined) style.borderBottom = bottom
  if (left !== undefined) style.borderLeft = left
  return style
}

/// import snapshot vs current logical style → WorkbookStyleEdit; undefined
/// when nothing changed. A key absent from the read-back means the grid kept
/// the inherited format (Univer styles only carry explicit overrides), so
/// absence is "unchanged", never "cleared" — an explicit false / 'General'
/// in the read-back is what expresses a user-facing reset.
export function styleDelta(
  before: LogicalStyle | undefined,
  after: LogicalStyle | undefined,
): WorkbookStyleEdit | undefined {
  const keys: ReadonlyArray<keyof LogicalStyle> = [
    'bold',
    'italic',
    'underline',
    'strikethrough',
    'fontSize',
    'fontFamily',
    'fontColor',
    'fillColor',
    'hAlign',
    'vAlign',
    'textRotation',
    'wrap',
    'numberFormat',
    'borderTop',
    'borderBottom',
    'borderLeft',
    'borderRight',
  ]
  const delta: Record<string, unknown> = {}
  for (const key of keys) {
    const a = before?.[key]
    const b = after?.[key]
    if (a === b || (key === 'textRotation' && (a ?? 0) === (b ?? 0))) continue
    if (b === undefined) continue // inherited: the grid kept the file's format
    delta[univerKeyToEditKey(key)] = b
  }
  if (Object.keys(delta).length === 0) return undefined
  return delta as WorkbookStyleEdit
}

const KEY_MAP: Record<string, string> = {
  bold: 'bold',
  italic: 'italic',
  underline: 'underline',
  strikethrough: 'strikethrough',
  fontSize: 'fontSize',
  fontFamily: 'fontFamily',
  fontColor: 'fontColor',
  fillColor: 'fillColor',
  hAlign: 'horizontalAlignment',
  vAlign: 'verticalAlignment',
  textRotation: 'textRotation',
  wrap: 'wrapText',
  numberFormat: 'numberFormat',
  borderTop: 'borderTop',
  borderBottom: 'borderBottom',
  borderLeft: 'borderLeft',
  borderRight: 'borderRight',
}

function univerKeyToEditKey(key: keyof LogicalStyle): string {
  return KEY_MAP[key] ?? key
}
