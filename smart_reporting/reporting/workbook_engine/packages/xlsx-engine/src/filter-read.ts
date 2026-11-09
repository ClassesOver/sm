/// Sheet-level autoFilter reader, ported from the genoffice desktop reader
/// (native/xlsx-engine worksheet.rs): only the first sheet-level
/// `<autoFilter>` is the live filter (customSheetViews copies never count),
/// with per-column `filters` (values + blank + dateGroupItem) and
/// `customFilters` criteria. Color / icon / top10 / dynamic criteria have no
/// round-trip model here and mark the filter readOnly instead of being
/// silently dropped. The pinned genoffice build parses none of these extra
/// criteria (their filterColumns stay criteria-less and are dropped); the
/// date-group read model below follows the OOXML `<dateGroupItem>` shape
/// (ECMA-376 18.3.1.20: year/month/day/hour/minute/second + dateTimeGrouping,
/// several items per `<filters>` element alongside plain `<filter>` values).

import { parseRange, type RangeBounds } from './cell-address'
import { decodeXmlText, readXmlAttribute } from './xml'

export type SheetFilterDateGrouping = 'year' | 'month' | 'day' | 'hour' | 'minute' | 'second'

/// One OOXML `<dateGroupItem>`: a grouped date bucket. `dateTimeGrouping`
/// states the granularity; attributes above `year` are present exactly down
/// to that granularity (e.g. grouping "day" ⇒ year+month+day and nothing
/// deeper).
export interface SheetFilterDateGroup {
  year: number
  month?: number | undefined
  day?: number | undefined
  hour?: number | undefined
  minute?: number | undefined
  second?: number | undefined
  dateTimeGrouping: SheetFilterDateGrouping
}

export interface SheetFilterColumnModel {
  /// 0-based offset from the filter range's first column, per OOXML.
  colId: number
  values?: string[]
  blank?: boolean
  customs?: { and?: boolean; filters: { val: string; operator?: string }[] }
  /// Grouped date buckets of the column's `<filters>` element; they coexist
  /// with values/blank (same element) but never with customs (a filterColumn
  /// carries one criteria group per the schema choice).
  dateGroups?: SheetFilterDateGroup[]
}

export interface SheetFilterModel {
  /// Raw `ref` attribute of the worksheet-level autoFilter element.
  ref: string
  /// Parsed bounds of `ref`; absent when the producer wrote an unparseable ref.
  range?: RangeBounds
  /// Columns that carry at least one supported criterion, keyed by colId.
  columns: SheetFilterColumnModel[]
  /// Unsupported structure (color/icon/top10/dynamic criteria, or a
  /// ref this build cannot parse) — the write path refuses to overwrite.
  readOnlyReason?: string
}

/// Custom-filter operators the write path can serialize; absent means "equal".
export const FILTER_CUSTOM_OPERATORS = [
  'equal',
  'notEqual',
  'greaterThan',
  'greaterThanOrEqual',
  'lessThan',
  'lessThanOrEqual',
] as const

const UNSUPPORTED_CRITERIA =
  /<(?:[\w.-]+:)?(?:colorFilter|top10|dynamicFilter|iconFilter)\b/

/// Shared with the write path: overwriting such a filter would silently drop
/// criteria this build cannot represent (top10/dynamic stay rejected: neither
/// the pinned genoffice build nor pinned Univer 0.25.1 has a model for them).
export const UNSUPPORTED_READ_REASON = '筛选含颜色、图标、前十或动态条件，暂不能编辑回写'

/// Sections that may carry their own autoFilter copies (customSheetViews) or
/// pivot definitions (pivotTables live in their own parts, but a stray
/// `<pivotTableDefinition>`-embedded autoFilter must never be picked up).
/// Only matches outside these spans count.
const SHEET_LEVEL_EXCLUSIONS = /<customSheetViews\b[\s\S]*?<\/customSheetViews>|<customSheetViews\b[^>]*\/>/g

export interface FilterElement {
  readonly xml: string
  readonly start: number
  readonly end: number
}

/// First worksheet-level `<autoFilter>` in document order, skipping copies
/// inside customSheetViews spans. `filterPattern` matches both the
/// self-closing and the criteria-bearing forms.
export const AUTO_FILTER_PATTERN = /<autoFilter\b[^>]*\/>|<autoFilter\b[^>]*>[\s\S]*?<\/autoFilter>/g

export function firstSheetLevelAutoFilter(worksheetXml: string): FilterElement | null {
  const excluded: Array<[number, number]> = []
  for (const match of worksheetXml.matchAll(SHEET_LEVEL_EXCLUSIONS)) {
    excluded.push([match.index ?? 0, (match.index ?? 0) + match[0].length])
  }
  const inside = (at: number) => excluded.some(([start, end]) => at >= start && at < end)
  for (const match of worksheetXml.matchAll(AUTO_FILTER_PATTERN)) {
    if (inside(match.index ?? 0)) continue
    return { xml: match[0], start: match.index ?? 0, end: (match.index ?? 0) + match[0].length }
  }
  return null
}

/// Attribute chains a `dateTimeGrouping` granularity requires: the attributes
/// down to the grouping must be present, nothing deeper (ECMA-376 18.3.1.20).
const DATE_GROUP_CHAINS: Record<SheetFilterDateGrouping, string[]> = {
  year: [],
  month: ['month'],
  day: ['month', 'day'],
  hour: ['month', 'day', 'hour'],
  minute: ['month', 'day', 'hour', 'minute'],
  second: ['month', 'day', 'hour', 'minute', 'second'],
}

const DATE_GROUP_ATTR_LIMITS: Record<string, [number, number]> = {
  month: [1, 12], day: [1, 31], hour: [0, 23], minute: [0, 59], second: [0, 59],
}

function parseDateGroupItem(raw: string): SheetFilterDateGroup | { error: string } {
  const year = readXmlAttribute(raw, 'year')
  if (year === undefined || !/^\d+$/.test(year) || Number(year) < 1 || Number(year) > 9999) {
    return { error: '日期分组条件缺少有效年份' }
  }
  const group: SheetFilterDateGroup = { year: Number(year) } as SheetFilterDateGroup
  for (const [attribute, [min, max]] of Object.entries(DATE_GROUP_ATTR_LIMITS)) {
    const value = readXmlAttribute(raw, attribute)
    if (value === undefined) continue
    if (!/^\d+$/.test(value) || Number(value) < min || Number(value) > max) {
      return { error: `日期分组条件 ${attribute} 超出范围` }
    }
    ;(group as unknown as Record<string, number | undefined>)[attribute] = Number(value)
  }
  const grouping = readXmlAttribute(raw, 'dateTimeGrouping')
  if (grouping !== undefined && !(DATE_GROUP_CHAINS as Record<string, unknown>)[grouping]) {
    return { error: `日期分组条件粒度 ${grouping} 无效` }
  }
  const present = Object.keys(DATE_GROUP_ATTR_LIMITS).filter((attribute) => attribute in group)
  const chain = grouping !== undefined
    ? DATE_GROUP_CHAINS[grouping as SheetFilterDateGrouping]
    : // A missing dateTimeGrouping is inferred from the deepest attribute present.
      present
  for (const attribute of chain) {
    if (group[attribute as keyof SheetFilterDateGroup] === undefined) {
      return { error: '日期分组条件粒度与属性不匹配' }
    }
  }
  if (present.some((attribute) => !chain.includes(attribute))) {
    return { error: '日期分组条件粒度与属性不匹配' }
  }
  group.dateTimeGrouping = grouping !== undefined
    ? (grouping as SheetFilterDateGrouping)
    : (present.at(-1) as SheetFilterDateGrouping | undefined) ?? 'year'
  return group
}

function parseFilterColumn(raw: string): SheetFilterColumnModel | { error: string } {
  const colIdRaw = readXmlAttribute(raw, 'colId')
  if (colIdRaw === undefined || !/^\d+$/.test(colIdRaw)) return { error: '筛选列 colId 无效' }
  const colId = Number(colIdRaw)
  if (colId > 16383) return { error: '筛选列 colId 超出范围' }
  const column: SheetFilterColumnModel = { colId }
  let dateGroupCount = 0
  for (const filters of raw.match(/<filters\b[^>]*\/>|<filters\b[^>]*>[\s\S]*?<\/filters>/g) ?? []) {
    if (readXmlAttribute(filters, 'blank') === '1' || readXmlAttribute(filters, 'blank') === 'true') {
      column.blank = true
    }
    for (const filter of filters.match(/<filter\b[^>]*\/?>/g) ?? []) {
      const val = readXmlAttribute(filter, 'val')
      if (val !== undefined) (column.values ??= []).push(decodeXmlText(val))
    }
    for (const item of filters.match(/<dateGroupItem\b[^>]*\/?>/g) ?? []) {
      dateGroupCount += 1
      if ((column.dateGroups?.length ?? 0) + dateGroupCount > 1000) {
        return { error: '筛选列日期分组条件超出预算' }
      }
      const group = parseDateGroupItem(item)
      if ('error' in group) return group
      ;(column.dateGroups ??= []).push(group)
    }
  }
  // A dateGroupItem outside a `<filters>` element is invalid OOXML; fail
  // closed instead of silently dropping it.
  if ((raw.match(/<dateGroupItem\b/g) ?? []).length !== dateGroupCount) {
    return { error: '日期分组条件位置无效' }
  }
  const customs = raw.match(/<customFilters\b[^>]*\/>|<customFilters\b[^>]*>[\s\S]*?<\/customFilters>/)
  if (customs) {
    const items: { val: string; operator?: string }[] = []
    for (const custom of customs[0].match(/<customFilter\b[^>]*\/?>/g) ?? []) {
      const val = readXmlAttribute(custom, 'val')
      if (val === undefined) return { error: '筛选自定义条件缺少 val' }
      const operator = readXmlAttribute(custom, 'operator')
      items.push({ val: decodeXmlText(val), ...(operator === undefined || operator === 'equal' ? {} : { operator }) })
    }
    if (items.length > 0) {
      column.customs = {
        ...(readXmlAttribute(customs[0], 'and') === '1' || readXmlAttribute(customs[0], 'and') === 'true'
          ? { and: true }
          : {}),
        filters: items,
      }
    }
  }
  return column
}

/// Reads the live filter out of one worksheet part. Lenient by contract:
/// structural surprises become `readOnlyReason`, never a thrown error, so a
/// foreign producer's sheet still opens for every other feature.
export function readSheetFilter(worksheetXml: string): SheetFilterModel | null {
  try {
    const element = firstSheetLevelAutoFilter(worksheetXml)
    if (!element) return null
    const ref = readXmlAttribute(element.xml, 'ref')
    if (ref === undefined) {
      return { ref: '', columns: [], readOnlyReason: '筛选范围 ref 缺失，暂不能编辑' }
    }
    const model: SheetFilterModel = { ref, columns: [] }
    try {
      model.range = parseRange(ref)
    } catch {
      model.readOnlyReason = '筛选范围地址无法解析，暂不能编辑'
      return model
    }
    const body = element.xml.match(/^<autoFilter\b[^>]*>([\s\S]*?)<\/autoFilter>$/)?.[1] ?? ''
    if (UNSUPPORTED_CRITERIA.test(body) || /<extLst\b/.test(body)) {
      model.readOnlyReason = UNSUPPORTED_READ_REASON
    }
    for (const raw of body.match(/<filterColumn\b[^>]*\/>|<filterColumn\b[^>]*>[\s\S]*?<\/filterColumn>/g) ?? []) {
      const parsed = parseFilterColumn(raw)
      if ('error' in parsed) {
        model.readOnlyReason = `筛选列无法读取（${parsed.error}），暂不能编辑回写`
        continue
      }
      if (
        parsed.values === undefined && parsed.blank === undefined &&
        parsed.customs === undefined && parsed.dateGroups === undefined
      ) {
        continue // criteria-less color/icon/top10 columns stay out of the model
      }
      if (parsed.customs && parsed.customs.filters.length > 2) {
        model.readOnlyReason = '筛选列自定义条件超过两个，暂不能编辑回写'
        continue
      }
      if (model.columns.some((existing) => existing.colId === parsed.colId)) {
        model.readOnlyReason = '同一筛选列出现重复条件，暂不能编辑回写'
        continue
      }
      model.columns.push(parsed)
    }
    return model
  } catch (error) {
    return { ref: '', columns: [], readOnlyReason: `筛选读取失败：${(error as Error).message}` }
  }
}
