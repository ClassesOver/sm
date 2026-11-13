/// Pivot output-area growth, ported from genoffice xlsx-pivot-expand.ts: when
/// a refresh yields an expanded output area (new row or column members entered
/// the source data), the pivotTableDefinition's <location ref="…"> must be
/// widened to match, and the new cells must be clear of pre-existing non-pivot
/// content. This guard keeps the file consistent on disk — an unupdated ref
/// would confuse Excel about which cells belong to the pivot.
///
/// Also supports the layout-edit (relayout) path: regenerating the
/// pivotTableDefinition and pivotCacheDefinition from a full PivotAddition
/// layout while keeping the original name, cacheId, and records rel id.
/// The existing rebuild path updates records and visible cells immediately.

import { columnIndex, columnLabel } from './cell-address'
import {
  pivotHostSheet,
  readPivotState,
  rebuildPivotOutput,
  type PivotAddition,
} from './pivot-add'
import { assemblePackage, createBufferEntrySource } from './zip'

export class PivotExpandError extends Error {}

/// Carries the intended new output area for one recomputed pivot.
export interface PivotRefreshUpdate {
  /// xl/pivotCache/pivotCacheDefinitionN.xml
  readonly cachePath: string
  readonly tablePath?: string | undefined
  /// xl/worksheets/sheetN.xml — the sheet hosting the pivot output; required
  /// whenever the update grows the output area (the conflict check reads it).
  readonly worksheetPath?: string | undefined
  /// New full output ref (including header row + grand-total row/col),
  /// e.g. "F1:G7". May equal the current ref (no-op), larger, or smaller.
  readonly newOutputRef: string
  /// Layout edit: the full edited layout in the pivot-addition shape. The
  /// definitions are regenerated from it — the original name, cacheId, and
  /// records rel id stay; records and visible output are rebuilt immediately.
  /// name/location are taken from this update, not the payload,
  /// and the host worksheet's name is resolved automatically.
  readonly relayout?: Omit<PivotAddition, 'worksheetSheetName' | 'name' | 'location'> | undefined
}

// ─── Reference helpers ──────────────────────────────────────────────────────

interface CellRef {
  col: number // 0-based column index
  row: number // 0-based row index
}

interface AreaRef {
  start: CellRef
  end: CellRef
}

function parseCellRef(ref: string): CellRef {
  const m = ref.trim().toUpperCase().match(/^([A-Z]+)(\d+)$/)
  if (!m) throw new PivotExpandError(`Cannot parse cell address "${ref}".`)
  return { col: columnIndex(m[1] as string), row: Number(m[2]) - 1 }
}

function parseAreaRef(ref: string): AreaRef {
  const parts = ref.trim().toUpperCase().split(':')
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    throw new PivotExpandError(`Cannot parse area ref "${ref}".`)
  }
  return { start: parseCellRef(parts[0]), end: parseCellRef(parts[1]) }
}

function areaRefToString(area: AreaRef): string {
  return (
    `${columnLabel(area.start.col)}${area.start.row + 1}` +
    `:${columnLabel(area.end.col)}${area.end.row + 1}`
  )
}

function refToArea(ref: string): PivotAddition['location'] {
  const area = parseAreaRef(ref)
  return {
    startRow: area.start.row,
    startColumn: area.start.col,
    endRow: area.end.row,
    endColumn: area.end.col,
  }
}

function unescapeAttribute(input: string): string {
  return input
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&quot;', '"')
    .replaceAll('&apos;', "'")
    .replaceAll('&amp;', '&')
}

// ─── Package helpers ────────────────────────────────────────────────────────

/// Minimal relative-path resolver: walk ".." segments from the base directory.
function resolveRelativePath(baseDir: string, target: string): string {
  if (target.startsWith('/')) return target.slice(1)
  const segments = baseDir.split('/')
  for (const part of target.split('/')) {
    if (part === '..') segments.pop()
    else if (part !== '.') segments.push(part)
  }
  return segments.join('/')
}

/// Find the pivotTable part path linked to a given pivotCacheDefinition via
/// its own rels (pivot table → cache, so we do a reverse scan).
async function findPivotTablePathForCache(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
  cachePath: string,
): Promise<string | null> {
  const tableRelsPattern = /^xl\/pivotTables\/_rels\/[^/]+\.rels$/
  for (const relsPath of await source.paths()) {
    if (!tableRelsPattern.test(relsPath)) continue
    const relsXml = await source.readText(relsPath)
    const targetMatch =
      relsXml.match(/Target="([^"]+)"[^>]*Type="[^"]*pivotCacheDefinition[^"]*"/) ??
      relsXml.match(/Type="[^"]*pivotCacheDefinition[^"]*"[^>]*Target="([^"]+)"/)
    if (!targetMatch?.[1]) continue
    const relsDir = relsPath.replace(/\/_rels\/[^/]+$/, '')
    const resolved = resolveRelativePath(relsDir, targetMatch[1])
    if (resolved !== cachePath) continue
    const tableFilename = relsPath.replace(/.*\/_rels\//, '').replace(/\.rels$/, '')
    return `${relsDir}/${tableFilename}`
  }
  return null
}

/// Find the worksheet part whose rels reference the pivot table part (the
/// sheet hosting the pivot output).
async function findWorksheetPathForTable(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
  tablePath: string,
): Promise<string | null> {
  const worksheetRelsPattern = /^xl\/worksheets\/_rels\/[^/]+\.rels$/
  for (const relsPath of await source.paths()) {
    if (!worksheetRelsPattern.test(relsPath)) continue
    const relsXml = await source.readText(relsPath)
    const targetMatch =
      relsXml.match(/Target="([^"]+)"[^>]*Type="[^"]*pivotTable[^"]*"/) ??
      relsXml.match(/Type="[^"]*pivotTable[^"]*"[^>]*Target="([^"]+)"/)
    if (!targetMatch?.[1]) continue
    const resolved = resolveRelativePath('xl/worksheets', targetMatch[1] as string)
    if (resolved !== tablePath) continue
    const sheetFilename = relsPath.replace(/.*\/_rels\//, '').replace(/\.rels$/, '')
    return `xl/worksheets/${sheetFilename}`
  }
  return null
}

/// Read the current <location ref="…"> from a pivot table XML.
function extractLocationRef(pivotTableXml: string): string | null {
  return pivotTableXml.match(/<location\b[^>]*\bref="([^"]+)"/)?.[1] ?? null
}

/// Replace the ref attribute on the <location …> element.
function updateLocationRef(pivotTableXml: string, newRef: string): string {
  return pivotTableXml.replace(
    /<location\b([^>]*)\bref="[^"]*"([^>]*)>/,
    (_match, before: string, after: string) => `<location${before}ref="${newRef}"${after}>`,
  )
}

// ─── Conflict detection ─────────────────────────────────────────────────────

/// True when the worksheet XML has any non-empty cell in the given area.
function worksheetHasContentInArea(worksheetXml: string, area: AreaRef): boolean {
  const { start, end } = area
  for (const rowMatch of worksheetXml.matchAll(/<row\b([^>]*)>([\s\S]*?)<\/row>/g)) {
    const rAttr = (rowMatch[1] ?? '').match(/\br="(\d+)"/)
    if (!rAttr) continue
    const rowIdx = Number(rAttr[1]) - 1 // 0-based
    if (rowIdx < start.row || rowIdx > end.row) continue
    for (const cellMatch of (rowMatch[2] ?? '').matchAll(/<c\b([^>]*)(?:\/>|>[\s\S]*?<\/c>)/g)) {
      const rCell = (cellMatch[1] ?? '').match(/\br="([A-Z]+\d+)"/)
      if (!rCell?.[1]) continue
      const colMatch = (rCell[1] as string).match(/^([A-Z]+)/)
      if (!colMatch?.[1]) continue
      const colIdx = columnIndex(colMatch[1])
      if (colIdx < start.col || colIdx > end.col) continue
      // Cell exists in area — is it non-empty?
      const cellXml = cellMatch[0] as string
      // Self-closing <c .../> or <c with no <v>/<is> = empty
      if (cellXml.endsWith('/>')) continue
      if (!/<v[^>]*>/.test(cellXml) && !/<is>/.test(cellXml)) continue
      return true
    }
  }
  return false
}

/// Subtract the old area from the new one, returning the newly-added bands:
/// rows below the old area, then columns right of the old area (within the
/// old rows). Old ⊆ new always holds on refresh.
function subtractAreas(newArea: AreaRef, oldArea: AreaRef): AreaRef[] {
  const result: AreaRef[] = []
  if (oldArea.end.row < newArea.end.row) {
    result.push({
      start: { col: newArea.start.col, row: oldArea.end.row + 1 },
      end: { col: newArea.end.col, row: newArea.end.row },
    })
  }
  if (oldArea.end.col < newArea.end.col) {
    result.push({
      start: { col: oldArea.end.col + 1, row: newArea.start.row },
      end: { col: newArea.end.col, row: Math.min(oldArea.end.row, newArea.end.row) },
    })
  }
  return result
}

// ─── Main entry ─────────────────────────────────────────────────────────────

/// Applies output-area growth (and optional relayout) for each update:
///  1. Growth checks that the newly-added rows/columns in the worksheet XML
///     are empty (fail-closed on conflict).
///  2. The pivotTableDefinition <location ref="…"> is updated to newOutputRef.
///  3. With a relayout payload, both definitions are regenerated from it.
///
/// No-ops (same ref) and shrinking refs are silently skipped (a shrink is
/// intentional after a layout edit; the caller already cleared the cells).
export async function applyPivotLayoutExpansions(
  sourceBytes: Uint8Array,
  updates: readonly PivotRefreshUpdate[],
): Promise<Uint8Array> {
  if (updates.length === 0) return sourceBytes
  const source = await createBufferEntrySource(sourceBytes)
  const replaced = new Map<string, string>()
  const rebuilds: Array<{
    readonly tablePath: string
    readonly cachePath: string
    readonly requested?: PivotAddition
  }> = []
  for (const update of updates) {
    let pivotTablePath = update.tablePath ?? await findPivotTablePathForCache(source, update.cachePath)
    if (!pivotTablePath) {
      if (update.relayout !== undefined) throw new PivotExpandError('Pivot layout refresh needs a resolvable pivot table/cache relationship.')
      // Cache not yet linked to a table (bare cache from an old save) — skip.
      continue
    }
    let pivotTableXml = replaced.get(pivotTablePath) ?? (await source.readText(pivotTablePath))
    const currentRef = extractLocationRef(pivotTableXml)
    if (!currentRef) continue

    const oldArea = parseAreaRef(currentRef)
    const newArea = parseAreaRef(update.newOutputRef)
    const sameArea =
      oldArea.start.col === newArea.start.col &&
      oldArea.start.row === newArea.start.row &&
      oldArea.end.col === newArea.end.col &&
      oldArea.end.row === newArea.end.row

    if (sameArea && update.relayout === undefined) continue

    // Moved origin (shouldn't happen on refresh, but fail safe).
    if (oldArea.start.col !== newArea.start.col || oldArea.start.row !== newArea.start.row) {
      throw new PivotExpandError(
        `Pivot output "${update.newOutputRef}" cannot change its top-left cell during refresh.`,
      )
    }

    const grows = newArea.end.row > oldArea.end.row || newArea.end.col > oldArea.end.col
    // Shrinking refs are silently skipped without a relayout payload (the
    // caller never shrinks intentionally; the genoffice doc comment promises
    // this even though its writer also applied the smaller ref).
    if (
      !grows &&
      update.relayout === undefined &&
      (newArea.end.row < oldArea.end.row || newArea.end.col < oldArea.end.col)
    ) {
      continue
    }
    if (grows) {
      let worksheetPath = update.worksheetPath
      if (worksheetPath === undefined) {
        worksheetPath = (await findWorksheetPathForTable(source, pivotTablePath)) ?? undefined
      }
      if (worksheetPath === undefined) {
        throw new PivotExpandError('Pivot expansion needs a resolvable host worksheet.')
      }
      const worksheetXml = await source.readText(worksheetPath)
      for (const added of subtractAreas(newArea, oldArea)) {
        if (worksheetHasContentInArea(worksheetXml, added)) {
          throw new PivotExpandError(
            `Pivot expansion into ${areaRefToString(added)} conflicts with existing worksheet content. ` +
              'Clear the area first or move the pivot.',
          )
        }
      }
    }

    const persisted = readPivotState(pivotTableXml)
    if (persisted || update.relayout !== undefined) {
      if (update.relayout === undefined) {
        if (!persisted) continue
        rebuilds.push({
          tablePath: pivotTablePath,
          cachePath: update.cachePath,
          requested: { ...persisted, location: refToArea(update.newOutputRef) },
        })
      } else {
        const host = await pivotHostSheet(source, pivotTablePath)
        const name = unescapeAttribute(
          pivotTableXml.match(/<pivotTableDefinition\b[^>]*?\bname="([^"]*)"/)?.[1] ?? '',
        )
        const requested: PivotAddition = {
          ...update.relayout,
          name,
          worksheetSheetName: host.name,
          location: refToArea(update.newOutputRef),
        }
        rebuilds.push({ tablePath: pivotTablePath, cachePath: update.cachePath, requested })
      }
      continue
    }

    if (update.relayout === undefined) {
      pivotTableXml = updateLocationRef(pivotTableXml, update.newOutputRef)
      replaced.set(pivotTablePath, pivotTableXml)
      continue
    }
  }
  if (replaced.size === 0 && rebuilds.length === 0) return sourceBytes
  let result = replaced.size === 0 ? sourceBytes : (await assemblePackage(sourceBytes, {
    replaced,
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: [...replaced.keys()],
  })).buffer
  for (const rebuild of rebuilds) {
    result = await rebuildPivotOutput(result, rebuild.tablePath, rebuild.cachePath, rebuild.requested)
  }
  return result
}

/// Convenience wrapper for the AI surface: resolves each expansion's pivot
/// table by name (case-insensitive) to its cache + host worksheet and applies
/// the output-area growth. Unknown names throw (fail closed).
export interface PivotOutputExpansion {
  readonly pivotName: string
  readonly newOutputRef: string
}

export async function expandPivotOutputs(
  sourceBytes: Uint8Array,
  expansions: readonly PivotOutputExpansion[],
): Promise<Uint8Array> {
  if (expansions.length === 0) return sourceBytes
  const source = await createBufferEntrySource(sourceBytes)
  const updates: PivotRefreshUpdate[] = []
  for (const expansion of expansions) {
    const wanted = expansion.pivotName.toLowerCase()
    let tablePath: string | null = null
    let tableXml = ''
    for (const path of await source.paths()) {
      if (!/^xl\/pivotTables\/[^/]+\.xml$/.test(path)) continue
      const xml = await source.readText(path)
      const name = unescapeAttribute(xml.match(/\bname="([^"]+)"/)?.[1] ?? '')
      if (name.toLowerCase() === wanted) {
        tablePath = path
        tableXml = xml
        break
      }
    }
    if (!tablePath) {
      throw new PivotExpandError(`数据透视表 "${expansion.pivotName}" 不存在。`)
    }
    void tableXml
    // the table's own rels point at its cache
    const tableRelsPath = `${tablePath.replace(/^xl\/pivotTables\//, 'xl/pivotTables/_rels/')}.rels`
    const cachePath = await (async (): Promise<string | null> => {
      if (!(await source.has(tableRelsPath))) return null
      const relsXml = await source.readText(tableRelsPath)
      const target =
        relsXml.match(/Target="([^"]+)"[^>]*Type="[^"]*pivotCacheDefinition[^"]*"/)?.[1] ??
        relsXml.match(/Type="[^"]*pivotCacheDefinition[^"]*"[^>]*Target="([^"]+)"/)?.[1]
      if (!target) return null
      return resolveRelativePath('xl/pivotTables', target)
    })()
    if (!cachePath) {
      throw new PivotExpandError(`数据透视表 "${expansion.pivotName}" 缺少缓存关联。`)
    }
    updates.push({
      cachePath,
      worksheetPath:
        (await findWorksheetPathForTable(source, tablePath)) ?? undefined,
      newOutputRef: expansion.newOutputRef,
    })
  }
  return applyPivotLayoutExpansions(sourceBytes, updates)
}
