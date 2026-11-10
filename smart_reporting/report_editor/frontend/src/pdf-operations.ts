import { formatLength, type MeasureScale } from './vendor/genoffice-pdf/renderer/measure'
import { validatePdfReplies } from './pdf-replies'
import { validateAttachmentEdits, type PdfAttachmentModel } from './pdf-attachment-edits'
import { validatePendingPdfNote, validatePdfNoteOperation, type SavedPdfNote } from './pdf-notes'
import { validatePdfMarkup, type SavedPdfMarkup } from './pdf-markup'
import type { NativeOperation } from './native-draft'
import { buildStamps, type HeaderFooterConfig, type WatermarkConfig } from './vendor/genoffice-pdf/renderer/stamps'
import type { PDFPageProxy } from 'pdfjs-dist'

export const PDF_PAPER_SIZES = [{ label: 'A3', width: 842, height: 1191 }, { label: 'A4', width: 595, height: 842 }, { label: 'A5', width: 420, height: 595 }, { label: 'Letter', width: 612, height: 792 }, { label: 'Legal', width: 612, height: 1008 }] as const
export function validatePdfSizeOperations(operations: NativeOperation[]) {
  const sizes = operations.filter(op => op.kind === 'setPageSize')
  if (sizes.length > 1 || sizes.some(op => !PDF_PAPER_SIZES.some(paper => paper.label === op.preset)) || (sizes.length && operations.some(op => ['cropPage', 'replaceText', 'replyNote', 'replyPendingNote'].includes(op.kind)))) throw new Error('页面尺寸不能重复或与裁切、原位改字、回复混用；请先保存重开')
}
export function setPdfPageSize(operations: NativeOperation[], preset: string): NativeOperation[] {
  validatePdfSizeOperations(operations)
  if (operations.some(op => op.kind === 'setPageSize' && op.preset === preset)) return structuredClone(operations)
  const result = [...structuredClone(operations).filter(op => op.kind !== 'setPageSize'), { kind: 'setPageSize', preset }]
  validatePdfSizeOperations(result)
  if (result.length > 500) throw new Error('页面尺寸变更将超过 500 条修改，请先保存')
  return result
}
export interface PdfBox { x: number; y: number; width: number; height: number }
export interface PdfPageIdentity { pageId: string; index: number; blank?: boolean; mediaBox: PdfBox; cropBox: PdfBox; rotation: number; textObjects?: PdfTextObject[]; markups?: SavedPdfMarkup[]; markupReadSafe?: boolean; notes?: SavedPdfNote[]; notesReadSafe?: boolean }
export interface PdfFormField { name: string; kind: 'text' | 'checkbox' | 'radio' | 'choice' | 'signature' | 'unsupported'; value: string | boolean | null; options?: string[]; editable: boolean; fieldId: string; expectedFieldSha256: string }
export interface PdfModel extends PdfAttachmentModel { sourceSha256: string; pageCount: number; pages: PdfPageIdentity[]; formFields?: PdfFormField[]; capabilities?: { cropPage?: boolean; selectionMarkup?: boolean; removeMarkup?: boolean; notes?: boolean; noteReplies?: boolean; savedReplyEdits?: boolean; pendingNoteReplies?: boolean; pageSize?: boolean; pageSizeReason?: string | null } }
export type PdfRect = [number, number, number, number]
export interface PdfViewportInverse { width: number; height: number; convertToPdfPoint(x: number, y: number): number[] }

/** 所有操作引用不可变来源索引；排序后的页面位置永远不能当作来源身份。 */
export function pdfPageState(pages: PdfPageIdentity[], operations: NativeOperation[]): PdfPageIdentity[] {
  validatePdfSizeOperations(operations)
  validateAttachmentEdits(operations)
  validatePdfReplies(pages, operations)
  const byId = new Map(pages.map(page => [page.pageId, { ...page }]))
  const deleted = new Set<string>()
  const removed = new Set<string>()
  let order = pages.map(page => page.pageId)
  let blanks = 0
  let stamped = false
  let redactions = 0
  const layout = operations.find(op => op.kind === 'mergePages' || op.kind === 'splitPages')
  if (layout) {
    if (operations.length !== 1) throw new Error(PDF_PAGE_LAYOUT_ALONE_REASON)
    validatePdfPageLayout(layout)
    return pages.map(page => ({ ...page }))
  }
  if (operations.some(op => op.kind === 'redact') && operations.some(op => op.kind === 'setPageSize')) throw new Error(PDF_REDACTION_PAGE_SIZE_REASON)
  for (const operation of operations) {
    if (stamped && ['reorderPages', 'deletePage', 'insertBlankPage', 'setPageSize', 'cropPage'].includes(operation.kind)) throw new Error(PDF_STAMPS_STRUCTURE_REASON)
    if (operation.kind === 'setStamps') { if (stamped) throw new Error('水印/页眉页脚只能设置一次'); stamped = true; continue }
    if (operation.kind === 'insertBlankPage') {
      // 与引擎 blankPages 一致：空白页按插入顺序追加在来源页之后，索引为 来源页数 + k。
      const blank = pdfBlankPageIdentity(operation, pages.length + blanks++)
      if (byId.has(blank.pageId)) throw new Error('空白页身份重复')
      byId.set(blank.pageId, blank); order = [...order, blank.pageId]
      continue
    }
    if (operation.kind === 'reorderPages') {
      if (!Array.isArray(operation.pageIds) || operation.pageIds.some(id => typeof id !== 'string' || !byId.has(id)) || new Set(operation.pageIds).size !== operation.pageIds.length) throw new Error('页面排序无效')
      order = operation.pageIds as string[]
      continue
    }
    if (['setFormValue', 'setPageSize', 'addAttachment', 'removeAttachment', 'replyNote', 'replyPendingNote'].includes(operation.kind)) continue
    const page = byId.get(String(operation.pageId))
    if (!page) throw new Error('页面身份已过期，请重新打开文件')
    if (page.blank && operation.kind !== 'rotatePage') throw new Error(PDF_BLANK_PAGE_EDIT_REASON)
    if (operation.kind === 'deletePage') deleted.add(page.pageId)
    else if (operation.kind === 'rotatePage') {
      if (![90, 180, 270].includes(Number(operation.delta))) throw new Error('页面旋转无效')
      page.rotation = (page.rotation + Number(operation.delta)) % 360
    } else if (operation.kind === 'cropPage') {
      if (deleted.has(page.pageId)) throw new Error('裁切不能引用已删除页面')
      const rect = validatedPdfCrop(operation.rect, page.cropBox)
      page.cropBox = { x: rect[0], y: rect[1], width: rect[2] - rect[0], height: rect[3] - rect[1] }
    } else if (operation.kind === 'addTextAnnotation') {
      if (deleted.has(page.pageId)) throw new Error('便签不能引用已删除页面')
      validatePendingPdfNote(operation, page)
    } else if (operation.kind === 'editNote' || operation.kind === 'removeNote') {
      if (deleted.has(page.pageId)) throw new Error('便签不能引用已删除页面')
      const note = validatePdfNoteOperation(operation, pages.find(item => item.pageId === page.pageId)!)
      if (removed.has(note.annotationId)) throw new Error('同一便签不能重复编辑或删除')
      removed.add(note.annotationId)
      page.notes = operation.kind === 'removeNote' ? page.notes?.filter(item => item.annotationId !== note.annotationId) : page.notes?.map(item => item.annotationId === note.annotationId ? { ...item, contents: String(operation.contents) } : item)
    } else if (operation.kind === 'removeMarkup') {
      if (deleted.has(page.pageId)) throw new Error('文字标注不能引用已删除页面')
      const source = pages.find(item => item.pageId === page.pageId)!
      const mark = source.markups?.find(item => item.annotationId === operation.annotationId)
      if (Object.keys(operation).some(key => !['kind', 'pageId', 'annotationId', 'expectedAnnotationSha256', 'sourceSha256'].includes(key)) || typeof operation.annotationId !== 'string' || !/^[a-f0-9]{64}$/.test(operation.annotationId) || !source.markupReadSafe || !mark?.removable || mark.expectedAnnotationSha256 !== operation.expectedAnnotationSha256 || removed.has(operation.annotationId)) throw new Error('标注身份已过期或暂不支持移除；原草稿已保留')
      removed.add(operation.annotationId)
      page.markups = page.markups?.filter(item => item.annotationId !== operation.annotationId)
    } else if (operation.kind === 'redact') {
      if (deleted.has(page.pageId)) throw new Error('涂黑不能引用已删除页面')
      validatePdfRedaction(operation, page.cropBox)
      if (++redactions > PDF_REDACTION_MAX) throw new Error(`涂黑区域不能超过 ${PDF_REDACTION_MAX} 个`)
    } else if (operation.kind === 'addDrawing') {
      if (deleted.has(page.pageId)) throw new Error('绘图不能引用已删除页面')
      validatePdfDrawing(operation, page.cropBox)
    } else if (operation.kind === 'addMarkup') {
      if (deleted.has(page.pageId)) throw new Error('文字标注不能引用已删除页面')
      validatePdfMarkup(operation)
      for (const q of operation.quads as number[][]) validatedPdfCrop([q[0], q[5], q[2], q[1]], page.cropBox)
    } else if (!['addMarkup', 'highlight', 'addTextAnnotation', 'replaceText'].includes(operation.kind)) throw new Error('不支持的 PDF 操作')
  }
  for (const operation of operations) {
    if (operation.kind !== 'addDrawing' || operation.shape !== 'link' || operation.destPage === undefined) continue
    const destination = [...byId.values()].find(item => item.index === Number(operation.destPage) - 1)
    if (!destination || deleted.has(destination.pageId)) throw new Error('链接目标页不存在或已删除')
  }
  const remaining = order.filter(id => !deleted.has(id))
  const stampsOp = operations.find(operation => operation.kind === 'setStamps')
  if (stampsOp) validatePdfStamps(stampsOp, remaining.map(id => byId.get(id)!))
  if (remaining.length !== byId.size - deleted.size) throw new Error('页面排序必须包含所有保留页面')
  if (!remaining.length) throw new Error('不能删除全部页面')
  return remaining.map(id => byId.get(id)!)
}


/**
 * 固定源 StampDialog → setStamps：水印与页眉页脚/页码按当前页面顺序由固定源 buildStamps 渲染成 PNG，
 * 位置按 CropBox 原点平移后交给引擎 stamps。页码依赖页面顺序与尺寸，因此设置后不能再重排、删除、
 * 插入、裁切或改尺寸（撤销或保存后再调整）。
 */
export const PDF_STAMPS_STRUCTURE_REASON = '已设置水印/页眉页脚：请先保存或撤销，再调整页面顺序、数量、裁切或尺寸'
export type PdfStampBuilder = typeof buildStamps
export function buildPdfStampsOperation(pages: PdfPageIdentity[], watermark: WatermarkConfig | null, headerFooter: HeaderFooterConfig | null, build: PdfStampBuilder = buildStamps): NativeOperation {
  if (!watermark?.text.trim() && !headerFooter) throw new Error('请填写水印文字或页眉页脚')
  const built = build(pages.map((page, index) => ({ origIdx: index, pw: page.cropBox.width, ph: page.cropBox.height, displayNo: index + 1 })), watermark?.text.trim() ? watermark : null, headerFooter)
  const images: string[] = [], indexOf = new Map<string, number>()
  const stamps = built.map(stamp => {
    const page = pages[stamp.pageIndex]!
    if (!indexOf.has(stamp.image)) { indexOf.set(stamp.image, images.length); images.push(stamp.image) }
    const [x1, y1, x2, y2] = stamp.rect
    return { pageId: page.pageId, image: indexOf.get(stamp.image)!, rect: [x1 + page.cropBox.x, y1 + page.cropBox.y, x2 + page.cropBox.x, y2 + page.cropBox.y], ...(stamp.opacity === undefined ? {} : { opacity: stamp.opacity }) }
  })
  if (!stamps.length) throw new Error('浏览器未能渲染水印/页眉页脚位图')
  return { kind: 'setStamps', watermark: watermark?.text.trim() ? { ...watermark } : null, headerFooter: headerFooter ? { ...headerFooter } : null, images, stamps }
}
export function validatePdfStamps(operation: NativeOperation, pages: PdfPageIdentity[]) {
  const { images, stamps, watermark, headerFooter } = operation as { images?: unknown; stamps?: unknown; watermark?: unknown; headerFooter?: unknown }
  if (Object.keys(operation).some(key => !['kind', 'watermark', 'headerFooter', 'images', 'stamps', 'sourceSha256'].includes(key)) || (!watermark && !headerFooter) || !Array.isArray(images) || !images.length || !Array.isArray(stamps) || !stamps.length) throw new Error('水印/页眉页脚设置无效')
  const byId = new Map(pages.map(page => [page.pageId, page]))
  const covered = new Set<string>()
  for (const stamp of stamps as { pageId: string; image: number; rect: number[] }[]) {
    const page = byId.get(stamp.pageId)
    if (!page || !Number.isInteger(stamp.image) || stamp.image < 0 || stamp.image >= images.length) throw new Error('水印/页眉页脚页面身份已过期')
    covered.add(stamp.pageId)
  }
  if (covered.size !== pages.length) throw new Error('水印/页眉页脚须覆盖全部页面，请重新设置')
}

/** 固定源 DrawLayer 的矩形/椭圆/箭头/手绘；坐标为未旋转 PDF user space，须位于当前可见范围内。 */
export type PdfDrawingShape = 'rect' | 'ellipse' | 'arrow' | 'measure' | 'ink' | 'polygon' | 'caret' | 'link' | 'image'
/** 插入图像：浏览器转成的 PNG（base64，无 data: 前缀），≤ 6MB 编码长度。 */
export const PDF_IMAGE_MAX_BASE64 = 6_000_000
/** 固定源 LinkDialog：外部 URL 或文档内页码二选一。出于安全只接受 http/https/mailto（固定源允许任意 scheme）。 */
export const PDF_LINK_URL = /^(https?:\/\/[^\s]+|mailto:[^\s]+)$/i
export type PdfLinkTarget = { url: string } | { destPage: number }
export const PDF_DRAWING_WIDTH = 2
/** 引擎以 Helvetica 写测量标签：只接受可打印 ASCII，≤ 64 字符；单位因此须为英文（固定源默认 m）。 */
export const PDF_MEASURE_LABEL = /^[\x20-\x7e]{1,64}$/
/** 测量线长度（PDF pt）。 */
export function pdfLineLength(from: number[], to: number[]) { return Math.hypot(to[0]! - from[0]!, to[1]! - from[1]!) }
/** 固定源 DrawLayer.tsx DRAW_COLORS（默认红色）。 */
export const PDF_DRAW_COLORS: { name: string; label: string; rgb: [number, number, number] }[] = [
  { name: 'red', label: '红色', rgb: [0.86, 0.22, 0.18] },
  { name: 'yellow', label: '黄色', rgb: [1, 0.78, 0.13] },
  { name: 'green', label: '绿色', rgb: [0.13, 0.65, 0.35] },
  { name: 'blue', label: '蓝色', rgb: [0.17, 0.4, 1] },
  { name: 'black', label: '黑色', rgb: [0.15, 0.15, 0.15] },
]
export function validatePdfDrawing(operation: NativeOperation, box: PdfBox) {
  const { shape, rect, from, to, paths, vertices, point, color, width, url, destPage, image, label } = operation as Record<string, unknown>
  const finite = (value: unknown, length?: number) => Array.isArray(value) && (length === undefined || value.length === length) && value.every(item => typeof item === 'number' && Number.isFinite(item))
  const inside = (x: number, y: number) => x >= box.x && x <= box.x + box.width && y >= box.y && y <= box.y + box.height
  const allowed = new Set(['kind', 'pageId', 'shape', 'color', 'width', 'sourceSha256', ...(shape === 'arrow' ? ['from', 'to'] : shape === 'measure' ? ['from', 'to', 'label'] : shape === 'ink' ? ['paths'] : shape === 'polygon' ? ['vertices'] : shape === 'caret' ? ['point'] : shape === 'link' ? ['rect', 'url', 'destPage'] : shape === 'image' ? ['rect', 'image'] : ['rect'])])
  if (Object.keys(operation).some(key => !allowed.has(key)) || !finite(color, 3) || (color as number[]).some(value => value < 0 || value > 1) || typeof width !== 'number' || width < 0.25 || width > 24) throw new Error('绘图参数无效')
  if (shape === 'link' && ((url === undefined) === (destPage === undefined) || (url !== undefined && (typeof url !== 'string' || url.length > 2048 || !PDF_LINK_URL.test(url))) || (destPage !== undefined && (!Number.isInteger(destPage) || (destPage as number) < 1)))) throw new Error('链接目标须为 http/https/mailto 地址或有效页码')
  if (shape === 'image' && (typeof image !== 'string' || !image.startsWith('iVBORw0KGgo') || image.length > PDF_IMAGE_MAX_BASE64)) throw new Error('图像须为不超过限额的 PNG')
  if (shape === 'rect' || shape === 'ellipse' || shape === 'link' || shape === 'image') {
    if (!finite(rect, 4)) throw new Error('绘图范围无效')
    const [x1, y1, x2, y2] = rect as number[]
    if (x2! - x1! < 1 || y2! - y1! < 1 || !inside(x1!, y1!) || !inside(x2!, y2!)) throw new Error('绘图范围必须在当前页面内')
  } else if (shape === 'arrow' || shape === 'measure') {
    if (shape === 'measure' && (typeof label !== 'string' || !PDF_MEASURE_LABEL.test(label) || !label.trim())) throw new Error('测量标签须为 1–64 个英文字符（PDF 标签字体为 Helvetica）')
    if (!finite(from, 2) || !finite(to, 2) || !inside(...(from as [number, number])) || !inside(...(to as [number, number])) || Math.hypot((to as number[])[0]! - (from as number[])[0]!, (to as number[])[1]! - (from as number[])[1]!) < 2) throw new Error(shape === 'measure' ? '测量线太短或超出页面' : '箭头太短或超出页面')
  } else if (shape === 'ink') {
    if (!Array.isArray(paths) || !paths.length || paths.length > 20 || paths.some(path => !finite(path) || path.length < 4 || path.length > 4000 || path.length % 2 || path.some((value: number, index: number) => index % 2 === 0 && !inside(value, path[index + 1])))) throw new Error('手绘路径无效')
  } else if (shape === 'polygon') {
    if (!Array.isArray(vertices) || vertices.length < 3 || vertices.length > 200 || vertices.some(vertex => !finite(vertex, 2) || !inside(...(vertex as [number, number])))) throw new Error('多边形至少需要 3 个页面内的顶点')
  } else if (shape === 'caret') {
    if (!finite(point, 2) || !inside(...(point as [number, number]))) throw new Error('插入符号必须在页面内')
  } else throw new Error('不支持的绘图形状')
}
/** 把一次拖拽转换为绘图操作；端点先夹到可见范围内。 */
export function pdfDrawingOperation(pageId: string, shape: PdfDrawingShape, points: number[][], box: PdfBox, color: [number, number, number], target?: PdfLinkTarget | { image: string } | { label: string }): NativeOperation {
  const clamp = (point: number[]) => [Math.min(box.x + box.width, Math.max(box.x, point[0]!)), Math.min(box.y + box.height, Math.max(box.y, point[1]!))].map(value => Math.round(value * 100) / 100)
  const clamped = points.map(clamp)
  const base = { kind: 'addDrawing', pageId, shape, color: [...color], width: PDF_DRAWING_WIDTH, ...(shape === 'link' || shape === 'image' || shape === 'measure' ? target ?? {} : {}) }
  const first = clamped[0]!, last = clamped.at(-1)!
  const distinct = clamped.filter((value, index) => index === 0 || Math.hypot(value[0]! - clamped[index - 1]![0]!, value[1]! - clamped[index - 1]![1]!) >= 2)
  const operation: NativeOperation = shape === 'ink' ? { ...base, paths: [clamped.flat()] }
    : shape === 'polygon' ? { ...base, vertices: distinct }
    : shape === 'caret' ? { ...base, point: first }
    : shape === 'arrow' || shape === 'measure' ? { ...base, from: first, to: last }
    : { ...base, rect: [Math.min(first[0]!, last[0]!), Math.min(first[1]!, last[1]!), Math.max(first[0]!, last[0]!), Math.max(first[1]!, last[1]!)] }
  validatePdfDrawing(operation, box)
  return operation
}

/** 固定源原生安全涂黑（redaction.ts）：标记区域，保存新修订时由 PDFium 永久移除区域内文字/图像/路径并黑块覆盖；来源修订保持不变。 */
export const PDF_REDACTION_MAX = 500
export const PDF_REDACTION_PAGE_SIZE_REASON = '涂黑不能与页面尺寸同批修改；请先保存重开'
export function validatePdfRedaction(operation: NativeOperation, box: PdfBox) {
  if (Object.keys(operation).some(key => !['kind', 'pageId', 'rect', 'sourceSha256'].includes(key))) throw new Error('涂黑参数无效')
  const rect = validatedPdfCrop(operation.rect, box)
  if (rect[2] - rect[0] < 1 || rect[3] - rect[1] < 1) throw new Error('涂黑区域太小')
  return rect
}
export function pdfRedactionOperation(pageId: string, rect: PdfRect, box: PdfBox): NativeOperation {
  const operation: NativeOperation = { kind: 'redact', pageId, rect: rect.map((value, index) => (index < 2 ? Math.ceil : Math.floor)(value * 100) / 100) }
  validatePdfRedaction(operation, box)
  return operation
}

/** 固定源 mergePages（N 合 1，2–16，横向/纵向顺序，可选分隔线）与 splitPages（每页拆成 2/4/9 格）：整份文档重排版，须单独保存为新修订。 */
export const PDF_PAGE_LAYOUT_ALONE_REASON = '合并页面/拆分页面须单独保存，请先保存或撤销其他修改'
export function validatePdfPageLayout(operation: NativeOperation) {
  if (operation.kind === 'mergePages') {
    if (Object.keys(operation).some(key => !['kind', 'perSheet', 'direction', 'separator', 'sourceSha256'].includes(key)) || !Number.isInteger(operation.perSheet) || Number(operation.perSheet) < 2 || Number(operation.perSheet) > 16 || !['horizontal', 'vertical'].includes(String(operation.direction)) || typeof operation.separator !== 'boolean') throw new Error('每张页数须为 2–16 的整数')
  } else if (operation.kind === 'splitPages') {
    if (Object.keys(operation).some(key => !['kind', 'perPage', 'sourceSha256'].includes(key)) || ![2, 4, 9].includes(Number(operation.perPage))) throw new Error('拆分份数须为 2、4 或 9')
  } else throw new Error('不支持的页面版式操作')
  return operation
}
export function pdfMergePagesOperation(perSheet: number, direction: 'horizontal' | 'vertical', separator: boolean): NativeOperation {
  return validatePdfPageLayout({ kind: 'mergePages', perSheet, direction, separator })
}
export function pdfSplitPagesOperation(perPage: number): NativeOperation {
  return validatePdfPageLayout({ kind: 'splitPages', perPage })
}

/** Native crop stores unrotated PDF coordinates, never a displayed page index. */
export function validatedPdfCrop(value: unknown, box: PdfBox): PdfRect {
  if (!Array.isArray(value) || value.length !== 4 || !value.every(item => typeof item === 'number' && Number.isFinite(item))) throw new Error('裁切范围无效')
  const [x1, y1, x2, y2] = value
  if (x2 - x1 < .5 || y2 - y1 < .5 || x1 < box.x || y1 < box.y || x2 > box.x + box.width || y2 > box.y + box.height) throw new Error('裁切范围必须在当前页面内，且宽高至少为 0.5 PDF 单位')
  return [x1, y1, x2, y2]
}

/** Reuse PDF.js PageViewport construction for CropBox/UserUnit/rotation transforms. */
export function pdfPageViewport(page: PDFPageProxy, identity: PdfPageIdentity, scale: number) {
  const base = page.getViewport({ scale, rotation: identity.rotation })
  const box = identity.cropBox
  const viewBox = [box.x, box.y, box.x + box.width, box.y + box.height]
  if (viewBox.every((value, index) => value === base.viewBox[index])) return base
  // PDF.js exposes viewport instances through getViewport, but not its class export.
  const Viewport = base.constructor as new (params: { viewBox: number[]; userUnit: number; scale: number; rotation: number }) => typeof base
  return new Viewport({ viewBox, userUnit: page.userUnit, scale, rotation: identity.rotation })
}

export function cropPdfPage(pages: PdfPageIdentity[], operations: NativeOperation[], pageId: string, rect: unknown): NativeOperation[] {
  if (operations.some(op => op.kind === 'setPageSize')) throw new Error('请先保存页面尺寸并重开，再裁切')
  const page = pdfPageState(pages, operations).find(item => item.pageId === pageId)
  if (!page) throw new Error('页面不存在')
  const bounds = validatedPdfCrop(rect, page.cropBox)
  if (bounds.every((value, index) => value === [page.cropBox.x, page.cropBox.y, page.cropBox.x + page.cropBox.width, page.cropBox.y + page.cropBox.height][index])) return structuredClone(operations)
  if (operations.length >= 500) throw new Error('裁切将超过 500 条修改；请先保存当前修改')
  return [...structuredClone(operations), { kind: 'cropPage', pageId, rect: bounds }]
}

/** Prepare every surviving page before committing one NativeDraft history step. */
export async function cropAllPdfPages(pages: PdfPageIdentity[], operations: NativeOperation[], margins: number[], getViewport: (page: PdfPageIdentity) => Promise<PdfViewportInverse>): Promise<NativeOperation[]> {
  const snapshot = structuredClone(operations), selection = [...margins]
  // 未保存的空白页没有来源内容可裁切，全部裁切只作用于来源页。
  const survivors = pdfPageState(pages, snapshot).filter(page => !page.blank)
  let result = snapshot
  for (const page of survivors) {
    const viewport = await getViewport(page)
    const rect = pdfCropFromMargins(viewport, page.cropBox, selection)
    result = cropPdfPage(pages, result, page.pageId, rect)
  }
  return result
}

export function pdfCropFromMargins(viewport: PdfViewportInverse, box: PdfBox, margins: number[]): PdfRect {
  if (margins.length !== 4 || !margins.every(value => Number.isFinite(value) && value >= 0 && value < 100)) throw new Error('裁切边距须为 0–100% 之间的数值')
  const [left, top, right, bottom] = margins
  if (left + right >= 100 || top + bottom >= 100) throw new Error('裁切边距不能覆盖整个页面')
  const bounds = { left: 0, top: 0, width: viewport.width, height: viewport.height }
  return validatedPdfCrop(pdfRectFromClient(viewport, bounds, [viewport.width * left / 100, viewport.height * top / 100], [viewport.width * (1 - right / 100), viewport.height * (1 - bottom / 100)], box), box)
}

export function pdfPrintPages(pages: PdfPageIdentity[], operations: NativeOperation[]): PdfPageIdentity[] {
  return pdfPageState(pages, operations)
}

export function pdfCanPrint(state: { loaded: boolean; locked: boolean; dirty: boolean; previewing: boolean; printing: boolean; previewDocument: boolean }): boolean {
  return state.loaded && !state.locked && !state.dirty && !state.previewing && !state.printing && !state.previewDocument
}

export async function renderPdfPrintHost(root: HTMLElement, pages: PdfPageIdentity[], getPage: (sourceIndex: number) => Promise<PDFPageProxy>, annotationMode: number, pixelLimit: number) {
  const host = root.ownerDocument.createElement('div')
  host.className = 'pdf-print-document'
  root.append(host)
  try {
    for (const [index, identity] of pages.entries()) {
      const page = await getPage(identity.index)
      const viewport = page.getViewport({ scale: 1, rotation: identity.rotation })
      const dpr = Math.min(1.5, Math.sqrt(pixelLimit / (viewport.width * viewport.height)))
      const canvas = root.ownerDocument.createElement('canvas')
      canvas.width = Math.max(1, Math.floor(viewport.width * dpr)); canvas.height = Math.max(1, Math.floor(viewport.height * dpr))
      canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`
      const sheet = root.ownerDocument.createElement('section')
      sheet.className = 'pdf-print-page'; sheet.setAttribute('aria-label', `第 ${index + 1} 页`)
      sheet.append(canvas); host.append(sheet)
      await page.render({ canvas, viewport, annotationMode, transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0] }).promise
    }
    return { host, print: (start: () => void) => start(), cleanup: () => host.remove() }
  } catch (error) {
    host.remove()
    throw error
  }
}

/** 结构变更在写入草稿前完整校验（例如已设置水印/页眉页脚时拒绝重排或删页）。 */
function validated(pages: PdfPageIdentity[], operations: NativeOperation[]): NativeOperation[] {
  pdfPageState(pages, operations)
  return operations
}
function withOrder(operations: NativeOperation[], pageIds: string[]): NativeOperation[] {
  return [...operations.filter(operation => operation.kind !== 'reorderPages'), { kind: 'reorderPages', pageIds }]
}
export function movePdfPage(pages: PdfPageIdentity[], operations: NativeOperation[], pageId: string, direction: -1 | 1): NativeOperation[] {
  const order = pdfPageState(pages, operations).map(page => page.pageId)
  const index = order.indexOf(pageId), destination = index + direction
  if (index < 0 || destination < 0 || destination >= order.length) return structuredClone(operations)
  ;[order[index], order[destination]] = [order[destination], order[index]]
  return validated(pages, withOrder(operations, order))
}
export function reversePdfPages(pages: PdfPageIdentity[], operations: NativeOperation[]): NativeOperation[] {
  const order = pdfPageState(pages, operations).map(page => page.pageId)
  if (order.length <= 1) return structuredClone(operations)
  return validated(pages, withOrder(operations, order.reverse()))
}
/** Pinned source rotateAllPages(90): one draft action over surviving source IDs. */
export function rotateAllPdfPages(pages: PdfPageIdentity[], operations: NativeOperation[]): NativeOperation[] {
  const survivors = pdfPageState(pages, operations)
  if (operations.length + survivors.length > 500) throw new Error('旋转全部页面将超过 500 条修改；请先保存当前修改或减少页面后重开')
  return [...structuredClone(operations), ...survivors.map(page => ({ kind: 'rotatePage', pageId: page.pageId, delta: 90 }))]
}
export function deletePdfPage(pages: PdfPageIdentity[], operations: NativeOperation[], pageId: string): NativeOperation[] {
  const order = pdfPageState(pages, operations).map(page => page.pageId)
  if (!order.includes(pageId)) throw new Error('页面不存在')
  if (order.length === 1) throw new Error('不能删除全部页面')
  // 删除同时丢弃该页未保存的标注/旋转；撤销会恢复完整前一个操作快照。
  // 未保存的空白页没有来源页：删除即撤回插入本身，不产生 deletePage。
  const kept = operations.filter(operation => operation.pageId !== pageId)
  return validated(pages, withOrder(isPdfBlankPageId(pageId) ? kept : [...kept, { kind: 'deletePage', pageId }], order.filter(id => id !== pageId)))
}

/**
 * 固定源 insertBlankPage：在当前页之后插入一张与当前页显示尺寸相同的空白页（无当前页时为 A4），
 * 作为待保存修改立即可见、可移动、可撤销，保存时由引擎 blankPages 写入。
 * 空白页只有本地草稿身份，保存重开前不接受标注、裁切、改字等需要来源身份的修改。
 */
export const PDF_A4_POINTS = { width: 595.28, height: 841.89 } as const
export const PDF_BLANK_PAGE_EDIT_REASON = '新插入的空白页只能旋转、移动或删除；请先保存并重新打开后再编辑其内容'
const BLANK_ID = /^blank:[a-z0-9-]{1,64}$/
export function isPdfBlankPageId(pageId: unknown): pageId is string { return typeof pageId === 'string' && BLANK_ID.test(pageId) }
export function pdfBlankPageIdentity(operation: NativeOperation, index: number): PdfPageIdentity {
  const { pageId, width, height } = operation as { pageId?: unknown; width?: unknown; height?: unknown }
  if (Object.keys(operation).some(key => !['kind', 'pageId', 'width', 'height', 'sourceSha256'].includes(key)) || !isPdfBlankPageId(pageId) || ![width, height].every(value => typeof value === 'number' && Number.isFinite(value) && value >= 1 && value <= 14400)) throw new Error('空白页尺寸或身份无效')
  const box = { x: 0, y: 0, width: width as number, height: height as number }
  return { pageId, index, blank: true, mediaBox: box, cropBox: { ...box }, rotation: 0, textObjects: [], markups: [], markupReadSafe: false, notes: [], notesReadSafe: false }
}
export function insertBlankPdfPage(pages: PdfPageIdentity[], operations: NativeOperation[], afterPageId: string | null, newId: () => string = () => crypto.randomUUID()): NativeOperation[] {
  const current = pdfPageState(pages, operations)
  if (operations.length + 2 > 500) throw new Error('插入空白页将超过 500 条修改；请先保存当前修改')
  const at = afterPageId === null ? -1 : current.findIndex(page => page.pageId === afterPageId)
  if (afterPageId !== null && at < 0) throw new Error('页面不存在')
  const neighbor = current[Math.max(0, at)]
  const quarter = neighbor ? neighbor.rotation % 180 !== 0 : false
  const size = neighbor ? { width: quarter ? neighbor.cropBox.height : neighbor.cropBox.width, height: quarter ? neighbor.cropBox.width : neighbor.cropBox.height } : PDF_A4_POINTS
  const pageId = `blank:${newId().toLowerCase()}`
  if (!isPdfBlankPageId(pageId)) throw new Error('空白页身份无效')
  const order = current.map(page => page.pageId)
  order.splice(at + 1, 0, pageId)
  const width = Math.round(Math.min(14400, Math.max(1, size.width)) * 100) / 100, height = Math.round(Math.min(14400, Math.max(1, size.height)) * 100) / 100
  const next = withOrder([...structuredClone(operations), { kind: 'insertBlankPage', pageId, width, height }], order)
  pdfPageState(pages, next)
  return next
}

/** 最小单页 PDF（仅 MediaBox），供 PDF.js 渲染草稿空白页；不参与保存，保存由引擎生成实际页面。 */
export function blankPdfBytes(width: number, height: number): Uint8Array {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] /Resources << >> >>`]
  let body = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((object, index) => { offsets.push(body.length); body += `${index + 1} 0 obj\n${object}\nendobj\n` })
  const xref = body.length
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return new TextEncoder().encode(body)
}

/** 使用 PDF.js 的逆变换处理 CropBox、UserUnit、旋转和缩放，避免再次实现页面变换。 */
export function pdfRectFromClient(viewport: PdfViewportInverse, bounds: { left: number; top: number; width: number; height: number }, start: readonly number[], end: readonly number[], crop: PdfBox): PdfRect {
  if (!(bounds.width > 0 && bounds.height > 0)) throw new Error('页面范围无效')
  const point = (value: readonly number[]) => viewport.convertToPdfPoint((value[0] - bounds.left) * viewport.width / bounds.width, (value[1] - bounds.top) * viewport.height / bounds.height)
  const first = point(start), second = point(end)
  const result: PdfRect = [Math.max(crop.x, Math.min(first[0], second[0])), Math.max(crop.y, Math.min(first[1], second[1])), Math.min(crop.x + crop.width, Math.max(first[0], second[0])), Math.min(crop.y + crop.height, Math.max(first[1], second[1]))]
  if (!result.every(Number.isFinite) || result[2] - result[0] < .5 || result[3] - result[1] < .5) throw new Error('请选择页面内的有效范围')
  return result
}
export function stickyNoteRect(point: readonly number[], crop: PdfBox): PdfRect {
  if (crop.width < 20 || crop.height < 18 || !point.every(Number.isFinite)) throw new Error('该页面无法放置文字批注')
  const x = Math.max(crop.x, Math.min(crop.x + crop.width - 20, point[0]))
  const y = Math.max(crop.y + 18, Math.min(crop.y + crop.height, point[1]))
  return [x, y - 18, x + 20, y]
}

export interface PdfTextObject { objectId: string; text: string; rect: PdfRect; expectedTextSha256: string; fontSize: number; fontName: string; fontSha256: string | null }

/** Confirmation belongs to one complete operation snapshot and never survives undo via a changed draft. */
export class PdfPreviewReview {
  private snapshot?: string
  private digest?: string
  private checked = false
  reset() { this.snapshot = undefined; this.digest = undefined; this.checked = false }
  invalidate(operations: NativeOperation[]) { if (this.snapshot !== JSON.stringify(operations)) this.reset() }
  stage(operations: NativeOperation[], digest: string) {
    if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error('PDF 预览摘要无效')
    this.snapshot = JSON.stringify(operations); this.digest = digest; this.checked = false
  }
  isPrepared(operations: NativeOperation[]) { this.invalidate(operations); return !!this.digest }
  confirm(operations: NativeOperation[], checked: boolean) {
    if (!this.isPrepared(operations)) throw new Error('请先生成当前草稿的实际 PDF 预览')
    this.checked = checked
  }
  confirmedDigest(operations: NativeOperation[]): string | undefined {
    return this.isPrepared(operations) && this.checked ? this.digest : undefined
  }
}

/** Calibration is session-only; each saved Line carries its own immutable label. */
export function pdfMeasurementOperation(pageId: string, points: number[][], box: PdfBox, color: [number, number, number], scale: MeasureScale): NativeOperation {
  if (!Number.isFinite(scale.unitsPerPt) || scale.unitsPerPt <= 0 || !/^[\x20-\x7e]{1,12}$/.test(scale.unit) || !scale.unit.trim()) throw new Error('标定比例无效；单位请使用 m、cm、mm、ft、in 等 ASCII 字符')
  const line = pdfDrawingOperation(pageId, 'arrow', points, box, color)
  const from = line.from as number[], to = line.to as number[]
  const length = Math.hypot(to[0]! - from[0]!, to[1]! - from[1]!) / scale.unitsPerPt
  if (!Number.isFinite(length) || length >= 1e21) throw new Error('测量结果超出范围')
  return pdfDrawingOperation(pageId, 'measure', [from, to], box, color, { label: formatLength(Math.hypot(to[0]! - from[0]!, to[1]! - from[1]!), scale) })
}
