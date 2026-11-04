/// Pivot cache refresh, ported from genoffice's refresh semantics
/// (pivot-engine growPivotDefinition + xlsx-pivot refreshOnLoad): re-reads
/// each cache's worksheetSource ref (the ref itself never grows — genoffice
/// fails closed on a moved source and leaves range growth to Excel's
/// refreshOnLoad), appends new members to sharedItems in first-seen order
/// (append-on-refresh — old item indices stay valid for the pivot tables'
/// layout lines), rebuilds pivotCacheRecords (grouped fields apply the
/// grouping rule read back from the pivot table's {AIO-PIVOT-GROUPINGS}
/// ext), updates recordCount, and marks the cache definition
/// refreshOnLoad="1" so Excel rebuilds rowItems/colItems on open.

import { parseRange, type RangeBounds } from './cell-address'
import { groupLabel, isValidGrouping, type PivotFieldGrouping } from './pivot-grouping'
import { rebuildPivotOutput, readPivotState } from './pivot-add'
import { readSourceAreaRows, escapeXmlAttribute, type SourceValue } from './pivot-source'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { assemblePackage, createBufferEntrySource } from './zip'

const MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const RECORDS_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheRecords'
const GROUPINGS_EXT_URI = '{AIO-PIVOT-GROUPINGS}'

export class PivotRefreshError extends Error {}

function decodeEntities(input: string): string {
  return input
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&')
}

function relsPathFor(partPath: string): string {
  const slash = partPath.lastIndexOf('/')
  return `${partPath.slice(0, slash + 1)}_rels/${partPath.slice(slash + 1)}.rels`
}

function resolveRelTarget(fromPart: string, target: string): string {
  if (target.startsWith('/')) return target.slice(1)
  const base = fromPart.split('/').slice(0, -1)
  for (const part of target.split('/')) {
    if (part === '..') base.pop()
    else if (part !== '.') base.push(part)
  }
  return base.join('/')
}

interface CacheFieldInfo {
  readonly name: string
  /// String members declared in <sharedItems>; empty for measure fields and
  /// empty dimensions.
  readonly sharedItems: string[]
}

/// Parses a cacheDefinition's <cacheFields> block: field names plus per-field
/// string sharedItems. Calculated fields (databaseField="0") take no cache
/// records and are excluded — records map one cell per database field.
function parseCacheFields(cacheXml: string): readonly CacheFieldInfo[] {
  const fields: CacheFieldInfo[] = []
  for (const field of cacheXml.matchAll(/<cacheField\b([^>]*)>([\s\S]*?)<\/cacheField>/g)) {
    if (/\bdatabaseField="0"/.test(field[1] ?? '')) continue
    const name = (field[1] ?? '').match(/\bname="([^"]*)"/)?.[1] ?? ''
    const items = [...(field[2] ?? '').matchAll(/<sharedItems\b[^>]*>([\s\S]*?)<\/sharedItems>/g)].flatMap(
      (si) => [...(si[1] ?? '').matchAll(/<s\b[^>]*v="([^"]*)"/g)].map((sv) => decodeEntities(sv[1] ?? '')),
    )
    fields.push({ name: decodeEntities(name), sharedItems: items })
  }
  return fields
}

/// Reads the grouping rules a pivot table attached to this cache persists in
/// its private extLst (written by pivot-add); returns fieldIndex -> grouping.
function parseGroupingsFromTable(tableXml: string): Map<number, PivotFieldGrouping> {
  const result = new Map<number, PivotFieldGrouping>()
  const marker = tableXml.indexOf(GROUPINGS_EXT_URI)
  if (marker === -1) return result
  const payload = tableXml
    .slice(marker)
    .match(/<aio:aioPivotGroupings\s+v="([^"]*)"/)
  if (!payload) return result
  let parsed: unknown
  try {
    parsed = JSON.parse(decodeEntities(payload[1] ?? ''))
  } catch {
    return result
  }
  if (!Array.isArray(parsed)) return result
  for (const entry of parsed) {
    if (typeof entry !== 'object' || entry === null) continue
    const { fieldIndex, ...grouping } = entry as { fieldIndex?: unknown }
    if (typeof fieldIndex !== 'number' || !isValidGrouping(grouping)) continue
    if (!result.has(fieldIndex)) result.set(fieldIndex, grouping)
  }
  return result
}

function escapeAttribute(value: string): string {
  return escapeXmlAttribute(value)
}

function measureCellXml(value: SourceValue): string {
  if (value === null || value === '') return '<m/>'
  if (typeof value === 'number') return `<n v="${value}"/>`
  const n = Number(value)
  if (Number.isFinite(n) && value.trim() !== '') return `<n v="${n}"/>`
  return `<s v="${escapeAttribute(String(value))}"/>`
}

/// Refreshes every pivot cache in the workbook against its current worksheet
/// source. Returns the patched package bytes; a workbook without pivot caches
/// throws (the AI layer surfaces the message).
export async function refreshPivotCaches(sourceBytes: Uint8Array): Promise<Uint8Array> {
  const source = await createBufferEntrySource(sourceBytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const cachePaths = (await source.paths()).filter((path) =>
    /^xl\/pivotCache\/pivotCacheDefinition\d+\.xml$/.test(path),
  )
  if (cachePaths.length === 0) {
    throw new PivotRefreshError('工作簿没有可刷新的数据透视表。')
  }

  // workbook.xml maps cacheId -> r:id; workbook rels map r:id -> cache path,
  // so pivot tables are matched to caches through their cacheId attribute.
  const workbookRels = await source.readText('xl/_rels/workbook.xml.rels')
  const cacheIdToPath = new Map<number, string>()
  for (const match of workbookXml.matchAll(/<pivotCache\b[^>]*\bcacheId="(\d+)"[^>]*\br:id="([^"]+)"/g)) {
    const relId = match[2] ?? ''
    const target = workbookRels
      .match(new RegExp(`<Relationship\\b[^>]*\\bId="${relId}"[^>]*\\bTarget="([^"]+)"`))
      ?.[1]
    if (target) cacheIdToPath.set(Number(match[1]), resolveRelTarget('xl/workbook.xml', target))
  }

  const managedTables: Array<{ tablePath: string; cachePath: string; outputRef: string | undefined }> = []
  const tableGroupingsByCachePath = new Map<string, Map<number, PivotFieldGrouping>>()
  for (const path of await source.paths()) {
    if (!/^xl\/pivotTables\/[^/]+\.xml$/.test(path)) continue
    const tableXml = await source.readText(path)
    const cacheId = Number(tableXml.match(/\bcacheId="(\d+)"/)?.[1] ?? -1)
    const cachePath = cacheIdToPath.get(cacheId)
    if (!cachePath) continue
    const groupings = parseGroupingsFromTable(tableXml)
    const existing = tableGroupingsByCachePath.get(cachePath)
    if (existing) {
      for (const [fieldIndex, grouping] of groupings) {
        if (!existing.has(fieldIndex)) existing.set(fieldIndex, grouping)
      }
    } else {
      tableGroupingsByCachePath.set(cachePath, groupings)
    }
    if (readPivotState(tableXml)) {
      // the current location ref — possibly an enlarged area the user
      // reserved via expandPivots — must survive the refresh re-bake
      const outputRef = tableXml.match(/<location\b[^>]*\bref="([^"]+)"/)?.[1]
      managedTables.push({ tablePath: path, cachePath, outputRef })
    }
  }

  const replaced = new Map<string, string>()
  for (const cachePath of cachePaths) {
    const cacheXml = await source.readText(cachePath)
    const sourceTag = cacheXml.match(/<worksheetSource\b[^>]*\/>/)?.[0] ?? ''
    const ref = sourceTag.match(/\bref="([^"]+)"/)?.[1]
    const sheet = decodeEntities(sourceTag.match(/\bsheet="([^"]+)"/)?.[1] ?? '')
    if (!ref || sheet === '') {
      throw new PivotRefreshError('数据透视表缓存缺少可解析的源区域。')
    }
    let bounds: RangeBounds
    try {
      bounds = parseRange(ref)
    } catch {
      throw new PivotRefreshError(`数据透视表源区域 "${ref}" 无法解析。`)
    }
    const element = parseSheetElements(workbookXml).find((entry) => entry.name === sheet)
    if (!element?.relationshipId) {
      throw new PivotRefreshError(`源工作表 "${sheet}" 不存在，无法刷新数据透视表。`)
    }
    const worksheetPath = await resolveWorksheetPath(source, element.relationshipId)
    const worksheetXml = await source.readText(worksheetPath)

    const fields = parseCacheFields(cacheXml)
    if (fields.length !== bounds.endColumn - bounds.startColumn + 1) {
      throw new PivotRefreshError(
        `数据透视表源区域与缓存字段数不一致（${fields.length} 个字段，源区域 ${bounds.endColumn - bounds.startColumn + 1} 列）。`,
      )
    }
    const sourceRows = await readSourceAreaRows(
      source,
      worksheetXml,
      bounds.startRow, // readSourceAreaRows skips the header row itself
      bounds.endRow,
      bounds.startColumn,
      bounds.endColumn,
    )

    // Append-on-refresh member space: existing sharedItems keep their indices,
    // first-seen new members go to the end of their field's list.
    const sharedItems = fields.map((field) => [...field.sharedItems])
    const groupings = tableGroupingsByCachePath.get(cachePath) ?? new Map()
    const records = sourceRows
      .map((row) => {
        const cells = row.map((value, fieldIndex) => {
          const items = sharedItems[fieldIndex] ?? []
          const isDimension =
            items.length > 0 || (fields[fieldIndex]?.sharedItems.length ?? 0) > 0
          if (isDimension) {
            if (value === null || value === '') return '<m/>'
            const grouping = groupings.get(fieldIndex)
            const key = grouping ? groupLabel(grouping, value) : String(value)
            let index = items.indexOf(key)
            if (index === -1) {
              items.push(key)
              index = items.length - 1
            }
            return index === 0 ? '<x/>' : `<x v="${index}"/>`
          }
          return measureCellXml(value)
        })
        return `<r>${cells.join('')}</r>`
      })
      .join('')

    // Rewrite the definition: appended sharedItems, new recordCount, and
    // refreshOnLoad="1" so Excel rebuilds rowItems/colItems on open. The
    // split keeps every replacement inside its own <cacheField> segment.
    let updatedCacheXml = cacheXml
    const segments = updatedCacheXml.split(/(?=<cacheField\b)/)
    updatedCacheXml = segments
      .map((segment, index) => {
        if (index === 0) return segment
        const items = sharedItems[index - 1]
        if (!items || items.length === 0) return segment
        const sharedItemsXml =
          `<sharedItems count="${items.length}">` +
          items.map((item) => `<s v="${escapeAttribute(item)}"/>`).join('') +
          '</sharedItems>'
        if (/<sharedItems\b[^>]*\/>/.test(segment)) {
          return segment.replace(/<sharedItems\b[^>]*\/>/, sharedItemsXml)
        }
        if (/<sharedItems\b[^>]*>[\s\S]*?<\/sharedItems>/.test(segment)) {
          return segment.replace(/<sharedItems\b[^>]*>[\s\S]*?<\/sharedItems>/, sharedItemsXml)
        }
        return segment
      })
      .join('')
    updatedCacheXml = updatedCacheXml.replace(
      /\brecordCount="\d+"/,
      `recordCount="${sourceRows.length}"`,
    )
    const definitionTag = updatedCacheXml.match(/<pivotCacheDefinition\b[^>]*>/)?.[0] ?? ''
    if (/\brefreshOnLoad="/.test(definitionTag)) {
      updatedCacheXml = updatedCacheXml.replace(/\brefreshOnLoad="[^"]*"/, 'refreshOnLoad="1"')
    } else {
      updatedCacheXml = updatedCacheXml.replace(
        '<pivotCacheDefinition',
        '<pivotCacheDefinition refreshOnLoad="1"',
      )
    }
    replaced.set(cachePath, updatedCacheXml)

    // Records part: resolved through the cache's own rels.
    const cacheRelsPath = relsPathFor(cachePath)
    const cacheRels = (await source.has(cacheRelsPath))
      ? await source.readText(cacheRelsPath)
      : ''
    const recordsTarget = cacheRels
      .match(new RegExp(`<Relationship\\b[^>]*\\bType="${RECORDS_REL_TYPE}"[^>]*\\bTarget="([^"]+)"`))
      ?.[1]
    if (!recordsTarget) {
      throw new PivotRefreshError('数据透视表缓存缺少 records 部分，无法刷新。')
    }
    const recordsPath = resolveRelTarget(cachePath, recordsTarget)
    replaced.set(
      recordsPath,
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        `<pivotCacheRecords xmlns="${MAIN_NS}" xmlns:r="${REL_NS}" count="${sourceRows.length}">${records}</pivotCacheRecords>`,
    )
  }

  const refreshed = (await assemblePackage(sourceBytes, {
    replaced,
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: [...replaced.keys()],
  })).buffer

  let rebuilt = refreshed
  for (const { tablePath, cachePath, outputRef } of managedTables) {
    rebuilt = await rebuildPivotOutput(
      rebuilt,
      tablePath,
      cachePath,
      undefined,
      // keep the reserved output area (expandPivots may have enlarged it);
      // the re-baked matrix anchors at the same top-left cell
      outputRef ? parseRange(outputRef) : undefined,
    )
  }
  return rebuilt
}
