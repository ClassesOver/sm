import { normalizeAddedNoteDates, type AddedNoteDate } from './note-timestamps'
import { markupRemovalLinks, markupRemovalIdentity, removeSourceMarkups, type MarkupRemoval, type NoteContentEdit } from './markup-delete'
import { createHash } from 'node:crypto'
import { PDFArray, PDFDict, PDFString, PDFHexString, PDFRef, PDFName, PDFNumber, PDFCheckBox, PDFDocument, PDFDropdown, PDFOptionList, PDFRadioGroup, PDFSignature, PDFTextField } from 'pdf-lib'
import { z } from 'zod'
import { applySaveRequest, setPageSizeBytes } from '../src/main/save-pdf'
import { inspectNativeText, prepareTextEdits, textResourcesIdentity } from './text-operations'
import type { SkippedOperation } from './text-operations'
import type { SavePdfRequest } from '../src/shared/ipc'

export const sha256 = (content: Uint8Array): string => createHash('sha256').update(content).digest('hex')
const paperSizes = { A3: [842, 1191], A4: [595, 842], A5: [420, 595], Letter: [612, 792], Legal: [612, 1008] } as const
function pageSizeAvailability(document: PDFDocument, signedOrUnsupported: boolean) {
  try {
    const safe = !signedOrUnsupported && !document.getForm().hasXFA()
      && !['Outlines', 'Dests', 'Names'].some(name => document.catalog.has(PDFName.of(name)))
      && document.getPages().every(page => {
        const unit = page.node.get(PDFName.of('UserUnit'))
        if (unit !== undefined && (!(unit instanceof PDFNumber) || unit.asNumber() !== 1)) return false
        if (page.getRotation().angle % 90 !== 0 || ['BleedBox', 'TrimBox', 'ArtBox'].some(name => page.node.getInheritableAttribute(PDFName.of(name)) !== undefined)) return false
        const annotations = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
        return !annotations || Array.from({ length: annotations.size() }, (_, index) => annotations.lookup(index, PDFDict)).every(annotation => ['Text', 'Widget', 'Highlight', 'Underline', 'StrikeOut', 'Squiggly'].includes(String(annotation.get(PDFName.of('Subtype'))).slice(1)))
      })
    return { pageSize: safe, pageSizeReason: safe ? null : '来源含非默认单位、签名、坐标导航、印刷框或未支持批注，暂不能安全变更页面尺寸' }
  } catch { return { pageSize: false, pageSizeReason: '来源页面结构尚不能安全变更尺寸' } }
}
const identity = { sourceSha256: z.string().regex(/^[a-f0-9]{64}$/).optional() }
const page = { ...identity, pageId: z.string().min(1) }
const color = z.tuple([z.number().min(0).max(1), z.number().min(0).max(1), z.number().min(0).max(1)])
const rect = z.tuple([z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite()])
const fieldIdentity = { fieldId: z.string().regex(/^[a-f0-9]{64}$/), expectedFieldSha256: z.string().regex(/^[a-f0-9]{64}$/), name: z.string().min(1).max(256), fieldKind: z.enum(['text', 'checkbox', 'radio', 'choice']) }
const operation = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('setFormValue'), ...fieldIdentity, value: z.string().max(4000).optional(), checked: z.boolean().optional() }).strict(),
  z.object({ kind: z.literal('replaceText'), ...page, objectId: z.string().min(1).max(256), expectedTextSha256: z.string().regex(/^[a-f0-9]{64}$/), newText: z.string().max(4000) }).strict(),
  z.object({ kind: z.literal('editNote'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/), contents: z.string().trim().min(1).max(10000), modifiedAt: z.string().datetime({ precision: 0 }) }).strict(),
  z.object({ kind: z.literal('removeNote'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('removeMarkup'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('addMarkup'), ...page, markupType: z.enum(['highlight', 'underline', 'squiggly', 'strikeout']), quads: z.array(z.tuple([z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite()])).min(1).max(200), color }).strict(),
  z.object({ kind: z.literal('highlight'), ...page, rect, color: color.optional() }).strict(),
  z.object({ kind: z.literal('addTextAnnotation'), ...page, rect, text: z.string().trim().min(1).max(10000), color: color.optional(), createdMs: z.number().int().min(0).max(253402300799999).optional() }).strict(),
  z.object({ kind: z.literal('setPageSize'), ...identity, preset: z.enum(['A3', 'A4', 'A5', 'Letter', 'Legal']) }).strict(),
  z.object({ kind: z.literal('cropPage'), ...page, rect }).strict(),
  z.object({ kind: z.literal('rotatePage'), ...page, delta: z.union([z.literal(90), z.literal(180), z.literal(270)]) }).strict(),
  z.object({ kind: z.literal('deletePage'), ...page }).strict(),
  z.object({ kind: z.literal('reorderPages'), ...identity, pageIds: z.array(z.string()).min(1).max(10000) }).strict(),
])
const operationsSchema = z.array(operation).max(500)

export async function inspectPdf(content: Uint8Array, includeText = false) {
  const document = await PDFDocument.load(content, { updateMetadata: false })
  const sourceSha256 = sha256(content)
  const textPages = includeText ? await inspectNativeText(content, sourceSha256) : undefined
  // pdf-lib getForm() removes XFA from its in-memory model; census the immutable source first.
  const sourceHasXfa = document.catalog.lookupMaybe(PDFName.of('AcroForm'), PDFDict)?.has(PDFName.of('XFA')) === true
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
    const model = { name, kind, value, ...(options ? { options } : {}), editable: supported && !sourceHasXfa }
    const expectedFieldSha256 = sha256(Buffer.from(JSON.stringify(model)))
    return { ...model, fieldId: sha256(Buffer.from(`${sourceSha256}:${name}:${kind}`)), expectedFieldSha256 }
  })
  const removalLinks = markupRemovalLinks(document, formFields.some(field => field.kind === 'signature') || sourceHasXfa || document.catalog.has(PDFName.of('Perms')))
  const pages = document.getPages().map((page, index) => ({
    pageId: `sha256:${sourceSha256}:page:${index}`, index,
    ...(textPages ? { textObjects: textPages[index] } : {}),
    ...(() => {
      try {
        const annots = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
        const markups = annots ? Array.from({ length: annots.size() }, (_, i) => annots.lookup(i, PDFDict)).flatMap((annotation, i) => {
          const subtype = String(annotation.get(PDFName.of('Subtype'))).slice(1)
          const type = ({ Highlight: 'highlight', Underline: 'underline', Squiggly: 'squiggly', StrikeOut: 'strikeout' } as Record<string, string>)[subtype]
          if (!type) return []
          const q = annotation.lookupMaybe(PDFName.of('QuadPoints'), PDFArray)?.asArray().map(value => Number(String(value))) ?? []
          if (!q.length || q.length % 8 || !q.every(Number.isFinite)) throw new Error('unreadable_source_markup')
          const quads = Array.from({ length: q.length / 8 }, (_, i) => q.slice(i * 8, i * 8 + 8))
          const c = annotation.lookupMaybe(PDFName.of('C'), PDFArray)?.asArray().map(value => Number(String(value))) ?? []
          return [{ markupType: type, quads, color: c, ...markupRemovalIdentity(sourceSha256, index, i, annots!.get(i)!, annotation, removalLinks) }]
        }) : []
        return { markups, markupReadSafe: true }
      } catch { return { markups: [], markupReadSafe: false } }
    })(),
    ...(() => {
      try {
        const annots = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
        const notes = annots ? annots.asArray().flatMap((raw, i) => {
          const annotation = document.context.lookup(raw, PDFDict)
          if (String(annotation.get(PDFName.of('Subtype'))) !== '/Text') return []
          const value = annotation.lookup(PDFName.of('Contents'))
          if (value !== undefined && !(value instanceof PDFString || value instanceof PDFHexString)) throw new Error('pdf_note_contents_unreadable')
          const contents = value?.decodeText() ?? ''
          const identity = markupRemovalIdentity(sourceSha256, index, i, raw, annotation, removalLinks)
          const flags = annotation.lookup(PDFName.of('F'))
          const unsafe = ['RC', 'DS', 'DA', 'State', 'StateModel', 'RT'].some(key => annotation.has(PDFName.of(key)))
            || (raw instanceof PDFRef && removalLinks.references.get(raw.toString()) !== 1)
            || (flags !== undefined && (!(flags instanceof PDFNumber) || !Number.isInteger(flags.asNumber()) || flags.asNumber() < 0 || (flags.asNumber() & 704) !== 0))
          const reason = identity.removalReason ?? (unsafe ? '此便签含共享引用、锁定、富文本或状态信息，暂不支持编辑/删除' : null)
          return [{ ...identity, sourceRef: raw instanceof PDFRef ? `${raw.objectNumber}R${raw.generationNumber || ''}` : null, contents, editable: reason === null, removable: reason === null, removalReason: reason }]
        }) : []
        return { notes, notesReadSafe: true }
      } catch { return { notes: [], notesReadSafe: false } }
    })(),
    mediaBox: page.getMediaBox(), cropBox: page.getCropBox(), rotation: page.getRotation().angle,
  }))
  if (pages.length === 0) throw new Error('PDF 没有可编辑页面')
  return { sourceSha256, pageCount: pages.length, pages, formFields, capabilities: { maxOperations: 500, textAnnotation: { kind: 'stickyNote', width: 20, height: 18 }, cropPage: true, selectionMarkup: true, removeMarkup: true, notes: true, ...pageSizeAvailability(document, sourceHasXfa || formFields.some(field => ['signature', 'unsupported'].includes(field.kind))), coordinates: 'unrotated-pdf-user-space' } }
}

export async function patchPdfWithReceipt(content: Uint8Array, rawOperations: unknown, expectedSha256: string) {
  const ops = operationsSchema.parse(rawOperations)
  const hasText = ops.some(op => op.kind === 'replaceText')
  const model = await inspectPdf(content, hasText)
  if (expectedSha256 !== model.sourceSha256) throw new Error('PDF 来源摘要不匹配')
  const sizeOps = ops.filter(op => op.kind === 'setPageSize')
  if (sizeOps.length > 1 || (sizeOps.length && ops.some(op => ['cropPage', 'replaceText'].includes(op.kind)))) throw new Error('PDF 页面尺寸不能重复或与裁切、原位改字混用；请先保存重开')
  if (sizeOps.length && !model.capabilities.pageSize) throw new Error(model.capabilities.pageSizeReason ?? 'pdf_page_size_source_unsupported')
  const byId = new Map(model.pages.map((page) => [page.pageId, page]))
  const crops = new Map<string, [number, number, number, number]>()
  const removals: MarkupRemoval[] = []
  const noteEdits: NoteContentEdit[] = []
  const addedNoteDates: AddedNoteDate[] = []
  const removedIds = new Set<string>()
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
    if (op.kind === 'setPageSize') continue
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
    if (op.kind === 'editNote' || op.kind === 'removeNote') {
      const note = target.notes.find(note => note.annotationId === op.annotationId)
      if (!target.notesReadSafe || !note?.editable || !note.removable || note.expectedAnnotationSha256 !== op.expectedAnnotationSha256 || removedIds.has(op.annotationId)) throw new Error('pdf_note_identity_invalid_or_readonly')
      removedIds.add(op.annotationId)
      const plan = { pageIndex: target.index, annotationId: op.annotationId, expectedAnnotationSha256: op.expectedAnnotationSha256, subtype: 'Text' as const }
      if (op.kind === 'editNote') noteEdits.push({ ...plan, contents: op.contents, modifiedAt: op.modifiedAt })
      else removals.push(plan)
      continue
    }
    if (op.kind === 'removeMarkup') {
      const markup = target.markups.find(mark => mark.annotationId === op.annotationId)
      if (!target.markupReadSafe || !markup || !markup.removable || markup.expectedAnnotationSha256 !== op.expectedAnnotationSha256 || removedIds.has(op.annotationId)) throw new Error('pdf_markup_identity_invalid_or_readonly')
      removedIds.add(op.annotationId)
      removals.push({ pageIndex: target.index, annotationId: op.annotationId, expectedAnnotationSha256: op.expectedAnnotationSha256 })
      continue
    }
    if (op.kind === 'addMarkup') {
      if (!target.markupReadSafe) throw new Error('pdf_source_markup_unreadable')
      const current = crops.get(op.pageId), b = target.cropBox
      const [left, bottom, right, top] = current ?? [b.x, b.y, b.x + b.width, b.y + b.height]
      for (const q of op.quads) {
        const [x1, y2, x2, , , y1] = q
        if (x2 - x1 < .5 || y2 - y1 < .5 || q[3] !== y2 || q[4] !== x1 || q[6] !== x2 || q[7] !== y1 || x1 < left || y1 < bottom || x2 > right || y2 > top) throw new Error('PDF 文字标注范围无效')
      }
      request.markups.push({ pageIndex: target.index, type: op.markupType, quads: op.quads, color: op.color })
      continue
    }
    const [x1, y1, x2, y2] = op.rect
    const previousCrop = crops.get(op.pageId)
    const box = previousCrop ? { x: previousCrop[0], y: previousCrop[1], width: previousCrop[2] - previousCrop[0], height: previousCrop[3] - previousCrop[1] } : target.cropBox
    if (x1 >= x2 || y1 >= y2 || x1 < box.x || y1 < box.y || x2 > box.x + box.width || y2 > box.y + box.height) throw new Error('PDF 坐标超出页面范围')
    if (op.kind === 'cropPage') {
      if (x2 - x1 < .5 || y2 - y1 < .5) throw new Error('PDF 裁切范围过小')
      crops.set(op.pageId, op.rect)
      continue
    }
    if (op.kind === 'highlight') {
      request.markups.push({ pageIndex: target.index, type: 'highlight', color: op.color ?? [1, 0.85, 0], quads: [[x1, y2, x2, y2, x1, y1, x2, y1]] })
    } else {
      // 上游便签固定为 20×18pt；矩形只定位左上角，避免改变上游绘制器。
      if (x1 + 20 > box.x + box.width || y2 - 18 < box.y) throw new Error('PDF 文字批注超出页面范围')
      request.drawings.push({ kind: 'note', pageIndex: target.index, at: [x1, y2], contents: op.text, color: op.color ?? [1, 0.85, 0], createdMs: op.createdMs ?? 0 })
      addedNoteDates.push({ pageIndex: target.index, contents: op.text, rect: [x1, y2 - 18, x1 + 20, y2].map(value => Math.round(value * 100) / 100), ...(op.createdMs === undefined ? {} : { createdMs: op.createdMs }) })
    }
  }
  const survivors = model.pages.filter((page) => !deleted.has(page.pageId))
  if (!survivors.length) throw new Error('PDF 不能删除全部页面')
  if (request.pageOrder && (request.pageOrder.length !== survivors.length || request.pageOrder.some((index) => deleted.has(model.pages[index]!.pageId)))) throw new Error('PDF 排序必须完整包含保留页面')
  const prepared = hasText ? await prepareTextEdits(content, model.pages, ops) : { edits: [], indices: [], skipped: [] as SkippedOperation[] }
  request.textEdits = prepared.edits
  const skippedOperations = [...prepared.skipped]
  const remaining = ops.filter((_, index) => !skippedOperations.some(item => item.operationIndex === index))
  let bytes = await removeSourceMarkups(content, model.sourceSha256, removals, noteEdits)
  const annotationBaseBytes = bytes
  if (remaining.some(op => !['editNote', 'removeNote', 'removeMarkup', 'cropPage', 'setPageSize'].includes(op.kind))) {
    const result = await applySaveRequest(bytes, request)
    if (result.skippedTextEdits.length) {
      for (const index of prepared.indices) skippedOperations.push({ operationIndex: index, kind: 'replaceText', pageId: (ops[index] as {pageId:string}).pageId, reason: 'pdf_text_combined_edit_failed_original_retained' })
      request.textEdits = []
      bytes = ops.some(op => !['replaceText', 'editNote', 'removeNote', 'removeMarkup'].includes(op.kind)) ? (await applySaveRequest(bytes, request)).bytes : bytes
    } else bytes = result.bytes
  }
  bytes = await normalizeAddedNoteDates(annotationBaseBytes, bytes, addedNoteDates, request.markups.map(mark => mark.pageIndex), request.pageOrder ?? survivors.map(page => page.index))
  if (crops.size) {
    // Same CropBox primitive as pinned cropPagesBytes; absolute source-space
    // bounds keep ordered crop/rotation commands stable through final reorder.
    const output = await PDFDocument.load(bytes, { updateMetadata: false })
    const order = request.pageOrder ?? survivors.map(page => page.index)
    for (const [pageId, [x1, y1, x2, y2]] of crops) {
      const sourceIndex = byId.get(pageId)!.index
      output.getPage(order.indexOf(sourceIndex)).setCropBox(x1, y1, x2 - x1, y2 - y1)
    }
    bytes = await output.save({ useObjectStreams: false, updateFieldAppearances: false })
  }
  const sizeOp = sizeOps[0]
  if (sizeOp) {
    const [width, height] = paperSizes[sizeOp.preset]
    bytes = await setPageSizeBytes(bytes, width, height)
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
  const resizedIdentity = sizeOp ? { sha256: sha256(bytes), pages: (await inspectPdf(bytes)).pages } : null
  const resources = hasText ? await textResourcesIdentity() : null
  const previewDigest = sha256(Buffer.from(JSON.stringify({ sourceSha256: model.sourceSha256, operations: ops, appliedOperationIndices, skippedOperations, outputIdentity, savedFormFields, resources, resizedIdentity, ...(ops.some(op => ['addMarkup', 'removeMarkup', 'editNote', 'removeNote', 'addTextAnnotation'].includes(op.kind)) ? { markupOutputSha256: sha256(bytes) } : {}) })))
  return { bytes, sourceSha256: model.sourceSha256, sha256: sha256(bytes), size: bytes.length, skippedOperations, appliedOperationIndices, previewDigest }
}

export async function patchPdf(content: Uint8Array, rawOperations: unknown, expectedSha256: string) {
  const result = await patchPdfWithReceipt(content, rawOperations, expectedSha256)
  if (result.skippedOperations.length) throw new Error('pdf_text_operations_skipped')
  return result.bytes
}
