/** Shared explicit-cell format projection for pivot dimension identities. */
import * as numfmt from 'numfmt'
import { formatAddress } from './cell-address'
import { readXmlAttribute } from './xml'
import { formatCodeFor, parseStylesheet } from './style-read'
import type { EntrySource } from './zip'
import type { SourceValue } from './pivot-source'
import type { PivotLayoutSpec } from './pivot-layout'

type ProjectionSpec = Pick<PivotLayoutSpec, 'values' | 'groupings'> & { dimensionFormatProjection?: boolean | undefined }

export function pivotSourceColumnValues(
  values: readonly SourceValue[], patterns: readonly string[], field: string,
  spec: ProjectionSpec, date1904: boolean,
): SourceValue[] {
  // Grouping and calculated expressions require raw numeric inputs. Preserve
  // those existing paths until calculation dependencies have separate identities.
  if (spec.dimensionFormatProjection === false || spec.values.some(value => value.formula !== undefined || value.field === field)
    || spec.groupings?.some(rule => rule.field === field)) return [...values]
  const calendar = new Map<string, boolean>()
  return values.map((value, index) => {
    const pattern = patterns[index] ?? ''
    if (typeof value !== 'number' || !pattern || pattern === 'General') return value
    try {
      let shift = 0
      if (date1904) {
        let isDate = calendar.get(pattern)
        if (isDate === undefined) {
          const type = numfmt.getFormatInfo(pattern.replace(/\[\$\]/g, '')).type
          isDate = type === 'date' || type === 'datetime'
          calendar.set(pattern, isDate)
        }
        if (isDate) shift = 1462
      }
      return numfmt.format(pattern, value + shift, { nbsp: true, throws: false })
    } catch { return value }
  })
}

export function projectPivotSourceGrid(
  grid: readonly (readonly SourceValue[])[], patterns: readonly (readonly string[])[],
  spec: ProjectionSpec, date1904: boolean,
): SourceValue[][] {
  const result = grid.map(row => [...row])
  for (let column = 0; column < (grid[0]?.length ?? 0); column++) {
    const values = pivotSourceColumnValues(grid.slice(1).map(row => row[column] ?? null),
      patterns.slice(1).map(row => row[column] ?? ''), String(grid[0]?.[column] ?? '').trim(), spec, date1904)
    values.forEach((value, index) => { result[index + 1]![column] = value })
  }
  return result
}

/** Cell XF overrides a custom row XF, then column XF, then workbook default. */
export async function readPivotSourcePatterns(source: EntrySource, xml: string,
  area: {startRow: number;endRow: number;startColumn: number;endColumn: number}): Promise<string[][]> {
  const styles = parseStylesheet(await source.has('xl/styles.xml') ? await source.readText('xl/styles.xml') : '')
  const code = (index: number) => { const xf = styles.cellXfs[index]; return xf ? formatCodeFor(styles, xf) : 'General' }
  const columns = new Map<number, string>(), rows = new Map<number, string>()
  for (const match of xml.matchAll(/<col\b[^>]*>/g)) {
    const style = readXmlAttribute(match[0], 'style')
    if (style === undefined) continue
    const start = Math.max(area.startColumn, Number(readXmlAttribute(match[0], 'min')) - 1)
    const end = Math.min(area.endColumn, Number(readXmlAttribute(match[0], 'max')) - 1)
    for (let column = start; column <= end; column++) columns.set(column, code(Number(style)))
  }
  for (const match of xml.matchAll(/<row\b[^>]*>/g)) {
    const row = Number(readXmlAttribute(match[0], 'r')) - 1, style = readXmlAttribute(match[0], 's')
    if (row >= area.startRow && row <= area.endRow && style !== undefined
      && ['1', 'true'].includes(readXmlAttribute(match[0], 'customFormat') ?? '')) rows.set(row, code(Number(style)))
  }
  const formats = new Map<string, string>()
  for (const match of xml.matchAll(/<c\b[^>]*>/g)) {
    const address = readXmlAttribute(match[0], 'r'), style = readXmlAttribute(match[0], 's')
    if (address && style !== undefined) formats.set(address, code(Number(style)))
  }
  return Array.from({length: area.endRow-area.startRow+1}, (_, row) =>
    Array.from({length: area.endColumn-area.startColumn+1}, (_, column) =>
      formats.get(formatAddress(area.startRow+row, area.startColumn+column))
        ?? rows.get(area.startRow+row) ?? columns.get(area.startColumn+column) ?? code(0)))
}
