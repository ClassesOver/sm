/// Orchestration for sheet management and structural edits over a package:
/// locates parts through workbook relationships, applies the ported
/// transforms, rewrites cross-package references, and reassembles with the
/// untouched-entries-preservation assembler.

import {
  applySheetPlanToWorkbookXml,
  addWorksheetOverride,
  addWorksheetRelationship,
  assertSheetRemovable,
  buildWorksheetPartXml,
  chartReferencesSheet,
  definedNamesReferenceSheet,
  maxRelationshipId,
  maxSheetIdInWorkbook,
  renameSheetReferencesInChart,
  renameSheetReferencesInDefinedNames,
  renameSheetReferencesInWorksheet,
  validateSheetName,
  worksheetReferencesSheet,
  type SheetAllocation,
  type SheetEditPlan,
} from './sheets-edit'
import {
  applyStructuralOp,
  assertShiftable,
  shiftChartSeriesReferences,
  shiftDefinedNames,
  shiftDrawingAnchors,
  shiftQualifiedFormulas,
  shiftSpecOf,
  shiftTablePart,
  shiftVmlObjectAnchors,
  type ShiftSpec,
  type StructuralOp,
} from './structural'
import { setWorksheetCellText } from './workbook-write'
import { shiftSheetNotes } from './notes'
import { parseRange, parseAddress, formatAddress, columnIndex } from './cell-address'
import { computeSortedRowOrder } from './sort-range'
import { parseSheetElements, resolveWorksheetPath, readWorkbook } from './workbook-read'
import { assemblePackage, createBufferEntrySource, type MutationPlan } from './zip'

const RELS_PATH = 'xl/_rels/workbook.xml.rels'
const CONTENT_TYPES_PATH = '[Content_Types].xml'

function columnLetters(index: number): string {
  let label = ''
  let remaining = index + 1
  while (remaining > 0) {
    remaining -= 1
    label = String.fromCharCode(65 + (remaining % 26)) + label
    remaining = Math.floor(remaining / 26)
  }
  return label
}

interface SheetPart {
  readonly name: string
  readonly path: string
  readonly relationshipId: string
}

async function sheetPartsOf(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
  workbookXml: string,
): Promise<SheetPart[]> {
  const parts: SheetPart[] = []
  for (const element of parseSheetElements(workbookXml)) {
    if (element.relationshipId === undefined) continue
    parts.push({
      name: element.name,
      path: await resolveWorksheetPath(source, element.relationshipId),
      relationshipId: element.relationshipId,
    })
  }
  return parts
}

async function worksheetPathByChart(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
): Promise<string[]> {
  const charts: string[] = []
  for (const path of await source.paths()) {
    if (/^xl\/charts\/chart[0-9]+\.xml$/.test(path)) charts.push(path)
  }
  return charts.sort()
}

/// Rename / add / remove worksheets. Renames rewrite every qualified
/// reference (other sheets' formulas, chart series, defined names, internal
/// hyperlink anchors); removals fail closed while anything still references
/// the sheet or it carries owned satellite parts.
export async function applySheetEdits(
  sourceBytes: Uint8Array,
  plan: SheetEditPlan,
): Promise<Uint8Array> {
  const source = await createBufferEntrySource(sourceBytes)
  let workbookXml = await source.readText('xl/workbook.xml')
  let relsXml = await source.readText(RELS_PATH)
  let contentTypes = await source.readText(CONTENT_TYPES_PATH)
  const parts = await sheetPartsOf(source, workbookXml)
  const partByName = new Map(parts.map((part) => [part.name, part]))
  const existingNames = new Set(parts.map((part) => part.name))

  // ── validate ────────────────────────────────────────────────────────
  for (const rename of plan.renames) {
    if (!existingNames.has(rename.sheetName)) {
      throw new Error(`workbook.xml 中找不到工作表 "${rename.sheetName}"。`)
    }
    validateSheetName(rename.newName)
    if (
      rename.newName !== rename.sheetName &&
      existingNames.has(rename.newName) &&
      !plan.renames.some((other) => other.sheetName === rename.newName)
    ) {
      throw new Error(`已存在名为 "${rename.newName}" 的工作表。`)
    }
  }
  for (const removal of plan.removals) {
    if (!existingNames.has(removal)) {
      throw new Error(`workbook.xml 中找不到工作表 "${removal}"。`)
    }
  }
  for (const addition of plan.additions) {
    validateSheetName(addition.name)
    if (existingNames.has(addition.name)) {
      throw new Error(`已存在名为 "${addition.name}" 的工作表。`)
    }
  }

  // ── removals: fail closed while referenced ───────────────────────────
  const removedNames = new Set(plan.removals)
  const removedLocalIds = new Set(
    parseSheetElements(workbookXml)
      .map((element, index) => ({ element, index }))
      .filter(({ element }) => removedNames.has(element.name))
      .map(({ index }) => index),
  )
  for (const removal of plan.removals) {
    const part = partByName.get(removal)!
    const relsPartPath = part.path.replace(/worksheets\/([^/]+)$/, 'worksheets/_rels/$1.rels')
    if (await source.has(relsPartPath)) {
      assertSheetRemovable(await source.readText(relsPartPath), removal)
    }
    for (const other of parts) {
      if (removedNames.has(other.name)) continue
      if (worksheetReferencesSheet(await source.readText(other.path), removal)) {
        throw new Error(
          `工作表 "${other.name}" 的公式仍引用 "${removal}"，已拒绝删除。`,
        )
      }
    }
    for (const chartPath of await worksheetPathByChart(source)) {
      if (chartReferencesSheet(await source.readText(chartPath), removal)) {
        throw new Error(`仍有图表引用 "${removal}"，已拒绝删除。`)
      }
    }
    if (definedNamesReferenceSheet(workbookXml, removal, removedLocalIds)) {
      throw new Error(`仍有定义名称引用 "${removal}"，已拒绝删除。`)
    }
  }

  const replaced = new Map<string, string>()
  const added = new Map<string, string>()
  const removedEntries: string[] = []
  const touchedEntries: string[] = []

  // ── renames: rewrite references first ────────────────────────────────
  for (const rename of plan.renames) {
    for (const part of parts) {
      const xml = await source.readText(part.path)
      const rewritten = renameSheetReferencesInWorksheet(xml, rename.sheetName, rename.newName)
      const existing = replaced.get(part.path)
      const base = existing !== undefined ? existing : xml
      const merged = existing !== undefined
        ? renameSheetReferencesInWorksheet(base, rename.sheetName, rename.newName)
        : rewritten
      if (merged !== xml) {
        replaced.set(part.path, merged)
        touchedEntries.push(part.path)
      }
    }
    for (const chartPath of await worksheetPathByChart(source)) {
      const xml = await source.readText(chartPath)
      const rewritten = renameSheetReferencesInChart(xml, rename.sheetName, rename.newName)
      if (rewritten !== xml) {
        replaced.set(chartPath, rewritten)
        touchedEntries.push(chartPath)
      }
    }
    workbookXml = renameSheetReferencesInDefinedNames(workbookXml, rename.sheetName, rename.newName)
  }

  // ── removals: drop parts and their wiring ────────────────────────────
  for (const removal of plan.removals) {
    const part = partByName.get(removal)!
    removedEntries.push(part.path)
    const relsPartPath = part.path.replace(/worksheets\/([^/]+)$/, 'worksheets/_rels/$1.rels')
    if (await source.has(relsPartPath)) removedEntries.push(relsPartPath)
    relsXml = relsXml.replace(
      new RegExp(`<Relationship\\b[^>]*\\bId="${part.relationshipId}"[^>]*/>\\s*`),
      '',
    )
    contentTypes = contentTypes.replace(
      new RegExp(`<Override\\b[^>]*PartName="/${part.path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"[^>]*/>\\s*`),
      '',
    )
  }

  // ── additions: allocate parts ─────────────────────────────────────────
  const allocations: SheetAllocation[] = []
  let nextSheetId = maxSheetIdInWorkbook(workbookXml) + 1
  let nextRelId = maxRelationshipId(relsXml) + 1
  let nextPartIndex = 1
  const takenPaths = new Set(parts.map((part) => part.path))
  for (const addition of plan.additions) {
    let partPath = `xl/worksheets/sheet${nextPartIndex}.xml`
    while (takenPaths.has(partPath)) {
      nextPartIndex += 1
      partPath = `xl/worksheets/sheet${nextPartIndex}.xml`
    }
    takenPaths.add(partPath)
    nextPartIndex += 1
    const relationshipId = `rId${nextRelId}`
    nextRelId += 1
    const sheetId = nextSheetId
    nextSheetId += 1
    allocations.push({
      name: addition.name,
      path: partPath,
      sheetId,
      relationshipId,
    })
    added.set(partPath, buildWorksheetPartXml())
    added.set(RELS_PATH, '__MERGED_LATER__')
    relsXml = addWorksheetRelationship(relsXml, relationshipId, partPath.replace(/^xl\//, ''))
    contentTypes = addWorksheetOverride(contentTypes, partPath)
  }
  added.delete(RELS_PATH)
  replaced.set(RELS_PATH, relsXml)
  if (!touchedEntries.includes(RELS_PATH)) touchedEntries.push(RELS_PATH)
  if (contentTypes !== (await source.readText(CONTENT_TYPES_PATH))) {
    replaced.set(CONTENT_TYPES_PATH, contentTypes)
    touchedEntries.push(CONTENT_TYPES_PATH)
  }

  workbookXml = applySheetPlanToWorkbookXml(workbookXml, plan, allocations)
  replaced.set('xl/workbook.xml', workbookXml)
  touchedEntries.push('xl/workbook.xml')

  // Tab order changed or sheets were removed: calcChain sheet indexes are
  // stale — drop it for Excel to rebuild.
  if (plan.removals.length > 0) {
    const orderChanged = plan.order.some(
      (name, index) => name !== (parts[index]?.name ?? name),
    )
    if (orderChanged && (await source.has('xl/calcChain.xml'))) {
      removedEntries.push('xl/calcChain.xml')
    }
  }

  const mutationPlan: MutationPlan = {
    replaced,
    added,
    addedBinary: new Map(),
    removedEntries,
    addedEntries: [...added.keys()],
    touchedEntries,
  }
  return (await assemblePackage(sourceBytes, mutationPlan)).buffer
}

/// worksheet part path → its relationships part path.
function relsPathFor(partPath: string): string {
  const slash = partPath.lastIndexOf('/')
  return `${partPath.slice(0, slash + 1)}_rels/${partPath.slice(slash + 1)}.rels`
}

/// Resolves the parts behind a worksheet's relationship-typed elements
/// (drawings, tables, legacy VML): `<drawing r:id>` / `<tablePart r:id>` /
/// `<legacyDrawing r:id>` → rels → path.
async function relatedPartPaths(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
  worksheetXml: string,
  worksheetPath: string,
  elementTag: 'drawing' | 'tablePart' | 'legacyDrawing',
): Promise<string[]> {
  const relIds = [...worksheetXml.matchAll(new RegExp(`<${elementTag}\\b[^>]*\\br:id="([^"]+)"`, 'g'))].map(
    (match) => match[1] ?? '',
  )
  if (relIds.length === 0) return []
  const relsPath = relsPathFor(worksheetPath)
  if (!(await source.has(relsPath))) return []
  const relsXml = await source.readText(relsPath)
  const paths: string[] = []
  for (const relId of relIds) {
    if (!relId) continue
    const relationship = relsXml.match(
      new RegExp(`<Relationship\\b[^>]*\\bId="${relId}"[^>]*/>`),
    )?.[0]
    if (!relationship) continue
    const target = relationship.match(/\bTarget="([^"]+)"/)?.[1]
    if (!target) continue
    // targets are relative to xl/worksheets/ — normalize ../drawings/x.xml
    const base = 'xl/worksheets'
    const resolved = new URL(target, `http://pkg/${base}/`).pathname.replace(/^\//, '')
    if ((await source.has(resolved)) && !paths.includes(resolved)) paths.push(resolved)
  }
  return paths
}

/// Insert/remove rows or columns on one sheet: shifts the sheet's geometry,
/// its own formulas, other sheets' qualified formulas, defined names, ranged
/// features (autoFilter / validations / conditional formats), drawing anchors,
/// and the dimension. Fails closed on features this build cannot shift around.
export async function applyRowColumnOps(
  sourceBytes: Uint8Array,
  sheetName: string,
  ops: readonly StructuralOp[],
): Promise<Uint8Array> {
  if (ops.length === 0) return sourceBytes
  const source = await createBufferEntrySource(sourceBytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const parts = await sheetPartsOf(source, workbookXml)
  const target = parts.find((part) => part.name === sheetName)
  if (!target) throw new Error(`workbook.xml 中找不到工作表 "${sheetName}"。`)

  const targetXml = await source.readText(target.path)
  assertShiftable(targetXml)
  // Notes can belong to cells with no stored cell value or row record.
  let xml = targetXml.replace(/<sheetData\b([^>]*)\/>/, '<sheetData$1></sheetData>')
  for (const op of ops) {
    xml = applyStructuralOp(xml, op, sheetName)
  }
  const specs: ShiftSpec[] = ops.map((op) => shiftSpecOf(op))

  const replaced = new Map<string, string>([[target.path, xml]])
  const touchedEntries = [target.path]

  // drawing anchors travel with the sheet (charts, images, shapes)
  for (const drawingPath of await relatedPartPaths(source, targetXml, target.path, 'drawing')) {
    const drawingXml = await source.readText(drawingPath)
    const shifted = shiftDrawingAnchors(drawingXml, specs)
    if (shifted !== drawingXml) {
      replaced.set(drawingPath, shifted)
      touchedEntries.push(drawingPath)
    }
  }

  // chart series references follow the sheet's geometry: the anchor moving
  // without the data reference would silently desync the plot (the same class
  // of bug sparklines fail closed on — charts CAN shift, so they do)
  for (const chartPath of await worksheetPathByChart(source)) {
    const chartXml = await source.readText(chartPath)
    let shifted = chartXml
    for (const spec of specs) {
      shifted = shiftChartSeriesReferences(shifted, spec, sheetName)
    }
    if (shifted !== chartXml) {
      replaced.set(chartPath, shifted)
      touchedEntries.push(chartPath)
    }
  }

  // Notes and worksheet geometry are committed in a single package mutation.
  const notePlan = await shiftSheetNotes(source, target.path, specs, xml)
  for (const [path, content] of notePlan.replaced) replaced.set(path, content)
  touchedEntries.push(...notePlan.touchedEntries)

  // VML Pict shapes (form controls) behind <legacyDrawing> shift their anchors
  for (const vmlPath of await relatedPartPaths(source, targetXml, target.path, 'legacyDrawing')) {
    if (notePlan.removedEntries.includes(vmlPath)) continue
    const vmlXml = replaced.get(vmlPath) ?? await source.readText(vmlPath)
    const shifted = shiftVmlObjectAnchors(vmlXml, specs)
    if (shifted !== vmlXml) {
      replaced.set(vmlPath, shifted)
      touchedEntries.push(vmlPath)
    }
  }

  // table parts shift their ref/ranges and reshape columns on insert/delete;
  // inserted columns need their header cell text written into the worksheet
  for (const tablePath of await relatedPartPaths(source, targetXml, target.path, 'tablePart')) {
    const tableXml = await source.readText(tablePath)
    const { xml: shifted, insertions } = shiftTablePart(tableXml, specs)
    if (shifted !== tableXml) {
      replaced.set(tablePath, shifted)
      touchedEntries.push(tablePath)
    }
    for (const insertion of insertions) {
      if (insertion.headerRow === null) continue
      for (const column of insertion.columns) {
        const address = `${columnLetters(column.column)}${insertion.headerRow + 1}`
        const worksheet = replaced.get(target.path)!
        replaced.set(target.path, setWorksheetCellText(worksheet, address, column.name))
      }
    }
  }

  // other sheets: only refs qualified with the target sheet shift
  for (const part of parts) {
    if (part.name === sheetName) continue
    const otherXml = await source.readText(part.path)
    let shifted = otherXml
    for (const spec of specs) {
      shifted = shiftQualifiedFormulas(shifted, spec, sheetName)
    }
    if (shifted !== otherXml) {
      replaced.set(part.path, shifted)
      touchedEntries.push(part.path)
    }
  }

  // defined names referencing the sheet shift too
  let nextWorkbookXml = workbookXml
  for (const spec of specs) {
    nextWorkbookXml = shiftDefinedNames(nextWorkbookXml, spec, sheetName)
  }
  if (nextWorkbookXml !== workbookXml) {
    replaced.set('xl/workbook.xml', nextWorkbookXml)
    touchedEntries.push('xl/workbook.xml')
  }

  const mutationPlan: MutationPlan = {
    replaced,
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: notePlan.removedEntries,
    addedEntries: [],
    touchedEntries,
  }
  return (await assemblePackage(sourceBytes, mutationPlan)).buffer
}

/// Full-fidelity range sort for the server path: permutes the raw <c> cell
/// records (value, type marker and style index move together, matching the
/// official grid reorder) instead of rewriting bare values. Row-level
/// attributes (heights, formats) stay in place like Excel's sort. Formulas
/// and notes make the call fail closed: formula text moved between rows
/// would silently re-target relative references, and note relocation rides
/// the grid path where the move payload preserves authors.
export async function sortRangeRows(sourceBytes: Uint8Array, sheetName: string,
  spec: { range: string; byColumn: string; ascending: boolean; hasHeader: boolean }): Promise<Uint8Array> {
  const model = await readWorkbook(sourceBytes)
  const sheet = model.sheets.find(entry => entry.name === sheetName)
  if (!sheet) throw new Error(`workbook.xml 中找不到工作表 "${sheetName}"。`)
  const bounds = parseRange(spec.range)
  const keyColumn = columnIndex(spec.byColumn)
  if (keyColumn < bounds.startColumn || keyColumn > bounds.endColumn) throw new Error(`Sort column ${spec.byColumn} is outside the range ${spec.range}.`)
  const inRange = (row: number, column: number) => row >= bounds.startRow && row <= bounds.endRow && column >= bounds.startColumn && column <= bounds.endColumn
  for (const [address, cell] of Object.entries(sheet.cells)) {
    if (!cell.formula) continue
    const { row, column } = parseAddress(address)
    if (inRange(row, column)) throw new Error(`The sort range contains a formula at ${address} — sorting would silently re-target its references.`)
  }
  if (sheet.notes) for (const note of sheet.notes.notes) {
    if (inRange(note.row, note.column)) throw new Error('排序范围包含批注；请改用网格排序以保留批注作者。')
  }
  const firstDataRow = bounds.startRow + (spec.hasHeader ? 1 : 0)
  if (firstDataRow >= bounds.endRow) throw new Error('The sort range needs at least two data rows.')
  const rows: (string | number | boolean | null)[][] = []
  for (let row = firstDataRow; row <= bounds.endRow; row += 1) {
    const cells: (string | number | boolean | null)[] = []
    for (let column = bounds.startColumn; column <= bounds.endColumn; column += 1) cells.push(sheet.cells[formatAddress(row, column)]?.value ?? null)
    rows.push(cells)
  }
  const order = computeSortedRowOrder(rows, keyColumn - bounds.startColumn, spec.ascending)

  const source = await createBufferEntrySource(sourceBytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const parts = await sheetPartsOf(source, workbookXml)
  const target = parts.find(part => part.name === sheetName)
  if (!target) throw new Error(`workbook.xml 中找不到工作表 "${sheetName}"。`)
  const worksheetXml = await source.readText(target.path)
  const sheetData = worksheetXml.match(/([\s\S]*?<sheetData[^>]*>)([\s\S]*?)(<\/sheetData>[\s\S]*)/)
  if (!sheetData?.[1] || sheetData[3] === undefined) throw new Error('Worksheet has no sheetData element.')
  const cellPattern = /<c\b[^>]*?(?:\/>|>[\s\S]*?<\/c>)/g
  const rowPattern = /<row\b[^>]*?(?:\/>|>[\s\S]*?<\/row>)/g
  const rangeCells = new Map<number, Map<number, string>>()
  const rangeRowXml = new Map<number, string>()
  for (const rowMatch of sheetData[2]!.matchAll(rowPattern)) {
    const rowXml = rowMatch[0]
    const rowIndex = Number(rowXml.match(/\br="([0-9]+)"/)?.[1] ?? '0') - 1
    if (rowIndex < firstDataRow || rowIndex > bounds.endRow) continue
    rangeRowXml.set(rowIndex, rowXml)
    const cells = new Map<number, string>()
    const inner = rowXml.match(/^(<row\b[^>]*>)([\s\S]*?)(<\/row>)$/)?.[2]
      ?? (/<row\b[^>]*\/>$/.test(rowXml) ? '' : rowXml)
    for (const cellMatch of inner.matchAll(cellPattern)) {
      const cellXml = cellMatch[0]
      const address = cellXml.match(/\br="([A-Z]{1,3})([0-9]+)"/)
      if (!address?.[1]) continue
      const column = columnIndex(address[1])
      if (column >= bounds.startColumn && column <= bounds.endColumn) cells.set(column, cellXml)
    }
    rangeCells.set(rowIndex, cells)
  }
  const renumberRow = (cellXml: string, row: number): string =>
    cellXml.replace(/\br="([A-Z]{1,3})[0-9]+"/, (_full, letters: string) => `r="${letters}${row + 1}"`)
  const columnNumberOf = (cellXml: string): number => columnIndex(cellXml.match(/\br="([A-Z]{1,3})[0-9]+"/)?.[1] ?? 'A')
  const rebuiltRows = new Map<number, string>()
  for (let row = firstDataRow; row <= bounds.endRow; row += 1) {
    const moved = rangeCells.get(firstDataRow + order[row - firstDataRow]!) ?? new Map<number, string>()
    const existing = rangeRowXml.get(row)
    const rowMatch = existing?.match(/^(<row\b[^>]*>)([\s\S]*?)(<\/row>)$/)
    const kept: string[] = []
    if (rowMatch?.[2]) for (const cellMatch of rowMatch[2].matchAll(cellPattern)) {
      const cellXml = cellMatch[0]
      const column = columnIndex(cellXml.match(/\br="([A-Z]{1,3})[0-9]+"/)?.[1] ?? 'A')
      if (column < bounds.startColumn || column > bounds.endColumn) kept.push(cellXml)
    }
    const pieces = [...kept]
    for (let column = bounds.startColumn; column <= bounds.endColumn; column += 1) {
      const cellXml = moved.get(column)
      if (cellXml) pieces.push(renumberRow(cellXml, row))
    }
    pieces.sort((left, right) => columnNumberOf(left) - columnNumberOf(right))
    if (rowMatch) rebuiltRows.set(row, `${rowMatch[1]}${pieces.join('')}${rowMatch[3]}`)
    else if (pieces.length) rebuiltRows.set(row, `<row r="${row + 1}">${pieces.join('')}</row>`)
  }
  // Rows the range must add (absent from sheetData) are spliced in row order:
  // before the first existing row with a higher index, else at the end of the
  // sheetData body (which excludes the closing tag). OOXML requires ascending rows.
  const additions = [...rebuiltRows.entries()].filter(([row]) => !rangeRowXml.has(row))
    .sort(([left], [right]) => left - right)
  const body = sheetData[2]!.replace(rowPattern, rowXml => {
    const rowIndex = Number(rowXml.match(/\br="([0-9]+)"/)?.[1] ?? '0') - 1
    let inserted = ''
    while (additions.length && additions[0]![0] < rowIndex) inserted += additions.shift()![1]
    return inserted + (rebuiltRows.get(rowIndex) ?? rowXml)
  })
  const nextBody = body + additions.map(([, xml]) => xml).join('')
  const mutationPlan: MutationPlan = {
    replaced: new Map([[target.path, `${sheetData[1]}${nextBody}${sheetData[3]}`]]),
    added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [],
    touchedEntries: [target.path],
  }
  return (await assemblePackage(sourceBytes, mutationPlan)).buffer
}
