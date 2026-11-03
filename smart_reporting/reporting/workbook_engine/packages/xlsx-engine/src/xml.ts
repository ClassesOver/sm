/// Shared XML text helpers for the OOXML patch pipeline.
/// Convention: str.match / str.matchAll / regex.test only — never
/// RegExp.prototype.exec (see cell-address.ts).

import { decodeXlsxEscapes, encodeXlsxEscapes } from './xlsx-escapes'

const XML_NAMED_ENTITIES: Record<string, string> = {
  quot: '"',
  apos: "'",
  lt: '<',
  gt: '>',
  amp: '&',
}

/// Single-pass decode of the XML named entities plus numeric character
/// references (&#dd; / &#xhh;), which some producers use for non-ASCII text.
export function decodeXmlText(input: string): string {
  return input.replace(
    /&(?:#x([0-9A-Fa-f]+)|#([0-9]+)|(quot|apos|lt|gt|amp));/g,
    (match, hex: string | undefined, dec: string | undefined, named: string | undefined) => {
      if (named !== undefined) return XML_NAMED_ENTITIES[named] ?? match
      const code = hex !== undefined ? Number.parseInt(hex, 16) : Number(dec)
      return code <= 0x10ffff ? String.fromCodePoint(code) : match
    },
  )
}

export function escapeXmlText(input: string): string {
  return input.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

export function escapeCellText(input: string): string {
  return escapeXmlText(encodeXlsxEscapes(input))
}

/// Mirrors the desktop reader: raw CRLF folds first so `_x000D_` + LF (Excel's
/// CR LF) ends up as one line break.
export function decodeCellText(input: string): string {
  const text = decodeXmlText(input).replace(/\r\n?/g, '\n')
  return decodeXlsxEscapes(text).replace(/\r\n?/g, '\n')
}

export function escapeXmlAttribute(input: string): string {
  return escapeXmlText(input).replaceAll('"', '&quot;').replaceAll("'", '&apos;')
}

export function escapeRegExp(input: string): string {
  return input.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function readXmlAttribute(attributes: string, name: string): string | undefined {
  return attributes.match(new RegExp(`(?:^|\\s)${escapeRegExp(name)}="([^"]*)"`))?.[1]
}

/** like readXmlAttribute, but never matches a namespace-prefixed name */
export function readCoreAttribute(element: string, name: string): string | undefined {
  return element.match(new RegExp(`(?<![\\w:.-])${name}="([^"]*)"`))?.[1]
}

/// Section inner content; '' for a self-closing section, null when absent.
export function sectionInner(xml: string, tag: string): string | null {
  if (new RegExp(`<${tag}\\b[^>]*/>`).test(xml)) return ''
  return xml.match(new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)</${tag}>`))?.[1] ?? null
}

export function extractElements(inner: string, tag: string): string[] {
  return [
    ...inner.matchAll(new RegExp(`<${tag}\\b[^>]*/>|<${tag}\\b[^>]*>[\\s\\S]*?</${tag}>`, 'g')),
  ].map((match) => match[0])
}

/// OpenXML SDK-family producers bind the spreadsheetml namespace to a prefix
/// (<x:workbook><x:sheets>...), invisible to the text-based patch pipeline's
/// unprefixed element patterns. Parts are normalized at read time instead:
/// the prefix is stripped and re-declared as the default namespace. Only
/// parts the planner rewrites reach the file, so untouched entries keep
/// their bytes; anything ambiguous returns the input unchanged (the save
/// then fails exactly as it did before this pass existed).

const NORMALIZABLE_NAMESPACES = new Set([
  'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
  'http://schemas.openxmlformats.org/package/2006/relationships',
  'http://schemas.openxmlformats.org/package/2006/content-types',
])

const SPREADSHEETML_NAMESPACE = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const OFFICE_RELATIONSHIPS_NAMESPACE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

/// Root start tag; the quote alternation keeps '>' inside attribute values
/// (legal in XML) from ending the match early.
const ROOT_START_TAG = /<(?![?!])(?:[^>"']|"[^"]*"|'[^']*')*?\/?>/

/// Elements the pipeline appends carry r:-prefixed attributes; some
/// producers bind r on individual elements only, so the host root gets the
/// conventional binding before such an element is inserted.
export function ensureRelationshipNamespace(partXml: string): string {
  const root = partXml.match(ROOT_START_TAG)?.[0]
  if (!root || /\bxmlns:r\s*=/.test(root)) return partXml
  const bound = root.replace(/^<([^\s/>]+)/, `<$1 xmlns:r="${OFFICE_RELATIONSHIPS_NAMESPACE}"`)
  // function replacer: a "$" inside the root tag's attribute values must not
  // be read as a String.replace pattern
  return partXml.replace(root, () => bound)
}

export function normalizeOoxmlPartPrefix(xml: string): string {
  const root = xml.match(/<(?![?!])([^\s/>]+)((?:[^>"']|"[^"]*"|'[^']*')*?)\/?>/)
  const rootName = root?.[1]
  if (!rootName) return xml
  const colon = rootName.indexOf(':')
  if (colon <= 0) return xml
  const prefix = rootName.slice(0, colon)
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(prefix)) return xml

  const rootTag = root[0]
  const declarationPattern = new RegExp(`xmlns:${prefix}\\s*=\\s*"([^"]*)"`)
  const declaration = rootTag.match(declarationPattern)
  const uri = declaration?.[1]
  if (declaration === null || uri === undefined || !NORMALIZABLE_NAMESPACES.has(uri)) return xml

  // Sections where plain text substitution could corrupt content.
  if (xml.includes('<![CDATA[') || xml.includes('<!--')) return xml
  // An existing default binding would capture the de-prefixed elements.
  if (/\sxmlns\s*=\s*["']/.test(xml)) return xml
  // The prefix rebound to another namespace deeper in the tree.
  for (const other of xml.matchAll(new RegExp(`\\sxmlns:${prefix}\\s*=\\s*"([^"]*)"`, 'g'))) {
    if (other[1] !== uri) return xml
  }

  const stripped = xml.replaceAll(`<${prefix}:`, '<').replaceAll(`</${prefix}:`, '</')
  // Attributes may still use the prefix; keep its binding alongside then.
  const bindings = new RegExp(`\\s${prefix}:`).test(stripped)
    ? `xmlns="${uri}" ${declaration[0]}`
    : `xmlns="${uri}"`
  let result = stripped.replace(declaration[0], bindings)

  // The pipeline appends elements carrying r:-prefixed attributes (new
  // <sheet r:id=...>); these producers bind r per element, not on the root,
  // so a root-level binding keeps such additions well-formed.
  if (
    uri === SPREADSHEETML_NAMESPACE &&
    !new RegExp(`xmlns:r\\s*=\\s*"`).test(ROOT_START_TAG.test(result) ? result : '') &&
    [...result.matchAll(/\sxmlns:r\s*=\s*"([^"]*)"/g)].every(
      (other) => other[1] === OFFICE_RELATIONSHIPS_NAMESPACE,
    )
  ) {
    result = result.replace(
      `xmlns="${uri}"`,
      `xmlns="${uri}" xmlns:r="${OFFICE_RELATIONSHIPS_NAMESPACE}"`,
    )
  }
  return result
}
