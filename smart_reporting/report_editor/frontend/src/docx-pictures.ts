import type { DocxAnchor, DocxPmNode } from './docx-operations'
import { pastedDocxImage } from './docx-operations'
import type { NativeOperation } from './native-draft'

export interface DocxPictureAnchor { imageEditable?: boolean; imageReadOnlyReason?: string | null; imageSha256?: string | null }
const pictureAttrs = ['imageDataUrl', 'imageWidthPx', 'imageHeightPx', 'imageCrop', 'imageFillRect', 'imageReplace']
/** 原生图片草稿保留来源身份；裁切/去背景均已由完整源组件烘焙为位图。 */
export function projectDocxPicture(source: DocxPmNode, anchor: DocxAnchor, op: NativeOperation): DocxPmNode {
  if (!anchor.imageEditable || source.type !== 'docProtected' || source.attrs?.blockType !== 'image'
    || op.blockId !== anchor.blockId || op.expectedObjectSha256 !== anchor.expectedObjectSha256 || op.expectedImageSha256 !== anchor.imageSha256
    || Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'expectedImageSha256', 'image'].includes(key))) throw new Error('图片草稿来源身份或字段无效')
  const image = picturePayload(op.image)
  const widthPx = Math.round(Number(source.attrs.imageWidthPx)), heightPx = Math.max(1, Math.round(widthPx * image.heightPx / image.widthPx))
  if (!Number.isInteger(widthPx) || widthPx < 1 || widthPx > 10000 || heightPx > 10000) throw new Error('图片显示尺寸超出可保存范围')
  return { ...structuredClone(source), attrs: { ...source.attrs, imageDataUrl: 'data:' + image.mime + ';base64,' + image.base64,
    imageWidthPx: widthPx, imageHeightPx: heightPx, imageCrop: null, imageFillRect: null, imageReplace: image } }
}

export function normalizeDocxPictures(baseline: DocxPmNode, current: DocxPmNode, anchors: DocxAnchor[]) {
  const result = structuredClone(current), operations: NativeOperation[] = []
  for (const node of result.content ?? []) {
    if (node.type !== 'docProtected' || node.attrs?.blockType !== 'image' || node.attrs.docxIndex == null || !node.attrs.imageReplace) continue
    const anchor = anchors.find(item => item.docxIndex === node.attrs!.docxIndex), original = baseline.content?.find(item => item.attrs?.docxIndex === node.attrs!.docxIndex)
    if (!anchor || !original) throw new Error('图片来源已变化，请重新打开图片工具')
    const operation = { kind: 'replaceImage', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256,
      expectedImageSha256: anchor.imageSha256, image: node.attrs.imageReplace }
    const projected = projectDocxPicture(original, anchor, operation)
    if (pictureAttrs.some(key => JSON.stringify(node.attrs?.[key]) !== JSON.stringify(projected.attrs?.[key]))) throw new Error('图片预览与原生草稿不一致')
    for (const key of pictureAttrs) {
      if (Object.hasOwn(original.attrs!, key)) node.attrs[key] = original.attrs![key]
      else delete node.attrs[key]
    }
    operations.push(operation)
  }
  return { current: result, operations }
}

export function picturePayload(value: unknown) {
  const image = value as { mime: string; base64: string; widthPx: number; heightPx: number }
  if (image?.mime !== 'image/gif') return pastedDocxImage({ type: 'docProtected', attrs: { blockType: 'image', genImage: value } })!
  // 复用粘贴边界校验，GIF只用于固定源的既有图片替换。服务端另核验真实魔数与尺寸。
  pastedDocxImage({ type: 'docProtected', attrs: { blockType: 'image', genImage: { ...image, mime: 'image/png' } } })
  return image
}

/** 固定源尚未保存的genImage直接更新载荷，继续走既有insertParagraphImage。 */
export function projectPendingDocxPicture(source: DocxPmNode, value: unknown): DocxPmNode {
  if (source.type !== 'docProtected' || source.attrs?.blockType !== 'image' || source.attrs.docxIndex != null || !source.attrs.genImage) throw new Error('新增图片来源无效')
  pastedDocxImage(source)
  const image = picturePayload(value), widthPx = Math.max(1, Math.round(Number(source.attrs.imageWidthPx) || Math.min(image.widthPx, 620)))
  const heightPx = Math.max(1, Math.round(widthPx * image.heightPx / image.widthPx))
  const genImage = { ...image, widthPx, heightPx }
  pastedDocxImage({ type: 'docProtected', attrs: { blockType: 'image', genImage } })
  return { ...structuredClone(source), attrs: { ...source.attrs, imageDataUrl: 'data:' + image.mime + ';base64,' + image.base64,
    imageWidthPx: widthPx, imageHeightPx: heightPx, imageCrop: null, imageFillRect: null, imageReplace: null, genImage } }
}
