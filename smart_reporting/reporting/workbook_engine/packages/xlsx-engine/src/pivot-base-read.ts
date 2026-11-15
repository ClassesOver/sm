import { showDataAsNeedsBaseField, showDataAsNeedsBaseItem, type PivotShowDataAs } from './pivot-value-modes'
import { decodeCellText, readXmlAttribute, extractElements, sectionInner } from './xml'

export interface PivotBaseRead {
  base: { baseField?: string; baseItem?: string }
  unsupported: boolean
}
const indexOf = (raw: string | undefined): number | undefined => {
  if (raw === undefined || raw.trim() === '') return undefined
  const index = Number(raw)
  return Number.isSafeInteger(index) && index >= 0 ? index : undefined
}

function cachedLabels(cacheField: string): (string | undefined)[] {
  const shared = sectionInner(cacheField, 'sharedItems') ?? ''
  return [...shared.matchAll(/<(s|n|b|m|d|e)\b([^>]*?)(?:\/>|>[\s\S]*?<\/\1>)/g)].map(entry => {
    const raw = readXmlAttribute(entry[2] ?? '', 'v')
    if (entry[1] === 'm') return ''
    if (entry[1] === 's' && raw !== undefined) return decodeCellText(raw)
    if (entry[1] === 'n' && raw !== undefined && raw.trim() !== '' && Number.isFinite(Number(raw))) return String(Number(raw))
    if (entry[1] === 'b' && ['0','1','true','false'].includes(raw ?? '')) return String(raw === '1' || raw === 'true')
    return undefined
  })
}

/// Display order is significant for running totals. Undefined means the host
/// cannot preserve it safely (rather than inventing source-first order).
export function readPivotMemberOrder(cacheField: string, pivotField: string): string[] | undefined {
  const items = extractElements(sectionInner(pivotField, 'items') ?? '', 'item')
  if (items.length === 0) return undefined
  const shared = cachedLabels(cacheField), labels: string[] = [], seen = new Set<string>()
  for (const item of items) {
    const type = readXmlAttribute(item, 't')
    if (type === 'default') continue
    if (type !== undefined && type !== 'data') return undefined
    const index = indexOf(readXmlAttribute(item, 'x')), label = index === undefined ? undefined : shared[index]
    if (label === undefined || seen.has(label)) return undefined
    seen.add(label)
    labels.push(label)
  }
  return labels
}

/// A foreign baseItem indexes pivotField.items, whose x indexes cache shared
/// items. Preserve that indirection (the two orders can differ).
export function readPivotValueBase(source: {
  valueXml: string; mode: string | undefined; fieldNames: readonly string[]
  rows: readonly number[]; columns: readonly number[]
  cacheFields: readonly string[]; pivotFields: readonly string[]
}): PivotBaseRead {
  const mode = source.mode as PivotShowDataAs | undefined
  if (!showDataAsNeedsBaseField(mode)) return { base: {}, unsupported: false }
  const field = indexOf(readXmlAttribute(source.valueXml.match(/^<[^>]+>/)?.[0] ?? '', 'baseField'))
  if (field === undefined || !source.fieldNames[field] || ![...source.rows, ...source.columns].includes(field)) return { base: {}, unsupported: true }
  const base: PivotBaseRead['base'] = { baseField: source.fieldNames[field] }
  if (!showDataAsNeedsBaseItem(mode)) return { base, unsupported: false }
  const item = indexOf(readXmlAttribute(source.valueXml.match(/^<[^>]+>/)?.[0] ?? '', 'baseItem'))
  const items = extractElements(sectionInner(source.pivotFields[field] ?? '', 'items') ?? '', 'item')
  // Includes Excel's previous/next sentinel indexes: they cannot be resolved
  // against this explicit member list and must not become a literal item.
  if (item === undefined || !items[item]) return { base, unsupported: true }
  const cacheIndex = indexOf(readXmlAttribute(items[item]!, 'x'))
  const label = cacheIndex === undefined ? undefined : cachedLabels(source.cacheFields[field] ?? '')[cacheIndex]
  // Date/error/shared-item extensions need a typed source projection first.
  if (label === undefined) return { base, unsupported: true }
  return { base: { ...base, baseItem: label }, unsupported: false }
}
