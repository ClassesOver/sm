/// Local adapter around the pinned GenOffice hyperlink writer (hyperlinks.ts):
/// reads a worksheet's cell hyperlinks, binds each edit to the target the cell
/// currently carries (expectedTarget), validates targets (http/https/mailto or an
/// in-workbook '#Sheet!A1' anchor), applies the pinned applyHyperlinkEdits and
/// reads the result back before returning the package.

import { formatAddress, parseAddress } from './cell-address'
import { applyHyperlinkEdits, ensureRelationshipNamespace, HyperlinkEditError, type HyperlinkEdit } from './hyperlinks'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { readXmlAttribute } from './xml'
import { assemblePackage, createBufferEntrySource, type EntrySource } from './zip'

const HYPERLINK_REL_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'
const MAX_ROW = 1048575
const MAX_COLUMN = 16383
/// Excel's URL length limit; the pinned normalizeLinkTarget uses the same bound.
export const HYPERLINK_TARGET_LIMIT = 2083
export const HYPERLINK_EDIT_LIMIT = 1000

export interface CellHyperlink {
  /// A1 reference of the hyperlink element (a single cell or a range)
  readonly ref: string
  /// '#Sheet!A1' for internal anchors, the external URL otherwise; null when unreadable
  readonly target: string | null
  /// set when this element cannot be edited safely (range ref, mixed r:id+location, unknown rel…)
  readonly readOnlyReason: string | null
}

export interface SheetHyperlinkEdit {
  /// single-cell A1 reference
  readonly ref: string
  /// the cell's current target in the input package (null = no link); mismatch rejects the batch
  readonly expectedTarget: string | null
  /// new target; null removes the link
  readonly target: string | null
}

function decodeAttribute(value: string): string {
  return value
    .replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&quot;', '"').replaceAll('&apos;', "'")
    .replace(/&#x([0-9a-f]+);/gi, (_match, hex: string) => String.fromCodePoint(Number.parseInt(hex, 16)))
    .replace(/&#([0-9]+);/g, (_match, decimal: string) => String.fromCodePoint(Number(decimal)))
    .replaceAll('&amp;', '&')
}

function relationshipTargets(relsXml: string | null): Map<string, { type: string; target: string; external: boolean }> {
  const result = new Map<string, { type: string; target: string; external: boolean }>()
  if (relsXml === null) return result
  for (const match of relsXml.matchAll(/<Relationship\b([^>]*?)\/?>/g)) {
    const attributes = match[1] ?? ''
    const id = readXmlAttribute(attributes, 'Id')
    if (!id) continue
    result.set(id, {
      type: readXmlAttribute(attributes, 'Type') ?? '',
      target: decodeAttribute(readXmlAttribute(attributes, 'Target') ?? ''),
      external: readXmlAttribute(attributes, 'TargetMode') === 'External',
    })
  }
  return result
}

/// Cell hyperlinks of one worksheet part, in document order.
export function readSheetHyperlinks(worksheetXml: string, relsXml: string | null): CellHyperlink[] {
  const rels = relationshipTargets(relsXml)
  const links: CellHyperlink[] = []
  const section = /<hyperlinks\b[^>]*>([\s\S]*?)<\/hyperlinks>/.exec(worksheetXml)?.[1] ?? ''
  for (const match of section.matchAll(/<hyperlink\b([^>]*?)\/?>/g)) {
    const attributes = match[1] ?? ''
    const ref = readXmlAttribute(attributes, 'ref') ?? ''
    const relId = readXmlAttribute(attributes, 'r:id')
    const location = readXmlAttribute(attributes, 'location')
    let target: string | null = null
    let reason: string | null = null
    if (!/^[A-Z]{1,3}[1-9][0-9]*$/.test(ref)) reason = '区域链接（覆盖多个单元格）暂不支持在此编辑'
    else if (relId && location) reason = '同时带外部地址与文档内位置的链接暂不支持在此编辑'
    else if (relId) {
      const rel = rels.get(relId)
      if (!rel || !rel.type.endsWith('/hyperlink') || !rel.external) reason = '链接关系无法核验，暂不支持在此编辑'
      else target = rel.target
    } else if (location) target = `#${decodeAttribute(location)}`
    else reason = '链接没有目标，暂不支持在此编辑'
    links.push({ ref, target, readOnlyReason: reason })
  }
  return links
}

function cellCovered(ref: string, row: number, column: number): boolean {
  const [start, end] = ref.split(':')
  try {
    const from = parseAddress(start!), to = parseAddress(end ?? start!)
    return row >= Math.min(from.row, to.row) && row <= Math.max(from.row, to.row) && column >= Math.min(from.column, to.column) && column <= Math.max(from.column, to.column)
  } catch { return false }
}

/// Unquoted or single-quoted sheet name (with '' escapes) followed by a single-cell address.
const INTERNAL_TARGET = /^#(?:'((?:[^']|'')+)'|([^'!\s][^!]*))!\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6})$/

export function validateHyperlinkTarget(target: string | null, sheetNames: readonly string[]): void {
  if (target === null) return
  if (typeof target !== 'string' || target.length === 0 || target.length > HYPERLINK_TARGET_LIMIT || /[\x00-\x1f\x7f]/.test(target)) {
    throw new HyperlinkEditError('链接地址无效：不能为空、不能含控制字符，且不超过 2083 字符。')
  }
  if (target.startsWith('#')) {
    const match = INTERNAL_TARGET.exec(target)
    const sheet = match ? (match[1] !== undefined ? match[1].replaceAll("''", "'") : match[2]!) : undefined
    if (!match || !sheetNames.some(name => name.toLowerCase() === sheet!.toLowerCase())) {
      throw new HyperlinkEditError('文档内链接须指向本工作簿中存在的工作表单元格，如 Sheet1!A1。')
    }
    const { row, column } = parseAddress(`${match[3]}${match[4]}`)
    if (row > MAX_ROW || column > MAX_COLUMN) throw new HyperlinkEditError('文档内链接的单元格超出工作表范围。')
    return
  }
  if (/\s/.test(target) || !/^(https?:\/\/[^/?#]+|mailto:[^@]+@[^@]+)/i.test(target)) {
    throw new HyperlinkEditError('外部链接只允许 http、https 或 mailto 地址。')
  }
}

async function worksheetParts(source: EntrySource, sheetName: string) {
  const workbookXml = await source.readText('xl/workbook.xml')
  const sheets = parseSheetElements(workbookXml)
  const element = sheets.find(entry => entry.name === sheetName)
  if (!element?.relationshipId) throw new HyperlinkEditError(`工作表 "${sheetName}" 不存在。`)
  const worksheetPath = await resolveWorksheetPath(source, element.relationshipId)
  const relsPath = worksheetPath.replace(/^(xl\/worksheets\/)([^/]+)$/, '$1_rels/$2.rels')
  const relsExisted = await source.has(relsPath)
  return {
    sheetNames: sheets.map(entry => entry.name),
    worksheetPath, relsPath, relsExisted,
    worksheetXml: await source.readText(worksheetPath),
    relsXml: relsExisted ? await source.readText(relsPath) : null,
  }
}

/// Hyperlinks of a sheet in a package (for the editor's dialog and identity binding).
export async function readPackageSheetHyperlinks(bytes: Uint8Array, sheetName: string): Promise<CellHyperlink[]> {
  const parts = await worksheetParts(await createBufferEntrySource(bytes), sheetName)
  return readSheetHyperlinks(parts.worksheetXml, parts.relsXml)
}

/// The target a single cell currently links to: null = no link; throws with the
/// read-only reason when the cell is covered by a link that cannot be edited.
export function cellHyperlinkState(links: readonly CellHyperlink[], row: number, column: number): string | null {
  const ref = formatAddress(row, column)
  for (const link of links) {
    if (link.ref === ref && link.readOnlyReason === null) return link.target
    if (cellCovered(link.ref, row, column)) throw new HyperlinkEditError(link.readOnlyReason ?? '此单元格的链接暂不支持在此编辑')
  }
  return null
}

export async function applySheetHyperlinks(sourceBytes: Uint8Array, sheetName: string, edits: readonly SheetHyperlinkEdit[]): Promise<Uint8Array> {
  if (!Array.isArray(edits) || edits.length === 0 || edits.length > HYPERLINK_EDIT_LIMIT) throw new HyperlinkEditError('链接修改须为 1–1000 项。')
  const source = await createBufferEntrySource(sourceBytes)
  const parts = await worksheetParts(source, sheetName)
  const links = readSheetHyperlinks(parts.worksheetXml, parts.relsXml)
  const seen = new Set<string>()
  const pinned: HyperlinkEdit[] = []
  for (const edit of edits) {
    if (!edit || typeof edit.ref !== 'string' || !/^[A-Z]{1,3}[1-9][0-9]{0,6}$/.test(edit.ref) || seen.has(edit.ref)) throw new HyperlinkEditError('链接修改的单元格无效或重复。')
    seen.add(edit.ref)
    const { row, column } = parseAddress(edit.ref)
    if (row > MAX_ROW || column > MAX_COLUMN) throw new HyperlinkEditError('链接修改的单元格超出工作表范围。')
    const current = cellHyperlinkState(links, row, column)
    if (current !== edit.expectedTarget) throw new HyperlinkEditError(`单元格 ${edit.ref} 的链接已变化，请刷新后重试。`)
    validateHyperlinkTarget(edit.target, parts.sheetNames)
    if (edit.target === current) throw new HyperlinkEditError(`单元格 ${edit.ref} 的链接没有变化。`)
    pinned.push({ row, column, target: edit.target })
  }
  const patch = applyHyperlinkEdits(parts.worksheetXml, parts.relsXml, pinned)
  const worksheetXml = ensureRelationshipNamespace(patch.worksheetXml)
  // Read back the final link set: every edited cell carries exactly its new target,
  // every untouched link is unchanged.
  const after = readSheetHyperlinks(worksheetXml, patch.relsXml)
  const expected = new Map(links.filter(link => !seen.has(link.ref)).map(link => [link.ref, link.target]))
  for (const edit of edits) if (edit.target !== null) expected.set(edit.ref, edit.target)
  if (after.length !== expected.size || after.some(link => link.readOnlyReason === null && expected.get(link.ref) !== link.target) || after.some(link => !expected.has(link.ref))) {
    throw new HyperlinkEditError('链接写入后回读不一致，已放弃修改。')
  }
  const replaced = new Map<string, string>([[parts.worksheetPath, worksheetXml]])
  const added = new Map<string, string>()
  if (patch.relsChanged && patch.relsXml !== null) (parts.relsExisted ? replaced : added).set(parts.relsPath, patch.relsXml)
  return (await assemblePackage(sourceBytes, {
    replaced, added, addedBinary: new Map(), removedEntries: [], addedEntries: [...added.keys()], touchedEntries: [...replaced.keys(), ...added.keys()],
  })).buffer
}

export { HYPERLINK_REL_TYPE }
