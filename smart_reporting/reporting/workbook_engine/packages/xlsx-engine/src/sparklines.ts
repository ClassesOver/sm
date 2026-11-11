/// Sparklines (迷你图): x14 extension read/write. Excel stores them in the
/// worksheet's root <extLst> under the 2009/9 x14 namespace. The write side
/// REPLACES this sheet's sparkline group set (the AI payload carries the full
/// desired state); the read side feeds the grid render bridge.

import { parseRange, rangeCellCount } from './cell-address'
import { createBufferEntrySource } from './zip'
import { escapeXmlText } from './xml'
import { SaxesParser } from 'saxes'

export class SparklineError extends Error {}

export type SparklineKind = 'line' | 'column' | 'winLoss'

export interface SparklineSpec {
  readonly kind: SparklineKind
  /// single rectangular source range, e.g. "B2:F2"
  readonly source: string
  /// 限定来源表的真实名称；缺省才表示宿主表。
  readonly sourceSheet?: string | undefined
  /// single target cell that hosts the sparkline, e.g. "G2"
  readonly target: string
  /// series stroke/fill color, default #376092 (Excel default blue)
  readonly color?: string | undefined
  readonly negativeColor?: string | undefined
  /// line sparklines: draw point markers
  readonly markers?: boolean | undefined
  /// winLoss/column: draw the axis for zero
  readonly showAxis?: boolean | undefined
}

const X14_URI = '{05C60535-1F16-4fd2-B633-F4F36F0B64E0}'
const EXT_PATTERN =
  /<ext\b[^>]*uri="\{05C60535-1F16-4fd2-B633-F4F36F0B64E0\}"[^>]*>([\s\S]*?)<\/ext>/

const VALID_COLOR = /^#[0-9A-Fa-f]{6}$/

const X14_NS = 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
const XM_NS = 'http://schemas.microsoft.com/office/excel/2006/main'

/** 严格识别单个引用；不能把无法定位的来源降级为当前工作表。 */
export function parseSparklineSourceReference(reference: string): { source: string; sourceSheet?: string } | undefined {
  const match = reference.trim().match(/^(?:(?:'((?:[^']|'')+)'|([\p{L}_][\p{L}\p{N}_.]*))!)?(\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}(?::\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})?)$/u)
  if (!match) return undefined
  const sourceSheet = match[1]?.replaceAll("''", "'") ?? match[2]
  if (sourceSheet !== undefined && (!sourceSheet.length || sourceSheet.length > 31 || /[\[\]:\\/?*]/.test(sourceSheet))) return undefined
  const source = match[3]!, bounds = parseRange(source)
  if (bounds.endRow >= 1048576 || bounds.endColumn >= 16384) return undefined
  return { source, ...(sourceSheet !== undefined ? { sourceSheet } : {}) }
}

/// 只读解析按 namespace 身份识别扩展，写入器仍保留各自原有语义。
export function readSparklines(worksheetXml: string): SparklineSpec[] {
  const specs: SparklineSpec[] = [], parser = new SaxesParser({ xmlns: true })
  const stack: { local: string; uri: string }[] = []
  let extensionDepth = -1, groupDepth = -1, entryDepth = -1
  let group: { kind: SparklineKind; color?: string; negativeColor?: string; markers?: boolean; showAxis?: boolean } | undefined
  let entry: { source?: string; target?: string; invalid?: boolean } | undefined
  let capture: 'source' | 'target' | undefined
  parser.on('doctype', () => { throw new Error('迷你图来源不支持 DOCTYPE') })
  parser.on('opentag', tag => {
    const attribute = (name: string) => Object.values(tag.attributes).find(attr => !attr.uri && attr.local === name)?.value
    const parent = stack.at(-1), depth = stack.length
    stack.push({ local: tag.local, uri: tag.uri })
    if (tag.uri === 'http://schemas.openxmlformats.org/spreadsheetml/2006/main' && tag.local === 'ext' && depth === 2 && parent?.local === 'extLst' && parent.uri === tag.uri && attribute('uri')?.toUpperCase() === X14_URI.toUpperCase()) extensionDepth = depth
    if (extensionDepth < 0) return
    if (tag.uri === X14_NS && tag.local === 'sparklineGroup' && depth === extensionDepth + 2 && parent?.uri === X14_NS && parent.local === 'sparklineGroups') {
      const type = attribute('type')
      group = type === undefined || type === 'line' || type === 'column' || type === 'stacked'
        ? { kind: type === 'stacked' ? 'winLoss' : type === 'column' ? 'column' : 'line',
            ...(['1', 'true'].includes(attribute('markers') ?? '') ? { markers: true } : {}),
            ...(['1', 'true'].includes(attribute('displayAxis') ?? '') ? { showAxis: true } : {}) } : undefined
      groupDepth = depth
    }
    if (!group) return
    if (tag.uri === X14_NS && tag.local === 'colorSeries' && depth === groupDepth + 1) {
      const rgb = attribute('rgb')
      if (rgb && /^[0-9A-Fa-f]{8}$/.test(rgb)) group.color = `#${rgb.slice(2).toUpperCase()}`
    }
    if (tag.uri === X14_NS && tag.local === 'colorNegative' && depth === groupDepth + 1) {
      const rgb = attribute('rgb')
      if (rgb && /^[0-9A-Fa-f]{8}$/.test(rgb)) group.negativeColor = `#${rgb.slice(2).toUpperCase()}`
    }
    if (tag.uri === X14_NS && tag.local === 'sparkline' && depth === groupDepth + 2 && parent?.uri === X14_NS && parent.local === 'sparklines') { entry = {}; entryDepth = depth }
    if (entry && depth > entryDepth + 1) entry.invalid = true
    if (entry && depth === entryDepth + 1 && tag.uri === XM_NS && ['f', 'sqref'].includes(tag.local)) {
      capture = tag.local === 'f' ? 'source' : 'target'
      // 重复的来源或宿主不属于可可靠读取的单个迷你图。
      if (entry[capture] !== undefined) entry.invalid = true
      entry[capture] = ''
    }
  })
  const text = (value: string) => { if (entry && capture && stack.length === entryDepth + 2) entry[capture] = (entry[capture] ?? '') + value }
  parser.on('text', text); parser.on('cdata', text)
  parser.on('closetag', tag => {
    const depth = stack.length - 1
    if (entry && depth === entryDepth + 1) capture = undefined
    if (entry && group && depth === entryDepth) {
      const source = parseSparklineSourceReference(entry.source ?? ''), target = entry.target?.trim()
      if (!entry.invalid && source && target && /^\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}$/.test(target)) {
        const bounds = parseRange(target)
        if (bounds.endRow < 1048576 && bounds.endColumn < 16384) specs.push({ ...group, ...source, target })
      }
      entry = undefined; entryDepth = -1; capture = undefined
    }
    if (depth === groupDepth && tag.uri === X14_NS) { group = undefined; groupDepth = -1 }
    if (depth === extensionDepth) extensionDepth = -1
    stack.pop()
  })
  // 损坏的 XML 不能留下前半段的可渲染对象。
  try { parser.write(worksheetXml).close() } catch { return [] }
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
  const groups: string[] = []
  const groupType = { line: 'line', column: 'column', winLoss: 'stacked' } as const
  for (const kind of ['line', 'column', 'winLoss'] as const) {
    const matching = new Map<string, SparklineSpec[]>()
    for (const spec of specs.filter((entry) => entry.kind === kind)) {
      const key = JSON.stringify([
        (spec.color ?? '#376092').toUpperCase(),
        kind === 'line' && spec.markers === true,
        spec.showAxis === true,
      ])
      const group = matching.get(key) ?? []
      group.push(spec)
      matching.set(key, group)
    }
    for (const group of matching.values()) {
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
          (group[0]!.showAxis ? 'displayAxis="1" ' : '') +
          'displayEmptyCellsAs="gap">' +
          `<x14:colorSeries rgb="FF${color}"/>` +
          '<x14:colorNegative rgb="FFD00000"/>' +
          `<x14:sparklines>${entries}</x14:sparklines>` +
          '</x14:sparklineGroup>',
      )
    }
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
    // Cell extensions can also contain extLst; only the root tail qualifies.
    const existing = /<extLst\b[^>]*>[\s\S]*?<\/extLst>\s*<\/worksheet>/.exec(xml)
    const empty = /<extLst\b[^>]*\/>\s*<\/worksheet>/.exec(xml)
    if (existing) {
      const at = xml.lastIndexOf('</extLst>')
      xml = xml.slice(0, at) + newExt + xml.slice(at)
    } else if (empty) {
      const at = empty.index
      const tag = empty[0].slice(0, empty[0].indexOf('/>') + 2)
      xml = xml.slice(0, at) + tag.replace(/\/>$/, `>${newExt}</extLst>`) + xml.slice(at + tag.length)
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
