/** Post-generation diagnostics only: preserve output bytes even if review fails. */
import { PDFDocument } from 'pdf-lib'
import { measureLabelBounds } from '../src/main/measure-label-bounds'

export interface MeasureLabelReviewTarget {
  operationIndex: number
  pageIndex: number
  from: readonly number[]
  to: readonly number[]
  label: string
}
export interface MeasureLabelReviewIssue {
  operationIndex: number
  kind: string
  fieldName: string
  code: string
  message: string
  details?: unknown
}
const failed = (target: MeasureLabelReviewTarget): MeasureLabelReviewIssue => ({
  operationIndex: target.operationIndex, kind: 'addDrawing', fieldName: '',
  code: 'pdf_measure_label_crop_review_failed',
  message: '测量标签的页边裁切风险复核失败；实际生成文件已保留，请核对实际预览。',
})

/** Coordinates remain PDF user-space units; rotation/UserUnit do not alter containment. */
export async function reviewMeasureLabelClipping(bytes: Uint8Array, targets: MeasureLabelReviewTarget[]): Promise<MeasureLabelReviewIssue[]> {
  if (!targets.length) return []
  let document: PDFDocument
  try { document = await PDFDocument.load(bytes, { updateMetadata: false }) }
  catch { return targets.map(failed) }
  return targets.flatMap((target): MeasureLabelReviewIssue[] => {
    try {
      if (!Number.isInteger(target.pageIndex) || target.pageIndex < 0 || target.pageIndex >= document.getPageCount()) return [failed(target)]
      const page = document.getPage(target.pageIndex), crop = page.getCropBox(), media = page.getMediaBox()
      const visibleBox = [Math.max(crop.x, media.x), Math.max(crop.y, media.y),
        Math.min(crop.x + crop.width, media.x + media.width), Math.min(crop.y + crop.height, media.y + media.height)]
      const labelBounds = measureLabelBounds(target.from, target.to, target.label)
      if (![...visibleBox, ...labelBounds].every(Number.isFinite) || visibleBox[0]! >= visibleBox[2]! || visibleBox[1]! >= visibleBox[3]!) return [failed(target)]
      const clippedEdges = (['left', 'bottom', 'right', 'top'] as const).filter((_, index) => index < 2
        ? labelBounds[index]! < visibleBox[index]! : labelBounds[index]! > visibleBox[index]!)
      if (!clippedEdges.length) return []
      return [{ operationIndex: target.operationIndex, kind: 'addDrawing', fieldName: '',
        code: 'pdf_measure_label_crop_clipping',
        message: `第 ${target.pageIndex + 1} 页的测量标签可能超出可见页框而被裁切；标签和生成文件已保留，请核对实际预览，可移动测量线或调整测量单位后重试。`,
        details: { pageNumber: target.pageIndex + 1, visibleBox, labelBounds, clippedEdges,
          conservativeFontBounds: true } }]
    } catch { return [failed(target)] }
  })
}
