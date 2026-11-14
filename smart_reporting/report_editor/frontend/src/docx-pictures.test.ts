import { describe, expect, it } from 'vitest'
import { normalizeDocxPictures, projectDocxPicture, projectPendingDocxPicture } from './docx-pictures'
const anchor = { docxIndex: 1, blockId: 'picture', expectedObjectSha256: 'xml', editable: false, imageEditable: true, imageSha256: 'pixels' }
const original = { type: 'doc', content: [{ type: 'docProtected', attrs: { docxIndex: 1, blockType: 'image', imageDataUrl: 'original', imageWidthPx: 192, imageHeightPx: 144 } }] }
const operation = { kind: 'replaceImage', blockId: 'picture', expectedObjectSha256: 'xml', expectedImageSha256: 'pixels', image: { base64: 'YQ==', mime: 'image/png', widthPx: 40, heightPx: 20 } }
describe('完整PictureDialogs共用原生位图草稿', () => {
  it('恢复图片预览并保留来源显示宽度，归一化只还原图片属性', () => {
    const projected = projectDocxPicture(original.content[0]!, anchor, operation)
    expect(projected.attrs).toMatchObject({ imageDataUrl: 'data:image/png;base64,YQ==', imageWidthPx: 192, imageHeightPx: 96, imageCrop: null, imageFillRect: null })
    const normalized = normalizeDocxPictures(original, { type: 'doc', content: [projected] }, [anchor])
    expect(normalized.current).toEqual(original); expect(normalized.operations).toEqual([operation])
  })
  it('拒绝迟到目标或篡改摘要', () => {
    expect(() => projectDocxPicture(original.content[0]!, anchor, { ...operation, expectedImageSha256: 'stale' })).toThrow()
    expect(() => projectDocxPicture(original.content[0]!, { ...anchor, imageEditable: false }, operation)).toThrow()
  })
})

it('源未保存genImage在原insertParagraphImage协议更新，不产生伪来源替换', () => {
  const source = { type: 'docProtected', attrs: { docxIndex: null, blockType: 'image', imageWidthPx: 160, genImage: { base64: 'YQ==', mime: 'image/png', widthPx: 160, heightPx: 120 } } }
  const projected = projectPendingDocxPicture(source, { base64: 'Yg==', mime: 'image/png', widthPx: 40, heightPx: 20 })
  expect(projected.attrs?.genImage).toEqual({ base64: 'Yg==', mime: 'image/png', widthPx: 160, heightPx: 80 })
  expect(projected.attrs?.imageReplace).toBeNull()
  expect(normalizeDocxPictures({ type: 'doc', content: [] }, { type: 'doc', content: [projected] }, []).operations).toEqual([])
})
