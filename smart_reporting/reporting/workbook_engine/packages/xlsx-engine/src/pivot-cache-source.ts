import { SaxesParser } from 'saxes'
import { escapeXmlAttribute } from './xml'
import { decodeXlsxEscapes } from './xlsx-escapes'

/** 与固定来源 gateway 的缓存定义条目扫描范围一致。 */
export function isPivotCacheDefinitionPath(path: string): boolean {
  return /^xl\/pivotCache\/pivotCacheDefinition[^/]*\.xml$/.test(path)
}

/** worksheetSource@sheet 是普通工作表名，按 Excel 语义忽略大小写。 */
export function pivotCacheReadsFromSheet(cacheXml: string, sheetName: string): boolean {
  return pivotCacheSourceMatches(cacheXml, 'sheet', sheetName)
}

export function pivotCacheReadsFromTable(cacheXml: string, tableName: string, fieldNames?: readonly string[]): boolean {
  return pivotCacheSourceMatches(cacheXml, 'name', tableName, fieldNames)
}

function pivotCacheSourceMatches(cacheXml: string, attributeName: 'sheet' | 'name', value: string, fieldNames?: readonly string[]): boolean {
  const parser = new SaxesParser({ xmlns: true })
  const target = value.toLowerCase()
  const fields = fieldNames && new Set(fieldNames.map(name => name.toLowerCase()))
  let referenced = false
  let fieldReferenced = fieldNames === undefined
  parser.on('doctype', () => { throw new Error('透视表缓存来源不支持DOCTYPE') })
  parser.on('opentag', tag => {
    if (tag.local === 'cacheField' && [
      'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'http://purl.oclc.org/ooxml/spreadsheetml/main',
    ].includes(tag.uri)) {
      const name = Object.values(tag.attributes).find(attribute => !attribute.uri && attribute.local === 'name')?.value
      // 兼容导入的 ST_Xstring 转义和旧本地产物保留的同形字面文本。
      if (name !== undefined && (fields?.has(name.toLowerCase()) || fields?.has(decodeXlsxEscapes(name).toLowerCase()))) fieldReferenced = true
    }
    if (tag.local !== 'worksheetSource' || ![
      'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'http://purl.oclc.org/ooxml/spreadsheetml/main',
    ].includes(tag.uri)) return
    const actual = Object.values(tag.attributes).find(attribute => !attribute.uri && attribute.local === attributeName)?.value
    if (actual?.toLowerCase() === target) referenced = true
  })
  // 完整解析后才返回，避免命中后忽略损坏的后续来源 XML。
  parser.write(cacheXml).close()
  return referenced && fieldReferenced
}

/** 仅替换实际 SpreadsheetML worksheetSource 的 sheet 属性值，保留其余字节。 */
export function renameSheetInPivotCacheSource(cacheXml: string, oldName: string, newName: string): string {
  return renamePivotCacheSourceAttribute(cacheXml, 'sheet', oldName, newName)
}

export function renameTableInPivotCacheSource(cacheXml: string, oldName: string, newName: string, sheetName?: string): string {
  return renamePivotCacheSourceAttribute(cacheXml, 'name', oldName, newName, sheetName)
}

function renamePivotCacheSourceAttribute(cacheXml: string, attributeName: 'sheet' | 'name', oldName: string, newName: string, sheetName?: string): string {
  const parser = new SaxesParser({ xmlns: true })
  const target = oldName.toLowerCase()
  const edits: { start: number; end: number }[] = []
  let tagStart = 0
  parser.on('doctype', () => { throw new Error('透视表缓存来源不支持DOCTYPE') })
  parser.on('opentagstart', () => { tagStart = cacheXml.lastIndexOf('<', parser.position - 1) })
  parser.on('opentag', tag => {
    if (tag.local !== 'worksheetSource' || ![
      'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'http://purl.oclc.org/ooxml/spreadsheetml/main',
    ].includes(tag.uri)) return
    const actual = Object.values(tag.attributes).find(attribute => !attribute.uri && attribute.local === attributeName)?.value
    if (actual?.toLowerCase() !== target) return
    if (attributeName === 'name') {
      const attributes = Object.values(tag.attributes), sheet = attributes.find(attribute => !attribute.uri && attribute.local === 'sheet')?.value
      const external = attributes.some(attribute => attribute.local === 'id' && [
        'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        'http://purl.oclc.org/ooxml/officeDocument/relationships',
      ].includes(attribute.uri))
      if (external || sheetName !== undefined && sheet !== undefined && sheet.toLowerCase() !== sheetName.toLowerCase()) {
        throw new Error('透视表命名来源指向外部或其他工作表，不能安全迁移表名')
      }
    }
    const opening = cacheXml.slice(tagStart, parser.position)
    // XML 已由 parser 校验；逐属性扫描，避免误命中其他属性值内的 sheet= 文本。
    for (const match of opening.matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)) {
      if (match[1] !== attributeName) continue
      const start = tagStart + match.index + match[0].indexOf(match[2]!) + 1
      edits.push({ start, end: start + match[3]!.length })
    }
  })
  // 验证全部 XML 后才应用修改，损坏的后续节点不能留下部分改名结果。
  parser.write(cacheXml).close()
  const value = escapeXmlAttribute(newName).replaceAll('\t', '&#9;').replaceAll('\n', '&#10;').replaceAll('\r', '&#13;')
  let result = cacheXml
  for (const edit of edits.reverse()) result = result.slice(0, edit.start) + value + result.slice(edit.end)
  return result
}
