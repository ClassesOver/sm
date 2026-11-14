import { createHash } from 'node:crypto'
import type { Block } from '../packages/docx-engine/src/types.ts'
import { imageSizeFromBytes } from '../../slides_engine/packages/pptx-render/src/image-dpi.ts'

const sha = (value: Uint8Array) => createHash('sha256').update(value).digest('hex')
/** 固定源PictureDialogs只编辑整块图片；组合、外链及保护来源保留只读。 */
export function inspectDocxPicture(block: Block, protectedSource: boolean) {
  if (block.type !== 'image') return {}
  const xml = block.originalXml ?? ''
  const match = /^data:image\/(?:png|jpeg|gif);base64,([A-Za-z0-9+/=]+)$/.exec(block.imageDataUrl ?? '')
  const bytes = match ? Buffer.from(match[1]!, 'base64') : undefined
  const editable = !protectedSource && !block.hidden && !!bytes?.length
    && (xml.match(/<w:drawing\b/g) ?? []).length === 1
    && (xml.match(/<a:blip\b/g) ?? []).length === 1
    && /<a:blip\b[^>]*\br:embed="[^"]+"/.test(xml)
    && !/<(?:w:(?:object|pict|ins|del)|wpg:|wps:|mc:AlternateContent)|\br:link=/.test(xml)
    && Number.isFinite(block.imageWidthPx) && Number.isFinite(block.imageHeightPx)
  return { imageEditable: editable, imageReadOnlyReason: editable ? null : '图片来源受保护或含不支持的组合、外链或格式',
    imageSha256: bytes ? sha(bytes) : null, imageWidthPx: block.imageWidthPx, imageHeightPx: block.imageHeightPx }
}

export function validatePictureDimensions(image: { base64: string; widthPx: number; heightPx: number }) {
  const bytes = Buffer.from(image.base64, 'base64')
  const size = /^GIF8[79]a$/.test(bytes.subarray(0, 6).toString('ascii')) && bytes.length >= 13 ? { w: bytes.readUInt16LE(6), h: bytes.readUInt16LE(8) } : imageSizeFromBytes(bytes)
  if (!size || size.w !== image.widthPx || size.h !== image.heightPx) throw new Error('docx_image_dimensions_invalid')
}

/** 源替换协议另支持GIF；粘贴协议仍维持原来的PNG/JPEG白名单。 */
export function gifPicture(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('docx_image_invalid')
  const image = value as Record<string, unknown>
  if (Object.keys(image).some(key => !['mime', 'base64', 'widthPx', 'heightPx'].includes(key)) || image.mime !== 'image/gif' || typeof image.base64 !== 'string' || image.base64.length > 11 * 1024 * 1024) throw new Error('docx_image_invalid')
  const bytes = Buffer.from(image.base64, 'base64')
  if (bytes.length < 13 || bytes.length > 8 * 1024 * 1024 || bytes.toString('base64') !== image.base64 || !/^GIF8[79]a$/.test(bytes.subarray(0, 6).toString('ascii'))) throw new Error('docx_image_invalid')
  for (const key of ['widthPx', 'heightPx']) if (typeof image[key] !== 'number' || !Number.isInteger(image[key]) || Number(image[key]) < 1 || Number(image[key]) > 10000) throw new Error('docx_image_dimensions_invalid')
  return { base64: image.base64, mime: 'image/gif' as const, widthPx: Number(image.widthPx), heightPx: Number(image.heightPx) }
}
