/// Internal shared helpers for reading pivot source areas out of worksheet
/// XML (used by both pivot-add and pivot-refresh). Not part of the public
/// engine API.

import { columnLabel } from './cell-address'
import { createBufferEntrySource, type EntrySource } from './zip'
import { decodeCellText } from './xml'

/// Reject declarations before any pivot XML parsing (including relationship
/// reads delegated to the shared workbook helpers).
export async function createPivotEntrySource(bytes: Uint8Array): Promise<EntrySource> {
  const entries = await createBufferEntrySource(bytes)
  return {
    ...entries,
    readText: async (path) => {
      const xml = await entries.readText(path)
      assertSafePivotXml(xml)
      return xml
    },
  }
}

export function assertSafePivotXml(xml: string): void {
  if (/<!\s*(?:DOCTYPE|ENTITY)\b/i.test(xml)) {
    throw new Error('Unsupported DOCTYPE or ENTITY declaration in pivot XML.')
  }
}

export async function assertSafePivotPackage(bytes: Uint8Array): Promise<void> {
  const source = await createPivotEntrySource(bytes)
  for (const path of await source.paths()) {
    if (/\.(?:xml|rels)$/i.test(path)) await source.readText(path)
  }
}

/// One raw source row: value per cacheField, in fieldNames order.
export type SourceValue = string | number | null

export function decodeEntities(input: string): string {
  return input
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&')
}

export async function readSharedStrings(source: EntrySource): Promise<readonly string[]> {
  if (!(await source.has('xl/sharedStrings.xml'))) return []
  const xml = await source.readText('xl/sharedStrings.xml')
  return [...xml.matchAll(/<si(?:\s[^>]*)?>([\s\S]*?)<\/si>/g)].map((m) =>
    [...(m[1] ?? '').matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)]
      .map((tm) => decodeCellText(tm[1] ?? ''))
      .join(''),
  )
}

export function extractCellValue(
  worksheetXml: string,
  address: string,
  sharedStrings: readonly string[],
): SourceValue {
  const match = worksheetXml.match(
    new RegExp(`<c\\b([^>]*)\\br="${address}"([^>]*)(?:/>|>([\\s\\S]*?)</c>)`),
  )
  if (!match) return null
  const attributes = `${match[1] ?? ''}${match[2] ?? ''}`
  const body = match[3] ?? ''
  const type = attributes.match(/\bt="([^"]+)"/)?.[1]
  if (type === 'inlineStr') {
    return [...body.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)]
      .map((textMatch) => decodeCellText(textMatch[1] ?? ''))
      .join('')
  }
  const rawValue = body.match(/<v(?:\s[^>]*)?>([\s\S]*?)<\/v>/)?.[1]
  if (rawValue === undefined) return null
  if (type === 's') return sharedStrings[Number(rawValue)] ?? null
  if (type === 'str') return decodeCellText(rawValue)
  if (type === 'b') return rawValue === '1' ? 1 : 0
  const n = Number(rawValue)
  return Number.isFinite(n) ? n : decodeCellText(rawValue)
}

/// Reads a rectangular source area (inclusive 0-based bounds), including its
/// header row. The first row is therefore suitable for buildPivotLayout.
export async function readSourceAreaGrid(
  source: EntrySource,
  worksheetXml: string,
  startRow: number,
  endRow: number,
  startColumn: number,
  endColumn: number,
): Promise<SourceValue[][]> {
  const sharedStrings = await readSharedStrings(source)
  const rows: SourceValue[][] = []
  for (let r = startRow; r <= endRow; r += 1) {
    const row: SourceValue[] = []
    for (let c = startColumn; c <= endColumn; c += 1) {
      row.push(extractCellValue(worksheetXml, `${columnLabel(c)}${r + 1}`, sharedStrings))
    }
    rows.push(row)
  }
  return rows
}

/// Reads a rectangular source area (inclusive 0-based bounds) as data rows,
/// omitting the header row.
export async function readSourceAreaRows(
  source: EntrySource,
  worksheetXml: string,
  startRow: number,
  endRow: number,
  startColumn: number,
  endColumn: number,
): Promise<SourceValue[][]> {
  const grid = await readSourceAreaGrid(
    source,
    worksheetXml,
    startRow,
    endRow,
    startColumn,
    endColumn,
  )
  return grid.slice(1)
}

export function escapeXmlAttribute(input: string): string {
  return input
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;')
}
