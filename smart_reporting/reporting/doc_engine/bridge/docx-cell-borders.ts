import { splitXmlChildren, xmlSegments } from '../packages/docx-engine/src/generate'
import { DOCX_CELL_BORDER_SIDES, docxCellBorderRect, docxCellBorderSideLine, safeDocxCellBorderSteps } from './docx-cell-borders-spec'
function fail(reason: string): never { throw new Error(`docx_cell_borders_${reason}`) }
const tcOrder = ['w:cnfStyle', 'w:tcW', 'w:gridSpan', 'w:hMerge', 'w:vMerge', 'w:tcBorders', 'w:shd', 'w:noWrap', 'w:tcMar', 'w:textDirection', 'w:tcFitText', 'w:vAlign', 'w:hideMark', 'w:headers']
const tableOrder = ['w:tblStyle', 'w:tblpPr', 'w:tblOverlap', 'w:bidiVisual', 'w:tblStyleRowBandSize', 'w:tblStyleColBandSize', 'w:tblW', 'w:jc', 'w:tblCellSpacing', 'w:tblInd', 'w:tblBorders', 'w:shd', 'w:tblLayout', 'w:tblCellMar', 'w:tblLook']
const borderOrder = DOCX_CELL_BORDER_SIDES.map(side => `w:${side}`)
/** 替换一个直接子节点，保留所有未命中字节（包括空白、注释、未知属性）。 */
function childPatch(xml: string, name: string, replacement: string, order: readonly string[]): string {
  const open = /^<([\w:.-]+)\b[^>]*>/.exec(xml)
  if (!open) fail('xml_invalid')
  if (open[0].endsWith('/>')) {
    if (!replacement) return xml
    return open[0].slice(0, -2) + '>' + replacement + `</${open[1]}>`
  }
  const close = `</${open[1]}>`
  if (!xml.endsWith(close)) fail('xml_invalid')
  const children = splitXmlChildren(xml.slice(open[0].length, -close.length)), matches = children.filter(child => child.name === name)
  if (matches.length > 1) fail('xml_invalid')
  if (matches.length) {
    const old = matches[0]!.xml, at = xml.indexOf(old, open[0].length)
    return xml.slice(0, at) + replacement + xml.slice(at + old.length)
  }
  if (!replacement) return xml
  const rank = order.indexOf(name), next = children.find(child => order.indexOf(child.name) > rank)
  const at = next ? xml.indexOf(next.xml, open[0].length) : xml.length - close.length
  return xml.slice(0, at) + replacement + xml.slice(at)
}
function onlyChild(xml: string, name: string): string | null {
  const open = /^<[\w:.-]+\b[^>]*>/.exec(xml)?.[0]
  if (!open || open.endsWith('/>')) return null
  const close = xml.lastIndexOf('</'), children = splitXmlChildren(xml.slice(open.length, close)), matches = children.filter(child => child.name === name)
  if (matches.length > 1) fail('xml_invalid')
  return matches[0]?.xml ?? null
}
function rowsOf(tableXml: string) {
  return xmlSegments(tableXml, 'w:tr', 0, tableXml.length).map(row => xmlSegments(tableXml, 'w:tc', row.start, row.end))
}
export function docxCellBordersCapability(tableXml: string): { bordersEditable: boolean; bordersReadOnlyReason?: string } {
  try {
    if ((tableXml.match(/<w:tbl\b/g) ?? []).length !== 1 || /<w:(?:vMerge|hMerge|gridSpan|ins|del|moveFrom|moveTo|sdt|trPrChange|tblPrChange|tcPrChange|cellIns|cellDel|cellMerge)\b/.test(tableXml)) fail('source_unsupported')
    const rows = rowsOf(tableXml)
    if (!rows.length || !rows[0]?.length || rows.some(row => row.length !== rows[0]!.length)) fail('source_unsupported')
    const tblPr = onlyChild(tableXml, 'w:tblPr')
    if (tblPr) onlyChild(tblPr, 'w:tblBorders')
    for (const row of rows) for (const segment of row) {
      const cell = tableXml.slice(segment.start, segment.end), props = onlyChild(cell, 'w:tcPr')
      if (props) {
        const borders = onlyChild(props, 'w:tcBorders')
        if (borders) for (const side of borderOrder) onlyChild(borders, side)
      }
    }
    return { bordersEditable: true }
  } catch { return { bordersEditable: false, bordersReadOnlyReason: '此表包含合并、嵌套、修订或不明确的边框属性，暂不能修改单元格边框' } }
}
/** 一次可信源table上的有序原子补丁；调用方先校验block/hash，再传其原cellId矩阵。 */
export function patchDocxTableCellBorders(tableXml: string, rawSteps: unknown, cells: readonly (readonly { cellId: string }[])[]): string {
  if (!docxCellBordersCapability(tableXml).bordersEditable) fail('source_unsupported')
  const steps = safeDocxCellBorderSteps(rawSteps), originalRows = rowsOf(tableXml)
  if (originalRows.length !== cells.length || originalRows.some((row, r) => row.length !== cells[r]?.length)) fail('anchor_invalid')
  let current = tableXml
  for (const step of steps) {
    const rect = docxCellBorderRect(step, cells), rows = rowsOf(current), patches: { start: number; end: number; xml: string }[] = []
    for (let r = rect.top; r < rect.bottom; r++) for (let c = rect.left; c < rect.right; c++) {
      const segment = rows[r]![c]!, original = current.slice(segment.start, segment.end)
      let props = onlyChild(original, 'w:tcPr') ?? '<w:tcPr/>', borders = onlyChild(props, 'w:tcBorders') ?? '<w:tcBorders/>'
      let changed = false
      for (const side of DOCX_CELL_BORDER_SIDES) {
        const line = docxCellBorderSideLine(step.mode, side, { top: r === rect.top, bottom: r === rect.bottom - 1, left: c === rect.left, right: c === rect.right - 1 }, step.pen)
        if (!line) continue
        const tag = line.style === 'none' ? `<w:${side} w:val="none"/>` : `<w:${side} w:val="${line.style}" w:sz="${line.szEighths}" w:space="0" w:color="${line.color}"/>`
        borders = childPatch(borders, `w:${side}`, tag, borderOrder); changed = true
      }
      if (changed) {
        props = childPatch(props, 'w:tcBorders', borders, tcOrder)
        patches.push({ ...segment, xml: childPatch(original, 'w:tcPr', props, ['w:tcPr', 'w:p']) })
      }
    }
    for (const patch of patches.sort((a, b) => b.start - a.start)) current = current.slice(0, patch.start) + patch.xml + current.slice(patch.end)
    if (step.mode === 'none') {
      const props = onlyChild(current, 'w:tblPr'), borders = props && onlyChild(props, 'w:tblBorders')
      if (props && borders) {
        const next = childPatch(childPatch(borders, 'w:insideH', '', []), 'w:insideV', '', [])
        current = childPatch(current, 'w:tblPr', childPatch(props, 'w:tblBorders', next, tableOrder), ['w:tblPr', 'w:tblGrid', 'w:tr'])
      }
    }
  }
  return current
}
