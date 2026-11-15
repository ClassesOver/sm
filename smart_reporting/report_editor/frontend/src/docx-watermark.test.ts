// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { DOCX_WATERMARK_PRESETS, docxWatermarkModel, docxWatermarkOperations, effectiveDocxWatermark, validDocxWatermarkSpec, withDocxWatermark, type DocxWatermarkModel } from './docx-watermark'
import { docxNativeOperations } from './docx-native-history'

const sha = 'a'.repeat(64)
const model: DocxWatermarkModel = { text: null, style: null, picture: false, mixed: false, editable: true, readOnlyReason: null, expectedHeadersSha256: sha }
afterEach(() => { document.body.replaceChildren() })

describe('Word watermark (pinned Design ▸ Watermark)', () => {
  it('parses the inspect model and keeps the pinned presets', () => {
    expect(docxWatermarkModel({ ...model, readOnlyReason: null })).toEqual(model)
    expect(docxWatermarkModel({ ...model, expectedHeadersSha256: 'x' })).toBeNull()
    expect(docxWatermarkModel(undefined)).toBeNull()
    expect(DOCX_WATERMARK_PRESETS).toEqual(['机密', '严禁复制', '草稿', '样本', 'CONFIDENTIAL', 'DRAFT'])
  })

  it('stages one document-level operation; reverting to the source withdraws it', () => {
    const others = [{ kind: 'replaceParagraph', blockId: 'b', expectedObjectSha256: sha, text: 'x' }]
    const staged = withDocxWatermark(others, model, { text: '机密' })
    expect(staged).toEqual([...others, { kind: 'setWatermark', expectedHeadersSha256: sha, watermark: { text: '机密' } }])
    expect(effectiveDocxWatermark(staged, model)).toEqual({ text: '机密' })
    expect(docxNativeOperations(staged)).toEqual([staged[1]])
    expect(withDocxWatermark(staged, model, null)).toEqual(others)
    const source = { ...model, text: '草稿' }
    expect(withDocxWatermark([], source, { text: '草稿' })).toEqual([])
    // 来源样式回读：预览与“与来源相同”判断都带样式；只按文字选同名预设会改回默认样式，不算撤回
    const styled = { ...model, text: '草稿', style: { fontFamily: 'Arial', colorHex: 'C00000', opacity: 0.3, diagonal: false } }
    expect(effectiveDocxWatermark([], styled)).toEqual({ text: '草稿', fontFamily: 'Arial', colorHex: 'C00000', opacity: 0.3, diagonal: false })
    expect(withDocxWatermark([], styled, { text: '草稿', fontFamily: 'Arial', colorHex: 'C00000', opacity: 0.3, diagonal: false })).toEqual([])
    expect(withDocxWatermark([], styled, { text: '草稿' })).toHaveLength(1)
    expect(docxWatermarkModel({ ...styled, readOnlyReason: null })?.style).toEqual(styled.style)
    expect(docxWatermarkModel({ ...styled, style: { colorHex: 'red' } })?.style).toBeNull()
    expect(withDocxWatermark([], source, { text: '草稿', bold: true })).toHaveLength(1)
    expect(withDocxWatermark([], source, null)).toEqual([{ kind: 'setWatermark', expectedHeadersSha256: sha, watermark: null }])
    expect(effectiveDocxWatermark([], source)).toEqual({ text: '草稿' })
    expect(withDocxWatermark([], { ...model, picture: true }, null)).toHaveLength(1)
  })

  it('validates drafts against the source and the pinned dialog ranges', () => {
    const op = { kind: 'setWatermark', expectedHeadersSha256: sha, watermark: { text: '机密' } }
    expect(docxWatermarkOperations([op], model)).toEqual([op])
    for (const bad of [[op, op], [{ ...op, expectedHeadersSha256: 'f'.repeat(64) }], [{ ...op, watermark: { text: '' } }], [{ ...op, watermark: null }], [{ ...op, extra: 1 }]]) {
      expect(() => docxWatermarkOperations(bad, model), JSON.stringify(bad)).toThrow('原草稿已保留')
    }
    expect(() => docxWatermarkOperations([op], { ...model, editable: false, readOnlyReason: '文档受保护，水印保持原样' })).toThrow('文档受保护')
    expect(() => docxWatermarkOperations([op], null)).toThrow('原草稿已保留')
    expect(validDocxWatermarkSpec({ text: 'x', sizePt: 72, boxPt: { widthPt: 10, heightPt: 5 } })).toBe(true)
    for (const bad of [{ text: 'x', sizePt: 72 }, { text: 'x', sizePt: 70, boxPt: { widthPt: 1, heightPt: 1 } }, { text: 'x', colorHex: 'c0c0c0' }, { text: 'x', opacity: 0.333 }, { text: 'a\nb' }, { text: 'x', fontFamily: 'a<b' }, { text: 'x', image: {} }]) {
      expect(validDocxWatermarkSpec(bad), JSON.stringify(bad)).toBe(false)
    }
    expect(() => withDocxWatermark([], { ...model, editable: false }, { text: 'x' })).toThrow()
  })

})
