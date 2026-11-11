import { SaxesParser } from 'saxes'

const MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
export interface SheetTableSource { path: string; name: string; displayName: string }

/** 身份只依赖完整XML的根，不要求列、范围或样式可编辑。 */
export function readTableSource(xml: string, path: string): SheetTableSource {
  const parser = new SaxesParser({ xmlns: true })
  let depth = 0, result: SheetTableSource | undefined
  parser.on('doctype', () => { throw new Error('表格来源不支持DOCTYPE') })
  parser.on('opentag', tag => {
    depth++
    if (depth !== 1) return
    if (tag.local !== 'table' || tag.uri !== MAIN_NS) throw new Error('表格根元素命名空间或结构无效')
    const attr = (name: string) => Object.values(tag.attributes).find(value => !value.uri && value.local === name)?.value
    const name = attr('name'), displayName = attr('displayName')
    if (name !== undefined && !name.trim() || displayName !== undefined && !displayName.trim() || !name && !displayName) throw new Error('表格来源名称缺失')
    result = { path, name: name ?? displayName!, displayName: displayName ?? name! }
  })
  parser.on('closetag', () => { depth-- })
  parser.write(xml).close()
  if (!result) throw new Error('表格根元素缺失')
  return result
}

/** 不从注释、扩展节点或外来命名空间猜测tablePart归属。 */
export function readTableRelationshipIds(xml: string): string[] {
  const parser = new SaxesParser({ xmlns: true }), ids: string[] = []
  let depth = 0, containers = 0, inParts = false, count: string | undefined
  parser.on('doctype', () => { throw new Error('表格归属来源不支持DOCTYPE') })
  parser.on('opentag', tag => {
    depth++
    if (depth === 1 && (tag.local !== 'worksheet' || tag.uri !== MAIN_NS)) throw new Error('表格归属工作表根无效')
    if (tag.local === 'tableParts') {
      if (depth !== 2 || tag.uri !== MAIN_NS || ++containers !== 1) throw new Error('表格容器重复或命名空间无效')
      inParts = true
      count = Object.values(tag.attributes).find(value => !value.uri && value.local === 'count')?.value
    } else if (inParts) {
      if (depth !== 3 || tag.local !== 'tablePart' || tag.uri !== MAIN_NS) throw new Error('表格归属容器内容无效')
      const id = Object.values(tag.attributes).find(value => value.uri === REL_NS && value.local === 'id')?.value
      if (!id || ids.includes(id)) throw new Error('表格归属关系身份缺失或重复')
      ids.push(id)
    } else if (tag.local === 'tablePart') throw new Error('表格归属容器缺失')
  })
  parser.on('text', value => { if (inParts && value.trim()) throw new Error('表格归属容器内容无效') })
  parser.on('closetag', () => { if (depth === 2) inParts = false;depth-- })
  parser.write(xml).close()
  if (count !== undefined && (!/^\d+$/.test(count) || Number(count) !== ids.length)) throw new Error('表格容器数量不一致')
  return ids
}
