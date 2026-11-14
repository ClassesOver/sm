import {setStaticFillSchema,removeStaticFillSchema,inspectStaticFills,prepareStaticFills,reviewStaticFills} from './static-form-fill'
import {inspectDigitalSignatures} from './signatures'
import {metadataAvailability,freezeMetadataDate,reviewMetadataOutput} from './metadata'
import {validateMetadataOperation,type MetadataValues} from '../vendor/metadata/protocol'
import {batesAvailability,prepareBates,reviewBatesOutput} from './bates'
import type {BatesConfig} from '../vendor/bates/bates'
import {inspectPdfOutline,outlineWriteRequest,reviewPdfOutline} from './outline'
import {reviewMeasureLabelClipping} from './measure-label-review'
import {prepareMixedPng,reviewMixedPngStamp,type MixedPngImage} from './mixed-png'
import {validateMixedLinkTarget,assertMixedLinkSource,reviewMixedLink} from './mixed-links'
import {reviewMixedMeasureCaret} from './mixed-measure-caret'
import {editDesignTextProperties,formTextPropertiesAvailability,type EditFormTextPropertiesOperation} from './form-text-properties'
import {inspectFormTextOverflow} from '../src/main/form-text-properties'
import {appendDesignRadioWidget,formRadioExtensionAvailability,type AppendRadioWidgetOperation} from './form-radio-extension'
import {replaceStyledText,type StyledReplaceTextOperation} from './replace-text-style'
import {staticTextAvailability,insertStaticText} from './static-text'
import { inspectSavedDrawings } from './saved-drawings'
import { inspectDesignWidgets, removeDesignWidgetWithReceipt } from './form-design'
import {createDesignField,editDesignFieldRequired,formDesignCreateAvailability,type CreateFormFieldOperation,type EditFormFieldRequiredOperation} from './form-design-create'
import {editDesignWidget,editDesignWidgetRects,arrangeDesignWidgets,formDesignPropertiesAvailability,type EditFormWidgetOperation,type EditFormWidgetRectsOperation,type ArrangeFormWidgetsOperation} from './form-design-properties'
import {patchExternalPages} from './external-pages'
import {inspectExistingImages,transformExistingImage,type ExistingImageOperation} from './existing-image'
import { assertRedactionAnnotationSafety, flattenLayoutAnnotations } from './layout-preservation'
import { appendLocalNoteReplies, type LocalNoteRoot, type LocalNoteReply } from './local-note-replies'
import { inspectReplyTargets, inspectNoteThreads, appendNoteReplies, rebindTextEditedReplies, canAppendPendingReplies, type NoteReply } from './note-replies'
import { inspectAttachments, patchAttachments, validAttachmentName, ATTACHMENT_FILE_MAX } from './attachments'
import { normalizeAddedNoteDates, type AddedNoteDate, type AddedNoteReference } from './note-timestamps'
import { markupDictionaryHash, markupRemovalLinks, markupRemovalIdentity, removeSourceMarkups, type MarkupRemoval, type NoteContentEdit } from './markup-delete'
import { createHash } from 'node:crypto'
import { PDFArray, PDFDict, PDFString, PDFHexString, PDFRef, PDFName, PDFNumber, PDFRawStream, decodePDFRawStream, PDFCheckBox, PDFDocument, PDFDropdown, PDFOptionList, PDFRadioGroup, PDFSignature, PDFTextField } from 'pdf-lib'
import { z } from 'zod'
import { applySaveRequest, mergePagesBytes, setPageSizeBytes, splitPagesBytes } from '../src/main/save-pdf'
import { MAX_REDACTION_REGIONS, redactPdf } from '../src/main/redaction'
import { inspectNativeText, prepareTextEdits, textResourcesIdentity } from './text-operations'
import type { SkippedOperation } from './text-operations'
import type { SavePdfRequest } from '../src/shared/ipc'

export const sha256 = (content: Uint8Array): string => createHash('sha256').update(content).digest('hex')
const paperSizes = { A3: [842, 1191], A4: [595, 842], A5: [420, 595], Letter: [612, 792], Legal: [612, 1008] } as const
interface AddedMarkupReference { pageIndex: number; sourceRef: string; expectedAnnotationSha256: string }
/** 只承认固定写入器的真实追加槽位；无法证明时放弃映射，不影响已生成 PDF。 */
export async function inspectAddedMarkupReferences(baseBytes: Uint8Array, outputBytes: Uint8Array, markups: SavePdfRequest['markups'], drawings: SavePdfRequest['drawings'], outputOrder: number[]): Promise<Map<number, AddedMarkupReference>> {
  const references = new Map<number, AddedMarkupReference>()
  if (!markups.length) return references
  try {
    const base = await PDFDocument.load(baseBytes, { updateMetadata: false })
    const output = await PDFDocument.load(outputBytes, { updateMetadata: false })
    if (output.getPageCount() !== outputOrder.length || new Set(outputOrder).size !== outputOrder.length) return references
    const originalRefs = new Set(base.context.enumerateIndirectObjects().map(([ref]) => ref.toString()))
    const occurrences = new Map<string, number>()
    for (const page of output.getPages()) for (const raw of page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)?.asArray() ?? []) {
      if (raw instanceof PDFRef) occurrences.set(raw.toString(), (occurrences.get(raw.toString()) ?? 0) + 1)
    }
    for (const [pageIndex, sourceIndex] of outputOrder.entries()) {
      const original = base.getPages()[sourceIndex]?.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
      const actual = output.getPage(pageIndex).node.lookupMaybe(PDFName.of('Annots'), PDFArray)
      const prefix = original?.size() ?? 0
      const pageMarkups = markups.flatMap((mark, index) => mark.pageIndex === sourceIndex ? [{ mark, index }] : [])
      if ((actual?.size() ?? 0) !== prefix + pageMarkups.length + (drawings ?? []).filter(item => item.pageIndex === sourceIndex).length) return new Map()
      for (let index = 0; index < prefix; index++) {
        if (String(original!.get(index)) !== String(actual!.get(index)) || markupDictionaryHash(original!.lookup(index, PDFDict)) !== markupDictionaryHash(actual!.lookup(index, PDFDict))) return new Map()
      }
      for (const [offset, { mark, index }] of pageMarkups.entries()) {
        const raw = actual!.get(prefix + offset)
        if (!(raw instanceof PDFRef) || originalRefs.has(raw.toString()) || occurrences.get(raw.toString()) !== 1) return new Map()
        const annotation = actual!.lookup(prefix + offset, PDFDict)
        const subtype = { highlight: 'Highlight', underline: 'Underline', strikeout: 'StrikeOut', squiggly: 'Squiggly' }[mark.type]
        if (String(annotation.get(PDFName.of('Subtype'))) !== '/' + subtype || String(annotation.get(PDFName.of('P'))) !== output.getPage(pageIndex).ref.toString()
          || String(annotation.lookupMaybe(PDFName.of('QuadPoints'), PDFArray)) !== output.context.obj(mark.quads.flat()).toString()
          || String(annotation.lookupMaybe(PDFName.of('C'), PDFArray)) !== output.context.obj(mark.color).toString()) return new Map()
        references.set(index, { pageIndex, sourceRef: raw.toString(), expectedAnnotationSha256: markupDictionaryHash(annotation) })
      }
    }
    return references
  } catch { references.clear(); return references }
}
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
  setStaticFillSchema,removeStaticFillSchema,
  z.object({kind:z.literal('setMetadata'),sourceSha256:z.string().regex(/^[a-f0-9]{64}$/),modifiedMs:z.number().int().min(0).max(8640000000000000),metadata:z.custom<MetadataValues>()}).strict(),
  z.object({kind:z.literal('addBates'),sourceSha256:z.string().regex(/^[a-f0-9]{64}$/),config:z.custom<BatesConfig>(),entries:z.array(z.object({pageId:z.string().min(1),ordinal:z.number().int().min(0),origin:point,rotate:z.union([z.literal(0),z.literal(90),z.literal(180),z.literal(270)]),lineXOffsets:z.tuple([z.number().finite().max(0).min(-100000)])}).strict()).min(1).max(2000)}).strict(),
  z.object({kind:z.literal('setOutline'),sourceSha256:z.string().regex(/^[a-f0-9]{64}$/),tree:z.array(z.unknown()).max(2000)}).strict(),
  z.object({kind:z.literal('insertText'),sourceSha256:z.string().regex(/^[a-f0-9]{64}$/),pageId:z.string().min(1),origin:point,text:z.string().min(1).max(1000).refine(value=>value.trim().length>0&&!/[\p{Cc}\p{Cf}\u2028\u2029]/u.test(value.replaceAll(String.fromCharCode(10),''))),fontSize:z.number().finite().min(6).max(72),color,align:z.enum(['left','center','right']),font:z.enum(['arial','times','courier']).optional(),bold:z.boolean().optional(),italic:z.boolean().optional(),lineLeading:z.number().finite().positive().optional()}).strict(),
  z.object({ kind:z.literal('removeFormWidget'), sourceSha256:z.string().regex(/^[a-f0-9]{64}$/), fieldName:z.string().min(1).max(256), widgetId:z.string().regex(/^\d+R\d*$/), widgetIdentity:z.string().regex(/^[a-f0-9]{64}$/), expectedWidgetSha256:z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('setStamps'), ...identity, watermark: watermarkConfig.nullable(), headerFooter: headerFooterConfig.nullable(), images: z.array(z.string().min(8).max(8_000_000)).min(1).max(1000), stamps: z.array(z.object({ pageId: z.string().min(1), image: z.number().int().min(0), rect, opacity: z.number().min(0).max(1).optional() }).strict()).min(1).max(20000) }).strict(),
  z.object({ kind: z.literal('replyPendingNote'), ...page, parentLocalId: z.string().regex(/^[a-f0-9]{32}$/), contents: z.string().trim().min(1).max(10000), createdMs: z.number().int().min(0).max(253402300799999), author:z.literal('AI Assistant').optional() }).strict(),
  z.object({ kind: z.literal('replyNote'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/), contents: z.string().trim().min(1).max(10000), createdMs: z.number().int().min(0).max(253402300799999), author: z.literal('AI Assistant').optional() }).strict(),
  z.object({ kind: z.literal('addAttachment'), ...identity, name: z.string().refine(validAttachmentName), bytesBase64: z.string().max(4 * Math.ceil(ATTACHMENT_FILE_MAX / 3)), description: z.string().max(4000).optional() }).strict(),
  z.object({ kind: z.literal('removeAttachment'), ...identity, attachmentId: z.string().regex(/^[a-f0-9]{64}$/), expectedAttachmentSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('setFormValue'), ...fieldIdentity, value: z.string().max(4000).optional(), checked: z.boolean().optional() }).strict(),
  z.object({ kind: z.literal('replaceText'), ...page, objectId: z.string().min(1).max(256), expectedTextSha256: z.string().regex(/^[a-f0-9]{64}$/), newText: z.string().max(4000),font:z.enum(['arial','times','courier']).optional(),fontSize:z.number().finite().min(6).max(72).optional(),color:color.optional(),bold:z.boolean().optional(),italic:z.boolean().optional(),align:z.enum(['left','center','right']).optional(),lineLeading:z.number().finite().positive().optional(),styleRuns:z.array(z.object({start:z.number().int().min(0),end:z.number().int().min(1),font:z.enum(['arial','times','courier']).optional(),size:z.number().finite().min(6).max(72).optional(),color:color.optional(),bold:z.boolean().optional(),italic:z.boolean().optional()}).strict()).max(4000).optional() }).strict(),
  z.object({ kind: z.literal('editNote'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/), contents: z.string().trim().min(1).max(10000), modifiedAt: z.string().datetime({ precision: 0 }) }).strict(),
  z.object({ kind: z.literal('removeNote'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('removeDrawing'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('removeMarkup'), ...page, annotationId: z.string().regex(/^[a-f0-9]{64}$/), expectedAnnotationSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('addMarkup'), ...page, markupType: z.enum(['highlight', 'underline', 'squiggly', 'strikeout']), quads: z.array(z.tuple([z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite(), z.number().finite()])).min(1).max(200), color }).strict(),
  z.object({ kind: z.literal('highlight'), ...page, rect, color: color.optional() }).strict(),
  z.object({ kind: z.literal('redact'), ...page, rect }).strict(),
  z.object({ kind: z.literal('mergePages'), ...identity, perSheet: z.number().int().min(2).max(16), direction: z.enum(['horizontal', 'vertical']), separator: z.boolean() }).strict(),
  z.object({ kind: z.literal('splitPages'), ...identity, perPage: z.union([z.literal(2), z.literal(4), z.literal(9)]) }).strict(),
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
  const signatureModel=await inspectDigitalSignatures(content)
  const metadataCapability=metadataAvailability(document)
  const sourceSha256 = sha256(content)
  const insertAvailability = staticTextAvailability(document)
  const protectionAvailable = !document.isEncrypted && !document.context.trailerInfo.Encrypt && !document.catalog.has(PDFName.of('Perms')) && !document.catalog.has(PDFName.of('AcroForm'))
  const formCreateAvailability = await formDesignCreateAvailability(content)
  const formPropertiesAvailability = await formDesignPropertiesAvailability(content)
  const existingImageModel = await inspectExistingImages(content).catch(()=>({existingImages:[],capabilities:{editExistingImage:false,editExistingImageReason:'当前图像读取引擎或来源暂不支持编辑已有图像'}}))
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
  const drawingPages = inspectSavedDrawings(document,sourceSha256,removalLinks.protectedSource)
  const threads = inspectNoteThreads(document, sourceSha256, removalLinks.protectedSource)
  const replyTargets = threads.roots
  const pages = document.getPages().map((page, index) => ({
    pageId: `sha256:${sourceSha256}:page:${index}`, index, ...drawingPages[index],
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
          const raw = annots!.get(i)!
          return [{ markupType: type, quads, color: c, sourceRef: raw instanceof PDFRef ? raw.toString() : null,
            ...markupRemovalIdentity(sourceSha256, index, i, raw, annotation, removalLinks) }]
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
    mediaBox: page.getMediaBox(), cropBox: page.getCropBox(), rotation: page.getRotation().angle, userUnit:page.node.lookupMaybe(PDFName.of('UserUnit'),PDFNumber)?.asNumber()??1,
  }))
  if (pages.length === 0) throw new Error('PDF 没有可编辑页面')
  const formDesign = await inspectDesignWidgets(content)
  const staticFillModel=await inspectStaticFills(content)
  return { sourceSha256, ...signatureModel, pageCount: pages.length, pages, formFields, staticFormFills:staticFillModel.staticFormFills, ...inspectPdfOutline(document,sourceSha256,removalLinks.protectedSource), existingImages:existingImageModel.existingImages, formDesignWidgets:formDesign.widgets, ...inspectAttachments(document, sourceSha256, sourceHasXfa || formFields.some(field => field.kind === 'signature') || document.catalog.has(PDFName.of('Perms'))), capabilities: { ...staticFillModel.capabilities, ...metadataCapability, ...batesAvailability(document), ...existingImageModel.capabilities, protectPdf: protectionAvailable, ...formCreateAvailability, ...formPropertiesAvailability, ...await formRadioExtensionAvailability(content), ...await formTextPropertiesAvailability(content), editFormFieldRequired: formDesign.widgets.some(widget => widget.removable), ...insertAvailability, maxOperations: 500, textAnnotation: { kind: 'stickyNote', width: 20, height: 18 }, cropPage: true, selectionMarkup: true, removeMarkup: true, removeDrawing: drawingPages.some(page => page.drawings.some(drawing => drawing.removable)), removeFormWidget:formDesign.widgets.some(widget => widget.removable || widget.radioRemovalEditable), notes: true, noteReplies: true, savedReplyEdits: true, pendingNoteReplies: canAppendPendingReplies(document, removalLinks.protectedSource), ...pageSizeAvailability(document, sourceHasXfa || formFields.some(field => ['signature', 'unsupported'].includes(field.kind))), coordinates: 'unrotated-pdf-user-space' } }
}

async function deterministicLayoutDates(source: Uint8Array, output: Uint8Array) {
  const original = await PDFDocument.load(source, { updateMetadata: false, ignoreEncryption: true })
  const document = await PDFDocument.load(output, { updateMetadata: false })
  const info = document.context.lookup(document.context.trailerInfo.Info, PDFDict)
  if (info) {
    for (const [key, value] of [['CreationDate', original.getCreationDate()], ['ModDate', original.getModificationDate()]] as const) {
      if (value) info.set(PDFName.of(key), PDFString.fromDate(value))
      else info.delete(PDFName.of(key))
    }
  }
  return document.save({ useObjectStreams: false, updateFieldAppearances: false })
}

export async function patchPdfWithReceipt(content: Uint8Array, rawOperations: unknown, expectedSha256: string) {
  if(Array.isArray(rawOperations)){
    const exclusive=rawOperations.find(op=>op&&typeof op==='object'&&['externalPages','createFormField','editFormFieldRequired','editFormWidget','editFormWidgetRects','arrangeFormWidgets','appendRadioWidget','editFormTextProperties','transformExistingImage'].includes(op.kind))
    if(exclusive){
      if(rawOperations.length!==1)throw Error('外部页面操作或表单设计须单独保存')
      if(exclusive.kind==='externalPages')return patchExternalPages(content,exclusive,expectedSha256)
      if(exclusive.kind==='transformExistingImage')return transformExistingImage(content,exclusive as ExistingImageOperation,expectedSha256)
      if(exclusive.kind==='editFormTextProperties')return editDesignTextProperties(content,expectedSha256,exclusive as EditFormTextPropertiesOperation)
      if(exclusive.kind==='appendRadioWidget')return appendDesignRadioWidget(content,expectedSha256,exclusive as AppendRadioWidgetOperation)
      if(exclusive.kind==='createFormField')return createDesignField(content,expectedSha256,exclusive as CreateFormFieldOperation)
      if(exclusive.kind==='editFormWidget')return editDesignWidget(content,expectedSha256,exclusive as EditFormWidgetOperation)
      if(exclusive.kind==='editFormWidgetRects')return editDesignWidgetRects(content,expectedSha256,exclusive as EditFormWidgetRectsOperation)
      if(exclusive.kind==='arrangeFormWidgets')return arrangeDesignWidgets(content,expectedSha256,exclusive as ArrangeFormWidgetsOperation)
      return editDesignFieldRequired(content,expectedSha256,exclusive as EditFormFieldRequiredOperation)
    }
  }
  const ops = operationsSchema.parse(rawOperations)
  if(ops.some(op=>op.kind==='replaceText'&&(['font','fontSize','color','bold','italic','align','lineLeading','styleRuns'].some(key=>op[key as keyof typeof op]!==undefined)||op.newText.includes(String.fromCharCode(10))))){
    if(ops.some(op=>!['replaceText','addMarkup','highlight','addDrawing'].includes(op.kind)))throw Error('文字样式替换仅可与新增文字标注、安全矢量、PNG图像或安全链接同批；其他类型修改请分别保存')
    if(ops.some(op=>op.kind==='addDrawing'&&!['rect','ellipse','arrow','polygon','ink','image','link','measure','caret'].includes(op.shape)))throw Error('样式改字同批绘图类型不支持，请分别保存')
    if(ops.every(op=>op.kind==='replaceText'))return replaceStyledText(content,ops as StyledReplaceTextOperation[],expectedSha256)
    // All page/geometry/source checks precede either writer. Source-space new
    // annotations commute with text edits; page structure and old annotations do not.
    const sourceSha256=sha256(content)
    if(expectedSha256!==sourceSha256||ops.some(op=>'sourceSha256'in op&&op.sourceSha256!==undefined&&op.sourceSha256!==sourceSha256))throw Error('PDF 来源摘要不匹配')
    const document=await PDFDocument.load(content,{updateMetadata:false})
    if(document.isEncrypted||document.context.trailerInfo.Encrypt||document.catalog.has(PDFName.of('Perms'))||document.catalog.has(PDFName.of('AcroForm')))throw Error('来源含保护、签名或表单，样式改字与文字标注请分别保存')
    const model=await inspectPdf(content),markups=ops.flatMap((op,index)=>op.kind==='addMarkup'||op.kind==='highlight'?[{op,index}]:[]),drawings=ops.flatMap((op,index)=>op.kind==='addDrawing'?[{op,index}]:[]),replacements=ops.flatMap((op,index)=>op.kind==='replaceText'?[{op,index}]:[]),additions=ops.flatMap((op,index)=>op.kind==='addMarkup'||op.kind==='highlight'||op.kind==='addDrawing'?[{op,index}]:[])
    const hasLinks=drawings.some(({op})=>op.shape==='link')
    if(hasLinks)assertMixedLinkSource(document)
    const request:SavePdfRequest={path:'',markups:[],drawings:[],formValues:[],stamps:[]}
    for(const pageId of new Set([...additions,...replacements].map(({op})=>op.pageId))){
      const target=model.pages.find(page=>page.pageId===pageId)
      if(!target)continue // Invalid replacement targets retain the existing per-operation skip contract.
      const unit=document.getPage(target.index).node.getInheritableAttribute(PDFName.of('UserUnit'))
      if(unit!==undefined&&(!(unit instanceof PDFNumber)||unit.asNumber()!==1))throw Error('来源页面单位暂不支持样式改字与文字标注同批')
    }
    for(const {op}of markups){
      const target=model.pages.find(page=>page.pageId===op.pageId)
      if(!target||!target.markupReadSafe)throw Error('PDF 文字标注页面身份无效或来源标注不可读')
      const quads=op.kind==='addMarkup'?op.quads:[[op.rect[0],op.rect[3],op.rect[2],op.rect[3],op.rect[0],op.rect[1],op.rect[2],op.rect[1]]] as [number,number,number,number,number,number,number,number][]
      const box=target.cropBox
      for(const q of quads){const[x1,y2,x2,,,y1]=q;if(x2-x1<.5||y2-y1<.5||q[3]!==y2||q[4]!==x1||q[6]!==x2||q[7]!==y1||x1<box.x||y1<box.y||x2>box.x+box.width||y2>box.y+box.height)throw Error('PDF 文字标注范围无效')}
      request.markups.push({pageIndex:target.index,type:op.kind==='addMarkup'?op.markupType:'highlight',quads,color:op.color??[1,.85,0]})
    }
    const pngBudget={pixels:0,bytes:0},pngImages=new Map<number,MixedPngImage>()
    for(const {op,index}of drawings){
      const target=model.pages.find(page=>page.pageId===op.pageId)
      if(!target||!target.drawingsReadSafe)throw Error('PDF 绘图页面身份无效或来源绘图不可读')
      const geometry=({rect:['rect'],ellipse:['rect'],arrow:['from','to'],polygon:['vertices'],ink:['paths'],image:['rect','image'],link:['rect','url','destPage'],measure:['from','to','label'],caret:['point']} as Record<string,string[]>)[op.shape]
      if(!geometry||Object.keys(op).some(key=>!['kind','sourceSha256','pageId','shape','color','width',...geometry].includes(key)))throw Error('样式改字同批绘图参数无效')
      const box=target.cropBox,inside=([x,y]:[number,number])=>x>=box.x&&y>=box.y&&x<=box.x+box.width&&y<=box.y+box.height,base={pageIndex:target.index,color:op.color,width:op.width}
      if(op.shape==='rect'||op.shape==='ellipse'||op.shape==='image'||op.shape==='link'){
        if(!op.rect)throw Error('PDF 绘图范围无效')
        const[x1,y1,x2,y2]=op.rect
        if(x2-x1<1||y2-y1<1||!inside([x1,y1])||!inside([x2,y2]))throw Error('PDF 绘图范围无效')
        if(op.shape==='image'){
          if(!op.image||![0,90,180,270].includes(((document.getPage(target.index).getRotation().angle%360)+360)%360))throw Error('PNG 图像或来源页面旋转不支持')
          pngImages.set(index,prepareMixedPng(op.image,pngBudget));request.drawings.push({kind:'image',pageIndex:target.index,rect:op.rect,image:op.image})
        }else if(op.shape==='link'){validateMixedLinkTarget(op.url,op.destPage,model.pages.length);request.drawings.push({kind:'link',pageIndex:target.index,rect:op.rect,...(op.url!==undefined?{url:op.url}:{destPage:op.destPage})})}
        else request.drawings.push({...base,kind:op.shape,rect:op.rect})
      }else if(op.shape==='arrow'){
        if(!op.from||!op.to||!inside(op.from)||!inside(op.to)||Math.hypot(op.to[0]-op.from[0],op.to[1]-op.from[1])<2)throw Error('PDF 箭头范围无效')
        request.drawings.push({...base,kind:'arrow',from:op.from,to:op.to})
      }else if(op.shape==='measure'){
        if(!op.from||!op.to||!inside(op.from)||!inside(op.to)||Math.hypot(op.to[0]-op.from[0],op.to[1]-op.from[1])<2||typeof op.label!=='string'||!/^[\x20-\x7e]{1,64}$/.test(op.label)||!op.label.trim())throw Error('PDF 测量线或标签无效')
        request.drawings.push({...base,kind:'measure',from:op.from,to:op.to,label:op.label})
      }else if(op.shape==='caret'){
        if(!op.point||!inside(op.point))throw Error('PDF 插入符号位置无效')
        request.drawings.push({kind:'caret',pageIndex:target.index,color:op.color,point:op.point})
      }else if(op.shape==='polygon'){
        if(!op.vertices||op.vertices.some(point=>!inside(point))||Math.max(...op.vertices.map(v=>v[0]))-Math.min(...op.vertices.map(v=>v[0]))<1||Math.max(...op.vertices.map(v=>v[1]))-Math.min(...op.vertices.map(v=>v[1]))<1)throw Error('PDF 多边形顶点无效')
        request.drawings.push({...base,kind:'polygon',vertices:op.vertices})
      }else if(op.shape==='ink'){
        if(!op.paths||op.paths.some(path=>path.length%2!==0||path.some((x,index)=>index%2===0&&!inside([x,path[index+1]!]))))throw Error('PDF 手绘路径无效')
        request.drawings.push({...base,kind:'ink',paths:op.paths})
      }
    }
    const appearanceIdentity=(document:PDFDocument,annotation:PDFDict)=>{
      const visited=new Set<string>();let nodes=0
      const identify=(value:unknown,depth=0):unknown=>{
        if(++nodes>4096||depth>64)throw Error('pdf_text_drawing_source_appearance_graph_limit')
        if(value instanceof PDFRef){const reference=value.toString();if(visited.has(reference))return ['ref',reference];visited.add(reference);const resolved=document.context.lookup(value);if(resolved===undefined)throw Error('pdf_text_drawing_source_appearance_graph_unreadable');return ['ref',reference,identify(resolved,depth+1)]}
        if(value instanceof PDFRawStream)return ['stream',identify(value.dict,depth+1),sha256(value.contents)]
        if(value instanceof PDFDict)return value.entries().sort(([a],[b])=>String(a).localeCompare(String(b))).map(([key,value])=>[String(key),identify(value,depth+1)])
        if(value instanceof PDFArray)return value.asArray().map(value=>identify(value,depth+1))
        return String(value)
      }
      return JSON.stringify(identify(annotation.get(PDFName.of('AP'))))
    }
    // Validate source appearance graphs before either writer. The byte-exact
    // append baseline is styled.bytes because PDFium may re-encode source APs.
    if(drawings.length)for(const page of document.getPages()){
      const annotations=page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)
      for(let index=0;index<(annotations?.size()??0);index++)appearanceIdentity(document,annotations!.lookup(index,PDFDict))
    }
    const styled=await replaceStyledText(content,replacements.map(({op})=>op) as StyledReplaceTextOperation[],expectedSha256)
    const skippedOperations:{operationIndex:number;kind:'replaceText'|'addMarkup'|'highlight'|'addDrawing';pageId:string;reason:string}[]=styled.skippedOperations.map(skip=>({...skip,operationIndex:replacements[skip.operationIndex]!.index}))
    const appliedOperationIndices=styled.appliedOperationIndices.map(index=>replacements[index]!.index)
    let bytes=styled.bytes,pendingMarkupMapping:{operationIndex:number;pageId:string;effectivePageId:string;annotationId:string;sourceRef:string;expectedAnnotationSha256:string}[]=[]
    let written=false
    try{
      bytes=(await applySaveRequest(bytes,request)).bytes;written=true
      const references=await inspectAddedMarkupReferences(styled.bytes,bytes,request.markups,request.drawings,model.pages.map(page=>page.index)),after=await inspectPdf(bytes)
      const mapping=markups.map(({op,index},markupIndex)=>{
        const reference=references.get(markupIndex),page=reference&&after.pages[reference.pageIndex],matches=page?.markups.filter(mark=>mark.sourceRef===reference!.sourceRef&&mark.expectedAnnotationSha256===reference!.expectedAnnotationSha256)??[]
        if(!reference||!page||matches.length!==1)throw Error('pdf_text_markup_output_identity_unreadable')
        return {operationIndex:index,pageId:op.pageId,effectivePageId:page.pageId,annotationId:matches[0]!.annotationId,sourceRef:reference.sourceRef,expectedAnnotationSha256:reference.expectedAnnotationSha256}
      })
      if(drawings.length){
        const base=await PDFDocument.load(styled.bytes,{updateMetadata:false}),output=await PDFDocument.load(bytes,{updateMetadata:false})
        if(output.getPageCount()!==model.pages.length)throw Error('pdf_text_drawing_output_pages_changed')
        if(hasLinks&&base.getPages().some((page,index)=>String(page.ref)!==String(output.getPage(index).ref)))throw Error('pdf_text_link_output_page_order_changed')
        for(let pageIndex=0;pageIndex<model.pages.length;pageIndex++){
          const original=base.getPage(pageIndex).node.lookupMaybe(PDFName.of('Annots'),PDFArray),actual=output.getPage(pageIndex).node.lookupMaybe(PDFName.of('Annots'),PDFArray),prefix=original?.size()??0
          if((actual?.size()??0)!==prefix+request.markups.filter(mark=>mark.pageIndex===pageIndex).length+request.drawings.filter(drawing=>drawing.pageIndex===pageIndex).length)throw Error('pdf_text_drawing_output_slots_changed')
          for(let index=0;index<prefix;index++)if(String(original!.get(index))!==String(actual!.get(index))||markupDictionaryHash(original!.lookup(index,PDFDict))!==markupDictionaryHash(actual!.lookup(index,PDFDict))||appearanceIdentity(base,original!.lookup(index,PDFDict))!==appearanceIdentity(output,actual!.lookup(index,PDFDict)))throw Error('pdf_text_drawing_source_annotations_changed')
        }
        for(const [drawingIndex,{op,index}]of drawings.entries()){
          const pageIndex=model.pages.findIndex(page=>page.pageId===op.pageId),page=output.getPage(pageIndex),original=base.getPage(pageIndex).node.lookupMaybe(PDFName.of('Annots'),PDFArray),actual=page.node.lookupMaybe(PDFName.of('Annots'),PDFArray),prefix=original?.size()??0
          const pageMarkups=request.markups.filter(mark=>mark.pageIndex===pageIndex).length,priorDrawings=drawings.slice(0,drawingIndex).filter(item=>item.op.pageId===op.pageId).length,slot=prefix+pageMarkups+priorDrawings
          if(!actual||actual.size()!==prefix+pageMarkups+drawings.filter(item=>item.op.pageId===op.pageId).length)throw Error('pdf_text_drawing_output_slots_changed')
          const a=actual.lookup(slot,PDFDict)
          if(op.shape==='link'){reviewMixedLink(output,pageIndex,a,op.rect!,op);continue}
          if(op.shape==='measure'||op.shape==='caret'){
            if(!after.pages[pageIndex]?.drawingsReadSafe||!after.pages[pageIndex].drawings.some(d=>d.annotationIndex===slot&&d.subtype===(op.shape==='caret'?'Caret':'Line')))throw Error('pdf_text_measure_caret_output_census_changed')
            reviewMixedMeasureCaret(output,pageIndex,a,{...op,shape:op.shape});continue
          }
          if(op.shape==='image'){reviewMixedPngStamp(output,pageIndex,a,op.rect!,pngImages.get(index)!,document.getPage(pageIndex).getRotation().angle);continue}
          const ap=a.lookupMaybe(PDFName.of('AP'),PDFDict)?.lookup(PDFName.of('N')),subtype=({rect:'Square',ellipse:'Circle',arrow:'Line',polygon:'Polygon',ink:'Ink'} as Record<string,string>)[op.shape]!
          let points:[number,number][]=[],path:{operator:string;values:number[]}[]=[]
          const command=(operator:string,values:number[]=[])=>path.push({operator,values})
          if(op.shape==='rect'||op.shape==='ellipse'){const[x1,y1,x2,y2]=op.rect!;points=[[x1,y1],[x2,y2]]}
          else if(op.shape==='arrow'){
            const from=op.from!,to=op.to!,angle=Math.atan2(to[1]-from[1],to[0]-from[0]),length=Math.max(9,op.width*4.5);points=[from,to];command('m',from);command('l',to);command('S')
            for(const offset of[-.45,.45]){const head:[number,number]=[to[0]-length*Math.cos(angle+offset),to[1]-length*Math.sin(angle+offset)];points.push(head);command('m',to);command('l',head);command('S')}
            if(String(a.get(PDFName.of('L')))!==output.context.obj([...from,...to]).toString())throw Error('pdf_text_drawing_output_line_changed')
          }else if(op.shape==='polygon'){
            points=op.vertices!;points.forEach((point,index)=>command(index?'l':'m',point));command('h');command('S')
            if(String(a.get(PDFName.of('Vertices')))!==output.context.obj(points.flat().map(v=>Math.round(v*100)/100)).toString())throw Error('pdf_text_drawing_output_vertices_changed')
          }else if(op.shape==='ink'){
            for(const stroke of op.paths!){for(let index=0;index<stroke.length;index+=2){const point:[number,number]=[stroke[index]!,stroke[index+1]!];points.push(point);command(index?'l':'m',point)}command('S')}
            if(String(a.get(PDFName.of('InkList')))!==output.context.obj(op.paths!).toString())throw Error('pdf_text_drawing_output_ink_changed')
          }
          const pad=op.shape==='polygon'?0:op.width+2,expected=[Math.min(...points.map(v=>v[0]))-pad,Math.min(...points.map(v=>v[1]))-pad,Math.max(...points.map(v=>v[0]))+pad,Math.max(...points.map(v=>v[1]))+pad].map(v=>op.shape==='polygon'?Math.round(v*100)/100:v)
          if(!after.pages[pageIndex]?.drawingsReadSafe||!after.pages[pageIndex].drawings.some(d=>d.annotationIndex===slot&&d.subtype===subtype)||String(a.get(PDFName.of('Subtype')))!=='/'+subtype||String(a.get(PDFName.of('P')))!==String(page.ref)||String(a.get(PDFName.of('Rect')))!==output.context.obj(expected).toString()||String(a.get(PDFName.of('C')))!==output.context.obj(op.color).toString()||a.lookupMaybe(PDFName.of('BS'),PDFDict)?.lookupMaybe(PDFName.of('W'),PDFNumber)?.asNumber()!==op.width||!(ap instanceof PDFRawStream)||!ap.contents.length||String(ap.dict.get(PDFName.of('BBox')))!==output.context.obj(expected).toString()||String(ap.dict.get(PDFName.of('Subtype')))!=='/Form'||String(ap.dict.get(PDFName.of('Type')))!=='/XObject')throw Error('pdf_text_drawing_output_identity_unreadable')
          const matrix=ap.dict.lookup(PDFName.of('Matrix'))
          if(matrix!==undefined&&(!(matrix instanceof PDFArray)||String(matrix)!==output.context.obj([1,0,0,1,0,0]).toString()))throw Error('pdf_text_drawing_output_matrix_changed')
          if(path.length){
            const expectedCommands=[{operator:'w',values:[op.width]},{operator:'J',values:[1]},{operator:'j',values:[1]},{operator:'RG',values:op.color},...path],actualCommands:{operator:string;values:number[]}[]=[],values:number[]=[]
            for(const token of Buffer.from(decodePDFRawStream(ap).decode()).toString('ascii').trim().split(/\s+/)){const number=Number(token);if(Number.isFinite(number))values.push(number);else actualCommands.push({operator:token,values:values.splice(0)})}
            if(values.length||actualCommands.length!==expectedCommands.length||actualCommands.some((actual,index)=>{const expected=expectedCommands[index]!;return actual.operator!==expected.operator||actual.values.length!==expected.values.length||actual.values.some((value,index)=>Math.abs(value-expected.values[index]!)>.0051)}))throw Error('pdf_text_drawing_output_path_changed')
          }
        }
      }
      pendingMarkupMapping=mapping;appliedOperationIndices.push(...additions.map(({index})=>index))
    }catch(error){for(const {op,index}of additions)skippedOperations.push({operationIndex:index,kind:op.kind,pageId:op.pageId,reason:`pdf_text_${op.kind==='addDrawing'?'drawing':'markup'}_${written?'output_review':'writer'}_failed_generated_bytes_retained: `+String(error)})}
    appliedOperationIndices.sort((a,b)=>a-b);skippedOperations.sort((a,b)=>a.operationIndex-b.operationIndex)
    const reviewIssues=drawings.filter(({op,index})=>op.shape==='measure'&&appliedOperationIndices.includes(index)).map(({index})=>({operationIndex:index,kind:'addDrawing',fieldName:'',code:'pdf_measure_label_appearance_review_required',message:'固定源测量标签仍从线条中点起写；AP BBox 已按 Helvetica 正式字体包围框保守扩展。草稿字体可能由浏览器替代，靠近页边仍可能裁切，请核对实际预览。'}))
    // Late advisory diagnostics may change independently of the generated bytes.
    // Keep original content/decision digest semantics; return these separately.
    const measureCropIssues=await reviewMeasureLabelClipping(bytes,drawings.flatMap(({op,index})=>op.shape==='measure'&&appliedOperationIndices.includes(index)?[{operationIndex:index,pageIndex:model.pages.find(page=>page.pageId===op.pageId)?.index??-1,from:op.from!,to:op.to!,label:op.label!}]:[]))
    const outputSha256=sha256(bytes)
    return {bytes,sourceSha256,sha256:outputSha256,size:bytes.length,appliedOperationIndices,skippedOperations,reviewIssues:[...reviewIssues,...measureCropIssues],pendingMarkupMapping,previewDigest:sha256(Buffer.from(JSON.stringify({sourceSha256,operations:ops,outputSha256,styledPreviewDigest:styled.previewDigest,appliedOperationIndices,skippedOperations,reviewIssues,pendingMarkupMapping})))}
  }
  const insertion=ops.find(op=>op.kind==='insertText')
  if(insertion){
    if(ops.length!==1)throw new Error('插入静态文字须单独保存，请先保存或撤销其他修改')
    return insertStaticText(content,insertion,expectedSha256)
  }
  const formRemoval = ops.find(op => op.kind === 'removeFormWidget')
  if (formRemoval) {
    if (ops.length !== 1) throw new Error('删除表单控件须单独保存，请先保存或撤销其他修改')
    const sourceSha256 = sha256(content)
    if (expectedSha256 !== sourceSha256 || formRemoval.sourceSha256 !== sourceSha256) throw new Error('PDF 来源摘要不匹配')
    return removeDesignWidgetWithReceipt(content, sourceSha256, formRemoval)
  }
  const layout = ops.find(op => op.kind === 'mergePages' || op.kind === 'splitPages')
  if (layout) {
    // 固定源 mergePages（N 合 1）/ splitPages（每页拆成 2/4/9 格）：整份文档重排版输出为新文件；
    // 原生编辑写为新修订、来源修订不变。必须单独保存，不与其他修改同批。
    if (ops.length !== 1) throw new Error('合并页面/拆分页面须单独保存，请先保存或撤销其他修改')
    const source = await inspectPdf(content)
    if (expectedSha256 !== source.sourceSha256 || (layout.sourceSha256 !== undefined && layout.sourceSha256 !== source.sourceSha256)) throw new Error('PDF 来源摘要不匹配')
    const sourceDocument = await PDFDocument.load(content, { updateMetadata: false })
    if (sourceDocument.catalog.lookupMaybe(PDFName.of('AcroForm'), PDFDict)?.has(PDFName.of('XFA'))) throw new Error('动态表单 PDF 暂不支持合并或拆分页面')
    if (source.formFields.some(field => field.kind === 'signature')) throw new Error('含有签名字段的 PDF 不能合并或拆分页面（输出不保留签名）')
    if (layout.kind === 'splitPages' && source.formFields.length) throw new Error('含表单字段的 PDF 暂不支持拆分页面；请先保留原件并展平表单')
    if (layout.kind === 'splitPages' && source.pageCount * layout.perPage > 10000) throw new Error('拆分后页数超过 10000')
    let bytes = layout.kind === 'mergePages'
      ? await mergePagesBytes(await flattenLayoutAnnotations(content), { perSheet: layout.perSheet, direction: layout.direction, separator: layout.separator })
      : await splitPagesBytes(content, layout.perPage)
    // 固定源新建文档时写入当前时间（CreationDate/ModDate），使同一草稿每次输出不同、预览确认摘要无法复现。
    // 改为沿用来源文档信息中的日期（来源无日期则移除），输出只取决于来源字节与操作。
    bytes = await deterministicLayoutDates(content, bytes)
    const pages = (await inspectPdf(bytes)).pageCount
    const expected = layout.kind === 'mergePages' ? Math.ceil(source.pageCount / layout.perSheet) : source.pageCount * layout.perPage
    if (pages !== expected) throw new Error('合并/拆分页面输出页数复读不一致')
    const outputSha256 = sha256(bytes)
    return { bytes, sourceSha256: source.sourceSha256, sha256: outputSha256, size: bytes.length, skippedOperations: [] as SkippedOperation[], appliedOperationIndices: [0], previewDigest: sha256(Buffer.from(JSON.stringify({ sourceSha256: source.sourceSha256, operations: ops, appliedOperationIndices: [0], layoutOutputSha256: outputSha256 }))) }
  }
  const hasText = ops.some(op => op.kind === 'replaceText')
  const model = await inspectPdf(content, hasText)
  if (expectedSha256 !== model.sourceSha256) throw new Error('PDF 来源摘要不匹配')
  if (ops.some(op=>op.kind==='removeDrawing') && ops.some(op=>['replaceText','setPageSize','cropPage'].includes(op.kind))) throw new Error('删除已保存绘图与原位改字、页面尺寸或裁切请分别保存重开')
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
  if ((replyOps.length || localReplies.length) && ops.some(op => ['setPageSize', 'cropPage'].includes(op.kind))) throw new Error('回复与页面尺寸或裁切请分别保存重开')
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
    if (op.kind === 'mergePages' || op.kind === 'splitPages') throw new Error('页面排版须单独处理')
    if (op.kind === 'setFormValue' || op.kind === 'setStaticFill' || op.kind === 'removeStaticFill') continue
    if (op.sourceSha256 !== undefined && op.sourceSha256 !== model.sourceSha256) throw new Error('PDF 操作来源摘要不匹配')
    if (op.kind === 'setMetadata' || op.kind === 'addBates' || op.kind === 'setOutline' || op.kind === 'setPageSize' || op.kind === 'addAttachment' || op.kind === 'removeAttachment' || op.kind === 'insertBlankPage' || op.kind === 'setStamps') continue
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
    if (op.kind === 'replyPendingNote') { pendingReplies.push({ parentLocalId: op.parentLocalId, pageIndex: target.index, contents: op.contents, createdMs: op.createdMs, ...(op.author?{author:op.author}:{}) }); continue }
    if (op.kind === 'replyNote') {
      const note = target.notes.find(note => note.annotationId === op.annotationId), parent = replyTargets.get(op.annotationId)
      if (!target.notesReadSafe || !note?.replyable || !parent || note.expectedAnnotationSha256 !== op.expectedAnnotationSha256 || parent.pageIndex !== target.index) throw new Error('pdf_reply_parent_invalid_or_readonly')
      replies.push({ target: parent, contents: op.contents, createdMs: op.createdMs, ...(op.author ? { author: op.author } : {}) }); continue
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
    if (op.kind === 'removeDrawing') {
      const drawing=target.drawings.find(item=>item.annotationId===op.annotationId)
      if (!target.drawingsReadSafe || !drawing || !drawing.removable || drawing.expectedAnnotationSha256!==op.expectedAnnotationSha256 || removedIds.has(op.annotationId)) throw new Error('pdf_drawing_identity_invalid_or_readonly')
      removedIds.add(op.annotationId)
      removals.push({pageIndex:target.index,annotationId:op.annotationId,expectedAnnotationSha256:op.expectedAnnotationSha256,subtype:drawing.subtype,unlinkDrawing:true})
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
      addedNoteDates.push({ pageIndex: target.index, contents: op.text, rect: [x1, y2 - 18, x1 + 20, y2].map(value => Math.round(value * 100) / 100), localId:op.localId??('operation:'+ops.indexOf(op)), ...(op.createdMs === undefined ? {} : { createdMs: op.createdMs }) })
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
  const metadataOps=ops.filter(op=>op.kind==='setMetadata')
  if(metadataOps.length>1)throw Error('文档属性不能重复设置')
  if(metadataOps.length){
    if(!model.capabilities.editMetadata)throw Error(model.capabilities.editMetadataReason??'来源文档属性仅可查看')
    validateMetadataOperation(metadataOps[0],model.sourceSha256);request.metadata=metadataOps[0]!.metadata
  }
  const outlineOps=ops.filter(op=>op.kind==='setOutline')
  if(outlineOps.length>1)throw Error('书签树替换不能重复')
  if(outlineOps.length){
    if(!model.outlineEditable)throw Error(model.outlineReason??'来源书签不能编辑')
    request.outline=outlineWriteRequest(outlineOps[0]!.tree,model.pages,blankIndex,deleted)
  }
  const prepared = hasText ? await prepareTextEdits(content, model.pages, ops) : { edits: [], indices: [], skipped: [] as SkippedOperation[] }
  const batesOps=ops.filter(op=>op.kind==='addBates')
  if(batesOps.length&&!model.capabilities.bates)throw Error(model.capabilities.batesReason??'来源不能添加 Bates 编号')
  const batesPlans=prepareBates(ops,model.sourceSha256,model.pages,blankIndex,deleted)
  request.textInserts=batesPlans.map(plan=>plan.input)
  request.textEdits = prepared.edits
  const skippedOperations = [...prepared.skipped]
  const remaining = ops.filter((_, index) => !skippedOperations.some(item => item.operationIndex === index))
  let bytes = await removeSourceMarkups(content, model.sourceSha256, removals, noteEdits)
  const staticPlan=await prepareStaticFills(bytes,ops as Record<string,unknown>[],model.sourceSha256,request.rotations??[])
  bytes=staticPlan.bytes
  if(staticPlan.records.length||model.staticFormFills.length||ops.some(op=>op.kind==='removeStaticFill'))request.staticFormFills=staticPlan.records.filter(record=>!redactions.some(redaction=>redaction.pageIndex===record.pageIndex&&Math.min(record.rect[2],redaction.rect[2])>Math.max(record.rect[0],redaction.rect[0])&&Math.min(record.rect[3],redaction.rect[3])>Math.max(record.rect[1],redaction.rect[1])))
  const annotationBaseBytes = bytes
  if (request.staticFormFills!==undefined || remaining.some(op => !(op.kind === 'addTextAnnotation' && op.localId && deferredIds.has(op.localId)) && !['redact', 'editNote', 'removeNote', 'removeMarkup', 'removeDrawing', 'cropPage', 'setPageSize', 'addAttachment', 'removeAttachment', 'replyNote', 'replyPendingNote'].includes(op.kind))) {
    let result:Awaited<ReturnType<typeof applySaveRequest>>
    try{result=await applySaveRequest(bytes,request)}catch(error){
      if(!ops.some(op=>op.kind==='setStaticFill'||op.kind==='removeStaticFill'))throw error
      // PDFium 已返回实际图像内容字节；后续 metadata/其他写入失败不能丢弃它。
      const appliedOperationIndices=ops.flatMap((op,index)=>op.kind==='setStaticFill'||op.kind==='removeStaticFill'?[index]:[])
      const skippedOperations=ops.flatMap((op,index)=>appliedOperationIndices.includes(index)?[]:[{operationIndex:index,kind:op.kind,...('pageId' in op?{pageId:op.pageId}:{}),reason:'pdf_static_fill_followup_write_failed_generated_bytes_retained: '+String(error)}])
      const reviewIssues=[{operationIndex:appliedOperationIndices[0]??0,kind:'setStaticFill',fieldName:'',code:'pdf_static_fill_metadata_write_failed',message:'静态填写内容已生成，但后续元数据或其他修改写入失败；实际 PDF 已保留，静态填写可能无法再次编辑，请人工核对：'+String(error)}]
      const outputSha256=sha256(bytes)
      return {bytes,sourceSha256:model.sourceSha256,sha256:outputSha256,size:bytes.length,appliedOperationIndices,skippedOperations,reviewIssues,previewDigest:sha256(Buffer.from(JSON.stringify({sourceSha256:model.sourceSha256,operations:ops,outputSha256,appliedOperationIndices,skippedOperations,reviewIssues})))}
    }
    for(const skipped of result.skippedTextInserts){const plan=batesPlans[skipped.editIndex];if(plan)skippedOperations.push({operationIndex:plan.operationIndex,kind:'addBates',pageId:plan.pageId,reason:'pdf_bates_insert_skipped: '+skipped.reason})}
    if (result.skippedTextEdits.length) {
      for (const index of prepared.indices) skippedOperations.push({ operationIndex: index, kind: 'replaceText', pageId: (ops[index] as {pageId:string}).pageId, reason: 'pdf_text_combined_edit_failed_original_retained' })
      request.textEdits = []
      bytes = ops.some(op => !['replaceText', 'editNote', 'removeNote', 'removeMarkup', 'removeDrawing', 'addAttachment', 'removeAttachment'].includes(op.kind)) ? (await applySaveRequest(bytes, request)).bytes : bytes
    } else bytes = result.bytes
  }
  const pendingMarkupReferences = await inspectAddedMarkupReferences(annotationBaseBytes, bytes, request.markups, request.drawings, finalOrder)
  const pendingReferences=new Map<string,AddedNoteReference>()
  bytes = await normalizeAddedNoteDates(annotationBaseBytes, bytes, addedNoteDates, request.markups.map(mark => mark.pageIndex), finalOrder, request.drawings,pendingReferences)
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
  bytes = await appendNoteReplies(bytes, hasText ? await rebindTextEditedReplies(content, bytes, replies, finalOrder) : replies, finalOrder)
  bytes = await appendLocalNoteReplies(bytes, localRoots, pendingReplies, finalOrder,pendingReferences)
  if (redactions.length) {
    // 涂黑是最终序列化：PDFium 另存只写清理后可达对象，之后不再有 pdf-lib 写入可复活旧内容流。
    // 页缩略图与 PieceInfo 可能保留涂黑前的渲染，先删除；页索引换算到最终页序。
    const mapped = redactions.map(item => ({ pageIndex: finalOrder.indexOf(item.pageIndex), rect: item.rect }))
    if (mapped.some(item => item.pageIndex < 0)) throw new Error('PDF 涂黑页面身份无效')
    const output = await PDFDocument.load(bytes, { updateMetadata: false })
    assertRedactionAnnotationSafety(output, mapped)
    for (const index of new Set(mapped.map(item => item.pageIndex))) { output.getPage(index).node.delete(PDFName.of('Thumb')); output.getPage(index).node.delete(PDFName.of('PieceInfo')) }
    bytes = await redactPdf(await output.save({ useObjectStreams: false, updateFieldAppearances: false }), mapped)
  }
  const appliedOperationIndices = ops.map((_, index) => index).filter(index => !skippedOperations.some(item => item.operationIndex === index))
  // 新根身份只来自本次已核验的append位置及新PDFRef；最终复读不一致时不签发该映射。
  const finalModel=pendingReferences.size || pendingMarkupReferences.size ? await inspectPdf(bytes) : null
  const pendingNoteMapping=ops.flatMap((op,operationIndex)=>{
    if(op.kind!=='addTextAnnotation'||!appliedOperationIndices.includes(operationIndex))return []
    const reference=pendingReferences.get(op.localId??('operation:'+operationIndex)),page=reference&&finalModel?.pages[reference.pageIndex]
    const notes=page?.notes.filter(note=>note.sourceRef===reference!.sourceRef&&note.expectedAnnotationSha256===reference!.expectedAnnotationSha256&&!note.parentAnnotationId)??[]
    return reference&&page&&notes.length===1?[{operationIndex,pageId:op.pageId,...(op.localId?{localId:op.localId}:{}),effectivePageId:page.pageId,annotationId:notes[0].annotationId,sourceRef:reference.sourceRef,expectedAnnotationSha256:reference.expectedAnnotationSha256}]:[]
  })
  let markupIndex = 0
  const pendingMarkupMapping = ops.flatMap((op, operationIndex) => {
    if (op.kind !== 'addMarkup' && op.kind !== 'highlight') return []
    const reference = pendingMarkupReferences.get(markupIndex++)
    if (!reference || sizeOp || redactions.length || !appliedOperationIndices.includes(operationIndex)) return []
    const page = finalModel?.pages[reference.pageIndex]
    const matches = page?.markups.filter(mark => mark.sourceRef === reference.sourceRef && mark.expectedAnnotationSha256 === reference.expectedAnnotationSha256) ?? []
    return page && matches.length === 1 ? [{ operationIndex, pageId: op.pageId, effectivePageId: page.pageId, annotationId: matches[0].annotationId, sourceRef: reference.sourceRef, expectedAnnotationSha256: reference.expectedAnnotationSha256 }] : []
  })
  // Bind confirmation to actual output font programs, text/bounds, output identity,
  // runtime WASM identity, requested operations and all application decisions.
  const savedFormFields = formOps.length ? (await inspectPdf(bytes)).formFields : []
  for (const op of formOps) {
    const field = savedFormFields.find(item => item.name === op.name)
    const expected = op.fieldKind === 'checkbox' ? op.checked : op.value
    if (!field || field.value !== expected) throw new Error('PDF 表单字段写回后复读不一致')
  }
  const reviewIssues: {operationIndex:number;kind:string;code:string;fieldName:string;message:string;details?:unknown}[] = []
  if(metadataOps.length){
    try{bytes=await freezeMetadataDate(bytes,metadataOps[0]!)}catch(error){reviewIssues.push({operationIndex:ops.indexOf(metadataOps[0]!),kind:'setMetadata',fieldName:'',code:'pdf_metadata_date_review_failed',message:'文档属性修改时间复核失败，实际生成文件已保留：'+String(error)})}
    reviewIssues.push(...await reviewMetadataOutput(bytes,metadataOps[0]!,ops.indexOf(metadataOps[0]!)))
  }
  reviewIssues.push(...await reviewBatesOutput(bytes,batesPlans,finalOrder))
  if(request.staticFormFills!==undefined)reviewIssues.push(...await reviewStaticFills(bytes,request.staticFormFills.flatMap(record=>{const pageIndex=finalOrder.indexOf(record.pageIndex);return pageIndex<0?[]:[{...record,pageIndex}]}),ops as Record<string,unknown>[]))
  // Advisory crop review must never invalidate confirmation of identical output.
  const measureCropIssues=await reviewMeasureLabelClipping(bytes,ops.flatMap((op,operationIndex)=>op.kind==='addDrawing'&&op.shape==='measure'&&appliedOperationIndices.includes(operationIndex)?[{operationIndex,pageIndex:finalOrder.indexOf(byId.get(op.pageId)?.index??-1),from:op.from!,to:op.to!,label:op.label!}]:[]))
  let formReviewDocument: PDFDocument | undefined
  for (const op of formOps.filter(op => op.fieldKind === 'text')) {
    try {
      formReviewDocument ??= await PDFDocument.load(bytes, {updateMetadata:false})
      const issue = await inspectFormTextOverflow(formReviewDocument, op.name)
      if (issue) reviewIssues.push({operationIndex:ops.indexOf(op),kind:op.kind,...issue})
    } catch (error) {
      reviewIssues.push({operationIndex:ops.indexOf(op),kind:op.kind,code:'pdf_form_text_overflow_review_failed',fieldName:op.name,
        message:'字段“'+op.name+'”的文字裁切风险复核失败；实际生成文件已保留，请人工核对：'+String(error)})
    }
  }
  if(request.outline)reviewIssues.push(...await reviewPdfOutline(bytes,request.outline,finalOrder,model.sourceSha256,ops.indexOf(outlineOps[0]!)))
  const outputIdentity = hasText ? (await inspectNativeText(bytes, sha256(bytes))).map(page => page.map(({ objectId, ...object }) => object)) : null
  const resizedIdentity = sizeOp ? { sha256: sha256(bytes), pages: (await inspectPdf(bytes)).pages } : null
  const resources = hasText ? await textResourcesIdentity() : null
  const previewDigest = sha256(Buffer.from(JSON.stringify({ sourceSha256: model.sourceSha256, operations: ops, appliedOperationIndices, skippedOperations, reviewIssues, pendingNoteMapping, pendingMarkupMapping, outputIdentity, savedFormFields, resources, resizedIdentity, ...(ops.some(op => ['setStaticFill', 'removeStaticFill', 'setMetadata', 'addBates', 'setOutline', 'redact', 'addMarkup', 'addDrawing', 'setStamps', 'removeMarkup', 'removeDrawing', 'editNote', 'removeNote', 'addTextAnnotation', 'addAttachment', 'removeAttachment', 'replyNote', 'replyPendingNote'].includes(op.kind)) ? { markupOutputSha256: sha256(bytes) } : {}) })))
  return { bytes, sourceSha256: model.sourceSha256, sha256: sha256(bytes), size: bytes.length, skippedOperations, appliedOperationIndices, reviewIssues: [...reviewIssues, ...measureCropIssues], pendingNoteMapping, pendingMarkupMapping, previewDigest }
}

export async function patchPdf(content: Uint8Array, rawOperations: unknown, expectedSha256: string) {
  const result = await patchPdfWithReceipt(content, rawOperations, expectedSha256)
  if (result.skippedOperations.length) throw new Error('pdf_text_operations_skipped')
  return result.bytes
}
