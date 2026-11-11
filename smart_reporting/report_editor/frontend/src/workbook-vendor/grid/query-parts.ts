// GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c, Apache-2.0.
// Extracted relationship helpers from xlsx-sheets.ts / xlsx-drawing-add.ts.
import { decodeXmlText as decodeAttribute, readXmlAttribute as readAttribute } from '@sheets-web/xlsx-engine/xml'

export interface ParsedRelationship {
  readonly id: string | undefined
  readonly type: string
  readonly target: string
  readonly external: boolean
}

export function parseRelationships(relsXml: string): ParsedRelationship[] {
  const entries: ParsedRelationship[] = []
  for (const match of relsXml.matchAll(/<Relationship\b[^>]*?\/>/g)) {
    const element = match[0]
    const type = readAttribute(element, 'Type')
    const target = readAttribute(element, 'Target')
    if (type === undefined || target === undefined) continue
    entries.push({
      id: readAttribute(element, 'Id'),
      type: decodeAttribute(type),
      target: decodeAttribute(target),
      external: readAttribute(element, 'TargetMode') === 'External',
    })
  }
  return entries
}


export function tableDisplayName(tableXml: string): string | undefined {
  const openTag = /<table\b[^>]*>/.exec(tableXml)?.[0]
  if (!openTag) return undefined
  const name = readAttribute(openTag, 'displayName') ?? readAttribute(openTag, 'name')
  return name === undefined ? undefined : decodeAttribute(name)
}


export function relsPathFor(partPath: string): string {
  const slash = partPath.lastIndexOf('/')
  return `${partPath.slice(0, slash)}/_rels/${partPath.slice(slash + 1)}.rels`
}


export function resolveRelTarget(fromPart: string, target: string): string {
  const trimmed = target.trim()
  const withoutFragment = trimmed.split('#', 1)[0] ?? ''
  if (withoutFragment.length === 0) throw new Error('Invalid OPC relationship target.')
  let decoded: string
  try {
    decoded = decodeURIComponent(withoutFragment)
  } catch {
    throw new Error('Invalid OPC relationship target.')
  }
  if (
    decoded.length === 0 ||
    decoded.includes('\0') ||
    decoded.startsWith('//') ||
    decoded.startsWith('\\') ||
    /^[A-Za-z][A-Za-z0-9+.-]*:/.test(decoded)
  ) {
    throw new Error('Invalid OPC relationship target.')
  }
  const base = decoded.startsWith('/')
    ? []
    : fromPart
        .replaceAll('\\', '/')
        .split('/')
        .slice(0, -1)
        .filter((segment) => segment !== '' && segment !== '.')
  for (const segment of decoded.replaceAll('\\', '/').split('/')) {
    if (segment === '' || segment === '.') continue
    if (segment === '..') {
      if (base.pop() === undefined) throw new Error('Invalid OPC relationship target.')
      continue
    }
    base.push(segment)
  }
  const resolved = base.join('/')
  if (resolved.length === 0) throw new Error('Invalid OPC relationship target.')
  return resolved
}


