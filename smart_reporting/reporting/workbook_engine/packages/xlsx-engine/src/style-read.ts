/// Read-only view of xl/styles.xml (plus the theme palette) for importing
/// resolved formats into the editor model. Ported from genoffice
/// xlsx-style-read.ts and extended with fonts / borders / alignment / numFmts.

import type { FillSpec, PatternType, StyleColor } from './style-color'
import { PATTERN_TYPES } from './style-color'
import { extractElements, readCoreAttribute, sectionInner } from './xml'

export interface FontInfo {
  bold: boolean
  italic: boolean
  strikethrough: boolean
  underline: 'none' | 'single' | 'double'
  size: number | undefined
  family: string | undefined
  color: StyleColor | undefined
  vertAlign?: 'superscript' | 'subscript' | undefined
}

export interface BorderEdge {
  style: string
  color: StyleColor | undefined
}

export interface BorderInfo {
  left: BorderEdge | undefined
  right: BorderEdge | undefined
  top: BorderEdge | undefined
  bottom: BorderEdge | undefined
}

export interface AlignmentInfo {
  horizontal: string | undefined
  vertical: string | undefined
  wrapText: boolean
  textRotation: number | undefined
  indent: number | undefined
}

export interface XfInfo {
  numFmtId: number
  fontId: number
  fillId: number
  borderId: number
  alignment: AlignmentInfo | undefined
}

export interface Stylesheet {
  /// custom numFmt id → format code (builtins live in BUILTIN_NUM_FMT_CODES)
  numFmts: ReadonlyMap<number, string>
  fonts: readonly FontInfo[]
  fills: readonly (FillSpec | null)[]
  borders: readonly BorderInfo[]
  cellXfs: readonly XfInfo[]
}

/// Builtin format codes the importer needs for display; id 14/22 are
/// regional short date / datetime and resolve through short-date.ts.
export const BUILTIN_NUM_FMT_CODES: ReadonlyMap<number, string> = new Map([
  [0, 'General'],
  [1, '0'],
  [2, '0.00'],
  [3, '#,##0'],
  [4, '#,##0.00'],
  [9, '0%'],
  [10, '0.00%'],
  [11, '0.00E+00'],
  [12, '# ?/?'],
  [13, '# ??/??'],
  [14, 'm/d/yyyy'],
  [15, 'd-mmm-yy'],
  [16, 'd-mmm'],
  [17, 'mmm-yy'],
  [18, 'h:mm AM/PM'],
  [19, 'h:mm:ss AM/PM'],
  [20, 'h:mm'],
  [21, 'h:mm:ss'],
  [22, 'm/d/yyyy h:mm'],
  [37, '#,##0 ;(#,##0)'],
  [38, '#,##0 ;[Red](#,##0)'],
  [39, '#,##0.00;(#,##0.00)'],
  [40, '#,##0.00;[Red](#,##0.00)'],
  [45, 'mm:ss'],
  [46, '[h]:mm:ss'],
  [47, 'mmss.0'],
  [48, '##0.0E+0'],
  [49, '@'],
])

export function formatCodeFor(styles: Stylesheet, xf: XfInfo): string {
  const custom = styles.numFmts.get(xf.numFmtId)
  if (custom !== undefined) return custom
  return BUILTIN_NUM_FMT_CODES.get(xf.numFmtId) ?? 'General'
}

export function parseStylesheet(stylesXml: string): Stylesheet {
  const numFmts = new Map<number, string>()
  for (const entry of extractElements(sectionInner(stylesXml, 'numFmts') ?? '', 'numFmt')) {
    const id = Number(readCoreAttribute(entry, 'numFmtId'))
    const code = readCoreAttribute(entry, 'formatCode')
    if (Number.isInteger(id) && code !== undefined) numFmts.set(id, decodeXml(code))
  }

  const fonts = extractElements(sectionInner(stylesXml, 'fonts') ?? '', 'font').map(parseFont)
  const fills = extractElements(sectionInner(stylesXml, 'fills') ?? '', 'fill').map(parseFill)
  const borders = extractElements(sectionInner(stylesXml, 'borders') ?? '', 'border').map(
    parseBorder,
  )
  const cellXfs = extractElements(sectionInner(stylesXml, 'cellXfs') ?? '', 'xf').map((xf) => ({
    numFmtId: Number(readCoreAttribute(xf, 'numFmtId') ?? 0),
    fontId: Number(readCoreAttribute(xf, 'fontId') ?? 0),
    fillId: Number(readCoreAttribute(xf, 'fillId') ?? 0),
    borderId: Number(readCoreAttribute(xf, 'borderId') ?? 0),
    alignment: parseAlignment(xf),
  }))
  return { numFmts, fonts, fills, borders, cellXfs }
}

function parseFont(fontXml: string): FontInfo {
  const underline = /<u\b([^>]*?)\/?>/.test(fontXml)
    ? readCoreAttribute(fontXml, 'val') === 'double'
      ? ('double' as const)
      : ('single' as const)
    : ('none' as const)
  return {
    bold: /<b\b[^>]*\/?>/.test(fontXml),
    italic: /<i\b[^>]*\/?>/.test(fontXml),
    strikethrough: /<strike\b[^>]*\/?>/.test(fontXml),
    underline,
    size: numberAttribute(fontXml, 'sz', 'val'),
    family: decodeXml(readCoreAttribute(fontXml.match(/<name\b[^>]*\/?>/)?.[0] ?? '', 'val') ?? ''),
    color: parseColor(fontXml.match(/<color\b[^>]*\/?>/)?.[0] ?? ''),
    vertAlign: (() => {
      const value = readCoreAttribute(fontXml.match(/<vertAlign\b[^>]*\/?>/)?.[0] ?? '', 'val')
      return value === 'superscript' || value === 'subscript' ? value : undefined
    })(),
  }
}

function parseBorder(borderXml: string): BorderInfo {
  return {
    left: parseBorderEdge(borderXml, 'left'),
    right: parseBorderEdge(borderXml, 'right'),
    top: parseBorderEdge(borderXml, 'top'),
    bottom: parseBorderEdge(borderXml, 'bottom'),
  }
}

function parseBorderEdge(borderXml: string, edge: string): BorderEdge | undefined {
  const element = borderXml.match(
    new RegExp(`<${edge}\\b[^>]*/>|<${edge}\\b[^>]*>[\\s\\S]*?</${edge}>`),
  )?.[0]
  if (element === undefined) return undefined
  const style = readCoreAttribute(element, 'style')
  if (style === undefined) return undefined
  return {
    style,
    color: parseColor(element.match(/<color\b[^>]*\/?>/)?.[0] ?? ''),
  }
}

function parseAlignment(xfXml: string): AlignmentInfo | undefined {
  const element = xfXml.match(/<alignment\b[^>]*\/?>/)?.[0]
  if (element === undefined) return undefined
  const rotation = numberAttribute(element, 'textRotation', undefined)
  const indent = numberAttribute(element, 'indent', undefined)
  return {
    horizontal: readCoreAttribute(element, 'horizontal'),
    vertical: readCoreAttribute(element, 'vertical'),
    wrapText: readCoreAttribute(element, 'wrapText') === '1',
    textRotation: rotation ?? undefined,
    indent: indent ?? undefined,
  }
}

function numberAttribute(
  element: string,
  tagName: string,
  attribute: string | undefined,
): number | undefined {
  const tag = attribute === undefined ? element : element.match(new RegExp(`<${tagName}\\b[^>]*\\/?>`))?.[0]
  if (tag === undefined) return undefined
  const raw = readCoreAttribute(tag, attribute ?? tagName)
  if (raw === undefined) return undefined
  const value = Number(raw)
  return Number.isFinite(value) ? value : undefined
}

function parseFill(fillXml: string): FillSpec | null {
  const gradient = fillXml.match(/<gradientFill\b([^>]*)>([\s\S]*?)<\/gradientFill>/)
  if (gradient) {
    const attrs = gradient[1] ?? ''
    const stops = [
      ...(gradient[2] ?? '').matchAll(
        /<stop\b[^>]*position="([^"]*)"[^>]*>([\s\S]*?)<\/stop>/g,
      ),
    ]
      .map((stop) => {
        const color = parseColor((stop[2] ?? '').match(/<color\b[^>]*\/?>/)?.[0] ?? '')
        return color === undefined ? null : { position: Number(stop[1]), color }
      })
      .filter((stop): stop is { position: number; color: StyleColor } => stop !== null)
    if (stops.length < 2) return null
    const type = readCoreAttribute(attrs, 'type') === 'path' ? 'path' : undefined
    const num = (name: string): number | undefined => {
      const value = readCoreAttribute(attrs, name)
      return value === undefined ? undefined : Number(value)
    }
    return {
      gradient: {
        ...(type ? { type } : {}),
        ...(type ? {} : num('degree') !== undefined ? { angle: num('degree') } : {}),
        ...(type && num('left') !== undefined ? { left: num('left') } : {}),
        ...(type && num('right') !== undefined ? { right: num('right') } : {}),
        ...(type && num('top') !== undefined ? { top: num('top') } : {}),
        ...(type && num('bottom') !== undefined ? { bottom: num('bottom') } : {}),
        stops,
      },
    }
  }

  const pattern = fillXml.match(/<patternFill\b([^>]*?)(?:\/>|>([\s\S]*?)<\/patternFill>)/)
  if (!pattern) return null
  const patternType = readCoreAttribute(pattern[1] ?? '', 'patternType')
  if (patternType === undefined || patternType === 'none') return null
  if (!(PATTERN_TYPES as readonly string[]).includes(patternType)) return null
  const inner = pattern[2] ?? ''
  const fg = parseColor(inner.match(/<fgColor\b[^>]*\/?>/)?.[0] ?? '')
  const bg = parseColor(inner.match(/<bgColor\b[^>]*\/?>/)?.[0] ?? '')
  // a pattern without a foreground is Excel's "automatic" color: not a choice to echo
  if (fg === undefined) return null
  return { pattern: patternType as PatternType, fg, ...(bg === undefined ? {} : { bg }) }
}

/// CT_Color → StyleColor; indexed / auto / system colors have no stable echo
export function parseColor(colorXml: string): StyleColor | undefined {
  if (colorXml === '') return undefined
  const theme = readCoreAttribute(colorXml, 'theme')
  if (theme !== undefined) {
    const index = Number(theme)
    if (!Number.isInteger(index) || index < 0 || index > 11) return undefined
    const tint = readCoreAttribute(colorXml, 'tint')
    const value = tint === undefined ? 0 : Number(tint)
    return value === 0 || !Number.isFinite(value)
      ? { theme: index }
      : { theme: index, tint: Math.round(value * 1e6) / 1e6 }
  }
  const rgb = readCoreAttribute(colorXml, 'rgb')
  if (rgb === undefined) return undefined
  const hex = rgb.length === 8 ? rgb.slice(2) : rgb
  return /^[0-9A-Fa-f]{6}$/.test(hex) ? `#${hex.toUpperCase()}` : undefined
}

function decodeXml(input: string): string {
  return input.replace(
    /&(?:#x([0-9A-Fa-f]+)|#([0-9]+)|(quot|apos|lt|gt|amp));/g,
    (match, hex: string | undefined, dec: string | undefined, named: string | undefined) => {
      if (named === 'quot') return '"'
      if (named === 'apos') return "'"
      if (named === 'lt') return '<'
      if (named === 'gt') return '>'
      if (named === 'amp') return '&'
      if (named !== undefined) return match
      const code = hex !== undefined ? Number.parseInt(hex, 16) : Number(dec)
      return code <= 0x10ffff ? String.fromCodePoint(code) : match
    },
  )
}

/// Theme palette in styles.xml theme-index order (Excel swaps the dk/lt
/// pairs relative to clrScheme order): lt1, dk1, lt2, dk2, accent1-6,
/// hlink, folHlink.
export function parseThemePalette(themeXml: string | undefined): string[] | undefined {
  if (themeXml === undefined) return undefined
  const scheme = themeXml.match(/<a:clrScheme\b[^>]*>([\s\S]*?)<\/a:clrScheme>/)?.[1]
  if (scheme === undefined) return undefined
  const slot = (name: string): string | undefined => {
    const element = scheme.match(
      new RegExp(`<a:${name}\\b[^>]*>([\\s\\S]*?)</a:${name}>`),
    )?.[1]
    if (element === undefined) return undefined
    const srgb = element.match(/<a:srgbClr\b[^>]*val="([^"]*)"/)?.[1]
    if (srgb !== undefined && /^[0-9A-Fa-f]{6}$/.test(srgb)) return `#${srgb.toUpperCase()}`
    const sys = element.match(/<a:sysClr\b[^>]*lastClr="([^"]*)"/)?.[1]
    if (sys !== undefined && /^[0-9A-Fa-f]{6}$/.test(sys)) return `#${sys.toUpperCase()}`
    return undefined
  }
  const dk1 = slot('dk1') ?? '#000000'
  const lt1 = slot('lt1') ?? '#FFFFFF'
  const dk2 = slot('dk2') ?? '#44546A'
  const lt2 = slot('lt2') ?? '#E7E6E6'
  const accents = [1, 2, 3, 4, 5, 6].map((n) => slot(`accent${n}`))
  const hlink = slot('hlink')
  const folHlink = slot('folHlink')
  const palette = [
    lt1,
    dk1,
    lt2,
    dk2,
    ...accents,
    hlink ?? '#0563C1',
    folHlink ?? '#954F72',
  ]
  return palette.every((color) => color !== undefined) ? palette : undefined
}
