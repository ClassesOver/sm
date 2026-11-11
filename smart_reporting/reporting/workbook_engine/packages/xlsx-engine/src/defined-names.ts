/// 用户定义名称按工作簿/工作表作用域读写；_xlnm. 保留名称仍由页面设置维护。

import { createBufferEntrySource } from './zip'
import { decodeXmlText, readXmlAttribute, escapeXmlAttribute, escapeXmlText } from './xml'

export interface DefinedNameEntry {
  readonly name: string
  /// reference or formula text as stored, e.g. `Sheet1!$A$1:$B$10`
  readonly refersTo: string
  /// 稳定工作表名称；落盘时解析为当前标签顺序中的 localSheetId。
  readonly scopeSheetName?: string | undefined
}

export class DefinedNameError extends Error {}

const RESERVED_PREFIX = '_xlnm.'

/// Excel name rules: letter / underscore / backslash / CJK start; then
/// letters, digits, underscore, dot; not shaped like a cell reference
/// (A1 / $A$1 / R1C1); not the reserved _xlnm. prefix.
export function isValidDefinedName(name: string): boolean {
  if (name.length === 0 || name.length > 255) return false
  if (name.toLowerCase().startsWith(RESERVED_PREFIX)) return false
  if (!/^[A-Za-z_\u00C0-\uFFFF\\]/.test(name)) return false
  if (!/^[A-Za-z0-9_.\u00C0-\uFFFF\\]+$/.test(name)) return false
  // collides with a cell reference (A1, $AA$10, R1C1-style)?
  if (/^\$?[A-Za-z]{1,3}\$?[0-9]{1,7}$/.test(name)) return false
  if (/^[Rr]([0-9]+)?[Cc]([0-9]+)?$/.test(name)) return false
  // Excel normalizes names case-insensitively for collision checks
  return true
}

const sheetNames = (xml: string): string[] => [...(xml.match(/<sheets\b[^>]*>([\s\S]*?)<\/sheets>/)?.[1] ?? '').matchAll(/<sheet\b[^>]*>/g)]
  .map(match => decodeXmlText(readXmlAttribute(match[0], 'name') ?? ''))
const entryKey = (entry: { name: string; scopeSheetName?: string | undefined }) => JSON.stringify([entry.scopeSheetName ?? null, entry.name.toLowerCase()])

export function readDefinedNames(workbookXml: string): DefinedNameEntry[] {
  const sheets = sheetNames(workbookXml), entries: DefinedNameEntry[] = []
  const section = workbookXml.match(/<definedNames\b[^>]*>([\s\S]*?)<\/definedNames>/)?.[1] ?? ''
  for (const match of section.matchAll(/<definedName\b[^>]*>([\s\S]*?)<\/definedName>/g)) {
    const name = readXmlAttribute(match[0], 'name'), local = readXmlAttribute(match[0], 'localSheetId')
    if (name === undefined || decodeXmlText(name).toLowerCase().startsWith('_xlnm.')) continue
    const scopeSheetName = local === undefined ? undefined : /^\d+$/.test(local) ? sheets[Number(local)] : undefined
    if (local !== undefined && scopeSheetName === undefined) continue
    entries.push({ name: decodeXmlText(name), refersTo: decodeXmlText(match[1] ?? '').trim(), ...(scopeSheetName !== undefined ? { scopeSheetName } : {}) })
  }
  return entries
}

function removeName(xml: string, entry: { name: string; scopeSheetName?: string | undefined }): string {
  const sheets = sheetNames(xml)
  return xml.replace(/<definedName\b[^>]*>[\s\S]*?<\/definedName>/g, full => {
    const name = decodeXmlText(readXmlAttribute(full, 'name') ?? ''), local = readXmlAttribute(full, 'localSheetId')
    const scope = local === undefined ? undefined : /^\d+$/.test(local) ? sheets[Number(local)] : undefined
    if (local !== undefined && scope === undefined) return full
    return name.toLowerCase() === entry.name.toLowerCase() && scope === entry.scopeSheetName ? '' : full
  })
}

function setName(xml: string, entry: DefinedNameEntry): string {
  const index = entry.scopeSheetName === undefined ? -1 : sheetNames(xml).indexOf(entry.scopeSheetName)
  if (entry.scopeSheetName !== undefined && index < 0) throw new DefinedNameError('名称的工作表作用域不存在。')
  const scope = index < 0 ? '' : ` localSheetId="${index}"`
  return insertDefinedName(removeName(xml, entry), `<definedName name="${escapeXmlAttribute(entry.name)}"${scope}>${escapeXmlText(entry.refersTo)}</definedName>`)
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
  /// add or replace in the specified scope
  readonly sets?: readonly DefinedNameEntry[]
  /// 旧字符串表示全局名称；对象明确指定工作表作用域。
  readonly removes?: readonly (string | { readonly name: string; readonly scopeSheetName?: string | undefined })[]
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
    const key = entryKey(entry)
    if (seen.has(key)) {
      throw new DefinedNameError(`名称 "${entry.name}" 在同一次操作中重复定义。`)
    }
    seen.add(key)
  }
  const removals = (plan.removes ?? []).map(entry => typeof entry === 'string' ? { name: entry } : entry)
  const removedLower = new Set(removals.map(entryKey))
  for (const entry of plan.sets ?? []) {
    if (removedLower.has(entryKey(entry))) {
      throw new DefinedNameError(`名称 "${entry.name}" 同时出现在新增与删除列表中。`)
    }
  }
  for (const { name } of removals) {
    if (!isValidDefinedName(name)) {
      throw new DefinedNameError(`名称 "${name}" 不合法。`)
    }
  }

  const source = await createBufferEntrySource(sourceBytes)
  let workbookXml = await source.readText('xl/workbook.xml')
  for (const entry of [...(plan.sets ?? []), ...removals]) {
    if (entry.scopeSheetName !== undefined && (typeof entry.scopeSheetName !== 'string' || !sheetNames(workbookXml).includes(entry.scopeSheetName))) throw new DefinedNameError('名称的工作表作用域不存在。')
  }
  for (const entry of removals) workbookXml = removeName(workbookXml, entry)
  for (const entry of plan.sets ?? []) workbookXml = setName(workbookXml, entry)
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
