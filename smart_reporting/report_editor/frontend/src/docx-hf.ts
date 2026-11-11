import { PAGE_MARK, type HeaderFooter } from '@genoffice/docx-engine'
import type { NativeOperation } from './native-draft'

/** 页眉/页脚部件编辑协议：与固定源 hf-editor/patch.ts 对齐——文本段以 '\n' 分段、
 *  PAGE/NUMPAGES 域以 PAGE_MARK 系标记承载，保存端按标记写回 fldChar 域；布局表格/
 *  浮动框段为显示专用内容，不进入文本模型（保存端外科合并保留其原字节）。 */

export type DocxHfPart = 'header' | 'footer'
export type DocxHfVariant = 'default' | 'first' | 'even'
export type DocxHfPartKey = `${DocxHfPart}.${DocxHfVariant}`
export interface DocxHfPartAnchor { rId: string | null; expectedPartSha256: string; text: string; hasPageNumber: boolean; editable: boolean }
export interface DocxHeadersFootersModel {
  titlePg: boolean
  titlePgReadOnlyReason?: string | null
  evenAndOddHeaders: boolean
  evenAndOddHeadersReadOnlyReason?: string | null
  pageNumberReadOnlyReason?: string | null
  pageNumberFmt: string | null
  pageNumberStart: number | null
  parts: Partial<Record<DocxHfPartKey, DocxHfPartAnchor>>
}
export interface DocxHfSectionAnchor { sectionId: string; expectedSectionSha256: string }
export interface DocxHfFlags { titlePg?: boolean; evenAndOddHeaders?: boolean; pageNumberFmt?: string | null; pageNumberStart?: number | null }

const HF_OP_KEYS = ['kind', 'sectionId', 'expectedSectionSha256', 'part', 'variant', 'afterLink', 'expectedPartSha256', 'text', 'pageNumber', 'align', 'titlePg', 'evenAndOddHeaders', 'pageNumberFmt', 'pageNumberStart']
const HF_VARIANTS: DocxHfVariant[] = ['default', 'first', 'even']
const HF_ALIGNMENTS = ['left', 'center', 'right']

/** 可编辑文本（简单文本段按 '\n' 连接；域标记保留为 PAGE_MARK 系字符）。 */
export function docxHfTextOf(value: HeaderFooter): string {
  return (value.paras ?? [])
    .filter(para => !para.cells && !para.row && !para.box && !para.boxAnchored)
    .map(para => (para.runs ?? []).map(run => run.text).join(''))
    .join('\n')
}

type HfAlign = 'left' | 'center' | 'right'

/** 文本段的统一对齐：全部文本段同一 left/center/right 时返回之，混合或未设置为 undefined。
 *  保存端 operation.align 会作用于部件的全部文本段，因此只承载统一对齐，避免压平混合对齐。 */
export function docxHfUniformAlign(paras: HeaderFooter['paras'] | undefined): HfAlign | undefined {
  const aligns = (paras ?? []).filter(para => !para.cells && !para.row && !para.box && !para.boxAnchored).map(para => para.align)
  const first = aligns[0]
  return aligns.length && HF_ALIGNMENTS.includes(first as string) && aligns.every(align => align === first) ? first as HfAlign : undefined
}

/** 部件编辑 → 严格操作；无实际变化（文本、标记、统一对齐均未变且无设置位）返回 null，不写草稿。
 *  force 固化新own复制快照，值与原来源相同也保留，避免后续前节编辑影响复制。
 *  sourceParas 为来源部件段落：统一对齐与来源不同（如页码位置选左/右）时随操作写回 align。 */
export function docxHeaderFooterOperation(anchor: DocxHfSectionAnchor, partAnchor: DocxHfPartAnchor, part: DocxHfPart, variant: DocxHfVariant, value: HeaderFooter, flags?: DocxHfFlags, sourceParas?: HeaderFooter['paras'], force = false): NativeOperation | null {
  const text = value.paras ? docxHfTextOf(value) : value.text
  const flagEntries = Object.entries(flags ?? {}).filter(([, flag]) => flag !== undefined)
  const valueAlign = docxHfUniformAlign(value.paras)
  const align = valueAlign !== undefined && valueAlign !== docxHfUniformAlign(sourceParas) ? valueAlign : undefined
  if (!force && text === partAnchor.text && !value.pageNumber === !partAnchor.hasPageNumber && !align && !flagEntries.length) return null
  return { kind: 'setHeaderFooter', sectionId: anchor.sectionId, expectedSectionSha256: anchor.expectedSectionSha256,
    part, variant, expectedPartSha256: partAnchor.expectedPartSha256, text, pageNumber: value.pageNumber ?? false,
    ...(align ? { align } : {}), ...Object.fromEntries(flagEntries) }
}

/** 新部件编辑并入草稿：替换同 (part, variant) 的旧操作，其余操作保持原顺序。 */
export function mergeDocxHeaderFooterOperation(operations: NativeOperation[], operation: NativeOperation): NativeOperation[] {
  return [...operations.filter(op => !(op.kind === 'setHeaderFooter' && op.sectionId === operation.sectionId && op.part === operation.part && op.variant === operation.variant)), operation]
}

/** 恢复/重放前的草稿校验：节与部件身份必须匹配当前来源，同一 (part, variant) 以后写为准。 */
export function restoredDocxHeaderFooterOperations(operations: NativeOperation[], anchor?: DocxHfSectionAnchor, model?: DocxHeadersFootersModel): NativeOperation[] {
  const kept: NativeOperation[] = []
  for (const operation of operations) {
    if (operation.kind !== 'setHeaderFooter') continue
    if (!anchor || operation.sectionId !== anchor.sectionId || operation.expectedSectionSha256 !== anchor.expectedSectionSha256) throw new Error('草稿页眉页脚设置的节身份与当前来源不一致')
    if (Object.keys(operation).some(key => !HF_OP_KEYS.includes(key))) throw new Error('草稿页眉页脚操作字段无效')
    const { part, variant } = operation as unknown as { part: unknown; variant: unknown }
    if (part !== 'header' && part !== 'footer') throw new Error('草稿页眉页脚部件无效')
    if (!HF_VARIANTS.includes(variant as DocxHfVariant)) throw new Error('草稿页眉页脚部件变体无效')
    if (typeof operation.text !== 'string' || operation.text.length > 20000 || typeof operation.pageNumber !== 'boolean'
      || typeof operation.expectedPartSha256 !== 'string') throw new Error('草稿页眉页脚文本无效')
    if (operation.afterLink !== undefined && operation.afterLink !== true) throw new Error('草稿解除链接后编辑标记无效')
    if (operation.align !== undefined && !HF_ALIGNMENTS.includes(operation.align as string)) throw new Error('草稿页眉页脚对齐无效')
    for (const key of ['titlePg', 'evenAndOddHeaders'] as const) {
      if (operation[key] !== undefined && typeof operation[key] !== 'boolean') throw new Error('草稿页眉页脚设置无效')
    }
    if (operation.titlePg !== undefined && model?.titlePgReadOnlyReason) throw new Error('草稿首页不同来源标记不可解释')
    if (operation.evenAndOddHeaders !== undefined && model?.evenAndOddHeadersReadOnlyReason) throw new Error('草稿奇偶页不同来源标记不可解释')
    if ((operation.pageNumberFmt !== undefined || operation.pageNumberStart !== undefined) && model?.pageNumberReadOnlyReason) throw new Error('草稿页码格式来源标记不可解释')
    for (const key of ['pageNumberFmt', 'pageNumberStart'] as const) {
      const value = operation[key]
      if (value !== undefined && value !== null && (typeof value !== (key === 'pageNumberFmt' ? 'string' : 'number') || key === 'pageNumberStart' && (!Number.isSafeInteger(value) || (value as number) < 0))) throw new Error('草稿页码格式无效')
    }
    const partAnchor = model?.parts[`${part}.${variant}` as DocxHfPartKey]
    if (!partAnchor || operation.expectedPartSha256 !== partAnchor.expectedPartSha256) throw new Error('草稿页眉页脚部件身份与当前来源不一致')
    // 后写覆盖先写（mergeDocxHeaderFooterOperation 追加在尾部）：同键取最后一次出现。
    const duplicate = kept.find(op => op.part === part && op.variant === variant)
    if (duplicate) kept.splice(kept.indexOf(duplicate), 1)
    kept.push(operation)
  }
  return kept
}

/** 显示用文本：PAGE_MARK 系标记换成可读占位（提交时逆向还原）。 */
const DISPLAY_MARKS: Array<[string, string]> = [['\uE001', '〖页码〗'], ['\uE000', '〖总页数〗'], ['\uE002', '〖节页数〗']]
export function docxHfDisplayText(text: string): string {
  return DISPLAY_MARKS.reduce((value, [mark, label]) => value.split(mark).join(label), text)
}
export function docxHfValueText(display: string): string {
  return DISPLAY_MARKS.reduce((value, [mark, label]) => value.split(label).join(mark), display)
}

/** 部件当前值 → 面板编辑器所需 HeaderFooter（paras 为显示专用结构的只读镜像）。 */
export function docxHfValueOf(info: { text: string; paras?: HeaderFooter['paras']; hasPageNumber?: boolean } | null | undefined): HeaderFooter {
  return { text: info?.text ?? '', ...(info?.paras ? { paras: info.paras } : {}), pageNumber: info?.hasPageNumber ?? false }
}

/** 便捷：部件是否存在页码字段或要求自动页码。 */
export const docxHfHasPageField = (value: HeaderFooter) => Boolean(value.pageNumber || value.text.includes(PAGE_MARK) || value.paras?.some(para => (para.runs ?? []).some(run => run.text.includes(PAGE_MARK))))
