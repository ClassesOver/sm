import { describe, expect, it } from 'vitest'
import { choosePdfSignatureFieldTarget, pngSize, signatureDataFromDialog, signatureDrawingForField, validatePdfSignatureFieldBindings, type PdfSignatureField } from './pdf-signature-field'
import { pdfPageState, type PdfPageIdentity } from './pdf-operations'

const field: PdfSignatureField = { fieldId: 'a'.repeat(64), expectedFieldSha256: 'b'.repeat(64), name: '甲方签字', signed: false, visuallySigned: false, widgets: [{ pageIndex: 0, rect: [40, 60, 240, 120] }], bindable: true, reason: null }
const box = { x: 0, y: 0, width: 400, height: 500 }
const pages: PdfPageIdentity[] = [{ pageId: 'p1', index: 0, mediaBox: box, cropBox: box, rotation: 0 }]
const color: [number, number, number] = [0.15, 0.15, 0.15]

describe('PDF visual signature into a signature field (pinned signatureDrawingForField)', () => {
  it('fits a handwritten signature with an 8% inset, centred, y flipped into PDF space', () => {
    const operation = signatureDrawingForField({ kind: 'ink', width: 480, height: 160, paths: [[0, 0, 480, 160]] }, field, 'p1', color)
    // field 200×60, inset 4.8 → avail 190.4×50.4, k = min(190.4/480, 50.4/160) = 0.315 → 151.2×50.4 centred
    expect(operation).toMatchObject({ kind: 'addDrawing', pageId: 'p1', shape: 'ink', width: 1.6, signatureField: { fieldId: field.fieldId, expectedFieldSha256: field.expectedFieldSha256 } })
    expect(operation.paths).toEqual([[64.4, 115.2, 215.6, 64.8]])
    expect(pdfPageState(pages, [operation])).toHaveLength(1)
  })

  it('fits a typed (image) signature by its PNG aspect ratio', () => {
    const png = 'iVBORw0KGgoAAAANSUhEUgAAAMgAAAAyCAYAAAAZUZThAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
    expect(pngSize(png)).toEqual({ width: 200, height: 50 })
    const operation = signatureDrawingForField({ kind: 'image', width: 200, height: 50, image: png }, field, 'p1', color)
    // k = min(190.4/200, 50.4/50) = 0.952 → 190.4×47.6 centred in the field
    expect(operation.rect).toEqual([44.8, 66.2, 235.2, 113.8])
    expect(operation.shape).toBe('image')
  })

  it('refuses unbindable fields, malformed identities and binding the same field twice', () => {
    expect(() => signatureDrawingForField({ kind: 'ink', width: 480, height: 160, paths: [] }, { ...field, bindable: false, reason: '此签名字段已有证书签名' }, 'p1', color)).toThrow('证书签名')
    const operation = signatureDrawingForField({ kind: 'ink', width: 480, height: 160, paths: [[10, 10, 400, 150]] }, field, 'p1', color)
    expect(() => validatePdfSignatureFieldBindings([operation, operation])).toThrow('只能放入一次')
    expect(() => validatePdfSignatureFieldBindings([{ ...operation, signatureField: { fieldId: 'x' } }])).toThrow('签名字段参数无效')
    expect(() => validatePdfSignatureFieldBindings([{ ...operation, shape: 'rect' }])).toThrow('签名字段参数无效')
    expect(() => pdfPageState(pages, [{ ...operation, signatureField: { ...(operation.signatureField as object), extra: 1 } }])).toThrow('签名字段参数无效')
    expect(() => pngSize('AAAA')).toThrow('PNG')
  })

  it('maps the upstream dialog data and skips the target chooser when no field is free', async () => {
    expect(signatureDataFromDialog({ kind: 'strokes', paths: [[1, 2, 3, 4]], width: 480, height: 160 })).toEqual({ kind: 'ink', width: 480, height: 160, paths: [[1, 2, 3, 4]] })
    expect(signatureDataFromDialog({ kind: 'image', image: 'iVBORw0KGgo', width: 20, height: 10 })).toEqual({ kind: 'image', width: 20, height: 10, image: 'iVBORw0KGgo' })
    await expect(choosePdfSignatureFieldTarget({} as Document, [])).resolves.toBe('')
  })
})
