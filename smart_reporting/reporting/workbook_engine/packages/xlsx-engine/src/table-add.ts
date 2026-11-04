/// Table (ListObject) creation, ported from genoffice xlsx-table-add.ts:
/// persists tables created in the editor as brand-new OOXML parts —
/// xl/tables/tableN.xml, the worksheet's <tableParts> element, the
/// worksheet→table relationship, and the [Content_Types].xml override.
/// Fail-closed: name collisions, overlaps with existing tables / the sheet
/// auto-filter / merged cells, and bad column names all abort the save.

import { columnLabel } from './cell-address'
import { ensureRelationshipNamespace } from './xml'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { assemblePackage, createBufferEntrySource } from './zip'

export class TableAddError extends Error {}

export interface TableArea {
  readonly startRow: number
  readonly startColumn: number
  readonly endRow: number
  readonly endColumn: number
}

export interface TableAddition {
  /// Sheet that hosts the table.
  readonly worksheetSheetName: string
  /// 0-based, header row included.
  readonly area: TableArea
  readonly name: string
  /// One per column, in order; must be non-blank and unique.
  readonly columnNames: readonly string[]
  /// Built-in style name; undefined = TableStyleMedium2.
  readonly style?: string | undefined
  readonly bandedRows: boolean
}

const MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const TABLE_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/table'
const TABLE_CONTENT_TYPE =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml'
const DEFAULT_TABLE_STYLE = 'TableStyleMedium2'

type EntrySource = Awaited<ReturnType<typeof createBufferEntrySource>>

function validateAddition(addition: TableAddition): void {
  const { area, columnNames } = addition
  if (area.endRow <= area.startRow) {
    throw new TableAddError(
      `Table "${addition.name}" needs a header row plus at least one data row.`,
    )
  }
  const width = area.endColumn - area.startColumn + 1
  if (width !== columnNames.length) {
    throw new TableAddError(
      `Table "${addition.name}" spans ${width} columns but has ${columnNames.length} column names.`,
    )
  }
  const seen = new Set<string>()
  for (const name of columnNames) {
    const normalized = name.trim().toLowerCase()
    if (normalized.length === 0) {
      throw new TableAddError(`Table "${addition.name}" has a blank column name.`)
    }
    if (seen.has(normalized)) {
      throw new TableAddError(`Table "${addition.name}" has duplicate column name "${name}".`)
    }
    seen.add(normalized)
  }
}

/// name= and displayName= of every existing table part, lowercased.
async function collectExistingTableNames(source: EntrySource): Promise<Set<string>> {
  const names = new Set<string>()
  for (const path of await tablePartPaths(source)) {
    const xml = await source.readText(path)
    for (const attribute of ['name', 'displayName']) {
      const value = xml.match(new RegExp(`<table\\b[^>]*\\b${attribute}="([^"]+)"`))?.[1]
      if (value) names.add(value.toLowerCase())
    }
  }
  return names
}

async function maxExistingTableId(source: EntrySource): Promise<number> {
  let max = 0
  for (const path of await tablePartPaths(source)) {
    const xml = await source.readText(path)
    const id = Number(xml.match(/<table\b[^>]*\bid="(\d+)"/)?.[1] ?? 0)
    if (Number.isFinite(id)) max = Math.max(max, id)
  }
  return max
}

async function tablePartPaths(source: EntrySource): Promise<string[]> {
  return (await source.paths()).filter((path) => /^xl\/tables\/[^/]+\.xml$/.test(path))
}

/// Table names share Excel's defined-name namespace.
async function assertNameNotDefined(source: EntrySource, name: string): Promise<void> {
  const workbookXml = await source.readText('xl/workbook.xml')
  for (const match of workbookXml.matchAll(/<definedName\b[^>]*\bname="([^"]+)"/g)) {
    if (match[1]?.toLowerCase() === name.toLowerCase()) {
      throw new TableAddError(`Table name "${name}" collides with a defined name in the workbook.`)
    }
  }
}

/// Pending ranges cover additions in this call; the immutable source rels
/// cover tables already stored on the same worksheet.
async function assertNoTableOverlap(
  source: EntrySource,
  addition: TableAddition,
  worksheetPath: string,
  pending: readonly { worksheetPath: string; area: TableArea }[],
): Promise<void> {
  for (const entry of pending) {
    if (entry.worksheetPath === worksheetPath && areasOverlap(addition.area, entry.area)) {
      throw new TableAddError(`Table "${addition.name}" overlaps a table added in the same operation.`)
    }
  }
  const relsPath = relsPathFor(worksheetPath)
  if (!(await source.has(relsPath))) return
  const relsXml = await source.readText(relsPath)
  for (const match of relsXml.matchAll(/<Relationship\b[^>]*\/?>/g)) {
    const tag = match[0]
    if (!tag.includes(`Type="${TABLE_REL_TYPE}"`)) continue
    const target = tag.match(/\bTarget="([^"]+)"/)?.[1]
    if (!target) continue
    const tablePath = resolveTarget(worksheetPath, target)
    if (!(await source.has(tablePath))) continue
    const ref = (await source.readText(tablePath)).match(/<table\b[^>]*\bref="([^"]+)"/)?.[1]
    if (ref && areasOverlap(addition.area, parseRef(ref))) {
      throw new TableAddError(`Table "${addition.name}" overlaps an existing table (${ref}).`)
    }
  }
}

/// Excel forbids a table overlapping the sheet auto-filter or merged cells.
function assertNoSheetConflicts(addition: TableAddition, worksheetXml: string): void {
  const autoFilterRef = worksheetXml.match(/<autoFilter\b[^>]*\bref="([^"]+)"/)?.[1]
  if (autoFilterRef && areasOverlap(addition.area, parseRef(autoFilterRef))) {
    throw new TableAddError(
      `Table "${addition.name}" overlaps the sheet auto-filter (${autoFilterRef}) — clear it first.`,
    )
  }
  for (const match of worksheetXml.matchAll(/<mergeCell\b[^>]*\bref="([^"]+)"/g)) {
    const ref = match[1]
    if (ref && areasOverlap(addition.area, parseRef(ref))) {
      throw new TableAddError(`Table "${addition.name}" overlaps merged cells (${ref}) — unmerge them first.`)
    }
  }
}

/// Resolves a relationship target relative to its source part.
function resolveTarget(fromPart: string, target: string): string {
  const segments = fromPart.split('/').slice(0, -1)
  for (const segment of target.split('/')) {
    if (segment === '..') segments.pop()
    else if (segment !== '.' && segment !== '') segments.push(segment)
  }
  return segments.join('/')
}

function buildTableXml(id: number, addition: TableAddition): string {
  const ref = areaToRef(addition.area)
  const name = escapeAttribute(addition.name)
  const columns = addition.columnNames
    .map(
      (columnName, index) =>
        `<tableColumn id="${index + 1}" name="${escapeAttribute(columnName)}"/>`,
    )
    .join('')
  const style = escapeAttribute(addition.style ?? DEFAULT_TABLE_STYLE)
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    `<table xmlns="${MAIN_NS}" ` +
    `id="${id}" name="${name}" displayName="${name}" ref="${ref}" totalsRowShown="0">` +
    `<autoFilter ref="${ref}"/>` +
    `<tableColumns count="${addition.columnNames.length}">${columns}</tableColumns>` +
    `<tableStyleInfo name="${style}" showFirstColumn="0" showLastColumn="0" ` +
    `showRowStripes="${addition.bandedRows ? 1 : 0}" showColumnStripes="0"/>` +
    '</table>'
  )
}

/// Appends (or extends) the worksheet's <tableParts> element. Schema order
/// puts tableParts after every print/drawing element, before extLst.
function appendTablePart(worksheetXml: string, relId: string): string {
  const xml = ensureRelationshipNamespace(worksheetXml)
  const part = `<tablePart r:id="${relId}"/>`
  const existing = xml.match(/<tableParts\b[^>]*count="(\d+)"[^>]*>/)
  if (existing) {
    const opener = existing[0]
    const count = Number(existing[1] ?? 0) + 1
    const reopened = opener.replace(/count="\d+"/, `count="${count}"`)
    if (/\/\s*>$/.test(opener)) {
      const expanded = reopened.replace(/\/\s*>$/, () => `>${part}</tableParts>`)
      return xml.replace(opener, expanded)
    }
    if (!xml.includes('</tableParts>')) {
      throw new TableAddError('The worksheet tableParts element is malformed.')
    }
    return xml
      .replace(opener, () => reopened)
      .replace('</tableParts>', () => `${part}</tableParts>`)
  }
  const element = `<tableParts count="1">${part}</tableParts>`
  const extLstAt = xml.search(/<extLst\b/)
  if (extLstAt >= 0) return xml.slice(0, extLstAt) + element + xml.slice(extLstAt)
  const closeAt = xml.lastIndexOf('</worksheet>')
  if (closeAt < 0) throw new TableAddError('The worksheet part is malformed.')
  return xml.slice(0, closeAt) + element + xml.slice(closeAt)
}

function areaToRef(area: TableArea): string {
  return (
    `${columnLabel(area.startColumn)}${area.startRow + 1}` +
    `:${columnLabel(area.endColumn)}${area.endRow + 1}`
  )
}

function parseRef(ref: string): TableArea {
  const match = ref.replace(/[$]/g, '').match(/^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$/)
  if (!match?.[1] || !match[2]) {
    throw new TableAddError(`Unsupported range reference "${ref}" in the workbook.`)
  }
  const startColumn = labelToIndex(match[1])
  const startRow = Number(match[2]) - 1
  const endColumn = match[3] ? labelToIndex(match[3]) : startColumn
  const endRow = match[4] ? Number(match[4]) - 1 : startRow
  return { startRow, startColumn, endRow, endColumn }
}

function labelToIndex(label: string): number {
  let index = 0
  for (const char of label) index = index * 26 + (char.charCodeAt(0) - 64)
  return index - 1
}

function areasOverlap(a: TableArea, b: TableArea): boolean {
  return (
    a.startRow <= b.endRow &&
    b.startRow <= a.endRow &&
    a.startColumn <= b.endColumn &&
    b.startColumn <= a.endColumn
  )
}

function escapeAttribute(input: string): string {
  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function relsPathFor(partPath: string): string {
  const slash = partPath.lastIndexOf('/')
  return `${partPath.slice(0, slash + 1)}_rels/${partPath.slice(slash + 1)}.rels`
}

function relativeTarget(fromPart: string, toPart: string): string {
  const fromDir = fromPart.split('/').slice(0, -1)
  const toSegments = toPart.split('/')
  let common = 0
  while (
    common < fromDir.length &&
    common < toSegments.length - 1 &&
    fromDir[common] === toSegments[common]
  ) {
    common += 1
  }
  const ups = fromDir.length - common
  return `${'../'.repeat(ups)}${toSegments.slice(common).join('/')}`
}

function nextRelationshipId(relsXml: string): string {
  let max = 0
  for (const match of relsXml.matchAll(/\bId="rId([0-9]+)"/g)) {
    max = Math.max(max, Number(match[1]))
  }
  return `rId${max + 1}`
}

function appendRelationship(
  relsXml: string,
  type: string,
  target: string,
): { relsXml: string; relId: string } {
  const closeAt = relsXml.lastIndexOf('</Relationships>')
  if (closeAt < 0) throw new TableAddError('The worksheet relationships part is malformed.')
  const relId = nextRelationshipId(relsXml)
  const element =
    `<Relationship Id="${relId}" Type="${escapeAttribute(type)}" ` +
    `Target="${escapeAttribute(target)}"/>`
  return {
    relId,
    relsXml: relsXml.slice(0, closeAt) + element + relsXml.slice(closeAt),
  }
}

function registerContentTypeOverride(contentTypes: string, tablePath: string): string {
  const partName = `/${tablePath}`
  if (contentTypes.includes(`PartName="${partName}"`)) return contentTypes
  const closeAt = contentTypes.lastIndexOf('</Types>')
  if (closeAt < 0) throw new TableAddError('[Content_Types].xml is malformed.')
  const element = `<Override PartName="${partName}" ContentType="${TABLE_CONTENT_TYPE}"/>`
  return contentTypes.slice(0, closeAt) + element + contentTypes.slice(closeAt)
}

async function worksheetPathOf(source: EntrySource, sheetName: string): Promise<string> {
  const workbookXml = await source.readText('xl/workbook.xml')
  const element = parseSheetElements(workbookXml).find((entry) => entry.name === sheetName)
  if (!element?.relationshipId) {
    throw new TableAddError(`Sheet "${sheetName}" was not found.`)
  }
  return resolveWorksheetPath(source, element.relationshipId)
}

async function allocateTablePartPath(
  source: EntrySource,
  reservedPaths: ReadonlySet<string>,
): Promise<string> {
  let max = 0
  for (const path of [...(await source.paths()), ...reservedPaths]) {
    const number = path.match(/^xl\/tables\/table([0-9]+)\.xml$/)?.[1]
    if (number !== undefined) max = Math.max(max, Number(number))
  }
  return `xl/tables/table${max + 1}.xml`
}

/// Applies every table addition to the package (new part + rels +
/// content-type override + worksheet <tableParts> wiring).
export async function applyTableAdditions(
  sourceBytes: Uint8Array,
  additions: readonly TableAddition[],
): Promise<Uint8Array> {
  if (additions.length === 0) return sourceBytes
  const entries = await createBufferEntrySource(sourceBytes)
  const source: EntrySource = {
    ...entries,
    readText: async (path) => {
      const xml = await entries.readText(path)
      if (/<!\s*(?:DOCTYPE|ENTITY)\b/i.test(xml)) {
        throw new TableAddError(`Unsupported DOCTYPE or ENTITY declaration in ${path}.`)
      }
      return xml
    },
  }
  const replaced = new Map<string, string>()
  const added = new Map<string, string>()
  const touched: string[] = []
  const reservedPaths = new Set<string>()
  const pendingTables: Array<{ worksheetPath: string; area: TableArea }> = []

  const reserved = await collectExistingTableNames(source)
  let nextId = await maxExistingTableId(source)
  for (const addition of additions) {
    validateAddition(addition)
    const lowerName = addition.name.toLowerCase()
    if (reserved.has(lowerName)) {
      throw new TableAddError(`Table name "${addition.name}" is already taken in this workbook.`)
    }
    reserved.add(lowerName)
    await assertNameNotDefined(source, addition.name)
    const worksheetPath = await worksheetPathOf(source, addition.worksheetSheetName)
    await assertNoTableOverlap(source, addition, worksheetPath, pendingTables)
    const worksheetXml = replaced.get(worksheetPath) ?? (await source.readText(worksheetPath))
    assertNoSheetConflicts(addition, worksheetXml)

    nextId += 1
    const tablePath = await allocateTablePartPath(source, reservedPaths)
    reservedPaths.add(tablePath)
    pendingTables.push({ worksheetPath, area: addition.area })
    added.set(tablePath, buildTableXml(nextId, addition))
    touched.push(tablePath)

    const contentTypes =
      replaced.get('[Content_Types].xml') ?? (await source.readText('[Content_Types].xml'))
    replaced.set('[Content_Types].xml', registerContentTypeOverride(contentTypes, tablePath))
    touched.push('[Content_Types].xml')

    const worksheetRelsPath = relsPathFor(worksheetPath)
    const worksheetRelsBase = replaced.get(worksheetRelsPath) ??
      ((await source.has(worksheetRelsPath))
        ? await source.readText(worksheetRelsPath)
        : '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '</Relationships>')
    const rel = appendRelationship(
      worksheetRelsBase,
      TABLE_REL_TYPE,
      relativeTarget(worksheetPath, tablePath),
    )
    replaced.set(worksheetRelsPath, rel.relsXml)
    touched.push(worksheetRelsPath)

    replaced.set(worksheetPath, appendTablePart(worksheetXml, rel.relId))
    touched.push(worksheetPath)
  }
  return (await assemblePackage(sourceBytes, {
    replaced,
    added,
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [...added.keys()],
    touchedEntries: [...new Set(touched)],
  })).buffer
}
