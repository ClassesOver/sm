/// Sheet-level workbook surgery, ported (trimmed) from genoffice
/// xlsx-sheets.ts: rename (rewrites every qualified reference — other sheets'
/// formulas, defined names, chart series), add, and remove (fails closed when
/// anything still references the sheet). Structural shared-formula clones and
/// pivot-cache renames are out of the web scope.

import { decodeXmlText, escapeXmlAttribute, escapeXmlText, readXmlAttribute } from './xml'
import { SaxesParser } from 'saxes'

/// '>' is legal inside XML attribute values (sheet names can carry it), so
/// element scans consume quoted runs atomically instead of using [^>]*.
const TAG_ATTRIBUTES = `(?:"[^"]*"|'[^']*'|[^>"'])*?`

export class SheetEditError extends Error {}

export interface SheetEditPlan {
  /// original file name → new name
  readonly renames: readonly { readonly sheetName: string; readonly newName: string }[]
  /// final names of new blank sheets
  readonly additions: readonly { readonly name: string }[]
  /// original file names of sheets to delete
  readonly removals: readonly string[]
  /// the complete final tab order, as final names
  readonly order: readonly string[]
}

export interface SheetAllocation {
  readonly name: string
  readonly path: string
  readonly sheetId: number
  readonly relationshipId: string
}

const INVALID_NAME_CHARACTERS = /[\\/?*[\]:]/

export function validateSheetName(name: string): void {
  if (name.length === 0 || name.length > 31) {
    throw new SheetEditError(`Sheet name "${name}" must be 1-31 characters long.`)
  }
  if (INVALID_NAME_CHARACTERS.test(name)) {
    throw new SheetEditError(
      `Sheet name "${name}" contains a forbidden character (\\ / ? * [ ] :).`,
    )
  }
  if (name.startsWith("'") || name.endsWith("'")) {
    throw new SheetEditError(`Sheet name "${name}" cannot start or end with an apostrophe.`)
  }
}

/// Quotes a sheet name for use as a formula qualifier when Excel requires it
/// (non-identifier characters, or a name that parses as a cell reference).
export function formatSheetQualifier(name: string): string {
  const needsQuoting =
    !/^[A-Za-z_][A-Za-z0-9_.]*$/.test(name) ||
    /^[A-Za-z]{1,3}[0-9]+$/.test(name) ||
    /^(?:TRUE|FALSE)$/i.test(name) ||
    /^R[0-9]*C[0-9]*$/i.test(name)
  return needsQuoting ? `'${name.replaceAll("'", "''")}'` : name
}

/// A1-style token, optionally sheet-qualified: cell, cell range, whole-column
/// range, or whole-row range. Unicode-letter qualifiers (Excel allows unquoted
/// non-ASCII sheet names) — shared with the structural module's semantics.
export const FORMULA_REFERENCE_PATTERN = new RegExp(
  "(^|[^\\p{L}\\p{N}_.$'!:])" +
    "(?:('(?:[^']|'')+'|[\\p{L}_][\\p{L}\\p{N}_.]*)!)?" +
    '(\\$?[A-Z]{1,3}\\$?[0-9]+(?::\\$?[A-Z]{1,3}\\$?[0-9]+)?' +
    '|\\$?[A-Z]{1,3}:\\$?[A-Z]{1,3}' +
    '|\\$?[0-9]+:\\$?[0-9]+)' +
    '(?![0-9\\p{L}_(])',
  'gu',
)
const SHEET_FORMULA_REFERENCE_PATTERN = new RegExp(FORMULA_REFERENCE_PATTERN.source, 'giu')

export function qualifierMatches(qualifier: string, sheetName: string): boolean {
  const unquoted = qualifier.startsWith("'")
    ? qualifier.slice(1, -1).replaceAll("''", "'")
    : qualifier
  return unquoted.toUpperCase() === sheetName.toUpperCase()
}

/// Rewrites references qualified with oldName to newName inside one formula.
/// String literals ("" escaping) are left untouched.
export function renameSheetInFormula(formula: string, oldName: string, newName: string): string {
  return formula
    .split('"')
    .map((segment, index) =>
      index % 2 === 1
        ? segment
        : segment.replace(
            SHEET_FORMULA_REFERENCE_PATTERN,
            (full, lead: string, qualifier: string | undefined, token: string) => {
              // An unquoted external workbook ends immediately before the sheet
              // qualifier: [book.xlsx]Source!A1 is not this workbook's Source.
              if (lead === ']' || qualifier === undefined || !qualifierMatches(qualifier, oldName)) return full
              return `${lead}${formatSheetQualifier(newName)}!${token}`
            },
          ),
    )
    .join('"')
}

/// True when the formula contains a reference qualified with sheetName.
export function formulaReferencesSheet(formula: string, sheetName: string): boolean {
  let found = false
  formula.split('"').forEach((segment, index) => {
    if (index % 2 === 1 || found) return
    segment.replace(
      SHEET_FORMULA_REFERENCE_PATTERN,
      (_full, lead: string, qualifier: string | undefined) => {
        if (lead !== ']' && qualifier !== undefined && qualifierMatches(qualifier, sheetName)) found = true
        return ''
      },
    )
  })
  return found
}

/// Rewrites qualified references in a worksheet part: formula bodies, CF/DV
/// rule formulas, and internal hyperlink anchors.
export function renameSheetReferencesInWorksheet(
  worksheetXml: string,
  oldName: string,
  newName: string,
): string {
  // Self-closing `<f .../>` (shared-formula followers) must not match, or
  // the XML up to the next `</f>` would be swallowed as a formula body.
  let xml = worksheetXml.replace(
    /<f\b([^>]*[^/>])?>([\s\S]*?)<\/f>/g,
    (_full, attributes: string | undefined, body: string) =>
      `<f${attributes ?? ''}>${escapeXmlText(renameSheetInFormula(decodeXmlText(body), oldName, newName))}</f>`,
  )
  xml = xml.replace(
    /<(formula[12]?|xm:f)>([\s\S]*?)<\/\1>/g,
    (_full, tag: string, body: string) =>
      `<${tag}>${escapeXmlText(renameSheetInFormula(decodeXmlText(body), oldName, newName))}</${tag}>`,
  )
  xml = xml.replace(new RegExp(`<(?:x14:)?cfvo\\b${TAG_ATTRIBUTES}>`, 'g'), node => {
    if (readXmlAttribute(node, 'type') !== 'formula') return node
    return node.replace(/(\sval\s*=\s*)(["'])([\s\S]*?)\2/g, (full, prefix: string, quote: string, value: string) => {
      const formula = decodeXmlText(value), renamed = renameSheetInFormula(formula, oldName, newName)
      if (renamed === formula) return full
      return `${prefix}${quote}${escapeXmlAttribute(renamed)}${quote}`
    })
  })
  return xml.replace(
    new RegExp(`(<hyperlink\\b${TAG_ATTRIBUTES}\\blocation=")([^"]+)(")`, 'g'),
    (full, prefix: string, location: string, suffix: string) => {
      const match = decodeXmlText(location).match(/^('(?:[^']|'')+'|[^'!]+)!([\s\S]*)$/)
      if (!match?.[1] || match[2] === undefined) return full
      if (!qualifierMatches(match[1], oldName)) return full
      const renamed = `${formatSheetQualifier(newName)}!${match[2]}`
      return `${prefix}${escapeXmlAttribute(renamed)}${suffix}`
    },
  )
}

/** Local compatibility fix: source regex only recognises c:f, not the chart namespace. */
export function renameSheetReferencesInChart(
  chartXml: string,
  oldName: string,
  newName: string,
): string {
  const parser = new SaxesParser({ xmlns: true })
  const replacements: { start: number; end: number; value: string }[] = []
  let formula: { start: number; text: string } | undefined
  parser.on('opentag', tag => {
    if (formula) throw new Error('图表公式不得包含嵌套元素')
    if (tag.local === 'f' && tag.uri === 'http://schemas.openxmlformats.org/drawingml/2006/chart' && !tag.isSelfClosing)
      formula = { start: parser.position, text: '' }
  })
  const append = (value: string) => { if (formula) formula.text += value }
  parser.on('text', append)
  parser.on('cdata', append)
  parser.on('closetag', tag => {
    if (!formula || tag.local !== 'f' || tag.uri !== 'http://schemas.openxmlformats.org/drawingml/2006/chart') return
    const renamed = renameSheetInFormula(formula.text, oldName, newName)
    if (renamed !== formula.text) replacements.push({
      start: formula.start,
      end: chartXml.lastIndexOf('</', parser.position - 1),
      value: escapeXmlText(renamed),
    })
    formula = undefined
  })
  // Parse the complete part before applying any edits; invalid XML cannot produce a partial rewrite.
  parser.write(chartXml).close()
  let result = chartXml
  for (const replacement of replacements.reverse())
    result = result.slice(0, replacement.start) + replacement.value + result.slice(replacement.end)
  return result
}

/// Rewrites qualified references in workbook definedName bodies.
export function renameSheetReferencesInDefinedNames(
  workbookXml: string,
  oldName: string,
  newName: string,
): string {
  return workbookXml.replace(
    /(<definedName\b[^>]*>)([\s\S]*?)(<\/definedName>)/g,
    (_full, open: string, body: string, close: string) =>
      `${open}${escapeXmlText(renameSheetInFormula(decodeXmlText(body), oldName, newName))}${close}`,
  )
}

export function worksheetReferencesSheet(worksheetXml: string, sheetName: string): boolean {
  for (const pattern of [
    /<f\b(?:[^>]*[^/>])?>([\s\S]*?)<\/f>/g,
    /<(?:formula[12]?|xm:f)>([\s\S]*?)<\/(?:formula[12]?|xm:f)>/g,
  ]) {
    for (const match of worksheetXml.matchAll(pattern)) {
      if (formulaReferencesSheet(decodeXmlText(match[1] ?? ''), sheetName)) return true
    }
  }
  for (const match of worksheetXml.matchAll(new RegExp(`<(?:x14:)?cfvo\\b${TAG_ATTRIBUTES}>`, 'g'))) {
    if (readXmlAttribute(match[0], 'type') !== 'formula') continue
    const formula = readXmlAttribute(match[0], 'val')
    if (formula !== undefined && formulaReferencesSheet(decodeXmlText(formula), sheetName)) return true
  }
  return false
}

/** Namespace-scoped chart formulas; malformed XML throws before deletion. */
export function readChartFormulas(chartXml: string): string[] {
  const parser = new SaxesParser({ xmlns: true })
  const formulas: string[] = []
  let formula: string | undefined
  parser.on('opentag', tag => {
    if (tag.local === 'f' && tag.uri === 'http://schemas.openxmlformats.org/drawingml/2006/chart') formula = ''
  })
  const append = (value: string) => { if (formula !== undefined) formula += value }
  parser.on('text', append)
  parser.on('cdata', append)
  parser.on('closetag', tag => {
    if (tag.local !== 'f' || tag.uri !== 'http://schemas.openxmlformats.org/drawingml/2006/chart') return
    if (formula !== undefined) formulas.push(formula)
    formula = undefined
  })
  parser.write(chartXml).close()
  return formulas
}

export function chartReferencesSheet(chartXml: string, sheetName: string): boolean {
  return readChartFormulas(chartXml).some(formula => formulaReferencesSheet(formula, sheetName))
}

/// Blank worksheet part for added sheets.
export function buildWorksheetPartXml(): string {
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"' +
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
    '<dimension ref="A1"/><sheetViews><sheetView workbookViewId="0"/></sheetViews>' +
    '<sheetData/></worksheet>'
  )
}

export function maxSheetIdInWorkbook(workbookXml: string): number {
  let max = 0
  for (const match of workbookXml.matchAll(/\bsheetId="([0-9]+)"/g)) {
    max = Math.max(max, Number(match[1]))
  }
  return max
}

export function maxRelationshipId(relationshipsXml: string): number {
  let max = 0
  for (const match of relationshipsXml.matchAll(/\bId="rId([0-9]+)"/g)) {
    max = Math.max(max, Number(match[1]))
  }
  return max
}

/// Rebuilds workbook.xml for the plan: sheet elements renamed / added /
/// removed and re-assembled in the final order, definedName localSheetId
/// scopes renumbered (or dropped with their sheet), and the active tab
/// clamped to a surviving visible sheet.
export function applySheetPlanToWorkbookXml(
  workbookXml: string,
  plan: SheetEditPlan,
  additions: readonly SheetAllocation[],
): string {
  const elements = sheetElementsOf(workbookXml)
  const originalNames = elements.map((element) => element.name)
  const renameByOriginal = new Map(plan.renames.map((rename) => [rename.sheetName, rename.newName]))
  const removedSet = new Set(plan.removals)

  const finalElements = new Map<string, { xml: string; hidden: boolean }>()
  for (const element of elements) {
    if (removedSet.has(element.name)) continue
    const newName = renameByOriginal.get(element.name)
    const xml =
      newName === undefined
        ? element.xml
        : element.xml.replace(/\bname="[^"]*"/, () => `name="${escapeXmlAttribute(newName)}"`)
    finalElements.set(newName ?? element.name, { xml, hidden: element.hidden })
  }
  for (const addition of additions) {
    finalElements.set(addition.name, {
      // Declare the relationships prefix on the element itself: producers such as
      // openpyxl bind xmlns:r per <sheet> rather than on <workbook>, and an
      // undeclared r:id makes the whole workbook unreadable (found by the
      // real-browser smoke: add sheet + save on an openpyxl source).
      xml: `<sheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" name="${escapeXmlAttribute(addition.name)}" sheetId="${addition.sheetId}" r:id="${addition.relationshipId}"/>`,
      hidden: false,
    })
  }

  if (
    plan.order.length !== finalElements.size ||
    plan.order.some((name) => !finalElements.has(name))
  ) {
    throw new SheetEditError('The sheet order does not match the final sheet set.')
  }
  if (plan.order.every((name) => finalElements.get(name)?.hidden)) {
    throw new SheetEditError('A workbook needs at least one visible sheet.')
  }

  const sheetsInner = plan.order.map((name) => finalElements.get(name)?.xml ?? '').join('')
  let result = workbookXml.replace(
    /<sheets>[\s\S]*?<\/sheets>/,
    () => `<sheets>${sheetsInner}</sheets>`,
  )

  // Defined-name scopes are positional (localSheetId = tab index).
  const oldIndexToNew = (oldIndex: number): number | null => {
    const originalName = originalNames[oldIndex]
    if (originalName === undefined || removedSet.has(originalName)) return null
    return plan.order.indexOf(renameByOriginal.get(originalName) ?? originalName)
  }
  result = result.replace(
    /<definedName\b[^>]*?\blocalSheetId="([0-9]+)"[^>]*>[\s\S]*?<\/definedName>/g,
    (full, localId: string) => {
      if (originalNames[Number(localId)] === undefined) return full
      const mapped = oldIndexToNew(Number(localId))
      if (mapped === null) return ''
      return full.replace(/\blocalSheetId="[0-9]+"/, () => `localSheetId="${mapped}"`)
    },
  )
  result = result.replace(/<definedNames>\s*<\/definedNames>/, '')

  result = result.replace(
    /(<workbookView\b[^>]*?\bactiveTab=")([0-9]+)(")/,
    (full, prefix: string, activeTab: string, suffix: string) => {
      const mapped = oldIndexToNew(Number(activeTab))
      const fallback = plan.order.findIndex((name) => !finalElements.get(name)?.hidden)
      return mapped === null || mapped === undefined
        ? `${prefix}${Math.max(fallback, 0)}${suffix}`
        : `${prefix}${mapped}${suffix}`
    },
  )

  return result
}

interface RawSheetElement {
  readonly xml: string
  readonly name: string
  readonly hidden: boolean
}

function sheetElementsOf(workbookXml: string): RawSheetElement[] {
  const elements: RawSheetElement[] = []
  for (const match of workbookXml.matchAll(
    new RegExp(`<sheet\\b${TAG_ATTRIBUTES}(?:/>|>[\\s\\S]*?</sheet>)`, 'g'),
  )) {
    const xml = match[0]
    const name = readXmlAttribute(xml, 'name')
    if (name === undefined) continue
    const state = readXmlAttribute(xml, 'state')
    elements.push({
      xml,
      name: decodeXmlText(name),
      hidden: state === 'hidden' || state === 'veryHidden',
    })
  }
  return elements
}

export function addWorksheetOverride(contentTypesXml: string, partPath: string): string {
  const override = `<Override PartName="/${partPath}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`
  if (!contentTypesXml.includes('</Types>')) {
    throw new SheetEditError('The workbook has no [Content_Types].xml Types element.')
  }
  return contentTypesXml.replace('</Types>', () => `${override}</Types>`)
}

export function addWorksheetRelationship(
  relationshipsXml: string,
  relationshipId: string,
  target: string,
): string {
  const relationship = `<Relationship Id="${relationshipId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="${target}"/>`
  if (!relationshipsXml.includes('</Relationships>')) {
    throw new SheetEditError('The workbook has no relationships part.')
  }
  return relationshipsXml.replace('</Relationships>', () => `${relationship}</Relationships>`)
}

export function removeRelationshipById(relationshipsXml: string, relationshipId: string): string {
  return relationshipsXml.replace(
    new RegExp(`<Relationship\\b[^>]*\\bId="${relationshipId}"[^>]*/>\\s*`),
    '',
  )
}

/// Relationship types whose targets never block a sheet removal: hyperlink
/// targets are external (or workbook-internal anchors that die with the
/// sheet's part), and printer settings survive as harmless orphans.
const IGNORABLE_SHEET_RELATIONSHIP_TYPES = /\/(?:hyperlink|printerSettings)$/

/// The web engine does not cascade-delete owned satellite parts; any owned or
/// unknown part on a sheet blocks its removal (fail closed).
export function assertSheetRemovable(relsXml: string, sheetName: string): void {
  for (const match of relsXml.matchAll(/<Relationship\b[^>]*?\/>/g)) {
    const element = match[0]
    const type = readXmlAttribute(element, 'Type') ?? ''
    if (readXmlAttribute(element, 'TargetMode') === 'External') continue
    if (IGNORABLE_SHEET_RELATIONSHIP_TYPES.test(type)) continue
    const kind = /\/drawing$/.test(type)
      ? 'charts or images'
      : /\/table$/.test(type)
        ? 'a table'
        : /\/pivotTable$/.test(type)
          ? 'a pivot table'
          : `a part this build cannot delete safely (${type})`
    throw new SheetEditError(
      `Sheet "${sheetName}" carries ${kind} — deleting it is not supported yet.`,
    )
  }
}

/// DefinedNames scoped to a removed sheet are dropped with it, so their
/// bodies referencing the sheet must not block the removal.
export function definedNamesReferenceSheet(
  workbookXml: string,
  sheetName: string,
  removedLocalIds: ReadonlySet<number>,
): boolean {
  for (const match of workbookXml.matchAll(/<definedName\b([^>]*)>([\s\S]*?)<\/definedName>/g)) {
    const localId = readXmlAttribute(`<definedName${match[1] ?? ''}/>`, 'localSheetId')
    if (localId !== undefined && removedLocalIds.has(Number(localId))) continue
    if (formulaReferencesSheet(decodeXmlText(match[2] ?? ''), sheetName)) return true
  }
  return false
}
