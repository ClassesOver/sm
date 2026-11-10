import { appendLocalNoteReplies, type LocalNoteRoot, type LocalNoteReply } from './local-note-replies'
import { inspectReplyTargets, inspectNoteThreads, appendNoteReplies, canAppendPendingReplies, type NoteReply } from './note-replies'
import { inspectAttachments, patchAttachments, validAttachmentName, ATTACHMENT_FILE_MAX } from './attachments'
import { normalizeAddedNoteDates, type AddedNoteDate } from './note-timestamps'
import { markupRemovalLinks, markupRemovalIdentity, removeSourceMarkups, type MarkupRemoval, type NoteContentEdit } from './markup-delete'
import { createHash } from 'node:crypto'
import { PDFArray, PDFDict, PDFString, PDFHexString, PDFRef, PDFName, PDFNumber, PDFCheckBox, PDFDocument, PDFDropdown, PDFOptionList, PDFRadioGroup, PDFSignature, PDFTextField } from 'pdf-lib'
import { z } from 'zod'
import { applySaveRequest, setPageSizeBytes } from '../src/main/save-pdf'
import { MAX_REDACTION_REGIONS, redactPdf } from '../src/main/redaction'
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
const point = z.tuple([z.number().finite(), z.number().finite()])
const fieldIdentity = { fieldId: z.string().regex(/^[a-f0-9]{64}$/), expectedFieldSha256: z.string().regex(/^[a-f0-9]{64}$/), name: z.string().min(1).max(256), fieldKind: z.enum(['text', 'checkbox', 'radio', 'choice']) }
const hexColor = z.string().regex(/^#[0-9a-fA-F]{6}$/)
const stampText = z.string().max(200)
// 固定源 StampDialog 配置（WatermarkConfig / HeaderFooterConfig），位图由浏览器按固定源 stamps.ts 渲染。
const watermarkConfig = z.object({ text: z.string().trim().min(1).max(200), angle: z.number().min(-90).max(90), opacity: z.number().min(0.05).max(1), color: hexColor, sizeRatio: z.number().min(0.04).max(0.22) }).strict()
const headerFooterConfig = z.object({ headerLeft: stampText, headerCenter: stampText, headerRight: stampText, footerLeft: stampText, footerCenter: stampText, footerRight: stampText, pageNumber: z.boolean(), startAt: z.number().int().min(1).max(100000), fontSize: z.number().min(4).max(72), color: hexColor }).strict()
const operation = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('setStamps'), ...identity, watermark: watermarkConfig.nullable(), headerFooter: headerFooterConfig.nullable(), images: z.array(z.string().min(8).max(8_000_000)).min(1).max(1000), stamps: z.array(z.object({ pageId: z.string().min(1), image: z.number().int().min(0), rect, opacity: z.number().min(0).max(1).optional() }).strict()).min(1).max(20000) }).strict(),
  z.object({ kind: z.literal('replyPendingNote'), ...page, parentLocalId: z.string().regex(/^[a-f0-9]{32}$/), contents: z.string().trim().min(1).max(10000), createdMs: z.number().int().min(0).max(253402300799999) }).strict(),
  z.object({ kind: z.literal('replyNote'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/), contents: z.string().trim().min(1).max(10000), createdMs: z.number().int().min(0).max(253402300799999) }).strict(),
  z.object({ kind: z.literal('addAttachment'), ...identity, name: z.string().refine(validAttachmentName), bytesBase64: z.string().max(4 * Math.ceil(ATTACHMENT_FILE_MAX / 3)), description: z.string().max(4000).optional() }).strict(),
  z.object({ kind: z.literal('removeAttachment'), ...identity, attachmentId: z.string().regex(/^[a-f0-9]{64}$/), expectedAttachmentSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('setFormValue'), ...fieldIdentity, value: z.string().max(4000).optional(), checked: z.boolean().optional() }).strict(),
  z.object({ kind: z.literal('replaceText'), ...page, objectId: z.string().min(1).max(256), expectedTextSha256: z.string().regex(/^[a-f0-9]{64}$/), newText: z.string().max(4000) }).strict(),
  z.object({ kind: z.literal('editNote'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/), contents: z.string().trim().min(1).max(10000), modifiedAt: z.string().datetime({ precision: 0 }) }).strict(),
  z.object({ kind: z.literal('removeNote'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('removeMarkup'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('addMarkup'), ...page, markupType: z.enum(['highlight', 'underline', 'squiggly', 'strikeout']), quads: z.array(z.tuple([z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite()])).min(1).max(200), color }).strict(),
  z.object({ kind: z.literal('highlight'), ...page, rect, color: color.optional() }).strict(),
  z.object({ kind: z.literal('redact'), ...page, rect }).strict(),
  // 固定源 DrawLayer 的矩形/椭圆/箭头/手绘：PDF user space 坐标，写入引擎 drawings。
  z.object({ kind: z.literal('addDrawing'), ...page, shape: z.enum(['rect', 'ellipse', 'arrow', 'measure', 'ink', 'polygon', 'caret', 'link', 'image']), label: z.string().min(1).max(64).regex(/^[\x20-\x7e]+$/).optional(), image: z.string().min(8).max(6_000_000).optional(), url: z.string().max(2048).regex(/^(https?:\/\/[^\s]+|mailto:[^\s]+)$/i).optional(), destPage: z.number().int().min(1).max(10000).optional(), rect: rect.optional(), from: point.optional(), to: point.optional(), vertices: z.array(point).min(3).max(200).optional(), point: point.optional(), paths: z.array(z.array(z.number().finite()).min(4).max(4000)).min(1).max(20).optional(), color, width: z.number().finite().min(0.25).max(24) }).strict(),
  z.object({ kind: z.literal('addTextAnnotation'), ...page, localId: z.string().regex(/^[a-f0-9]{32}$/).optional(), rect, text: z.string().trim().min(1).max(10000), color: color.optional(), createdMs: z.number().int().min(0).max(253402300799999).optional() }).strict(),
  z.object({ kind: z.literal('setPageSize'), ...identity, preset: z.enum(['A3', 'A4', 'A5', 'Letter', 'Legal']) }).strict(),
  z.object({ kind: z.literal('cropPage'), ...page, rect }).strict(),
  z.object({ kind: z.literal('rotatePage'), ...page, delta: z.union([z.literal(90), z.literal(180), z.literal(270)]) }).strict(),
  z.object({ kind: z.literal('deletePage'), ...page }).strict(),
  z.object({ kind: z.literal('insertBlankPage'), ...identity, pageId: z.string().regex(/^blank:[a-z0-9-]{1,64}$/), width: z.number().finite().min(1).max(14400), height: z.number().finite().min(1).max(14400) }).strict(),
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
  const threads = inspectNoteThreads(document, sourceSha256, removalLinks.protectedSource)
  const replyTargets = threads.roots
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
          const leafReply = threads.replies.get(identity.annotationId)
          const reason = leafReply ? null : identity.removalReason ?? (unsafe ? '此便签含共享引用、锁定、富文本或状态信息，暂不支持编辑/删除' : null)
          return [{ ...identity, ...(leafReply?{parentAnnotationId:leafReply.parentAnnotationId}:{}), replyable: replyTargets.has(identity.annotationId), sourceRef: raw instanceof PDFRef ? `${raw.objectNumber}R${raw.generationNumber || ''}` : null, contents, editable: reason === null, removable: reason === null, removalReason: reason }]
        }) : []
        return { notes, notesReadSafe: true }
      } catch { return { notes: [], notesReadSafe: false } }
    })(),
    mediaBox: page.getMediaBox(), cropBox: page.getCropBox(), rotation: page.getRotation().angle,
  }))
  if (pages.length === 0) throw new Error('PDF 没有可编辑页面')
  return { sourceSha256, pageCount: pages.length, pages, formFields, ...inspectAttachments(document, sourceSha256, sourceHasXfa || formFields.some(field => field.kind === 'signature') || document.catalog.has(PDFName.of('Perms'))), capabilities: { maxOperations: 500, textAnnotation: { kind: 'stickyNote', width: 20, height: 18 }, cropPage: true, selectionMarkup: true, removeMarkup: true, notes: true, noteReplies: true, savedReplyEdits: true, pendingNoteReplies: canAppendPendingReplies(document, removalLinks.protectedSource), ...pageSizeAvailability(document, sourceHasXfa || formFields.some(field => ['signature', 'unsupported'].includes(field.kind))), coordinates: 'unrotated-pdf-user-space' } }
}

export async function patchPdfWithReceipt(content: Uint8Array, rawOperations: unknown, expectedSha256: string) {
  const ops = operationsSchema.parse(rawOperations)
  const hasText = ops.some(op => op.kind === 'replaceText')
  const model = await inspectPdf(content, hasText)
  if (expectedSha256 !== model.sourceSha256) throw new Error('PDF 来源摘要不匹配')
  const savedReplyMutations = ops.some(op => (op.kind === 'editNote' || op.kind === 'removeNote') && model.pages.some(page => page.notes.some(note => note.annotationId === op.annotationId && note.parentAnnotationId !== undefined)))
  if (savedReplyMutations && ops.some(op => ['replaceText','setPageSize','cropPage'].includes(op.kind))) throw new Error('已保存回复修改与原位改字、页面尺寸或裁切请分别保存重开')
  const localReplies = ops.filter(op => op.kind === 'replyPendingNote')
  const identifiedRoots = ops.filter((op): op is Extract<(typeof ops)[number], {kind:'addTextAnnotation'}> => op.kind === 'addTextAnnotation' && op.localId !== undefined)
  const rootIds = identifiedRoots.map(op => op.localId!)
  if (new Set(rootIds).size !== rootIds.length) throw new Error('pdf_local_reply_duplicate_root')
  if (localReplies.length && !model.capabilities.pendingNoteReplies) throw new Error('pdf_local_reply_source_readonly')
  const deferredIds = new Set(localReplies.map(op => op.parentLocalId))
  for (const reply of localReplies) if (!identifiedRoots.some(root => root.localId === reply.parentLocalId && root.pageId === reply.pageId)) throw new Error('pdf_local_reply_parent_invalid')
  const localRoots: LocalNoteRoot[] = [], pendingReplies: LocalNoteReply[] = []
  const replyOps = ops.filter(op => op.kind === 'replyNote')
  if ((replyOps.length || localReplies.length) && ops.some(op => ['replaceText', 'setPageSize', 'cropPage'].includes(op.kind))) throw new Error('回复与原位改字、页面尺寸或裁切请分别保存重开')
  if (replyOps.some(reply => ops.some(op => (op.kind === 'editNote' || op.kind === 'removeNote') && op.annotationId === reply.annotationId))) throw new Error('回复根便签不能在同一批编辑或删除')
  const replyTargets = replyOps.length ? inspectReplyTargets(await PDFDocument.load(content, { updateMetadata: false }), model.sourceSha256, false) : new Map()
  const replies: NoteReply[] = []
  const attachmentOps = ops.filter(op => op.kind === 'addAttachment' || op.kind === 'removeAttachment')
  if (attachmentOps.length && hasText) throw new Error('附件修改与原位改字请分别保存重开')
  const sizeOps = ops.filter(op => op.kind === 'setPageSize')
  if (sizeOps.length > 1 || (sizeOps.length && ops.some(op => ['cropPage', 'replaceText'].includes(op.kind)))) throw new Error('PDF 页面尺寸不能重复或与裁切、原位改字混用；请先保存重开')
  if (sizeOps.length && !model.capabilities.pageSize) throw new Error(model.capabilities.pageSizeReason ?? 'pdf_page_size_source_unsupported')
  const byId = new Map(model.pages.map((page) => [page.pageId, page]))
  // 固定源 blankPages：空白页按插入顺序追加为原始索引 pageCount + k，再由 pageOrder 放到目标位置。
  // 空白页只有本地草稿身份，只接受旋转；其他依赖来源身份的修改需保存重开后进行。
  const blankIndex = new Map<string, number>()
  for (const op of ops) {
    if (op.kind !== 'insertBlankPage') continue
    if (blankIndex.has(op.pageId)) throw new Error('PDF 空白页身份重复')
    blankIndex.set(op.pageId, model.pages.length + blankIndex.size)
  }
  if (blankIndex.size > 200) throw new Error('PDF 空白页数量超过 200')
  const crops = new Map<string, [number, number, number, number]>()
  // 固定源原生安全涂黑（redaction.ts，PDFium ApplyRedaction 移除区域内文字/图像/路径并黑块覆盖）；
  // 原生编辑每次保存都写新修订、来源修订不变，对应固定源“先另存副本再涂黑”。
  const redactions: { pageIndex: number; rect: [number, number, number, number] }[] = []
  if (sizeOps.length && ops.some(op => op.kind === 'redact')) throw new Error('PDF 涂黑不能与页面尺寸同批修改；请先保存重开')
  const removals: MarkupRemoval[] = []
  const noteEdits: NoteContentEdit[] = []
  const addedNoteDates: AddedNoteDate[] = []
  const removedIds = new Set<string>()
  const deleted = new Set<string>()
  const touched = new Set<string>()
  let reordered = false
  const request: SavePdfRequest = { path: '', markups: [], drawings: [], formValues: [], stamps: [], rotations: [], deletedPages: [], blankPages: ops.flatMap(op => op.kind === 'insertBlankPage' ? [{ pageIndex: blankIndex.get(op.pageId)!, width: op.width, height: op.height }] : []) }
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
    if (op.kind === 'setPageSize' || op.kind === 'addAttachment' || op.kind === 'removeAttachment' || op.kind === 'insertBlankPage' || op.kind === 'setStamps') continue
    if (op.kind === 'reorderPages') {
      if (reordered || new Set(op.pageIds).size !== op.pageIds.length || op.pageIds.some((id) => !byId.has(id) && !blankIndex.has(id))) throw new Error('PDF 页面排序无效')
      reordered = true
      request.pageOrder = op.pageIds.map((id) => byId.get(id)?.index ?? blankIndex.get(id)!)
      continue
    }
    const blank = blankIndex.get(op.pageId)
    if (blank !== undefined) {
      if (op.kind !== 'rotatePage') throw new Error('PDF 新插入的空白页只能旋转、移动或删除；请先保存重开后再编辑')
      request.rotations!.push({ pageIndex: blank, delta: op.delta })
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
    if (op.kind === 'replyPendingNote') { pendingReplies.push({ parentLocalId: op.parentLocalId, pageIndex: target.index, contents: op.contents, createdMs: op.createdMs }); continue }
    if (op.kind === 'replyNote') {
      const note = target.notes.find(note => note.annotationId === op.annotationId), parent = replyTargets.get(op.annotationId)
      if (!target.notesReadSafe || !note?.replyable || !parent || note.expectedAnnotationSha256 !== op.expectedAnnotationSha256 || parent.pageIndex !== target.index) throw new Error('pdf_reply_parent_invalid_or_readonly')
      replies.push({ target: parent, contents: op.contents, createdMs: op.createdMs }); continue
    }
    if (op.kind === 'editNote' || op.kind === 'removeNote') {
      const note = target.notes.find(note => note.annotationId === op.annotationId)
      if (!target.notesReadSafe || !note?.editable || !note.removable || note.expectedAnnotationSha256 !== op.expectedAnnotationSha256 || removedIds.has(op.annotationId)) throw new Error('pdf_note_identity_invalid_or_readonly')
      removedIds.add(op.annotationId)
      const plan = { pageIndex: target.index, annotationId: op.annotationId, expectedAnnotationSha256: op.expectedAnnotationSha256, subtype: 'Text' as const, ...(note.parentAnnotationId?{unlinkObject:true}:{}) }
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
    if (op.kind === 'addDrawing') {
      const current = crops.get(op.pageId), b = target.cropBox
      const [left, bottom, right, top] = current ?? [b.x, b.y, b.x + b.width, b.y + b.height]
      const inside = (x: number, y: number) => x >= left && x <= right && y >= bottom && y <= top
      const base = { pageIndex: target.index, color: op.color, width: op.width }
      if (op.image !== undefined && op.shape !== 'image') throw new Error('PDF 绘图参数无效')
      if (op.label !== undefined && op.shape !== 'measure') throw new Error('PDF 绘图参数无效')
      if (op.shape === 'rect' || op.shape === 'ellipse') {
        if (!op.rect || op.from || op.to || op.paths || op.vertices || op.point || op.url !== undefined || op.destPage !== undefined || op.image !== undefined) throw new Error('PDF 绘图参数无效')
        const [x1, y1, x2, y2] = op.rect
        if (x2 - x1 < 1 || y2 - y1 < 1 || !inside(x1, y1) || !inside(x2, y2)) throw new Error('PDF 绘图范围无效')
        request.drawings.push({ ...base, kind: op.shape, rect: op.rect })
      } else if (op.shape === 'arrow') {
        if (!op.from || !op.to || op.rect || op.paths || op.vertices || op.point || op.url !== undefined || op.destPage !== undefined || !inside(...op.from) || !inside(...op.to) || Math.hypot(op.to[0] - op.from[0], op.to[1] - op.from[1]) < 2) throw new Error('PDF 箭头范围无效')
        request.drawings.push({ ...base, kind: 'arrow', from: op.from, to: op.to })
      } else if (op.shape === 'measure') {
        // 固定源 measure.ts：标定后的测量线，标签为会话内换算的长度文字（Helvetica，仅可打印 ASCII）。
        if (!op.from || !op.to || op.label === undefined || op.label.trim() === '' || op.rect || op.paths || op.vertices || op.point || op.url !== undefined || op.destPage !== undefined || !inside(...op.from) || !inside(...op.to) || Math.hypot(op.to[0] - op.from[0], op.to[1] - op.from[1]) < 2) throw new Error('PDF 测量线无效')
        request.drawings.push({ ...base, kind: 'measure', from: op.from, to: op.to, label: op.label })
      } else if (op.shape === 'polygon') {
        if (!op.vertices || op.rect || op.from || op.to || op.paths || op.point || op.url !== undefined || op.destPage !== undefined || op.vertices.some(vertex => !inside(...vertex))) throw new Error('PDF 多边形顶点无效')
        request.drawings.push({ ...base, kind: 'polygon', vertices: op.vertices })
      } else if (op.shape === 'image') {
        // 固定源 ImageDialogs 插入图像：PNG 位图写为 Stamp 批注。
        if (!op.rect || !op.image || op.from || op.to || op.paths || op.vertices || op.point || op.url !== undefined || op.destPage !== undefined) throw new Error('PDF 图像参数无效')
        const bytes = Buffer.from(op.image, 'base64')
        if (bytes.toString('base64') !== op.image || !bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) throw new Error('PDF 图像须为 PNG')
        const [x1, y1, x2, y2] = op.rect
        if (x2 - x1 < 1 || y2 - y1 < 1 || !inside(x1, y1) || !inside(x2, y2)) throw new Error('PDF 图像范围无效')
        request.drawings.push({ kind: 'image', pageIndex: target.index, image: op.image, rect: op.rect })
      } else if (op.shape === 'link') {
        // 固定源 LinkDialog：外部 URL 或文档内页码二选一；仅允许 http/https/mailto。destPage 为来源页序号（引擎按删除/重排前页表解析）。
        if (!op.rect || op.image !== undefined || op.from || op.to || op.paths || op.vertices || op.point || (op.url === undefined) === (op.destPage === undefined)) throw new Error('PDF 链接目标无效')
        const [x1, y1, x2, y2] = op.rect
        if (x2 - x1 < 1 || y2 - y1 < 1 || !inside(x1, y1) || !inside(x2, y2)) throw new Error('PDF 链接范围无效')
        if (op.destPage !== undefined) {
          const total = model.pages.length + blankIndex.size
          const destination = op.destPage - 1
          if (destination >= total || (destination < model.pages.length && ops.some(other => other.kind === 'deletePage' && other.pageId === model.pages[destination]!.pageId))) throw new Error('PDF 链接目标页不存在或已删除')
        }
        request.drawings.push({ kind: 'link', pageIndex: target.index, rect: op.rect, ...(op.url !== undefined ? { url: op.url } : { destPage: op.destPage! }) })
      } else if (op.shape === 'caret') {
        if (!op.point || op.url !== undefined || op.destPage !== undefined || op.rect || op.from || op.to || op.paths || op.vertices || !inside(...op.point)) throw new Error('PDF 插入符号位置无效')
        request.drawings.push({ kind: 'caret', pageIndex: target.index, color: op.color, point: op.point })
      } else {
        if (!op.paths || op.rect || op.from || op.to || op.vertices || op.point || op.url !== undefined || op.destPage !== undefined || op.paths.some(path => path.length % 2 !== 0 || path.some((value, index) => index % 2 === 0 ? !inside(value, path[index + 1]!) : false))) throw new Error('PDF 手绘路径无效')
        request.drawings.push({ ...base, kind: 'ink', paths: op.paths })
      }
      continue
    }
    if (op.kind === 'redact') {
      const current = crops.get(op.pageId), b = target.cropBox
      const [left, bottom, right, top] = current ?? [b.x, b.y, b.x + b.width, b.y + b.height]
      const [x1, y1, x2, y2] = op.rect
      if (x2 - x1 < 1 || y2 - y1 < 1 || x1 < left || y1 < bottom || x2 > right || y2 > top) throw new Error('PDF 涂黑范围无效')
      if (redactions.length >= MAX_REDACTION_REGIONS) throw new Error(`PDF 涂黑区域超过 ${MAX_REDACTION_REGIONS} 个`)
      redactions.push({ pageIndex: target.index, rect: op.rect })
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
      if (op.localId !== undefined && deferredIds.has(op.localId)) { localRoots.push({localId:op.localId,pageIndex:target.index,rect:op.rect,contents:op.text,color:op.color??[1,.85,0],...(op.createdMs===undefined?{}:{createdMs:op.createdMs})}); continue }
      request.drawings.push({ kind: 'note', pageIndex: target.index, at: [x1, y2], contents: op.text, color: op.color ?? [1, 0.85, 0], createdMs: op.createdMs ?? 0 })
      addedNoteDates.push({ pageIndex: target.index, contents: op.text, rect: [x1, y2 - 18, x1 + 20, y2].map(value => Math.round(value * 100) / 100), ...(op.createdMs === undefined ? {} : { createdMs: op.createdMs }) })
    }
  }
  const survivors = model.pages.filter((page) => !deleted.has(page.pageId))
  if (!survivors.length) throw new Error('PDF 不能删除全部页面')
  // 水印/页眉页脚：每个保留页（含新空白页）恰好由同一批图章覆盖；位图须为 PNG 且总量受限。
  const stampOps = ops.filter((op): op is Extract<(typeof ops)[number], { kind: 'setStamps' }> => op.kind === 'setStamps')
  if (stampOps.length > 1 || (stampOps.length && sizeOps.length)) throw new Error('PDF 水印/页眉页脚只能设置一次，且不能与页面尺寸同批修改')
  for (const stampOp of stampOps) {
    if (!stampOp.watermark && !stampOp.headerFooter) throw new Error('PDF 水印/页眉页脚配置为空')
    const decoded = stampOp.images.map(image => Buffer.from(image, 'base64'))
    if (decoded.some((bytes, index) => bytes.toString('base64') !== stampOp.images[index] || !bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) || decoded.reduce((total, bytes) => total + bytes.length, 0) > 12 * 1024 * 1024) throw new Error('PDF 图章位图无效或过大')
    const covered = new Set<string>()
    for (const stamp of stampOp.stamps) {
      const source = byId.get(stamp.pageId), blank = blankIndex.get(stamp.pageId)
      if ((!source && blank === undefined) || deleted.has(stamp.pageId) || stamp.image >= decoded.length) throw new Error('PDF 图章页面身份无效')
      const box = source?.mediaBox ?? (() => { const op = ops.find(item => item.kind === 'insertBlankPage' && item.pageId === stamp.pageId) as { width: number; height: number }; return { x: 0, y: 0, width: op.width, height: op.height } })()
      const [x1, y1, x2, y2] = stamp.rect
      const tolerance = 0.01
      if (x2 - x1 < 1 || y2 - y1 < 1 || x1 < box.x - tolerance || y1 < box.y - tolerance || x2 > box.x + box.width + tolerance || y2 > box.y + box.height + tolerance) throw new Error('PDF 图章位置超出页面')
      covered.add(stamp.pageId)
      request.stamps!.push({ pageIndex: source?.index ?? blank!, image: stampOp.images[stamp.image]!, rect: stamp.rect, ...(stamp.opacity === undefined ? {} : { opacity: stamp.opacity }) })
    }
    const expected = [...survivors.map(page => page.pageId), ...blankIndex.keys()]
    if (covered.size !== expected.length || expected.some(id => !covered.has(id))) throw new Error('PDF 水印/页眉页脚须覆盖全部保留页面')
  }
  if (request.pageOrder && (request.pageOrder.length !== survivors.length + blankIndex.size || request.pageOrder.some((index) => index < model.pages.length && deleted.has(model.pages[index]!.pageId)))) throw new Error('PDF 排序必须完整包含保留页面')
  // 未重排时空白页按插入顺序追加在末尾；后续裁切/批注定位统一使用这一最终顺序。
  const finalOrder = request.pageOrder ?? [...survivors.map(page => page.index), ...blankIndex.values()]
  const prepared = hasText ? await prepareTextEdits(content, model.pages, ops) : { edits: [], indices: [], skipped: [] as SkippedOperation[] }
  request.textEdits = prepared.edits
  const skippedOperations = [...prepared.skipped]
  const remaining = ops.filter((_, index) => !skippedOperations.some(item => item.operationIndex === index))
  let bytes = await removeSourceMarkups(content, model.sourceSha256, removals, noteEdits)
  const annotationBaseBytes = bytes
  if (remaining.some(op => !(op.kind === 'addTextAnnotation' && op.localId && deferredIds.has(op.localId)) && !['redact', 'editNote', 'removeNote', 'removeMarkup', 'cropPage', 'setPageSize', 'addAttachment', 'removeAttachment', 'replyNote', 'replyPendingNote'].includes(op.kind))) {
    const result = await applySaveRequest(bytes, request)
    if (result.skippedTextEdits.length) {
      for (const index of prepared.indices) skippedOperations.push({ operationIndex: index, kind: 'replaceText', pageId: (ops[index] as {pageId:string}).pageId, reason: 'pdf_text_combined_edit_failed_original_retained' })
      request.textEdits = []
      bytes = ops.some(op => !['replaceText', 'editNote', 'removeNote', 'removeMarkup', 'addAttachment', 'removeAttachment'].includes(op.kind)) ? (await applySaveRequest(bytes, request)).bytes : bytes
    } else bytes = result.bytes
  }
  bytes = await normalizeAddedNoteDates(annotationBaseBytes, bytes, addedNoteDates, request.markups.map(mark => mark.pageIndex), finalOrder)
  if (crops.size) {
    // Same CropBox primitive as pinned cropPagesBytes; absolute source-space
    // bounds keep ordered crop/rotation commands stable through final reorder.
    const output = await PDFDocument.load(bytes, { updateMetadata: false })
    const order = finalOrder
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
  bytes = await patchAttachments(bytes, model, attachmentOps)
  bytes = await appendNoteReplies(bytes, replies, finalOrder)
  bytes = await appendLocalNoteReplies(bytes, localRoots, pendingReplies, finalOrder)
  if (redactions.length) {
    // 涂黑是最终序列化：PDFium 另存只写清理后可达对象，之后不再有 pdf-lib 写入可复活旧内容流。
    // 页缩略图与 PieceInfo 可能保留涂黑前的渲染，先删除；页索引换算到最终页序。
    const mapped = redactions.map(item => ({ pageIndex: finalOrder.indexOf(item.pageIndex), rect: item.rect }))
    if (mapped.some(item => item.pageIndex < 0)) throw new Error('PDF 涂黑页面身份无效')
    const output = await PDFDocument.load(bytes, { updateMetadata: false })
    for (const index of new Set(mapped.map(item => item.pageIndex))) { output.getPage(index).node.delete(PDFName.of('Thumb')); output.getPage(index).node.delete(PDFName.of('PieceInfo')) }
    bytes = await redactPdf(await output.save({ useObjectStreams: false, updateFieldAppearances: false }), mapped)
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
  const previewDigest = sha256(Buffer.from(JSON.stringify({ sourceSha256: model.sourceSha256, operations: ops, appliedOperationIndices, skippedOperations, outputIdentity, savedFormFields, resources, resizedIdentity, ...(ops.some(op => ['redact', 'addMarkup', 'addDrawing', 'setStamps', 'removeMarkup', 'editNote', 'removeNote', 'addTextAnnotation', 'addAttachment', 'removeAttachment', 'replyNote', 'replyPendingNote'].includes(op.kind)) ? { markupOutputSha256: sha256(bytes) } : {}) })))
  return { bytes, sourceSha256: model.sourceSha256, sha256: sha256(bytes), size: bytes.length, skippedOperations, appliedOperationIndices, previewDigest }
}

export async function patchPdf(content: Uint8Array, rawOperations: unknown, expectedSha256: string) {
  const result = await patchPdfWithReceipt(content, rawOperations, expectedSha256)
  if (result.skippedOperations.length) throw new Error('pdf_text_operations_skipped')
  return result.bytes
}
