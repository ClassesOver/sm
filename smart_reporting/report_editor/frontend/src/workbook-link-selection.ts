import { parseRange, rangeCellCount, type CellHyperlink, type RangeBounds, type SheetHyperlinkEdit } from '@sheets-web/xlsx-engine'

const CLEAR_LINK_SELECTION_LIMIT = 10_000

export function assertClearLinkSelection(selection: RangeBounds) {
  if (rangeCellCount(selection) > CLEAR_LINK_SELECTION_LIMIT) throw new Error('清除超链接的选区不能超过 10,000 个单元格')
}

export function hyperlinksToClear(links: readonly CellHyperlink[], selection: RangeBounds): SheetHyperlinkEdit[] {
  assertClearLinkSelection(selection)
  const edits: SheetHyperlinkEdit[] = []
  for (const link of links) {
    let bounds: RangeBounds
    try { bounds = parseRange(link.ref) }
    catch { continue }
    if (bounds.endRow < selection.startRow || bounds.startRow > selection.endRow ||
        bounds.endColumn < selection.startColumn || bounds.startColumn > selection.endColumn) continue
    if (link.readOnlyReason || !link.target) throw new Error(link.readOnlyReason ?? '链接没有目标，暂不支持在此编辑')
    edits.push({ ref: link.ref, expectedTarget: link.target, target: null })
  }
  return edits
}
