import {NativeDocxSplit} from './docx-native-split'
import {NativeNewRichParagraph} from './docx-new-rich-paragraph'
import {docxMirrorMarginsOperations,withDocxMirrorMargins,currentDocxMirrorMargins} from './docx-mirror-margins'
import {normalizeDocxTableStyle,replayDocxTableStyle} from './docx-table-style'
import {normalizeDocxPictureFormats,projectDocxPictureFormat} from './docx-picture-format'
import {createDocxPictureFormatControls} from './docx-picture-format-controls'
import {pageAt,visiblePageCount} from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-slices'
import {pagePaperEdges} from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-cuts'
import {NativeDocxChartFields,createDocxChartFields,normalizeDocxChartFields,replayDocxChartFields,assertDocxChartFieldBatch,isDocxChartFieldOperation,type DocxChartTarget,type DocxFieldTarget} from './docx-chart-fields'
import {createDocxChartFieldControls} from './docx-chart-fields-ui'
import {createDocxInsertObjectControls} from './docx-insert-object-ui'
import {createDocxExportControls} from './docx-export'
import {mountDocxPasteUi} from './docx-paste-ui'
import {NativeDocxRichPaste,createDocxRichPaste} from './docx-rich-paste'
import {EquationEditListener} from './docx-equation-source'
import {NativeDocxEquations,createDocxEquations} from './docx-equations'
import type {DocxEquationsModel} from '../../../reporting/doc_engine/bridge/docx-equations-core'
import { createDocxPictureControls } from './docx-picture-controls'
import { normalizeDocxPictures } from './docx-pictures'
import { createDocxStylesPane } from './docx-styles-pane'
import { NativeStylesPane, normalizeStylesPane, stylesPaneOperations, stylesPaneStyles, type StylesPaneModel } from './docx-styles-pane-operations'
import { NativeDocxFontDialog } from './docx-font-properties'
import { NativeDocxParagraphProperties } from './docx-paragraph-properties'
import { normalizeDocxDropCaps } from './docx-drop-cap'
import {createDocxRuler} from './docx-ruler'
import {createDocxGridlines, createDocxTableGridlines} from './docx-gridlines'
import {createDocxNavigation} from './docx-navigation'
import {createDocxOutlineView} from './docx-outline-view'
import {resetDocxHistory} from './docx-refresh-history'
import {NativeDocxCrossReference,assertDocxCrossReferencesBatch,createDocxCrossReferenceControls,normalizeDocxCrossReferences,replayDocxCrossReferences,verifiedDocxCrossReferenceModel,type DocxCrossReferencesModel} from './docx-cross-reference'
import {NativeDocxCaption,assertDocxCaptionBatch,createDocxCaption,normalizeDocxCaption,replayDocxCaption,isDocxCaptionOperation} from './docx-caption'
import {createDocxCaptionDialog} from './docx-caption-dialog'
import { docxAIReadSelection } from './docx-ai-read-selection'
import {assertDocxBookmarksBatch,createDocxBookmarksControls,normalizeDocxBookmarks,replayDocxBookmarks,verifiedDocxBookmarksModel,type DocxBookmarksModel} from './docx-bookmarks'
import {assertDocxCommentReplyBatch,createDocxCommentReplyControls,normalizeDocxCommentReplies,replayDocxCommentReplies,verifiedDocxCommentReplyModel,type DocxCommentReplyModel} from './docx-comment-reply'
import {assertDocxCommentCreationBatch,createDocxCommentCreationControls,normalizeDocxCommentCreation,replayDocxCommentCreation,verifiedDocxCommentCreationModel,type DocxCommentCreationModel} from './docx-comment-create'
import { normalizeDocxTextRevisions } from './docx-text-revisions'
import { assertDocxTextRevisionBatch } from './docx-text-revisions-core'
import { createDocxTextRevisionControls } from './docx-text-revision-controls'
import { createDocxWordCountControl } from './docx-word-count'
import { createDocxReviewPresets } from './docx-review-presets'
import { createDocxSpellcheckControl } from './docx-spellcheck'
import { assertDocxTrackedChangesBatch, normalizeDocxTrackedChanges, replayDocxTrackedChanges } from './docx-tracked-changes'
import {docxTrackedInputProjection} from './docx-tracked-input-guard'
import { docxTrackRevisionsEnabled, withDocxTrackRevisions } from './docx-track-revisions'
import {createDocxReviewView,NativeDocxReviewChangedLines,revisionAuthorsOf,reviewRunsInView} from './docx-review-view'
import {collectHfRevisions,collectNoteRevisions,collectTextboxRevisions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/story-revisions'
import { assertDocxCommentTextBatch, commentTextOperationsOf, normalizeDocxCommentText, projectedDocxCommentTexts, replayDocxCommentText, verifiedDocxCommentTextModel, type DocxCommentTextModel } from './docx-comment-text'
import { createDocxCommentControls } from './docx-comment-controls'
import { assertDocxCommentThreadBatch, hiddenDocxCommentIds, isDocxCommentThreadOperation, normalizeDocxCommentThreads, projectedDocxCommentThreads, replayDocxCommentThreads, verifiedDocxCommentThreadModel, type DocxCommentThreadModel } from './docx-comment-thread'
import { NativeDocxToc, createDocxToc, normalizeDocxToc, replayDocxToc, isDocxTocOperation, assertDocxTocBatch } from './docx-toc'
import { getDocxNestedTableTargets, isDocxNestedParagraphs } from './docx-nested-tables'
import { loadDocxBundledFonts } from './docx-bundled-fonts'
import './assets/docx-cjk/fonts.css'
import './assets/docx-caladea/fonts.css'
import type { PageLayout } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/goto'
import { scopeDocxStyleRules } from './docx-style-scope'
import { newWidthPassState, resetWidthPassHistory } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-sections'
import { docxColumnFacts, applyDocxCanvasColumns, applyDocxCanvasHf } from './docx-columns'
import { sectionHfHeights } from './vendor/genoffice-docs/apps/docs/src/renderer/hf-heights'
import { createDocxHfProbeScope } from './docx-hf-probe-scope'
import { NativeDocxHistory, commitDocxNativeOperations, docxNativeOperations, docxNativeOperationsOf, seedDocxNativeOperations } from './docx-native-history'
import { hfVariantsFromParsed } from './vendor/genoffice-docs/apps/docs/src/renderer/doc-state'
import { layoutMixedDocxColumns, renderDocxCanvasPageBorders } from './docx-mixed-columns'
import { docxSectionSettingsWithPatch } from '../../../reporting/doc_engine/bridge/docx-section-settings'
import { setColumnLayout } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/column-layout'
import { setPageGaps } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/pagination-gaps'
import { NativeRibbonStyle } from './docx-style-majority'
import { currentFootnotes, currentDocxNotes, footnotePagination, endnotePagination } from './docx-footnote-pagination'
import { measureCurrentDocxPagination } from './docx-measure-current-pagination'
import { resolveDocxEdgeHfTarget } from './docx-edge-hf-target'
import { NativeCellBorders } from './docx-cell-borders'
import { normalizePlainDocxRuns, replayPlainDocxRuns } from './docx-plain-paragraph-runs'
import { closeHistory } from '@tiptap/pm/history'
import { NativeDocxRulerIndent, applyDocxRulerIndent, docxRulerParagraphReason } from './docx-ruler-indent'
import { NativeDocxCustomList } from './docx-custom-list'
import { NativeDocxTabStops, applyDocxTabStops } from './docx-tab-stops'
import { TextSelection } from '@tiptap/pm/state'
import { applyDocxNotesIntent, notesOperationsOf, projectedDocxNotes, replayDocxNotes, normalizeDocxNotes, editDocxNoteOperations, type DocxNotesModel, type DocxNoteOperation } from './docx-notes'
import { createDocxNoteDialog, type DocxNotesController } from './docx-notes-source'
import { restoredSectionHfOperations, sectionHfLinkOperation, sectionHfState, plannedSectionHfTarget, resolveHf } from './docx-hf-sections'
import { bytesSha256 } from './source-validation'
import { Editor, Extension, type JSONContent } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { createRoot } from 'react-dom/client'
import { readSections, readSectionSettings, type HfPartInfo, type HeaderFooter, type SectionSettings } from '@genoffice/docx-engine'
import type { EditorShell } from './shell'
import type { createNativeApi, NativeContextResponse } from './native-api'
import type { NativeDraft } from './native-draft'
import { createDocxFindReplace } from './docx-find-replace'
import { docxOperations, replayDocxOperations, restoredDocxSectionOperation, restoredDocxSectionOperations, docxPageBorderSectionOperations, sectionBreakNode, type DocxAnchor, type DocxPmNode, type DocxSectionAnchor, type SectionBreakType, type SectionChangeResult, type SectionValues } from './docx-operations'
import { docxHeaderFooterOperation, mergeDocxHeaderFooterOperation, restoredDocxHeaderFooterOperations, type DocxHeadersFootersModel, type DocxHfFlags, type DocxHfPart, type DocxHfVariant } from './docx-hf'
import type { DocxHeaderFooterController, DocxHfPendingEditor } from './docx-hf-source'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { normalizeDocxAutoFitSources } from './docx-table-autofit'
import { normalizeDocxColumnWidthSources } from './docx-table-column-width'
import { withDocxTableAlignmentDisplayIndents } from './docx-table-alignment-baseline'
import { createDocxRibbon } from './docx-ribbon'
import {createDocxMailMergeControls} from './docx-mail-merge-controls'
import { docxPageColorModel, docxPageColorOperations, effectiveDocxPageColor, withDocxPageColor } from './docx-page-color'
import { effectiveDocxPageBorder, withDocxPageBorder } from './docx-page-borders'
import { pictureWatermarkPreviewImage, textWatermarkPreviewImage } from '@genoffice/docx-engine'
import { hfWashoutFilter } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-dom'
import { docxWatermarkModel, docxWatermarkOperations, effectiveDocxWatermark, withDocxWatermark } from './docx-watermark'
import { createDocxViewCommands } from './docx-view'
import { createDocxFormattingMarks } from './docx-formatting-marks'
import { parseDocxOffThread } from './vendor/genoffice-docs/apps/docs/src/renderer/parse-off-thread'
import { blocksToPmDoc, pmDocOptions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { sourceEmptyDocxParagraphs } from './docx-empty-paragraph'
import { DocNestedTable, DocTableRow, editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { PaginationPreview } from './vendor/genoffice-docs/apps/docs/src/renderer/components/PaginationPreview'
import { docStyleCss } from './vendor/genoffice-docs/apps/docs/src/renderer/doc-style-css'
import { adoptEmbeddedFonts } from './vendor/genoffice-docs/apps/docs/src/renderer/embedded-fonts'
import { setResolverFontTable } from './vendor/genoffice-docs/apps/docs/src/renderer/font-resolve'
import { setStaticAsciiResolver } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/protected-render'
import './vendor/genoffice-docs/scoped.css'
import './docx.css'
import './docx-outline-view.css'
import './office-theme.css'

interface WordModel { editableFields?:DocxFieldTarget[]; sourceSha256: string; trackRevisions?: boolean; trackRevisionsReadOnlyReason?: string | null; blocks: (Omit<DocxAnchor, 'docxIndex'> & { type: string })[]; sections: DocxSectionAnchor[]; headersFooters?: DocxHeadersFootersModel; notes?: DocxNotesModel; comments?: DocxCommentTextModel; commentCreation?: DocxCommentCreationModel; commentReplies?: DocxCommentReplyModel; commentThreads?: DocxCommentThreadModel; bookmarks?: DocxBookmarksModel; crossReferences?:DocxCrossReferencesModel }
const sha256 = (bytes: ArrayBuffer | Uint8Array<ArrayBuffer>) => bytesSha256(bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes))

const part = (value: HfPartInfo | null | undefined): HeaderFooter | null => value ? { text: value.text, paras: value.paras, pageNumber: value.hasPageNumber } : null

/** GenOffice Docs 的真实 ProseMirror 画布；保存仅提交服务端允许的原文件操作。 */
export async function createDocxEditorView(shell: EditorShell, options: {
  api: ReturnType<typeof createNativeApi>; context: NativeContextResponse; draft: NativeDraft; onDraftChange?: () => void; onAssistant?: () => void; onReviewSummary?:()=>void; onAIPreset?: (instruction:string,selection:import('./docx-review-presets').DocxPresetSelection,scope:import('./docx-review-presets').DocxPresetScope)=>void; onNoteAI?: (selection:import('./native-api').NativeAINoteSelection,instruction?:string,beforeText?:string)=>void; onReviewAI?: (selection: import('./native-api').NativeAIReviewSelection, instruction?: string) => void; onSelectionChange?: (selection: { blockId: string; cellId?: string }[]) => void
}) {
  const [{createDocxDocumentTools,docxDocumentToolModels,docxDocumentToolOperations},{createDocxFieldControls},{installDocxAutocorrect,openDocxPreferencesDialog},{createDocxTableStyleControls},{createDocxContextMenu},{createDocxContextActions},{createDocxImageDrop},{createDocxFileActions},tableLifecycle,cellOperations]=await Promise.all([import('./docx-document-tools'),import('./docx-field-controls'),import('./docx-preferences'),import('./docx-table-style-controls'),import('./docx-context-menu'),import('./docx-context-actions'),import('./docx-image-drop'),import('./docx-file-actions'),import('./docx-table-lifecycle'),import('./docx-table-cell-operations')])
  const { api, context, draft } = options
  const expectedSha256 = context.context.sourceFile.sha256
  const [buffer, inspected] = await Promise.all([api.file(), !context.editingEnabled && context.wordReadAIEnabled
    ? api.readModel<WordModel>() : api.preview<WordModel>({ expectedSha256, operations: [] })])
  if (await sha256(buffer) !== expectedSha256 || inspected.model.sourceSha256 !== expectedSha256) throw new Error('Word 来源文件身份发生变化，请重新打开')
  const trackRevisionsModel = { sourceSha256: expectedSha256, enabled: inspected.model.trackRevisions === true, readOnlyReason: inspected.model.trackRevisionsReadOnlyReason ?? null }
  const parsed = await parseDocxOffThread(new Uint8Array(buffer))
  const commentsModel = inspected.model.comments ? verifiedDocxCommentTextModel(inspected.model.comments, expectedSha256, parsed.comments ?? []) : undefined
  const commentCreationModel = inspected.model.commentCreation ? verifiedDocxCommentCreationModel(inspected.model.commentCreation, expectedSha256) : undefined
  const commentRepliesModel = inspected.model.commentReplies ? verifiedDocxCommentReplyModel(inspected.model.commentReplies, expectedSha256, parsed.comments ?? []) : undefined
  const commentThreadsModel = inspected.model.commentThreads ? verifiedDocxCommentThreadModel(inspected.model.commentThreads, expectedSha256, parsed.comments ?? []) : undefined
  const bookmarksModel = inspected.model.bookmarks ? verifiedDocxBookmarksModel(inspected.model.bookmarks, expectedSha256) : undefined
  const crossReferencesModel = inspected.model.crossReferences ? verifiedDocxCrossReferenceModel(inspected.model.crossReferences,expectedSha256) : undefined
  const visible = parsed.blocks.filter(block => !block.hidden)
  if (visible.length !== inspected.model.blocks.length) throw new Error('Word 解析对象与服务端不一致')
  let anchors: DocxAnchor[] = []
  for (let index = 0; index < visible.length; index++) {
    const block = visible[index], anchor = inspected.model.blocks[index]
    if (block.docxIndex == null || block.type !== anchor.type || await sha256(new TextEncoder().encode(block.originalXml ?? '')) !== anchor.expectedObjectSha256
      || await sha256(new TextEncoder().encode(`${expectedSha256}:block:${block.docxIndex}`)) !== anchor.blockId) throw new Error('Word 对象身份校验失败')
    anchors.push({ ...anchor, docxIndex: block.docxIndex, tableWidthsTwips: block.table?.colWidthsTwips, tableHeaderCount: block.table?.repeatHeaderRows?.findIndex(header => !header) === -1 ? block.table.rows.length : block.table?.repeatHeaderRows?.findIndex(header => !header) ?? 0 })
  }
  setResolverFontTable(parsed.fontTable)
  await adoptEmbeddedFonts(parsed.embeddedFonts)
  await loadDocxBundledFonts()
  const sections = readSections(parsed), section = readSectionSettings(parsed), px = (twips: number) => twips / 15
  anchors = withDocxTableAlignmentDisplayIndents(anchors, parsed.blocks, sections, pmDocOptions(parsed))
  const tocSource = createDocxToc(parsed, anchors)
  const captionSource = createDocxCaption(parsed, anchors)
  const richPasteSource=createDocxRichPaste(expectedSha256,parsed.blocks)
  const equationSource=createDocxEquations((inspected.model as {equations?:DocxEquationsModel}).equations)
  // 全部节逐一核验身份（文档顺序，尾节在最后）；页面设置作用于光标所在节。
  if (!sections.length || inspected.model.sections.length !== sections.length) throw new Error('Word 页面设置的节身份校验失败')
  const sectionAnchors: DocxSectionAnchor[] = []
  for (const [index, item] of sections.entries()) {
    const source = inspected.model.sections[index]!
    if (source.sectionId !== await sha256(new TextEncoder().encode(`${expectedSha256}:section:${item.lastBlockIndex}`))
      || source.expectedSectionSha256 !== await sha256(new TextEncoder().encode(item.sectPrXml))) throw new Error('Word 页面设置的节身份校验失败')
    sectionAnchors.push({ sectionId: source.sectionId, expectedSectionSha256: source.expectedSectionSha256, settings: index === sections.length - 1 ? section : item.settings,
      headersFooters: source.headersFooters, firstBlockIndex: item.firstBlockIndex, lastBlockIndex: item.lastBlockIndex, pageNumberFmt: source.pageNumberFmt, pageNumberStart: source.pageNumberStart, pageNumberReadOnlyReason: source.pageNumberReadOnlyReason, titlePg: source.titlePg ?? null, titlePgReadOnlyReason: source.titlePgReadOnlyReason,
      ...(index === sections.length - 1 ? { evenAndOddHeaders: inspected.model.headersFooters?.evenAndOddHeadersReadOnlyReason ? null : inspected.model.headersFooters?.evenAndOddHeaders ?? null,
        evenAndOddHeadersReadOnlyReason: inspected.model.headersFooters?.evenAndOddHeadersReadOnlyReason ?? undefined } : {}) })
  }
  const sectionAnchor = sectionAnchors.at(-1)!
  let nativeOperations = () => draft.operations
  const sectionOperation = (operations = nativeOperations()) => restoredDocxSectionOperations(operations, sectionAnchors)
  sectionOperation()
  let activeSection = 0
  const sectionValues = (index: number) => sectionOperation().find(operation => operation.sectionId === sectionAnchors[index]!.sectionId)?.values as SectionValues | undefined
  const sectionAt = (docxIndex: number) => Math.max(0, sectionAnchors.findIndex(item => (item.firstBlockIndex ?? 0) <= docxIndex && docxIndex <= (item.lastBlockIndex ?? Infinity)))
  /** 本次草稿已在该节插入分节符（保存前该节不能再插入分节符或改页面设置）。 */
  const pendingBreakIn = (index: number) => draft.operations.some(operation => operation.kind === 'insertSectionBreak'
    && sectionAt(anchors.find(anchor => anchor.blockId === operation.blockId)?.docxIndex ?? -1) === index)
  const hfModel = inspected.model.headersFooters as DocxHeadersFootersModel | undefined
  const hfAnchor = { sectionId: sectionAnchor.sectionId, expectedSectionSha256: sectionAnchor.expectedSectionSha256 } as const
  // 恢复的页眉/页脚草稿必须与当前来源的部件身份一致；不一致即拒绝打开并保留草稿。
  const multiHf = sectionAnchors.every(section => !!section.headersFooters)
  const headerFooterOperations = (operations = nativeOperations()) => multiHf ? restoredSectionHfOperations(operations, sectionAnchors) : restoredDocxHeaderFooterOperations(operations, hfAnchor, hfModel)
  headerFooterOperations()
  const titlePageOf = (index: number) => {
    if (typeof sectionAnchors[index]!.titlePg !== 'boolean') return null
    const value = sectionValues(index)?.titlePg
    if (value !== undefined) return value
    if (index === sectionAnchors.length - 1) {
      const flags = headerFooterOperations().filter(operation => operation.sectionId === sectionAnchors[index]!.sectionId && typeof operation.titlePg === 'boolean')
      if (flags.length) return flags.at(-1)!.titlePg as boolean
    }
    return sectionAnchors[index]!.titlePg ?? null
  }
  const pageNumberOf = (index: number) => {
    const source = sectionAnchors[index]!, values = sectionValues(index)
    const result = { pageNumberFmt: source.pageNumberFmt, pageNumberStart: source.pageNumberStart }
    for (const key of ['pageNumberFmt', 'pageNumberStart'] as const) {
      if (values && Object.hasOwn(values, key)) Object.assign(result, { [key]: values[key] })
      else if (index === sectionAnchors.length - 1) {
        const latest = headerFooterOperations().filter(operation => operation.sectionId === sectionAnchor.sectionId && operation[key] !== undefined).at(-1)
        if (latest) Object.assign(result, { [key]: latest[key] })
      }
    }
    return result
  }
  const evenOddOf = () => {
    if (typeof sectionAnchor.evenAndOddHeaders !== 'boolean') return null
    const value = sectionValues(sectionAnchors.length - 1)?.evenAndOddHeaders
    if (value !== undefined) return value
    const flags = headerFooterOperations().filter(operation => typeof operation.evenAndOddHeaders === 'boolean')
    return flags.length ? flags.at(-1)!.evenAndOddHeaders as boolean : sectionAnchor.evenAndOddHeaders
  }
  const host = document.createElement('div'); host.className = 'docx-native'
  host.innerHTML = '<div class="docx-tools" role="toolbar" aria-label="Word 编辑"></div><p class="docx-notice" role="status">支持正文、基础样式、表格文字及符合条件表格的增删行列。每张表的结构修改需保存并重开后继续；不支持的编辑会提示原因。</p><div class="docx-navigation-layout"><div class="docx-navigation-host"></div><div class="editor-scroll"><div class="doc-zoom"><div class="docx-canvas"></div></div></div></div><div class="docx-preview-root"></div>'
  shell.editor.replaceChildren(host)
  const style = document.createElement('style'); style.dataset.docCss = ''; style.textContent = docStyleCss(parsed); host.append(style); if (style.sheet) scopeDocxStyleRules(style.sheet)
  const notice = host.querySelector<HTMLElement>('.docx-notice')!, toolbar = host.querySelector<HTMLElement>('.docx-tools')!
  const previewRoot = createRoot(host.querySelector<HTMLElement>('.docx-preview-root')!)
  let baseline: DocxPmNode, ready = false, refreshing = false, saving = false, readingMode = false, webMode = false
  let pendingHfEditor: DocxHfPendingEditor | null = null
  let crossReferenceControls:ReturnType<typeof createDocxCrossReferenceControls>|undefined
  let captionDialog:ReturnType<typeof createDocxCaptionDialog>|undefined
  let bookmarkControls: ReturnType<typeof createDocxBookmarksControls> | undefined
  let commentControls: ReturnType<typeof createDocxCommentControls> | undefined
  let commentCreationControls: ReturnType<typeof createDocxCommentCreationControls> | undefined
  let commentReplyControls: ReturnType<typeof createDocxCommentReplyControls> | undefined
  const reportError = (error: unknown) => { notice.textContent = error instanceof Error ? error.message : String(error) }
  const equationError=(event:Event)=>reportError((event as CustomEvent).detail)
  host.addEventListener('native-equation-error',equationError)
  const notesModel = inspected.model.notes
  // 固定源 Design ▸ Page Color：文档级非正文意图，随原生事务历史撤销/重做，按来源背景摘要绑定。
  const chartFieldSource=createDocxChartFields(anchors,(inspected.model as unknown as {editableCharts?:DocxChartTarget[]}).editableCharts??[],(inspected.model as unknown as {editableFields?:DocxFieldTarget[]}).editableFields??[])
  const sourceMirrorMargins=parsed.mirrorMargins===true
  const documentToolModels=docxDocumentToolModels(inspected.model)
  const mirrorMargins=()=>currentDocxMirrorMargins(nativeOperations(),documentToolModels.protection,sourceMirrorMargins)
  docxDocumentToolOperations(draft.operations,documentToolModels)
  docxMirrorMarginsOperations(draft.operations,documentToolModels.protection)
  const pageColorModel = docxPageColorModel((inspected.model as { pageColor?: unknown }).pageColor)
  docxPageColorOperations(draft.operations, pageColorModel)
  // 固定源 Design ▸ Watermark：文档级非正文意图，按全部页眉部件摘要绑定来源。
  const watermarkModel = docxWatermarkModel((inspected.model as { watermark?: unknown }).watermark)
  docxWatermarkOperations(draft.operations, watermarkModel)
  const stylesPaneModel = (inspected.model as { stylesPane?: StylesPaneModel }).stylesPane
  stylesPaneOperations(draft.operations, parsed.styles, stylesPaneModel)
  const currentStyles = (current: DocxPmNode) => stylesPaneStyles(parsed.styles, docxNativeOperationsOf(current))
  const isNote = (op: { kind?: unknown }) => ['insertNote', 'updateNote', 'deleteNote'].includes(String(op.kind))
  const collectOperationsUnchecked = (current: DocxPmNode, sectionOps = sectionOperation(docxNativeOperationsOf(current)), hfOps = headerFooterOperations(docxNativeOperationsOf(current)), operationBaseline = baseline) => {
    if (!notesModel) {
      if (notesOperationsOf(current).length) throw new Error('当前来源未提供脚注尾注编辑能力')
      try { return docxOperations(operationBaseline, current, anchors, sectionOps, editor.schema, currentStyles(current), hfOps,{numbering:parsed.numbering}) }
      catch (originalError) {
        try {
          const normalized = normalizePlainDocxRuns(operationBaseline, current, anchors)
          return [...docxOperations(normalized.baseline, normalized.current, anchors, sectionOps, editor.schema, currentStyles(current), hfOps,{numbering:parsed.numbering}), ...normalized.operations]
        } catch { throw originalError }
      }
    }
    let normalized = normalizeDocxNotes(operationBaseline, current, anchors, notesModel)
    try { return [...docxOperations(normalized.baseline, normalized.current, anchors, sectionOps, editor.schema, currentStyles(current), hfOps,{numbering:parsed.numbering}), ...normalized.operations] }
    catch {
      normalized = normalizeDocxNotes(operationBaseline, current, anchors, notesModel, true)
      return [...docxOperations(normalized.baseline, normalized.current, anchors, sectionOps, editor.schema, currentStyles(current), hfOps,{numbering:parsed.numbering}), ...normalized.operations]
    }
  }
  const collectOperations = (current: DocxPmNode, sectionOps = sectionOperation(docxNativeOperationsOf(current)), hfOps = headerFooterOperations(docxNativeOperationsOf(current))) => {
    const cells=cellOperations.normalizeDocxTableCellOperation(baseline,current,anchors,editor.schema)
    if(cells.operations.length)return cells.operations
    const lifecycle=tableLifecycle.normalizeDocxTableLifecycle(baseline,current,anchors,editor.schema)
    if(lifecycle.operations.length)return lifecycle.operations
    const tableStyles=normalizeDocxTableStyle(baseline,current,anchors,editor.schema)
    current=tableStyles.current
    const chartFields=normalizeDocxChartFields(baseline,current,chartFieldSource,editor.schema)
    current=chartFields.current
    const mergeOperations=docxNativeOperationsOf(current).filter(op=>['insertMailMergeField','mailMergeSingle'].includes(op.kind))
    assertDocxChartFieldBatch([...chartFields.operations,...mergeOperations])
    if(mergeOperations.length){
      if(tableStyles.operations.length)throw new Error('表格样式不能与邮件合并混合保存')
      const clean=(node:DocxPmNode)=>({...node,attrs:{...node.attrs,nativeDocxOperations:null}})
      if(mergeOperations.length!==1||docxNativeOperationsOf(current).length!==1||JSON.stringify(clean(current))!==JSON.stringify(clean(baseline)))throw new Error('邮件合并需独立保存，请先保存或撤销其他修改')
      return mergeOperations
    }
    const pasted=richPasteSource.normalize(baseline,current,editor.schema)
    current=pasted.current
    const equations=equationSource.normalize(baseline,current,editor.schema)
    current=equations.current
    const styleDefinitions = stylesPaneOperations(docxNativeOperationsOf(current), parsed.styles, stylesPaneModel)
    const pane = normalizeStylesPane(baseline, current, anchors, currentStyles(current), editor.schema)
    const crossReferences = normalizeDocxCrossReferences(baseline,pane.current,crossReferencesModel)
    const captions = normalizeDocxCaption(baseline,crossReferences.current,captionSource,editor.schema)
    const bookmarks = normalizeDocxBookmarks(baseline, captions.current, bookmarksModel)
    const toc = normalizeDocxToc(baseline, bookmarks.current, tocSource, editor.schema)
    const threads = normalizeDocxCommentThreads(baseline, toc.current, commentThreadsModel)
    const replies = normalizeDocxCommentReplies(baseline, threads.current, commentRepliesModel)
    const creations = normalizeDocxCommentCreation(baseline, replies.current, commentCreationModel)
    const comments = commentsModel ? normalizeDocxCommentText(baseline, creations.current, commentsModel) : { current: creations.current, operations: [] }
    if (!commentsModel && commentTextOperationsOf(current).length) throw new Error('当前来源未提供批注文字编辑能力')
    const tracked = normalizeDocxTrackedChanges(baseline, comments.current, anchors)
    const revisions = normalizeDocxTextRevisions(baseline, tracked.current, anchors, editor.schema)
    const pictureFormats=normalizeDocxPictureFormats(revisions.baseline,revisions.current,anchors)
    const pictures = normalizeDocxPictures(revisions.baseline, pictureFormats.current, anchors)
    const dropCaps = normalizeDocxDropCaps(revisions.baseline, pictures.current, anchors)
    const nativeOperations=docxNativeOperationsOf(current)
    const operations = [...tableStyles.operations,...pictureFormats.operations, ...chartFields.operations, ...pasted.operations, ...equations.operations, ...styleDefinitions, ...pane.operations, ...crossReferences.operations, ...captions.operations, ...bookmarks.operations, ...toc.operations, ...threads.operations, ...replies.operations, ...creations.operations, ...comments.operations, ...tracked.operations, ...revisions.operations, ...pictures.operations, ...dropCaps.operations, ...collectOperationsUnchecked(dropCaps.current, sectionOps, hfOps, revisions.baseline), ...docxDocumentToolOperations(nativeOperations,documentToolModels),...docxMirrorMarginsOperations(nativeOperations,documentToolModels.protection), ...docxPageColorOperations(nativeOperations, pageColorModel), ...docxWatermarkOperations(nativeOperations, watermarkModel), ...nativeOperations.filter(operation=>operation.kind==='setTrackRevisions')]
    if(operations.some(op=>op.kind==='setTableStyle')&&operations.length!==1)throw new Error('表格样式需独立保存，请先保存或撤销其他修改')
    if(operations.some(op=>op.kind==='formatImage')&&operations.length!==1)throw new Error('图片格式需单独保存，请先保存或撤销其他修改')
    assertDocxChartFieldBatch(operations)
    docxDocumentToolOperations(operations,documentToolModels)
    if(pasted.operations.length&&operations.length!==1)throw new Error('富文本粘贴请单独保存')
    if(operations.some(op=>op.kind==='editEquations')&&operations.length!==1)throw new Error('公式修改请单独保存')
    assertDocxBookmarksBatch(operations)
    assertDocxTocBatch(operations)
    assertDocxCrossReferencesBatch(operations)
    assertDocxCaptionBatch(operations)
    assertDocxCommentThreadBatch(operations)
    assertDocxCommentReplyBatch(operations)
    assertDocxCommentCreationBatch(operations)
    assertDocxCommentTextBatch(operations)
    assertDocxTextRevisionBatch(operations)
    assertDocxTrackedChangesBatch(operations)
    if (operations.length > 500) throw new Error('操作超过 500 条，请分批保存')
    return operations
  }
  const NativeTableStyle=Extension.create({name:'nativeTableStyle',addGlobalAttributes:()=>[{types:['docTable'],attributes:{nativeTableStyle:{default:null,rendered:false}}}]})
  const NativeBookmarkIntent = Extension.create({name:'nativeBookmarkIntent',addGlobalAttributes:()=>[{types:['doc'],attributes:{nativeBookmarkOperations:{default:null,rendered:false}}}]})
  const NativeNotesIntent = Extension.create({ name: 'nativeNotesIntent', addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeNotesOperations: { default: null, rendered: false } } }] })
  const NativeCommentTextIntent = Extension.create({ name: 'nativeCommentTextIntent', addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeCommentTextOperations: { default: null, rendered: false } } }] })
  const NativeCommentCreationIntent = Extension.create({name:'nativeCommentCreationIntent',addGlobalAttributes:()=>[{types:['doc'],attributes:{nativeCommentCreationOperations:{default:null,rendered:false}}}]})
  const NativeCommentReplyIntent = Extension.create({name:'nativeCommentReplyIntent',addGlobalAttributes:()=>[{types:['doc'],attributes:{nativeCommentReplyOperations:{default:null,rendered:false}}}]})
  const NativeCommentThreadIntent = Extension.create({
    name: 'nativeCommentThreadIntent',
    addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeCommentThreadOperations: { default: null, rendered: false } } }],
    addProseMirrorPlugins: () => [new Plugin({
      view: () => ({ update(view, previous) {
        const doc = view.state.doc
        if (doc === previous.doc || (!doc.attrs.nativeCommentThreadOperations && !previous.doc.attrs.nativeCommentThreadOperations)) return
        const hidden = hiddenDocxCommentIds(doc.toJSON(), commentThreadsModel)
        for (const mark of view.dom.querySelectorAll<HTMLElement>('[data-comment-ids]')) {
          mark.classList.toggle('native-comment-hidden', (mark.dataset.commentIds ?? '').split(/\s+/).every(id => hidden.has(id)))
        }
      } }),
    })],
  })
  const NativeTextRevisionIntent = Extension.create({ name: 'nativeTextRevisionIntent', addGlobalAttributes: () => [{ types: ['docParagraph', 'docHeading', 'docListItem'], attributes: { nativeTextRevisionOperations: { default: null, rendered: false } } }] })
  const Guard = Extension.create({ name: 'nativeOperationGuard', addProseMirrorPlugins: () => [new Plugin({
    filterTransaction(transaction) {
      if (!ready || refreshing || !transaction.docChanged) return true
      if (readingMode || saving || draft.saving || draft.closed || !context.editingEnabled) return false
      if(documentToolModels.protection?.contentLocked&&!transaction.before.content.eq(transaction.doc.content))return false
      try { collectOperations(transaction.doc.toJSON()); return true }
      catch (error) {
        // 原生 recorder 在 appendTransaction 才补 ins/del；仅验证其前置纯文本过渡，不将临时 diff 写入草稿。
        if(editor.storage.trackChanges.enabled&&!editor.view.composing&&!transaction.getMeta('composition')&&!transaction.getMeta('trackIgnore')&&!transaction.getMeta('history$'))try{
          const input=docxTrackedInputProjection(transaction,anchors)
          if(input){
            collectOperations(transaction.before.toJSON())
            collectOperationsUnchecked(input.current,sectionOperation(docxNativeOperationsOf(input.current)),headerFooterOperations(docxNativeOperationsOf(input.current)),input.baseline)
            return true
          }
        }catch{ /* 保留原严格校验错误；不放行不满足来源权限的事务。 */ }
        reportError(error);return false
      }
    },
  })] })
  let nestedInputActive = false, nestedInputError: string | null = null
  const nativeNestedTable = DocNestedTable.configure({
    validateParagraphs: paragraphs => isDocxNestedParagraphs(paragraphs) ? null : '嵌套表格文字包含暂不支持的控制字符或内容过长，请修改后保存',
    onCommitError: reason => { nestedInputError = reason; reportError(new Error(reason)) },
    canEditCell: (_node, pos, row, column, instance) => {
    if(readingMode||saving||draft.saving||draft.closed||!context.editingEnabled||documentToolModels.protection?.contentLocked)return false
    const resolved = instance.state.doc.resolve(pos)
    for (let depth = resolved.depth; depth > 1; depth--) {
      if (!['docTableCell', 'docTableHeader'].includes(resolved.node(depth).type.name)) continue
      const root = resolved.node(depth - 2), anchor = anchors.find(item => item.docxIndex === root.attrs.docxIndex)
      if (root.type.name !== 'docTable' || (root.attrs.nativeTableProperties || root.attrs.nativeTableStructure || root.attrs.nativeTableCellShape || root.attrs.nativeTableColumnWidths || root.attrs.nativeTableRowHeights || root.attrs.nativeTableAutoFit || root.attrs.nativeTableCellTextDirection || root.attrs.nativeTableCellAlignment || root.attrs.nativeTableCellMargins || root.attrs.nativeTableCellMarginOverrides || root.attrs.nativeTableRowBreaks || root.attrs.nativeTableAlignment || root.attrs.nativeTableCellWrap || root.attrs.nativeTableAltText)) return false
      let ordinal = 0
      for (let index = 0; index < resolved.index(depth); index++) if (resolved.node(depth).child(index).type.name === 'docNestedTable') ordinal++
      return anchor?.nestedTables?.find(item => item.row === resolved.index(depth - 2) && item.column === resolved.index(depth - 1) && item.nestedOrdinal === ordinal)?.cells[row]?.[column]?.editable === true
    }
    return false
  } })
  const flushPendingEdits = () => { nestedInputError = null; window.dispatchEvent(new Event('ai-docs-commit-tables')); if (nestedInputError) throw new Error(nestedInputError); pendingHfEditor?.flush(); commentControls?.flush(); commentCreationControls?.flush(); commentReplyControls?.flush() }
  let richPasteController:ReturnType<typeof richPasteSource.controls>|undefined
  const editor = new Editor({ element: host.querySelector<HTMLElement>('.docx-canvas')!, extensions: [...editorExtensions.map(extension => extension.name === 'docNestedTable' ? nativeNestedTable : extension.name === 'docTableRow' ? DocTableRow.extend({ content: '(docTableCell | docTableHeader)*' }) : extension), NativeNewRichParagraph, NativeDocxSplit, NativeTableStyle, NativeTableStructure, NativeCellBorders, NativeBookmarkIntent, NativeNotesIntent, NativeCommentTextIntent, NativeCommentCreationIntent, NativeCommentReplyIntent, NativeCommentThreadIntent, NativeTextRevisionIntent, NativeDocxReviewChangedLines, NativeRibbonStyle, NativeDocxCustomList, NativeDocxRulerIndent, NativeDocxTabStops, NativeDocxParagraphProperties, NativeDocxFontDialog, NativeStylesPane, NativeDocxToc, NativeDocxCrossReference, NativeDocxCaption, NativeDocxEquations, NativeDocxRichPaste, NativeDocxHistory, NativeDocxChartFields, Guard],
    content: sourceEmptyDocxParagraphs(blocksToPmDoc(parsed.blocks, sections, pmDocOptions(parsed)) as DocxPmNode, parsed.blocks) as JSONContent,
    editable: context.editingEnabled && !documentToolModels.protection?.contentLocked,
    editorProps: { handleDOMEvents:{paste:(_view,event)=>{if(event.target instanceof HTMLElement&&event.target.closest('.doc-nested-table'))return false;const data=(event as ClipboardEvent).clipboardData;if(!data?.getData('text/html'))return false;event.preventDefault();try{richPasteController?.paste({html:data.getData('text/html'),text:data.getData('text/plain')})}catch(error){reportError(error)}return true}}, attributes: { class: 'doc-page', 'aria-label': 'Word 文档编辑区', role: 'textbox', 'aria-multiline': 'true' } },
    onSelectionUpdate: ({ editor }) => {
      if (!(document.activeElement instanceof HTMLElement) || !document.activeElement.closest('.doc-nested-table')) nestedInputActive = false
      const { $from } = editor.state.selection
      // 当前节：光标所在顶层块（或其前最近的原有块）的 docxIndex 所属节。
      let top = $from.depth > 0 ? $from.index(0) : 0, sectionIndex: number | undefined
      for (; top >= 0 && sectionIndex === undefined; top--) {
        const docxIndex = editor.state.doc.maybeChild(top)?.attrs.docxIndex
        if (docxIndex != null) sectionIndex = sectionAt(Number(docxIndex))
      }
      if ((sectionIndex ?? 0) !== activeSection) {
        pendingHfEditor?.flush(); activeSection = sectionIndex ?? 0
        if (ready) { syncSection(); editor.commands.setMeta('native-section-layout', true) }
      }
      let anchor: DocxAnchor | undefined
      for (let depth = $from.depth; depth > 0; depth--) {
        const node = $from.node(depth)
        if (node.attrs.docxIndex != null) { anchor = anchors.find(item => item.docxIndex === node.attrs.docxIndex); if (anchor) break }
      }
      if (!anchor) { options.onSelectionChange?.([]); return }
      if (editor.state.doc.content.content.some(node => node.attrs.docxIndex === anchor!.docxIndex && (node.attrs.nativeTableStructure || node.attrs.nativeTableCellShape || node.attrs.nativeTableColumnWidths || node.attrs.nativeTableRowHeights || node.attrs.nativeTableAutoFit || node.attrs.nativeTableCellTextDirection || node.attrs.nativeTableCellAlignment || node.attrs.nativeTableCellMargins || node.attrs.nativeTableCellMarginOverrides || node.attrs.nativeTableRowBreaks || node.attrs.nativeTableAlignment))) { options.onSelectionChange?.([{ blockId: anchor.blockId }]); return }
      let cellId: string | undefined
      for (let depth = $from.depth; depth > 1; depth--) if (['docTableCell', 'docTableHeader'].includes($from.node(depth).type.name)) {
        cellId = anchor.cells?.[$from.index(depth - 2)]?.[$from.index(depth - 1)]?.cellId
        break
      }
      options.onSelectionChange?.([{ blockId: anchor.blockId, ...(cellId ? { cellId } : {}) }])
    },
    onUpdate: () => {
      if (!ready || refreshing) return
      try { draft.setOperations(collectOperations(editor.getJSON())); syncSection(); editor.commands.setMeta('native-section-layout', true); reviewView.setAuthors(reviewAuthors()); bookmarkControls?.refresh(); commentControls?.refresh(); commentCreationControls?.refresh(); commentReplyControls?.refresh(); options.onDraftChange?.() }
      catch (error) { reportError(error) }
    },
  })
  let refreshOpenPaginationPreview:(()=>void)|null=null
  let invalidateReviewLayout:(()=>void)|null=null
  let paginationPreviewOpen=false
  const reviewView = createDocxReviewView({host,editor,previewRoot:host.querySelector<HTMLElement>('.docx-preview-root'),initial:{mode:'all',insDel:true,format:true,hiddenAuthors:[]},onChange:()=>{invalidateReviewLayout?.();refreshOpenPaginationPreview?.()}})
  editor.storage.trackChanges.enabled = docxTrackRevisionsEnabled(trackRevisionsModel, draft.operations)
  const formattingMarks = createDocxFormattingMarks({ editor, root: host, sections })
  const nestedFocus = (event: FocusEvent) => {
    const target = event.target as HTMLElement | null
    if (!target || !editor.view.dom.contains(target)) return
    const active = !!target.closest('.doc-nested-table'), changed = active !== nestedInputActive
    nestedInputActive = active
    if (nestedInputActive) options.onSelectionChange?.([])
    if (changed) editor.commands.setMeta('native-nested-selection', true)
  }
  host.addEventListener('focusin', nestedFocus)
  editor.storage.listNumbering.styles = parsed.styles
  editor.storage.trackChanges.author = context.context.scope.userId
  editor.storage.listNumbering.docDefaults = parsed.docDefaults
  editor.storage.listNumbering.defs = parsed.numbering
  editor.storage.listNumbering.defaultTabTwips = parsed.defaultTabStopTwips ?? 720
  editor.storage.listNumbering.indentNotTabStop = parsed.indentNotNumberingTabStop === true
  editor.storage.tabStops.defaultTabStopTwips = parsed.defaultTabStopTwips ?? null
  setStaticAsciiResolver(() => editor.storage.listNumbering)
  /** 画布纸面按生效页面颜色预览（与固定源 --page-bg 一致；属于文档内容色，不受外壳 token 改写）。 */
  const syncPageColor = () => {
    const color = effectiveDocxPageColor(nativeOperations(), pageColorModel)
    if (color) host.style.setProperty('--page-bg', `#${color}`); else host.style.removeProperty('--page-bg')
    syncWatermark()
  }
  /** 画布纸面按生效的文字或图片水印预览。 */
  const syncWatermark = () => {
    const spec = effectiveDocxWatermark(nativeOperations(), watermarkModel)
    for (const page of host.querySelectorAll<HTMLElement>('.doc-page')) {
      page.querySelector('.docx-picture-watermark-preview')?.remove()
      if (!spec) { delete page.dataset.watermark; continue }
      if ('image' in spec) {
        delete page.dataset.watermark
        const mark = pictureWatermarkPreviewImage(spec, { widthPt: (section.pageWidth - section.marginLeft - section.marginRight) / 20, heightPt: (section.pageHeight - section.marginTop - section.marginBottom) / 20 })
        const image = document.createElement('img'); image.className = 'docx-picture-watermark-preview'; image.src = mark.dataUrl; image.alt = ''; image.setAttribute('aria-hidden', 'true')
        Object.assign(image.style, { position: 'absolute', pointerEvents: 'none', width: `${mark.widthPx}px`, height: `${mark.heightPx}px`, left: '50%', top: '50%', transform: 'translate(-50%,-50%)', opacity: '1', zIndex: '0', ...(mark.washout ? { filter: hfWashoutFilter(mark.washout) } : {}) }); page.prepend(image); continue
      }
      page.dataset.watermark = spec.text
      page.style.setProperty('--watermark-color', `#${spec.colorHex ?? 'C0C0C0'}`)
      page.style.setProperty('--watermark-opacity', String(spec.opacity ?? 0.5))
      page.style.setProperty('--watermark-rotate', spec.diagonal === false ? '0deg' : '-45deg')
      page.style.setProperty('--watermark-font', `"${spec.fontFamily ?? 'Calibri'}", sans-serif`)
      page.style.setProperty('--watermark-weight', spec.bold ? 'bold' : 'normal')
      page.style.setProperty('--watermark-style', spec.italic ? 'italic' : 'normal')
    }
  }
  const syncSection = () => {
    syncPageColor()
    const settings = docxSectionSettingsWithPatch(sectionAnchors[activeSection]!.settings, sectionValues(activeSection))
    sectionRibbon.mirrorMargins=mirrorMargins()
    sectionRibbon.settings = settings
    Object.assign(sectionRibbon, pageNumberOf(activeSection), { pageNumberReason: sectionAnchors[activeSection]!.pageNumberReadOnlyReason })
    sectionRibbon.titlePg = titlePageOf(activeSection)
    sectionRibbon.titlePgReason = sectionAnchors[activeSection]!.titlePgReadOnlyReason
    sectionRibbon.evenAndOddHeaders = evenOddOf()
    sectionRibbon.label = sections.length > 1 ? `第 ${activeSection + 1} 节，共 ${sections.length} 节` : undefined
    const canvasSections = sections.map((item, index) => ({ ...item, settings: docxSectionSettingsWithPatch(sectionAnchors[index]!.settings, sectionValues(index)) }))
    applyDocxCanvasColumns(editor.view.dom, docxColumnFacts(canvasSections, section))
  }
  editor.chain().setMeta('addToHistory', false).setMeta('trackIgnore',true).setContent(cellOperations.normalizeDocxTableCellSources(normalizeDocxAutoFitSources(normalizeDocxColumnWidthSources(editor.getJSON(), anchors, editor.schema), anchors, editor.schema),anchors,editor.schema) as JSONContent, { emitUpdate: false }).run()
  editor.chain().setMeta('addToHistory',false).setMeta('trackIgnore',true).setContent(equationSource.annotate(editor.getJSON()),{emitUpdate:false}).run()
  const readSourceDoc = editor.state.doc
  baseline = editor.getJSON()
  richPasteController=richPasteSource.controls(editor,()=>draft.operations,()=>nestedInputActive?'请退出嵌套表格编辑后再粘贴正文':pendingHfEditor?'请退出页眉页脚编辑后再粘贴正文':null)
  mountDocxPasteUi(editor,host,reportError)
  equationSource.controls(editor,()=>draft.operations,()=>nestedInputActive?'嵌套表格当前只支持文字编辑，不能将公式插入正文':pendingHfEditor?'请退出页眉页脚编辑后，在支持公式的正文或普通表格中选择位置':null)
  const equationHost=document.createElement('div');host.append(equationHost);const equationRoot=createRoot(equationHost);equationRoot.render(<EquationEditListener editor={editor}/>)
  editor.storage.nativeDocxCustomList.sourceDoc = editor.state.doc
  nativeOperations = () => docxNativeOperationsOf(editor.getJSON())
  for (const anchor of anchors) if (anchor.nestedTables?.length) {
    const root = baseline.content?.find(node => node.attrs?.docxIndex === anchor.docxIndex)
    if (!root) throw new Error('嵌套表来源根丢失')
    getDocxNestedTableTargets(root, anchor)
  }
  const disposeAutocorrect=installDocxAutocorrect(editor,anchors)
  let disposePreferences:(()=>void)|undefined
  ready = true
  const refresh = async () => {
    if (saving || draft.saving || draft.closed) throw new Error('当前文档正在保存或修订已关闭，不能刷新草稿')
    if (!context.editingEnabled && draft.operations.length) throw new Error('当前文档只读，不能安装编辑草稿')
    cellOperations.assertDocxTableCellOperationBatch(draft.operations)
    tableLifecycle.assertDocxTableLifecycleBatch(draft.operations)
    assertDocxChartFieldBatch(draft.operations)
    docxDocumentToolOperations(draft.operations,documentToolModels)
    assertDocxBookmarksBatch(draft.operations)
    assertDocxTocBatch(draft.operations)
    assertDocxCrossReferencesBatch(draft.operations)
    assertDocxCaptionBatch(draft.operations)
    assertDocxCommentThreadBatch(draft.operations)
    assertDocxCommentReplyBatch(draft.operations)
    assertDocxCommentCreationBatch(draft.operations)
    assertDocxCommentTextBatch(draft.operations)
    assertDocxTextRevisionBatch(draft.operations)
    assertDocxTrackedChangesBatch(draft.operations)
    sectionOperation(draft.operations)
    headerFooterOperations(draft.operations)
    const bookmarkOperations = draft.operations.filter(op => ['createBookmark', 'deleteBookmark'].includes(op.kind))
    if (bookmarkOperations.length && !bookmarksModel) throw new Error('当前来源未提供书签编辑能力')
    const noteOperations = draft.operations.filter(isNote)
    if (noteOperations.length && !notesModel) throw new Error('当前来源未提供脚注尾注编辑能力')
    const replyOperations = draft.operations.filter(op => op.kind === 'replyComment')
    if(replyOperations.length && !commentRepliesModel) throw new Error('当前来源未提供批注回复能力')
    const creationOperations = draft.operations.filter(op => op.kind === 'createComment')
    if(creationOperations.length && !commentCreationModel) throw new Error('当前来源未提供新建批注能力')
    const commentOperations = draft.operations.filter(op => op.kind === 'editCommentText')
    if (commentOperations.length && !commentsModel) throw new Error('当前来源未提供批注文字编辑能力')
    const threadOperations = draft.operations.filter(isDocxCommentThreadOperation)
    if (threadOperations.length && !commentThreadsModel) throw new Error('当前来源未提供批注线程编辑能力')
    const ordinary = replayDocxOperations(baseline, draft.operations.filter(op => !isDocxChartFieldOperation(op) && !['insertMailMergeField','mailMergeSingle'].includes(op.kind) && !isNote(op) && !isDocxCommentThreadOperation(op) && !isDocxTocOperation(op) && !isDocxCaptionOperation(op) && op.kind !== 'pasteRichContent' && op.kind !== 'editEquations' && op.kind !== 'insertCrossReference' && !['editTableCells','deleteTable','splitTable','setDocumentTheme','setDocumentProtection','setInk','resolveStoryRevision','formatImage','setTableStyle'].includes(op.kind) && op.kind !== 'patchParagraphRuns' && op.kind !== 'recordTextRevision' && op.kind !== 'editCommentText' && op.kind !== 'createComment' && op.kind !== 'replyComment' && op.kind !== 'createBookmark' && op.kind !== 'deleteBookmark'), anchors, sectionAnchors, editor.schema, stylesPaneStyles(parsed.styles, draft.operations), multiHf ? undefined : { anchor: hfAnchor, model: hfModel },{numbering:parsed.numbering})
    const trackedOperations = draft.operations.filter(op => op.kind === 'recordTextRevision')
    const tracked = replayDocxTrackedChanges(ordinary, trackedOperations, anchors, editor.schema, context.context.scope.userId, null)
    const plans = draft.operations.filter(op => op.kind === 'patchParagraphRuns')
    const noted = notesModel ? replayDocxNotes(tracked, noteOperations, anchors, notesModel, plans) : replayPlainDocxRuns(tracked, plans, anchors)
    const commented = commentsModel ? replayDocxCommentText(noted, commentOperations, commentsModel) : noted
    const created = commentCreationModel ? replayDocxCommentCreation(commented, creationOperations, commentCreationModel) : commented
    const replied = commentRepliesModel ? replayDocxCommentReplies(created, replyOperations, commentRepliesModel) : created
    const reviewed = commentThreadsModel ? replayDocxCommentThreads(replied, threadOperations, commentThreadsModel) : replied
    const bookmarked = bookmarksModel ? replayDocxBookmarks(reviewed, bookmarkOperations, bookmarksModel) : reviewed
    const tocContent = replayDocxToc(bookmarked, draft.operations, tocSource, editor.schema)
    if(draft.operations.some(op=>op.kind==='insertCrossReference')&&!crossReferencesModel) throw new Error('当前来源未提供交叉引用能力')
    const referenced = crossReferencesModel ? replayDocxCrossReferences(tocContent,draft.operations,crossReferencesModel) : tocContent
    const captioned = replayDocxCaption(referenced,draft.operations,captionSource,editor.schema)
    const contentBase = richPasteSource.replay(equationSource.replay(captioned,draft.operations,editor.schema),draft.operations,editor.schema)
    for(const op of draft.operations.filter(op=>op.kind==='formatImage')){if(draft.operations.length!==1)throw new Error('图片格式草稿不能混合其他修改');const anchor=anchors.find(a=>a.blockId===op.blockId);const index=contentBase.content?.findIndex(n=>n.attrs?.docxIndex===anchor?.docxIndex)??-1;if(!anchor||index<0)throw new Error('图片格式来源已变化');contentBase.content![index]=projectDocxPictureFormat(contentBase.content![index],anchor,op)}
    const content=cellOperations.replayDocxTableCellOperation(tableLifecycle.replayDocxTableLifecycle(replayDocxTableStyle(replayDocxChartFields(contentBase,draft.operations,chartFieldSource,editor.schema),draft.operations,anchors,editor.schema),draft.operations,anchors,editor.schema),draft.operations,anchors,editor.schema)
    const operations = docxNativeOperationsOf({type:'doc',attrs:{nativeDocxOperations:draft.operations}})
    const expected = editor.schema.nodeFromJSON({...content,attrs:{...content.attrs,
      nativeBookmarkOperations:bookmarkOperations.length?bookmarkOperations:null,
      nativeNotesOperations:noteOperations.length?noteOperations:null,
      nativeCommentTextOperations:commentOperations.length?commentOperations:null,
      nativeCommentCreationOperations:creationOperations.length?creationOperations:null,
      nativeCommentReplyOperations:replyOperations.length?replyOperations:null,
      nativeCommentThreadOperations:threadOperations.length?threadOperations:null,
      nativeDocxOperations:operations.length?operations:null,
    }})
    const previousState = editor.state, previousSection = activeSection, previousEditable = editor.isEditable
    refreshing = true
    try {
      editor.chain().setMeta('addToHistory',false).setMeta('trackIgnore',true).setContent(expected.toJSON(),{emitUpdate:false}).run()
      const transaction = editor.state.tr.setMeta('addToHistory',false)
      for (const [key,value] of Object.entries(expected.attrs)) transaction.setDocAttribute(key,value)
      editor.view.dispatch(transaction)
      seedDocxNativeOperations(editor,draft.operations)
      editor.storage.trackChanges.enabled = docxTrackRevisionsEnabled(trackRevisionsModel, draft.operations)
      if (!editor.state.doc.eq(expected)) throw new Error('草稿刷新未能完整安装，已保留原编辑状态')
      syncSection(); editor.commands.setMeta('native-section-layout',true)
      editor.setEditable(context.editingEnabled&&!readingMode&&!documentToolModels.protection?.contentLocked&&!saving&&!draft.saving&&!draft.closed,false)
      // 外部草稿成功成为新基线后，才清除旧正文/部件意图的撤销和重做。
      resetDocxHistory(editor)
    } catch (error) {
      editor.view.updateState(previousState)
      activeSection = previousSection
      editor.setEditable(previousEditable,false)
      syncSection()
      throw error
    } finally {
      refreshing = false
      navigation.refresh(); outline.refresh(); ruler.refresh()
      bookmarkControls?.refresh(); crossReferenceControls?.refresh(); captionDialog?.refresh()
      commentControls?.refresh(); commentCreationControls?.refresh(); commentReplyControls?.refresh()
    }
  }
  const prepareNotePagination = async (currentSections: typeof sections, currentSection: typeof section, stillCurrent: () => boolean) => {
    const doc = editor.state.doc
    const notes = await currentFootnotes({ bytes: new Uint8Array(buffer), parsed, doc, model: notesModel }, stillCurrent)
    const endnotes = await currentDocxNotes('endnote', { bytes: new Uint8Array(buffer), parsed, doc, model: notesModel }, stillCurrent)
    if (document.fonts) await document.fonts.ready
    if (!stillCurrent()) throw new Error('文档或注释发生变化，请重新打开分页或页眉页脚菜单')
    return { ...footnotePagination({ parsed, notes, doc, sections: currentSections, section: currentSection }),
      endnoteItems: endnotePagination({ parsed, notes: endnotes, doc, sections: currentSections, section: currentSection }) }
  }
  let currentColumnLayout: PageLayout | null = null
  let currentCanvasTop = px(section.marginTop)
  const resolvePaginationHf = (_live: typeof sections, index: number, kind: 'header' | 'footer', variant: DocxHfVariant) => {
    if (multiHf) return resolveHf(hfState(), index, kind, variant)
    if (!legacyHeaderFooter) return resolveHf({ sections: _live, edits: {}, links: {}, parsed,
      docStrips: { header: { text: parsed.headerText ?? '', paras: parsed.headerParas ?? undefined, pageNumber: parsed.headerHasPageNumber },
        footer: { text: parsed.footerText ?? '', paras: parsed.footerParas ?? undefined, pageNumber: parsed.footerHasPageNumber }, variants: hfVariantsFromParsed(parsed) } }, index, kind, variant)
    const found = legacyHeaderFooter?.valueOf(kind, variant)
    const source = found?.anchor.rId ? parsed.hfParts?.[found.anchor.rId] : undefined
    return { value: found?.value ?? null, images: source?.images, owner: index }
  }
  const columnWidthHistory = newWidthPassState()
  let columnHistoryDoc = editor.state.doc, columnHistoryGeometry = '', columnLayoutReady = false
  const layoutColumns = (currentSections: typeof sections, currentSection: typeof section, noteFacts: Awaited<ReturnType<typeof prepareNotePagination>>) => {
    if(readingMode||webMode){setColumnLayout(editor.view,[]);setPageGaps(editor.view,[]);editor.view.dom.style.removeProperty('height');currentColumnLayout=null;return}
    const hfHeights = sectionHfHeights(currentSections, (index, kind, variant) => resolvePaginationHf(currentSections, index, kind, variant), {
      titlePg: sectionAnchors.some((_, index) => titlePageOf(index) === true), evenOddHf: evenOddOf() ?? false, legacyBands: (parsed.compatibilityMode ?? 0) < 15,
    })
    currentCanvasTop = applyDocxCanvasHf(editor.view.dom, currentSections, currentSection, hfHeights[0]!, evenOddOf() ?? false)
    const geometry = JSON.stringify([currentSections, draft.operations, reviewView.state, hfHeights, currentCanvasTop, [...editor.view.dom.querySelectorAll('img')].map(image => [image.currentSrc, image.complete, image.naturalWidth, image.naturalHeight])])
    if (columnHistoryDoc !== editor.state.doc || columnHistoryGeometry !== geometry) {
      resetWidthPassHistory(columnWidthHistory); columnHistoryDoc = editor.state.doc; columnHistoryGeometry = geometry; columnLayoutReady = false; currentColumnLayout = null
    }
    // 源App仅在正文/布局输入变化时重排；Preview及prepareEdges复用同一已提交布局。
    if (columnLayoutReady) return
    const facts = docxColumnFacts(currentSections, section)
    if (facts.colMode !== 'mixed' && !facts.sectionWidths && !mirrorMargins() && !currentSections.some(item => item.settings.pageBorder)) {
      setColumnLayout(editor.view, []); setPageGaps(editor.view, []); editor.view.dom.style.removeProperty('height')
      const wrap = (editor.view.dom.closest('.page-wrap') as HTMLElement) ?? editor.view.dom
      renderDocxCanvasPageBorders(wrap, currentSection, 1)
      return
    }
    const result = layoutMixedDocxColumns(editor.view, { pm: editor.view.dom, sections: currentSections, section: currentSection,
      mirrorMargins: mirrorMargins(), canvasTop: currentCanvasTop, colMode: facts.colMode, colFlow: facts.colFlow, ...noteFacts,
      hfParts: parsed.hfParts ?? {}, legacyBands: (parsed.compatibilityMode ?? 0) < 15,
      hf: { header: { text: parsed.headerText ?? '', paras: parsed.headerParas ?? undefined, pageNumber: parsed.headerHasPageNumber },
        footer: { text: parsed.footerText ?? '', paras: parsed.footerParas ?? undefined, pageNumber: parsed.footerHasPageNumber },
        headerFirst: part(parsed.headerFirst), footerFirst: part(parsed.footerFirst), headerEven: part(parsed.headerEven), footerEven: part(parsed.footerEven),
        titlePg: sectionAnchors.some((_, index) => titlePageOf(index) === true), evenOddHf: evenOddOf() ?? false },
      resolveHf: resolvePaginationHf }, columnWidthHistory)
    currentColumnLayout = result.layout ?? null
    columnLayoutReady = true
    if (!result.converged) reportError(new Error(`多栏布局在 ${result.passes} 次测量后仍未收敛，当前分页需要复核`))
  }
  let previewRequest = 0
  const showPaginationPreview = async () => {
    flushPendingEdits()
    paginationPreviewOpen=true
    const request = ++previewRequest, doc = editor.state.doc, operations = JSON.stringify(draft.operations), geometrySection = activeSection, reviewState=JSON.stringify(reviewView.state)
    const stillCurrent = () => request === previewRequest && ready && !editor.isDestroyed && !draft.closed
      && editor.state.doc === doc && JSON.stringify(draft.operations) === operations && activeSection === geometrySection && JSON.stringify(reviewView.state)===reviewState && paginationPreviewOpen
    try {
    const currentSections = sections.map((item, index) => ({ ...item, titlePg: titlePageOf(index) ?? item.titlePg,
      pageNumberFmt: pageNumberOf(index).pageNumberFmt ?? undefined, pageNumberStart: pageNumberOf(index).pageNumberStart ?? undefined,
      settings: docxSectionSettingsWithPatch(sectionAnchors[index]!.settings, sectionValues(index)) }))
    const columnFacts = docxColumnFacts(currentSections, section)
    const currentSection = columnFacts.section
    const footnotes = await prepareNotePagination(currentSections, currentSection, stillCurrent)
    if (!stillCurrent()) return
    layoutColumns(currentSections, currentSection, footnotes)
    // 在React effect之前清旧gap，避免Tiptap节点视图在effect内flushSync。
    setPageGaps(editor.view, [])
    const commentTexts = commentsModel ? new Map(projectedDocxCommentTexts(commentsModel, commentTextOperationsOf(editor.getJSON(), commentsModel))
      .filter(target => target.editableText).map(target => [target.originalCommentId, target.text])) : undefined
    const previewComments = projectedDocxCommentThreads((parsed.comments ?? []).map(comment => ({ ...comment, text: commentTexts?.get(comment.id) ?? comment.text })), editor.getJSON(), commentThreadsModel)
    const watermarkDirty = nativeOperations().some(operation => operation.kind === 'setWatermark')
    const watermark = effectiveDocxWatermark(nativeOperations(), watermarkModel)
    const pendingWatermark = !watermark ? null : 'image' in watermark
      ? pictureWatermarkPreviewImage(watermark, { widthPt: (currentSection.pageWidth - currentSection.marginLeft - currentSection.marginRight) / 20, heightPt: (currentSection.pageHeight - currentSection.marginTop - currentSection.marginBottom) / 20 })
      : textWatermarkPreviewImage(watermark)
    if (!stillCurrent()) return
    const review=reviewView.state
    const previewResolveHf:typeof resolvePaginationHf=(...args)=>{
      const result=resolvePaginationHf(...args), value=result.value
      if(!value?.paras)return result
      const filter=(runs:NonNullable<HeaderFooter['paras']>[number]['runs'])=>reviewRunsInView(runs,review)
      return {...result,value:{...value,paras:value.paras.map(para=>({...para,runs:filter(para.runs),...(para.cells?{cells:para.cells.map(cell=>({...cell,paras:cell.paras.map(filter)}))}:{})}))}}
    }
    previewRoot.render(<PaginationPreview section={currentSection} sections={currentSections} canvasTop={currentCanvasTop} hfParts={parsed.hfParts ?? {}}
    watermarkDirty={watermarkDirty} pendingWatermark={pendingWatermark}
    {...footnotes}
    resolveHf={previewResolveHf}
    layout={() => currentColumnLayout}
    colFlow={columnFacts.colFlow} colMode={columnFacts.colMode} mirrorMargins={mirrorMargins()} comments={previewComments} anchorBlocks={parsed.blocks}
    hf={{ header: { text: parsed.headerText ?? '', paras: parsed.headerParas ?? undefined, pageNumber: parsed.headerHasPageNumber },
      footer: { text: parsed.footerText ?? '', paras: parsed.footerParas ?? undefined, pageNumber: parsed.footerHasPageNumber },
      headerFirst: part(parsed.headerFirst), footerFirst: part(parsed.footerFirst), headerEven: part(parsed.headerEven), footerEven: part(parsed.footerEven),
      titlePg: sectionAnchors.some((_, index) => titlePageOf(index) === true), evenOddHf: evenOddOf() ?? parsed.evenAndOddHeaders ?? false,
      images: { header: parsed.headerImages ?? undefined, footer: parsed.footerImages ?? undefined,
        headerFirst: parsed.headerFirst?.images, footerFirst: parsed.footerFirst?.images, headerEven: parsed.headerEven?.images, footerEven: parsed.footerEven?.images } }}
    onExportPdf={() => shell.exportPdf.click()} onClose={() => { paginationPreviewOpen=false; previewRequest++; previewRoot.render(null); columnLayoutReady = false; scheduleColumns() }} />)
  } catch (error) { if (stillCurrent() && ready && !editor.isDestroyed) reportError(error) }
  }
  refreshOpenPaginationPreview=()=>{if(paginationPreviewOpen)void showPaginationPreview()}
  const selectParagraph = () => {
    const { $from } = editor.state.selection
    for (let depth = $from.depth; depth > 0; depth--) if (['docParagraph', 'docHeading', 'docListItem'].includes($from.node(depth).type.name)) {
      return editor.chain().focus().setTextSelection({ from: $from.start(depth), to: $from.end(depth) })
    }
    throw new Error('请先选择正文段落')
  }
  const paragraphCommand = (command: 'add' | 'delete') => {
    try {
      if (command === 'add') {
        const { $from } = editor.state.selection
        const position = $from.depth ? $from.after(1) : editor.state.doc.content.size
        editor.chain().focus().insertContentAt(position, { type: 'docParagraph', attrs: { docxIndex: null }, content: [{ type: 'text', text: '新段落' }] }).run()
      } else selectParagraph().deleteNode(editor.state.selection.$from.parent.type.name).run()
    } catch (error) { reportError(error) }
  }
  /** 布局▸分隔符▸分节符（固定源 App.tsx insertSectionBreak）：插在光标所在顶层原有块之后。 */
  const insertSectionBreak = (type: SectionBreakType) => {
    try {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) throw new Error('当前文档不可编辑或正在保存')
      const { $from } = editor.state.selection
      if ($from.depth < 1) throw new Error('请先将光标放在段落中')
      const top = editor.state.doc.child($from.index(0)), docxIndex = top.attrs.docxIndex
      if (docxIndex == null) throw new Error('请将光标放在原有段落或表格中，再插入分节符（新增内容请先保存）')
      const index = sectionAt(Number(docxIndex))
      if (pendingBreakIn(index)) throw new Error('此节已插入分节符，请先保存再继续分节')
      if (sectionOperation().some(operation => operation.sectionId === sectionAnchors[index]!.sectionId)) throw new Error('此节的页面设置修改请先保存，再插入分节符')
      editor.chain().insertContentAt($from.after(1), sectionBreakNode(type) as JSONContent).run()
    } catch (error) { reportError(error) }
  }
  const commitPageSetup=(values:SectionValues,scope:'section'|'document',mirror?:boolean):SectionChangeResult=>{
    try{
      if(readingMode||saving||draft.saving||draft.closed||refreshing||!context.editingEnabled||!editor.isEditable)throw new Error('当前文档不可编辑或正在保存')
      const indices=scope==='document'?sectionAnchors.map((_,i)=>i):[activeSection]
      if(indices.some(i=>pendingBreakIn(i)))throw new Error('目标节已插入分节符，请先保存')
      const replacements=indices.flatMap(i=>{const a=sectionAnchors[i],operation=restoredDocxSectionOperation([{kind:'setSectionLayout',sectionId:a.sectionId,expectedSectionSha256:a.expectedSectionSha256,values:{...sectionValues(i),...values}}],a);return operation?[operation]:[]})
      const sectionsNext=[...sectionOperation().filter(op=>!indices.some(i=>sectionAnchors[i].sectionId===op.sectionId)),...replacements]
      const current=editor.getJSON() as DocxPmNode,journal=mirror===undefined?docxNativeOperationsOf(current):withDocxMirrorMargins(docxNativeOperationsOf(current),documentToolModels.protection,mirror,sourceMirrorMargins)
      current.attrs={...current.attrs,nativeDocxOperations:journal}
      const next=collectOperations(current,sectionsNext,headerFooterOperations())
      if(!commitDocxNativeOperations(editor,next)&&JSON.stringify(docxNativeOperationsOf(editor.getJSON()))!==JSON.stringify(docxNativeOperations(next)))throw new Error('页面设置未能进入草稿')
      syncSection();editor.commands.setMeta('native-section-layout',true)
    }catch(error){reportError(error);return {error:error instanceof Error?error.message:String(error)}}
  }
  const sectionRibbon = {
    mirrorMargins:mirrorMargins(),
    mirrorMarginsReason:documentToolModels.protection?.editable&&!documentToolModels.protection.contentLocked?undefined:'当前来源不支持镜像页边距',
    onMirrorMargins:(on:boolean,values:SectionValues={})=>commitPageSetup(values,'section',on),
    onPaperSizeAll:(width:number,height:number,orientation:'portrait'|'landscape')=>commitPageSetup({pageWidth:orientation==='landscape'?height:width,pageHeight:orientation==='landscape'?width:height,orientation},'document'),
    ...pageNumberOf(0),
    pageNumberReason: sectionAnchors[0]!.pageNumberReadOnlyReason,
    settings: section,
    titlePg: titlePageOf(0),
    titlePgReason: sectionAnchors[0]!.titlePgReadOnlyReason,
    evenAndOddHeaders: evenOddOf(),
    evenAndOddHeadersReason: sectionAnchor.evenAndOddHeadersReadOnlyReason,
    label: sections.length > 1 ? `第 1 节，共 ${sections.length} 节` : undefined as string | undefined,
    onSectionBreak: insertSectionBreak,
    pageBorders: () => {
      const openedDoc = editor.state.doc, openedSection = activeSection
      return {
        settings: docxSectionSettingsWithPatch(sectionAnchors[openedSection]!.settings, sectionValues(openedSection)),
        apply: (props: SectionSettings['pageBorderProps'] | null, scope: 'whole' | 'section'): SectionChangeResult => {
          try {
            if (saving || draft.saving || draft.closed || !context.editingEnabled || !editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
            if (editor.state.doc !== openedDoc || activeSection !== openedSection) throw new Error('文档或活动节已变化，请重新打开页面边框')
            const indices = scope === 'whole' ? sectionAnchors.map((_, index) => index) : [openedSection]
            if (indices.some(index => pendingBreakIn(index))) throw new Error('目标节已插入分节符，请先保存，再调整页面边框')
            const before = indices.map(index => docxSectionSettingsWithPatch(sectionAnchors[index]!.settings, sectionValues(index)))
            const operations = docxPageBorderSectionOperations(sectionOperation(), sectionAnchors, indices, props)
            const changed = indices.some((index, slot) => {
              const values = operations.find(item => item.kind === 'setSectionLayout' && item.sectionId === sectionAnchors[index]!.sectionId)?.values
              const after = docxSectionSettingsWithPatch(sectionAnchors[index]!.settings, values as SectionValues | undefined)
              return before[slot]!.pageBorder !== after.pageBorder || JSON.stringify(before[slot]!.pageBorderProps) !== JSON.stringify(after.pageBorderProps)
            })
            if (!changed) return
            const next = collectOperations(editor.getJSON(), operations, headerFooterOperations())
            if (!commitDocxNativeOperations(editor, next)) throw new Error('页面边框未能写入文档，请重试')
            syncSection()
            editor.commands.setMeta('native-section-layout', true)
          } catch (error) { reportError(error); return { error: error instanceof Error ? error.message : String(error) } }
        },
      }
    },
    onChange: (values: SectionValues): SectionChangeResult => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return { error: '当前文档不可编辑或正在保存' }
      let result: SectionChangeResult = undefined
      try {
        // 文档级奇偶页设置使用尾节身份作为保存锚，无论光标在哪一节。
        const targetIndex = values.evenAndOddHeaders !== undefined ? sectionAnchors.length - 1 : activeSection
        const target = sectionAnchors[targetIndex]!
        if (pendingBreakIn(targetIndex)) throw new Error('此节已插入分节符，请先保存，再调整页面设置')
        const merged = { ...sectionValues(targetIndex), ...values }
        if (values.pageBorder !== undefined && !Object.hasOwn(values, 'pageBorderProps')) delete merged.pageBorderProps
        const operation = restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId: target.sectionId,
          expectedSectionSha256: target.expectedSectionSha256, values: merged }], target)
        const others = sectionOperation().filter(item => item.sectionId !== target.sectionId)
        const hfOperations = headerFooterOperations().map(item => {
          const rest = { ...item }
          if (values.titlePg !== undefined && targetIndex === sectionAnchors.length - 1) delete rest.titlePg
          if (values.evenAndOddHeaders !== undefined) delete rest.evenAndOddHeaders
          if (targetIndex === sectionAnchors.length - 1) for (const key of ['pageNumberFmt', 'pageNumberStart'] as const) if (values[key] !== undefined) delete rest[key]
          return rest
        })
        const operations = collectOperations(editor.getJSON(), [...others, ...(operation ? [operation] : [])], hfOperations)
        if (!commitDocxNativeOperations(editor, operations) && JSON.stringify(docxNativeOperationsOf(editor.getJSON())) !== JSON.stringify(docxNativeOperations(operations))) throw new Error('页面设置未能写入文档，请重试')
      } catch (error) { reportError(error); result = { error: error instanceof Error ? error.message : String(error) } }
      syncSection()
      editor.commands.setMeta('native-section-layout', true)
      return result
    },
  }
  // 导航和首末页入口复用同一真实测量；异步等待后同时复核文档、草稿与活动节。
  const measurePagination = async (stillCurrent: () => boolean) => {
    const doc = editor.state.doc, operations = JSON.stringify(draft.operations), targetSection = activeSection
    const current = () => stillCurrent() && ready && !editor.isDestroyed && !draft.closed
      && editor.state.doc === doc && JSON.stringify(draft.operations) === operations && activeSection === targetSection
    const assertCurrent = () => { if (!current()) throw new Error('文档或页面设置发生变化，请重新打开页面导航') }
    assertCurrent()
    const currentSections = sections.map((item, index) => ({ ...item, titlePg: titlePageOf(index) ?? item.titlePg,
      pageNumberFmt: pageNumberOf(index).pageNumberFmt ?? undefined, pageNumberStart: pageNumberOf(index).pageNumberStart ?? undefined,
      settings: docxSectionSettingsWithPatch(sectionAnchors[index]!.settings, sectionValues(index)) }))
    const columnFacts = docxColumnFacts(currentSections, section)
    const currentSection = columnFacts.section
    // 固定源App边缘条使用document全局titlePg（parse对整个XML判定）；面板仍保留按节能力。
    const globalTitlePg = sectionAnchors.some((_, index) => titlePageOf(index) === true)
    const evenOddHf = evenOddOf()
    if (evenOddHf === null || sectionAnchors.some((_, index) => titlePageOf(index) === null)) throw new Error('页眉页脚变体的来源状态不可判定')
    const footnotes = await prepareNotePagination(currentSections, currentSection, current)
    layoutColumns(currentSections, currentSection, footnotes)
    const snapshot = currentColumnLayout ?? await measureCurrentDocxPagination({ pm: editor.view.dom, section: currentSection, sections: currentSections,
      blockMetaOf: footnotes.blockMetaOf,
      endnoteItems: footnotes.endnoteItems,
      mirrorMargins: mirrorMargins(), canvasTop: currentCanvasTop, colMode: columnFacts.colMode, colFlow: columnFacts.colFlow, hfParts: parsed.hfParts ?? {}, legacyBands: (parsed.compatibilityMode ?? 0) < 15,
      hf: { header: { text: parsed.headerText ?? '', paras: parsed.headerParas ?? undefined, pageNumber: parsed.headerHasPageNumber },
        footer: { text: parsed.footerText ?? '', paras: parsed.footerParas ?? undefined, pageNumber: parsed.footerHasPageNumber },
        headerFirst: part(parsed.headerFirst), footerFirst: part(parsed.footerFirst), headerEven: part(parsed.headerEven), footerEven: part(parsed.footerEven),
        titlePg: globalTitlePg, evenOddHf },
      resolveHf: resolvePaginationHf,
    }, current)
    assertCurrent()
    return { snapshot, currentSection, currentSections, columnFacts, globalTitlePg, evenOddHf }
  }
  const rulerReadOnlyReason = () => {
    if (saving || draft.saving || draft.closed || !context.editingEnabled || !editor.isEditable) return '当前文档不可编辑或正在保存'
    if (nestedInputActive) return '请先退出嵌套表格编辑'
    if (host.querySelector('.docx-navigation-layout')?.classList.contains('view-outline')) return '大纲视图仅显示标尺'
    if (pendingBreakIn(activeSection)) return '此节已插入分节符，请先保存'
    if (mirrorMargins()) return '镜像边距标尺暂不支持写回，请使用布局设置'
    return null
  }
  const ruler = createDocxRuler({ editor, container: host.querySelector<HTMLElement>('.doc-zoom')!, extendedIndents: true, editableTabs: true,
    onTabStopsChange: stops => applyDocxTabStops(editor, anchors, stops ?? []),
    getSection: () => (docxSectionSettingsWithPatch(sectionAnchors[activeSection]!.settings, sectionValues(activeSection))),
    getZoom: () => Number(host.dataset.docxZoom ?? 100) / 100,
    readOnlyReason: kind => {
      const locked = rulerReadOnlyReason()
      if (locked || kind === 'margins') return locked
      if ((sectionRibbon.settings.columns ?? 1) > 1) return '分栏段落标尺尚未接入栏坐标，请使用段落设置'
      return docxRulerParagraphReason(editor, anchors, kind)
    },
    onIndentsChange: attrs => {
      if (attrs.indentRight === undefined) { applyDocxRulerIndent(editor, anchors, attrs); return }
      const reason = ruler.reason('indentRight')
      if (reason) throw new Error(reason)
      const { $from } = editor.state.selection, node = $from.parent
      const right = attrs.indentRight
      if (!Number.isInteger(right) || right! < -14400 || right! > 14400) throw new Error('右缩进须为 -14400–14400 的整数 twips')
      editor.view.dispatch(editor.state.tr.setNodeMarkup($from.before(1), undefined, { ...node.attrs, indentRight: right }))
    },
    onMarginsChange: margins => sectionRibbon.onChange({ marginLeft: margins.left, marginRight: margins.right }),
    onError: reportError,
  })
  const gridlines = createDocxGridlines({editor,root:host.querySelector<HTMLElement>('.docx-navigation-layout')!})
  const tableGridlines = createDocxTableGridlines({editor,root:host.querySelector<HTMLElement>('.docx-navigation-layout')!})
  const navigation = createDocxNavigation({editor,container:host.querySelector<HTMLElement>('.docx-navigation-host')!,styles:new Map(parsed.styles),onError:reportError,onSearchNavigate:()=>outline.run('页面视图'),
    pages: { prepare: () => outline.run('页面视图'), getZoom: () => Number(host.dataset.docxZoom ?? 100) / 100,
      getPagination: async stillCurrent => {
        const { snapshot, currentSection, currentSections, columnFacts } = await measurePagination(stillCurrent)
        return { cuts: snapshot.cuts, geoms: snapshot.geoms, blocks: snapshot.blocks, rowSplits: snapshot.rowSplits,
          section: currentSection, sections: currentSections, colMode: columnFacts.colMode, mirrorMargins: mirrorMargins() }
      } },
    onVisibilityChange:()=>{editor.commands.setMeta('native-view-state',true)}})
  const outline = createDocxOutlineView({editor,root:host.querySelector<HTMLElement>('.docx-navigation-layout')!,onError:reportError})
  const view = createDocxViewCommands({ root: host, scroller: host.querySelector<HTMLElement>('.editor-scroll')!, page: editor.view.dom,
    pageSize: () => { const current = docxSectionSettingsWithPatch(sectionAnchors[activeSection]!.settings, sectionValues(activeSection)); return { width: px(current.pageWidth), height: px(current.pageHeight) } },
    reading:{setActive(active){if(!ready||editor.isDestroyed){readingMode=active;return}flushPendingEdits();readingMode=active;editor.setEditable(context.editingEnabled&&!active&&!documentToolModels.protection?.contentLocked&&!saving&&!draft.saving&&!draft.closed,false);pendingHfEditor?.setEditable(editor.isEditable);editor.commands.setMeta('native-view-state',true)}},
    pageColor:()=>effectiveDocxPageColor(nativeOperations(),pageColorModel),
    onViewChange:()=>{if(!ready)return;if(readingMode)options.onSelectionChange?.([]);webMode=view.mode==='web';columnLayoutReady=false;currentColumnLayout=null;scheduleColumns();ruler.refresh();navigation.refresh()},
    onPaginationPreview: showPaginationPreview, onZoomChange: () => { ruler.refresh(); navigation.refresh() }, navigation, outline, gridlines, ruler })
  const legacyHeaderFooter: DocxHeaderFooterController | undefined = hfModel ? {
    get editable() { return context.editingEnabled && !readingMode && !saving && !draft.saving && !draft.closed },
    anchor: hfAnchor,
    flushPendingEdits,
    registerEditor: editor => { pendingHfEditor = editor },
    get model() {
      const current = { ...hfModel }
      for (const operation of headerFooterOperations()) {
        if (typeof operation.titlePg === 'boolean') current.titlePg = operation.titlePg
        if (typeof operation.evenAndOddHeaders === 'boolean') current.evenAndOddHeaders = operation.evenAndOddHeaders
      }
      Object.assign(current, pageNumberOf(sectionAnchors.length - 1))
      const titlePg = titlePageOf(sectionAnchors.length - 1)
      if (typeof titlePg === 'boolean') current.titlePg = titlePg
      const evenOdd = evenOddOf()
      if (typeof evenOdd === 'boolean') current.evenAndOddHeaders = evenOdd
      return current
    },
    valueOf: (part: DocxHfPart, variant: DocxHfVariant) => {
      const partAnchor = hfModel.parts[`${part}.${variant}`]
      if (!partAnchor) return null
      const operation = headerFooterOperations().find(value => value.part === part && value.variant === variant)
      // 草稿重放携带已写入操作的统一对齐，后续再提交（切换选项/变体）不会丢失页码位置。
      const align = operation?.align as 'left' | 'center' | 'right' | undefined
      if (operation) return { value: { text: operation.text as string, paras: (operation.text as string).split('\n').map(text => ({ ...(align ? { align } : {}), runs: [{ text }] })), pageNumber: operation.pageNumber as boolean }, anchor: partAnchor }
      const info = partAnchor.rId ? parsed.hfParts?.[partAnchor.rId] : null
      return { value: { text: partAnchor.text, ...(info?.paras ? { paras: info.paras } : {}), pageNumber: partAnchor.hasPageNumber }, anchor: partAnchor }
    },
    onCommit: (part: DocxHfPart, variant: DocxHfVariant, value, flags?: DocxHfFlags) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return
      try {
        const partAnchor = hfModel.parts[`${part}.${variant}`]
        if (!partAnchor) throw new Error('页眉/页脚部件不受当前保存协议支持')
        const settings: DocxHfFlags = {}
        for (const previous of headerFooterOperations()) {
          for (const key of ['titlePg', 'evenAndOddHeaders', 'pageNumberFmt', 'pageNumberStart'] as const) {
            if (previous[key] !== undefined) Object.assign(settings, { [key]: previous[key] })
          }
        }
        const sourceParas = partAnchor.rId ? parsed.hfParts?.[partAnchor.rId]?.paras : undefined
        const operation = docxHeaderFooterOperation(hfAnchor, partAnchor, part, variant, value, { ...settings, ...flags }, sourceParas)
        let operations = operation ? mergeDocxHeaderFooterOperation(draft.operations, operation)
          : draft.operations.filter(operation => !(operation.kind === 'setHeaderFooter' && operation.part === part && operation.variant === variant))
        if (typeof flags?.titlePg === 'boolean') {
          operations = operations.map(item => item.kind === 'setSectionLayout' && item.sectionId === hfAnchor.sectionId && Object.hasOwn(item.values as object, 'titlePg')
            ? { ...item, values: { ...item.values as SectionValues, titlePg: flags.titlePg } } : item)
        }
        if (typeof flags?.evenAndOddHeaders === 'boolean') {
          operations = operations.map(item => item.kind === 'setSectionLayout' && item.sectionId === hfAnchor.sectionId && Object.hasOwn(item.values as object, 'evenAndOddHeaders')
            ? { ...item, values: { ...item.values as SectionValues, evenAndOddHeaders: flags.evenAndOddHeaders } } : item)
        }
        for (const key of ['pageNumberFmt', 'pageNumberStart'] as const) {
          if (flags?.[key] !== undefined) operations = operations.map(item => item.kind === 'setSectionLayout' && item.sectionId === hfAnchor.sectionId && Object.hasOwn(item.values as object, key)
            ? { ...item, values: { ...item.values as SectionValues, [key]: flags[key] } } : item)
        }
        assertDocxCommentReplyBatch(operations)
        assertDocxCommentThreadBatch(operations)
        if(operations.some(op=>op.kind==='editEquations')&&operations.length!==1)throw new Error('公式修改请单独保存')
    assertDocxBookmarksBatch(operations)
        assertDocxTocBatch(operations)
        assertDocxCrossReferencesBatch(operations)
        assertDocxCaptionBatch(operations)
        assertDocxCommentCreationBatch(operations)
        assertDocxCommentTextBatch(operations)
        commitDocxNativeOperations(editor, operations)
      } catch (error) { reportError(error) }
    },
  } : undefined
  const publishHf = (operations: typeof draft.operations) => {
    assertDocxCommentReplyBatch(operations)
    assertDocxCommentThreadBatch(operations)
    if(operations.some(op=>op.kind==='editEquations')&&operations.length!==1)throw new Error('公式修改请单独保存')
    assertDocxBookmarksBatch(operations)
    assertDocxTocBatch(operations)
    assertDocxCrossReferencesBatch(operations)
    assertDocxCaptionBatch(operations)
    assertDocxCommentCreationBatch(operations)
    assertDocxCommentTextBatch(operations)
    restoredSectionHfOperations(operations, sectionAnchors)
    commitDocxNativeOperations(editor, operations)
  }
  const hfState = () => sectionHfState(sections, sectionAnchors, headerFooterOperations(), parsed.hfParts)
  const sectionHeaderFooter = (sectionIndex: () => number): DocxHeaderFooterController => ({
    get editable() { return context.editingEnabled && !readingMode && !saving && !draft.saving && !draft.closed },
    get anchor() { return sectionAnchors[sectionIndex()]! },
    get sectionLabel() { return `第 ${sectionIndex() + 1} 节，共 ${sections.length} 节` },
    flushPendingEdits,
    registerEditor: editor => { pendingHfEditor = editor },
    get model() {
      const current = sectionAnchors[sectionIndex()]!
      return { ...hfModel, parts: current.headersFooters!.parts, titlePg: titlePageOf(sectionIndex()) ?? false,
        titlePgReadOnlyReason: current.titlePgReadOnlyReason, evenAndOddHeaders: evenOddOf() ?? false,
        ...pageNumberOf(sectionIndex()), pageNumberReadOnlyReason: current.pageNumberReadOnlyReason } as DocxHeadersFootersModel
    },
    linked: (part, variant) => {
      const source = sectionAnchors[sectionIndex()]!.headersFooters!.parts[`${part}.${variant}`]!
      const { owner } = resolveHf(hfState(), sectionIndex(), part, variant)
      const operation = headerFooterOperations().find(operation => operation.kind === 'setHeaderFooterLink' && operation.sectionId === sectionAnchors[sectionIndex()]!.sectionId && operation.part === part && operation.variant === variant)
      return { value: !sectionIndex() ? null : operation ? operation.linked as boolean : source.linked,
        reason: source.readOnlyReason, ownerLabel: `内容归属：第 ${owner + 1} 节` }
    },
    valueOf: (part, variant) => {
      const source = sectionAnchors[sectionIndex()]!.headersFooters!.parts[`${part}.${variant}`]
      if (!source) return null
      const found = resolveHf(hfState(), sectionIndex(), part, variant)
      return { value: found.value ?? { text: '' }, anchor: { ...source, editable: source.editable && plannedSectionHfTarget(sectionAnchors, headerFooterOperations(), sectionIndex(), part, variant).anchor.editable } }
    },
    onLink: (part, variant, linked, pending) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return
      try {
        const target = sectionAnchors[sectionIndex()]!, source = target.headersFooters!.parts[`${part}.${variant}`]!
        if (!sectionIndex() || !source.editable || draft.operations.some(operation => operation.kind === 'insertSectionBreak')) throw new Error(source.readOnlyReason ?? '此节暂不可切换链接，请先保存')
        let operations = draft.operations.filter(operation => !(operation.sectionId === target.sectionId && operation.part === part && operation.variant === variant && ['setHeaderFooterLink', 'setHeaderFooter'].includes(operation.kind)))
        const inheritedValue = pending ?? resolveHf(hfState(), sectionIndex(), part, variant).value ?? { text: '' }
        if (!linked && pending) {
          const { owner } = resolveHf(hfState(), sectionIndex(), part, variant)
          const ownerAnchor = sectionAnchors[owner]!, partAnchor = plannedSectionHfTarget(sectionAnchors, headerFooterOperations(), owner, part, variant).anchor
          if (!partAnchor.editable || pendingBreakIn(owner)) throw new Error('继承内容尚无法写回，请先保存再解除链接')
          const afterLink = headerFooterOperations().some(operation => operation.kind === 'setHeaderFooterLink' && operation.sectionId === ownerAnchor.sectionId && operation.part === part && operation.variant === variant && operation.linked === false)
          const content = docxHeaderFooterOperation(ownerAnchor, partAnchor, part, variant, pending, undefined, partAnchor.rId ? parsed.hfParts?.[partAnchor.rId]?.paras : undefined, afterLink)
          const edit = content && afterLink ? { ...content, afterLink: true } : content
          operations = edit ? mergeDocxHeaderFooterOperation(operations, edit) : operations.filter(operation => !(operation.kind === 'setHeaderFooter' && operation.sectionId === ownerAnchor.sectionId && operation.part === part && operation.variant === variant))
        }
        if (linked !== source.linked) operations = [...operations, sectionHfLinkOperation(target, part, variant, linked)]
        if (!linked && source.linked) {
          // 固化解除当时的有效内容；后续再编辑前节不会改写此新own的复制快照。
          const base = plannedSectionHfTarget(sectionAnchors, operations, sectionIndex(), part, variant).anchor
          const copy = docxHeaderFooterOperation(target, base, part, variant, inheritedValue, undefined, base.rId ? parsed.hfParts?.[base.rId]?.paras : undefined, true)!
          operations = mergeDocxHeaderFooterOperation(operations, { ...copy, afterLink: true })
        }
        publishHf(operations)
      } catch (error) { reportError(error) }
    },
    onCommit: (part, variant, value, flags) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return
      try {
        const { owner } = resolveHf(hfState(), sectionIndex(), part, variant)
        const target = sectionAnchors[owner]!, planned = plannedSectionHfTarget(sectionAnchors, headerFooterOperations(), owner, part, variant)
        const partAnchor = planned.anchor
        const afterLink = headerFooterOperations().some(operation => operation.kind === 'setHeaderFooterLink' && operation.sectionId === target.sectionId && operation.part === part && operation.variant === variant && operation.linked === false)
        if (!partAnchor.editable || pendingBreakIn(owner)) throw new Error(partAnchor.readOnlyReason ?? '请先保存再编辑此节页眉页脚')
        const sourceParas = partAnchor.rId ? parsed.hfParts?.[partAnchor.rId]?.paras : undefined
        const content = docxHeaderFooterOperation(target, partAnchor, part, variant, value, undefined, sourceParas, afterLink)
        const operation = content && afterLink ? { ...content, afterLink: true } : content
        let operations = operation ? mergeDocxHeaderFooterOperation(draft.operations, operation) : draft.operations.filter(operation => !(operation.kind === 'setHeaderFooter' && operation.sectionId === target.sectionId && operation.part === part && operation.variant === variant))
        for (const [key, flag] of Object.entries(flags ?? {})) {
          if (flag === undefined) continue
          const index = key === 'evenAndOddHeaders' ? sectionAnchors.length - 1 : sectionIndex()
          const anchor = sectionAnchors[index]!
          const previous = operations.find(operation => operation.kind === 'setSectionLayout' && operation.sectionId === anchor.sectionId)
          const layout = restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId: anchor.sectionId, expectedSectionSha256: anchor.expectedSectionSha256, values: { ...previous?.values as SectionValues, [key]: flag } }], anchor)
          operations = [...operations.filter(operation => !(operation.kind === 'setSectionLayout' && operation.sectionId === anchor.sectionId)), ...(layout ? [layout] : [])]
        }
        publishHf(operations)
      } catch (error) { reportError(error) }
    },
  })
  const headerFooter = multiHf && hfModel ? sectionHeaderFooter(() => activeSection) : legacyHeaderFooter
  if (headerFooter && multiHf) headerFooter.forSection = sectionId => {
    const index = sectionAnchors.findIndex(anchor => anchor.sectionId === sectionId)
    if (index < 0) throw new Error('页眉页脚目标节身份无效')
    return sectionHeaderFooter(() => index)
  }
  if (headerFooter) headerFooter.prepareEdges = async () => {
    headerFooter.flushPendingEdits?.()
    if (!headerFooter.editable || !editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    const documentAtOpen = editor.state.doc, operationsAtOpen = JSON.stringify(draft.operations), geometrySectionAtOpen = activeSection
    const stillCurrent = () => !editor.isDestroyed && ready && headerFooter.editable && editor.isEditable
      && editor.state.doc === documentAtOpen && JSON.stringify(draft.operations) === operationsAtOpen && activeSection === geometrySectionAtOpen
    const assertCurrent = () => { if (!stillCurrent()) throw new Error('文档或页面设置发生变化，请重新打开页眉页脚菜单') }
    const { snapshot, globalTitlePg, evenOddHf } = await measurePagination(stillCurrent)
    assertCurrent()
    const facts = { sections: sectionAnchors, cuts: snapshot.cuts, titlePg: globalTitlePg, evenOddHf }
    const header = resolveDocxEdgeHfTarget('header', facts), footer = resolveDocxEdgeHfTarget('footer', facts)
    const controllerFor = (sectionId: string) => {
      const controller = headerFooter.forSection?.(sectionId) ?? headerFooter
      if (controller.anchor.sectionId !== sectionId) throw new Error('页眉页脚目标节身份无效')
      return controller
    }
    return { header: { controller: controllerFor(header.sectionId), part: 'header', variant: header.variant },
      footer: { controller: controllerFor(footer.sectionId), part: 'footer', variant: footer.variant }, assertCurrent }
  }
  const findReplace = createDocxFindReplace({ editor, root: host, anchors, getBaseline: () => ({ ...baseline, attrs: { ...baseline.attrs, nativeDocxOperations: editor.state.doc.attrs.nativeDocxOperations } }),
    isLocked: () => saving || draft.saving || draft.closed || !context.editingEnabled,
    getSection: () => sectionAnchors, getSectionOperation: sectionOperation, styles: parsed.styles })
  const noteDialog = createDocxNoteDialog(host)
  const noteLocked = () => saving || draft.saving || draft.closed || !context.editingEnabled || !editor.isEditable
  const insertNoteTarget = () => {
    const selection = editor.state.selection, { $from } = selection
    if (!notesModel || !selection.empty || $from.depth !== 1) return undefined
    const node = $from.node(1), anchor = anchors.find(anchor => anchor.docxIndex === node.attrs.docxIndex)
    const eligible = notesModel.referenceBlocks?.find(block => block.blockId === anchor?.blockId && block.expectedObjectSha256 === anchor.expectedObjectSha256)
    if (!anchor || !(eligible?.editable ?? anchor.editable) || !['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name)
      || node.content.content.some(child => !['text', 'docNoteRef', 'hardBreak'].includes(child.type.name))
      || editor.state.doc.content.content.filter(item => item.attrs.docxIndex === anchor.docxIndex).length !== 1) return undefined
    return { blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, offset: $from.parentOffset }
  }
  const commitNotes = (operations: DocxNoteOperation[], removedPending?: { kind: 'footnote' | 'endnote'; id: string }) => {
    if (noteLocked() || !notesModel) throw new Error('当前文档不可编辑或正在保存')
    const current = editor.getJSON()
    const next = applyDocxNotesIntent(current, operations, anchors, notesModel, removedPending)
    // 当前正文与marker共同编译成最终run计划，保留普通键入及格式历史。
    collectOperations(next)
    const node = editor.schema.nodeFromJSON(next), selection = editor.state.selection.from
    const tr = closeHistory(editor.state.tr).replaceWith(0, editor.state.doc.content.size, node.content)
      .setDocAttribute('nativeNotesOperations', operations)
    tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(selection, tr.doc.content.size))))
    editor.view.dispatch(tr)
    // 模态框先同步关闭并归还焦点，随后恢复画布；避免rAF晚到覆盖用户下一次选区。
    queueMicrotask(() => { if (!editor.isDestroyed && !noteLocked()) editor.view.focus() })
  }
  const notes: DocxNotesController = {
    get editable() { return !noteLocked() && !!notesModel },
    get insertReason() { return !notesModel ? '当前来源未提供脚注尾注编辑能力' : insertNoteTarget() ? undefined : '请把光标放在可插入注释的来源正文段落内' },
    get entries() {
      if (!notesModel) return []
      return projectedDocxNotes(notesModel, notesOperationsOf(editor.getJSON())).map(entry => ({
        ...entry, readOnlyReason: entry.reason,
        canDelete: entry.pending || entry.references.every(ref => notesModel.referenceBlocks?.some(block => block.blockId === ref.blockId && block.expectedObjectSha256 === ref.expectedObjectSha256 && block.editable)
          ?? anchors.some(anchor => anchor.blockId === ref.blockId && anchor.expectedObjectSha256 === ref.expectedObjectSha256 && anchor.editable)),
        deleteReason: '此注释的正文引用包含暂不支持安全修改的对象',
      }))
    },
    aiInsert:context.aiEnabled&&options.onNoteAI?()=>{
      try{flushPendingEdits();const target=insertNoteTarget();if(!target||noteLocked())throw new Error('请把光标放在可插入注释的正文段落内')
        options.onNoteAI?.({selectionKind:'noteAnchor',blockId:target.blockId})
      }catch(error){reportError(error)}
    }:undefined,
    aiEdit:context.aiEnabled&&options.onNoteAI?(kind,id)=>{
      try{flushPendingEdits();const entry=notes.entries.find(note=>note.kind===kind&&note.id===id)
        if(!entry?.editable||noteLocked())return
        if(entry.pending)throw new Error('请先保存新增注释，再使用 AI 编辑该注释')
        options.onNoteAI?.({selectionKind:'note',noteKind:kind,noteId:id},'',entry.text)
      }catch(error){reportError(error)}
    }:undefined,
    insert(kind) {
      const target = insertNoteTarget()
      if (!target || noteLocked()) return
      const snapshot = JSON.stringify(editor.getJSON())
      noteDialog.open(kind === 'footnote' ? '插入脚注' : '插入尾注', '', text => {
        if (JSON.stringify(editor.getJSON()) !== snapshot) throw new Error('文档已经变化，请重新打开注释')
        commitNotes([...notesOperationsOf(editor.getJSON()), { kind: 'insertNote', noteKind: kind, ...target, text }])
      })
    },
    edit(kind, id) {
      const entry = notes.entries.find(entry => entry.kind === kind && entry.id === id)
      if (!entry?.editable || noteLocked() || !notesModel) return
      const snapshot = JSON.stringify(editor.getJSON())
      noteDialog.open('编辑注释', entry.text, text => {
        if (JSON.stringify(editor.getJSON()) !== snapshot) throw new Error('文档已经变化，请重新打开注释')
        commitNotes(editDocxNoteOperations(notesModel, notesOperationsOf(editor.getJSON()), kind, id, text, { baseline, anchors }))
      })
    },
    remove(kind, id) {
      try {
        if (noteLocked() || !notesModel) return
        const operations = notesOperationsOf(editor.getJSON()), entry = projectedDocxNotes(notesModel, operations).find(entry => entry.kind === kind && entry.id === id)
        commitNotes(entry?.pending ? operations.filter((_, index) => index !== entry.operationIndex) : editDocxNoteOperations(notesModel, operations, kind, id, null), entry?.pending ? { kind, id } : undefined)
      }
      catch (error) { reportError(error) }
    },
  }
  const noteFormattingAnchors = notesModel ? anchors.map(anchor => ({ ...anchor, editable: notesModel.referenceBlocks?.find(block => block.blockId === anchor.blockId && block.expectedObjectSha256 === anchor.expectedObjectSha256)?.editable ?? anchor.editable })) : []
  const textRevisions = createDocxTextRevisionControls({ editor, baseline, anchors, container: host,
    onReviewAI: context.aiEnabled ? options.onReviewAI : undefined,
    revisionFilter:()=>reviewView.state,
    readOnlyReason: () => !context.editingEnabled || saving || draft.saving || draft.closed || nestedInputActive ? '当前文档不可编辑、正在保存或有未完成的表格输入' : null,
    onError: reportError,
  })
  const spellcheckControl = createDocxSpellcheckControl(editor)
  const reviewPresets = context.aiEnabled && options.onAIPreset ? createDocxReviewPresets({editor,source:readSourceDoc,anchors,open:options.onAIPreset,flush:flushPendingEdits,onError:reportError,reason:()=>!context.editingEnabled||saving||draft.saving||draft.closed||refreshing||nestedInputActive?'当前文档不可编辑、正在保存或有未完成的表格输入':null}) : undefined
  const reviewAuthors = () => {
    const doc = editor.state.doc, operations = notesOperationsOf(editor.getJSON())
    const stories = [...collectHfRevisions(hfState()), ...collectTextboxRevisions(doc)]
    for (const kind of ['footnote', 'endnote'] as const) {
      const list = kind === 'footnote' ? parsed.footnotes ?? [] : parsed.endnotes ?? []
      let notes = list
      if (notesModel) {
        const projected = projectedDocxNotes(notesModel, operations).filter(note => note.kind === kind)
        const updated = new Set(operations.filter(operation => operation.kind === 'updateNote' && operation.noteKind === kind).map(operation => operation.noteId))
        notes = projected.flatMap(note => {
          const source = list.find(item => item.id === note.id)
          return source && !updated.has(note.id) ? [source] : []
        })
      }
      stories.push(...collectNoteRevisions(doc, kind, notes))
    }
    return revisionAuthorsOf(doc, stories)
  }
  reviewView.setAuthors(reviewAuthors())
  let compareControls:ReturnType<typeof import('./docx-compare').createDocxCompareControls>|undefined
  let compareDisposed=false,compareLoading=false
  const compare=async()=>{
    if(compareDisposed||compareLoading)return
    compareLoading=true
    try{const {createDocxCompareControls}=await import('./docx-compare');if(compareDisposed)return;compareControls??=createDocxCompareControls({editor,blocks:parsed.blocks,container:host,flush:flushPendingEdits,onError:reportError});compareControls.open()}catch(error){reportError(error)}finally{compareLoading=false}
  }
  const reviewCommands = { ...textRevisions, compare, presets:reviewPresets, spellcheck: spellcheckControl, view:{state:()=>reviewView.state,authors:reviewAuthors,setMode:reviewView.setMode,setFilter:reviewView.setFilter},
    trackingEnabled: () => docxTrackRevisionsEnabled(trackRevisionsModel, nativeOperations()),
    trackingReason: () => !context.editingEnabled || saving || draft.saving || draft.closed ? '当前文档不可编辑或正在保存' : trackRevisionsModel.readOnlyReason,
    toggleTracking: () => {
      if (!context.editingEnabled || saving || draft.saving || draft.closed || trackRevisionsModel.readOnlyReason) return
      const enabled = !docxTrackRevisionsEnabled(trackRevisionsModel, nativeOperations())
      if (commitDocxNativeOperations(editor, withDocxTrackRevisions(nativeOperations(), trackRevisionsModel, enabled))) editor.storage.trackChanges.enabled = enabled
    },
  }
  const replyLock = () => saving || draft.saving || draft.closed || !context.editingEnabled || refreshing ? '当前文档不可编辑或正在保存' : draft.operations.some(op => op.kind !== 'replyComment') ? '批注回复需独立保存，请先保存或撤销正文及其他修改' : null
  commentControls = createDocxCommentControls({ editor, container: host, model: commentsModel, collectOperations,
    onReviewAI: context.aiEnabled ? options.onReviewAI : undefined,
    thread: commentThreadsModel ? {model: commentThreadsModel, readOnlyReason: () => saving || draft.saving || draft.closed || !context.editingEnabled || refreshing
      ? '当前文档不可编辑或正在保存' : draft.operations.some(op => !isDocxCommentThreadOperation(op)) ? '请先保存或撤销其他修改，再编辑批注线程' : null} : undefined,
    onReply: targetId => commentReplyControls?.openFor(targetId),
    replyReadOnlyReason: targetId => replyLock() ?? commentRepliesModel?.readOnlyReason ?? (commentRepliesModel?.targets.find(t => t.targetId === targetId)?.canReply ? null : commentRepliesModel?.targets.find(t => t.targetId === targetId)?.replyReadOnlyReason ?? '当前来源未提供可信根线程回复能力'),
    parentIdOf: targetId => commentRepliesModel?.targets.find(t => t.targetId === targetId)?.parentId ?? null,
    readOnlyReason: () => saving || draft.saving || draft.closed || !context.editingEnabled || refreshing ? '当前文档不可编辑或正在保存' : draft.operations.some(op => op.kind !== 'editCommentText') ? '批注修改必须独立保存，请先保存或撤销正文及其他修改' : null,
    onError: reportError,
  })
  commentCreationControls = createDocxCommentCreationControls({editor,container:host,model:commentCreationModel,collectOperations,
    readOnlyReason:()=>saving||draft.saving||draft.closed||!context.editingEnabled||refreshing?'当前文档不可编辑或正在保存':draft.operations.some(op=>op.kind!=='createComment')?'新建批注需独立保存，请先保存或撤销正文及其他修改':null,onError:reportError})
  commentReplyControls = createDocxCommentReplyControls({editor,container:host,model:commentRepliesModel,collectOperations,readOnlyReason:replyLock,onError:reportError})
  bookmarkControls = createDocxBookmarksControls({editor,container:host,model:bookmarksModel,collectOperations,
    readOnlyReason:()=>saving||draft.saving||draft.closed||!context.editingEnabled||refreshing?'当前文档不可编辑或正在保存':draft.operations.some(op=>!['createBookmark','deleteBookmark'].includes(op.kind))?'书签修改需独立保存，请先保存或撤销其他修改':null,onError:reportError})
  const referenceLock=()=>saving||draft.saving||draft.closed||!context.editingEnabled||refreshing||nestedInputActive?'当前文档不可编辑、正在保存或有未完成的表格输入':null
  crossReferenceControls=createDocxCrossReferenceControls({editor,container:host,model:crossReferencesModel,collectOperations,readOnlyReason:referenceLock,onError:reportError})
  captionDialog=createDocxCaptionDialog({editor,container:host,controls:captionSource.controls(editor,()=>draft.operations,reportError),readOnlyReason:referenceLock,onError:reportError})
  const pictureControls = createDocxPictureControls(editor, anchors, host, () => saving || draft.saving || draft.closed || !context.editingEnabled ? '当前文档不可编辑或正在保存' : null, reportError)
  const pictureFormatControls=createDocxPictureFormatControls(editor,anchors,host,()=>saving||draft.saving||draft.closed||!context.editingEnabled?'当前文档不可编辑或正在保存':null,reportError,()=>Number.parseFloat(getComputedStyle(editor.view.dom).getPropertyValue('--section-content-w'))||editor.view.dom.clientWidth-Number.parseFloat(getComputedStyle(editor.view.dom).paddingLeft)-Number.parseFloat(getComputedStyle(editor.view.dom).paddingRight))
  const tableStyleControls=createDocxTableStyleControls({editor,anchors,onError:reportError})
  const wordCountControl = createDocxWordCountControl({editor,container:host})
  const toolReason=()=>readingMode?'阅读视图中不能修改文档':saving||draft.saving||draft.closed||refreshing?'当前文档正在保存、刷新或已经关闭':null
  const fileActions=createDocxFileActions({root:host,api,sourceSha256:expectedSha256,displayName:context.context.displayName,blocked:()=>!context.editingEnabled?'当前会话未开放文档编辑':saving||draft.saving||draft.closed||refreshing?'当前文档正在保存、刷新或已经关闭':null,pendingEdits:()=>draft.dirty,flush:flushPendingEdits,onError:reportError})
  const documentTools=createDocxDocumentTools({editor,host,models:documentToolModels,parsed,reason:()=>!context.editingEnabled?'当前文档只读':toolReason(),flush:flushPendingEdits,onError:reportError})
  const objectControls=createDocxInsertObjectControls({editor,root:host,editable:()=>!toolReason()&&context.editingEnabled&&!documentToolModels.protection?.contentLocked,onError:reportError})
  let fieldPagination: (Pick<PageLayout,'cuts'> & Partial<Pick<PageLayout,'slices'>>) | null = null
  const fieldPageInfo=()=>{const layout=currentColumnLayout??fieldPagination;if(!layout?.cuts.length)throw new Error('分页正在计算，请稍后再插入或更新域');const pm=editor.view.dom.getBoundingClientRect(),scroll=host.querySelector('.editor-scroll')!.getBoundingClientRect(),zoom=Number(host.dataset.docxZoom??100)/100,mid=Math.min(scroll.top+scroll.height/2,pm.bottom);let physical=layout.slices?.length?pageAt(layout.slices,(mid-pm.top)/zoom-currentCanvasTop):1;if(layout.cuts.some(cut=>cut.gap)){physical=1;for(const edge of pagePaperEdges(layout.cuts,currentCanvasTop)){if(pm.top+edge.gapTop*zoom>mid)break;physical=edge.page+1}}return {current:layout.slices?.length?visiblePageCount(layout.slices,physical):physical,total:layout.slices?.length?visiblePageCount(layout.slices):layout.cuts.length}}
  const prepare=async(run:()=>void)=>{try{const doc=editor.state.doc,selection=editor.state.selection;const measured=await measurePagination(()=>editor.state.doc===doc&&editor.state.selection.eq(selection)&&!toolReason());fieldPagination=measured.snapshot;run()}catch(error){reportError(error)}}
  const chartFieldControls=createDocxChartFieldControls({root:host,editable:()=>!toolReason()&&editor.isEditable,actions:(()=>{const actions=chartFieldSource.controls(editor,()=>draft.operations,reportError,()=> context.context.displayName||'report.docx',fieldPageInfo);return {...actions,insertField:(instruction:string)=>{void prepare(()=>actions.insertField(instruction))},updateFields:()=>{void prepare(()=>actions.updateFields())}}})()})
  const fieldControls=createDocxFieldControls({root:host,editor,fields:inspected.model.editableFields??[],pending:()=>draft.operations,reportError,value:instruction=>{const kind=instruction.trim().split(/\s+/)[0].toUpperCase();if(kind==='DATE')return new Date().toLocaleDateString('zh-CN');if(kind==='TIME')return new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});if(kind==='FILENAME')return context.context.displayName||'report.docx';const pages=fieldPageInfo();return kind==='NUMPAGES'?String(pages.total):String(pages.current)}})
  const updateFieldsKey=(event:KeyboardEvent)=>{if(!event.isComposing&&event.keyCode!==229&&!event.defaultPrevented&&fieldControls.handleKey(event))return;if(event.target instanceof HTMLElement&&event.target.closest('[role=dialog]'))return;if(event.key==='F9'&&!event.isComposing&&event.keyCode!==229&&!event.defaultPrevented&&!event.ctrlKey&&!event.metaKey&&!event.altKey){event.preventDefault();chartFieldControls.updateFields()}}
  host.addEventListener('keydown',updateFieldsKey)
  const exportControls=createDocxExportControls({editor,container:host,reason:toolReason,flush:flushPendingEdits,onError:reportError,title:context.context.displayName?.replace(/\.docx$/i,'')||'文档'})
  const mailExportAbort=new AbortController()
  let mailExportUrl:string|undefined
  const mailExportDelivery=document.createElement('div');mailExportDelivery.setAttribute('aria-live','polite');host.append(mailExportDelivery)
  const mailMergeControls=createDocxMailMergeControls({editor,host,api,draft,anchors,reason:()=>saving||draft.saving||draft.closed||!context.editingEnabled||refreshing?'当前文档不可编辑或正在保存':null,onSave:()=>shell.save.click(),onError:reportError,onExport:async request=>{
    flushPendingEdits();if(toolReason()||draft.operations.length)throw new Error('请先保存当前修改再导出邮件合并')
    const doc=editor.state.doc,result=await api.mailMergeExport(request,mailExportAbort.signal)
    const {verifyDocxMailMergeDownload}=await import('./docx-mail-merge-download')
    await verifyDocxMailMergeDownload(result,expectedSha256)
    if(!ready||editor.isDestroyed||editor.state.doc!==doc||draft.operations.length)throw new Error('文档已变化，请重新导出邮件合并')
    if(mailExportUrl)URL.revokeObjectURL(mailExportUrl)
    const filename=request.mode==='labels'?'mail-merge-labels.docx':'mail-merge.zip'
    mailExportUrl=URL.createObjectURL(new Blob([result.content],{type:request.mode==='labels'?'application/vnd.openxmlformats-officedocument.wordprocessingml.document':'application/zip'}))
    const link=document.createElement('a');link.href=mailExportUrl;link.download=filename;link.textContent='下载邮件合并结果';mailExportDelivery.replaceChildren(link);link.click()
  }})
  host.addEventListener('native-mail-merge-open',mailMergeControls.open)
  const ordinaryTableCommands=createDocxTableCommands(editor,baseline,anchors,reportError,()=>nestedInputActive)
  const tableMutationReason=()=>toolReason()??(nestedInputActive||pendingHfEditor?'请先退出嵌套表格或页眉页脚编辑':commentControls?.hasPendingInput||commentCreationControls?.hasPendingInput||commentReplyControls?.hasPendingInput?'请先完成或取消批注输入，再编辑表格':null)
  const lifecycleControls=tableLifecycle.createDocxTableLifecycleControls({editor,baseline,anchors,reason:tableMutationReason,onError:reportError})
  const cellControls=cellOperations.createDocxTableCellControls({editor,baseline,anchors,root:host,reason:tableMutationReason,onError:reportError})
  const isCellAction=(action:string):action is 'table-insert-cells'|'table-delete-cells'=>action==='table-insert-cells'||action==='table-delete-cells'
  const isLifecycleAction=(action:string):action is 'table-delete'|'table-split-table'=>action==='table-delete'||action==='table-split-table'
  const tableCommands={...ordinaryTableCommands,reason:(action:string)=>isCellAction(action)?cellControls.reason(action):isLifecycleAction(action)?lifecycleControls.reason(action):ordinaryTableCommands.reason(action),run:(action:string)=>{if(isCellAction(action))cellControls.run(action);else if(isLifecycleAction(action))lifecycleControls.run(action);else ordinaryTableCommands.run(action)}}
  const lifecycleKey=(event:KeyboardEvent)=>{lifecycleControls.handleKey(event)}
  host.addEventListener('keydown',lifecycleKey,true)
  toolbar.append(createDocxRibbon(editor, context.editingEnabled, showPaginationPreview, paragraphCommand, sectionRibbon, anchors, tableCommands, view, findReplace.open, reportError, headerFooter, notes, noteFormattingAnchors, reviewCommands, {open:commentControls.open,toggle:event=>{const closing=commentControls.visible;if(closing)commentCreationControls.cancelPending();commentControls.toggle(event)},openNew:commentCreationControls.openNew,navigate:commentControls.navigate,navigationReason:commentControls.navigationReason,deleteCurrent:commentControls.deleteAtCaret,deleteReason:commentControls.deleteAtCaretReason,deleteAll:commentControls.deleteAll,deleteAllReason:commentControls.deleteAllReason}, tocSource.controls(editor, () => draft.operations, reportError), bookmarkControls, {crossReferences:crossReferenceControls,caption:captionDialog}, options.onAssistant, pageColorModel ? {
    current: () => effectiveDocxPageColor(nativeOperations(), pageColorModel),
    reason: () => saving || draft.saving || draft.closed || !context.editingEnabled ? '当前文档不可编辑或正在保存' : pageColorModel.editable ? null : pageColorModel.readOnlyReason ?? '此文档的页面颜色不能修改',
    apply: (color: string | null) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return
      commitDocxNativeOperations(editor, withDocxPageColor(nativeOperations(), pageColorModel, color))
      syncPageColor()
    },
  } : undefined, watermarkModel ? {
    current: () => effectiveDocxWatermark(nativeOperations(), watermarkModel),
    source: watermarkModel,
    reason: () => saving || draft.saving || draft.closed || !context.editingEnabled ? '当前文档不可编辑或正在保存' : watermarkModel.editable ? null : watermarkModel.readOnlyReason ?? '此文档的水印不能修改',
    snapshot: () => JSON.stringify([editor.getJSON(), nativeOperations(), activeSection]),
    pageBox: () => {
      const current = docxSectionSettingsWithPatch(sectionAnchors[activeSection]!.settings, sectionValues(activeSection))
      return { pageWidthPt: current.pageWidth / 20, pageHeightPt: current.pageHeight / 20, marginWidthPt: (current.pageWidth - current.marginLeft - current.marginRight) / 20, marginHeightPt: (current.pageHeight - current.marginTop - current.marginBottom) / 20 }
    },
    apply: (spec: import('./docx-watermark').DocxWatermarkValue | null) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return
      commitDocxNativeOperations(editor, withDocxWatermark(nativeOperations(), watermarkModel, spec))
      syncWatermark()
    },
  } : undefined, pictureControls, tableGridlines, formattingMarks, {
    // 固定源 Design ▸ Page Borders：整篇文档 = 每节一条 setSectionLayout（onPageBorderAll），本节 = 当前节。
    current: () => effectiveDocxPageBorder(sectionAnchors[activeSection]!.settings, sectionValues(activeSection) as Record<string, unknown> | undefined),
    sectionLabel: () => sectionAnchors.length > 1 ? `第 ${activeSection + 1} 节` : undefined,
    reason: (scope: import('./docx-page-borders').PageBorderScope) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return '当前文档不可编辑或正在保存'
      if (draft.operations.some(operation => operation.kind === 'insertSectionBreak')) return '已插入分节符，请先保存，再设置页面边框'
      if (draft.operations.some(operation => operation.kind === 'setWatermark')) return '页面边框与水印需分开保存，请先保存水印修改'
      return (scope === 'whole' ? sectionAnchors.map((_, index) => index) : [activeSection]).some(pendingBreakIn) ? '此节已插入分节符，请先保存' : null
    },
    apply: (value: import('./docx-page-borders').DocxPageBorderValue, scope: import('./docx-page-borders').PageBorderScope) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return
      const indices = scope === 'whole' ? sectionAnchors.map((_, index) => index) : [activeSection]
      const layout = withDocxPageBorder(sectionOperation(), indices.map(index => ({ sectionId: sectionAnchors[index]!.sectionId, settings: sectionAnchors[index]!.settings })), value,
        (sectionId, values) => { const anchor = sectionAnchors.find(item => item.sectionId === sectionId)!; return restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId, expectedSectionSha256: anchor.expectedSectionSha256, values }], anchor) })
      if (JSON.stringify(layout) === JSON.stringify(sectionOperation())) return
      if (!commitDocxNativeOperations(editor, collectOperations(editor.getJSON(), layout, headerFooterOperations()))) throw new Error('页面边框未能写入文档，请重试')
      syncSection()
      editor.commands.setMeta('native-section-layout', true)
    },
  }, {files:{...fileActions,save:()=>shell.save.click(),saveReason:()=>shell.save.disabled?'当前没有可保存的修改或文档不可编辑':null},tableStyles:tableStyleControls,preferences:kind=>{disposePreferences?.();disposePreferences=openDocxPreferencesDialog(kind)},editField:()=>{void prepare(()=>fieldControls.openEdit())},toggleFieldCode:fieldControls.toggleSelectedCode,toggleAllFieldCodes:fieldControls.toggleAllCodes,theme:documentTools.themeElement,draw:documentTools.drawElement,protect:documentTools.openProtection,stories:documentTools.openStory,chart:chartFieldControls.openChart,field:chartFieldControls.insertField,updateFields:chartFieldControls.updateFields,summary:options.onReviewSummary,pictureFormat:pictureFormatControls,object:type=>objectControls.open(type),export:format=>format==='pdf'?shell.exportPdf.click():void exportControls.run(format)})); toolbar.append(wordCountControl.element)
  const contextReplyTarget=(id:string|null)=>{const entry=commentRepliesModel?.targets.find(t=>t.originalCommentId===id);return entry?commentRepliesModel?.targets.find(t=>t.originalCommentId===(entry.parentId??entry.originalCommentId)&&t.parentId===null):undefined}
  const contextBindings=createDocxContextActions({editor,root:host,anchors,onError:reportError,tables:tableCommands,fields:fieldControls,prepare,extra:{
    newComment:{reason:()=>commentCreationModel?.readOnlyReason??(!commentCreationModel?'当前来源不支持新建批注':draft.operations.some(op=>op.kind!=='createComment')?'请先保存其他修改':null),run:()=>commentCreationControls?.openNew()},
    deleteComment:{reason:()=>commentControls?.deleteAtCaretReason()??null,run:()=>commentControls?.deleteAtCaret()},
    replyComment:{reason:target=>{const root=contextReplyTarget(target.commentId);return replyLock()??(!root?.canReply?root?.replyReadOnlyReason??'当前位置没有可回复的可信根批注':null)},run:target=>{const root=contextReplyTarget(target.commentId);if(!root?.canReply)throw new Error('当前位置不能回复批注');commentReplyControls?.openFor(root.targetId)}},
    acceptRevision:{label:'接受所选受支持的正文修订',description:'仅处理受支持的简单正文修订。',reason:()=>textRevisions.scopeReason('selection'),run:()=>textRevisions.applyScope('accept','selection')},
    rejectRevision:{label:'拒绝所选受支持的正文修订',description:'仅处理受支持的简单正文修订。',reason:()=>textRevisions.scopeReason('selection'),run:()=>textRevisions.applyScope('reject','selection')},
    acceptAllRevisions:{label:'接受所有受支持的正文修订',description:'不处理复杂修订和非正文修订。',reason:textRevisions.batchReason,run:()=>textRevisions.applyAll('accept')},
    rejectAllRevisions:{label:'拒绝所有受支持的正文修订',description:'不处理复杂修订和非正文修订。',reason:textRevisions.batchReason,run:()=>textRevisions.applyAll('reject')},
    trackChanges:{reason:()=>reviewCommands.trackingReason?.()??null,run:()=>reviewCommands.toggleTracking?.()},
    ...(reviewPresets?{translate:{label:'翻译所选段落…',description:'按整段或整格授权；候选须明确采纳。',run:()=>{toolbar.querySelector<HTMLButtonElement>('[data-tab-id="review"]')?.click();reviewPresets.element.querySelector<HTMLButtonElement>('[data-action="review-translate"]')?.click()}}}:{}),
  }})
  const contextMenu=createDocxContextMenu({editor,root:host,actions:contextBindings.actions,locked:()=>toolReason()??(!editor.isEditable?'当前文档只读':nestedInputActive?'请先退出嵌套表格编辑':null),onError:reportError})
  const imageDrop=createDocxImageDrop({editor,root:host,locked:()=>toolReason()??(!context.editingEnabled||documentToolModels.protection?.contentLocked?'当前文档只读':nestedInputActive?'请先退出嵌套表格编辑':null),onError:reportError})

  const stylesPane = createDocxStylesPane({ editor, host, toolbar, parsed, anchors, model: stylesPaneModel, canEdit: () => ready && !saving && !draft.saving && !draft.closed && context.editingEnabled, onError: reportError, onCss: css => { style.textContent = css; if (style.sheet) scopeDocxStyleRules(style.sheet) } })
  editor.on('transaction', view.refresh)
  let columnFrame = 0, columnRequest = 0
  const scheduleColumns = () => {
    const request = ++columnRequest
    cancelAnimationFrame(columnFrame)
    columnFrame = requestAnimationFrame(() => {
      const doc = editor.state.doc, operations = JSON.stringify(draft.operations)
      const stillCurrent = () => ready && !editor.isDestroyed && !draft.closed && request === columnRequest && editor.state.doc === doc && JSON.stringify(draft.operations) === operations
      const currentSections = sections.map((item, index) => ({ ...item, titlePg: titlePageOf(index) ?? item.titlePg,
        pageNumberFmt: pageNumberOf(index).pageNumberFmt ?? undefined, pageNumberStart: pageNumberOf(index).pageNumberStart ?? undefined,
        settings: docxSectionSettingsWithPatch(sectionAnchors[index]!.settings, sectionValues(index)) }))
      const currentSection = docxColumnFacts(currentSections, section).section
      void prepareNotePagination(currentSections, currentSection, stillCurrent).then(notes => { if (stillCurrent()) layoutColumns(currentSections, currentSection, notes) }).catch(error => { if (stillCurrent()) reportError(error) })
    })
  }
  invalidateReviewLayout=()=>{columnLayoutReady=false;currentColumnLayout=null;resetWidthPassHistory(columnWidthHistory);scheduleColumns()}
  const columnTransaction = ({ transaction }: { transaction: import('@tiptap/pm/state').Transaction }) => {
    if (transaction.docChanged || transaction.getMeta('native-section-layout')) scheduleColumns()
  }
  editor.on('transaction', columnTransaction)
  await refresh()
  const releaseHfProbeScope = createDocxHfProbeScope(host)
  scheduleColumns()
  return {get mutationLocked(){return readingMode||!editor.isEditable}, refresh, flushPendingEdits, getReadSelection: () => docxAIReadSelection(editor.state.doc, editor.state.selection, readSourceDoc, anchors, nestedInputActive), setSaving(value: boolean) { saving = value; pendingHfEditor?.setEditable(!value && !readingMode && context.editingEnabled && !documentToolModels.protection?.contentLocked && !draft.closed); editor.setEditable(context.editingEnabled && !readingMode && !documentToolModels.protection?.contentLocked && !saving && !draft.closed, false); editor.commands.setMeta('native-section-layout', true); findReplace.refreshLock(); textRevisions.refresh(); bookmarkControls?.refresh(); crossReferenceControls?.refresh(); captionDialog?.refresh(); commentControls?.refresh(); commentCreationControls?.refresh(); commentReplyControls?.refresh(); toolbar.querySelectorAll<HTMLButtonElement>('[data-mutates=true], [data-editable-action=true]').forEach(control => { control.disabled = !context.editingEnabled || readingMode || saving || draft.closed }) },
    dispose() {host.removeEventListener('keydown',lifecycleKey,true);cellControls.dispose();lifecycleControls.dispose();fileActions.dispose();imageDrop.dispose();contextMenu.dispose();contextBindings.dispose();mailExportAbort.abort();if(mailExportUrl)URL.revokeObjectURL(mailExportUrl);mailExportDelivery.remove();tableStyleControls.dispose();disposeAutocorrect();disposePreferences?.();fieldControls.dispose(); documentTools.dispose();host.removeEventListener('keydown',updateFieldsKey);chartFieldControls.dispose();objectControls.dispose();exportControls.dispose();compareDisposed=true;compareControls?.dispose();reviewPresets?.dispose(); mailMergeControls.dispose(); host.removeEventListener('native-mail-merge-open',mailMergeControls.open); wordCountControl.dispose(); spellcheckControl.dispose(); formattingMarks.dispose(); pictureControls.dispose();pictureFormatControls.dispose(); stylesPane.dispose(); reviewView.dispose(); host.removeEventListener('focusin', nestedFocus); ready = false; columnRequest++; cancelAnimationFrame(columnFrame); editor.off('transaction', columnTransaction); editor.off('transaction', view.refresh); findReplace.dispose(); textRevisions.dispose(); bookmarkControls?.dispose(); crossReferenceControls?.dispose(); captionDialog?.dispose(); commentControls?.dispose(); commentCreationControls?.dispose(); commentReplyControls?.dispose(); noteDialog.dispose(); ruler.dispose(); navigation.dispose(); gridlines.dispose(); tableGridlines.dispose(); outline.dispose(); view.dispose(); equationRoot.unmount();equationHost.remove();host.removeEventListener('native-equation-error',equationError);previewRoot.unmount(); editor.destroy(); void adoptEmbeddedFonts([]); releaseHfProbeScope(); host.remove() } }
}
