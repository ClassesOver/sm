/// Worksheet/workbook protection writer, ported from genoffice
/// xlsx-protection.ts: adds or removes `<sheetProtection>`, workbook structure
/// protection (`<workbookProtection>`), and allow-edit ranges
/// (`<protectedRanges>`). No password support — unprotecting a
/// password-protected target fails closed.

import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { assemblePackage, createBufferEntrySource } from './zip'

export class SheetProtectionError extends Error {}

const ELEMENT_PATTERN = /<sheetProtection\b[^>]*\/>|<sheetProtection\b[^>]*>\s*<\/sheetProtection>/

export function applySheetProtection(worksheetXml: string, protect: boolean): string {
  const existing = worksheetXml.match(ELEMENT_PATTERN)
  if (!protect) {
    if (!existing) return worksheetXml
    if (/\b(?:password|hashValue)="/.test(existing[0])) {
      throw new SheetProtectionError(
        'This sheet is protected with a password — removing its protection is not supported.',
      )
    }
    return worksheetXml.replace(existing[0], '')
  }
  if (existing) {
    if (/\bsheet="(?:1|true)"/.test(existing[0])) return worksheetXml
    const updated = existing[0].includes(' sheet="')
      ? existing[0].replace(/ sheet="[^"]*"/, ' sheet="1"')
      : existing[0].replace(/<sheetProtection\b/, '<sheetProtection sheet="1"')
    return worksheetXml.replace(existing[0], updated)
  }
  // Excel's defaults when protecting without a password. Schema order: the
  // element follows sheetData (and sheetCalcPr when present).
  const element = '<sheetProtection sheet="1" objects="1" scenarios="1"/>'
  const anchor =
    worksheetXml.match(/<sheetCalcPr\b[^>]*\/?>/) ??
    worksheetXml.match(/<\/sheetData>|<sheetData\b[^>]*\/>/)
  if (!anchor || anchor.index === undefined) {
    throw new SheetProtectionError('Worksheet has no sheetData element.')
  }
  const at = anchor.index + anchor[0].length
  return worksheetXml.slice(0, at) + element + worksheetXml.slice(at)
}

const WORKBOOK_PROTECTION_PATTERN =
  /<workbookProtection\b[^>]*\/>|<workbookProtection\b[^>]*>\s*<\/workbookProtection>/

/// Workbook structure lock in workbook.xml. Unlocking a password-protected
/// structure fails closed; other workbookProtection attributes stay verbatim.
export function applyWorkbookProtection(workbookXml: string, lockStructure: boolean): string {
  const existing = workbookXml.match(WORKBOOK_PROTECTION_PATTERN)
  if (!lockStructure) {
    if (!existing || existing.index === undefined) return workbookXml
    if (/\bworkbook(?:Password|HashValue)="/.test(existing[0])) {
      throw new SheetProtectionError(
        'The workbook structure is protected with a password — removing its protection is not supported.',
      )
    }
    const stripped = existing[0].replace(/\s+lockStructure="[^"]*"/, '')
    // Drop the element entirely once no protection attribute remains.
    const empty = /^<workbookProtection\s*(?:\/>|>\s*<\/workbookProtection>)$/.test(stripped)
    return (
      workbookXml.slice(0, existing.index) +
      (empty ? '' : stripped) +
      workbookXml.slice(existing.index + existing[0].length)
    )
  }
  if (existing && existing.index !== undefined) {
    if (/\blockStructure="(?:1|true)"/.test(existing[0])) return workbookXml
    const updated = /\slockStructure="/.test(existing[0])
      ? existing[0].replace(/(\s+lockStructure=)"[^"]*"/, '$1"1"')
      : existing[0].replace(/<workbookProtection\b/, '<workbookProtection lockStructure="1"')
    return (
      workbookXml.slice(0, existing.index) +
      updated +
      workbookXml.slice(existing.index + existing[0].length)
    )
  }
  // Schema order: workbookProtection follows fileVersion/fileSharing/
  // workbookPr/alternateContent and precedes bookViews/sheets.
  const element = '<workbookProtection lockStructure="1"/>'
  const anchor = workbookXml.match(/<bookViews\b|<sheets\b/)
  if (!anchor || anchor.index === undefined) {
    throw new SheetProtectionError('Workbook has no sheets element.')
  }
  return workbookXml.slice(0, anchor.index) + element + workbookXml.slice(anchor.index)
}

export interface ProtectedRangeState {
  readonly name: string
  readonly sqref: string
}

const PROTECTED_RANGES_PATTERN =
  /<protectedRanges\b[^>]*\/>|<protectedRanges\b[^>]*>[\s\S]*?<\/protectedRanges>/

function escapeAttr(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

/// Replaces the sheet's allow-edit ranges with the session's snapshot; an
/// empty set removes the element. Replacing password-protected ranges fails
/// closed (their hashes cannot be preserved through the rewrite).
export function applyProtectedRanges(
  worksheetXml: string,
  ranges: readonly ProtectedRangeState[],
): string {
  const existing = worksheetXml.match(PROTECTED_RANGES_PATTERN)
  // securityDescriptor carries per-user permissions (attribute or child
  // element form); rewriting name+sqref only would silently fail open.
  if (existing && /\b(?:password|hashValue)="|securityDescriptor/.test(existing[0])) {
    throw new SheetProtectionError(
      'This sheet has password- or permission-protected edit ranges — editing them is not supported.',
    )
  }
  const stripped =
    existing && existing.index !== undefined
      ? worksheetXml.slice(0, existing.index) +
        worksheetXml.slice(existing.index + existing[0].length)
      : worksheetXml
  if (ranges.length === 0) return stripped
  const body = ranges
    .map(
      (range) =>
        `<protectedRange sqref="${escapeAttr(range.sqref)}" name="${escapeAttr(range.name)}"/>`,
    )
    .join('')
  const element = `<protectedRanges>${body}</protectedRanges>`
  // Schema order: protectedRanges follows sheetProtection (or sheetCalcPr/
  // sheetData when absent) and precedes scenarios/autoFilter.
  const anchor =
    stripped.match(/<sheetProtection\b[^>]*\/?>/) ??
    stripped.match(/<sheetCalcPr\b[^>]*\/?>/) ??
    stripped.match(/<\/sheetData>|<sheetData\b[^>]*\/>/)
  if (!anchor || anchor.index === undefined) {
    throw new SheetProtectionError('Worksheet has no sheetData element.')
  }
  const at = anchor.index + anchor[0].length
  return stripped.slice(0, at) + element + stripped.slice(at)
}

// ─── Package-level wrappers (byte orchestration mirrors rules.ts) ───────────

async function worksheetPathFor(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
  sheetName: string,
): Promise<string> {
  const workbookXml = await source.readText('xl/workbook.xml')
  const element = parseSheetElements(workbookXml).find((entry) => entry.name === sheetName)
  if (!element?.relationshipId) {
    throw new SheetProtectionError(`Sheet "${sheetName}" was not found.`)
  }
  return resolveWorksheetPath(source, element.relationshipId)
}

/// Toggles one sheet's protection, addressed by sheet name.
export async function protectSheet(
  sourceBytes: Uint8Array,
  sheetName: string,
  protect: boolean,
): Promise<Uint8Array> {
  const source = await createBufferEntrySource(sourceBytes)
  const worksheetPath = await worksheetPathFor(source, sheetName)
  const xml = applySheetProtection(await source.readText(worksheetPath), protect)
  return (await assemblePackage(sourceBytes, {
    replaced: new Map([[worksheetPath, xml]]),
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: [worksheetPath],
  })).buffer
}

/// Toggles the workbook structure lock (workbook.xml).
export async function protectWorkbookStructure(
  sourceBytes: Uint8Array,
  lockStructure: boolean,
): Promise<Uint8Array> {
  const source = await createBufferEntrySource(sourceBytes)
  const xml = applyWorkbookProtection(await source.readText('xl/workbook.xml'), lockStructure)
  return (await assemblePackage(sourceBytes, {
    replaced: new Map([['xl/workbook.xml', xml]]),
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: ['xl/workbook.xml'],
  })).buffer
}
