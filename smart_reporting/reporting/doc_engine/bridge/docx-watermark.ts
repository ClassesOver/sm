/**
 * 固定源 Design ▸ Watermark（ribbon-design-tab.tsx onWatermark → 保存时 SaveOptions.watermark）：
 * 预设文字、“自定义水印…”文字设置（字体/字号/粗斜体/透明度/颜色/水平或斜式）与“删除水印”。
 * 引擎把水印写进每个生效节的页眉（必要时新建页眉部件）；原生桥接按全部页眉部件的摘要绑定来源，
 * 整批先验后写，写后独立回读每个被改动的页眉部件。图片水印本轮不接入。
 */
import { createHash } from 'node:crypto'
import type JSZip from 'jszip'
import { parseRels, resolveRelationshipTargetPath } from '../packages/docx-engine/src/parse-package.ts'
import { readPictureWatermark, readWatermarkShape, readWatermarkText, type WatermarkSpec } from '../packages/docx-engine/src/watermark.ts'

export interface DocxWatermarkModel {
  /** 来源页眉中的文字水印（各页眉一致时）；无则 null */
  text: string | null
  /** 来源文字水印的样式（固定源 textFromDocImage：字体、颜色、不透明度、斜式、粗斜体；字号保持“自动”）；无文字水印时 null */
  style: Omit<WatermarkSpec, 'text' | 'sizePt' | 'boxPt'> | null
  /** 来源含图片水印 */
  picture: boolean
  /** 各页眉水印不一致（设置或删除会统一为同一水印） */
  mixed: boolean
  editable: boolean
  readOnlyReason: string | null
  /** 全部页眉部件（按路径排序的 路径 + 内容）的 SHA-256 */
  expectedHeadersSha256: string
}

export interface DocxWatermarkOperation { kind: 'setWatermark'; expectedHeadersSha256: string; watermark: WatermarkSpec | null }

/** 固定源 WatermarkDialog 的字号档位（“自动”= 不传 sizePt/boxPt）。 */
export const WATERMARK_SIZES = [36, 40, 44, 48, 54, 60, 66, 72, 80, 90, 96, 105, 120, 144]
const HEX = /^[0-9A-F]{6}$/
const sha256 = (value: string) => createHash('sha256').update(value).digest('hex')

/** 主文档关系里的全部页眉部件（路径 → XML），按路径排序。 */
export async function readDocxHeaderParts(zip: JSZip): Promise<[string, string][]> {
  const rels = await parseRels(zip, 'word/_rels/document.xml.rels')
  const paths = new Set<string>()
  for (const rel of rels.values()) {
    if (!/\/header$/.test(rel.type) || rel.targetMode === 'External') continue
    const path = resolveRelationshipTargetPath('word/document.xml', rel.target)
    if (path && zip.file(path)) paths.add(path)
  }
  return Promise.all([...paths].sort().map(async path => [path, await zip.file(path)!.async('string')] as [string, string]))
}

export async function inspectDocxWatermark(zip: JSZip, protectedSource: boolean): Promise<DocxWatermarkModel> {
  const parts = await readDocxHeaderParts(zip)
  const expectedHeadersSha256 = sha256(JSON.stringify(parts))
  const marks = parts.map(([, xml]) => readPictureWatermark(xml) ? 'picture' : readWatermarkText(xml))
  const present = marks.filter((mark): mark is string => mark !== null)
  const picture = present.includes('picture')
  const texts = [...new Set(present.filter(mark => mark !== 'picture'))]
  const mixed = new Set(marks).size > 1 && present.length > 0
  const text = !picture && texts.length === 1 ? texts[0]! : null
  const shape = text === null ? null : readWatermarkShape(parts.find(([, xml]) => readWatermarkText(xml) === text)![1])
  const art = shape?.wordArt
  const style = art ? { ...(art.fontFamily ? { fontFamily: art.fontFamily } : {}), colorHex: art.colorHex.toUpperCase(), opacity: Math.round(art.opacity * 100) / 100,
    diagonal: (shape!.rotationDeg ?? 0) !== 0, ...(art.bold ? { bold: true } : {}), ...(art.italic ? { italic: true } : {}) } : null
  if (protectedSource) return { text, style, picture, mixed, editable: false, readOnlyReason: '文档受保护，水印保持原样', expectedHeadersSha256 }
  return { text, style, picture, mixed, editable: true, readOnlyReason: null, expectedHeadersSha256 }
}

const KEYS = ['bold', 'boxPt', 'colorHex', 'diagonal', 'fontFamily', 'italic', 'opacity', 'sizePt', 'text']
/** 整批先验：至多一条；来源可编辑、页眉摘要一致；文字水印字段与固定源对话框取值范围一致。返回要写入的值（undefined = 不写）。 */
export function validateDocxWatermarkOperations(operations: Record<string, unknown>[], model: DocxWatermarkModel): WatermarkSpec | null | undefined {
  if (!operations.length) return undefined
  if (operations.length !== 1) throw new Error('docx_watermark_batch_conflict')
  const op = operations[0]!
  if (Object.keys(op).sort().join() !== 'expectedHeadersSha256,kind,watermark' || op.kind !== 'setWatermark') throw new Error('docx_watermark_operation_invalid')
  if (!model.editable) throw new Error('docx_watermark_source_unsupported')
  if (op.expectedHeadersSha256 !== model.expectedHeadersSha256) throw new Error('docx_watermark_anchor_invalid')
  if (op.watermark === null) {
    if (model.text === null && !model.picture) throw new Error('docx_watermark_unchanged')
    return null
  }
  const spec = op.watermark as Record<string, unknown>
  if (!spec || typeof spec !== 'object' || Array.isArray(spec) || Object.keys(spec).some(key => !KEYS.includes(key))
    || typeof spec.text !== 'string' || !spec.text.trim() || spec.text !== spec.text.trim() || spec.text.length > 255 || /[\u0000-\u001f\u007f]/.test(spec.text)
    || (spec.fontFamily !== undefined && (typeof spec.fontFamily !== 'string' || !spec.fontFamily.trim() || spec.fontFamily.length > 100 || /[\u0000-\u001f"<>&]/.test(spec.fontFamily)))
    || (spec.colorHex !== undefined && (typeof spec.colorHex !== 'string' || !HEX.test(spec.colorHex)))
    || (spec.opacity !== undefined && (typeof spec.opacity !== 'number' || !Number.isFinite(spec.opacity) || spec.opacity < 0 || spec.opacity > 1 || Math.abs(Math.round(spec.opacity * 100) - spec.opacity * 100) > 1e-9))
    || [spec.diagonal, spec.bold, spec.italic].some(value => value !== undefined && typeof value !== 'boolean')
    || (spec.sizePt === undefined) !== (spec.boxPt === undefined)
    || (spec.sizePt !== undefined && !WATERMARK_SIZES.includes(spec.sizePt as number))
    || (spec.boxPt !== undefined && (!spec.boxPt || typeof spec.boxPt !== 'object' || Object.keys(spec.boxPt).sort().join() !== 'heightPt,widthPt'
      || ![(spec.boxPt as Record<string, unknown>).widthPt, (spec.boxPt as Record<string, unknown>).heightPt].every(value => typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= 2000)))) {
    throw new Error('docx_watermark_operation_invalid')
  }
  return spec as unknown as WatermarkSpec
}

/** 写后独立回读：每个内容变化或新增的页眉部件都恰好带请求的文字水印（删除时不再带任何水印），且至少改动一个页眉。 */
export function assertDocxWatermarkWritten(before: [string, string][], after: [string, string][], watermark: WatermarkSpec | null): void {
  const source = new Map(before)
  const changed = after.filter(([path, xml]) => source.get(path) !== xml)
  const ok = changed.length > 0 && changed.every(([, xml]) => watermark === null
    ? readWatermarkText(xml) === null && readPictureWatermark(xml) === null
    : readWatermarkText(xml) === watermark.text && readPictureWatermark(xml) === null)
  if (!ok) throw new Error('docx_watermark_write_not_applied')
}
