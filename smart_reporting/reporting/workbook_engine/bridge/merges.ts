import {
  assemblePackage, createBufferEntrySource, formatAddress, parseRange, readWorkbook,
  readXmlAttribute, type RangeBounds,
} from '@sheets-web/xlsx-engine'
import { z } from 'zod'

const rangesSchema = z.array(z.string().max(40)).max(10000)
const overlaps = (a: RangeBounds, b: RangeBounds) =>
  a.startRow <= b.endRow && a.endRow >= b.startRow && a.startColumn <= b.endColumn && a.endColumn >= b.startColumn

/** Replace only merge layout; cell content continues through the existing cell-edit path. */
export async function applySheetMerges(bytes: Uint8Array, sheetName: string, input: unknown): Promise<Uint8Array> {
  const parsed = rangesSchema.safeParse(input)
  if (!parsed.success) throw new Error('workbook_merge_range_invalid')
  const ranges: RangeBounds[] = []
  for (const ref of parsed.data) {
    let range: RangeBounds
    try { range = parseRange(ref) }
    catch { throw new Error('workbook_merge_range_invalid') }
    if (range.endRow > 1048575 || range.endColumn > 16383 ||
        (range.startRow === range.endRow && range.startColumn === range.endColumn)) {
      throw new Error('workbook_merge_range_invalid')
    }
    if (ranges.some(existing => overlaps(range, existing))) throw new Error('workbook_merge_ranges_overlap')
    ranges.push(range)
  }
  const sheet = (await readWorkbook(bytes)).sheets.find(sheet => sheet.name === sheetName)
  if (!sheet) throw new Error('workbook_sheet_missing')
  const refs = ranges.map(range => `${formatAddress(range.startRow, range.startColumn)}:${formatAddress(range.endRow, range.endColumn)}`)
  if (JSON.stringify([...sheet.merges].sort()) === JSON.stringify([...refs].sort())) return bytes
  const source = await createBufferEntrySource(bytes)
  // Table and pivot outputs cannot contain merged cells. Resolve only this sheet's relationships.
  const relsPath = sheet.path.replace(/([^/]+)$/, '_rels/$1.rels')
  if (ranges.length && await source.has(relsPath)) {
    for (const match of (await source.readText(relsPath)).matchAll(/<Relationship\b[^>]*\/?\s*>/g)) {
      const type = readXmlAttribute(match[0], 'Type') ?? ''
      if (!/\/(?:table|pivotTable)$/.test(type)) continue
      const target = readXmlAttribute(match[0], 'Target')
      if (!target) continue
      const path = decodeURI(new URL(target, `https://workbook.invalid/${sheet.path}`).pathname).slice(1)
      const element = (await source.readText(path)).match(/<(?:table|location)\b[^>]*>/)?.[0]
      const ref = element && readXmlAttribute(element, 'ref')
      if (ref && ranges.some(range => overlaps(range, parseRange(ref)))) throw new Error('workbook_merge_table_conflict')
    }
  }
  let xml = (await source.readText(sheet.path))
    .replace(/<mergeCells\b[^>]*\/>|<mergeCells\b[^>]*>[\s\S]*?<\/mergeCells>/g, '')
  if (refs.length) {
    const merged = `<mergeCells count="${refs.length}">${refs.map(ref => `<mergeCell ref="${ref}"/>`).join('')}</mergeCells>`
    xml = xml.replace(/<(?:phoneticPr|conditionalFormatting|dataValidations|hyperlinks|printOptions|pageMargins|pageSetup|headerFooter|rowBreaks|colBreaks|customProperties|cellWatches|ignoredErrors|smartTags|drawing|legacyDrawing|legacyDrawingHF|picture|oleObjects|controls|webPublishItems|tableParts|extLst)\b|<\/worksheet>/,
      match => merged + match)
  }
  return (await assemblePackage(bytes, {
    replaced: new Map([[sheet.path, xml]]), added: new Map(), addedBinary: new Map(),
    removedEntries: [], addedEntries: [], touchedEntries: [sheet.path],
  })).buffer
}
