/// Protection state readback (本地新增): the editor projects whether a sheet or
/// the workbook structure is protected, and whether a password guards it, so
/// the protect/unprotect commands only offer what `protection.ts` can write
/// (no password support: password-protected targets stay as they are).

import { decodeXmlText, readXmlAttribute } from './xml'
import { formatAddress, parseRange } from './cell-address'

export interface EditableRange {
  readonly name: string
  readonly sqref: string
  readonly readonlyReason?: string
}

/** 仅支持工作表内 A1 区域并集；归一化同时限制到 Excel 实际边界。 */
export function normalizeEditableRangeRef(sqref: string): string {
  const parts = sqref.trim().split(/\s+/)
  if (!sqref.trim() || parts.length > 1000) throw new Error('允许编辑区域必须是有效的单元格区域')
  return parts.map(part => {
    const area = parseRange(part.toUpperCase())
    if (area.endRow > 1048575 || area.endColumn > 16383) throw new Error('允许编辑区域超出工作表边界')
    const first = formatAddress(area.startRow, area.startColumn), last = formatAddress(area.endRow, area.endColumn)
    return first === last ? first : first + ':' + last
  }).join(' ')
}

/** 带密码、身份权限或未知限制的范围仅展示；绝不将其当作免密码可编辑区域。 */
export function readProtectedRanges(worksheetXml: string): EditableRange[] {
  const section = worksheetXml.match(/<(?:\w+:)?protectedRanges\b[^>]*>[\s\S]*?<\/(?:\w+:)?protectedRanges>/)?.[0] ?? ''
  const skeleton = section.replace(/<(?:\w+:)?protectedRange\b[^>]*(?:\/>|>[\s\S]*?<\/(?:\w+:)?protectedRange>)/g, '')
  const unsupportedSection = section !== '' && !/^<(?:\w+:)?protectedRanges\s*>\s*<\/(?:\w+:)?protectedRanges>$/.test(skeleton)
  return [...section.matchAll(/<(?:\w+:)?protectedRange\b[^>]*(?:\/>|>[\s\S]*?<\/(?:\w+:)?protectedRange>)/g)].map(match => {
    const element = match[0], attributes = [...element.matchAll(/([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)]
    const value = (name: string) => decodeXmlText(attributes.find(attr => attr[1] === name)?.slice(2).find(part => part !== undefined) ?? '')
    const name = value('name'), original = value('sqref')
    let sqref = original, readonlyReason: string | undefined
    if (unsupportedSection || attributes.some(attr => !['name', 'sqref'].includes(attr[1]!)) || !/\/\s*>$/.test(element)) readonlyReason = '该区域包含密码、用户权限或未支持的限制，保留原定义且不可编辑'
    try { sqref = normalizeEditableRangeRef(original) } catch { readonlyReason = '该区域地址暂不支持，保留原定义且不可编辑' }
    if (!name) readonlyReason = '区域名称缺失，保留原定义且不可编辑'
    return { name, sqref, ...(readonlyReason ? { readonlyReason } : {}) }
  })
}

export interface SheetProtectionModel {
  readonly protected: boolean
  readonly hasPassword: boolean
}

export interface WorkbookProtectionModel {
  readonly lockStructure: boolean
  readonly hasPassword: boolean
}

const truthy = (value: string | undefined) => value === '1' || value === 'true'

export function readSheetProtection(worksheetXml: string): SheetProtectionModel | undefined {
  const element = worksheetXml.match(/<(?:\w+:)?sheetProtection\b[^>]*>/)?.[0]
  if (!element) return undefined
  return {
    protected: truthy(readXmlAttribute(element, 'sheet')),
    hasPassword: /\b(?:password|hashValue)="/.test(element),
  }
}

export function readWorkbookProtection(workbookXml: string): WorkbookProtectionModel | undefined {
  const element = workbookXml.match(/<(?:\w+:)?workbookProtection\b[^>]*>/)?.[0]
  if (!element) return undefined
  return {
    lockStructure: truthy(readXmlAttribute(element, 'lockStructure')),
    hasPassword: /\bworkbook(?:Password|HashValue)="/.test(element),
  }
}
