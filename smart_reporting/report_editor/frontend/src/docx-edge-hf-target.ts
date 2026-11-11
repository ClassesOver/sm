import { restingHfAreaVariant } from './vendor/genoffice-docs/apps/docs/src/renderer/doc-state'
import { visiblePageCount } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination'
import type { DocxHfPart, DocxHfSectionAnchor, DocxHfVariant } from './docx-hf'

type EdgeCut = { start: number; end: number; pageNo: number; section: number }
export interface DocxEdgeHfTarget extends DocxHfSectionAnchor {
  sectionIndex: number
  part: DocxHfPart
  variant: DocxHfVariant
  pageCount: number
  lastPageNo: number
}

/** 源App的首/末页面边缘目标；cuts必须来自当前真实分页，菜单捕获返回身份。 */
export function resolveDocxEdgeHfTarget(part: DocxHfPart, facts: {
  sections: readonly DocxHfSectionAnchor[]
  cuts: readonly EdgeCut[]
  titlePg: boolean
  evenOddHf: boolean
}): DocxEdgeHfTarget {
  const sectionIndex = part === 'header' ? 0 : facts.sections.length - 1
  const anchor = facts.sections[sectionIndex]
  const lastPageNo = facts.cuts.at(-1)?.pageNo
  if (!anchor?.sectionId || !anchor.expectedSectionSha256 || !facts.cuts.length || lastPageNo === undefined || !Number.isSafeInteger(lastPageNo)) throw new Error('页眉页脚目标的当前分页尚未就绪')
  const pageCount = visiblePageCount([...facts.cuts])
  const variant = restingHfAreaVariant(part, { titlePg: facts.titlePg, evenOddHf: facts.evenOddHf, pageCount, lastPageNo })
  return { ...anchor, sectionIndex, part, variant, pageCount, lastPageNo }
}
