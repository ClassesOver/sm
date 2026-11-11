import { splitXmlChildren, xmlSegments } from '../packages/docx-engine/src/generate'

function fail(reason: string): never { throw new Error(`docx_cell_shading_${reason}`) }
export function safeDocxCellShadingFill(fill: unknown): string | null {
  if (fill === null) return null
  if (typeof fill !== 'string' || !/^[0-9a-fA-F]{6}$/.test(fill)) fail('fill_invalid')
  return fill.toUpperCase()
}
const unsupported = /<w:(?:vMerge|hMerge|gridSpan|ins|del|moveFrom|moveTo|sdt|trPrChange|tblPrChange|tcPrChange|cellIns|cellDel)\b/
/** 源表的物理 cell 身份须与编辑器一一对应；正文 rich runs 不影响底纹能力。 */
export function docxCellShadingCapability(tableXml: string, cellXml: string): { shadingEditable: boolean; shadingReadOnlyReason?: string } {
  try {
    if ((tableXml.match(/<w:tbl\b/g) ?? []).length !== 1 || unsupported.test(tableXml)) fail('source_unsupported')
    patchDocxCellShading(cellXml, null)
    return { shadingEditable: true }
  } catch {
    return { shadingEditable: false, shadingReadOnlyReason: '此表包含合并、嵌套、修订或不明确的单元格属性，暂不能修改底纹' }
  }
}
/** 只修改直接 tcPr/shd；无色删除直接底纹，让原 tblStyle 继续继承。 */
export function patchDocxCellShading(cellXml: string, value: unknown): string {
  const fill = safeDocxCellShadingFill(value)
  if (!/^<w:tc\b/.test(cellXml) || !cellXml.endsWith('</w:tc>') || unsupported.test(cellXml) || /<w:tbl\b/.test(cellXml)) fail('source_unsupported')
  const properties = xmlSegments(cellXml, 'w:tcPr', 0, cellXml.length)
  if (properties.length > 1) fail('properties_invalid')
  const tag = fill === null ? '' : `<w:shd w:val="clear" w:color="auto" w:fill="${fill}"/>`
  if (!properties.length) {
    if (!tag) return cellXml
    const open = /^<w:tc\b[^>]*>/.exec(cellXml)?.[0]
    if (!open) fail('properties_invalid')
    return open + `<w:tcPr>${tag}</w:tcPr>` + cellXml.slice(open.length)
  }
  const property = properties[0]!, original = cellXml.slice(property.start, property.end)
  if (original.endsWith('/>')) {
    if (!tag) return cellXml
    return cellXml.slice(0, property.start) + original.slice(0, -2) + `>${tag}</w:tcPr>` + cellXml.slice(property.end)
  }
  const open = /^<w:tcPr\b[^>]*>/.exec(original)?.[0]
  if (!open || !original.endsWith('</w:tcPr>')) fail('properties_invalid')
  const children = splitXmlChildren(original.slice(open.length, -'</w:tcPr>'.length))
  const shading = children.filter(child => child.name === 'w:shd')
  if (shading.length > 1) fail('properties_invalid')
  // Word 的 w:shd 是空元素；禁止吞掉未知子树。
  if (shading.some(child => !/^<w:shd\b[^>]*(?:\/>|>\s*<\/w:shd>)$/.test(child.xml))) fail('properties_invalid')
  let replacement = original
  if (shading.length) {
    const old = shading[0]!.xml, at = original.indexOf(old, open.length)
    replacement = original.slice(0, at) + tag + original.slice(at + old.length)
  } else if (tag) {
    const after = new Set(['w:noWrap', 'w:tcMar', 'w:textDirection', 'w:tcFitText', 'w:vAlign', 'w:hideMark', 'w:headers'])
    const following = children.find(child => after.has(child.name))
    const at = following ? original.indexOf(following.xml, open.length) : original.length - '</w:tcPr>'.length
    replacement = original.slice(0, at) + tag + original.slice(at)
  }
  return cellXml.slice(0, property.start) + replacement + cellXml.slice(property.end)
}
