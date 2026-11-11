import { createBufferEntrySource, parseRange } from '@sheets-web/xlsx-engine'
import { SaxesParser } from 'saxes'
import { listWorkbookQueries, type WorkbookQuery } from './workbook-vendor/grid/workbook-queries'
export type { WorkbookQuery } from './workbook-vendor/grid/workbook-queries'
const MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
const OFFICE_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const escapeXml = (value: string) => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')

// 源正则读取器只接收已验证并去除注释/外来命名空间的规范 XML。
function canonicalPart(xml: string, path: string): string {
  const namespace = path.endsWith('.rels') ? REL_NS : MAIN_NS
  const expected = path.endsWith('.rels') ? 'Relationships' : path === 'xl/connections.xml' ? 'connections' : path === 'xl/workbook.xml' ? 'workbook' : /\/tables\//.test(path) ? 'table' : 'queryTable'
  const allowed = new Set([expected, 'connections/connection', 'connections/connection/dbPr', 'connections/connection/webPr', 'connections/connection/textPr', 'Relationships/Relationship', 'workbook/sheets', 'workbook/sheets/sheet', 'workbook/definedNames', 'workbook/definedNames/definedName'])
  const parser = new SaxesParser({ xmlns: true }), stack: boolean[] = [], names: string[] = []
  let output = ''
  parser.on('opentag', tag => {
    if (!stack.length && (tag.local !== expected || tag.uri !== namespace)) throw new Error('查询元数据根元素或命名空间无效')
    names.push(tag.local)
    const include = tag.uri === namespace && (stack.at(-1) ?? true) && allowed.has(names.join('/')); stack.push(include)
    if (!include) return
    const attrs = Object.values(tag.attributes).filter(attr => !attr.uri || attr.uri === OFFICE_NS).map(attr => ' ' + (attr.uri === OFFICE_NS ? 'r:' : '') + attr.local + '="' + escapeXml(attr.value) + '"').join('')
    output += '<' + tag.local + attrs + '>'
  })
  parser.on('text', text => { if (stack.at(-1)) output += escapeXml(text) })
  parser.on('cdata', text => { if (stack.at(-1)) output += escapeXml(text) })
  parser.on('closetag', tag => { if (stack.pop()) output += '</' + tag.local + '>'; names.pop() })
  parser.write(xml).close()
  return output.replace(/<([A-Za-z][\w:]*)\b([^>]*)><\/\1>/g, '<$1$2/>')
}

function safeText(text: string): string {
  return text.replace(/https?:\/\/[^\s;]+/gi, value => {
    try { const url = new URL(value); return url.origin + url.pathname } catch { return '[地址已隐藏]' }
  }).replace(/((?:password|pwd|uid|token|secret|api[_ -]?key|authorization|user(?:name| id)?)\s*[=:]\s*)(?:"[^"]*"|'[^']*'|[^;,&\s]*)/gi, '$1[已隐藏]')
}
function safeSource(source: string, kind: WorkbookQuery['kind']): string | undefined {
  try {
    const url = new URL(source)
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.origin + safeText(url.pathname)
    if (kind === 'web') return undefined
  } catch { if (kind === 'web') return undefined }
  const basename = source.split(/[\\/]/).pop()?.split(/[?#;]/, 1)[0]
  return basename ? safeText(basename) : undefined
}

/** 只读 OOXML 元数据，不请求连接地址，不执行查询，不修改工作簿。 */
export async function readWorkbookQueries(bytes: Uint8Array): Promise<WorkbookQuery[]> {
  const source = await createBufferEntrySource(bytes)
  const queries = await listWorkbookQueries(async path => {
    if (!await source.has(path)) return undefined
    const xml = await source.readText(path)
    return canonicalPart(xml, path)
  })
  return queries.map(query => {
    const { source: rawSource, description, destination, ...rest } = query
    const displaySource = rawSource ? safeSource(rawSource, query.kind) : undefined
    let validDestination = false
    if (destination) {
      try {
        const range = parseRange(destination.range)
        validDestination = range.startRow >= 0 && range.endRow < 1048576 && range.startColumn >= 0 && range.endColumn < 16384
      } catch { /* 无效范围不能作为可导航目标。 */ }
    }
    // 自由说明可嵌任意连接串/凭据，不进入只读 UI 或 title。
    return { ...rest, name: safeText(query.name), ...(displaySource ? { source: displaySource } : {}), ...(validDestination ? { destination } : {}) }
  })
}
