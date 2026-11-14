/**
 * 固定源 Sign ▸ 放入签名字段（renderer/signature-field.ts signatureDrawingForField + App.tsx placeSignatureInField）
 * 的桥接侧：列出 AcroForm 签名字段（/FT /Sig）的控件位置，并判断能否放入可视签名。
 * 可视签名仍写为 Ink / Stamp 批注，由固定引擎 setVisualSignatureMetadata 记录 /GenOfficeFormField 关联，
 * 不写入 /V，不是证书数字签名。
 */
import { PDFArray, PDFDict, PDFDocument, PDFHexString, PDFName, PDFRef, PDFSignature, PDFString } from 'pdf-lib'

export interface SignatureFieldWidget { pageIndex: number; rect: [number, number, number, number] }
export interface SignatureFieldModel {
  fieldId: string
  expectedFieldSha256: string
  name: string
  /** 已有 /V（证书签名）——写任何内容都会使其失效，只读 */
  signed: boolean
  /** 已有固定源可视签名（/GenOfficeFormField 指向此字段的批注） */
  visuallySigned: boolean
  widgets: SignatureFieldWidget[]
  bindable: boolean
  reason: string | null
}

const text = (value: unknown) => value instanceof PDFHexString || value instanceof PDFString ? value.decodeText() : undefined

/** 已有固定源可视签名所关联的字段名集合。 */
export function visualSignatureFieldNames(document: PDFDocument): Set<string> {
  const names = new Set<string>()
  for (const page of document.getPages()) {
    const annotations = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
    for (let index = 0; index < (annotations?.size() ?? 0); index++) {
      try {
        const name = text(annotations!.lookup(index, PDFDict).get(PDFName.of('GenOfficeFormField')))
        if (name) names.add(name)
      } catch { /* 非字典条目不参与 */ }
    }
  }
  return names
}

export function inspectSignatureFields(document: PDFDocument, formFields: { name: string; kind: string; fieldId: string; expectedFieldSha256: string }[], blocked: string | null): SignatureFieldModel[] {
  const visual = visualSignatureFieldNames(document)
  const pageOf = new Map<string, number>()
  document.getPages().forEach((page, pageIndex) => {
    const annotations = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
    for (const entry of annotations?.asArray() ?? []) if (entry instanceof PDFRef) pageOf.set(entry.toString(), pageIndex)
  })
  const fields = document.getForm().getFields()
  return formFields.filter(field => field.kind === 'signature').map(field => {
    const source = fields.find(item => item.getName() === field.name)
    const signed = source instanceof PDFSignature && source.acroField.dict.has(PDFName.of('V'))
    const widgets: SignatureFieldWidget[] = []
    let reason: string | null = blocked
    for (const widget of source instanceof PDFSignature ? source.acroField.getWidgets() : []) {
      const ref = document.context.getObjectRef(widget.dict)
      const pageIndex = ref ? pageOf.get(ref.toString()) : undefined
      const box = widget.getRectangle()
      const rect: [number, number, number, number] = [box.x, box.y, box.x + box.width, box.y + box.height]
      if (pageIndex === undefined || !rect.every(Number.isFinite) || box.width < 4 || box.height < 4) { reason ??= '签名字段控件的页面或位置无法确认'; continue }
      widgets.push({ pageIndex, rect: rect.map(value => Math.round(value * 100) / 100) as SignatureFieldWidget['rect'] })
    }
    if (source?.isReadOnly()) reason ??= '签名字段为只读，不能放入可视签名'
    if (signed) reason ??= '此签名字段已有证书签名，写入任何内容都会使其失效'
    if (visual.has(field.name)) reason ??= '此签名字段已有可视签名'
    if (widgets.length !== 1) reason ??= '仅支持只有一个控件的签名字段'
    return { fieldId: field.fieldId, expectedFieldSha256: field.expectedFieldSha256, name: field.name, signed, visuallySigned: visual.has(field.name), widgets, bindable: reason === null, reason }
  })
}
