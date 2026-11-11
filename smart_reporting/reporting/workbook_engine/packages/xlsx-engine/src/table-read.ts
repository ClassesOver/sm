import { readTableSource, readTableRelationshipIds, type SheetTableSource } from './table-source'
import { relationships } from './sheet-removal-parts'
import type { CustomTableStyle } from './table-style-read'
import { parseRange, type RangeBounds } from './cell-address'
import { decodeXmlText, extractElements, readXmlAttribute, sectionInner } from './xml'
import type { EntrySource } from './zip'
import { decodeXlsxEscapes } from './xlsx-escapes'

const MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

export interface SheetTableModel {
  id: string
  name: string
  displayName: string
  path: string
  range: RangeBounds
  headerRowCount: number
  customStyle?: CustomTableStyle
  totalsRowCount: number
  filterButton: boolean
  columns: { id: string; name: string }[]
  style?: { name?: string; showFirstColumn: boolean; showLastColumn: boolean; showRowStripes: boolean; showColumnStripes: boolean }
}

export function resolveTablePartPath(sheetPath: string, target: string): string {
  if (/[\\?#:%]/.test(target)) throw new Error('表格关系路径不安全')
  const parts = target.startsWith('/') ? [] : sheetPath.split('/').slice(0, -1)
  for (const part of target.split('/')) {
    if (part === '..') { if (!parts.pop()) throw new Error('表格关系越界') }
    else if (part && part !== '.') parts.push(part)
  }
  const path = parts.join('/')
  if (!path.startsWith('xl/')) throw new Error('表格关系越界')
  return path
}

function required(xml: string, attribute: string): string {
  const raw = readXmlAttribute(xml, attribute)
  if (!raw) throw new Error(`表格缺少 ${attribute}`)
  return decodeXmlText(raw)
}

function numericId(xml: string): string {
  const value = required(xml, 'id')
  if (!/^\d+$/.test(value) || Number(value) < 1 || Number(value) > 4294967295) throw new Error('表格身份编号无效')
  return String(Number(value))
}

function children(xml: string, container: string, child: string): string[] {
  if ([...xml.matchAll(new RegExp(`<${container}\\b`, 'g'))].length !== 1) throw new Error('表格容器重复或缺失')
  const open = xml.match(new RegExp(`<${container}\\b[^>]*>`))?.[0]
  const inner = sectionInner(xml, container)
  if (!open || inner === null) throw new Error('表格容器不完整')
  if (readXmlAttribute(open, 'xmlns') !== undefined && readXmlAttribute(open, 'xmlns') !== MAIN_NS) throw new Error('表格容器命名空间无效')
  const items = extractElements(inner, child)
  const count = readXmlAttribute(open, 'count')
  let remainder = inner
  for (const item of items) {
    const tag = item.match(/^<[^>]*>/)![0]
    if (readXmlAttribute(tag, 'xmlns') !== undefined && readXmlAttribute(tag, 'xmlns') !== MAIN_NS) throw new Error('表格子元素命名空间无效')
    remainder = remainder.replace(item, '')
  }
  if (remainder.trim() || (count !== undefined && (!/^\d+$/.test(count) || Number(count) !== items.length))) throw new Error('表格容器数量或内容不一致')
  return items
}

export function tableRelationshipId(worksheetXml: string, part: string): string {
  const root = worksheetXml.match(/<worksheet\b[^>]*>/)?.[0] ?? ''
  const container = worksheetXml.match(/<tableParts\b[^>]*>/)?.[0] ?? ''
  const bindings = new Map<string, string>()
  for (const tag of [root, container, part]) for (const match of tag.matchAll(/\sxmlns:([\w.-]+)="([^"]*)"/g)) bindings.set(match[1]!, decodeXmlText(match[2]!))
  const ids = [...part.matchAll(/\s([\w.-]+):id="([^"]*)"/g)].filter(match => bindings.get(match[1]!) === REL_NS)
  if (ids.length !== 1) throw new Error('表格关系属性命名空间无效')
  return decodeXmlText(ids[0]![2]!)
}

function rowCount(xml: string, attribute: string, fallback: number): number {
  const value = readXmlAttribute(xml, attribute) ?? String(fallback)
  if (!/^[01]$/.test(value)) throw new Error('表格表头或汇总行数无效')
  return Number(value)
}

function parseTable(xml: string, path: string): SheetTableModel {
  const open = xml.match(/<table\b[^>]*>/)?.[0]
  if (!open) throw new Error('表格根元素缺失')
  if (!/^\s*(?:<\?xml[^>]*>\s*)?<table\b[\s\S]*<\/table>\s*$/.test(xml) || [...xml.matchAll(/<table\b/g)].length !== 1) throw new Error('表格根结构不完整')
  if (readXmlAttribute(open, 'xmlns') !== MAIN_NS) throw new Error('表格根元素命名空间无效')
  const range = parseRange(required(open, 'ref'))
  if (range.endRow > 1048575 || range.endColumn > 16383) throw new Error('表格范围越界')
  const headerRowCount = rowCount(open, 'headerRowCount', 1)
  const totalsRowCount = rowCount(open, 'totalsRowCount', 0)
  if (headerRowCount + totalsRowCount > range.endRow - range.startRow + 1) throw new Error('表格行数无效')
  const columns = children(xml, 'tableColumns', 'tableColumn').map(column => {
    const tag = column.match(/^<tableColumn\b[^>]*>/)![0]
    return { id: numericId(tag), name: decodeXlsxEscapes(required(tag, 'name')) }
  })
  if (columns.length !== range.endColumn - range.startColumn + 1 ||
      new Set(columns.map(column => column.id)).size !== columns.length ||
      new Set(columns.map(column => column.name.toLowerCase())).size !== columns.length) throw new Error('表格列定义与范围不一致')
  const styleXml = xml.match(/<tableStyleInfo\b[^>]*>/)?.[0]
  if (styleXml && readXmlAttribute(styleXml, 'xmlns') !== undefined && readXmlAttribute(styleXml, 'xmlns') !== MAIN_NS) throw new Error('表格样式命名空间无效')
  const flag = (attribute: string) => {
    const value = readXmlAttribute(styleXml ?? '', attribute) ?? '0'
    if (!/^(0|1|true|false)$/.test(value)) throw new Error('表格样式选项无效')
    return value === '1' || value === 'true'
  }
  const styleName = readXmlAttribute(styleXml ?? '', 'name')
  return {
    id: numericId(open), name: decodeXmlText(readXmlAttribute(open, 'name') ?? '') || required(open, 'displayName'), displayName: required(open, 'displayName'),
    path, range, headerRowCount, totalsRowCount, filterButton: headerRowCount > 0 && /<autoFilter\b/.test(xml), columns,
    ...(styleXml ? { style: {
      ...(styleName ? { name: decodeXmlText(styleName) } : {}),
      showFirstColumn: flag('showFirstColumn'), showLastColumn: flag('showLastColumn'),
      showRowStripes: flag('showRowStripes'), showColumnStripes: flag('showColumnStripes'),
    } } : {}),
  }
}

/// 只读取工作表明确拥有的表格；不完整上下文不能用于结构化引用解析。
/// 保留原始包，读取失败不阻断其他内容的编辑或下载。
export async function readSheetTables(source: EntrySource, sheetPath: string, worksheetXml: string): Promise<{ tables: SheetTableModel[]; tablesReadOnlyReason?: string; tableSources?: SheetTableSource[]; tableSourcesReadOnlyReason?: string }> {
  let tableSources: SheetTableSource[] | undefined
  try {
    const ids = readTableRelationshipIds(worksheetXml)
    const sources: SheetTableSource[] = [], xmls = new Map<string, string>(), names = new Set<string>()
    const relsPath = sheetPath.replace(/\/([^/]+)$/, '/_rels/$1.rels')
    const rels = await source.has(relsPath) ? relationships(await source.readText(relsPath), relsPath) : []
    const tableTypes = new Set([REL_NS + '/table', 'http://purl.oclc.org/ooxml/officeDocument/relationships/table'])
    if (rels.some(rel => tableTypes.has(rel.type) && !ids.includes(rel.id))) throw new Error('表格所属关系未完整登记在工作表中')
    if (ids.length) {
      for (const id of ids) {
        const rel = rels.find(rel => rel.id === id)
        if (!rel || rel.external || rel.type !== `${REL_NS}/table`) throw new Error('表格所属关系无效')
        const path = resolveTablePartPath(sheetPath, rel.target)
        if (xmls.has(path)) throw new Error('表格来源重复')
        const xml = await source.readText(path), identity = readTableSource(xml, path)
        for (const name of new Set([identity.name.toLowerCase(), identity.displayName.toLowerCase()])) {
          if (names.has(name)) throw new Error('表格名称重复')
          names.add(name)
        }
        sources.push(identity);xmls.set(path, xml)
      }
    }
    tableSources = sources
    return { tables: sources.map(identity => parseTable(xmls.get(identity.path)!, identity.path)), tableSources }
  } catch (error) {
    const reason = (error as Error).message
    return { tables: [], tablesReadOnlyReason: reason, ...(tableSources ? { tableSources } : { tableSourcesReadOnlyReason: reason }) }
  }
}
