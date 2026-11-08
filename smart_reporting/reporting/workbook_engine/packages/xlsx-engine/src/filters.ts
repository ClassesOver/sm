/// Worksheet-level autoFilter writer, ported from genoffice xlsx-gateway
/// xlsx-filter.ts: replaces the sheet's declarative filter snapshot — the
/// `<autoFilter>` element with per-column value / custom criteria, plus the
/// declarative row visibility inside the span (hidden rows are the cached
/// filter result). Everything else in the worksheet stays byte-for-byte.
/// A filter whose range sits inside an Excel table is rejected: Excel stores
/// table filters in the table part, and a worksheet element overlapping a
/// table is invalid OOXML that Excel repairs away.

import { formatAddress, type RangeBounds } from './cell-address'
import {
  FILTER_CUSTOM_OPERATORS,
  firstSheetLevelAutoFilter,
  UNSUPPORTED_READ_REASON,
  type SheetFilterDateGroup,
  type SheetFilterDateGrouping,
} from './filter-read'
import { escapeXmlAttribute } from './xml'
import { assemblePackage, createBufferEntrySource } from './zip'

export class FilterEditError extends Error {}

export type { SheetFilterDateGroup, SheetFilterDateGrouping }

export interface SheetFilterCustom {
  val: string | number
  operator?: string | undefined
}

export interface SheetFilterColumn {
  /// 0-based offset from the filter range's first column, per OOXML.
  colId: number
  values?: readonly string[] | undefined
  blank?: boolean | undefined
  customs?: { and?: boolean | undefined; filters: readonly SheetFilterCustom[] } | undefined
  /// Grouped date buckets of the column's `<filters>` element. They coexist
  /// with values/blank (one element) but never with customs: a filterColumn
  /// carries one criteria group per the OOXML schema choice, and a snapshot
  /// mixing them is rejected whole.
  dateGroups?: readonly SheetFilterDateGroup[] | undefined
}

export interface SheetFilterCriteria {
  range: RangeBounds
  columns: readonly SheetFilterColumn[]
}

/// One declarative filter snapshot, shaped like the genoffice save payload
/// (minus the sheet key): `filter: null` removes the element, and the
/// visibility fields are siblings so a cleared filter can still unhide the
/// rows its model was hiding.
export interface SheetFilterState {
  filter: SheetFilterCriteria | null
  /// Rows hidden inside the span (the cached filter result); declarative.
  hiddenRows?: readonly number[] | undefined
  /// Rows not listed in hiddenRows are unhidden within this span (defaults
  /// to the filter range); matches how Excel re-evaluates a filter.
  visibilityRange?: RangeBounds | undefined
}

const UNSUPPORTED_EXISTING =
  /<(?:[\w.-]+:)?(?:colorFilter|top10|dynamicFilter|iconFilter)\b|<extLst\b/

const DATE_GROUPINGS: readonly SheetFilterDateGrouping[] = [
  'year', 'month', 'day', 'hour', 'minute', 'second',
]

/// Attributes a grouping granularity requires (down to it, nothing deeper).
const DATE_GROUP_CHAINS: Record<SheetFilterDateGrouping, readonly string[]> = {
  year: [], month: ['month'], day: ['month', 'day'], hour: ['month', 'day', 'hour'],
  minute: ['month', 'day', 'hour', 'minute'], second: ['month', 'day', 'hour', 'minute', 'second'],
}

const DATE_GROUP_ATTR_LIMITS: Record<string, [number, number]> = {
  month: [1, 12], day: [1, 31], hour: [0, 23], minute: [0, 59], second: [0, 59],
}

function validBounds(bounds: unknown, limitRow: number, limitColumn: number): boolean {
  if (typeof bounds !== 'object' || bounds === null) return false
  const read = (key: string, limit: number) => {
    const value = (bounds as Record<string, unknown>)[key]
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= limit
  }
  return (
    read('startRow', limitRow) && read('endRow', limitRow) &&
    read('startColumn', limitColumn) && read('endColumn', limitColumn)
  )
}

/// Validates one declarative snapshot; contradictions reject the whole
/// operation before any byte is touched (FilterEditError).
function validateSnapshot(state: SheetFilterState): RangeBounds {
  if (state.filter !== null) {
    const filter = state.filter
    if (!validBounds(filter.range, 1048575, 16383)) {
      throw new FilterEditError('筛选范围无效')
    }
    if (filter.range.endRow < filter.range.startRow || filter.range.endColumn < filter.range.startColumn) {
      throw new FilterEditError('筛选范围起止颠倒')
    }
    const width = filter.range.endColumn - filter.range.startColumn + 1
    const seen = new Set<number>()
    for (const column of filter.columns) {
      if (!Number.isInteger(column.colId) || column.colId < 0 || column.colId > 16383) {
        throw new FilterEditError('筛选列 colId 无效')
      }
      if (column.colId >= width) {
        throw new FilterEditError('筛选列超出筛选范围宽度，无法写入')
      }
      if (seen.has(column.colId)) throw new FilterEditError('同一筛选列出现重复条件')
      seen.add(column.colId)
      if (column.dateGroups !== undefined) {
        const groups = column.dateGroups
        if (!Array.isArray(groups) || groups.length < 1 || groups.length > 1000) {
          throw new FilterEditError('筛选日期分组条件无效或超出预算（1-1000 个）')
        }
        // OOXML filterColumn is a schema choice: one criteria group per column.
        if (column.customs !== undefined) {
          throw new FilterEditError('筛选列不能同时携带日期分组与自定义条件')
        }
        for (const group of groups) {
          if (typeof group !== 'object' || group === null) {
            throw new FilterEditError('筛选日期分组条件无效')
          }
          const read = (key: string) => (group as Record<string, unknown>)[key]
          const year = read('year')
          if (typeof year !== 'number' || !Number.isInteger(year) || year < 1 || year > 9999) {
            throw new FilterEditError('筛选日期分组条件年份必须是 1-9999 的整数')
          }
          for (const [attribute, [min, max]] of Object.entries(DATE_GROUP_ATTR_LIMITS)) {
            const value = read(attribute)
            if (value === undefined) continue
            if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) {
              throw new FilterEditError(`筛选日期分组条件 ${attribute} 超出 ${min}-${max} 范围`)
            }
          }
          const grouping = group.dateTimeGrouping
          if (typeof grouping !== 'string' || !DATE_GROUPINGS.includes(grouping as SheetFilterDateGrouping)) {
            throw new FilterEditError('筛选日期分组条件粒度无效')
          }
          const chain = DATE_GROUP_CHAINS[grouping as SheetFilterDateGrouping]
          // The chain down to the grouping must be present, nothing deeper.
          for (const attribute of chain) {
            if (read(attribute) === undefined) {
              throw new FilterEditError('筛选日期分组条件粒度与属性不匹配')
            }
          }
          for (const attribute of Object.keys(DATE_GROUP_ATTR_LIMITS)) {
            if (read(attribute) !== undefined && !chain.includes(attribute)) {
              throw new FilterEditError('筛选日期分组条件粒度与属性不匹配')
            }
          }
        }
      }
      const hasCriteria =
        column.values !== undefined || column.blank === true ||
        column.customs !== undefined || column.dateGroups !== undefined
      if (!hasCriteria) {
        throw new FilterEditError('筛选列缺少条件（values/blank/customs/dateGroups 至少其一）')
      }
      if (column.values !== undefined) {
        if (!Array.isArray(column.values) || column.values.length > 10000) {
          throw new FilterEditError('筛选值集合无效或超出预算')
        }
        for (const value of column.values) {
          if (typeof value !== 'string' || value.length > 32767) {
            throw new FilterEditError('筛选值必须是 32767 字符以内的文本')
          }
        }
      }
      if (column.blank !== undefined && typeof column.blank !== 'boolean') {
        throw new FilterEditError('筛选 blank 标记必须是布尔值')
      }
      if (column.customs !== undefined) {
        const filters = column.customs.filters
        if (!Array.isArray(filters) || filters.length < 1 || filters.length > 2) {
          throw new FilterEditError('自定义筛选条件必须为 1-2 个')
        }
        if (column.customs.and !== undefined && typeof column.customs.and !== 'boolean') {
          throw new FilterEditError('自定义筛选 and 标记必须是布尔值')
        }
        for (const custom of filters) {
          const value = custom.val
          if (!(typeof value === 'string' && value.length <= 32767) && !(typeof value === 'number' && Number.isFinite(value))) {
            throw new FilterEditError('自定义筛选条件值必须是有限数字或 32767 字符以内的文本')
          }
          if (custom.operator !== undefined && !(FILTER_CUSTOM_OPERATORS as readonly string[]).includes(custom.operator)) {
            throw new FilterEditError(`筛选条件 "${custom.operator}" 暂不能写回 XLSX`)
          }
        }
      }
    }
  }
  const span = state.visibilityRange ?? state.filter?.range
  if (state.hiddenRows !== undefined || state.visibilityRange !== undefined) {
    if (!span) throw new FilterEditError('隐藏行声明缺少可见性范围或筛选范围')
    if (!validBounds(span, 1048575, 16383)) throw new FilterEditError('筛选可见性范围无效')
    if (span.endRow < span.startRow || span.endColumn < span.startColumn) {
      throw new FilterEditError('筛选可见性范围起止颠倒')
    }
    if (state.hiddenRows !== undefined) {
      if (!Array.isArray(state.hiddenRows) || state.hiddenRows.length > 100000) {
        throw new FilterEditError('筛选隐藏行集合无效或超出预算')
      }
      for (const row of state.hiddenRows) {
        if (!Number.isInteger(row) || row < span.startRow + 1 || row > span.endRow) {
          throw new FilterEditError('筛选隐藏行超出可见性范围的数据行，无法声明式写入')
        }
      }
    }
  }
  return span ?? { startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 }
}

/// Table parts overlapping the filter span make the snapshot unrepresentable:
/// routing into the table part is not supported by this operation yet.
async function assertOutsideTables(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
  worksheetXml: string,
  worksheetPath: string,
  spans: readonly RangeBounds[],
): Promise<void> {
  const relIds = [...worksheetXml.matchAll(/<tablePart\b[^>]*\br:id="([^"]+)"/g)].map(
    (match) => match[1] ?? '',
  )
  if (relIds.length === 0) return
  const relsPath = worksheetPath.replace(/^(xl\/worksheets\/)([^/]+)$/, '$1_rels/$2.rels')
  if (!(await source.has(relsPath))) return
  const relsXml = await source.readText(relsPath)
  for (const relId of relIds) {
    const relationship = relsXml.match(new RegExp(`<Relationship\\b[^>]*\\bId="${relId}"[^>]*/>`))?.[0]
    const target = relationship?.match(/\bTarget="([^"]+)"/)?.[1]
    if (!target) continue
    const tablePath = new URL(target, `http://pkg/xl/worksheets/`).pathname.replace(/^\//, '')
    if (!(await source.has(tablePath))) continue
    const ref = (await source.readText(tablePath)).match(/<table\b[^>]*\bref="([^"]+)"/)?.[1]
    if (!ref) continue
    const parts = ref.split(':')
    const parse = (token: string) => {
      const match = token.match(/^(\$?)([A-Z]{1,3})(\$?)([0-9]+)$/)
      if (!match?.[2] || match[4] === undefined) return null
      let column = 0
      for (const character of match[2]) column = column * 26 + character.charCodeAt(0) - 64
      return { row: Number(match[4]) - 1, column: column - 1 }
    }
    const start = parse(parts[0] ?? '')
    const end = parse(parts[1] ?? parts[0] ?? '')
    if (!start || !end) continue
    const table = {
      startRow: Math.min(start.row, end.row),
      endRow: Math.max(start.row, end.row),
      startColumn: Math.min(start.column, end.column),
      endColumn: Math.max(start.column, end.column),
    }
    for (const span of spans) {
      if (
        table.startRow <= span.endRow && span.startRow <= table.endRow &&
        table.startColumn <= span.endColumn && span.startColumn <= table.endColumn
      ) {
        throw new FilterEditError(
          `筛选范围与表格 ${ref} 重叠；表格内筛选保存在表格部件中，此操作暂不支持，请先清除表格筛选`,
        )
      }
    }
  }
}

function serializeFilterColumn(column: SheetFilterColumn): string {
  const parts: string[] = []
  if (column.values !== undefined || column.blank || (column.dateGroups?.length ?? 0) > 0) {
    const blank = column.blank ? ' blank="1"' : ''
    const values = (column.values ?? [])
      .map((value) => `<filter val="${escapeXmlAttribute(value)}"/>`)
      .join('')
    // CT_Filters order: filter* then dateGroupItem*; attribute order follows
    // year month day hour minute second then dateTimeGrouping, as Excel writes.
    const groups = (column.dateGroups ?? [])
      .map((group) => {
        const attributes = (['month', 'day', 'hour', 'minute', 'second'] as const)
          .filter((attribute) => group[attribute] !== undefined)
          .map((attribute) => ` ${attribute}="${group[attribute]}"`)
          .join('')
        return `<dateGroupItem year="${group.year}"${attributes} dateTimeGrouping="${group.dateTimeGrouping}"/>`
      })
      .join('')
    parts.push(`<filters${blank}>${values}${groups}</filters>`)
  }
  if (column.customs) {
    const and = column.customs.and ? ' and="1"' : ''
    const filters = column.customs.filters
      .map((custom) => {
        const operator =
          custom.operator === undefined || custom.operator === 'equal'
            ? ''
            : ` operator="${custom.operator}"`
        return `<customFilter${operator} val="${escapeXmlAttribute(String(custom.val))}"/>`
      })
      .join('')
    parts.push(`<customFilters${and}>${filters}</customFilters>`)
  }
  return `<filterColumn colId="${column.colId}">${parts.join('')}</filterColumn>`
}

function serializeAutoFilter(filter: SheetFilterCriteria): string {
  const ref = `${formatAddress(filter.range.startRow, filter.range.startColumn)}:${formatAddress(filter.range.endRow, filter.range.endColumn)}`
  const columns = [...filter.columns]
    .sort((left, right) => left.colId - right.colId)
    .map(serializeFilterColumn)
    .join('')
  return columns === '' ? `<autoFilter ref="${ref}"/>` : `<autoFilter ref="${ref}">${columns}</autoFilter>`
}

/// Schema order places autoFilter after sheetData (and after the protection
/// block when present) — ported verbatim from genoffice insertAfterSheetData.
function insertAfterSheetData(worksheetXml: string, element: string): string {
  let insertAt = -1
  for (const pattern of [
    /<sheetData\s*\/>|<\/sheetData>/,
    /<sheetProtection\b[^>]*\/>/,
    /<protectedRanges\b[^>]*\/>|<\/protectedRanges>/,
    /<\/scenarios>/,
  ]) {
    const match = pattern.exec(worksheetXml)
    if (match) insertAt = Math.max(insertAt, match.index + match[0].length)
  }
  if (insertAt < 0) throw new FilterEditError('工作表缺少 sheetData 元素。')
  return worksheetXml.slice(0, insertAt) + element + worksheetXml.slice(insertAt)
}

/// Declarative row visibility inside the span: listed rows are hidden, every
/// other row in the span is unhidden (the header row is never touched).
/// Ported verbatim from genoffice applyRowVisibility.
function applyRowVisibility(
  worksheetXml: string,
  range: RangeBounds,
  hiddenRows: ReadonlySet<number>,
): string {
  const firstDataRow = range.startRow + 1
  const seen = new Set<number>()
  let xml = worksheetXml.replace(
    /<row\b([^>]*?)(\/>|>)/g,
    (full, attributes: string, close: string) => {
      const rowNumber = /(?:^|\s)r="([0-9]+)"/.exec(attributes)?.[1]
      if (rowNumber === undefined) return full
      const rowIndex = Number(rowNumber) - 1
      if (rowIndex < firstDataRow || rowIndex > range.endRow) return full
      seen.add(rowIndex)
      const withoutHidden = attributes.replace(/\s*hidden="[^"]*"/, '')
      const hidden = hiddenRows.has(rowIndex) ? ' hidden="1"' : ''
      return `<row${withoutHidden}${hidden}${close}`
    },
  )
  const missing = [...hiddenRows]
    .filter(
      (rowIndex) => !seen.has(rowIndex) && rowIndex >= firstDataRow && rowIndex <= range.endRow,
    )
    .sort((left, right) => left - right)
  for (const rowIndex of missing) {
    xml = insertEmptyHiddenRow(xml, rowIndex + 1)
  }
  return xml
}

function insertEmptyHiddenRow(worksheetXml: string, rowNumber: number): string {
  const newRow = `<row r="${rowNumber}" hidden="1"/>`
  const rowStartPattern = /<row\b[^>]*?\br="([1-9][0-9]*)"/g
  let match: RegExpExecArray | null
  while ((match = rowStartPattern.exec(worksheetXml)) !== null) {
    if (Number(match[1]) > rowNumber) {
      return worksheetXml.slice(0, match.index) + newRow + worksheetXml.slice(match.index)
    }
  }
  if (worksheetXml.includes('</sheetData>')) {
    return worksheetXml.replace('</sheetData>', () => `${newRow}</sheetData>`)
  }
  const emptySheetData = /<sheetData\s*\/>/
  if (emptySheetData.test(worksheetXml)) {
    return worksheetXml.replace(emptySheetData, () => `<sheetData>${newRow}</sheetData>`)
  }
  throw new FilterEditError('工作表缺少 sheetData 元素。')
}

/// Sets or clears one sheet's worksheet-level autoFilter, addressed by sheet
/// name. `filter: null` removes the element (Excel "清除筛选" on the sheet);
/// a snapshot replaces the existing element or is inserted at its schema
/// slot. Row visibility inside the span is declarative whenever hiddenRows or
/// visibilityRange is present.
export async function applySheetFilter(
  sourceBytes: Uint8Array,
  sheetName: string,
  state: SheetFilterState,
): Promise<Uint8Array> {
  const source = await createBufferEntrySource(sourceBytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const { parseSheetElements, resolveWorksheetPath } = await import('./workbook-read')
  const element = parseSheetElements(workbookXml).find((entry) => entry.name === sheetName)
  if (!element?.relationshipId) throw new FilterEditError(`工作表 "${sheetName}" 不存在。`)
  const worksheetPath = await resolveWorksheetPath(source, element.relationshipId)
  let xml = await source.readText(worksheetPath)

  const span = validateSnapshot(state)
  if (state.filter !== null) {
    await assertOutsideTables(
      source,
      xml,
      worksheetPath,
      [state.filter.range, ...(state.visibilityRange ? [state.visibilityRange] : [])],
    )
  }
  const existing = firstSheetLevelAutoFilter(xml)
  if (existing && state.filter !== null && UNSUPPORTED_EXISTING.test(existing.xml)) {
    // Overwriting would silently drop criteria this build cannot represent;
    // removing the element wholesale (filter: null) stays allowed.
    throw new FilterEditError(UNSUPPORTED_READ_REASON)
  }

  if (state.filter === null) {
    if (existing) {
      xml = xml.slice(0, existing.start) + xml.slice(existing.end)
    }
  } else {
    const serialized = serializeAutoFilter(state.filter)
    if (existing) {
      xml = xml.slice(0, existing.start) + serialized + xml.slice(existing.end)
    } else {
      xml = insertAfterSheetData(xml, serialized)
    }
  }
  if (state.hiddenRows !== undefined || state.visibilityRange !== undefined) {
    xml = applyRowVisibility(xml, span, new Set(state.hiddenRows ?? []))
  }
  if (xml === await source.readText(worksheetPath)) return sourceBytes
  return (await assemblePackage(sourceBytes, {
    replaced: new Map([[worksheetPath, xml]]),
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: [worksheetPath],
  })).buffer
}
