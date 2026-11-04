/// Sparklines (迷你图): x14 extension read/write. Excel stores them in the
/// worksheet's root <extLst> under the 2009/9 x14 namespace. The write side
/// REPLACES this sheet's sparkline group set (the AI payload carries the full
/// desired state); the read side feeds the grid render bridge.

import { parseRange, rangeCellCount } from './cell-address'
import { createBufferEntrySource } from './zip'
import { decodeXmlText, escapeXmlText } from './xml'

export class SparklineError extends Error {}

export type SparklineKind = 'line' | 'column' | 'winLoss'

export interface SparklineSpec {
  readonly kind: SparklineKind
  /// single rectangular source range, e.g. "B2:F2"
  readonly source: string
  /// single target cell that hosts the sparkline, e.g. "G2"
  readonly target: string
  /// series stroke/fill color, default #376092 (Excel default blue)
  readonly color?: string | undefined
  /// line sparklines: draw point markers
  readonly markers?: boolean | undefined
  /// winLoss/column: draw the axis for zero
  readonly showAxis?: boolean | undefined
}

const X14_URI = '{05C60535-1F16-4fd2-B633-F4F36F0B64E0}'
const EXT_PATTERN =
  /<ext\b[^>]*uri="\{05C60535-1F16-4fd2-B633-F4F36F0B64E0\}"[^>]*>([\s\S]*?)<\/ext>/

const VALID_COLOR = /^#[0-9A-Fa-f]{6}$/

/// Parse this sheet's sparklines out of its worksheet XML.
export function readSparklines(worksheetXml: string): SparklineSpec[] {
  const ext = worksheetXml.match(EXT_PATTERN)
  if (!ext) return []
  const specs: SparklineSpec[] = []
  for (const group of (ext[1] ?? '').matchAll(
    /<x14:sparklineGroup\b[^>]*>([\s\S]*?)<\/x14:sparklineGroup>/g,
  )) {
    const head = group[0] ?? ''
    const body = group[1] ?? ''
    const type = head.match(/\btype="([\w-]+)"/)?.[1]
    const markers = /\bmarkers="1"/.test(head)
    const showAxis = /\bdisplayAxis="1"/.test(head)
    const color = head
      .match(/<x14:colorSeries\b[^>]*\brgb="([0-9A-Fa-f]{8})"/)?.[1]
      ?.slice(2)
    for (const sparkline of body.matchAll(
      /<x14:sparkline\b[^>]*>([\s\S]*?)<\/x14:sparkline>/g,
    )) {
      const inner = sparkline[1] ?? ''
      const source = inner.match(/<xm:f>([\s\S]*?)<\/xm:f>/)?.[1]
      const target = inner.match(/<xm:sqref>([\s\S]*?)<\/xm:sqref>/)?.[1]
      if (source === undefined || target === undefined) continue
      const reference = source.replace(/^[^!]*!/, '')
      specs.push({
        kind: type === 'column' ? 'column' : type === 'stacked' ? 'winLoss' : 'line',
        source: decodeXmlText(reference),
        target: decodeXmlText(target.trim()),
        ...(color !== undefined ? { color: `#${color.toUpperCase()}` } : {}),
        ...(markers ? { markers: true } : {}),
        ...(showAxis ? { showAxis: true } : {}),
      })
    }
  }
  return specs
}

function validateSpecs(specs: readonly SparklineSpec[]): void {
  const targets = new Set<string>()
  for (const spec of specs) {
    const bounds = parseRange(spec.source)
    if (rangeCellCount(bounds) > 1000) {
      throw new SparklineError(`迷你图源区域 ${spec.source} 超出 1000 格上限。`)
    }
    parseRange(spec.target) // must parse
    if (spec.target.includes(':')) {
      throw new SparklineError(`迷你图目标 ${spec.target} 必须是单个单元格。`)
    }
    if (spec.color !== undefined && !VALID_COLOR.test(spec.color)) {
      throw new SparklineError(`迷你图颜色 ${spec.color} 必须是 #RRGGBB。`)
    }
    const key = spec.target.toUpperCase()
    if (targets.has(key)) {
      throw new SparklineError(`迷你图目标 ${spec.target} 重复。`)
    }
    targets.add(key)
  }
}

function buildExt(specs: readonly SparklineSpec[]): string {
  const byKind = (kind: SparklineKind) => specs.filter((spec) => spec.kind === kind)
  const groups: string[] = []
  const groupType = { line: 'line', column: 'column', winLoss: 'stacked' } as const
  for (const kind of ['line', 'column', 'winLoss'] as const) {
    const group = byKind(kind)
    if (group.length === 0) continue
    const color = (group[0]!.color ?? '#376092').replace('#', '').toUpperCase()
    const entries = group
      .map(
        (spec) =>
          `<x14:sparkline><xm:f>${escapeXmlText(spec.source)}</xm:f>` +
          `<xm:sqref>${escapeXmlText(spec.target)}</xm:sqref></x14:sparkline>`,
      )
      .join('')
    groups.push(
      `<x14:sparklineGroup type="${groupType[kind]}" ` +
        (kind === 'line' && group[0]!.markers ? 'markers="1" ' : '') +
        (spec_axis(group) ? 'displayAxis="1" ' : '') +
        'displayEmptyCellsAs="gap">' +
        `<x14:colorSeries rgb="FF${color}"/>` +
        '<x14:colorNegative rgb="FFD00000"/>' +
        `<x14:sparklines>${entries}</x14:sparklines>` +
        '</x14:sparklineGroup>',
    )
  }
  return (
    `<ext uri="${X14_URI}" ` +
    'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main" ' +
    'xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">' +
    '<x14:sparklineGroups>' +
    groups.join('') +
    '</x14:sparklineGroups></ext>'
  )
}

const spec_axis = (group: readonly SparklineSpec[]): boolean =>
  group.some((spec) => spec.showAxis === true)

/// Replace this sheet's sparkline set in the worksheet's root extLst.
export async function applySparklines(
  sourceBytes: Uint8Array,
  sheetName: string,
  specs: readonly SparklineSpec[],
): Promise<Uint8Array> {
  validateSpecs(specs)
  const source = await createBufferEntrySource(sourceBytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const { parseSheetElements, resolveWorksheetPath } = await import('./workbook-read')
  const element = parseSheetElements(workbookXml).find((entry) => entry.name === sheetName)
  if (!element?.relationshipId) {
    throw new SparklineError(`workbook.xml 中找不到工作表 "${sheetName}"。`)
  }
  const path = await resolveWorksheetPath(source, element.relationshipId)
  let xml = await source.readText(path)

  const newExt = buildExt(specs)
  if (specs.length === 0) {
    // drop the sparkline ext entirely; other extensions stay
    xml = xml.replace(EXT_PATTERN, '').replace(/<extLst>\s*<\/extLst>|<extLst\s*\/>/, '')
  } else if (EXT_PATTERN.test(xml)) {
    // replace only the sparkline ext; other extensions stay byte-identical
    xml = xml.replace(EXT_PATTERN, newExt)
  } else {
    const existing = xml.match(/<extLst\b[^>]*>[\s\S]*?<\/extLst>/)
    if (existing && existing.index !== undefined) {
      const at = existing.index + existing[0].length
      xml = xml.slice(0, at) + newExt + xml.slice(at)
    } else {
      // extLst is last in the worksheet schema; anchor on the closing tag
      xml = xml.replace(/<\/worksheet>/, `<extLst>${newExt}</extLst></worksheet>`)
    }
  }

  const { assemblePackage } = await import('./zip')
  const mutation = await assemblePackage(sourceBytes, {
    replaced: new Map([[path, xml]]),
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: [path],
  })
  return mutation.buffer
}
