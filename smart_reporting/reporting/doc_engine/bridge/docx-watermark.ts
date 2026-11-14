/**
 * 固定源 Design ▸ Watermark（ribbon-design-tab.tsx onWatermark → 保存时 SaveOptions.watermark）：
 * 预设文字、“自定义水印…”文字设置（字体/字号/粗斜体/透明度/颜色/水平或斜式）与“删除水印”。
 * 引擎把水印写进每个生效节的页眉（必要时新建页眉部件）；原生桥接按全部页眉部件的摘要绑定来源，
 * 整批先验后写，写后独立回读页眉、媒体关系、图片字节与显示尺寸。
 */
import { createHash } from 'node:crypto'
import { imageSizeFromBytes } from '../../slides_engine/packages/pptx-render/src/image-dpi.ts'
import type JSZip from 'jszip'
import { parseRels, resolveRelationshipTargetPath } from '../packages/docx-engine/src/parse-package.ts'
import { pictureWatermarkBoxPt, readPictureWatermark, readWatermarkShape, readWatermarkText, type PictureWatermarkSpec, type WatermarkSpec } from '../packages/docx-engine/src/watermark.ts'

export interface DocxWatermarkModel {
  /** 来源页眉中的文字水印（各页眉一致时）；无则 null */
  text: string | null
  /** 来源文字水印的样式（固定源 textFromDocImage：字体、颜色、不透明度、斜式、粗斜体；字号保持“自动”）；无文字水印时 null */
  style: Omit<WatermarkSpec, 'text' | 'sizePt' | 'boxPt'> | null
  /** 来源含图片水印 */
  picture: boolean
  pictureSpec?: PictureWatermarkSpec | null
  /** 各页眉水印不一致（设置或删除会统一为同一水印） */
  mixed: boolean
  editable: boolean
  readOnlyReason: string | null
  /** 全部页眉部件（按路径排序的 路径 + 内容）的 SHA-256 */
  expectedHeadersSha256: string
}

export interface DocxWatermarkOperation { kind: 'setWatermark'; expectedHeadersSha256: string; watermark: WatermarkSpec | PictureWatermarkSpec | null }

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

export async function inspectDocxWatermark(zip: JSZip, protectedSource: boolean, marginBox: { widthPt: number; heightPt: number } | null = null): Promise<DocxWatermarkModel> {
  const parts = await readDocxHeaderParts(zip)
  const expectedHeadersSha256 = sha256(JSON.stringify(parts))
  const pictures = await Promise.all(parts.map(async ([path, xml]) => readWatermarkPicture(zip, path, xml)))
  const marks = parts.map(([, xml], index) => readPictureWatermark(xml) ? `picture:${JSON.stringify(pictures[index])}` : readWatermarkText(xml))
  const present = marks.filter((mark): mark is string => mark !== null)
  const picture = present.some(mark => mark.startsWith('picture:'))
  let pictureSpec: PictureWatermarkSpec | null = null
  for (const value of pictures) {
    if (!value) continue
    const { image, ...info } = value
    const scale = Math.round(info.widthPt / (image.widthPx * .75) * 100)
    const auto = pictureWatermarkBoxPt({ image }, marginBox)
    const isAuto = Math.abs(auto.widthPt - info.widthPt) < .02 && Math.abs(auto.heightPt - info.heightPt) < .02
    pictureSpec = { image, ...(!isAuto && scale > 0 ? { scale } : {}), washout: info.washout }
    break
  }
  const texts = [...new Set(present.filter(mark => !mark.startsWith('picture:')))]
  const mixed = new Set(marks).size > 1 && present.length > 0
  const text = !picture && texts.length === 1 ? texts[0]! : null
  const shape = text === null ? null : readWatermarkShape(parts.find(([, xml]) => readWatermarkText(xml) === text)![1])
  const art = shape?.wordArt
  const style = art ? { ...(art.fontFamily ? { fontFamily: art.fontFamily } : {}), colorHex: art.colorHex.toUpperCase(), opacity: Math.round(art.opacity * 100) / 100,
    diagonal: (shape!.rotationDeg ?? 0) !== 0, ...(art.bold ? { bold: true } : {}), ...(art.italic ? { italic: true } : {}) } : null
  if (protectedSource) return { text, style, picture, ...(pictureSpec ? { pictureSpec } : {}), mixed, editable: false, readOnlyReason: '文档受保护，水印保持原样', expectedHeadersSha256 }
  return { text, style, picture, ...(pictureSpec ? { pictureSpec } : {}), mixed, editable: true, readOnlyReason: null, expectedHeadersSha256 }
}

async function readWatermarkPicture(zip: JSZip, path: string, xml: string) {
  const info = readPictureWatermark(xml)
  if (!info) return null
  const rels = await parseRels(zip, path.replace(/([^/]+)$/, '_rels/$1.rels'))
  const rel = rels.get(info.rId), target = rel && rel.targetMode !== 'External' ? resolveRelationshipTargetPath(path, rel.target) : null
  const bytes = target ? await zip.file(target)?.async('uint8array') : undefined
  const image = bytes ? watermarkImage(bytes) : null
  return image ? { image, widthPt: info.widthPt, heightPt: info.heightPt, washout: info.washout } : null
}

/** 从实际输出的页眉关系独立读取图片，防止仅写入形状却媒体丢失、替换或尺寸错误。 */
export async function assertDocxPictureWatermarkWritten(zip: JSZip, spec: PictureWatermarkSpec, marginBox: { widthPt: number; heightPt: number } | null): Promise<void> {
  const parts = await readDocxHeaderParts(zip), box = pictureWatermarkBoxPt(spec, marginBox)
  const actual = await Promise.all(parts.map(([path, xml]) => readWatermarkPicture(zip, path, xml)))
  if (!actual.length || actual.some(value => !value || value.image.base64 !== spec.image.base64 || value.image.mime !== spec.image.mime
    || value.image.widthPx !== spec.image.widthPx || value.image.heightPx !== spec.image.heightPx
    || value.washout !== (spec.washout !== false) || Math.abs(value.widthPt - box.widthPt) > .02 || Math.abs(value.heightPt - box.heightPt) > .02)) throw new Error('docx_watermark_picture_write_not_applied')
}

const KEYS = ['bold', 'boxPt', 'colorHex', 'diagonal', 'fontFamily', 'italic', 'opacity', 'sizePt', 'text']
/** 整批先验：至多一条；来源可编辑、页眉摘要一致；文字水印字段与固定源对话框取值范围一致。返回要写入的值（undefined = 不写）。 */
export function validateDocxWatermarkOperations(operations: Record<string, unknown>[], model: DocxWatermarkModel): WatermarkSpec | PictureWatermarkSpec | null | undefined {
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
  if (spec && typeof spec === 'object' && 'image' in spec) {
    if (Object.keys(spec).some(key => !['image', 'scale', 'washout'].includes(key)) || !validWatermarkPicture(spec.image)
      || spec.scale !== undefined && (typeof spec.scale !== 'number' || !Number.isInteger(spec.scale) || spec.scale < 1 || spec.scale > 10000)
      || spec.washout !== undefined && typeof spec.washout !== 'boolean') throw new Error('docx_watermark_operation_invalid')
    return spec as unknown as PictureWatermarkSpec
  }
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
export function assertDocxWatermarkWritten(before: [string, string][], after: [string, string][], watermark: WatermarkSpec | PictureWatermarkSpec | null): void {
  const source = new Map(before)
  const changed = after.filter(([path, xml]) => source.get(path) !== xml)
  const ok = changed.length > 0 && changed.every(([, xml]) => watermark === null
    ? readWatermarkText(xml) === null && readPictureWatermark(xml) === null
    : 'image' in watermark ? (() => { const actual = readPictureWatermark(xml); return !!actual && actual.washout === (watermark.washout !== false) && readWatermarkText(xml) === null })()
    : readWatermarkText(xml) === watermark.text && readPictureWatermark(xml) === null)
  if (!ok) throw new Error('docx_watermark_write_not_applied')
}

/** 复用既有PNG/JPEG尺寸读取；GIF取规范逻辑屏幕尺寸，严格字节身份。 */
function watermarkImage(bytes: Uint8Array): PictureWatermarkSpec['image'] | null {
  const b = Buffer.from(bytes), gif = b.length >= 10 && ['GIF87a', 'GIF89a'].includes(b.subarray(0, 6).toString())
  const mime = gif ? 'image/gif' : b.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])) ? 'image/png' : b[0] === 255 && b[1] === 216 ? 'image/jpeg' : null
  const size = gif ? { w: b.readUInt16LE(6), h: b.readUInt16LE(8) } : imageSizeFromBytes(b)
  return mime && size && size.w > 0 && size.h > 0 && size.w <= 10000 && size.h <= 10000 && b.length <= 8 * 1024 * 1024 ? { base64: b.toString('base64'), mime, widthPx: size.w, heightPx: size.h } : null
}
function validWatermarkPicture(value: unknown): value is PictureWatermarkSpec['image'] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const image = value as Record<string, unknown>
  if (Object.keys(image).sort().join() !== 'base64,heightPx,mime,widthPx' || typeof image.base64 !== 'string' || !image.base64.length || image.base64.length > 11 * 1024 * 1024) return false
  const bytes = Buffer.from(image.base64, 'base64'), actual = watermarkImage(bytes)
  return !!actual && actual.base64 === image.base64 && actual.mime === image.mime && actual.widthPx === image.widthPx && actual.heightPx === image.heightPx
}
