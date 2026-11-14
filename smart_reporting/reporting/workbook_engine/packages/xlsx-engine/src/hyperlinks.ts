/// Surgical hyperlink editing for a worksheet part and its .rels sibling.
/// External targets live as TargetMode="External" relationships referenced by
/// r:id; internal anchors use the `location` attribute and need no rel.

// Ported from pinned GenOffice packages/xlsx-gateway/src/gateway/xlsx-hyperlinks.ts
// (f8c17004, SHA-256 8dc34f16…ae452). Local adaptation: the two helpers below come
// from this engine's xml.ts and a verbatim copy of xlsx-sheets.ts relationship-id
// allocation. Local safety fix: attribute matching accepts either quote style
// so shared relationships survive edits and single-quoted links can be removed.
import { escapeRegExp } from './xml'

export { ensureRelationshipNamespace } from './xml'

// Verbatim from pinned xlsx-sheets.ts (RELATIONSHIP_ID / relationshipIds /
// firstFreeRelationshipId / nextFreeRelationshipId).
const RELATIONSHIP_ID = /\bId\s*=\s*(["'])rId(\d+)\1/g

function relationshipIds(relationshipsXml: string): Set<string> {
  return new Set([...relationshipsXml.matchAll(RELATIONSHIP_ID)].map((match) => `rId${match[2]}`))
}

function firstFreeRelationshipId(used: ReadonlySet<string>): string {
  let index = 1
  while (used.has(`rId${index}`)) index += 1
  return `rId${index}`
}

export function nextFreeRelationshipId(relationshipsXml: string): string {
  return firstFreeRelationshipId(relationshipIds(relationshipsXml))
}

export class HyperlinkEditError extends Error {}

export interface HyperlinkEdit {
  readonly row: number
  readonly column: number
  /// '#Sheet!A1' = internal anchor (leading '#' stripped into `location`);
  /// anything else = external URL; null removes the link.
  readonly target: string | null
}

export interface HyperlinkPatch {
  readonly worksheetXml: string
  /// null when the sheet had no rels file and still needs none.
  readonly relsXml: string | null
  readonly relsChanged: boolean
}

const HYPERLINK_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'
const EMPTY_RELS =
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
  '</Relationships>'

export function applyHyperlinkEdits(
  worksheetXml: string,
  relsXml: string | null,
  edits: readonly HyperlinkEdit[],
): HyperlinkPatch {
  let xml = worksheetXml
  let rels = relsXml
  let relsChanged = false

  const relIdsInUse = (): Set<string> => {
    const used = new Set<string>()
    for (const element of xml.matchAll(/<hyperlink\b[^>]*?\br:id\s*=\s*(["'])(.*?)\1/g)) {
      if (element[2]) used.add(element[2])
    }
    return used
  }
  const dropUnusedRel = (relId: string): void => {
    if (rels === null || relIdsInUse().has(relId)) return
    // Quote-agnostic like the id scan in xlsx-sheets.ts: a single-quoted
    // r:id is document-controlled; unescaped it could match every relationship.
    const next = rels.replace(
      new RegExp(`<Relationship\\b[^>]*\\bId=["']${escapeRegExp(relId)}["'][^>]*/>`),
      '',
    )
    if (next !== rels) {
      rels = next
      relsChanged = true
    }
  }
  const allocateRel = (target: string): string => {
    if (rels === null) {
      rels = EMPTY_RELS
      relsChanged = true
    }
    const relId = nextFreeRelationshipId(rels)
    const element =
      `<Relationship Id="${relId}" Type="${HYPERLINK_REL_TYPE}" ` +
      `Target="${escapeXmlAttribute(target)}" TargetMode="External"/>`
    const close = rels.replace('</Relationships>', () => `${element}</Relationships>`)
    if (close !== rels) {
      rels = close
    } else {
      const emptyRoot = /<Relationships\b([^>]*)\/>/.exec(rels)
      if (emptyRoot) {
        rels = rels.replace(
          emptyRoot[0],
          `<Relationships${emptyRoot[1]}>${element}</Relationships>`,
        )
      }
    }
    relsChanged = true
    return relId
  }

  for (const edit of edits) {
    const ref = toA1(edit.row, edit.column)
    const existingPattern = new RegExp(`<hyperlink\\b[^>]*?\\bref\\s*=\\s*(["'])${ref}\\1[^>]*/>`)
    const existing = existingPattern.exec(xml)?.[0]
    const existingRelId =
      existing === undefined ? undefined : /\br:id\s*=\s*(["'])(.*?)\1/.exec(existing)?.[2]
    if (existing !== undefined) {
      xml = xml.replace(existingPattern, '')
    }
    if (existingRelId !== undefined) dropUnusedRel(existingRelId)
    if (edit.target === null) continue

    const element = edit.target.startsWith('#')
      ? `<hyperlink ref="${ref}" location="${escapeXmlAttribute(edit.target.slice(1))}"/>`
      : `<hyperlink ref="${ref}" r:id="${allocateRel(edit.target)}"/>`
    xml = insertHyperlinkElement(xml, element)
  }

  // An emptied section must go — Excel repairs `<hyperlinks/>` with no children.
  xml = xml.replace(/<hyperlinks>\s*<\/hyperlinks>/, '')
  return { worksheetXml: xml, relsXml: rels, relsChanged }
}

function insertHyperlinkElement(xml: string, element: string): string {
  if (xml.includes('</hyperlinks>')) {
    return xml.replace('</hyperlinks>', () => `${element}</hyperlinks>`)
  }
  const section = `<hyperlinks>${element}</hyperlinks>`
  // Schema order: hyperlinks follows dataValidations / conditionalFormatting /
  // mergeCells / sheetData and precedes print-related elements and drawings.
  const anchor =
    /<printOptions\b|<pageMargins\b|<pageSetup\b|<headerFooter\b|<rowBreaks\b|<colBreaks\b|<drawing\b|<legacyDrawing\b|<picture\b|<oleObjects\b|<tableParts\b|<extLst\b/.exec(
      xml,
    )
  if (anchor) {
    return xml.slice(0, anchor.index) + section + xml.slice(anchor.index)
  }
  const end = xml.lastIndexOf('</worksheet>')
  if (end === -1) throw new HyperlinkEditError('Worksheet has no closing element.')
  return xml.slice(0, end) + section + xml.slice(end)
}

function toA1(row: number, column: number): string {
  let letters = ''
  let remaining = column + 1
  while (remaining > 0) {
    remaining -= 1
    letters = String.fromCharCode(65 + (remaining % 26)) + letters
    remaining = Math.floor(remaining / 26)
  }
  return `${letters}${row + 1}`
}

function escapeXmlAttribute(input: string): string {
  return input
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}
