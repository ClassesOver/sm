import { createHash } from 'node:crypto'
import { PDFCheckBox, PDFDocument, PDFDropdown, PDFOptionList, PDFRadioGroup, PDFSignature, PDFTextField } from 'pdf-lib'
import { z } from 'zod'
import { applySaveRequest } from '../src/main/save-pdf'
import { inspectNativeText, prepareTextEdits, textResourcesIdentity } from './text-operations'
import type { SkippedOperation } from './text-operations'
import type { SavePdfRequest } from '../src/shared/ipc'

export const sha256 = (content: Uint8Array): string => createHash('sha256').update(content).digest('hex')
const identity = { sourceSha256: z.string().regex(/^[a-f0-9]{64}$/).optional() }
const page = { ...identity, pageId: z.string().min(1) }
const color = z.tuple([z.number().min(0).max(1), z.number().min(0).max(1), z.number().min(0).max(1)])
const rect = z.tuple([z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite()])
const fieldIdentity = { fieldId: z.string().regex(/^[a-f0-9]{64}$/), expectedFieldSha256: z.string().regex(/^[a-f0-9]{64}$/), name: z.string().min(1).max(256), fieldKind: z.enum(['text', 'checkbox', 'radio', 'choice']) }
const operation = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('setFormValue'), ...fieldIdentity, value: z.string().max(4000).optional(), checked: z.boolean().optional() }).strict(),
  z.object({ kind: z.literal('replaceText'), ...page, objectId: z.string().min(1).max(256), expectedTextSha256: z.string().regex(/^[a-f0-9]{64}$/), newText: z.string().max(4000) }).strict(),
  z.object({ kind: z.literal('highlight'), ...page, rect, color: color.optional() }).strict(),
  z.object({ kind: z.literal('addTextAnnotation'), ...page, rect, text: z.string().trim().min(1).max(10000), color: color.optional() }).strict(),
  z.object({ kind: z.literal('rotatePage'), ...page, delta: z.union([z.literal(90), z.literal(180), z.literal(270)]) }).strict(),
  z.object({ kind: z.literal('deletePage'), ...page }).strict(),
  z.object({ kind: z.literal('reorderPages'), ...identity, pageIds: z.array(z.string()).min(1).max(10000) }).strict(),
])
const operationsSchema = z.array(operation).max(500)

export async function inspectPdf(content: Uint8Array, includeText = false) {
  const document = await PDFDocument.load(content, { updateMetadata: false })
  const sourceSha256 = sha256(content)
  const textPages = includeText ? await inspectNativeText(content, sourceSha256) : undefined
  const form = document.getForm()
  const formFields = form.getFields().map((field) => {
    const name = field.getName()
    let kind: 'text' | 'checkbox' | 'radio' | 'choice' | 'signature' | 'unsupported' = 'unsupported'
    let value: string | boolean | null = null
    let options: string[] | undefined
    let supported = false
    if (field instanceof PDFTextField) { kind = 'text'; value = field.getText() ?? ''; supported = !field.isPassword() && !field.isRichFormatted() && !field.isReadOnly() }
    else if (field instanceof PDFCheckBox) { kind = 'checkbox'; value = field.isChecked(); supported = !field.isReadOnly() }
    else if (field instanceof PDFRadioGroup) { kind = 'radio'; value = field.getSelected() ?? ''; options = field.getOptions(); supported = !field.isReadOnly() }
    else if (field instanceof PDFDropdown) { kind = 'choice'; value = field.getSelected()[0] ?? ''; options = field.getOptions(); supported = !field.isReadOnly() && !field.isMultiselect() && !field.isEditable() }
    else if (field instanceof PDFOptionList) { kind = 'choice'; value = field.getSelected()[0] ?? ''; options = field.getOptions() }
    else if (field instanceof PDFSignature) kind = 'signature'
    const model = { name, kind, value, ...(options ? { options } : {}), editable: supported }
    const expectedFieldSha256 = sha256(Buffer.from(JSON.stringify(model)))
    return { ...model, fieldId: sha256(Buffer.from(`${sourceSha256}:${name}:${kind}`)), expectedFieldSha256 }
  })
  const pages = document.getPages().map((page, index) => ({
    pageId: `sha256:${sourceSha256}:page:${index}`, index,
    ...(textPages ? { textObjects: textPages[index] } : {}),
    mediaBox: page.getMediaBox(), cropBox: page.getCropBox(), rotation: page.getRotation().angle,
  }))
  if (pages.length === 0) throw new Error('PDF 没有可编辑页面')
  return { sourceSha256, pageCount: pages.length, pages, formFields, capabilities: { maxOperations: 500, textAnnotation: { kind: 'stickyNote', width: 20, height: 18 }, coordinates: 'unrotated-pdf-user-space' } }
}

export async function patchPdfWithReceipt(content: Uint8Array, rawOperations: unknown, expectedSha256: string) {
  const ops = operationsSchema.parse(rawOperations)
  const hasText = ops.some(op => op.kind === 'replaceText')
  const model = await inspectPdf(content, hasText)
  if (expectedSha256 !== model.sourceSha256) throw new Error('PDF 来源摘要不匹配')
  const byId = new Map(model.pages.map((page) => [page.pageId, page]))
  const deleted = new Set<string>()
  const touched = new Set<string>()
  let reordered = false
  const request: SavePdfRequest = { path: '', markups: [], drawings: [], formValues: [], stamps: [], rotations: [], deletedPages: [] }
  const formOps = ops.filter((op): op is Extract<typeof op, { kind: 'setFormValue' }> => op.kind === 'setFormValue')
  if (formOps.length) {
    if (model.formFields.some(field => field.kind === 'signature')) throw new Error('含有签名字段的 PDF 不允许表单值写回')
    const fields = new Map(model.formFields.map(field => [field.name, field]))
    const seen = new Set<string>()
    for (const op of formOps) {
      if (seen.has(op.name)) throw new Error('PDF 表单字段操作重复')
      seen.add(op.name)
    }
    for (const op of formOps) {
      const field = fields.get(op.name)
      if (!field || field.fieldId !== op.fieldId || field.expectedFieldSha256 !== op.expectedFieldSha256 || field.kind !== op.fieldKind) throw new Error('PDF 表单字段身份无效或已过期')
      if (!field.editable) throw new Error('PDF 表单字段只读或类型暂不支持')
      if (op.fieldKind === 'checkbox') {
        if (typeof op.checked !== 'boolean' || op.value !== undefined) throw new Error('PDF 复选框值无效')
        request.formValues.push({ name: op.name, kind: 'checkbox', checked: op.checked })
      } else {
        if (typeof op.value !== 'string' || op.checked !== undefined) throw new Error('PDF 表单字段值无效')
        if (op.fieldKind === 'radio' || op.fieldKind === 'choice') {
          const value = op.value
          if (value && !field.options?.includes(value)) throw new Error('PDF 表单选项无效')
        }
        request.formValues.push({ name: op.name, kind: op.fieldKind, value: op.value })
      }
    }
  }
  for (const op of ops) {
    if (op.kind === 'setFormValue') continue
    if (op.sourceSha256 !== undefined && op.sourceSha256 !== model.sourceSha256) throw new Error('PDF 操作来源摘要不匹配')
    if (op.kind === 'reorderPages') {
      if (reordered || new Set(op.pageIds).size !== op.pageIds.length || op.pageIds.some((id) => !byId.has(id))) throw new Error('PDF 页面排序无效')
      reordered = true
      request.pageOrder = op.pageIds.map((id) => byId.get(id)!.index)
      continue
    }
    const target = byId.get(op.pageId)
    if (!target) {
      if (op.kind === 'replaceText') continue
      throw new Error('PDF 页面身份无效或已过期')
    }
    if (op.kind === 'deletePage') {
      if (deleted.has(op.pageId) || touched.has(op.pageId)) throw new Error('PDF 删除页面与其他操作冲突')
      deleted.add(op.pageId)
      request.deletedPages!.push(target.index)
      continue
    }
    if (deleted.has(op.pageId)) throw new Error('PDF 操作不能引用已删除页面')
    touched.add(op.pageId)
    if (op.kind === 'rotatePage') {
      request.rotations!.push({ pageIndex: target.index, delta: op.delta })
      continue
    }
    if (op.kind === 'replaceText') continue
    const [x1, y1, x2, y2] = op.rect
    const box = target.cropBox
    if (x1 >= x2 || y1 >= y2 || x1 < box.x || y1 < box.y || x2 > box.x + box.width || y2 > box.y + box.height) throw new Error('PDF 坐标超出页面范围')
    if (op.kind === 'highlight') {
      request.markups.push({ pageIndex: target.index, type: 'highlight', color: op.color ?? [1, 0.85, 0], quads: [[x1, y2, x2, y2, x1, y1, x2, y1]] })
    } else {
      // 上游便签固定为 20×18pt；矩形只定位左上角，避免改变上游绘制器。
      if (x1 + 20 > box.x + box.width || y2 - 18 < box.y) throw new Error('PDF 文字批注超出页面范围')
      request.drawings.push({ kind: 'note', pageIndex: target.index, at: [x1, y2], contents: op.text, color: op.color ?? [1, 0.85, 0] })
    }
  }
  const survivors = model.pages.filter((page) => !deleted.has(page.pageId))
  if (!survivors.length) throw new Error('PDF 不能删除全部页面')
  if (request.pageOrder && (request.pageOrder.length !== survivors.length || request.pageOrder.some((index) => deleted.has(model.pages[index]!.pageId)))) throw new Error('PDF 排序必须完整包含保留页面')
  const prepared = hasText ? await prepareTextEdits(content, model.pages, ops) : { edits: [], indices: [], skipped: [] as SkippedOperation[] }
  request.textEdits = prepared.edits
  const skippedOperations = [...prepared.skipped]
  const remaining = ops.filter((_, index) => !skippedOperations.some(item => item.operationIndex === index))
  let bytes = content
  if (remaining.length) {
    const result = await applySaveRequest(content, request)
    if (result.skippedTextEdits.length) {
      for (const index of prepared.indices) skippedOperations.push({ operationIndex: index, kind: 'replaceText', pageId: (ops[index] as {pageId:string}).pageId, reason: 'pdf_text_combined_edit_failed_original_retained' })
      request.textEdits = []
      bytes = ops.some(op => op.kind !== 'replaceText') ? (await applySaveRequest(content, request)).bytes : content
    } else bytes = result.bytes
  }
  const appliedOperationIndices = ops.map((_, index) => index).filter(index => !skippedOperations.some(item => item.operationIndex === index))
  // Bind confirmation to actual output font programs, text/bounds, output identity,
  // runtime WASM identity, requested operations and all application decisions.
  const savedFormFields = formOps.length ? (await inspectPdf(bytes)).formFields : []
  for (const op of formOps) {
    const field = savedFormFields.find(item => item.name === op.name)
    const expected = op.fieldKind === 'checkbox' ? op.checked : op.value
    if (!field || field.value !== expected) throw new Error('PDF 表单字段写回后复读不一致')
  }
  const outputIdentity = hasText ? (await inspectNativeText(bytes, sha256(bytes))).map(page => page.map(({ objectId, ...object }) => object)) : null
  const resources = hasText ? await textResourcesIdentity() : null
  const previewDigest = sha256(Buffer.from(JSON.stringify({ sourceSha256: model.sourceSha256, operations: ops, appliedOperationIndices, skippedOperations, outputIdentity, savedFormFields, resources })))
  return { bytes, sourceSha256: model.sourceSha256, sha256: sha256(bytes), size: bytes.length, skippedOperations, appliedOperationIndices, previewDigest }
}

export async function patchPdf(content: Uint8Array, rawOperations: unknown, expectedSha256: string) {
  const result = await patchPdfWithReceipt(content, rawOperations, expectedSha256)
  if (result.skippedOperations.length) throw new Error('pdf_text_operations_skipped')
  return result.bytes
}
