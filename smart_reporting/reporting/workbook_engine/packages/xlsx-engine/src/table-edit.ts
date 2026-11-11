/// Adapted from pinned GenOffice xlsx-gateway/xlsx-table-edit.ts.
/// Uses the transactional ZIP assembler and strict owned-table reader.
import { type EntrySource, assemblePackage, createBufferEntrySource } from './zip'
import { readSheetTables, tableRelationshipId, resolveTablePartPath } from './table-read'
import { escapeRegExp, escapeXmlAttribute as escapeAttribute, decodeXmlText, extractElements, readXmlAttribute } from './xml'
import { decodeXlsxEscapes, encodeXlsxEscapes } from './xlsx-escapes'
import { assertPivotTableSourceColumns, pivotTableSourceUsesColumns, updatePivotTableSourceNames } from './pivot-table-source'
import { planPivotTableFieldRename } from './pivot-source-field-rename'
import { pivotControlPartPath } from './pivot-controls'
import { areaToRef, areasOverlap, assertNameNotDefined, collectExistingTableNames, parseRef, relsPathFor, worksheetPathOf, type TableArea } from './table-add'
interface TableStyleOptions {
  readonly headerRow?: boolean | undefined
  readonly totalsRow?: boolean | undefined
  readonly firstColumn?: boolean | undefined
  readonly lastColumn?: boolean | undefined
  readonly bandedColumns?: boolean | undefined
  readonly filterButton?: boolean | undefined
}
type MutablePackage = EntrySource & { write(path: string, xml: string): void; remove(path: string): void }
export type TableEdit = Omit<ResolvedTableEdit, 'worksheetPath'> & { readonly worksheetSheetName: string }
function autoFilterRef(area: TableArea, totalsRows: number): string {
  return areaToRef({ ...area, endRow: area.endRow - totalsRows })
}
export async function applyTableEdits(bytes: Uint8Array, edits: readonly TableEdit[]): Promise<Uint8Array> {
  if (!edits.length) return bytes
  const source = await createBufferEntrySource(bytes)
  const replaced = new Map<string, string>(), removed = new Set<string>(), touched = new Set<string>()
  const pkg: MutablePackage = {
    paths: async () => (await source.paths()).filter(path => !removed.has(path)),
    has: async path => !removed.has(path) && (replaced.has(path) || await source.has(path)),
    readText: async path => {
      if (removed.has(path)) throw new TableEditError('表格部件已删除')
      return replaced.get(path) ?? await source.readText(path)
    },
    write: (path, xml) => { replaced.set(path, xml) },
    remove: path => { replaced.delete(path); removed.add(path) },
  }
  const snapshot = async () => (await assemblePackage(bytes, { replaced, added: new Map(), addedBinary: new Map(), removedEntries: [...removed], addedEntries: [], touchedEntries: [...touched] })).buffer
  for (const edit of edits) {
    const worksheetPath = await worksheetPathOf(pkg, edit.worksheetSheetName)
    await applyEditsToPackage(pkg, [{ ...edit, worksheetPath }], touched, edit.worksheetSheetName, snapshot)
  }
  return (await assemblePackage(bytes, { replaced, added: new Map(), addedBinary: new Map(),
    removedEntries: [...removed], addedEntries: [], touchedEntries: [...touched] })).buffer
}

/// Table Design changes to tables already in the file: the table part is
/// rewritten in place (name, ref, columns, header/totals bands, style info)
/// or unregistered for Convert to Range. Fail-closed like table additions.

export class TableEditError extends Error {}

interface ResolvedTableEdit extends TableStyleOptions {
  readonly worksheetPath: string
  /// displayName (or name) of the table part at open time.
  readonly tableName: string
  readonly name?: string | undefined
  readonly area?: TableArea | undefined
  readonly columnNames?: readonly string[] | undefined
  readonly style?: string | undefined
  readonly bandedRows?: boolean | undefined
  readonly remove?: true | undefined
}

const CONTENT_TYPES_PATH = '[Content_Types].xml'
const TABLE_NAME_RULE = /^[\p{L}_\\][\p{L}\p{N}_.\\]*$/u
const CELL_LIKE = /^(\$?[A-Za-z]{1,3}\$?[0-9]+|[rR]\d*[cC]\d*)$/

export interface LocatedTable {
  readonly path: string
  readonly relId: string
  readonly xml: string
}

async function applyEditsToPackage(
  pkg: MutablePackage,
  edits: readonly ResolvedTableEdit[],
  touchedEntries: Set<string>,
  sheetName: string,
  snapshot: () => Promise<Uint8Array>,
): Promise<void> {
  if (edits.length === 0) return
  for (const edit of edits) {
    const located = await locateTable(pkg, edit)
    await assertExclusiveTablePart(pkg, edit.worksheetPath, located.path)
    if (edit.remove) {
      await updatePivotTableSourceNames(pkg, tableNames(located.xml), sheetName, undefined, touchedEntries)
      await removeTable(pkg, edit.worksheetPath, located, touchedEntries)
      continue
    }
    if (edit.headerRow === false) {
      await updatePivotTableSourceNames(pkg, tableNames(located.xml), sheetName, undefined, touchedEntries,
        '表格仍被透视表作为动态来源引用，不能关闭标题行')
    }
    const rewritten = await rewriteTable(pkg, edit, located)
    if (edit.columnNames !== undefined) {
      const oldStart = parseRef(readXmlAttribute(located.xml.match(/<table\b[^>]*>/)![0], 'ref')!).startColumn
      const nextStart = edit.area?.startColumn ?? oldStart
      const beforeNames = extractElements(located.xml, 'tableColumn').map(tag => decodeXlsxEscapes(decodeXmlText(readXmlAttribute(tag, 'name') ?? '')))
      const removedNames = beforeNames.filter((name, index) => edit.columnNames![oldStart + index - nextStart] !== name)
      if (beforeNames.length === edit.columnNames.length && oldStart === nextStart && await pivotTableSourceUsesColumns(pkg, tableNames(located.xml), removedNames)) {
        const input = (await pkg.paths()).some(path => pivotControlPartPath.test(path)) ? await snapshot() : pkg
        const plan = await planPivotTableFieldRename(input, { aliases: tableNames(located.xml), sheetName, startColumn: oldStart, beforeNames, afterNames: edit.columnNames })
        for (const [path, xml] of plan.replacements) { pkg.write(path, xml); touchedEntries.add(path) }
      } else await assertPivotTableSourceColumns(pkg, tableNames(located.xml), removedNames)
    }
    if (edit.name !== undefined) await updatePivotTableSourceNames(pkg, tableNames(located.xml), sheetName, edit.name, touchedEntries)
    pkg.write(located.path, rewritten)
    touchedEntries.add(located.path)
  }
}

async function assertExclusiveTablePart(pkg: EntrySource, worksheetPath: string, tablePath: string): Promise<void> {
  for (const path of await pkg.paths()) {
    if (!path.endsWith('.rels') || !path.includes('/_rels/')) continue
    const owner = path.replace('/_rels/', '/').slice(0, -5)
    if (owner === worksheetPath) continue
    for (const rel of extractElements(await pkg.readText(path), 'Relationship')) {
      if (readXmlAttribute(rel, 'Type') !== 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/table' ||
          ![undefined, 'Internal'].includes(readXmlAttribute(rel, 'TargetMode'))) continue
      const target = readXmlAttribute(rel, 'Target')
      if (target && resolveTablePartPath(owner, decodeXmlText(target)) === tablePath) throw new TableEditError('表格部件被多个来源引用，不能修改或删除')
    }
  }
}

/// The table parts related from a worksheet, in relationship order. Shared
/// with the filter save path, which routes table-overlapping filters into
/// the table part instead of the worksheet.
export async function sheetTableParts(
  pkg: MutablePackage,
  worksheetPath: string,
): Promise<readonly LocatedTable[]> {
  const context = await readSheetTables(pkg, worksheetPath, await pkg.readText(worksheetPath))
  if (context.tablesReadOnlyReason) throw new TableEditError(context.tablesReadOnlyReason)
  if (!context.tables.length) return []
  const worksheetXml = await pkg.readText(worksheetPath)
  const parts = extractElements(worksheetXml, 'tablePart')
  return Promise.all(context.tables.map(async (table, index) => ({
    path: table.path, relId: tableRelationshipId(worksheetXml, parts[index]!),
    xml: await pkg.readText(table.path),
  })))
}

function tableNames(xml: string): string[] {
  const open = xml.match(/<table\b[^>]*>/)?.[0] ?? ''
  const names: string[] = []
  for (const attribute of ['displayName', 'name']) {
    const value = open.match(new RegExp(`\\b${attribute}="([^"]*)"`))?.[1]
    if (value) names.push(decodeXmlText(value))
  }
  return names
}

async function locateTable(pkg: MutablePackage, edit: ResolvedTableEdit): Promise<LocatedTable> {
  const wanted = edit.tableName.toLowerCase()
  for (const part of await sheetTableParts(pkg, edit.worksheetPath)) {
    if (tableNames(part.xml).some((name) => name.toLowerCase() === wanted)) return part
  }
  throw new TableEditError(`Table "${edit.tableName}" was not found on its worksheet.`)
}

async function removeTable(
  pkg: MutablePackage,
  worksheetPath: string,
  table: LocatedTable,
  touchedEntries: Set<string>,
): Promise<void> {
  const relsPath = relsPathFor(worksheetPath)
  let rels = await pkg.readText(relsPath)
  for (const item of extractElements(rels, 'Relationship')) {
    const target = readXmlAttribute(item, 'Target')
    if (!target || ![undefined, 'Internal'].includes(readXmlAttribute(item, 'TargetMode'))) continue
    if (resolveTablePartPath(worksheetPath, decodeXmlText(target)) !== table.path) continue
    if (readXmlAttribute(item, 'Type') !== 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/table') throw new TableEditError('表格部件仍被其他对象引用')
    rels = rels.replace(item, '')
  }
  pkg.write(relsPath, rels)
  touchedEntries.add(relsPath)
  pkg.write(worksheetPath, removeTablePart(await pkg.readText(worksheetPath), table.relId))
  touchedEntries.add(worksheetPath)
  pkg.remove(table.path)
  touchedEntries.add(table.path)
  const contentTypes = await pkg.readText(CONTENT_TYPES_PATH)
  const stripped = contentTypes.replace(
    new RegExp(`<Override\\b[^>]*PartName="/${escapeRegExp(table.path)}"[^>]*/>`),
    '',
  )
  if (stripped !== contentTypes) {
    pkg.write(CONTENT_TYPES_PATH, stripped)
    touchedEntries.add(CONTENT_TYPES_PATH)
  }
}

/// Drops one <tablePart>; an emptied <tableParts> container goes with it.
export function removeTablePart(worksheetXml: string, relId: string): string {
  const without = worksheetXml.replace(/<tablePart\b[^>]*?(?:\/>|>\s*<\/tablePart>)/g, element => {
    const ids = [...element.matchAll(/\s[\w.-]+:id="([^"]*)"/g)]
    return ids.some(match => decodeXmlText(match[1]!) === relId) ? '' : element
  })
  const container = without.match(/<tableParts\b([^>]*?)(\/?)>/)
  if (!container) return without
  const remaining = (without.match(/<tablePart\b/g) ?? []).length
  if (remaining === 0) {
    return without.replace(/<tableParts\b[^>]*?(?:\/>|>\s*<\/tableParts>)/, '')
  }
  if (/count="\d+"/.test(container[1] ?? '')) {
    return without.replace(
      container[0],
      container[0].replace(/count="\d+"/, `count="${remaining}"`),
    )
  }
  return without
}

async function rewriteTable(
  pkg: MutablePackage,
  edit: ResolvedTableEdit,
  table: LocatedTable,
): Promise<string> {
  let xml = table.xml
  const openMatch = xml.match(/<table\b[^>]*>/)
  if (!openMatch) throw new TableEditError(`Table part ${table.path} is malformed.`)
  const attributes = parseAttributes(openMatch[0])
  const currentRef = attributes.get('ref')
  if (!currentRef) throw new TableEditError(`Table part ${table.path} has no ref.`)

  if (edit.name !== undefined) {
    await assertRenameAllowed(pkg, edit, table)
    attributes.set('name', escapeAttribute(edit.name))
    attributes.set('displayName', escapeAttribute(edit.name))
  }

  const headerRows =
    edit.headerRow === undefined
      ? Number(attributes.get('headerRowCount') ?? '1')
      : edit.headerRow
        ? 1
        : 0
  const totalsRows =
    edit.totalsRow === undefined
      ? Number(attributes.get('totalsRowCount') ?? '0')
      : edit.totalsRow
        ? 1
        : 0
  const area = edit.area ?? parseRef(currentRef)
  if (!Object.values(area).every(value => Number.isInteger(value) && value >= 0) ||
      area.endRow > 1048575 || area.endColumn > 16383 ||
      area.startRow > area.endRow || area.startColumn > area.endColumn) {
    throw new TableEditError('表格范围无效或越界')
  }
  if (area.endRow - area.startRow + 1 <= headerRows + totalsRows) {
    throw new TableEditError(
      `Table "${edit.tableName}" needs at least one data row beside its header and totals rows.`,
    )
  }
  if (edit.area) {
    await assertAreaFree(pkg, edit, table, area)
    attributes.set('ref', areaToRef(area))
  }
  if (headerRows === 0) attributes.set('headerRowCount', '0')
  else attributes.delete('headerRowCount')
  if (totalsRows > 0) {
    attributes.set('totalsRowCount', String(totalsRows))
    attributes.set('totalsRowShown', '1')
  } else {
    attributes.delete('totalsRowCount')
    if (edit.totalsRow === false) attributes.set('totalsRowShown', '0')
  }
  xml = xml.replace(openMatch[0], () => `<table ${serializeAttributes(attributes)}>`)

  const previousArea = parseRef(currentRef)
  xml = rewriteColumns(xml, edit, area, previousArea)

  const filterPattern = /<autoFilter\b[^>]*\/>|<autoFilter\b[^>]*>[\s\S]*?<\/autoFilter>/
  const existingFilter = xml.match(filterPattern)?.[0]
  const wantsFilter =
    headerRows > 0 &&
    (edit.filterButton ?? (edit.headerRow === true ? true : existingFilter !== undefined)) === true
  const columnsMoved =
    area.startColumn !== previousArea.startColumn || area.endColumn !== previousArea.endColumn
  const filterRef = autoFilterRef(area, totalsRows)
  if (!wantsFilter) {
    xml = xml.replace(filterPattern, '')
  } else if (existingFilter === undefined) {
    xml = xml.replace(/<table\b[^>]*>/, (open) => `${open}<autoFilter ref="${filterRef}"/>`)
  } else if (columnsMoved || edit.headerRow !== undefined) {
    // Criteria index columns from the filter's left edge: a column shift or
    // a re-headed table would point them at the wrong cells, so they drop.
    xml = xml.replace(filterPattern, `<autoFilter ref="${filterRef}"/>`)
  } else {
    xml = xml.replace(
      existingFilter,
      existingFilter.replace(/(<autoFilter\b[^>]*?\bref=")[^"]*(")/, `$1${filterRef}$2`),
    )
  }

  return rewriteStyleInfo(xml, edit)
}

async function assertRenameAllowed(
  pkg: MutablePackage,
  edit: ResolvedTableEdit,
  table: LocatedTable,
): Promise<void> {
  const name = edit.name ?? ''
  if (
    name.length === 0 ||
    name.length > 255 ||
    !TABLE_NAME_RULE.test(name) ||
    CELL_LIKE.test(name)
  ) {
    throw new TableEditError(`"${name}" is not a valid table name.`)
  }
  const own = new Set(tableNames(table.xml).map((value) => value.toLowerCase()))
  const reserved = await collectExistingTableNames(pkg)
  for (const value of own) reserved.delete(value)
  if (reserved.has(name.toLowerCase())) {
    throw new TableEditError(`Table name "${name}" is already taken in this workbook.`)
  }
  await assertNameNotDefined(pkg, name)
}

async function assertAreaFree(
  pkg: MutablePackage,
  edit: ResolvedTableEdit,
  table: LocatedTable,
  area: TableArea,
): Promise<void> {
  for (const part of await sheetTableParts(pkg, edit.worksheetPath)) {
    if (part.path === table.path) continue
    const ref = part.xml.match(/<table\b[^>]*\bref="([^"]+)"/)?.[1]
    if (ref && areasOverlap(area, parseRef(ref))) {
      throw new TableEditError(`Table "${edit.tableName}" would overlap table ${ref}.`)
    }
  }
  const worksheetXml = await pkg.readText(edit.worksheetPath)
  for (const match of worksheetXml.matchAll(/<mergeCell\b[^>]*\bref="([^"]+)"/g)) {
    const ref = match[1]
    if (ref && areasOverlap(area, parseRef(ref))) {
      throw new TableEditError(
        `Table "${edit.tableName}" would overlap merged cells (${ref}) — unmerge them first.`,
      )
    }
  }
}

/// Existing <tableColumn> elements follow their sheet column, so a left-edge
/// resize keeps ids, formulas and totals metadata with the right cells.
function rewriteColumns(
  xml: string,
  edit: ResolvedTableEdit,
  area: TableArea,
  previousArea: TableArea,
): string {
  const width = area.endColumn - area.startColumn + 1
  const block = xml.match(/<tableColumns\b[^>]*>([\s\S]*?)<\/tableColumns>/)
  if (!block) throw new TableEditError(`Table "${edit.tableName}" has no tableColumns.`)
  const existing = [
    ...(block[1] ?? '').matchAll(/<tableColumn\b[^>]*?(?:\/>|>[\s\S]*?<\/tableColumn>)/g),
  ].map((match) => match[0])
  if (edit.columnNames === undefined) {
    if (existing.length !== width || area.startColumn !== previousArea.startColumn) {
      throw new TableEditError(
        `Table "${edit.tableName}" spans ${width} columns but lists ${existing.length} column names.`,
      )
    }
    return xml
  }
  if (edit.columnNames.length !== width) {
    throw new TableEditError(
      `Table "${edit.tableName}" spans ${width} columns but has ${edit.columnNames.length} column names.`,
    )
  }
  const seen = new Set<string>()
  for (const name of edit.columnNames) {
    const key = name.trim().toLowerCase()
    if (key.length === 0)
      throw new TableEditError(`Table "${edit.tableName}" has a blank column name.`)
    if (seen.has(key)) {
      throw new TableEditError(`Table "${edit.tableName}" has duplicate column name "${name}".`)
    }
    seen.add(key)
  }
  let nextId = existing.reduce(
    (max, element) => Math.max(max, Number(element.match(/\bid="(\d+)"/)?.[1] ?? 0)),
    0,
  )
  const columns = edit.columnNames.map((name, index) => {
    const previousIndex = area.startColumn + index - previousArea.startColumn
    const element = previousIndex >= 0 ? existing[previousIndex] : undefined
    const escaped = escapeAttribute(encodeXlsxEscapes(name))
    if (element === undefined) {
      nextId += 1
      return `<tableColumn id="${nextId}" name="${escaped}"/>`
    }
    return /\bname="/.test(element)
      ? element.replace(/\bname="[^"]*"/, () => `name="${escaped}"`)
      : element.replace(/<tableColumn\b/, () => `<tableColumn name="${escaped}"`)
  })
  const opener = block[0].match(/^<tableColumns\b[^>]*>/)![0]
  const attributes = parseAttributes(opener)
  attributes.set('count', String(columns.length))
  return xml.replace(block[0], () => `<tableColumns ${serializeAttributes(attributes)}>${columns.join('')}</tableColumns>`)
}

function rewriteStyleInfo(xml: string, edit: ResolvedTableEdit): string {
  const existing =
    xml.match(/<tableStyleInfo\b[^>]*\/>|<tableStyleInfo\b[^>]*>[\s\S]*?<\/tableStyleInfo>/)
  const attributes = existing
    ? parseAttributes(existing[0])
    : new Map<string, string>([
        ['showFirstColumn', '0'],
        ['showLastColumn', '0'],
        ['showRowStripes', '1'],
        ['showColumnStripes', '0'],
      ])
  if (edit.style !== undefined) attributes.set('name', escapeAttribute(edit.style))
  const flags: [keyof ResolvedTableEdit, string][] = [
    ['firstColumn', 'showFirstColumn'],
    ['lastColumn', 'showLastColumn'],
    ['bandedRows', 'showRowStripes'],
    ['bandedColumns', 'showColumnStripes'],
  ]
  for (const [key, attribute] of flags) {
    const value = edit[key]
    if (typeof value === 'boolean') attributes.set(attribute, value ? '1' : '0')
  }
  const element = `<tableStyleInfo ${serializeAttributes(attributes)}/>`
  if (existing) return xml.replace(existing[0], () => element)
  // tableColumn may own an extLst too; style belongs after tableColumns.
  return xml.replace('</tableColumns>', () => `</tableColumns>${element}`)
}

function parseAttributes(openTag: string): Map<string, string> {
  const attributes = new Map<string, string>()
  const body = openTag.replace(/^<[^\s/>]+/, '').replace(/\/?>$/, '')
  for (const match of body.matchAll(/([^\s=]+)="([^"]*)"/g)) {
    attributes.set(match[1]!, match[2]!)
  }
  return attributes
}

function serializeAttributes(attributes: Map<string, string>): string {
  return [...attributes].map(([key, value]) => `${key}="${value}"`).join(' ')
}

