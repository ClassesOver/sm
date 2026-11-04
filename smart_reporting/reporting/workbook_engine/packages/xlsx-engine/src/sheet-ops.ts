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
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
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
  let xml = targetXml
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

  // VML Pict shapes (form controls) behind <legacyDrawing> shift their anchors
  for (const vmlPath of await relatedPartPaths(source, targetXml, target.path, 'legacyDrawing')) {
    const vmlXml = await source.readText(vmlPath)
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
    removedEntries: [],
    addedEntries: [],
    touchedEntries,
  }
  return (await assemblePackage(sourceBytes, mutationPlan)).buffer
}
