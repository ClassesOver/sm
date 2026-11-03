/// Workbook-level defined names (名称管理器 write path): adds / replaces /
/// removes `<definedName>` entries in workbook.xml. Sheet-scoped names
/// (_xlnm.Print_Area and friends) are maintained by page-setup/sheet-ops and
/// are deliberately out of scope here — this module only owns global names.

import { createBufferEntrySource } from './zip'
import { escapeXmlAttribute, escapeXmlText } from './xml'

export interface DefinedNameEntry {
  readonly name: string
  /// reference or formula text as stored, e.g. `Sheet1!$A$1:$B$10`
  readonly refersTo: string
}

export class DefinedNameError extends Error {}

const RESERVED_PREFIX = '_xlnm.'

/// Excel name rules: letter / underscore / backslash / CJK start; then
/// letters, digits, underscore, dot; not shaped like a cell reference
/// (A1 / $A$1 / R1C1); not the reserved _xlnm. prefix.
export function isValidDefinedName(name: string): boolean {
  if (name.length === 0 || name.length > 255) return false
  if (name.startsWith(RESERVED_PREFIX)) return false
  if (!/^[A-Za-z_\u00C0-\uFFFF\\]/.test(name)) return false
  if (!/^[A-Za-z0-9_.\u00C0-\uFFFF\\]+$/.test(name)) return false
  // collides with a cell reference (A1, $AA$10, R1C1-style)?
  if (/^\$?[A-Za-z]{1,3}\$?[0-9]{1,7}$/.test(name)) return false
  if (/^[Rr]([0-9]+)?[Cc]([0-9]+)?$/.test(name)) return false
  // Excel normalizes names case-insensitively for collision checks
  return true
}

const namePatternOf = (name: string): RegExp =>
  // global names only: a localSheetId attribute means page-setup owns it
  new RegExp(
    `<definedName\\b((?![^>]*localSheetId)[^>])*?\\bname="${escapeXmlAttribute(name).replace(/\./g, '\\.')}"[^>]*>[\\s\\S]*?</definedName>`,
  )

/// Read global defined names out of workbook.xml (sheet-scoped excluded).
export function readDefinedNames(workbookXml: string): DefinedNameEntry[] {
  const entries: DefinedNameEntry[] = []
  const section = workbookXml.match(/<definedNames\b[^>]*>([\s\S]*?)<\/definedNames>/)
  if (!section) return entries
  for (const match of (section[1] ?? '').matchAll(
    /<definedName\b([^>]*?)>([\s\S]*?)<\/definedName>/g,
  )) {
    const attributes = match[1] ?? ''
    if (/\blocalSheetId=/.test(attributes)) continue
    const name = attributes.match(/\bname="([^"]*)"/)?.[1]
    if (name === undefined) continue
    entries.push({ name, refersTo: (match[2] ?? '').trim() })
  }
  return entries
}

function setGlobalName(workbookXml: string, entry: DefinedNameEntry): string {
  const without = workbookXml.replace(namePatternOf(entry.name), '')
  const element =
    `<definedName name="${escapeXmlAttribute(entry.name)}">` +
    `${escapeXmlText(entry.refersTo)}</definedName>`
  return insertDefinedName(without, element)
}

function removeGlobalName(workbookXml: string, name: string): string {
  return dropEmptiedSection(workbookXml.replace(namePatternOf(name), ''))
}

function dropEmptiedSection(xml: string): string {
  return xml.replace(/<definedNames>\s*<\/definedNames>|<definedNames\s*\/>/, '')
}

function insertDefinedName(xml: string, element: string): string {
  // Google Sheets exports an empty self-closing <definedNames/>.
  const empty = xml.match(/<definedNames\b[^>]*\/>/)
  if (empty && empty.index !== undefined) {
    return (
      xml.slice(0, empty.index) +
      `<definedNames>${element}</definedNames>` +
      xml.slice(empty.index + empty[0].length)
    )
  }
  const section = xml.match(/<definedNames\b[^>]*>/)
  if (section && section.index !== undefined) {
    const at = section.index + section[0].length
    return xml.slice(0, at) + element + xml.slice(at)
  }
  // Schema order: definedNames follows sheets (and functionGroups /
  // externalReferences when present).
  const anchor =
    xml.match(/<externalReferences\b[^>]*>[\s\S]*?<\/externalReferences>|<externalReferences\b[^>]*\/>/) ??
    xml.match(/<functionGroups\b[^>]*>[\s\S]*?<\/functionGroups>|<functionGroups\b[^>]*\/>/) ??
    xml.match(/<\/sheets>|<sheets\b[^>]*\/>/)
  if (!anchor || anchor.index === undefined) {
    throw new DefinedNameError('workbook.xml has no sheets section.')
  }
  const at = anchor.index + anchor[0].length
  return `${xml.slice(0, at)}<definedNames>${element}</definedNames>${xml.slice(at)}`
}

export interface DefinedNamesPlan {
  /// add or replace (global scope)
  readonly sets?: readonly DefinedNameEntry[]
  /// remove by exact name (global scope)
  readonly removes?: readonly string[]
}

export async function applyDefinedNames(
  sourceBytes: Uint8Array,
  plan: DefinedNamesPlan,
): Promise<Uint8Array> {
  if ((plan.sets?.length ?? 0) + (plan.removes?.length ?? 0) === 0) return sourceBytes
  const seen = new Set<string>()
  for (const entry of plan.sets ?? []) {
    if (!isValidDefinedName(entry.name)) {
      throw new DefinedNameError(`名称 "${entry.name}" 不合法（字母或下划线开头、不能形如单元格地址、不能使用 _xlnm. 前缀）。`)
    }
    if (entry.refersTo.length === 0 || entry.refersTo.length > 500) {
      throw new DefinedNameError(`名称 "${entry.name}" 的引用不能为空或超过 500 字符。`)
    }
    const key = entry.name.toLowerCase()
    if (seen.has(key)) {
      throw new DefinedNameError(`名称 "${entry.name}" 在同一次操作中重复定义。`)
    }
    seen.add(key)
  }
  const removedLower = new Set((plan.removes ?? []).map((name) => name.toLowerCase()))
  for (const entry of plan.sets ?? []) {
    if (removedLower.has(entry.name.toLowerCase())) {
      throw new DefinedNameError(`名称 "${entry.name}" 同时出现在新增与删除列表中。`)
    }
  }
  for (const name of plan.removes ?? []) {
    if (!isValidDefinedName(name)) {
      throw new DefinedNameError(`名称 "${name}" 不合法。`)
    }
  }

  const source = await createBufferEntrySource(sourceBytes)
  let workbookXml = await source.readText('xl/workbook.xml')
  for (const name of plan.removes ?? []) workbookXml = removeGlobalName(workbookXml, name)
  for (const entry of plan.sets ?? []) workbookXml = setGlobalName(workbookXml, entry)
  workbookXml = dropEmptiedSection(workbookXml)

  const { assemblePackage } = await import('./zip')
  const mutation = await assemblePackage(sourceBytes, {
    replaced: new Map([['xl/workbook.xml', workbookXml]]),
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: ['xl/workbook.xml'],
  })
  return mutation.buffer
}
