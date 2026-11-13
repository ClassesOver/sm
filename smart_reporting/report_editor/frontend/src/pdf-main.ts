import {bindPdfFormTextPropertiesPanel,validateRestoredPdfFormTextProperties} from './pdf-form-text-properties'
import {bindPdfRadioExtensionPanel,validateRestoredPdfRadioExtension} from './pdf-form-radio-extension'
import type {bindNativePDFFormAI} from './native-pdf-form-ai'
import { styleOfficeAIEntry } from './office-ai-entry'
import {bindPdfReplacementStyle,isStyledPdfReplacement} from './pdf-replace-text-style'
import {bindPdfTextEditShortcuts} from './pdf-text-edit-shortcuts'
import {mountPdfFormCanvas,type PdfFormCanvasController,type PdfFormCanvasSelection} from './pdf-form-canvas'
import { addPdfCommandIcon } from './pdf-ribbon-command-icons'
import { bindPdfStaticText, PDF_STATIC_TEXT_ALONE_REASON } from './pdf-static-text'
import { mountPdfCropCanvas } from './pdf-crop-canvas'
import { bindPdfExtractDialog } from './pdf-extract-dialog'
import { bindPdfProtectionDialog } from './pdf-protection'
import { bindPdfExternalPagesDialog } from './pdf-external-pages'
import {bindPdfExistingImagePanel,validatePdfExistingImage} from './pdf-existing-image'
import {bindPdfFormCreatePanel,stagePdfFormCreation,validateRestoredPdfFormCreation,stagePdfFormRequired,stagePdfFormWidgetProperties,stagePdfFormWidgetArrangement,type PdfFormCreation} from './pdf-form-create'
import { bindPdfFormDesignPanel,stagePdfFormWidgetRemoval } from './pdf-form-design'
import { bindNativePDFReview } from './native-pdf-review'
import { bindNativePDFAssistant } from './native-pdf-assistant'
import { mountDrawingCanvas, type DrawingCanvasController } from './pdf-drawing-canvas'
import { pendingDrawingTarget, movePendingDrawing, resizePendingImage, removePendingDrawing, type PendingDrawingReference, type PendingImageAnchor } from './pdf-pending-drawings'
import { toggleSavedDrawing } from './pdf-saved-drawings'
import { stagePdfReply, stagePendingPdfReply, stagePdfLocalReply } from './pdf-replies'
import { attachmentEditState, attachmentFileOperation, isAttachmentEdit } from './pdf-attachment-edits'
/** PDF.js canvas/text-layer hosting follows GenOffice PdfPage.tsx at 4b55db9.
 * Desktop IPC is replaced by the native API; original source page IDs stay authoritative.
 */
import { AnnotationMode, GlobalWorkerOptions, TextLayer, getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs'
import type { PDFDocumentProxy, PDFDocumentLoadingTask, PDFPageProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import 'pdfjs-dist/web/pdf_viewer.css'
import './pdf.css'
import './pdf-ribbon.css'
import './office-theme.css'
import type { NativeContextResponse, createNativeApi } from './native-api'
import { NativeDraft, type NativeOperation } from './native-draft'
import type { EditorShell } from './shell'
import { bytesSha256 } from './source-validation'
import { DEFAULT_HEADER_FOOTER, DEFAULT_WATERMARK } from './vendor/genoffice-pdf/renderer/stamps'
import { parseCalibration, type MeasureScale } from './vendor/genoffice-pdf/renderer/measure'
import { PDF_DRAW_COLORS, PDF_PAPER_SIZES, PDF_PAGE_LAYOUT_ALONE_REASON, pdfLineLength, pdfMergePagesOperation, pdfRedactionOperation, pdfSplitPagesOperation, blankPdfBytes, pdfMeasurementOperation, buildPdfStampsOperation, pdfDrawingOperation, type PdfDrawingShape, insertBlankPdfPage, setPdfPageSize, cropAllPdfPages, cropPdfPage, pdfCropFromMargins, pdfPageViewport, deletePdfPage, movePdfPage, pdfCanPrint, pdfPageState, pdfPrintPages, pdfRectFromClient, renderPdfPrintHost, reversePdfPages, rotateAllPdfPages, stickyNoteRect, PdfPreviewReview, type PdfFormField, type PdfTextObject, type PdfModel, type PdfPageIdentity, type PdfRect } from './pdf-operations'
import { createPdfRibbon } from './pdf-ribbon'
import { PDF_PAGE_RIBBON_GROUPS } from './pdf-page-ribbon'
import { PDF_HOME_READ_ONLY_COMMANDS } from './pdf-home-ribbon'
import { PDF_VIEW_RIBBON_GROUPS, resolvePdfOutline, type ResolvedPdfOutlineItem } from './pdf-view-ribbon'
import { createPdfRibbonIcon, type PdfRibbonIconName } from './pdf-ribbon-icons'
import { pdfRibbonLabel } from './pdf-ribbon-locales'
const PDF_OBJECT_DESIGN_KINDS=['transformExistingImage','createFormField','editFormFieldRequired','editFormWidget','arrangeFormWidgets','appendRadioWidget','editFormTextProperties']
const PDF_EXCLUSIVE_DRAFT_KINDS=['insertText','removeFormWidget',...PDF_OBJECT_DESIGN_KINDS]
const PDF_REVIEW_KINDS=['replaceText',...PDF_EXCLUSIVE_DRAFT_KINDS]

import { MARKUP_COLORS, quadToRect, selectionQuadsByPage } from './genoffice-pdf-annotations'
import { markupSelectionState, togglePdfMarkup, type MarkupType, type PdfMarkupSelection } from './pdf-markup'

import { createSearchIndexCache, searchInIndex, type SearchIndex } from './genoffice-pdf-search'

import { loadViewState, saveViewState, type PdfFitMode, type PdfViewState } from './genoffice-pdf-reading-state'
import { pdfReadingKey, capturePdfReading, restorePdfReading } from './pdf-reading-state'

import { PdfAttachmentCache, humanBytes, attachmentDownloadName, type PdfAttachmentRow } from './pdf-attachments'

import { PdfAnnotationCache, projectPageComments, filterComments, flattenComments, type CommentNode, type CommentTarget } from './pdf-comments'

import { stagePdfNote, stagePendingPdfNote, type PendingPdfNoteReference, type SavedPdfNote } from './pdf-notes'

import { createPdfSidebarSizing } from './pdf-sidebar'

import { spreadRows } from './genoffice-pdf-spread'
import { fitPdfRows } from './pdf-fit-state'

import { PDF_ZOOM_STEPS, clampPdfZoom, stepPdfZoom, capturePdfZoomAnchor, restorePdfZoomAnchor, type PdfZoomAnchor } from './pdf-view-state'

GlobalWorkerOptions.workerSrc = workerUrl
const ASSET_BASE = '/reports/v1/editor/assets/pdfjs/'
const MAX_PAGE_PIXELS = 48_000_000
interface Options { api: ReturnType<typeof createNativeApi>; context: NativeContextResponse; draft: NativeDraft; onDraftChange?: () => void; onSelectionChange?: (selection: {pageId: string; objectId: string}[]) => void }
interface PdfThumbnailEntry { key: string; canvas: HTMLCanvasElement; task?: RenderTask; loaded: boolean; wanted: boolean; show(): void; hide(): void }
export interface PdfEditorHandle { setSaving(saving: boolean): void; refresh(): Promise<void>; dispose(): void; prepareSave(): Promise<{ confirmedPreviewDigest?: string }> }

export async function createPdfEditorView(shell: EditorShell, { api, context: response, draft, onDraftChange, onSelectionChange }: Options): Promise<PdfEditorHandle> {
  const root = shell.editor
  const context = response.context
  if (context.format !== 'pdf') throw new Error('文件格式不是 PDF')
  root.classList.add('native-pdf-editor')
  root.replaceChildren()
  const abort = new AbortController()
  let disposed = false, locked = true, generation = 0, document: PDFDocumentProxy | undefined
  let mode: 'select' | 'highlight' | 'note' | 'text' | 'draw' | 'redact' | 'staticText' = 'select'
  let drawShape: PdfDrawingShape = 'rect'
  let drawColor: [number, number, number] = [...PDF_DRAW_COLORS[0]!.rgb]
  const drawButtons = new Map<PdfDrawingShape, HTMLButtonElement>()
  // 多边形逐点放置：当前页的待完成顶点（PDF 坐标）与预览层。
  let polygonDraft: { pageId: string; vertices: number[][]; preview?: SVGElement; finish: () => void } | undefined
  const cancelPolygon = () => { polygonDraft?.preview?.remove(); polygonDraft = undefined }
  root.addEventListener('keydown', event => {
    if (!polygonDraft) return
    if (event.key === 'Escape') { cancelPolygon(); status.textContent = '已取消多边形' }
    else if (event.key === 'Enter') { event.preventDefault(); polygonDraft.finish() }
  }, { signal: abort.signal })
  const textEnabled = response.pdfTextEnabled === true && response.editingEnabled
  const review = new PdfPreviewReview()
  let previewing = false, previewDocument: PDFDocumentProxy | undefined, previewLoading: PDFDocumentLoadingTask | undefined
  let sourceDocument: PDFDocumentProxy | undefined, indexGeneration = 0
  let textLoaded = !textEnabled, textLoadWarning = ''
  let reportedSelectionPage = ''
  let textSelectionPage = '', selectedTextId = '', lastOperationsKey = JSON.stringify(draft.operations)
  let scale = 1, fitMode: PdfFitMode = null
  const readingKey = pdfReadingKey(draft.identity)
  const readingStorage = { getItem: (key: string) => window.localStorage.getItem(key), setItem: (key: string, value: string) => window.localStorage.setItem(key, value) }
  let pendingReadingRestore: PdfViewState | null = null, sourceReadingBeforePreview: PdfViewState | null = null
  let lastStableReading: PdfViewState | null = null
  let readingRestoresSelection = false
  let fitFrame: number | undefined
  let readingReady = false, readingTimer: number | undefined
  let pendingZoomAnchor: PdfZoomAnchor | null = null
  let markupColor: [number, number, number] = [...MARKUP_COLORS.highlight]
  let markupSelection: PdfMarkupSelection[] = []
  let markupStructureKey = ''
  const markupButtons: { button: HTMLButtonElement; type: MarkupType }[] = []
  let printing = false
  let printRoot: HTMLElement | undefined
  let printTimer: number | undefined
  const tasks = new Set<RenderTask>()
  const textLayers = new Set<TextLayer>()
  const pageNodes = new Map<string, HTMLElement>()
  const pagesCached = new Map<number, PDFPageProxy>()
  const thumbnailCache = new WeakMap<PDFDocumentProxy, Map<string, PdfThumbnailEntry>>()
  const thumbnailTasks = new Set<RenderTask>()
  let thumbnailObserver: IntersectionObserver | undefined, thumbnailDocument: PDFDocumentProxy | undefined
  let thumbnailSlots = new Map<Element,PdfThumbnailEntry>()
  let committedSidebarWidth = 150, sidebarRasterFrame: number | undefined
  const searchCache = createSearchIndexCache()
  let searchIndex: SearchIndex = [], searchPageIds: string[] = []
  let searchMatches: { pageId: string; rects: [number, number, number, number][] }[] = []
  let searchMatchCase = false, searchWholeWord = false, searchLoading = false
  let searchJumpPending = false, searchRendering = false
  let searchTimer: number | undefined
  let observer: IntersectionObserver | undefined
  const visible = new Set<string>()
  let activeId = '', currentSearch = '', searchPosition = 0
  const ribbon = createPdfRibbon(root, { hasForms: false })
  ribbon.setLanguage(window.document.documentElement.lang || 'en')
  let commandGroup: HTMLElement
  const noteInput = documentElement('textarea', 'pdf-note-input')
  noteInput.placeholder = '输入批注后点击页面'; noteInput.setAttribute('aria-label', '文字批注内容'); noteInput.maxLength = 10000; noteInput.hidden = true
  const status = documentElement('p', 'pdf-editor-message')
  status.setAttribute('role', 'status')
  const propertiesPanel = documentElement('section', 'pdf-properties-panel'); propertiesPanel.hidden = true
  propertiesPanel.setAttribute('aria-label', 'PDF 文档属性')
  propertiesPanel.append(documentElement('h3'))
  propertiesPanel.querySelector('h3')!.textContent = '文档属性'
  const propertiesList = documentElement('dl'); propertiesPanel.append(propertiesList)
  const layout = documentElement('div', 'pdf-layout')
  const thumbs = documentElement('nav', 'pdf-thumbnails')
  thumbs.setAttribute('aria-label', '页面缩略图及顺序')
  const outlinePanel = documentElement('nav', 'pdf-outline'); outlinePanel.hidden = true; outlinePanel.setAttribute('aria-label', 'PDF 目录大纲')
  const viewport = documentElement('div', 'pdf-document-pages')
  viewport.setAttribute('aria-label', 'PDF 页面'); viewport.tabIndex = 0
  const saveReading = () => {
    if (readingTimer !== undefined) window.clearTimeout(readingTimer)
    if (!readingReady || disposed || !document || previewDocument || previewing || printing) return
    // Reflow may temporarily remove rows. Preserve the last source position and
    // the latest explicit zoom/fit intent when pagehide arrives before it settles.
    const current = searchRendering || pendingReadingRestore
      ? pendingReadingRestore ?? lastStableReading
      : capturePdfReading(viewport, model.pages.map(page => page.pageId), scale, fitMode)
    if (current) { lastStableReading = { ...current, scale, fitMode }; saveViewState(readingKey, lastStableReading, readingStorage) }
  }
  const scheduleReading = () => { if (readingTimer !== undefined) window.clearTimeout(readingTimer); readingTimer = window.setTimeout(saveReading, 300) }
  const cancelReadingRestore = () => { pendingReadingRestore = null; readingRestoresSelection = false }
  viewport.addEventListener('scroll', scheduleReading, { passive: true, signal: abort.signal })
  for (const event of ['pointerdown', 'wheel', 'keydown']) root.addEventListener(event, cancelReadingRestore, { capture: true, passive: true, signal: abort.signal })
  window.addEventListener('pagehide', saveReading, { signal: abort.signal })
  const commentsPanel = documentElement('aside', 'pdf-comments-sidebar'); commentsPanel.hidden = true; commentsPanel.setAttribute('aria-label', '全文便签批注')
  const commentsHeading = documentElement('header'), commentsTitle = documentElement('strong'); commentsTitle.textContent = '便签批注'
  const closeComments = documentElement('button', 'pdf-tool'); closeComments.type = 'button'; closeComments.textContent = '关闭批注侧栏'; commentsHeading.append(commentsTitle, closeComments)
  const commentsFilter = documentElement('input'); commentsFilter.type = 'search'; commentsFilter.placeholder = '搜索正文或作者'; commentsFilter.setAttribute('aria-label', '筛选便签批注')
  const commentsStatus = documentElement('p'); commentsStatus.setAttribute('role', 'status')
  const commentsList = documentElement('div', 'pdf-comment-list'); commentsList.setAttribute('role', 'list')
  const retryComments = documentElement('button', 'pdf-tool'); retryComments.type = 'button'; retryComments.textContent = '重试未读页面'; retryComments.hidden = true
  commentsPanel.append(commentsHeading, commentsFilter, commentsStatus, retryComments, commentsList)
  const attachmentsPanel = documentElement('aside', 'pdf-attachments-sidebar'); attachmentsPanel.hidden = true; attachmentsPanel.setAttribute('aria-label', 'PDF 附件')
  const attachmentsHeading = documentElement('header'), attachmentsTitle = documentElement('strong'); attachmentsTitle.textContent = '附件'
  const closeAttachments = documentElement('button', 'pdf-tool'); closeAttachments.type = 'button'; closeAttachments.textContent = '关闭附件侧栏'; attachmentsHeading.append(attachmentsTitle, closeAttachments)
  const attachmentNotice = documentElement('p'); attachmentNotice.textContent = '新增附件单文件最多 2 MiB、每次共 6 MiB。删除只移除附件目录，不能擦除敏感数据。'
  const addAttachment = documentElement('button', 'pdf-tool'); addAttachment.type = 'button'; addAttachment.textContent = '新增附件'
  const attachmentFile = documentElement('input'); attachmentFile.type = 'file'; attachmentFile.hidden = true; attachmentFile.setAttribute('aria-label', '选择新增附件')
  addAttachment.addEventListener('click', () => { if (canEditAttachments()) attachmentFile.click() })
  attachmentFile.addEventListener('change', () => { void stageAttachmentFile().catch(showError) })
  const attachmentsStatus = documentElement('p'); attachmentsStatus.setAttribute('role', 'status')
  const attachmentsList = documentElement('ul', 'pdf-attachments-list')
  const retryAttachments = documentElement('button', 'pdf-tool'); retryAttachments.type = 'button'; retryAttachments.textContent = '重试附件读取'; retryAttachments.hidden = true
  attachmentsPanel.append(attachmentsHeading, attachmentNotice, addAttachment, attachmentFile, attachmentsStatus, retryAttachments, attachmentsList)
  const sidebarDivider = documentElement('div', 'pdf-sidebar-resizer')
  const sidebarPanels = { thumbs, outline: outlinePanel, comments: commentsPanel, attachments: attachmentsPanel }
  const sidebarId = `pdf-sidebar-${crypto.randomUUID()}`
  for (const [name,panel] of Object.entries(sidebarPanels)) panel.id = `${sidebarId}-${name}`
  layout.append(thumbs, outlinePanel, commentsPanel, attachmentsPanel, sidebarDivider, viewport)
  const sidebarSizing = createPdfSidebarSizing(sidebarDivider, (width,committed) => {
    layout.style.setProperty('--pdf-sidebar-width',`${width}px`)
    if (!committed) return
    committedSidebarWidth = width
    if (!disposed && document && readingReady && sidebarRasterFrame === undefined) sidebarRasterFrame = requestAnimationFrame(() => { sidebarRasterFrame = undefined; if (!disposed) void refresh().catch(showError) })
  })
  committedSidebarWidth = sidebarSizing.width; sidebarSizing.setPanel(thumbs)
  const attachmentCache = new PdfAttachmentCache()
  let attachmentsGeneration = 0
  const attachmentDownloads = new Map<string, number>()
  closeAttachments.addEventListener('click', () => setSidebar(null))
  retryAttachments.addEventListener('click', () => { void loadAttachments() })
  const annotationCache = new PdfAnnotationCache()
  let sidebar: 'thumbs' | 'outline' | 'comments' | 'attachments' | null = 'thumbs', commentsGeneration = 0, commentsLoading = false
  let commentRoots: CommentNode[] = [], commentsRead = 0, commentsTotal = 0, commentsFailed = 0, selectedComment = ''
  let commentsSnapshot = '', commentsDocument: PDFDocumentProxy | undefined, pendingCommentJump: CommentTarget | null = null
  commentsFilter.addEventListener('input', () => renderComments())
  closeComments.addEventListener('click', () => setSidebar(null))
  retryComments.addEventListener('click', () => { void loadComments() })
  const textPanel = documentElement('section', 'pdf-text-editor'); textPanel.hidden = true
  const textObjects = documentElement('select'); textObjects.setAttribute('aria-label', '待修改文字对象')
  const originalText = documentElement('p', 'pdf-original-text')
  const replacement = documentElement('textarea'); replacement.setAttribute('aria-label', '替换后的文字'); replacement.maxLength = 4000
  const stageText = documentElement('button'); stageText.type = 'button'; stageText.textContent = '加入文字修改'
  const textHelp = documentElement('p'); textHelp.textContent = '仅修改选中的原始文字对象；最多 4000 字符。Ctrl/Cmd+Enter 加入修改；Enter 换行。请生成实际预览，核对未执行的修改后保存。'
  textPanel.append(textObjects, originalText, replacement)
  const replacementStyle=bindPdfReplacementStyle(textPanel)
  textPanel.append(stageText,textHelp)
  const reviewPanel = documentElement('section', 'pdf-preview-review'); reviewPanel.hidden = true
  const reviewTitle = documentElement('p'); reviewTitle.textContent = '实际 PDF 预览与执行清单'
  const reviewList = documentElement('ul')
  const confirmLabel = documentElement('label'), confirmPreview = documentElement('input'); confirmPreview.type = 'checkbox'
  const confirmText = documentElement('span')
  confirmLabel.append(confirmPreview, confirmText); reviewPanel.append(reviewTitle, reviewList, confirmLabel)
  confirmPreview.addEventListener('change', () => { try { review.confirm(draft.operations, confirmPreview.checked) } catch (error) { confirmPreview.checked = false; showError(error) } })
  const drawingsPanel = documentElement('section', 'pdf-saved-drawings'); drawingsPanel.hidden = true
  drawingsPanel.setAttribute('aria-label', '已保存绘图')
  const pendingDrawingsPanel = documentElement('section', 'pdf-pending-drawings-panel'); pendingDrawingsPanel.hidden = true
  pendingDrawingsPanel.setAttribute('aria-label', '待保存绘图')
  let selectedPendingDrawing: PendingDrawingReference | undefined, pendingDrawingsGeneration = 0
  const drawingCanvases = new Set<DrawingCanvasController>()
  const formCanvases = new Set<PdfFormCanvasController>()
  let selectedFormWidget:PdfFormCanvasSelection|undefined
  function clearFormCanvases(){for(const controller of formCanvases)controller.dispose();formCanvases.clear()}
  function syncFormCanvases(){
    if(root.querySelector('[data-pdf-ribbon-tab="formDesign"]')?.getAttribute('aria-selected')!=='true')selectedFormWidget=undefined
    for(const controller of formCanvases)if(!controller.sync()){controller.dispose();formCanvases.delete(controller)}
  }
  for(const type of ['click','keydown'])root.addEventListener(type,event=>{
    if((event.target as Element|null)?.closest('[data-pdf-ribbon-tab]'))syncFormCanvases()
  },{signal:abort.signal})
  let drawingActiveId = activeId
  function clearDrawingCanvases() { for (const controller of drawingCanvases) controller.dispose(); drawingCanvases.clear() }
  function syncDrawingCanvases() {
    syncFormCanvases()
    if (drawingActiveId !== activeId) {
      for (const controller of drawingCanvases) controller.cancel()
      drawingActiveId = activeId
      if (selectedPendingDrawing?.pageId !== activeId) selectedPendingDrawing = undefined
    }
    for (const controller of drawingCanvases) if (!controller.sync()) drawingCanvases.delete(controller)
  }
  let pendingDrawingDialog: HTMLDialogElement | undefined
  root.append(noteInput, textPanel, status, propertiesPanel, reviewPanel, drawingsPanel, pendingDrawingsPanel, layout)
  const editableButtons: HTMLButtonElement[] = []
  const pageInputs: HTMLInputElement[] = []
  function button(label: string, action: () => void | Promise<void>, editable = true, icon?: PdfRibbonIconName) {
    const element = documentElement('button', 'pdf-tool')
    element.type = 'button'
    if (icon) element.append(createPdfRibbonIcon(icon, 18))
    else addPdfCommandIcon(element, label)
    const text = documentElement('span'); text.textContent = pdfRibbonLabel(label); element.append(text)
    element.addEventListener('click', () => {
      if (editable && draft.operations.some(operation => PDF_EXCLUSIVE_DRAFT_KINDS.includes(operation.kind)) && element !== undo && element !== redo) { showError(new Error('此项 PDF 编辑须单独保存，请先保存或撤销当前修改')); return }
      void Promise.resolve().then(action).catch(showError)
    })
    commandGroup.append(element)
    if (editable) editableButtons.push(element)
    return element
  }
  let pdfAssistant: ReturnType<typeof bindNativePDFAssistant> | undefined
  let pdfFormAI: ReturnType<typeof bindNativePDFFormAI> | undefined
  let pdfReview: ReturnType<typeof bindNativePDFReview> | undefined
  let formDesignPanel: ReturnType<typeof bindPdfFormDesignPanel> | undefined
  let textPropertiesPanel:ReturnType<typeof bindPdfFormTextPropertiesPanel>|undefined
  let radioExtensionPanel:ReturnType<typeof bindPdfRadioExtensionPanel>|undefined
  let formCreatePanel:ReturnType<typeof bindPdfFormCreatePanel>|undefined
  let existingImagePanel:ReturnType<typeof bindPdfExistingImagePanel>|undefined
  const sourceCommand = (element: HTMLElement, id: string) => {
    addPdfCommandIcon(element, id)
    element.dataset.sourceCommandId = `genoffice.pdf.${id}`
    return element
  }
  function createPageInput(id: string) {
    const row = documentElement('label', 'pdf-view-page-row')
    const input = documentElement('input', 'pdf-view-page-input')
    input.type = 'number'; input.min = '1'; input.setAttribute('aria-label', pdfRibbonLabel('跳转到页面'))
    sourceCommand(input, id)
    input.addEventListener('change', () => jumpToPage(input))
    input.addEventListener('keydown', event => { if (event.key === 'Enter') jumpToPage(input) })
    const total = documentElement('span')
    row.append(input, total)
    pageInputs.push(input)
    return { row, input, total }
  }
  function unavailableSourceGroup(tab: 'home' | 'annotate' | 'page' | 'view', groupName: string, items: { id: string; label: string; reason: string }[], target?: HTMLElement) {
    const group = target ?? ribbon.group(tab, groupName)
    for (const item of items) {
      const action = documentElement('button', 'pdf-tool')
      action.type = 'button'; action.textContent = item.label; action.disabled = true; action.title = item.reason
      sourceCommand(action, item.id)
      action.setAttribute('aria-label', `${item.label}，${item.reason}`)
      group.append(action)
    }
    return group
  }
  function createMarkupPalette() {
    const markupPalette = documentElement('div', 'pdf-ribbon-palette')
    const palette = documentElement('div', 'pdf-ribbon-swatches'); palette.setAttribute('role', 'group'); palette.setAttribute('aria-label', '标注颜色')
    const swatches: HTMLButtonElement[] = []
    for (const color of ['#000000', '#808080', '#ffffff', '#e53935', '#fb8c00', '#fdd835', '#7cb342', '#22a75a', '#00acc1', '#2b66ff', '#7e57c2', '#d81b60']) {
      const swatch = documentElement('button', 'pdf-ribbon-swatch'); swatch.type = 'button'; swatch.style.backgroundColor = color; swatch.title = color; swatch.setAttribute('aria-label', `标注颜色 ${color}`)
      swatch.dataset.ribbonCommand = 'markup-color-preset'
      swatch.setAttribute('aria-pressed', String(color === '#fdd835'))
      swatch.addEventListener('click', () => {
        markupColor = [parseInt(color.slice(1, 3), 16) / 255, parseInt(color.slice(3, 5), 16) / 255, parseInt(color.slice(5, 7), 16) / 255]
        root.querySelectorAll<HTMLButtonElement>('[data-ribbon-command="markup-color-preset"]').forEach(item => item.setAttribute('aria-pressed', String(item === swatch)))
      })
      swatches.push(swatch)
      palette.append(swatch)
    }
    const customColor = documentElement('input'); customColor.type = 'color'; customColor.value = '#ffde59'; customColor.setAttribute('aria-label', '更多标注颜色')
    customColor.addEventListener('input', () => {
      const color = customColor.value
      markupColor = [parseInt(color.slice(1, 3), 16) / 255, parseInt(color.slice(3, 5), 16) / 255, parseInt(color.slice(5, 7), 16) / 255]
      root.querySelectorAll<HTMLButtonElement>('[data-ribbon-command="markup-color-preset"]').forEach(item => item.setAttribute('aria-pressed', 'false'))
    })
    markupPalette.title = '设置高亮颜色；下划线、波浪线和删除线使用固定源颜色'
    markupPalette.append(palette, customColor)
    return markupPalette
  }
  const unavailableGroup = (tab: 'home' | 'annotate' | 'edit' | 'page' | 'view' | 'fillForm' | 'formDesign', groupName: string, commands: string[], reason: string) => {
    const group = ribbon.group(tab, groupName)
    for (const label of commands) {
      const action = documentElement('button', 'pdf-tool')
      action.type = 'button'; action.textContent = label; action.disabled = true; action.title = reason
      addPdfCommandIcon(action, label)
      action.setAttribute('aria-label', `${label}，${reason}`)
      group.append(action)
    }
  }
  commandGroup = ribbon.group('home', 'AI')
  function readAIButton(label: string, id: string, action: 'ask' | 'summarize' | 'keyPoints' | 'reviewSummary') {
    const control = button(label, () => pdfAssistant?.open(action), false, 'sparkles')
    sourceCommand(control, id)
    control.disabled = response.pdfReadAIEnabled !== true
    if (control.disabled) control.title = 'PDF AI 阅读尚未开放'
    return control
  }
  commandGroup.classList.add('office-ai-group')
  styleOfficeAIEntry(readAIButton('AI 助手', 'home.ai.openAssistant', 'ask'))
  readAIButton('AI 总结', 'home.ai.summarize', 'summarize')
  readAIButton('AI 关键要点', 'home.ai.keyPoints', 'keyPoints')
  commandGroup = ribbon.group('home', 'Markup')
  const homeMarkupGroup = commandGroup
  function selectionMarkupButton(type: MarkupType, label: string, sourceId: string) {
    const control = button(label, () => applySelectedMarkup(type), true, type === 'highlight' ? 'highlight' : undefined)
    control.addEventListener('mousedown', event => event.preventDefault())
    sourceCommand(control, sourceId); markupButtons.push({ button: control, type }); return control
  }
  for (const [type, label] of [['highlight', '高亮'], ['underline', '下划线'], ['squiggly', '波浪线'], ['strikeout', '删除线']] as const) selectionMarkupButton(type, label, `home.markup.${type}`)
  homeMarkupGroup.append(createMarkupPalette())
  commandGroup = ribbon.group('home', 'Edit')
  const homeEditGroup = commandGroup
  const undo = button('撤销', async () => { draft.undo(); await refresh() }, true, 'undo')
  const redo = button('重做', async () => { draft.redo(); await refresh() }, true, 'redo')
  sourceCommand(undo, 'home.edit.undo')
  sourceCommand(redo, 'home.edit.redo')
  const homeTextEdit = button('原位改字', () => { setMode('text'); renderTextPanel(true) }, true)
  sourceCommand(homeTextEdit, 'home.edit.editText')
  homeEditGroup.append(homeTextEdit)
  const insertStaticText = button('插入文字', () => staticText?.open(), true)
  sourceCommand(insertStaticText, 'home.edit.insertText')
  let staticText: ReturnType<typeof bindPdfStaticText> | undefined
  commandGroup = ribbon.group('home', 'Convert & Export')
  const homeConvertGroup = commandGroup
  const downloads = documentElement('a', 'pdf-original-download')
  downloads.textContent = pdfRibbonLabel('下载当前 PDF'); downloads.href = `/reports/v1/native/${encodeURIComponent(context.documentId)}/${context.revision}/api/file`; downloads.download = 'report.pdf'
  sourceCommand(downloads, 'home.convert.downloadOriginal')
  commandGroup.append(downloads)
  const officeConvertButtons:HTMLButtonElement[]=[]
  for (const [format,label,id] of [['docx','转换为 Word','home.convert.toWord'],['xlsx','转换为 Excel','home.convert.toExcel']] as const) {
    commandGroup=homeConvertGroup;const control=button(label,()=>officeConversion.open(format));sourceCommand(control,id);officeConvertButtons.push(control)
  }
  commandGroup = ribbon.group('home', 'Page & Zoom')
  const homePageInput = createPageInput('home.pageZoom.goToPage')
  commandGroup.append(homePageInput.row)
  const homeZoom = documentElement('select', 'pdf-zoom')
  homeZoom.setAttribute('aria-label', '页面缩放')
  for (const value of PDF_ZOOM_STEPS) { const option = documentElement('option'); option.value = String(value); option.textContent = `${Math.round(value * 100)}%`; homeZoom.append(option) }
  homeZoom.value = '1'; homeZoom.addEventListener('change', () => setZoom(Number(homeZoom.value))); commandGroup.append(homeZoom)
  const fittedScale = (mode: 'width' | 'page') => {
    if (!document) return
    const pages = state(), items = []
    const pixels = (value: string) => Number.parseFloat(value) || 0
    for (const [index, page] of pages.entries()) {
      const original = pagesCached.get(previewDocument ? index : page.index)
      if (!original) return
      const unit = displayViewport(original, page, 1), card = pageNodes.get(page.pageId), content = card?.querySelector<HTMLElement>('.pdf-page-content')
      const style = card && getComputedStyle(card)
      const chromeWidth = style ? pixels(style.borderLeftWidth) + pixels(style.borderRightWidth) + pixels(style.paddingLeft) + pixels(style.paddingRight) : 10
      const chromeHeight = style && content ? content.getBoundingClientRect().top - card!.getBoundingClientRect().top + pixels(style.paddingBottom) + pixels(style.borderBottomWidth) : 36
      items.push({ width: unit.width, height: unit.height, chromeWidth, chromeHeight })
    }
    const style = getComputedStyle(viewport)
    return fitPdfRows(items, twoPageView ? 2 : 1, mode, viewport.clientWidth - pixels(style.paddingLeft) - pixels(style.paddingRight), viewport.clientHeight - pixels(style.paddingTop) - pixels(style.paddingBottom)) ?? undefined
  }
  const scheduleFit = () => {
    if (disposed || !fitMode || !document || fitFrame !== undefined) return
    fitFrame = requestAnimationFrame(() => {
      fitFrame = undefined
      if (disposed || !fitMode || !document || !readingReady || searchRendering || printing || previewing) return
      try {
        const next = fittedScale(fitMode)
        if (next !== undefined && Math.abs(next - scale) > .0001) setZoom(next, 0, 0, false)
      } catch (error) { showError(error) }
    })
  }
  const fitObserver = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(scheduleFit)
  fitObserver?.observe(viewport)
  window.addEventListener('resize', scheduleFit, { signal: abort.signal })
  const fitScale = (mode: 'width' | 'page') => {
    const next = fittedScale(mode)
    if (next === undefined) return
    cancelReadingRestore(); fitMode = mode; setZoom(next, 0, 0, false); scheduleReading()
  }
  const homeZoomOut = button('缩小', () => setZoom(stepPdfZoom(scale, -1)), false)
  const homeZoomIn = button('放大', () => setZoom(stepPdfZoom(scale, 1)), false)
  sourceCommand(homeZoomOut, 'home.pageZoom.zoomOut'); sourceCommand(homeZoomIn, 'home.pageZoom.zoomIn')
  sourceCommand(button('适合宽度', () => fitScale('width'), false), 'home.pageZoom.fitWidth')
  sourceCommand(button('适合页面', () => fitScale('page'), false), 'home.pageZoom.fitPage')
  commandGroup = ribbon.group('home', 'Search, Print & Properties')
  const searchPrintGroup = commandGroup
  const printButton = documentElement('button', 'pdf-tool pdf-ribbon-big')
  printButton.type = 'button'; printButton.append(createPdfRibbonIcon('print', 22))
  const printLabel = documentElement('span'); printLabel.textContent = pdfRibbonLabel('打印'); printButton.append(printLabel)
  printButton.title = pdfRibbonLabel('打印完整 PDF；未保存草稿不可打印')
  printButton.addEventListener('click', () => { void printPdf().catch(showError) })
  sourceCommand(printButton, 'home.print.print')
  const search = documentElement('input', 'pdf-search')
  search.type = 'search'; search.placeholder = '搜索文字'; search.setAttribute('aria-label', '搜索 PDF 文字')
  sourceCommand(search, 'home.search.search')
  searchPrintGroup.append(search)
  search.addEventListener('input', () => { currentSearch = search.value.trim(); scheduleSearch() })
  function openSearch() {
    root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="home"]')?.click()
    search.focus(); search.select()
  }
  search.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); stepSearch(event.shiftKey ? -1 : 1) }
    else if (event.key === 'Escape') { event.preventDefault(); search.value = ''; currentSearch = ''; runSearch(false); viewport.focus() }
  })
  window.document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') { event.preventDefault(); openSearch() }
  }, { signal: abort.signal })
  const matchCase = button('区分大小写', () => { searchMatchCase = !searchMatchCase; matchCase.setAttribute('aria-pressed', String(searchMatchCase)); scheduleSearch() }, false)
  sourceCommand(matchCase, 'search.matchCase'); matchCase.setAttribute('aria-pressed', 'false')
  const wholeWord = button('全词匹配', () => { searchWholeWord = !searchWholeWord; wholeWord.setAttribute('aria-pressed', String(searchWholeWord)); scheduleSearch() }, false)
  sourceCommand(wholeWord, 'search.wholeWord'); wholeWord.setAttribute('aria-pressed', 'false')
  const searchCount = documentElement('span', 'pdf-search-count'); searchCount.setAttribute('role', 'status'); searchCount.setAttribute('aria-label', '搜索匹配计数')
  searchPrintGroup.append(matchCase, wholeWord, searchCount)
  const stepSearch = (direction: -1 | 1) => {
    if (searchTimer !== undefined) runSearch(false)
    if (!searchMatches.length) return
    searchPosition = (searchPosition + direction + searchMatches.length) % searchMatches.length
    markSearch(); jumpSearch()
  }
  const previousSearch = button('上一处', () => stepSearch(-1), false)
  sourceCommand(previousSearch, 'home.search.previousMatch')
  const nextSearch = button('下一处', () => stepSearch(1), false)
  sourceCommand(nextSearch, 'home.search.nextMatch')
  searchPrintGroup.append(previousSearch, nextSearch, printButton)
  const propertiesButton = button(PDF_HOME_READ_ONLY_COMMANDS[0].label, () => { propertiesPanel.hidden = !propertiesPanel.hidden }, false)
  sourceCommand(propertiesButton, 'home.properties.documentProperties')
  const toggleThumbnails = documentElement('button', 'pdf-tool'); toggleThumbnails.type = 'button'; toggleThumbnails.textContent = pdfRibbonLabel('缩略图'); toggleThumbnails.setAttribute('aria-pressed', 'true')
  toggleThumbnails.addEventListener('click', () => setSidebar(sidebar === 'thumbs' ? null : 'thumbs'))
  let outline: ResolvedPdfOutlineItem[] = []
  const viewNavigation = ribbon.group('view', 'Navigation')
  commandGroup = viewNavigation
  sourceCommand(toggleThumbnails, 'view.navigation.thumbnails')
  viewNavigation.append(toggleThumbnails)
  const focusSearch = button('搜索', openSearch, false)
  sourceCommand(focusSearch, 'view.navigation.search')
  commandGroup = viewNavigation
  const outlineToggle = button('目录大纲', () => {
    setSidebar(sidebar === 'outline' ? null : 'outline')
  }, false)
  sourceCommand(outlineToggle, 'view.navigation.outline'); outlineToggle.setAttribute('aria-pressed', 'false')
  const commentsToggle = button('批注侧栏', () => setSidebar(sidebar === 'comments' ? null : 'comments'), false)
  sourceCommand(commentsToggle, 'view.navigation.comments'); commentsToggle.setAttribute('aria-pressed', 'false')
  const attachmentsToggle = button('附件', () => setSidebar(sidebar === 'attachments' ? null : 'attachments'), false)
  sourceCommand(attachmentsToggle, 'view.navigation.attachments'); attachmentsToggle.setAttribute('aria-pressed', 'false')
  let twoPageView = false
  const pageSpreadToggle = button('双页视图', () => {
    twoPageView = !twoPageView
    viewport.dataset.spread = twoPageView ? 'two' : 'single'
    pageSpreadToggle.textContent = pdfRibbonLabel(twoPageView ? '单页视图' : '双页视图')
    pageSpreadToggle.setAttribute('aria-pressed', String(twoPageView))
    void refresh().catch(showError)
  }, false)
  sourceCommand(pageSpreadToggle, 'view.navigation.pageSpread')
  const nightToggle = button('夜间模式', () => {
    const enabled = !viewport.classList.contains('pdf-night')
    viewport.classList.toggle('pdf-night', enabled); nightToggle.setAttribute('aria-pressed', String(enabled))
  }, false)
  sourceCommand(nightToggle, 'view.navigation.nightMode'); nightToggle.setAttribute('aria-pressed', 'false')
  unavailableSourceGroup('view', 'Navigation', PDF_VIEW_RIBBON_GROUPS[0].commands.filter(item => !item.enabled).map(item => ({ id: item.id.replace('genoffice.pdf.', ''), label: item.label, reason: item.reason! })), viewNavigation)
  for (const command of PDF_VIEW_RIBBON_GROUPS[0].commands) { const control = [...viewNavigation.querySelectorAll<HTMLElement>('[data-source-command-id]')].find(node => node.dataset.sourceCommandId === command.id); if (control) viewNavigation.append(control) }
  const viewZoomGroup = ribbon.group('view', 'Page & Zoom')
  const viewPageInput = createPageInput('view.pageZoom.goToPage')
  viewZoomGroup.append(viewPageInput.row)
  commandGroup = viewZoomGroup
  const syncZoomControls = () => {
    for (const option of [...homeZoom.options]) if (!PDF_ZOOM_STEPS.some(step => step === Number(option.value)) && Number(option.value) !== scale) option.remove()
    if (![...homeZoom.options].some(item => Number(item.value) === scale)) { const added = documentElement('option'); added.value = String(scale); added.textContent = `${Math.round(scale * 100)}%`; homeZoom.append(added) }
    homeZoom.value = String(scale); zoomSlider.value = String(Math.round(scale * 100)); zoomValue.textContent = `${Math.round(scale * 100)}%`
  }
  const setZoom = (value: number, vx = 0, vy = 0, manual = true) => {
    let next: number
    try { next = clampPdfZoom(value) } catch (error) { showError(error); return }
    if (manual) {
      fitMode = null; cancelReadingRestore()
      if (fitFrame !== undefined) { cancelAnimationFrame(fitFrame); fitFrame = undefined }
    }
    if (next === scale) { scheduleReading(); return }
    pendingZoomAnchor ??= capturePdfZoomAnchor(viewport, scale, vx, vy)
    scale = next
    syncZoomControls()
    void refresh().catch(showError)
  }
  const zoomOut = button('缩小', () => setZoom(stepPdfZoom(scale, -1)), false)
  const zoomIn = button('放大', () => setZoom(stepPdfZoom(scale, 1)), false)
  sourceCommand(zoomOut, 'view.pageZoom.zoomOut'); sourceCommand(zoomIn, 'view.pageZoom.zoomIn')
  const viewFitWidth = button('适合宽度', () => fitScale('width'), false)
  const viewFitPage = button('适合页面', () => fitScale('page'), false)
  sourceCommand(viewFitWidth, 'view.pageZoom.fitWidth'); sourceCommand(viewFitPage, 'view.pageZoom.fitPage')
  viewZoomGroup.append(zoomOut, zoomIn, viewFitWidth, viewFitPage)
  const zoomStatus = documentElement('footer', 'pdf-view-status')
  const statusZoomOut = documentElement('button'); statusZoomOut.type = 'button'; statusZoomOut.textContent = '−'; statusZoomOut.setAttribute('aria-label', '缩小页面')
  const statusZoomIn = documentElement('button'); statusZoomIn.type = 'button'; statusZoomIn.textContent = '+'; statusZoomIn.setAttribute('aria-label', '放大页面')
  const zoomSlider = documentElement('input'); zoomSlider.type = 'range'; zoomSlider.min = '10'; zoomSlider.max = '800'; zoomSlider.step = '5'; zoomSlider.value = '100'; zoomSlider.setAttribute('aria-label', '页面缩放滑块')
  const zoomValue = documentElement('span'); zoomValue.textContent = '100%'
  statusZoomOut.addEventListener('click', () => setZoom(stepPdfZoom(scale, -1)))
  statusZoomIn.addEventListener('click', () => setZoom(stepPdfZoom(scale, 1)))
  zoomSlider.addEventListener('input', () => setZoom(Number(zoomSlider.value) / 100))
  sourceCommand(statusZoomOut, 'view.status.zoomOut'); sourceCommand(statusZoomIn, 'view.status.zoomIn'); sourceCommand(zoomSlider, 'view.status.zoomSlider')
  zoomStatus.append(statusZoomOut, zoomSlider, statusZoomIn, zoomValue); root.append(zoomStatus)
  viewport.addEventListener('wheel', event => {
    if ((!event.ctrlKey && !event.metaKey) || !document || event.deltaY === 0) return
    event.preventDefault()
    const box = viewport.getBoundingClientRect()
    setZoom(scale - event.deltaY * .006, event.clientX - box.left, event.clientY - box.top)
  }, { passive: false, signal: abort.signal })
  const formGroup = ribbon.group('fillForm', '填写可填写域')
  const formControls = documentElement('div', 'pdf-form-controls')
  let formControlsKey = ''
  formGroup.append(formControls)
  const formNavigation = documentElement('div', 'pdf-form-navigation')
  const previousField = documentElement('button', 'pdf-tool')
  previousField.type = 'button'; previousField.textContent = pdfRibbonLabel('上一个字段'); previousField.dataset.pdfFormNavigation = 'previous'
  previousField.setAttribute('aria-label', '上一个可编辑表单字段')
  previousField.addEventListener('click', () => focusFormField(-1))
  const nextField = documentElement('button', 'pdf-tool')
  nextField.type = 'button'; nextField.textContent = pdfRibbonLabel('下一个字段'); nextField.dataset.pdfFormNavigation = 'next'
  nextField.setAttribute('aria-label', '下一个可编辑表单字段')
  nextField.addEventListener('click', () => focusFormField(1))
  formNavigation.append(previousField, nextField)
  formGroup.append(formNavigation)
  const fillFormAI=documentElement('button','pdf-tool');fillFormAI.type='button';fillFormAI.dataset.pdfFormAiEntry='true'
  fillFormAI.append(createPdfRibbonIcon('sparkles'),window.document.createTextNode('AI 填写表单'));fillFormAI.onclick=()=>pdfFormAI?.open()
  fillFormAI.hidden=!(response.pdfFormAIEnabled&&response.editingEnabled);formGroup.append(fillFormAI)
  unavailableGroup('fillForm', '静态表单', ['添加文本', '添加勾选', '添加叉号', '完成表单'], '静态表单填值尚未接入 PDF 写回契约')
  unavailableGroup('formDesign', '创建字段', ['签名字段'], '该字段类型尚未接入带来源身份及输出复读验证的 PDF 操作契约')
  commandGroup=ribbon.group('formDesign','创建字段')
  const createTextField=button('文本字段',()=>{if(!objectDesignUnavailable())formCreatePanel?.open('text')})
  const createCheckBox=button('复选框',()=>{if(!objectDesignUnavailable())formCreatePanel?.open('checkbox')})
  sourceCommand(createTextField,'formDesign.addTextField');sourceCommand(createCheckBox,'formDesign.addCheckBox')
  const extendedFormCreationButtons:HTMLButtonElement[]=[]
  for(const[kind,label,id]of [['date','日期字段','formDesign.addDateField'],['radio','单选按钮','formDesign.addRadioGroup'],['choice','下拉列表','formDesign.addDropdown']]as const){
    const control=button(label,()=>{if(!objectDesignUnavailable())formCreatePanel?.open(kind)});sourceCommand(control,id);extendedFormCreationButtons.push(control)
  }
  unavailableGroup('formDesign', '设计、检测与排列', ['自动检测', '预览'], '字段检测、排列与完整设计预览尚未接入来源身份契约')
  commandGroup = ribbon.group('formDesign', '字段管理')
  const formDesignDelete = button('删除字段', () => { if (!formDesignUnavailable()) formDesignPanel?.open() })
  sourceCommand(formDesignDelete, 'formDesign.deleteField')
  const fieldProperties=button('字段属性',()=>{if(!objectDesignUnavailable())formCreatePanel?.open('properties')})
  sourceCommand(fieldProperties,'formDesign.fieldProperties')
  const textFieldProperties=button('文本字段属性',()=>{if(!objectDesignUnavailable())textPropertiesPanel?.open()});sourceCommand(textFieldProperties,'formDesign.textProperties')
  const appendRadioOption=button('追加单选选项',()=>{if(!objectDesignUnavailable())radioExtensionPanel?.open()});sourceCommand(appendRadioOption,'formDesign.addRadioOption')
  const arrangeFields=button('排列字段',()=>{if(!objectDesignUnavailable())formCreatePanel?.open('arrange')});sourceCommand(arrangeFields,'formDesign.alignFields')
  commandGroup = ribbon.group('annotate', 'AI Review')
  readAIButton('AI 总结审阅', 'annotate.aiReview.summary', 'reviewSummary')
  const processNotes = button('AI 处理批注', () => pdfReview?.open(), false, 'sparkles')
  sourceCommand(processNotes, 'annotate.aiReview.processNotes')
  processNotes.disabled = response.pdfReviewAIEnabled !== true
  if (processNotes.disabled) processNotes.title = 'PDF AI 批注处理需要开启 AI 与正文编辑权限'
  commandGroup = ribbon.group('annotate', 'Markup')
  const select = button('选择文字', () => setMode('select'), false)
  for (const [type, label] of [['highlight', '高亮'], ['underline', '下划线'], ['squiggly', '波浪线'], ['strikeout', '删除线']] as const) selectionMarkupButton(type, label, `annotate.markup.${type}`)
  commandGroup.append(createMarkupPalette())
  const note = button('文字批注', () => setMode('note'), true, 'note')
  sourceCommand(note, 'annotate.drawTools.note')
  commandGroup = ribbon.group('annotate', 'Draw Tools')
  const annotateDrawGroup = commandGroup
  button('待保存绘图', () => { pendingDrawingsPanel.hidden = !pendingDrawingsPanel.hidden; if (pendingDrawingsPanel.hidden) pendingDrawingDialog?.close(); renderPendingDrawings() }, false)
  button('已保存绘图', () => { drawingsPanel.hidden = !drawingsPanel.hidden; renderSavedDrawings() }, false)
  // 固定源 DRAW_TOOLS 顺序：ink、measure、rect、ellipse、arrow、polygon、caret；颜色取标注调色板。
  for (const [shape, label, id] of [['ink', '手绘', 'ink'], ['measure', '测量', 'measure'], ['rect', '矩形', 'rectangle'], ['ellipse', '椭圆', 'ellipse'], ['arrow', '箭头', 'arrow'], ['polygon', '多边形', 'polygon'], ['caret', '插入符号', 'caret']] as const) {
    const tool = button(label, () => {
      // 固定源：再次点击已激活的测量工具 = 重新标定，下一条线作为参考线。
      if (shape === 'measure' && mode === 'draw' && drawShape === 'measure') { measureRecalibrate = true; status.textContent = '重新标定：请画一条已知实际长度的参考线'; return }
      if (shape === 'measure' && !measureScale) status.textContent = '测量：先画一条已知实际长度的参考线完成标定'
      drawShape = shape; setMode(mode === 'draw' && drawShape === shape && tool.getAttribute('aria-pressed') === 'true' ? 'select' : 'draw') }, true)
    sourceCommand(tool, `annotate.drawTools.${id}`); tool.dataset.pdfDrawShape = shape
    tool.title = shape === 'measure' ? '测量：拖出测量线，首次（或再次点击本按钮）会以该线标定比例；比例仅在本次会话有效，保存后写入带长度标签的 PDF 线批注' : shape === 'polygon' ? '多边形：逐个点击顶点，双击或按 Enter 完成，Esc 取消；保存后写入 PDF 批注' : shape === 'caret' ? '插入符号：在页面上点击放置；保存后写入 PDF 批注' : `${label}：在页面上拖动绘制，颜色取绘图颜色；保存后写入 PDF 批注`
    drawButtons.set(shape, tool)
  }
  const drawColorSelect = documentElement('select', 'pdf-draw-color')
  drawColorSelect.setAttribute('aria-label', '绘图颜色'); sourceCommand(drawColorSelect, 'annotate.drawTools.color')
  for (const item of PDF_DRAW_COLORS) { const option = documentElement('option'); option.value = item.name; option.textContent = item.label; drawColorSelect.append(option) }
  drawColorSelect.addEventListener('change', () => { drawColor = [...(PDF_DRAW_COLORS.find(item => item.name === drawColorSelect.value) ?? PDF_DRAW_COLORS[0]!).rgb] })
  commandGroup.append(drawColorSelect)
  commandGroup.append(note)
  // 固定源 Redact / Clear redaction / Apply redaction：拖出区域标记涂黑；保存新修订时由 PDFium 永久移除区域内文字、图像与路径并黑块覆盖。
  // 固定源先另存副本再涂黑；原生编辑每次保存都是新修订，来源修订保持不变。
  const redactTool = button('涂黑', () => setMode(mode === 'redact' ? 'select' : 'redact'), true)
  sourceCommand(redactTool, 'annotate.drawTools.redact'); redactTool.dataset.pdfRedactTool = ''
  redactTool.title = '涂黑：在页面上拖出要永久移除的区域；保存时写入新修订，区域内文字、图像与路径被删除并以黑块覆盖'
  const redactionCount = () => draft.operations.filter(op => op.kind === 'redact').length
  const clearRedaction = button('清除涂黑', () => {
    const count = redactionCount()
    if (!count) { status.textContent = '当前没有待应用的涂黑标记'; return }
    const operations = draft.operations.filter(op => op.kind !== 'redact')
    pdfPageState(model.pages, operations); draft.setOperations(operations)
    void refresh().then(() => { status.textContent = `已清除 ${count} 处待应用的涂黑标记` }).catch(showError)
  }, true)
  sourceCommand(clearRedaction, 'annotate.drawTools.clearRedaction')
  const applyRedaction = button('应用涂黑', () => {
    const count = redactionCount()
    if (!count) { status.textContent = '请先用“涂黑”工具标记要移除的区域'; return }
    if (shell.save.disabled) { status.textContent = `${count} 处涂黑待保存；当前不能保存：${shell.save.title || '请稍后重试'}`; return }
    setMode('select'); status.textContent = `正在保存新修订并永久应用 ${count} 处涂黑…`; shell.save.click()
  }, true)
  sourceCommand(applyRedaction, 'annotate.drawTools.applyRedaction')
  applyRedaction.title = '应用涂黑：保存新修订并永久移除标记区域内的内容（来源修订不变）'
  annotateDrawGroup.append(redactTool, clearRedaction, applyRedaction)
  // 固定源 SignatureDialog：手写（矢量笔迹）或键入（按所选字体栅格化为图像），再在页面上拖出放置区域。
  commandGroup = ribbon.group('annotate', 'Signature & Protection')
  const signButton = button('签名', () => openSignature(), true)
  sourceCommand(signButton, 'annotate.signature.sign'); signButton.dataset.pdfDrawShape = 'signature'
  signButton.title = '签名：手写或键入后在页面上拖出放置区域；这是可视签名，不是证书数字签名'
  drawButtons.set('signature' as PdfDrawingShape, signButton)
  const SIGN_FONTS = [
    { id: 'script', family: `"Snell Roundhand", "Segoe Script", "Brush Script MT", cursive`, italic: true },
    { id: 'xingkai', family: `"Xingkai SC", "STXingkai", "KaiTi", "Kaiti SC", cursive` },
    { id: 'kaiti', family: `"Kaiti SC", "STKaiti", "KaiTi", "DFKai-SB", serif` },
    { id: 'songti', family: `"Songti SC", "SimSun", "Times New Roman", serif` },
  ]
  const SIGN_PAD = { width: 480, height: 160 }, SIGN_COLOR: [number, number, number] = [...PDF_DRAW_COLORS[4]!.rgb]
  let pendingSignature: { paths: number[][] } | undefined
  const signDialog = documentElement('dialog', 'pdf-sign-dialog'); signDialog.setAttribute('aria-label', '签名')
  const signTitle = documentElement('h3'); signTitle.textContent = '签名'
  const signTabs = documentElement('div', 'pdf-sign-tabs')
  const drawTab = documentElement('button'); drawTab.type = 'button'; drawTab.textContent = '手写'
  const typeTab = documentElement('button'); typeTab.type = 'button'; typeTab.textContent = '键入'
  signTabs.append(drawTab, typeTab)
  const pad = documentElement('canvas', 'pdf-sign-pad'); pad.width = SIGN_PAD.width; pad.height = SIGN_PAD.height; pad.setAttribute('aria-label', '手写签名区域')
  const padClear = documentElement('button'); padClear.type = 'button'; padClear.textContent = '清除笔迹'
  const typeRow = documentElement('div', 'pdf-sign-type')
  const typeText = documentElement('input'); typeText.type = 'text'; typeText.maxLength = 60; typeText.setAttribute('aria-label', '键入签名'); typeText.placeholder = '输入姓名'
  const typeFont = documentElement('select'); typeFont.setAttribute('aria-label', '签名字体')
  for (const [index, font] of SIGN_FONTS.entries()) typeFont.add(new Option(['手写体', '行楷', '楷体', '宋体'][index]!, font.id))
  typeRow.append(typeText, typeFont)
  const signError = documentElement('p', 'pdf-crop-error'); signError.setAttribute('role', 'alert')
  const signCancel = documentElement('button'); signCancel.type = 'button'; signCancel.textContent = '取消'
  const signApply = documentElement('button'); signApply.type = 'button'; signApply.textContent = '确定'
  const signActions = documentElement('div', 'pdf-link-actions'); signActions.append(signCancel, signApply)
  signDialog.append(signTitle, signTabs, pad, padClear, typeRow, signError, signActions); root.append(signDialog)
  let signMode: 'draw' | 'type' = 'draw'
  let padPaths: number[][] = [], padStroke: number[] | undefined
  const redrawPad = () => {
    const context = pad.getContext('2d'); if (!context) return
    context.clearRect(0, 0, pad.width, pad.height); context.strokeStyle = 'rgb(38,38,38)'; context.lineWidth = 2.4; context.lineCap = 'round'; context.lineJoin = 'round'
    for (const path of [...padPaths, ...(padStroke ? [padStroke] : [])]) { context.beginPath(); for (let index = 0; index < path.length; index += 2) context[index ? 'lineTo' : 'moveTo'](path[index]!, path[index + 1]!); context.stroke() }
  }
  const setSignMode = (next: 'draw' | 'type') => { signMode = next; drawTab.setAttribute('aria-pressed', String(next === 'draw')); typeTab.setAttribute('aria-pressed', String(next === 'type')); pad.hidden = padClear.hidden = next !== 'draw'; typeRow.hidden = next !== 'type' }
  drawTab.addEventListener('click', () => setSignMode('draw')); typeTab.addEventListener('click', () => setSignMode('type'))
  const padPoint = (event: PointerEvent) => { const bounds = pad.getBoundingClientRect(); return [Math.round((event.clientX - bounds.left) * pad.width / bounds.width * 10) / 10, Math.round((event.clientY - bounds.top) * pad.height / bounds.height * 10) / 10] }
  pad.addEventListener('pointerdown', event => { event.preventDefault(); pad.setPointerCapture?.(event.pointerId); padStroke = padPoint(event) })
  pad.addEventListener('pointermove', event => { if (padStroke && padStroke.length < 4000) { padStroke.push(...padPoint(event)); redrawPad() } })
  pad.addEventListener('pointerup', () => { if (padStroke && padStroke.length >= 4 && padPaths.length < 20) padPaths.push(padStroke); padStroke = undefined; redrawPad() })
  padClear.addEventListener('click', () => { padPaths = []; redrawPad() })
  function openSignature() {
    if (!document || locked || previewing || previewDocument || !response.editingEnabled || draft.closed) return
    padPaths = []; padStroke = undefined; typeText.value = ''; signError.textContent = ''; setSignMode('draw'); redrawPad(); signDialog.showModal()
  }
  signCancel.addEventListener('click', () => signDialog.close())
  signApply.addEventListener('click', () => {
    try {
      if (signMode === 'draw') {
        if (!padPaths.length) throw new Error('请先在签名区域书写')
        pendingSignature = { paths: padPaths.map(path => [...path]) }; pendingImage = ''
      } else {
        const text = typeText.value.trim()
        if (!text) throw new Error('请输入签名文字')
        // 与固定源 textToImage 相同：按字体实测字形边界紧裁透明画布。
        const font = SIGN_FONTS.find(item => item.id === typeFont.value) ?? SIGN_FONTS[0]!
        const canvas = documentElement('canvas'), context = canvas.getContext('2d')
        if (!context) throw new Error('浏览器不支持画布，无法生成键入签名')
        const css = `${font.italic ? 'italic ' : ''}200px ${font.family}`
        context.font = css
        const metrics = context.measureText(text), padding = 16
        const left = Math.ceil(metrics.actualBoundingBoxLeft) + padding, ascent = Math.ceil(metrics.actualBoundingBoxAscent) + padding
        canvas.width = left + Math.ceil(metrics.actualBoundingBoxRight) + padding; canvas.height = ascent + Math.ceil(metrics.actualBoundingBoxDescent) + padding
        context.font = css; context.fillStyle = 'rgb(38,38,38)'; context.fillText(text, left, ascent)
        const encoded = canvas.toDataURL('image/png').split(',')[1] ?? ''
        if (!encoded.startsWith('iVBORw0KGgo')) throw new Error('签名图像生成失败')
        pendingImage = encoded; pendingSignature = undefined
      }
      signDialog.close(); drawShape = pendingSignature ? ('signature' as PdfDrawingShape) : 'image'; setMode('draw')
      status.textContent = '请在页面上拖出签名放置区域'
    } catch (error) { signError.textContent = error instanceof Error ? error.message : String(error) }
  })
  unavailableSourceGroup('annotate', 'Signature & Protection', [
    { id: 'annotate.signature.certificateSign', label: '证书签名', reason: '证书签名需要独立密钥托管与签名服务，浏览器端不持有私钥' },
    { id: 'annotate.signature.signaturePanel', label: '数字签名面板', reason: '数字签名列表与验证状态尚未接入原生 PDF 服务' },
  ])
  const cropDialog = documentElement('dialog', 'pdf-crop-dialog')
  cropDialog.setAttribute('aria-label', '裁切当前页面')
  const cropTitle = documentElement('h3'); cropTitle.textContent = '裁切当前页面'
  const cropHelp = documentElement('p'); cropHelp.textContent = '拖动八个控制柄或保留范围，也可按当前显示方向输入四边裁去的百分比。预览显示当前裁切和旋转，其他未保存修改请以“校验当前修改”为准。裁切只隐藏边缘内容，不能用于删除敏感信息。'
  const cropError = documentElement('p', 'pdf-crop-error'); cropError.setAttribute('role', 'alert')
  const cropCanvasHost = documentElement('div')
  const cropCanvasStatus = documentElement('p'); cropCanvasStatus.setAttribute('role', 'status')
  let cropCanvas: ReturnType<typeof mountPdfCropCanvas> | undefined, cropRenderTask: RenderTask | undefined
  let cropCanvasGeneration = 0, cropSnapshot = ''
  function clearCropCanvas() {
    cropCanvasGeneration++; cropRenderTask?.cancel(); cropRenderTask = undefined
    cropCanvas?.dispose(); cropCanvas = undefined; cropCanvasHost.replaceChildren(); cropCanvasStatus.textContent = ''
  }
  cropDialog.addEventListener('close', clearCropCanvas)
  cropDialog.addEventListener('cancel', clearCropCanvas)
  const cropFields = documentElement('fieldset')
  const cropInputs = ['左侧裁去 (%)', '顶部裁去 (%)', '右侧裁去 (%)', '底部裁去 (%)'].map(label => {
    const row = documentElement('label'); row.textContent = label
    const input = documentElement('input'); input.type = 'number'; input.min = '0'; input.max = '99.99'; input.step = 'any'; input.value = '0'; input.setAttribute('aria-label', label)
    row.append(input); cropFields.append(row); return input
  })
  const cropAllLabel = documentElement('label')
  const cropAll = documentElement('input'); cropAll.type = 'checkbox'; cropAll.setAttribute('aria-label', '裁切全部保留页')
  const cropAllText = documentElement('span')
  cropAllLabel.append(cropAll, cropAllText); cropFields.append(cropAllLabel)
  cropAll.addEventListener('change', () => {
    cropTitle.textContent = cropAll.checked ? '裁切全部保留页' : '裁切当前页面'
    cropDialog.setAttribute('aria-label', cropTitle.textContent)
  })
  let cropApplying = false
  const cropApply = documentElement('button'); cropApply.type = 'button'; cropApply.textContent = '应用裁切'
  const cropCancel = documentElement('button'); cropCancel.type = 'button'; cropCancel.textContent = '取消'
  cropFields.append(cropApply, cropCancel); cropDialog.append(cropTitle, cropHelp, cropCanvasStatus, cropCanvasHost, cropError, cropFields); root.append(cropDialog)
  let cropPageId = ''
  for (const input of cropInputs) input.addEventListener('input', () => {
    if (!cropCanvas) return
    try {
      if (cropInputs.some(field => !field.value.trim())) throw new Error('请填写全部四个裁切边距')
      cropCanvas.setMargins(cropInputs.map(field => Number(field.value))); cropError.textContent = ''
    } catch (error) { cropError.textContent = error instanceof Error ? error.message : String(error) }
  })
  cropCancel.addEventListener('click', () => cropDialog.close())
  cropApply.addEventListener('click', () => { void applyCrop().catch(error => { cropError.textContent = error instanceof Error ? error.message : String(error); showError(error) }) })
  async function openCrop() {
    if (cropDialog.open || draft.operations.some(op => op.kind === 'setPageSize') || cropApplying || !document || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed || model.capabilities?.cropPage !== true) return
    const page = state().find(item => item.pageId === activeId)
    if (!page) return
    clearCropCanvas()
    cropSnapshot = JSON.stringify(draft.operations)
    const canvasGeneration = cropCanvasGeneration, source = document
    const current = () => !disposed && canvasGeneration === cropCanvasGeneration && source === document && cropDialog.open && !cropApplying && !locked && !previewing && !printing && !previewDocument && response.editingEnabled && !draft.closed && page.pageId === activeId && cropSnapshot === JSON.stringify(draft.operations)
    const checkCurrent = () => {
      if (current()) return true
      if (!disposed && canvasGeneration === cropCanvasGeneration && cropDialog.open) {
        cropCanvasStatus.textContent = ''; cropError.textContent = '页面或草稿已变化，请关闭并重新选择裁切范围'
      }
      return false
    }
    cropError.textContent = ''; cropAll.checked = false; cropTitle.textContent = '裁切当前页面'; cropDialog.setAttribute('aria-label', cropTitle.textContent); cropAllText.textContent = `裁切全部保留页（${state().length} 页，各按当前显示方向和可见范围）`; cropPageId = page.pageId; cropInputs.forEach(input => { input.value = '0' })
    cropDialog.showModal()
    cropCanvasStatus.textContent = '正在读取当前页面裁切预览…'
    try {
      const original = await sourcePage(page.index)
      if (!checkCurrent()) return
      const unit = pdfPageViewport(original, page, 1)
      const view = pdfPageViewport(original, page, Math.min(520 / unit.width, 520 / unit.height))
      const canvas = documentElement('canvas'); canvas.width = Math.ceil(view.width); canvas.height = Math.ceil(view.height)
      const context = canvas.getContext('2d')
      if (!context) throw new Error('当前浏览器无法绘制裁切预览，仍可输入裁切边距')
      const task = original.render({ canvas, canvasContext: context, viewport: view, annotationMode: AnnotationMode.ENABLE })
      cropRenderTask = task
      await task.promise
      if (cropRenderTask === task) cropRenderTask = undefined
      if (!checkCurrent()) return
      cropCanvas = mountPdfCropCanvas({ host: cropCanvasHost, canvas, enabled: current, change: margins => {
        margins.forEach((value, index) => { cropInputs[index]!.value = String(value) }); cropError.textContent = ''
      } })
      cropCanvasStatus.textContent = ''
      cropCanvas.setMargins(cropInputs.map(input => Number(input.value)))
    } catch (error) {
      if (checkCurrent()) { cropCanvasStatus.textContent = ''; cropError.textContent = error instanceof Error ? error.message : String(error) }
    }
  }
  async function applyCrop() {
    if (cropApplying || !cropDialog.open || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed || model.capabilities?.cropPage !== true) return
    const page = state().find(item => item.pageId === cropPageId)
    if (!page) throw new Error('裁切目标页面已变化，请重新选择')
    if (cropSnapshot !== JSON.stringify(draft.operations)) throw new Error('草稿已变化，请关闭并重新选择裁切范围')
    const key = JSON.stringify(draft.operations), operations = structuredClone(draft.operations)
    if (cropInputs.some(input => input.value.trim() === '')) throw new Error('请填写全部四个裁切边距')
    const margins = cropInputs.map(input => Number(input.value)), allPages = cropAll.checked
    cropApplying = true; updateControls()
    try {
      let next: NativeOperation[]
      if (allPages) next = await cropAllPdfPages(model.pages, operations, margins, async target => pdfPageViewport(await sourcePage(target.index), target, 1))
      else {
        const original = await sourcePage(page.index)
        const rect = pdfCropFromMargins(pdfPageViewport(original, page, 1), page.cropBox, margins)
        next = cropPdfPage(model.pages, operations, page.pageId, rect)
      }
      if (disposed || !cropDialog.open || locked || previewing || printing || previewDocument || draft.closed || key !== JSON.stringify(draft.operations)) throw new Error('草稿已变化或裁切已取消，请重新选择裁切范围')
      pdfPageState(model.pages,next); draft.setOperations(next)
      cropDialog.close(); await refresh()
    } finally { cropApplying = false; updateControls() }
  }
  const sizeDialog = documentElement('dialog', 'pdf-crop-dialog pdf-size-dialog'); sizeDialog.setAttribute('aria-label', '页面尺寸')
  const sizeTitle = documentElement('h3'); sizeTitle.textContent = '全部保留页的页面尺寸'
  const sizeHint = documentElement('p'); sizeHint.textContent = '按原始整页等比缩放内容与批注并居中，保留显示方向；尺寸改变的页面重置裁切范围，尺寸已匹配的页面保持原样。保存会创建新修订；先查看实际写回预览。'
  const sizeError = documentElement('p'); sizeError.setAttribute('role', 'alert')
  const sizeOptions = documentElement('fieldset'); sizeOptions.style.border = '0'
  for (const paper of PDF_PAPER_SIZES) {
    const choice = documentElement('button'); choice.type = 'button'; choice.textContent = paper.label
    choice.addEventListener('click', () => { void applyPageSize(paper.label).catch(error => { sizeError.textContent = error instanceof Error ? error.message : String(error); showError(error) }) })
    sizeOptions.append(choice)
  }
  let sizeApplying = false
  const sizeCancel = documentElement('button'); sizeCancel.type = 'button'; sizeCancel.textContent = '取消'; sizeCancel.addEventListener('click', () => sizeDialog.close())
  sizeOptions.append(sizeCancel); sizeDialog.append(sizeTitle, sizeHint, sizeError, sizeOptions); root.append(sizeDialog)
  function pageSizeUnavailable() {
    if (model.capabilities?.pageSize !== true) return model.capabilities?.pageSizeReason ?? '当前 PDF 引擎未确认页面尺寸写回能力'
    if (draft.operations.some(op => ['cropPage', 'replaceText', 'replyNote', 'replyPendingNote'].includes(op.kind))) return '请先保存裁切、原位改字或回复并重开，再变更页面尺寸'
    return null
  }
  async function openPageSize() {
    if (sizeApplying || !document || locked || previewing || printing || previewDocument || draft.closed || !response.editingEnabled || pageSizeUnavailable()) return
    sizeError.textContent = ''; sizeDialog.showModal()
  }
  async function applyPageSize(preset: string) {
    if (sizeApplying || !sizeDialog.open || locked || previewing || printing || previewDocument || draft.closed || !response.editingEnabled || pageSizeUnavailable()) return
    if (hasUnstagedText()) throw new Error('请先完成当前文字编辑')
    sizeApplying = true; updateControls()
    try {
      const next=setPdfPageSize(draft.operations,preset);pdfPageState(model.pages,next);draft.setOperations(next)
      sizeDialog.close(); await refresh(); await previewDraft()
    } finally { sizeApplying = false; updateControls() }
  }
  // 固定源 MergePagesDialog / SplitPagesDialog：整份文档重排版，单独保存为新修订（来源修订不变），先查看实际预览。
  const layoutDialog = documentElement('dialog', 'pdf-layout-dialog')
  const layoutTitle = documentElement('h3'), layoutHint = documentElement('p', 'pdf-measure-hint')
  const layoutBody = documentElement('div', 'pdf-layout-body')
  const layoutError = documentElement('p', 'pdf-crop-error'); layoutError.setAttribute('role', 'alert')
  const layoutActions = documentElement('div', 'pdf-link-actions')
  layoutDialog.append(layoutTitle, layoutHint, layoutBody, layoutError, layoutActions); root.append(layoutDialog)
  const layoutCancel = documentElement('button'); layoutCancel.type = 'button'; layoutCancel.textContent = '取消'; layoutCancel.addEventListener('click', () => layoutDialog.close())
  function pageLayoutUnavailable(kind?: string) {
    if (!document || locked || previewing || printing || !!previewDocument || draft.closed || !response.editingEnabled) return '请先打开 PDF 并退出预览'
    if (draft.operations.length) return PDF_PAGE_LAYOUT_ALONE_REASON
    if (kind === 'splitPages' && model.formFields?.length) return '含表单字段的 PDF 暂不支持拆分页面；请先保留原件并展平表单'
    if (model.formFields?.some(field => field.kind === 'signature')) return '含有签名字段的 PDF 不能合并或拆分页面（输出不保留签名）'
    return null
  }
  async function applyPageLayout(operation: NativeOperation) {
    const reason = pageLayoutUnavailable(operation.kind)
    if (reason) throw new Error(reason)
    if (hasUnstagedText()) throw new Error('请先完成当前文字编辑')
    pdfPageState(model.pages, [operation]); draft.setOperations([operation])
    layoutDialog.close(); await refresh(); await previewDraft()
  }
  function openLayoutDialog(kind: 'mergePages' | 'splitPages') {
    const reason = pageLayoutUnavailable(kind)
    if (reason) { status.textContent = reason; return }
    layoutError.textContent = ''; layoutBody.replaceChildren(); layoutActions.replaceChildren(layoutCancel)
    const total = state().length
    layoutDialog.setAttribute('aria-label', kind === 'mergePages' ? '合并页面' : '拆分页面')
    layoutTitle.textContent = kind === 'mergePages' ? '合并页面' : '拆分页面'
    const fail = (error: unknown) => { layoutError.textContent = error instanceof Error ? error.message : String(error) }
    if (kind === 'mergePages') {
      layoutHint.textContent = `把每 N 个连续页面缩放排到一张纸上（共 ${total} 页）。纸张取第 1 页尺寸，2 合 1 时横向；批注、绘图与表单外观转为静态内容；交互、书签与附件不保留。保存为新修订，来源修订不变。`
      const countLabel = documentElement('label'); countLabel.textContent = '每张页数（2–16）'
      const count = documentElement('input'); count.inputMode = 'numeric'; count.value = '2'; count.setAttribute('aria-label', '每张页数'); countLabel.append(count)
      const directionLabel = documentElement('label'); directionLabel.textContent = '排列顺序'
      const direction = documentElement('select'); direction.setAttribute('aria-label', '排列顺序')
      for (const [value, label] of [['vertical', '纵向（先上下，再左右）'], ['horizontal', '横向（先左右，再上下）']] as const) { const option = documentElement('option'); option.value = value; option.textContent = label; direction.append(option) }
      directionLabel.append(direction)
      const separatorLabel = documentElement('label', 'pdf-layout-check'); const separator = documentElement('input'); separator.type = 'checkbox'; separator.setAttribute('aria-label', '绘制分隔线')
      separatorLabel.append(separator, '绘制分隔线')
      layoutBody.append(countLabel, directionLabel, separatorLabel)
      const apply = documentElement('button'); apply.type = 'button'; apply.textContent = '确定'
      apply.addEventListener('click', () => {
        try {
          const perSheet = Number(count.value.trim())
          if (!/^\d+$/.test(count.value.trim()) || perSheet < 2 || perSheet > 16) throw new Error('每张页数须为 2–16 的整数')
          void applyPageLayout(pdfMergePagesOperation(perSheet, direction.value as 'horizontal' | 'vertical', separator.checked)).catch(error => { fail(error); showError(error) })
        } catch (error) { fail(error) }
      })
      layoutActions.append(apply)
    } else {
      layoutHint.textContent = `把每一页按显示方向均分为 2、4 或 9 页（共 ${total} 页），按可见范围分割，仍保留底层页面内容；含表单字段的来源暂不支持。保存为新修订，来源修订不变。`
      for (const perPage of [2, 4, 9]) {
        const choice = documentElement('button'); choice.type = 'button'; choice.textContent = `拆成 ${perPage} 页`; choice.dataset.pdfSplitPages = String(perPage)
        choice.addEventListener('click', () => { void applyPageLayout(pdfSplitPagesOperation(perPage)).catch(error => { fail(error); showError(error) }) })
        layoutBody.append(choice)
      }
    }
    layoutDialog.showModal()
  }
  function displayViewport(original: PDFPageProxy, page: PdfPageIdentity, scale: number) {
    return previewDocument ? original.getViewport({ scale, rotation: page.rotation }) : pdfPageViewport(original, page, scale)
  }
  const pageButtons = new Map<string, HTMLButtonElement>()
  function extractionUnavailable() {
    if (disposed || !document || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed) return '请先打开可编辑的 PDF 并退出预览或保存'
    if (staticText?.incompleteReason()) return staticText.incompleteReason()
    if(existingImagePanel?.incompleteReason())return existingImagePanel.incompleteReason()
    if (draft.operations.length || hasUnstagedText()) return '请先保存或撤销当前修改，再从已保存版本提取页面'
    return null
  }
  const extraction = bindPdfExtractDialog({ root, sourceSha256: context.sourceFile.sha256,
    pageCount: () => model.pages.length, currentPage: () => (model.pages.find(page => page.pageId === activeId)?.index ?? 0) + 1,
    unavailable: extractionUnavailable, extract: payload => api.extractPages(payload) })
  const externalPages = bindPdfExternalPagesDialog({root,sourceSha256:context.sourceFile.sha256,
    pageCount:()=>model.pages.length,currentPage:()=>(model.pages.find(page=>page.pageId===activeId)?.index??0)+1,
    unavailable:extractionUnavailable,submit:payload=>api.externalPages(payload)})
  const protectionUnavailable = () => extractionUnavailable() ?? (model.capabilities?.protectPdf === true ? null : '当前仅支持未加密且不含表单或签名保护结构的 PDF')
  const protection = bindPdfProtectionDialog({root,sourceSha256:context.sourceFile.sha256,unavailable:protectionUnavailable,submit:payload=>api.protectPdf(payload)})
  const [{bindPdfImageExportDialog},{bindPdfConvertOfficeDialog},{bindPdfExportTextDialog}]=await Promise.all([
    import('./pdf-image-export'),import('./pdf-convert-office'),import('./pdf-export-text'),
  ])
  const imageExport=bindPdfImageExportDialog({root,sourceSha256:context.sourceFile.sha256,pageCount:()=>model.pages.length,
    currentPage:()=>(model.pages.find(page=>page.pageId===activeId)?.index??0)+1,unavailable:extractionUnavailable,exportImages:payload=>api.exportImages(payload)})
  const officeConversion=bindPdfConvertOfficeDialog({root,sourceSha256:context.sourceFile.sha256,unavailable:extractionUnavailable,submit:payload=>api.convertOffice(payload)})
  const textExport=bindPdfExportTextDialog({root,sourceSha256:context.sourceFile.sha256,unavailable:extractionUnavailable,convertOffice:payload=>api.convertOffice(payload)})
  commandGroup=homeConvertGroup
  const convertPptx=button('转换为演示文稿',()=>officeConversion.open());sourceCommand(convertPptx,'home.convert.toPowerPoint')
  const exportTextButtons:HTMLButtonElement[]=[]
  for(const[format,label,id]of [['markdown','转换为 Markdown','home.convert.toMarkdown'],['html','转换为 HTML','home.convert.toHtml']]as const){const control=button(label,()=>textExport.open(format));sourceCommand(control,id);exportTextButtons.push(control)}
  const exportPng=button('导出图像 PNG',()=>imageExport.open('png'));sourceCommand(exportPng,'home.convert.exportImagesPng')
  const exportJpg=button('导出图像 JPG',()=>imageExport.open('jpeg'));sourceCommand(exportJpg,'home.convert.exportImagesJpg')
  commandGroup = ribbon.group('annotate','Signature & Protection')
  const protectButton = button('保护 PDF', () => protection.open())
  sourceCommand(protectButton,'annotate.protection.protect')
  const pageActions: Record<string, () => void | Promise<void>> = {
    'genoffice.pdf.page.insertPdf':()=>externalPages.open('insert'),
    'genoffice.pdf.page.replace':()=>externalPages.open('replace'),
    'genoffice.pdf.page.extract': () => extraction.open(),
    'genoffice.pdf.page.crop': openCrop,
    'genoffice.pdf.page.size': openPageSize,
    'genoffice.pdf.page.rotateLeft': () => append({ kind: 'rotatePage', pageId: activeId, delta: 270 }),
    'genoffice.pdf.page.rotateRight': () => append({ kind: 'rotatePage', pageId: activeId, delta: 90 }),
    'genoffice.pdf.page.rotateAll': async () => {
      if (disposed || !document || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed) return
      draft.setOperations(rotateAllPdfPages(model.pages, draft.operations)); await refresh()
    },
    'genoffice.pdf.page.delete': async () => {
      if (!activeId) return
      draft.setOperations(deletePdfPage(model.pages, draft.operations, activeId)); await refresh()
    },
    'genoffice.pdf.page.insertBlank': async () => {
      if (disposed || !document || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed) return
      if (hasUnstagedText()) throw new Error('请先完成当前文字编辑')
      const before = new Set(state().map(page => page.pageId))
      draft.setOperations(insertBlankPdfPage(model.pages, draft.operations, activeId || null))
      activeId = state().find(page => !before.has(page.pageId))?.pageId ?? activeId
      await refresh()
    },
    'genoffice.pdf.page.mergePages': () => openLayoutDialog('mergePages'),
    'genoffice.pdf.page.splitPages': () => openLayoutDialog('splitPages'),
    'genoffice.pdf.page.reverse': async () => {
      draft.setOperations(reversePdfPages(model.pages, draft.operations)); await refresh()
    },
  }
  for (const group of PDF_PAGE_RIBBON_GROUPS) {
    commandGroup = ribbon.group('page', group.title)
    for (const item of group.commands) {
      if (!item.enabled) {
        unavailableSourceGroup('page', group.title, [{ id: item.id.replace('genoffice.pdf.', ''), label: item.label, reason: item.reason! }], commandGroup)
        continue
      }
      const icon = item.id.endsWith('rotateLeft') ? 'rotateLeft' : item.id.endsWith('rotateRight') ? 'rotateRight' : undefined
      const action = button(item.label, pageActions[item.id]!, true, icon)
      sourceCommand(action, item.id.replace('genoffice.pdf.', ''))
      pageButtons.set(item.id, action)
    }
  }
  commandGroup = ribbon.group('page', 'Local Draft Controls')
  button('页面前移', async () => { draft.setOperations(movePdfPage(model.pages, draft.operations, activeId, -1)); await refresh() })
  button('页面后移', async () => { draft.setOperations(movePdfPage(model.pages, draft.operations, activeId, 1)); await refresh() })
  commandGroup = ribbon.group('edit', 'Content')
  const textEditButton = textEnabled ? button('原位改字', () => { setMode('text'); renderTextPanel(true) }) : undefined
  const previewButton = button('校验当前修改', () => previewDraft(), false)
  const backToSource = button('返回原稿编辑', async () => {
    if (locked || previewing) return
    await leavePreview(); review.reset(); reviewPanel.hidden = true; confirmPreview.checked = false
    await rebuildTextIndex(); await refresh()
  }, false)
  backToSource.hidden = true
  commandGroup = ribbon.group('edit', '图像、链接与水印')
  // 固定源 ImageDialogs ▸ 插入图像：选择 PNG/JPEG，浏览器转为 PNG 后在页面上拖出位置，保存为 Stamp 批注。
  let pendingImage = ''
  const imageFile = documentElement('input'); imageFile.type = 'file'; imageFile.accept = 'image/png,image/jpeg'; imageFile.hidden = true; imageFile.setAttribute('aria-label', '选择要插入的图像')
  root.append(imageFile)
  const insertImage = button('插入图像', () => { if (!document || locked || previewing || previewDocument || !response.editingEnabled || draft.closed) return; imageFile.value = ''; imageFile.click() }, true)
  sourceCommand(insertImage, 'edit.objects.insertImage'); insertImage.dataset.pdfDrawShape = 'image'
  insertImage.title = '插入图像：选择 PNG 或 JPEG，再在页面上拖出放置区域；保存后写入 PDF'
  drawButtons.set('image', insertImage)
  imageFile.addEventListener('change', () => { void (async () => {
    const file = imageFile.files?.[0]
    if (!file) return
    if (!['image/png', 'image/jpeg'].includes(file.type) || file.size > 10 * 1024 * 1024) throw new Error('请选择不超过 10MB 的 PNG 或 JPEG 图像')
    const bitmap = await createImageBitmap(file)
    const ratio = Math.min(1, 2000 / Math.max(bitmap.width, bitmap.height))
    const canvas = documentElement('canvas'); canvas.width = Math.max(1, Math.round(bitmap.width * ratio)); canvas.height = Math.max(1, Math.round(bitmap.height * ratio))
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height); bitmap.close()
    const encoded = canvas.toDataURL('image/png').split(',')[1] ?? ''
    if (!encoded.startsWith('iVBORw0KGgo') || encoded.length > 6_000_000) throw new Error('图像转换后过大，请换一张较小的图像')
    pendingImage = encoded; drawShape = 'image'; setMode('draw')
    status.textContent = `已选择图像 ${file.name}（${canvas.width}×${canvas.height}）；请在页面上拖出放置区域`
  })().catch(showError) })
  const editExistingImage=button('编辑图像',()=>existingImagePanel?.open());sourceCommand(editExistingImage,'edit.objects.editImage')
  // 固定源 editLink：在页面上拖出链接区域，再选择外部地址或文档内页码。
  const linkTool = button('编辑链接', () => { drawShape = 'link'; setMode(mode === 'draw' && linkTool.getAttribute('aria-pressed') === 'true' ? 'select' : 'draw') }, true)
  sourceCommand(linkTool, 'edit.objects.editLink'); linkTool.dataset.pdfDrawShape = 'link'
  linkTool.title = '编辑链接：在页面上拖出链接区域，再填写 http/https/mailto 地址或页码；保存后写入 PDF'
  drawButtons.set('link', linkTool)
  // 固定源 Edit ▸ 水印 → StampDialog：水印与页眉页脚/页码一次设置，按当前页序渲染位图。
  const stampButton = button('水印', () => openStamps(), true)
  sourceCommand(stampButton, 'edit.objects.watermark')
  stampButton.title = '水印与页眉页脚：设置后覆盖全部页面，保存时写入页面内容'
  const stampDialog = documentElement('dialog', 'pdf-stamp-dialog')
  stampDialog.setAttribute('aria-label', '水印与页眉页脚')
  const stampForm = documentElement('div', 'pdf-stamp-form')
  const stampField = (label: string, input: HTMLInputElement) => { const row = documentElement('label'); const text = documentElement('span'); text.textContent = label; row.append(text, input); stampForm.append(row); return input }
  const stampInput = (type: string, attrs: Record<string, string> = {}) => { const input = documentElement('input'); input.type = type; for (const [key, value] of Object.entries(attrs)) input.setAttribute(key, value); return input }
  const stampHeading = (text: string) => { const heading = documentElement('h4'); heading.textContent = text; stampForm.append(heading) }
  const stampTitle = documentElement('h3'); stampTitle.textContent = '水印与页眉页脚'
  stampHeading('水印')
  const wmText = stampField('水印文字', stampInput('text', { maxlength: '200', placeholder: '例如：机密' }))
  const wmAngle = stampField('角度（°）', stampInput('range', { min: '-90', max: '90' }))
  const wmOpacity = stampField('不透明度（%）', stampInput('range', { min: '5', max: '100' }))
  const wmSize = stampField('字号（页宽 %）', stampInput('range', { min: '4', max: '22' }))
  const wmColor = stampField('颜色', stampInput('color'))
  stampHeading('页眉页脚')
  const hfInputs = Object.fromEntries((['headerLeft', 'headerCenter', 'headerRight', 'footerLeft', 'footerCenter', 'footerRight'] as const).map((key, index) => [key, stampField(['页眉左', '页眉中', '页眉右', '页脚左', '页脚中', '页脚右'][index]!, stampInput('text', { maxlength: '200' }))])) as Record<'headerLeft' | 'headerCenter' | 'headerRight' | 'footerLeft' | 'footerCenter' | 'footerRight', HTMLInputElement>
  const hfPageNumber = stampField('页脚居中显示页码（第 n / 共 N 页）', stampInput('checkbox'))
  const hfStartAt = stampField('起始页码', stampInput('number', { min: '1', max: '100000' }))
  const stampHint = documentElement('p'); stampHint.textContent = '页眉页脚可用 {page} 与 {total} 表示页码与总页数。设置后在保存或撤销前不能再调整页面顺序、数量、裁切或尺寸。'
  const stampError = documentElement('p', 'pdf-crop-error'); stampError.setAttribute('role', 'alert')
  const stampCancel = documentElement('button'); stampCancel.type = 'button'; stampCancel.textContent = '取消'
  const stampClear = documentElement('button'); stampClear.type = 'button'; stampClear.textContent = '清除水印与页眉页脚'
  const stampApply = documentElement('button'); stampApply.type = 'button'; stampApply.textContent = '确定'
  const stampActions = documentElement('div', 'pdf-link-actions'); stampActions.append(stampCancel, stampClear, stampApply)
  stampDialog.append(stampTitle, stampForm, stampHint, stampError, stampActions); root.append(stampDialog)
  function openStamps() {
    if (!document || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed) return
    const existing = draft.operations.find(op => op.kind === 'setStamps') as { watermark?: typeof DEFAULT_WATERMARK | null; headerFooter?: typeof DEFAULT_HEADER_FOOTER | null } | undefined
    const wm = existing?.watermark ?? DEFAULT_WATERMARK, hf = existing ? existing.headerFooter ?? { ...DEFAULT_HEADER_FOOTER, pageNumber: false } : DEFAULT_HEADER_FOOTER
    wmText.value = existing?.watermark?.text ?? ''; wmAngle.value = String(wm.angle); wmOpacity.value = String(Math.round(wm.opacity * 100)); wmSize.value = String(Math.round(wm.sizeRatio * 100)); wmColor.value = wm.color
    for (const [key, input] of Object.entries(hfInputs)) input.value = hf[key as keyof typeof hfInputs]
    hfPageNumber.checked = hf.pageNumber; hfStartAt.value = String(hf.startAt)
    stampClear.disabled = !existing; stampError.textContent = ''
    stampDialog.showModal(); wmText.focus()
  }
  stampCancel.addEventListener('click', () => stampDialog.close())
  stampClear.addEventListener('click', () => {
    draft.setOperations(draft.operations.filter(op => op.kind !== 'setStamps')); stampDialog.close(); void refresh().catch(showError)
  })
  stampApply.addEventListener('click', () => {
    try {
      const watermark = wmText.value.trim() ? { text: wmText.value.trim(), angle: Number(wmAngle.value), opacity: Number(wmOpacity.value) / 100, color: wmColor.value, sizeRatio: Number(wmSize.value) / 100 } : null
      const headerFooter = { ...DEFAULT_HEADER_FOOTER, ...Object.fromEntries(Object.entries(hfInputs).map(([key, input]) => [key, input.value])), pageNumber: hfPageNumber.checked, startAt: Math.max(1, Math.floor(Number(hfStartAt.value) || 1)) }
      const used = headerFooter.pageNumber || Object.keys(hfInputs).some(key => String(headerFooter[key as keyof typeof hfInputs]).trim())
      if (!watermark && !used) throw new Error('请填写水印文字，或启用页码/页眉页脚')
      const base = draft.operations.filter(op => op.kind !== 'setStamps')
      const operation = buildPdfStampsOperation(pdfPageState(model.pages, base), watermark, used ? headerFooter : null)
      const next = [...base, operation]
      pdfPageState(model.pages, next)
      draft.setOperations(next); stampDialog.close(); void refresh().catch(showError)
    } catch (error) { stampError.textContent = error instanceof Error ? error.message : String(error) }
  })
  const linkDialog = documentElement('dialog', 'pdf-link-dialog')
  linkDialog.setAttribute('aria-label', '添加链接')
  const linkTitle = documentElement('h3'); linkTitle.textContent = '添加链接'
  const linkUrlLabel = documentElement('label'); linkUrlLabel.textContent = '网址（http、https 或 mailto）'
  const linkUrl = documentElement('input'); linkUrl.type = 'url'; linkUrl.placeholder = 'https://…'; linkUrl.setAttribute('aria-label', '链接网址'); linkUrlLabel.append(linkUrl)
  const linkPageLabel = documentElement('label')
  const linkPageText = documentElement('span')
  const linkPage = documentElement('input'); linkPage.inputMode = 'numeric'; linkPage.setAttribute('aria-label', '链接页码'); linkPageLabel.append(linkPageText, linkPage)
  const linkError = documentElement('p', 'pdf-crop-error'); linkError.setAttribute('role', 'alert')
  const linkApply = documentElement('button'); linkApply.type = 'button'; linkApply.textContent = '确定'
  const linkCancel = documentElement('button'); linkCancel.type = 'button'; linkCancel.textContent = '取消'
  const linkActions = documentElement('div', 'pdf-link-actions'); linkActions.append(linkCancel, linkApply)
  linkDialog.append(linkTitle, linkUrlLabel, linkPageLabel, linkError, linkActions); root.append(linkDialog)
  let linkPending: { page: PdfPageIdentity; points: number[][] } | undefined
  // 固定源 MeasureScaleDialog：参考线的实际长度 + 单位（默认 m）；比例只在本次会话有效。
  const measureDialog = documentElement('dialog', 'pdf-measure-dialog')
  measureDialog.setAttribute('aria-label', '标定测量比例')
  const measureTitle = documentElement('h3'); measureTitle.textContent = '标定测量比例'
  const measureHint = documentElement('p', 'pdf-measure-hint')
  const measureValueLabel = documentElement('label'); measureValueLabel.textContent = '参考线实际长度'
  const measureValue = documentElement('input'); measureValue.inputMode = 'decimal'; measureValue.setAttribute('aria-label', '参考线实际长度'); measureValueLabel.append(measureValue)
  const measureUnitLabel = documentElement('label'); measureUnitLabel.textContent = '单位（英文，如 m、cm、mm、in、ft）'
  const measureUnit = documentElement('input'); measureUnit.maxLength = 12; measureUnit.value = 'm'; measureUnit.setAttribute('aria-label', '测量单位'); measureUnitLabel.append(measureUnit)
  const measureError = documentElement('p', 'pdf-crop-error'); measureError.setAttribute('role', 'alert')
  const measureApply = documentElement('button'); measureApply.type = 'button'; measureApply.textContent = '确定'
  const measureCancel = documentElement('button'); measureCancel.type = 'button'; measureCancel.textContent = '取消'
  const measureActions = documentElement('div', 'pdf-link-actions'); measureActions.append(measureCancel, measureApply)
  measureDialog.append(measureTitle, measureHint, measureValueLabel, measureUnitLabel, measureError, measureActions); root.append(measureDialog)
  let measureScale: MeasureScale | undefined, measureRecalibrate = false
  let measurePending: { page: PdfPageIdentity; operation: NativeOperation; snapshot: string; doc: PDFDocumentProxy | undefined; userUnit: number } | undefined
  function commitMeasure(page: PdfPageIdentity, line: NativeOperation, scale: MeasureScale, userUnit: number, after?: () => void) {
    const from = line.from as number[], to = line.to as number[]
    const operation = pdfMeasurementOperation(page.pageId, [from, to], page.cropBox, line.color as [number,number,number], scale, userUnit)
    pdfPageState(model.pages, [...draft.operations, operation])
    void append(operation).then(after).catch(showError)
  }
  // 取消：丢弃待定的参考线（与固定源一致），已有比例保持不变。
  measureDialog.addEventListener('close', () => { measurePending = undefined; measureRecalibrate = false })
  measureCancel.addEventListener('click', () => { measurePending = undefined; measureRecalibrate = false; measureDialog.close() })
  measureApply.addEventListener('click', () => {
    try {
      if (!measurePending || !measureDialog.open || disposed || locked || previewing || printing || previewDocument || draft.closed || !response.editingEnabled || measurePending.doc !== document || measurePending.snapshot !== JSON.stringify(draft.operations)) throw new Error('草稿已变化，请取消后重新绘制参考线')
      const { page, operation, userUnit } = measurePending
      const scale = parseCalibration(measureValue.value.trim(), measureUnit.value, pdfLineLength(operation.from as number[], operation.to as number[], userUnit))
      if (!scale) throw new Error('请输入大于 0 的长度和不超过 12 个字符的单位')
      if (!/^[\x20-\x7e]+$/.test(scale.unit)) throw new Error('PDF 标签字体为 Helvetica，单位请使用英文字符（如 m、cm、ft）')
      commitMeasure(page, operation, scale, userUnit, () => { status.textContent = `测量比例已标定：1 ${scale.unit} = ${scale.unitsPerPt.toFixed(2)} pt（仅本次会话有效）` })
      measureScale = scale; measureRecalibrate = false; measurePending = undefined; measureDialog.close()
    } catch (error) { measureError.textContent = error instanceof Error ? error.message : String(error) }
  })
  // 二选一：输入一项会清空另一项（与固定源一致）。
  linkUrl.addEventListener('input', () => { if (linkUrl.value.trim()) linkPage.value = '' })
  linkPage.addEventListener('input', () => { linkPage.value = linkPage.value.replace(/[^0-9]/g, ''); if (linkPage.value) linkUrl.value = '' })
  linkCancel.addEventListener('click', () => { linkPending = undefined; linkDialog.close() })
  linkApply.addEventListener('click', () => {
    try {
      if (!linkPending) return
      const raw = linkUrl.value.trim(), url = raw.startsWith('www.') ? `https://${raw}` : raw
      const order = state(), position = Number(linkPage.value)
      let target: { url: string } | { destPage: number }
      if (url) target = { url }
      else if (Number.isInteger(position) && position >= 1 && position <= order.length) target = { destPage: order[position - 1]!.index + 1 }
      else throw new Error(`请输入链接网址，或 1–${order.length} 之间的页码`)
      const operation = pdfDrawingOperation(linkPending.page.pageId, 'link', linkPending.points, linkPending.page.cropBox, drawColor, target)
      pdfPageState(model.pages, [...draft.operations, operation])
      linkPending = undefined; linkDialog.close()
      void append(operation).catch(showError)
    } catch (error) { linkError.textContent = error instanceof Error ? error.message : String(error) }
  })
  textObjects.addEventListener('change', () => { selectedTextId = textObjects.value; fillReplacement(); notifyTextSelection() })
  bindPdfTextEditShortcuts(replacement,stageText,abort.signal)
  stageText.addEventListener('click', () => {
    if (!textEnabled || !response.editingEnabled || locked || printing || previewing || previewDocument || draft.closed || draft.saving || draft.operations.some(op => PDF_EXCLUSIVE_DRAFT_KINDS.includes(op.kind) || op.kind === 'setPageSize')) return
    const target = activeTextObject()
    if (!target) return
    try {
      const operations = draft.operations.filter(op => !(op.kind === 'replaceText' && op.objectId === target.objectId))
      const style=replacementStyle.read()
      if (replacement.value !== target.text || Object.keys(style).length) operations.push({ kind: 'replaceText', pageId: activeId, objectId: target.objectId, expectedTextSha256: target.expectedTextSha256, newText: replacement.value,...style })
      if(operations.some(isStyledPdfReplacement))for(const operation of operations)if(operation.kind==='replaceText')operation.sourceSha256=model.sourceSha256
      pdfPageState(model.pages,operations);draft.setOperations(operations); notifyTextSelection(); void refresh().catch(showError)
    } catch (error) { showError(error) }
  })
  function captureMarkupSelection() {
    if (!document || locked || previewing || previewDocument || !response.editingEnabled || draft.closed || !model.capabilities?.selectionMarkup) return
    const selection = window.getSelection()
    if (!selection || selection.isCollapsed) return
    const pages = state()
    const quads = selectionQuadsByPage(viewport, pages.map(page => {
      const unit = pagesCached.get(page.index)?.userUnit ?? 1
      return { pw: page.cropBox.width * unit, ph: page.cropBox.height * unit, x0: page.cropBox.x, y0: page.cropBox.y, rot: page.rotation, userUnit: unit }
    }), scale)
    if (!quads) return
    markupSelection = [...quads].map(([index, selected]) => ({ pageId: pages[index].pageId, quads: selected, saved: model.pages.find(page => page.pageId === pages[index].pageId)?.markups ?? [] }))
    updateControls()
  }
  window.document.addEventListener('selectionchange', captureMarkupSelection, { signal: abort.signal })
  viewport.addEventListener('pointerdown', () => { markupSelection = []; updateControls() })
  viewport.addEventListener('pointerup', captureMarkupSelection)
  async function applySelectedMarkup(type: MarkupType) {
    if (locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed || !model.capabilities?.selectionMarkup) return
    if (markupSelection.some(selection => !state().find(page => page.pageId === selection.pageId)?.markupReadSafe)) throw new Error('此页已有标注尚不能完整读取，原草稿已保留')
    const color = type === 'highlight' ? markupColor : MARKUP_COLORS[type]
    const selectedState = markupSelectionState(markupSelection, draft.operations, type)
    if (selectedState.active && selectedState.matches.some(match => match.pending < 0 && match.saved) && model.capabilities?.removeMarkup !== true) throw new Error('当前引擎未确认已保存标注移除能力；原草稿已保留')
    const next = togglePdfMarkup(markupSelection, draft.operations, type, color)
    pdfPageState(model.pages, next)
    draft.setOperations(next); await refresh()
  }
  function documentElement<K extends keyof HTMLElementTagNameMap>(tag: K, className = ''): HTMLElementTagNameMap[K] {
    const element = window.document.createElement(tag); element.className = className; return element
  }
  function showError(error: unknown) { if (!disposed) status.textContent = error instanceof Error ? error.message : 'PDF 操作失败，请重试' }
  async function changeSavedNote(pageId: string, annotationId: string, contents: string | null) {
    if (locked || previewing || printing || previewDocument || draft.closed || !response.editingEnabled || model.capabilities?.notes !== true) throw new Error('当前修订或引擎不支持修改已有便签')
    if (model.pages.find(page => page.pageId === pageId)?.notes?.find(note => note.annotationId === annotationId)?.parentAnnotationId !== undefined && !canChangeSavedReply()) throw new Error('当前引擎或修订不支持修改已保存回复')
    const next = stagePdfNote(model.pages, draft.operations, pageId, annotationId, contents)
    pdfPageState(model.pages, next); draft.setOperations(next); await refresh()
  }
  async function editSavedNote(pageId: string, note: SavedPdfNote) {
    if (!note.editable) throw new Error('当前便签只读')
    await editNoteContents(note.contents, value => changeSavedNote(pageId, note.annotationId, value))
  }
  async function changePendingNote(reference: PendingPdfNoteReference, contents: string | null) {
    if (locked || previewing || printing || previewDocument || draft.closed || !response.editingEnabled) throw new Error('当前修订不支持修改待保存便签')
    const next = stagePendingPdfNote(model.pages, draft.operations, reference, contents)
    pdfPageState(model.pages, next); draft.setOperations(next); await refresh()
  }
  async function editNoteContents(contents: string, applyContents: (value: string) => Promise<void>, actionLabel = '应用便签修改', inputLabel = '编辑便签正文') {
    if (locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed) throw new Error('当前便签只读')
    const snapshot = JSON.stringify(draft.operations)
    const dialog = documentElement('dialog', 'pdf-note-edit-dialog'), form = documentElement('form')
    form.method = 'dialog'
    const label = documentElement('label'); label.textContent = inputLabel.replace(/^编辑/, '')
    const input = documentElement('textarea'); input.value = contents; input.maxLength = 10000; input.required = true; input.setAttribute('aria-label', inputLabel); label.append(input)
    const apply = documentElement('button'); apply.type = 'submit'; apply.textContent = actionLabel
    const cancel = documentElement('button'); cancel.type = 'button'; cancel.textContent = '取消'; cancel.addEventListener('click', () => dialog.close())
    form.append(label, apply, cancel); dialog.append(form); root.append(dialog)
    try {
      const value = await new Promise<string | null>(resolve => {
        form.addEventListener('submit', event => { event.preventDefault(); if (!input.value.trim()) { input.setCustomValidity('请输入便签正文'); input.reportValidity(); return }; dialog.close('apply'); resolve(input.value.trim()) })
        input.addEventListener('input', () => input.setCustomValidity(''))
        dialog.addEventListener('close', () => resolve(null), { once: true })
        dialog.showModal(); input.focus()
      })
      if (value === null || disposed) return
      if (JSON.stringify(draft.operations) !== snapshot) throw new Error('草稿已变化，请重新编辑便签')
      await applyContents(value)
    } finally { dialog.remove() }
  }
  function setSidebar(next: typeof sidebar) {
    if (sidebar === 'comments' && next !== 'comments') { commentsGeneration++; commentsFilter.value = ''; commentsLoading = false }
    if (sidebar === 'attachments' && next !== 'attachments') attachmentsGeneration++
    sidebarSizing.setPanel(next ? sidebarPanels[next] : undefined)
    sidebar = next; attachmentsPanel.hidden = next !== 'attachments'; thumbs.hidden = next !== 'thumbs'; outlinePanel.hidden = next !== 'outline'; commentsPanel.hidden = next !== 'comments'
    toggleThumbnails.setAttribute('aria-pressed', String(next === 'thumbs')); outlineToggle.setAttribute('aria-pressed', String(next === 'outline')); commentsToggle.setAttribute('aria-pressed', String(next === 'comments'))
    attachmentsToggle.setAttribute('aria-pressed', String(next === 'attachments'))
    if (next === 'comments') void loadComments()
    if (next === 'attachments') void loadAttachments()
  }
  function canEditAttachments() {
    return !disposed && !!document && !locked && !previewing && !printing && !previewDocument && response.editingEnabled && !draft.closed && model.attachmentsEditable === true && !draft.operations.some(operation => PDF_EXCLUSIVE_DRAFT_KINDS.includes(operation.kind))
  }
  async function setAttachmentOperations(operations: NativeOperation[]) {
    if (!canEditAttachments()) return
    attachmentEditState(model, operations)
    pdfPageState(model.pages, operations)
    draft.setOperations(operations); await refresh()
  }
  async function stageAttachmentFile() {
    const file = attachmentFile.files?.[0]; attachmentFile.value = ''
    if (!file || !canEditAttachments()) return
    const snapshot = JSON.stringify(draft.operations), doc = document
    const op = await attachmentFileOperation(file)
    if (!canEditAttachments() || doc !== document || snapshot !== JSON.stringify(draft.operations)) throw Error('草稿已变化，请重新选择附件')
    await setAttachmentOperations([...draft.operations, op])
  }
  function clearAttachments() {
    attachmentsGeneration++; attachmentsList.replaceChildren(); retryAttachments.hidden = true
    attachmentsStatus.textContent = '正在读取附件…'
  }
  async function loadAttachments() {
    if (disposed || sidebar !== 'attachments' || !document) return
    clearAttachments()
    const epoch = attachmentsGeneration, doc = document, snapshot = JSON.stringify(draft.operations)
    const current = () => !disposed && sidebar === 'attachments' && epoch === attachmentsGeneration && doc === document && snapshot === JSON.stringify(draft.operations)
    try {
      const rows = await attachmentCache.rows(doc)
      if (!current()) return
      const projected = previewDocument ? { removed: new Set<string>(), added: [] as NativeOperation[] } : attachmentEditState(model, draft.operations)
      let failures = 0
      for (const row of rows) {
        if (!current()) return
        const item = documentElement('li'), name = documentElement('strong'), description = documentElement('p'), size = documentElement('span')
        name.textContent = row.filename || '未命名附件'; name.title = row.filename; description.textContent = row.description
        const download = documentElement('button', 'pdf-tool'); download.type = 'button'; download.textContent = '下载附件'; download.disabled = true
        item.append(name, description, size, download); attachmentsList.append(item)
        const saved = !previewDocument && model.attachments?.find(entry => entry.key === row.id)
        if (saved && model.attachmentsEditable) {
          const remove = documentElement('button', 'pdf-tool'); remove.type = 'button'; remove.dataset.pdfAttachmentEditable = 'true'
          const deleted = projected.removed.has(row.id); remove.textContent = deleted ? '撤销移除附件' : '移除附件'; if (deleted) name.textContent += '（待移除）'
          remove.disabled = !canEditAttachments()
          remove.addEventListener('click', () => {
            if (!current() || !canEditAttachments()) return
            const next = deleted ? draft.operations.filter(op => !(op.kind === 'removeAttachment' && op.attachmentId === saved.attachmentId)) : [...draft.operations, {kind:'removeAttachment',attachmentId:saved.attachmentId,expectedAttachmentSha256:saved.expectedAttachmentSha256}]
            void setAttachmentOperations(next).catch(showError)
          }); item.append(remove)
        }
        try {
          const bytes = await attachmentCache.content(doc, row)
          if (!current()) return
          size.textContent = humanBytes(bytes.byteLength); download.disabled = false
          download.addEventListener('click', () => {
            if (!current() || previewing || printing) return
            try { exportAttachment(row, bytes) } catch (error) { showError(error) }
          })
        } catch {
          if (!current()) return
          failures++; size.textContent = '内容读取失败，暂不能下载'
        }
      }
      if (!current()) return
      attachmentsStatus.textContent = failures ? `${rows.length} 个附件；${failures} 个内容读取失败` : rows.length ? `${rows.length} 个附件` : '此 PDF 没有附件'
      for (const op of projected.added) {
        const item = documentElement('li'), name = documentElement('strong'), remove = documentElement('button', 'pdf-tool')
        name.textContent = `${String(op.name)}（待新增）`; remove.type = 'button'; remove.textContent = '取消新增附件'; remove.dataset.pdfAttachmentEditable = 'true'; remove.disabled = !canEditAttachments()
        remove.addEventListener('click', () => { if (current() && canEditAttachments()) void setAttachmentOperations(draft.operations.filter(entry => !(entry.kind === 'addAttachment' && entry.name === op.name))).catch(showError) })
        const size = documentElement('span'), payload = String(op.bytesBase64)
        size.textContent = humanBytes(payload.length * 3 / 4 - (payload.endsWith('==') ? 2 : payload.endsWith('=') ? 1 : 0))
        item.append(name, size, remove); attachmentsList.append(item)
      }
      if (projected.added.length || projected.removed.size) attachmentsStatus.textContent += `；待新增 ${projected.added.length}、待移除 ${projected.removed.size}`
      retryAttachments.hidden = !failures
    } catch {
      if (!current()) return
      attachmentsStatus.textContent = '附件目录读取失败，请重试'; retryAttachments.hidden = false
    }
  }
  function exportAttachment(row: PdfAttachmentRow, bytes: Uint8Array) {
    const url = URL.createObjectURL(new Blob([new Uint8Array(bytes).buffer], { type: 'application/octet-stream' }))
    const link = documentElement('a'); link.href = url; link.download = attachmentDownloadName(row.filename); link.hidden = true
    try { window.document.body.append(link); link.click() }
    finally {
      link.remove()
      attachmentDownloads.set(url, window.setTimeout(() => { URL.revokeObjectURL(url); attachmentDownloads.delete(url) }, 60000))
    }
  }
  function canReply() { return !disposed && !!document && !locked && !previewing && !printing && !previewDocument && response.editingEnabled && !draft.closed && model.capabilities?.noteReplies === true }
  function canChangeSavedReply() { return canReply() && model.capabilities?.savedReplyEdits === true }
  async function changePendingReply(reference: PendingPdfNoteReference, contents: string | null) {
    if (!canReply()) return
    const next = stagePendingPdfReply(model.pages, draft.operations, reference, contents)
    pdfPageState(model.pages, next); draft.setOperations(next); await refresh()
  }
  function renderComments() {
    if (disposed || sidebar !== 'comments') return
    commentsList.replaceChildren()
    const shown = filterComments(commentRoots, commentsFilter.value)
    commentsStatus.textContent = commentsLoading ? `载入中：已读 ${commentsRead} / ${commentsTotal} 页` : commentsFailed ? `可读取 ${commentRoots.length} 个线程；${commentsFailed} 页未能读取` : !commentRoots.length ? '没有可显示的便签批注' : !shown.length ? '没有匹配的便签批注' : `${shown.length} / ${commentRoots.length} 个线程`
    retryComments.hidden = !commentsFailed || commentsLoading
    const row = (node: CommentNode) => {
      const control = documentElement('button', 'pdf-comment-row'); control.type = 'button'; control.dataset.commentKey = node.key
      control.setAttribute('aria-current', String(selectedComment === node.key))
      const label = documentElement('span'); label.textContent = `第 ${node.pageNo} 页 · ${node.author || '—'}${node.timeMs === null ? ' · 时间未知' : ` · ${new Date(node.timeMs).toLocaleString()}`}${node.readonly || !response.editingEnabled || previewDocument ? ' · 只读' : ''}`
      const body = documentElement('span'); body.textContent = node.contents || '（空便签）'; control.append(label, body)
      if (node.issue) { const issue = documentElement('small'); issue.textContent = node.issue; control.append(issue) }
      const target: CommentTarget = { node, snapshot: commentsSnapshot, document: commentsDocument! }
      control.addEventListener('click', () => {
        if (disposed || target.document !== document || target.snapshot !== JSON.stringify(draft.operations)) { status.textContent = '批注列表已更新，请重新选择'; return }
        searchJumpPending = false; selectedComment = node.key; pendingCommentJump = target; renderComments(); jumpComment()
      })
      return control
    }
    for (const root of shown) {
      const item = documentElement('div'); item.setAttribute('role', 'listitem'); item.append(row(root))
      const replies = flattenComments(root).slice(1)
      if (replies.length) {
        const details = documentElement('details'), summary = documentElement('summary'); summary.textContent = `${replies.length} 条回复`; details.append(summary)
        for (const { node, depth } of replies) {
          const control = row(node); control.style.marginInlineStart = `${Math.min(depth, 6) * 8}px`; details.append(control)
          if (node.savedReplyId && !node.readonly) {
            const snapshot=commentsSnapshot,doc=commentsDocument,epoch=commentsGeneration,id=node.savedReplyId
            const current=()=>sidebar==='comments' && doc===document && epoch===commentsGeneration && snapshot===JSON.stringify(draft.operations) && canChangeSavedReply()
            for (const [label,action] of [['编辑已保存回复',()=>editNoteContents(node.contents,async contents=>{if(!current())throw Error('批注列表已变化，请重新选择回复');await changeSavedNote(node.pageId,id,contents)},'应用回复修改','编辑已保存回复正文')],['删除已保存回复',()=>changeSavedNote(node.pageId,id,null)]] as const) {
              const button=documentElement('button','pdf-tool');button.type='button';button.textContent=label;button.dataset.pdfSavedReplyEditable='true';button.disabled=!canChangeSavedReply()
              button.addEventListener('click',()=>{if(current())void Promise.resolve().then(action).catch(showError)});details.append(button)
            }
          }
          if (node.pendingReply && node.pendingIndex !== undefined) {
            const reference = {index:node.pendingIndex,snapshot:commentsSnapshot}, replyDoc = commentsDocument, replyEpoch = commentsGeneration
            for (const [label,action] of [['编辑待保存回复',()=>editNoteContents(node.contents,value=>{if(sidebar!=='comments'||replyEpoch!==commentsGeneration||replyDoc!==document||!canReply())throw Error('批注列表已变化，请重新选择回复');return changePendingReply(reference,value)},'应用回复修改','编辑回复正文')],['取消待保存回复',()=>changePendingReply(reference,null)]] as const) {
              const button = documentElement('button','pdf-tool'); button.type='button';button.textContent=label;button.dataset.pdfReplyEditable='true';button.disabled=!canReply()
              button.addEventListener('click',()=>{if(sidebar==='comments' && replyEpoch===commentsGeneration && replyDoc===document && reference.snapshot===JSON.stringify(draft.operations) && canReply())void Promise.resolve().then(action).catch(showError)});details.append(button)
            }
          }
        }
        item.append(details)
      }
      if ((root.replyAnnotationId || root.pendingIndex !== undefined) && !previewDocument) {
        const reply = documentElement('button','pdf-tool'), snapshot = commentsSnapshot, doc = commentsDocument, epoch = commentsGeneration
        reply.type='button';reply.textContent='回复此线程';reply.dataset.pdfReplyEditable=String(root.pendingIndex===undefined||model.capabilities?.pendingNoteReplies===true);reply.disabled=!canReply()||reply.dataset.pdfReplyEditable!=='true'
        reply.addEventListener('click',()=>{
          if (!canReply() || reply.dataset.pdfReplyEditable!=='true' || sidebar!=='comments' || epoch!==commentsGeneration || doc!==document || snapshot!==JSON.stringify(draft.operations)) return
          void editNoteContents('',async contents=>{
            if (!canReply() || reply.dataset.pdfReplyEditable!=='true' || sidebar!=='comments' || epoch!==commentsGeneration || doc!==document || snapshot!==JSON.stringify(draft.operations)) throw Error('批注列表已变化，请重新选择线程')
            const next=root.pendingIndex===undefined ? stagePdfReply(model.pages,draft.operations,root.pageId,root.replyAnnotationId!,contents) : stagePdfLocalReply(model.pages,draft.operations,{index:root.pendingIndex,snapshot},contents)
            pdfPageState(model.pages,next);draft.setOperations(next);await refresh()
          },'加入回复草稿','回复正文').catch(showError)
        });item.append(reply)
      }
      commentsList.append(item)
    }
  }
  async function loadComments() {
    if (disposed || sidebar !== 'comments' || !document) return
    const epoch = ++commentsGeneration, doc = document, preview = !!previewDocument, pages = state(), operations = draft.operations
    commentsDocument = doc; commentsSnapshot = JSON.stringify(operations); commentRoots = []; commentsRead = commentsFailed = 0; commentsTotal = pages.length; commentsLoading = true; renderComments()
    for (const [position, page] of pages.entries()) {
      if (disposed || sidebar !== 'comments' || epoch !== commentsGeneration || doc !== document) return
      const source = model.pages.find(item => item.pageId === page.pageId)
      const identity = { ...page, notes: source?.notes, notesReadSafe: source?.notesReadSafe }, readIndex = preview ? position : page.index
      let roots: CommentNode[]
      try { roots = projectPageComments(await annotationCache.get(doc, readIndex), identity, position + 1, operations, preview) }
      catch {
        if (epoch !== commentsGeneration || doc !== document || disposed) return
        annotationCache.evict(doc, readIndex); commentsFailed++
        roots = projectPageComments([], identity, position + 1, operations, preview)
      }
      if (disposed || epoch !== commentsGeneration || doc !== document) return
      commentRoots.push(...roots)
      commentsRead++; renderComments()
    }
    if (epoch === commentsGeneration) { commentsLoading = false; if (!commentRoots.some(root => flattenComments(root).some(({ node }) => node.key === selectedComment))) selectedComment = ''; renderComments() }
  }
  function jumpComment() {
    const target = pendingCommentJump
    if (!target || searchRendering) return
    if (target.document !== document || target.snapshot !== JSON.stringify(draft.operations)) { pendingCommentJump = null; return }
    const card = pageNodes.get(target.node.pageId)
    if (!card) return
    const note = target.node.pendingIndex === undefined ? [...card.querySelectorAll<HTMLElement>('[data-note-id]')].find(node => node.dataset.noteId === target.node.cardId) : [...card.querySelectorAll<HTMLElement>('[data-operation-index]')].find(node => node.dataset.operationIndex === String(target.node.pendingIndex))
    for (const node of viewport.querySelectorAll('.pdf-comment-selected')) node.classList.remove('pdf-comment-selected')
    if (note) { const details = note.closest('details'); if (details) details.open = true; note.classList.add('pdf-comment-selected'); note.tabIndex = -1; note.scrollIntoView({ block: 'center' }); note.focus({ preventScroll: true }) }
    else { card.scrollIntoView({ block: 'start' }); status.textContent = '已定位所在页；此批注无法唯一匹配页内卡片' }
    activeId = target.node.pageId; for (const node of pageNodes.values()) node.classList.toggle('is-active', node === card)
    pendingCommentJump = null; updateControls(); renderTextPanel(true)
  }
  // 合并/拆分页面改变整份文档的页数与页面身份：实际预览期间按服务端复读的输出模型显示。
  let layoutPreviewPages: PdfPageIdentity[] | undefined
  function state() { return previewDocument && layoutPreviewPages ? layoutPreviewPages : pdfPageState(model.pages, draft.operations) }
  function jumpToPageForIdentity(pageId: string) {
    const page = state().find(candidate => candidate.pageId === pageId)
    if (!page) return
    activeId = pageId
    pageNodes.get(pageId)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    for (const node of pageNodes.values()) node.classList.toggle('is-active', node.dataset.pageId === activeId)
    updateControls(); renderTextPanel(true)
  }
  function jumpToPage(input: HTMLInputElement) {
    if (!document) return
    const pages = state(), requested = Number(input.value)
    if (!Number.isInteger(requested) || requested < 1 || requested > pages.length) { updateControls(); return }
    const page = pages[requested - 1]!
    activeId = page.pageId
    pageNodes.get(page.pageId)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    for (const node of pageNodes.values()) node.classList.toggle('is-active', node.dataset.pageId === activeId)
    updateControls(); renderTextPanel(true)
  }
  function setMode(next: typeof mode) { if (next !== 'staticText') staticText?.cancel(); if (next !== 'draw' || drawShape !== 'polygon') cancelPolygon(); mode = next; noteInput.hidden = mode !== 'note'; root.dataset.pdfMode = mode; if (mode !== 'text') { reportedSelectionPage = ''; onSelectionChange?.([]) }; textPanel.hidden = mode !== 'text' || !!previewDocument; for (const [button, value] of [[select, 'select'], [note, 'note']] as const) button.setAttribute('aria-pressed', String(mode === value)); for (const [shape, tool] of drawButtons) tool.setAttribute('aria-pressed', String(mode === 'draw' && drawShape === shape)); root.querySelector('[data-pdf-redact-tool]')?.setAttribute('aria-pressed', String(mode === 'redact')); syncDrawingCanvases() }
  function canChangePendingDrawings() {
    return !disposed && !!document && !locked && !printing && !previewing && !previewDocument && response.editingEnabled && !draft.closed
  }
  async function editPendingDrawingPosition(reference: PendingDrawingReference) {
    const source = document, sourcePage = activeId
    const current = () => canChangePendingDrawings() && source === document && sourcePage === activeId && !pendingDrawingsPanel.hidden && reference.snapshot === JSON.stringify(draft.operations) && selectedPendingDrawing === reference
    if (!current()) return
    pendingDrawingTarget(model.pages, draft.operations, reference)
    const dialog = documentElement('dialog', 'pdf-pending-drawing-dialog'), form = documentElement('form')
    dialog.setAttribute('aria-label', '移动待保存绘图'); form.method = 'dialog'
    const help = documentElement('p'); help.textContent = '按原始 PDF 坐标平移：X 向右，Y 向上；旋转后仍以原始坐标方向为准。保持形状、颜色和线宽，超出页面时不应用。'
    const fields = ['X 位移（PDF 单位）', 'Y 位移（PDF 单位）'].map(text => {
      const label = documentElement('label'); label.textContent = text
      const input = documentElement('input'); input.type = 'number'; input.step = 'any'; input.value = '0'; input.required = true; input.setAttribute('aria-label', text); label.append(input); form.append(label); return input
    })
    const error = documentElement('p'); error.setAttribute('role', 'alert')
    const apply = documentElement('button'); apply.type = 'submit'; apply.textContent = '应用位移'
    const cancel = documentElement('button'); cancel.type = 'button'; cancel.textContent = '取消'; cancel.addEventListener('click', () => dialog.close())
    form.prepend(help); form.append(error, apply, cancel); dialog.append(form); pendingDrawingDialog?.close(); root.append(dialog); pendingDrawingDialog = dialog
    let cancelOnAbort: (() => void) | undefined
    try {
      await new Promise<void>(resolve => {
        cancelOnAbort = () => { if (dialog.open) dialog.close(); resolve() }
        abort.signal.addEventListener('abort', cancelOnAbort, { once: true })
        dialog.addEventListener('close', () => resolve(), { once: true })
        form.addEventListener('submit', event => {
          event.preventDefault()
          if (!dialog.open) return
          try {
            if (pendingDrawingDialog !== dialog || !current()) throw Error('草稿、页面或选择已变化，请重新选择绘图')
            if (fields.some(input => !input.value.trim())) throw Error('请输入 X 和 Y 位移')
            const next = movePendingDrawing(model.pages, draft.operations, reference, Number(fields[0]!.value), Number(fields[1]!.value))
            draft.setOperations(next); selectedPendingDrawing = undefined; dialog.close(); void refresh().catch(showError)
          } catch (cause) { error.textContent = cause instanceof Error ? cause.message : '无法移动此绘图' }
        })
        dialog.showModal(); fields[0]!.focus()
      })
    } finally {
      if (cancelOnAbort) abort.signal.removeEventListener('abort', cancelOnAbort)
      if (pendingDrawingDialog === dialog) pendingDrawingDialog = undefined
      dialog.remove()
    }
  }
  async function editPendingImageSize(reference: PendingDrawingReference) {
    const source = document, sourcePage = activeId
    const current = () => canChangePendingDrawings() && source === document && sourcePage === activeId && !pendingDrawingsPanel.hidden && reference.snapshot === JSON.stringify(draft.operations) && selectedPendingDrawing === reference
    if (!current()) return
    if (!pendingDrawingTarget(model.pages, draft.operations, reference).resizable) return
    const dialog = documentElement('dialog', 'pdf-pending-drawing-dialog'), form = documentElement('form')
    dialog.setAttribute('aria-label', '缩放待保存图像'); form.method = 'dialog'
    const help = documentElement('p'); help.textContent = '保持当前图像纵横比，围绕固定角缩放。固定角使用原始 PDF 坐标：左/右与上/下不随页面旋转改变；超出页面时不应用。'
    const label = documentElement('label'); label.textContent = '缩放百分比'
    const percent = documentElement('input'); percent.type = 'number'; percent.step = 'any'; percent.value = '100'; percent.required = true; percent.setAttribute('aria-label', '缩放百分比'); label.append(percent)
    const anchorLabel = documentElement('label'); anchorLabel.textContent = '固定角（原始 PDF 坐标）'
    const anchor = documentElement('select'); anchor.setAttribute('aria-label', '固定角（原始 PDF 坐标）')
    for (const [value, text] of [['bottom-left', '左下'], ['bottom-right', '右下'], ['top-left', '左上'], ['top-right', '右上']]) {
      const option = documentElement('option'); option.value = value!; option.textContent = text!; anchor.append(option)
    }
    anchorLabel.append(anchor)
    const error = documentElement('p'); error.setAttribute('role', 'alert')
    const apply = documentElement('button'); apply.type = 'submit'; apply.textContent = '应用缩放'
    const cancel = documentElement('button'); cancel.type = 'button'; cancel.textContent = '取消'; cancel.addEventListener('click', () => dialog.close())
    form.append(help, label, anchorLabel, error, apply, cancel); dialog.append(form); pendingDrawingDialog?.close(); root.append(dialog); pendingDrawingDialog = dialog
    let cancelOnAbort: (() => void) | undefined
    try {
      await new Promise<void>(resolve => {
        cancelOnAbort = () => { if (dialog.open) dialog.close(); resolve() }
        abort.signal.addEventListener('abort', cancelOnAbort, { once: true })
        dialog.addEventListener('close', () => resolve(), { once: true })
        form.addEventListener('submit', event => {
          event.preventDefault()
          if (!dialog.open) return
          try {
            if (pendingDrawingDialog !== dialog || !current()) throw Error('草稿、页面或选择已变化，请重新选择图像')
            if (!percent.value.trim()) throw Error('请输入缩放百分比')
            const next = resizePendingImage(model.pages, draft.operations, reference, Number(percent.value) / 100, anchor.value as PendingImageAnchor)
            draft.setOperations(next); selectedPendingDrawing = undefined; dialog.close(); void refresh().catch(showError)
          } catch (cause) { error.textContent = cause instanceof Error ? cause.message : '无法缩放此图像' }
        })
        dialog.showModal(); percent.focus()
      })
    } finally {
      if (cancelOnAbort) abort.signal.removeEventListener('abort', cancelOnAbort)
      if (pendingDrawingDialog === dialog) pendingDrawingDialog = undefined
      dialog.remove()
    }
  }
  function renderPendingDrawings() {
    const epoch = ++pendingDrawingsGeneration
    if (pendingDrawingsPanel.hidden) return
    pendingDrawingsPanel.replaceChildren()
    const source = document, sourcePage = activeId, operations = draft.operations, snapshot = JSON.stringify(operations)
    if (selectedPendingDrawing && (selectedPendingDrawing.snapshot !== snapshot || selectedPendingDrawing.pageId !== sourcePage)) selectedPendingDrawing = undefined
    const current = () => epoch === pendingDrawingsGeneration && source === document && sourcePage === activeId && snapshot === JSON.stringify(draft.operations) && !pendingDrawingsPanel.hidden && canChangePendingDrawings()
    const page = model.pages.find(item => item.pageId === sourcePage)
    const heading = documentElement('p'); heading.textContent = `待保存绘图 · 来源第 ${page ? page.index + 1 : '—'} 页`
    const help = documentElement('p'); help.textContent = '选择一个草稿记录后可平移或删除；图像还可保持纵横比缩放。保存后成为已保存绘图。链接可删除，暂不支持移动。'
    pendingDrawingsPanel.append(heading, help)
    let count = 0
    for (const [index, operation] of operations.entries()) {
      if (operation.kind !== 'addDrawing' || operation.pageId !== sourcePage) continue
      count++
      const reference = { index, snapshot, pageId: sourcePage }
      const row = documentElement('div'); row.dataset.pdfPendingDrawing = String(index)
      const label = documentElement('span'); label.textContent = `${operation.shape} · 草稿操作 #${index + 1}`
      const select = documentElement('button'); select.type = 'button'; select.textContent = '选择此绘图'; select.disabled = !current()
      select.setAttribute('aria-pressed', String(selectedPendingDrawing?.index === index))
      select.addEventListener('click', () => {
        if (!current()) return
        try { pendingDrawingTarget(model.pages, draft.operations, reference); selectedPendingDrawing = reference; renderPendingDrawings() } catch (cause) { showError(cause) }
      })
      row.append(label, select); pendingDrawingsPanel.append(row)
    }
    if (!count) { const empty = documentElement('p'); empty.textContent = '当前来源页没有待保存绘图'; pendingDrawingsPanel.append(empty) }
    if (selectedPendingDrawing) {
      const reference = selectedPendingDrawing, target = pendingDrawingTarget(model.pages, operations, reference)
      const chosen = documentElement('p'); chosen.textContent = `已选择草稿操作 #${reference.index + 1}（${target.operation.shape}）`
      const move = documentElement('button'); move.type = 'button'; move.textContent = '移动所选绘图'; move.disabled = !current() || !target.movable
      move.addEventListener('click', () => { if (current()) void editPendingDrawingPosition(reference).catch(showError) })
      const remove = documentElement('button'); remove.type = 'button'; remove.textContent = '删除所选绘图'; remove.disabled = !current()
      remove.addEventListener('click', () => {
        if (!current() || selectedPendingDrawing !== reference) return
        try { draft.setOperations(removePendingDrawing(model.pages, draft.operations, reference)); selectedPendingDrawing = undefined; void refresh().catch(showError) } catch (cause) { showError(cause) }
      })
      const resize = documentElement('button'); resize.type = 'button'; resize.textContent = '缩放所选图像'; resize.disabled = !current() || !target.resizable
      resize.addEventListener('click', () => { if (current()) void editPendingImageSize(reference).catch(showError) })
      pendingDrawingsPanel.append(chosen, move, resize, remove)
    }
    syncDrawingCanvases()
  }
  function renderSavedDrawings() {
    if (drawingsPanel.hidden) return
    drawingsPanel.replaceChildren()
    const page = model.pages.find(item => item.pageId === activeId)
    const heading = documentElement('p'); heading.textContent = `已保存绘图 · 来源第 ${page ? page.index + 1 : '—'} 页`
    const help = documentElement('p'); help.textContent = '按原始批注槽位选择。删除仅逻辑移除绘图，不是安全擦除；敏感内容请使用涂黑。暂存后可撤销、重做或恢复草稿；生成实际预览后核对。'
    drawingsPanel.append(heading, help)
    const source = document, snapshot = JSON.stringify(draft.operations)
    const canEdit = () => !disposed && source === document && snapshot === JSON.stringify(draft.operations) && !locked && !printing && !previewing && !previewDocument && response.editingEnabled && !draft.closed && model.capabilities?.removeDrawing === true
    for (const offset of [-1, 1]) {
      const adjacent = state()[state().findIndex(item => item.pageId === activeId) + offset]
      const nav = documentElement('button'); nav.type = 'button'; nav.textContent = offset < 0 ? '上一页绘图' : '下一页绘图'; nav.disabled = !adjacent || !!previewDocument
      nav.addEventListener('click', () => { if (!disposed && source === document && adjacent && !previewDocument) jumpToPageForIdentity(adjacent.pageId) })
      drawingsPanel.append(nav)
    }
    if (!page?.drawings?.length) { const empty = documentElement('p'); empty.textContent = page?.drawingsReadSafe === false ? '绘图列表读取不完整，暂不能删除' : '当前来源页没有支持的已保存绘图'; drawingsPanel.append(empty) }
    for (const drawing of page?.drawings ?? []) {
      const row = documentElement('div'); row.dataset.pdfSavedDrawing = drawing.annotationId
      const label = documentElement('span'); label.textContent = `${drawing.subtype} · 原始批注 #${drawing.annotationIndex + 1} · ${drawing.annotationId.slice(0, 10)}`
      const action = documentElement('button'); action.type = 'button'
      const pending = draft.operations.some(op => op.kind === 'removeDrawing' && op.annotationId === drawing.annotationId)
      action.textContent = pending ? '撤销此删除' : '暂存删除'; action.disabled = !canEdit() || !drawing.removable || !page?.drawingsReadSafe
      action.title = drawing.removalReason || '精确删除此原始绘图；请生成实际预览核对'
      action.addEventListener('click', () => { if (!canEdit() || !page) return; try { const next = toggleSavedDrawing(draft.operations, page, drawing.annotationId); pdfPageState(model.pages, next); draft.setOperations(next); void refresh().catch(showError) } catch (error) { showError(error) } })
      row.append(label, action)
      if (drawing.removalReason) { const reason = documentElement('span'); reason.textContent = drawing.removalReason; row.append(reason) }
      drawingsPanel.append(row)
    }
  }
  function updateControls() {
    pdfFormAI?.update()
    fillFormAI.disabled=!(response.pdfFormAIEnabled&&response.editingEnabled)||locked||previewing||printing||draft.closed||draft.saving
    pdfReview?.update()
    processNotes.disabled = response.pdfReviewAIEnabled !== true || locked || previewing || printing || draft.closed || draft.saving
    syncDrawingCanvases()
    if (!canChangePendingDrawings()) pendingDrawingDialog?.close()
    renderPendingDrawings()
    renderSavedDrawings()
    for (const control of root.querySelectorAll<HTMLButtonElement>('[data-pdf-saved-reply-editable]')) control.disabled = !canChangeSavedReply()
    for (const control of root.querySelectorAll<HTMLButtonElement>('[data-pdf-reply-editable]')) control.disabled = !canReply() || control.dataset.pdfReplyEditable !== 'true'
    addAttachment.disabled = attachmentFile.disabled = !canEditAttachments()
    addAttachment.title = document ? model.attachmentsReason || '选择本地文件加入草稿，保存时写入 PDF' : '请先打开 PDF'
    for (const control of root.querySelectorAll<HTMLButtonElement>('[data-pdf-attachment-editable]')) control.disabled = !canEditAttachments()
    for (const button of editableButtons) button.disabled = locked || previewing || printing || !!previewDocument || !response.editingEnabled || draft.closed
    insertStaticText.disabled ||= staticTextUnavailable() !== null
    insertStaticText.title = staticTextUnavailable() ?? '插入可搜索文字，支持字体、粗斜体、多行与左中右对齐；单独保存并核对实际 PDF 预览'
    staticText?.refresh()
    formDesignDelete.disabled ||= formDesignUnavailable() !== null
    formDesignDelete.title = formDesignUnavailable() ?? '按来源身份选择安全字段，单独暂存删除并核对实际预览'
    formDesignPanel?.refresh()
    formCreatePanel?.refresh();textPropertiesPanel?.refresh();radioExtensionPanel?.refresh();existingImagePanel?.refresh()
    sizeOptions.disabled = sizeApplying || locked || previewing || printing || !!previewDocument || !response.editingEnabled || draft.closed
    cropFields.disabled = cropApplying || locked || previewing || printing || !!previewDocument || !response.editingEnabled || draft.closed
    const exclusiveDraft=draft.operations.some(operation=>PDF_EXCLUSIVE_DRAFT_KINDS.includes(operation.kind))
    if (exclusiveDraft) for (const control of editableButtons) if (control !== undo && control !== redo) control.disabled = true
    for(const control of [createTextField,createCheckBox,...extendedFormCreationButtons])control.disabled ||= objectDesignUnavailable()!==null||model.capabilities?.createFormField!==true
    fieldProperties.disabled ||= objectDesignUnavailable()!==null||model.capabilities?.editFormWidget!==true
    textFieldProperties.disabled ||= objectDesignUnavailable()!==null||model.capabilities?.editFormTextProperties!==true
    appendRadioOption.disabled ||= objectDesignUnavailable()!==null||model.capabilities?.appendRadioWidget!==true
    arrangeFields.disabled ||= objectDesignUnavailable()!==null||model.capabilities?.arrangeFormWidgets!==true
    editExistingImage.disabled ||= existingImageUnavailable()!==null
    editExistingImage.title=existingImageUnavailable()??'移动或调整来源 PDF 中已有图像的尺寸'
    undo.disabled ||= !draft.canUndo; redo.disabled ||= !draft.canRedo
    for (const control of root.querySelectorAll<HTMLButtonElement>('[data-pdf-note-editable]')) control.disabled = locked || previewing || printing || !!previewDocument || !response.editingEnabled || draft.closed || control.dataset.pdfNoteEditable !== 'true'
    commentsToggle.disabled = attachmentsToggle.disabled = !document || previewing || printing
    noteInput.disabled = locked || previewing || !!previewDocument || !response.editingEnabled || draft.closed
    textObjects.disabled = replacement.disabled = stageText.disabled = exclusiveDraft || draft.operations.some(op => op.kind === 'setPageSize') || locked || previewing || !!previewDocument || draft.closed
    replacementStyle.setDisabled(stageText.disabled||!textEnabled||!response.editingEnabled)
    for (const control of formControls.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select')) control.disabled = exclusiveDraft || control.dataset.pdfEditable !== 'true' || locked || previewing || !!previewDocument || !response.editingEnabled || draft.closed
    if (textEditButton) textEditButton.disabled ||= !textLoaded
    previewButton.disabled = locked || previewing || !response.editingEnabled || draft.closed
    printButton.disabled = !pdfCanPrint({ loaded: !!document, locked, dirty: draft.dirty, previewing, printing, previewDocument: !!previewDocument })
    backToSource.disabled = locked || previewing
    confirmPreview.disabled = locked || previewing || draft.closed
    for (const input of pageInputs) input.disabled = !document
    homeZoom.disabled = homeZoomOut.disabled = homeZoomIn.disabled = zoomOut.disabled = zoomIn.disabled = statusZoomOut.disabled = statusZoomIn.disabled = zoomSlider.disabled = nightToggle.disabled = viewFitWidth.disabled = viewFitPage.disabled = !document
    if (document) {
      const pages = state()
      const current = String(Math.max(1, pages.findIndex(page => page.pageId === activeId) + 1))
      for (const input of pageInputs) { input.max = String(pages.length); input.value = current }
      for (const total of root.querySelectorAll('.pdf-view-page-row span')) total.textContent = ` / ${pages.length}`
    }
    for (const id of ['genoffice.pdf.page.rotateLeft', 'genoffice.pdf.page.rotateRight']) pageButtons.get(id)!.disabled ||= !activeId
    const extract = pageButtons.get('genoffice.pdf.page.extract')!
    extract.disabled ||= extractionUnavailable() !== null
    extract.title = extractionUnavailable() ?? '按所选页码生成独立 PDF，来源文档保持不变'
    for(const control of [convertPptx,...officeConvertButtons,...exportTextButtons,exportPng,exportJpg]){control.disabled ||= extractionUnavailable()!==null;control.title=extractionUnavailable()??'从已保存来源生成独立下载'}
    protectButton.disabled ||= protectionUnavailable() !== null
    protectButton.title = protectionUnavailable() ?? '生成独立密码保护下载；密码不保存在草稿中'
    for(const id of ['genoffice.pdf.page.insertPdf','genoffice.pdf.page.replace']){const control=pageButtons.get(id)!;control.disabled ||= extractionUnavailable()!==null;control.title=extractionUnavailable()??'上传来源身份绑定的外部 PDF，保存为新修订'}
    const crop = pageButtons.get('genoffice.pdf.page.crop')!
    crop.disabled ||= draft.operations.some(op => op.kind === 'setPageSize') || cropApplying || !document || !activeId || model.capabilities?.cropPage !== true || draft.operations.length >= 500
    crop.title = document && model.capabilities?.cropPage === true ? '裁切当前页的可见范围，保留底层内容；不能用于删除敏感信息' : '当前 PDF 引擎未确认裁切写回能力'
    const size = pageButtons.get('genoffice.pdf.page.size')!
    size.disabled ||= sizeApplying || !document || (!!document && pageSizeUnavailable() !== null)
    size.title = document ? pageSizeUnavailable() ?? '按整页等比缩放内容与批注，并查看实际预览' : '请先打开 PDF'
    const rotateAll = pageButtons.get('genoffice.pdf.page.rotateAll')!
    const rotateAllOverBudget = !!document && draft.operations.length + state().length > 500
    rotateAll.disabled ||= !document || rotateAllOverBudget
    rotateAll.title = rotateAllOverBudget ? '旋转全部页面将超过 500 条修改；请先保存当前修改或减少页面后重开' : '将当前全部保留页面顺时针旋转 90°'
    rotateAll.setAttribute('aria-description', rotateAll.title)
    pageButtons.get('genoffice.pdf.page.delete')!.disabled ||= !activeId || (!!document && state().length <= 1)
    pageButtons.get('genoffice.pdf.page.reverse')!.disabled ||= !document || state().length <= 1
    for (const id of ['genoffice.pdf.page.mergePages', 'genoffice.pdf.page.splitPages']) {
      const control = pageButtons.get(id)!, reason = document ? pageLayoutUnavailable(id.endsWith('splitPages') ? 'splitPages' : 'mergePages') : '请先打开 PDF'
      control.disabled ||= !!reason
      control.title = reason ?? (id.endsWith('mergePages') ? '合并页面：每 N 页排到一张纸上，单独保存为新修订' : '拆分页面：每页均分为 2/4/9 页，单独保存为新修订')
    }
    const insertBlank = pageButtons.get('genoffice.pdf.page.insertBlank')!
    insertBlank.disabled ||= !document || draft.operations.length + 2 > 500
    insertBlank.title = draft.operations.length + 2 > 500 ? '插入空白页将超过 500 条修改；请先保存当前修改' : '在当前页之后插入与当前页同尺寸的空白页'
    const activeBlank = !!document && state().some(page => page.pageId === activeId && page.blank)
    if (activeBlank) { crop.disabled = true; crop.title = '新插入的空白页请先保存并重新打开后再裁切' }
    for (const { button, type } of markupButtons) {
      const state = markupSelectionState(markupSelection, draft.operations, type)
      const savedRemoval = state.active && state.matches.some(match => match.pending < 0 && match.saved && (model.capabilities?.removeMarkup !== true || !match.saved.removable))
      button.disabled ||= !document || model.capabilities?.selectionMarkup !== true || !markupSelection.length || markupSelection.some(selection => !model.pages.find(page => page.pageId === selection.pageId)?.markupReadSafe) || savedRemoval
      button.setAttribute('aria-pressed', String(state.active))
      button.title = !document ? '请先打开 PDF' : !response.editingEnabled || draft.closed ? '当前修订为只读' : model.capabilities?.selectionMarkup !== true ? '当前引擎未确认文字选区标注能力' : markupSelection.some(selection => !model.pages.find(page => page.pageId === selection.pageId)?.markupReadSafe) ? '此页已有文字标注尚不能完整读取' : savedRemoval ? state.matches.find(match => match.saved && !match.saved.removable)?.saved?.removalReason || '当前引擎或来源不支持移除已保存标注' : '选择页面文字后添加；再次点击移除同类标注。移除结果请查看实际 PDF 预览'
    }
    status.dataset.dirty = String(draft.dirty)
  }
  async function append(operation: NativeOperation) {
    if (locked || previewing || previewDocument || !response.editingEnabled || draft.closed) return
    if (draft.operations.some(operation => PDF_EXCLUSIVE_DRAFT_KINDS.includes(operation.kind))) throw new Error('此项 PDF 编辑须单独保存')
    const next=[...draft.operations,operation];pdfPageState(model.pages,next)
    draft.setOperations(next); await refresh()
  }
  function cleanupPrint() {
    if (printTimer !== undefined) window.clearTimeout(printTimer)
    printTimer = undefined
    printRoot?.remove(); printRoot = undefined; printing = false
    window.removeEventListener('afterprint', cleanupPrint)
    updateControls(); scheduleFit()
  }
  async function printPdf() {
    if (!pdfCanPrint({ loaded: !!document, locked, dirty: draft.dirty, previewing, printing, previewDocument: !!previewDocument }) || !document) throw new Error('请先完成保存或返回原稿，再打印 PDF')
    printing = true; updateControls(); status.textContent = '正在准备完整 PDF 打印页面…'
    let printHost: Awaited<ReturnType<typeof renderPdfPrintHost>> | undefined
    try {
      const pages = pdfPrintPages(model.pages, draft.operations)
      if (!document) throw new Error('PDF 尚未载入')
      printHost = await renderPdfPrintHost(root, pages, index => document!.getPage(index + 1), AnnotationMode.ENABLE, MAX_PAGE_PIXELS)
      if (disposed) { printHost.cleanup(); throw new Error('PDF 打印已取消') }
      printRoot = printHost.host
      status.textContent = '正在打开浏览器打印对话框…'
      window.addEventListener('afterprint', cleanupPrint, { once: true })
      printTimer = window.setTimeout(cleanupPrint, 60000)
      printHost.print(() => window.print())
    } catch (error) {
      if (printHost) printHost.cleanup()
      cleanupPrint()
      throw error
    }
  }
  function scheduleSearch() {
    if (searchTimer !== undefined) window.clearTimeout(searchTimer)
    searchCount.textContent = currentSearch ? '正在搜索…' : ''
    searchTimer = window.setTimeout(() => runSearch(true), 200)
  }
  function runSearch(jump: boolean, reset = true) {
    if (searchTimer !== undefined) window.clearTimeout(searchTimer)
    searchTimer = undefined
    if (disposed || !document) return
    const surviving = new Set(state().map(page => page.pageId))
    searchMatches = searchInIndex(searchIndex, currentSearch, { matchCase: searchMatchCase, wholeWord: searchWholeWord })
      .map(match => ({ pageId: searchPageIds[match.pageIndex], rects: match.rects })).filter(match => surviving.has(match.pageId))
    searchPosition = reset ? 0 : Math.min(searchPosition, Math.max(0, searchMatches.length - 1))
    markSearch()
    if (jump) searchJumpPending = searchMatches.length > 0
    if (!searchMatches.length) searchJumpPending = false
    if (searchJumpPending) jumpSearch()
  }
  function jumpSearch() {
    if (searchRendering) { searchJumpPending = true; return }
    const match = searchMatches[searchPosition], page = match && state().find(page => page.pageId === match.pageId)
    const holder = match && pageNodes.get(match.pageId)?.querySelector<HTMLElement>('.pdf-page-content')
    if (!page || !holder) return
    const original = pagesCached.get(previewDocument ? state().findIndex(item => item.pageId === page.pageId) : page.index)
    if (!original) return
    const view = displayViewport(original, page, scale), rect = match.rects[0]
    const point = view.convertToViewportPoint(rect[0], rect[3])
    const bounds = holder.getBoundingClientRect(), scroll = viewport.getBoundingClientRect()
    viewport.scrollTop = Math.max(0, viewport.scrollTop + bounds.top - scroll.top + point[1] - viewport.clientHeight * .35)
    searchJumpPending = false
    activeId = page.pageId
    for (const node of pageNodes.values()) node.classList.toggle('is-active', node.dataset.pageId === activeId)
    updateControls(); renderTextPanel(true)
  }
  function markSearch() {
    searchCount.textContent = !currentSearch ? '' : searchLoading ? '正在建立搜索索引…' : searchMatches.length ? `${searchPosition + 1} / ${searchMatches.length}${searchMatches.length === 1000 ? '（最多 1000 处）' : ''}` : '无匹配；扫描页需 OCR'
    previousSearch.disabled = nextSearch.disabled = !searchMatches.length || searchLoading
    for (const [pageId, node] of pageNodes) {
      node.querySelector('.pdf-search-overlays')?.remove()
      const holder = node.querySelector<HTMLElement>('.pdf-page-content'), page = state().find(item => item.pageId === pageId)
      if (!holder?.querySelector('canvas') || !page) continue
      const original = pagesCached.get(previewDocument ? state().findIndex(item => item.pageId === pageId) : page.index)
      if (!original) continue
      const view = displayViewport(original, page, scale), layer = documentElement('div', 'pdf-search-overlays')
      for (const [index, match] of searchMatches.entries()) if (match.pageId === pageId) for (const rect of match.rects) {
        const [x1, y1] = view.convertToViewportPoint(rect[0], rect[1]), [x2, y2] = view.convertToViewportPoint(rect[2], rect[3])
        const mark = documentElement('span', `pdf-search-match${index === searchPosition ? ' is-current' : ''}`)
        mark.dataset.matchIndex = String(index)
        Object.assign(mark.style, { left: `${Math.min(x1, x2)}px`, top: `${Math.min(y1, y2)}px`, width: `${Math.abs(x2 - x1)}px`, height: `${Math.abs(y2 - y1)}px` })
        layer.append(mark)
      }
      holder.append(layer)
    }
  }
  async function sourcePage(index: number) {
    if (!document) throw new Error('PDF 尚未载入')
    if (previewDocument) index = state().findIndex(page => page.index === index)
    let page = pagesCached.get(index)
    if (!page && !previewDocument && index >= model.pages.length) page = await blankSourcePage(index)
    if (!page) { page = await document.getPage(index + 1); pagesCached.set(index, page) }
    return page
  }
  // 草稿空白页没有来源页：按其尺寸生成最小单页 PDF 供 PDF.js 渲染；保存/实际预览由引擎写入真实页面。
  const blankDocuments = new Map<string, ReturnType<typeof getDocument>>()
  async function blankSourcePage(index: number) {
    const identity = state().find(page => page.blank && page.index === index)
    if (!identity) throw new Error('页面身份已过期，请重新打开文件')
    const key = `${identity.mediaBox.width}x${identity.mediaBox.height}`
    let loading = blankDocuments.get(key)
    if (!loading) { loading = getDocument({ data: blankPdfBytes(identity.mediaBox.width, identity.mediaBox.height), enableXfa: false }); blankDocuments.set(key, loading) }
    const page = await (await loading.promise).getPage(1)
    pagesCached.set(index, page)
    return page
  }
  function overlays(holder: HTMLElement, page: PdfPageIdentity, pdfViewport: ReturnType<PDFPageProxy['getViewport']>) {
    const layer = documentElement('div', 'pdf-draft-overlays')
    for (const operation of draft.operations.filter(op => op.pageId === page.pageId && ['addMarkup', 'removeMarkup', 'removeDrawing', 'highlight', 'addTextAnnotation', 'redact'].includes(op.kind))) {
      const type = operation.kind === 'redact' ? 'redaction' : ['removeMarkup', 'removeDrawing'].includes(operation.kind) ? 'removal' : operation.kind === 'addMarkup' ? String(operation.markupType) : operation.kind === 'highlight' ? 'highlight' : 'note'
      const rects = operation.kind === 'removeDrawing' ? (model.pages.find(item => item.pageId === page.pageId)?.drawings?.filter(item => item.annotationId === operation.annotationId).map(item => item.rect) ?? []) : operation.kind === 'removeMarkup' ? (model.pages.find(item => item.pageId === page.pageId)?.markups?.find(mark => mark.annotationId === operation.annotationId)?.quads ?? []).map(quadToRect) : operation.kind === 'addMarkup' ? (operation.quads as number[][]).map(quadToRect) : [operation.rect as PdfRect]
      for (const rect of rects) {
        const converted = [...pdfViewport.convertToViewportPoint(rect[0], rect[1]), ...pdfViewport.convertToViewportPoint(rect[2], rect[3])]
        const overlay = documentElement('span', type === 'highlight' ? 'pdf-highlight' : type === 'note' ? 'pdf-note' : `pdf-pending-markup pdf-${type}`)
        Object.assign(overlay.style, { left: `${Math.min(converted[0], converted[2])}px`, top: `${Math.min(converted[1], converted[3])}px`, width: `${Math.abs(converted[2] - converted[0])}px`, height: `${Math.abs(converted[3] - converted[1])}px` })
        const rgb = (operation.color as number[] | undefined)?.map(value => Math.round(value * 255)).join(',') ?? '255,217,0'
        overlay.style.color = `rgb(${rgb})`
        if (type === 'highlight') overlay.style.backgroundColor = `rgba(${rgb},.4)`
        if (type === 'squiggly') overlay.style.backgroundImage = `url("data:image/svg+xml,${encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' width='8' height='4'><path d='M0 2 Q2 0 4 2 T8 2' fill='none' stroke='rgb(${rgb})'/></svg>`)}")`
        if (type === 'redaction') { overlay.dataset.pdfRedaction = ''; overlay.title = '待应用涂黑：保存后永久移除该区域内容' }
        if (type === 'removal') { overlay.style.outline = '2px dashed #c33'; overlay.title = '待移除标注；校验当前修改可查看实际结果' }
        if (type === 'note') { overlay.textContent = '▤'; overlay.title = String(operation.text) }
        layer.append(overlay)
      }
    }
    const stampsOp = draft.operations.find(op => op.kind === 'setStamps') as { images: string[]; stamps: { pageId: string; image: number; rect: number[]; opacity?: number }[] } | undefined
    const pageStamps = stampsOp?.stamps.filter(stamp => stamp.pageId === page.pageId) ?? []
    if (pageStamps.length) {
      // 位图按 PDF user space 放置：经页面视口矩阵变换，并在矩形内翻转 y 轴，旋转页同样准确。
      const svgNs = 'http://www.w3.org/2000/svg'
      const svg = window.document.createElementNS(svgNs, 'svg')
      svg.setAttribute('class', 'pdf-pending-drawings pdf-pending-stamps'); svg.setAttribute('width', String(pdfViewport.width)); svg.setAttribute('height', String(pdfViewport.height))
      const group = window.document.createElementNS(svgNs, 'g'); group.setAttribute('transform', `matrix(${pdfViewport.transform.join(' ')})`)
      for (const stamp of pageStamps) {
        const [x1, y1, x2, y2] = stamp.rect as [number, number, number, number]
        const image = window.document.createElementNS(svgNs, 'image')
        image.setAttribute('href', `data:image/png;base64,${stampsOp!.images[stamp.image]}`)
        image.setAttribute('x', String(x1)); image.setAttribute('y', String(-y2)); image.setAttribute('width', String(x2 - x1)); image.setAttribute('height', String(y2 - y1))
        image.setAttribute('transform', 'scale(1 -1)'); image.setAttribute('preserveAspectRatio', 'none'); image.setAttribute('opacity', String(stamp.opacity ?? 1))
        image.dataset.pdfStamp = 'true'
        group.append(image)
      }
      svg.append(group); layer.append(svg)
    }
    if (draft.operations.some(op => op.pageId === page.pageId && op.kind === 'addDrawing')) {
      const source = document, sourceGeneration = generation, snapshot = JSON.stringify(draft.operations)
      const controller = mountDrawingCanvas({ host: layer, pages: model.pages, pageId: page.pageId, operations: draft.operations, viewport: pdfViewport, scale,
        current: () => source === document && sourceGeneration === generation && mode === 'select' && canChangePendingDrawings() && !pendingDrawingDialog?.open,
        unchanged: () => snapshot === JSON.stringify(draft.operations),
        selected: () => selectedPendingDrawing,
        select(reference) { activeId = page.pageId; selectedPendingDrawing = reference; updateControls() },
        commit(operations) { draft.setOperations(operations); selectedPendingDrawing = undefined; void refresh().catch(showError) }, error: showError,
      })
      drawingCanvases.add(controller)
    }
    const source=document,sourceGeneration=generation
    formCanvases.add(mountPdfFormCanvas({editor:root,host:layer,pageId:page.pageId,viewport:pdfViewport,model:()=>model,operations:()=>draft.operations,
      current:()=>source===document&&sourceGeneration===generation&&mode==='select'&&pagesCached.get(page.index)?.userUnit===1&&root.querySelector('[data-pdf-ribbon-tab="formDesign"]')?.getAttribute('aria-selected')==='true'&&formCanvasCurrent(),
      selected:()=>selectedFormWidget,
      select(selection){selectedFormWidget=selection;if(selection){activeId=selection.pageId;for(const node of pageNodes.values())node.classList.toggle('is-active',node.dataset.pageId===activeId)}syncFormCanvases()},
      commit(operations){draft.setOperations(operations);void refresh().catch(showError)},error:showError,
    }))
    holder.append(layer); syncDrawingCanvases()
  }
  async function renderPage(page: PdfPageIdentity, holder: HTMLElement, renderGeneration: number) {
    const original = await sourcePage(page.index)
    if (disposed || renderGeneration !== generation || !visible.has(page.pageId)) return
    const pdfViewport = displayViewport(original, page, scale)
    const dpr = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(MAX_PAGE_PIXELS / (pdfViewport.width * pdfViewport.height)))
    const canvas = documentElement('canvas')
    canvas.width = Math.max(1, Math.floor(pdfViewport.width * dpr)); canvas.height = Math.max(1, Math.floor(pdfViewport.height * dpr))
    canvas.style.width = `${pdfViewport.width}px`; canvas.style.height = `${pdfViewport.height}px`
    const task = original.render({ canvas, viewport: pdfViewport, annotationMode: AnnotationMode.ENABLE, transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0] })
    tasks.add(task)
    try { await task.promise } finally { tasks.delete(task) }
    if (disposed || renderGeneration !== generation || !visible.has(page.pageId)) return
    const textContainer = documentElement('div', 'textLayer')
    holder.replaceChildren(canvas, textContainer)
    const textLayer = new TextLayer({ textContentSource: original.streamTextContent(), container: textContainer, viewport: pdfViewport })
    textLayers.add(textLayer)
    try { await textLayer.render() } finally { textLayers.delete(textLayer) }
    if (disposed || renderGeneration !== generation || !visible.has(page.pageId) || !holder.contains(canvas)) return
    markSearch(); if (!previewDocument) overlays(holder, page, pdfViewport)
    let start: [number, number] | undefined
    let stroke: number[][] = []
    const toPdf = (clientX: number, clientY: number) => { const bounds = holder.getBoundingClientRect(); return pdfViewport.convertToPdfPoint((clientX - bounds.left) * pdfViewport.width / bounds.width, (clientY - bounds.top) * pdfViewport.height / bounds.height) }
    holder.onpointerdown = event => {
      if (mode === 'staticText') {
        if (event.button !== 0 || event.isPrimary === false) return
        event.preventDefault()
        void staticText?.place(page.pageId, toPdf(event.clientX, event.clientY)).catch(showError)
        return
      }
      if (mode === 'select' || mode === 'text' || locked || previewing || previewDocument || !response.editingEnabled || draft.closed) return
      event.preventDefault(); start = [event.clientX, event.clientY]; stroke = [toPdf(event.clientX, event.clientY)]; holder.setPointerCapture?.(event.pointerId)
    }
    holder.ondblclick = event => {
      if (mode !== 'draw' || drawShape !== 'polygon' || !polygonDraft || polygonDraft.pageId !== page.pageId) return
      event.preventDefault()
      try { polygonDraft.finish() } catch (error) { cancelPolygon(); showError(error) }
    }
    holder.onpointermove = event => {
      if (!start || mode !== 'draw' || drawShape !== 'ink' || stroke.length >= 2000) return
      stroke.push(toPdf(event.clientX, event.clientY))
    }
    holder.onpointerup = event => {
      if (!start || locked || previewing || previewDocument || draft.closed) return
      const begin = start; start = undefined
      try {
        if (mode === 'draw' && drawShape === 'polygon') {
          if (page.blank) throw new Error('新插入的空白页请先保存并重新打开后再绘图')
          const vertex = toPdf(event.clientX, event.clientY)
          if (!polygonDraft || polygonDraft.pageId !== page.pageId) {
            cancelPolygon()
            const draftPolygon = { pageId: page.pageId, vertices: [] as number[][], preview: undefined as SVGElement | undefined, finish: () => {
              const vertices = draftPolygon.vertices
              cancelPolygon()
              const operation = pdfDrawingOperation(page.pageId, 'polygon', vertices, page.cropBox, drawColor)
              pdfPageState(model.pages, [...draft.operations, operation])
              void append(operation).catch(showError)
            } }
            polygonDraft = draftPolygon
          }
          const last = polygonDraft.vertices.at(-1)
          if (!last || Math.hypot(vertex[0]! - last[0]!, vertex[1]! - last[1]!) >= 2) polygonDraft.vertices.push(vertex)
          polygonDraft.preview?.remove()
          const svgNs = 'http://www.w3.org/2000/svg'
          const preview = window.document.createElementNS(svgNs, 'svg')
          preview.setAttribute('class', 'pdf-pending-drawings pdf-polygon-progress'); preview.setAttribute('width', String(pdfViewport.width)); preview.setAttribute('height', String(pdfViewport.height))
          const line = window.document.createElementNS(svgNs, 'polyline')
          line.setAttribute('points', polygonDraft.vertices.map(item => pdfViewport.convertToViewportPoint(item[0]!, item[1]!).join(',')).join(' '))
          line.setAttribute('stroke', `rgb(${drawColor.map(value => Math.round(value * 255)).join(',')})`); line.setAttribute('fill', 'none'); line.setAttribute('stroke-dasharray', '4 3'); line.setAttribute('stroke-width', '2')
          preview.append(line); holder.append(preview); polygonDraft.preview = preview
          status.textContent = `多边形已放置 ${polygonDraft.vertices.length} 个顶点；双击或按 Enter 完成，Esc 取消`
        } else if (mode === 'draw') {
          const points = drawShape === 'ink' ? [...stroke, toPdf(event.clientX, event.clientY)] : [toPdf(...begin), toPdf(event.clientX, event.clientY)]
          stroke = []
          if (page.blank) throw new Error('新插入的空白页请先保存并重新打开后再绘图')
          if ((drawShape as string) === 'signature') {
            if (!pendingSignature) throw new Error('请先点击“签名”书写签名')
            // 笔迹按签名板比例放入拖出的屏幕区域，再经页面视口逆变换到 PDF 坐标（旋转页同样正确）。
            const left = Math.min(begin[0], event.clientX), top = Math.min(begin[1], event.clientY)
            const width = Math.abs(event.clientX - begin[0]), height = Math.abs(event.clientY - begin[1])
            if (width < 4 || height < 4) throw new Error('请拖出更大的签名区域')
            const fit = Math.min(width / SIGN_PAD.width, height / SIGN_PAD.height)
            const offsetX = left + (width - SIGN_PAD.width * fit) / 2, offsetY = top + (height - SIGN_PAD.height * fit) / 2
            const clamp = (value: number[]) => [Math.min(page.cropBox.x + page.cropBox.width, Math.max(page.cropBox.x, value[0]!)), Math.min(page.cropBox.y + page.cropBox.height, Math.max(page.cropBox.y, value[1]!))].map(item => Math.round(item * 100) / 100)
            const paths = pendingSignature.paths.map(path => { const out: number[] = []; for (let index = 0; index < path.length; index += 2) out.push(...clamp(toPdf(offsetX + path[index]! * fit, offsetY + path[index + 1]! * fit))); return out })
            const operation: NativeOperation = { kind: 'addDrawing', pageId: page.pageId, shape: 'ink', paths, color: [...SIGN_COLOR], width: 2 }
            pdfPageState(model.pages, [...draft.operations, operation])
            pendingSignature = undefined; setMode('select')
            void append(operation).catch(showError)
            return
          }
          if (drawShape === 'image') {
            if (!pendingImage) throw new Error('请先点击“插入图像”选择图像')
            const operation = pdfDrawingOperation(page.pageId, 'image', points, page.cropBox, drawColor, { image: pendingImage })
            pdfPageState(model.pages, [...draft.operations, operation])
            pendingImage = ''; setMode('select')
            void append(operation).catch(showError)
            return
          }
          if (drawShape === 'link') {
            pdfDrawingOperation(page.pageId, 'link', points, page.cropBox, drawColor, { url: 'https://validate.invalid' })
            linkPending = { page, points }; linkUrl.value = ''; linkPage.value = ''; linkError.textContent = ''
            linkPageText.textContent = `或跳转到本文档第几页（1–${state().length}）`
            linkDialog.showModal(); linkUrl.focus()
            return
          }
          if (drawShape === 'measure') {
            const line = pdfDrawingOperation(page.pageId, 'measure', points, page.cropBox, drawColor, { label: '0' })
            if (measureScale && !measureRecalibrate) { commitMeasure(page, line, measureScale, original.userUnit); return }
            measurePending = { page, operation: line, snapshot: JSON.stringify(draft.operations), doc: document, userUnit: original.userUnit }; measureValue.value = ''; measureError.textContent = ''
            measureHint.textContent = `参考线长 ${pdfLineLength(line.from as number[], line.to as number[], original.userUnit).toFixed(1)} pt；输入它代表的实际长度。`
            measureDialog.showModal(); measureValue.focus()
            return
          }
          const operation = pdfDrawingOperation(page.pageId, drawShape, points, page.cropBox, drawColor)
          pdfPageState(model.pages, [...draft.operations, operation])
          void append(operation).catch(showError)
        } else if (mode === 'redact') {
          if (page.blank) throw new Error('新插入的空白页请先保存并重新打开后再涂黑')
          const operation = pdfRedactionOperation(page.pageId, pdfRectFromClient(pdfViewport, holder.getBoundingClientRect(), begin, [event.clientX, event.clientY], page.cropBox), page.cropBox)
          pdfPageState(model.pages, [...draft.operations, operation])
          void append(operation).catch(showError)
        } else if (mode === 'highlight') {
          const rect = pdfRectFromClient(pdfViewport, holder.getBoundingClientRect(), begin, [event.clientX, event.clientY], page.cropBox)
          void append({ kind: 'highlight', pageId: page.pageId, rect, color: markupColor }).catch(showError)
        } else if (mode === 'note') {
          const content = noteInput.value.trim()
          if (!content) throw new Error('请先输入批注内容，再点击页面')
          const bounds = holder.getBoundingClientRect()
          const point = pdfViewport.convertToPdfPoint((event.clientX - bounds.left) * pdfViewport.width / bounds.width, (event.clientY - bounds.top) * pdfViewport.height / bounds.height)
          void append({ kind: 'addTextAnnotation', pageId: page.pageId, rect: stickyNoteRect(point, page.cropBox), text: content, createdMs: Date.now() }).catch(showError)
        }
      } catch (error) { showError(error) }
    }
  }
  function activeTextObject(): PdfTextObject | undefined {
    return model.pages.find(page => page.pageId === activeId)?.textObjects?.find(item => item.objectId === selectedTextId && item.text.trim())
  }
  function notifyTextSelection() {
    const target = activeTextObject()
    const selected = target && mode === 'text' && !previewDocument ? [{ pageId: activeId, objectId: target.objectId }] : []
    reportedSelectionPage = selected.length ? activeId : ''
    onSelectionChange?.(selected)
  }
  function fillReplacement() {
    const target = activeTextObject()
    originalText.textContent = target ? `原文：${target.text}` : '本页没有可直接编辑的文字对象。'
    replacement.value = target ? String(draft.operations.find(op => op.kind === 'replaceText' && op.objectId === target.objectId)?.newText ?? target.text) : ''
    replacementStyle.fill(target?draft.operations.find(op=>op.kind==='replaceText'&&op.objectId===target.objectId):undefined)
    replacement.hidden = stageText.hidden = !target
  }
  function renderFormControls(fields: PdfFormField[]) {
    const key = JSON.stringify([fields,model.capabilities?.createFormField,draft.operations.filter(operation => operation.kind === 'setFormValue')])
    if (key === formControlsKey) return
    formControlsKey = key
    formControls.replaceChildren()
    const editableFields = fields.filter(field => field.editable && ['text', 'checkbox', 'radio', 'choice'].includes(field.kind))
    previousField.disabled = nextField.disabled = editableFields.length === 0
    for (const field of fields) {
      const label = documentElement('label', 'pdf-form-field')
      const title = documentElement('span'); title.textContent = field.name; label.append(title)
      const staged = draft.operations.find(op => op.kind === 'setFormValue' && op.name === field.name)
      const value = staged ? staged.value : field.value
      let control: HTMLInputElement | HTMLSelectElement
      if (field.kind === 'checkbox') {
        const checkbox = documentElement('input'); checkbox.type = 'checkbox'; checkbox.checked = Boolean(staged ? staged.checked : field.value); control = checkbox
      } else if (field.kind === 'radio' || field.kind === 'choice') {
        const select = documentElement('select')
        const empty = documentElement('option'); empty.value = ''; empty.textContent = '未选择'; select.append(empty)
        for (const optionValue of field.options ?? []) { const option = documentElement('option'); option.value = optionValue; option.textContent = optionValue; select.append(option) }
        select.value = typeof value === 'string' ? value : ''; control = select
      } else {
        const input = documentElement('input'); input.type = 'text'; input.value = typeof value === 'string' ? value : ''; input.maxLength = 4000; control = input
      }
      control.disabled = !field.editable || locked || previewing || !!previewDocument || !response.editingEnabled || draft.closed
      control.dataset.pdfEditable = String(field.editable)
      control.setAttribute('aria-label', field.name)
      if (field.editable) control.addEventListener('change', () => {
        if(disposed||locked||previewing||previewDocument||printing||!response.editingEnabled||draft.closed||draft.saving||control.disabled||draft.operations.some(op=>PDF_EXCLUSIVE_DRAFT_KINDS.includes(op.kind)))return
        const operation: NativeOperation = { kind: 'setFormValue', fieldId: field.fieldId, expectedFieldSha256: field.expectedFieldSha256, name: field.name, fieldKind: field.kind,
          ...(field.kind === 'checkbox' ? { checked: (control as HTMLInputElement).checked } : { value: control.value }) }
        const candidate=[...draft.operations.filter(op => !(op.kind === 'setFormValue' && op.name === field.name)), operation]
        try{pdfPageState(model.pages,candidate);draft.setOperations(candidate)}catch(error){showError(error);return}
        void refresh().catch(showError)
      })
      label.append(control); formControls.append(label)
    }
    ribbon.setHasForms(fields.length > 0,model.capabilities?.createFormField===true)
    if (!editableFields.length && fields.length) { const note = documentElement('p'); note.textContent = '检测到表单字段，但当前字段均为只读或暂不支持。'; formControls.append(note) }
  }
  function focusFormField(direction: -1 | 1) {
    const fields = [...formControls.querySelectorAll<HTMLInputElement | HTMLSelectElement>('[data-pdf-editable="true"]')]
      .filter(field => !field.disabled)
    if (!fields.length) return
    const current = fields.indexOf(window.document.activeElement as HTMLInputElement | HTMLSelectElement)
    const next = current < 0 ? (direction > 0 ? 0 : fields.length - 1) : (current + direction + fields.length) % fields.length
    fields[next]?.focus()
  }
  function renderTextPanel(force = false) {
    textPanel.hidden = !textEnabled || mode !== 'text' || !!previewDocument
    if (textPanel.hidden) return
    if (force || textSelectionPage !== activeId) {
      if (reportedSelectionPage && reportedSelectionPage !== activeId) { reportedSelectionPage = ''; onSelectionChange?.([]) }
      textSelectionPage = activeId; textObjects.replaceChildren()
      const objects = model.pages.find(page => page.pageId === activeId)?.textObjects?.filter(item => item.text.trim()) ?? []
      for (const object of objects) { const option = documentElement('option'); option.value = object.objectId; option.textContent = object.text.length > 100 ? `${object.text.slice(0,100)}…` : object.text; textObjects.append(option) }
      if (!objects.some(item => item.objectId === selectedTextId)) selectedTextId = objects[0]?.objectId ?? ''
      textObjects.value = selectedTextId; textObjects.hidden = !objects.length; fillReplacement()
      if (force && objects.length) notifyTextSelection()
    }
  }
  function hasUnstagedText() {
    const target = activeTextObject()
    if(textPanel.hidden||!target)return false
    const staged=draft.operations.find(op=>op.kind==='replaceText'&&op.objectId===target.objectId)
    try{return replacement.value!==String(staged?.newText??target.text)||replacementStyle.changed(staged)}catch{return true}
  }
  function staticTextUnavailable(): string | null {
    if (!textEnabled) return 'PDF 文字编辑尚未开放'
    if (disposed || !document || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed || draft.saving) return '当前修订无法插入文字，请先退出预览或保存'
    if (hasUnstagedText()) return '请先完成当前文字编辑'
    if (model.capabilities?.insertText !== true) return model.capabilities?.insertTextReason || '当前来源暂不支持静态文字插入'
    if (draft.operations.length) return PDF_STATIC_TEXT_ALONE_REASON
    return null
  }
  function formDesignUnavailable(): string | null {
    if (disposed || !document || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed || draft.saving) return '当前修订无法设计字段，请先退出预览或保存'
    if (hasUnstagedText()) return '请先完成当前文字编辑'
    if (model.capabilities?.removeFormWidget !== true) return '当前来源没有可安全删除的独立单控件字段'
    if (draft.operations.length && !draft.operations.every(op => op.kind === 'removeFormWidget')) return '删除表单控件须单独保存，请先保存或撤销其他修改'
    return null
  }
  function objectDesignUnavailable():string|null{
    if(disposed||!document||locked||previewing||printing||previewDocument||!response.editingEnabled||draft.closed||draft.saving)return '当前修订无法编辑对象，请先退出预览或保存'
    if(staticText?.incompleteReason())return staticText.incompleteReason()
    if(hasUnstagedText())return '请先完成当前文字编辑'
    if(draft.operations.length)return '对象设计须单独保存，请先保存或撤销其他修改'
    return null
  }
  function formCanvasCurrent(){
    return !disposed&&!!document&&!locked&&!previewing&&!printing&&!previewDocument&&response.editingEnabled&&!draft.closed&&!draft.saving&&model.sourceSha256===draft.identity.sourceSha256&&!staticText?.incompleteReason()&&!hasUnstagedText()
  }
  function existingImageUnavailable():string|null{return objectDesignUnavailable()??(model.capabilities?.editExistingImage===true?null:model.capabilities?.editExistingImageReason||'当前来源没有可编辑的已有图像')}
  async function rebuildTextIndex() {
    const version = ++indexGeneration, indexedDocument = document
    if (!indexedDocument) return
    searchLoading = true; searchIndex = []; searchMatches = []; markSearch()
    const ids = (previewDocument ? state() : model.pages).map(page => page.pageId)
    try {
      const index = await searchCache.get(indexedDocument)
      if (disposed || version !== indexGeneration || document !== indexedDocument) return
      searchIndex = index; searchPageIds = ids; searchLoading = false; runSearch(true)
    } catch (error) {
      if (!disposed && version === indexGeneration) { searchLoading = false; searchCount.textContent = '搜索索引读取失败'; throw error }
    }
  }
  async function leavePreview() {
    selectedFormWidget=undefined;clearFormCanvases()
    clearDrawingCanvases()
    readingReady = false
    for (const task of tasks) task.cancel()
    for (const layer of textLayers) layer.cancel()
    commentsGeneration++; pendingCommentJump = null; selectedComment = ''; clearAttachments()
    generation++; indexGeneration++; observer?.disconnect(); visible.clear(); tasks.clear(); textLayers.clear()
    document = sourceDocument; previewDocument = undefined; layoutPreviewPages = undefined; pagesCached.clear()
    if (sourceReadingBeforePreview) { pendingReadingRestore = sourceReadingBeforePreview; readingRestoresSelection = true }
    commentRoots = []; commentsRead = commentsFailed = 0; commentsLoading = sidebar === 'comments'; renderComments()
    const loading = previewLoading; previewLoading = undefined; await loading?.destroy()
    backToSource.hidden = true; root.dataset.pdfPreview = 'false'
  }
  function operationLabel(operation: NativeOperation, index: number) {
    const labels: Record<string, string> = { transformExistingImage:'编辑已有图像',createFormField:'创建表单字段',editFormFieldRequired:'修改字段必填属性',editFormWidget:'修改字段属性',arrangeFormWidgets:'排列字段',appendRadioWidget:'追加单选选项',editFormTextProperties:'修改文本字段属性', insertText: '插入文字', replaceText: '原位改字', highlight: '高亮', addTextAnnotation: '文字批注', rotatePage: '旋转', deletePage: '删页', addMarkup: '文字标注', removeMarkup: '移除已保存标注', removeDrawing: '删除已保存绘图', removeFormWidget: '删除表单字段', editNote: '编辑便签', removeNote: '删除便签', reorderPages: '页面重排', cropPage: '裁切页面', setPageSize: '页面尺寸', addAttachment: '新增附件', removeAttachment: '移除附件', replyNote: '便签回复', replyPendingNote: '待保存便签回复', insertBlankPage: '插入空白页', addDrawing: '绘图/链接', setStamps: '水印与页眉页脚', redact: '涂黑', mergePages: '合并页面', splitPages: '拆分页面' }
    return `第 ${index + 1} 项 · ${labels[operation.kind] ?? operation.kind}${operation.kind === 'replaceText' ? `：${String(operation.newText).slice(0,120) || '删除文字'}` : ''}`
  }
  function skipReason(reason: string) {
    if (/identity|located|match/i.test(reason)) return '无法唯一定位原文字对象，已保留原文'
    if (/overflow|multiline/i.test(reason)) return '替换超出原行、页面或会与其他文字重叠，已保留原文'
    if (/font|characters|glyph/i.test(reason)) return '当前字体无法完整显示替换文字，已保留原文'
    return reason
  }
  async function previewDraft() {
    const incomplete = staticText?.incompleteReason() ?? existingImagePanel?.incompleteReason(); if (incomplete) throw new Error(incomplete)
    if (hasUnstagedText()) throw new Error('请先点击“加入文字修改”，再生成预览或保存')
    if (previewing || locked || draft.closed) throw new Error('正在处理 PDF，请稍后重试')
    const operations = structuredClone(draft.operations), key = JSON.stringify(operations)
    if (!previewDocument) { saveReading(); sourceReadingBeforePreview = capturePdfReading(viewport, model.pages.map(page => page.pageId), scale, fitMode) }
    previewing = true; updateControls(); status.textContent = '正在生成实际 PDF 预览…'
    try {
      const result = await api.preview<PdfModel>({ expectedSha256: context.sourceFile.sha256, operations }, abort.signal)
      if (result.sourceSha256 !== context.sourceFile.sha256 || key !== JSON.stringify(draft.operations)) throw new Error('草稿或文件来源已变化，请重新预览')
      if (!result.reviewIssues?.length && !operations.some(op => ['addMarkup', 'removeMarkup', 'removeDrawing', 'removeFormWidget', 'insertText', ...PDF_OBJECT_DESIGN_KINDS, 'editNote', 'removeNote', 'addTextAnnotation', 'replaceText', 'cropPage', 'setPageSize', 'addAttachment', 'removeAttachment', 'replyNote', 'replyPendingNote', 'insertBlankPage', 'addDrawing', 'setStamps', 'redact', 'mergePages', 'splitPages'].includes(op.kind))) { status.textContent = `当前 ${operations.length} 项修改已校验；保存后仍需核验业务内容。`; return }
      if (!result.previewDigest) throw new Error('服务端未返回 PDF 预览确认摘要')
      const bytes = await api.previewFile({ expectedSha256: context.sourceFile.sha256, operations, expectedPreviewDigest: result.previewDigest }, abort.signal)
      if (key !== JSON.stringify(draft.operations)) throw new Error('草稿已变化，请重新预览')
      await leavePreview()
      layoutPreviewPages = operations.some(op => op.kind === 'mergePages' || op.kind === 'splitPages') ? result.model.pages : undefined
      previewLoading = getDocument({ data: new Uint8Array(bytes), cMapUrl: `${ASSET_BASE}cmaps/`, cMapPacked: true, standardFontDataUrl: `${ASSET_BASE}standard_fonts/`, wasmUrl: `${ASSET_BASE}wasm/`, enableXfa: false })
      previewDocument = await previewLoading.promise
      if (previewDocument.numPages !== state().length) throw new Error('实际 PDF 预览页数不匹配，请重新预览')
      document = previewDocument; pagesCached.clear()
      mode = 'select'; setMode('select'); backToSource.hidden = false; root.dataset.pdfPreview = 'true'
      review.stage(operations, result.previewDigest); reviewList.replaceChildren()
      const skips = result.skippedOperations ?? [], applied = result.appliedOperationIndices ?? [], reviewIssues = result.reviewIssues ?? []
      for (const index of applied) { const item = documentElement('li'); item.textContent = `已执行：${operationLabel(operations[index], index)}`; reviewList.append(item) }
      for (const skipped of skips) {
        const item = documentElement('li'); item.className = 'pdf-skipped-operation'
        const insert = operations[skipped.operationIndex]?.kind !== 'replaceText'||operations.some(isStyledPdfReplacement)
        item.textContent = `${insert ? '执行或复核告警，请以实际 PDF 为准' : '未执行，保留原文'}：${operationLabel(operations[skipped.operationIndex], skipped.operationIndex)}；${insert ? skipped.reason : skipReason(skipped.reason)}`
        item.title = skipped.reason; reviewList.append(item)
      }
      for (const issue of reviewIssues) {
        const item = documentElement('li'); item.className = 'pdf-review-issue'
        item.textContent = `内容或版式复核告警：${issue.message}`
        item.title = issue.code; reviewList.append(item)
      }
      confirmText.textContent = reviewIssues.length || operations.some(op => op.kind === 'insertText'||PDF_OBJECT_DESIGN_KINDS.includes(op.kind)||isStyledPdfReplacement(op))
        ? `我已核对实际 PDF 预览，确认保存；${applied.length} 项已执行，${skips.length} 项执行或复核告警（以实际 PDF 为准）`
        : `我已核对实际 PDF 预览，确认保存 ${applied.length} 项已执行修改及 ${skips.length} 项未执行修改（保留原文）`
      if (reviewIssues.length) confirmText.textContent += `；${reviewIssues.length} 项内容或版式复核告警`
      confirmPreview.checked = false; reviewPanel.hidden = !reviewIssues.length && !operations.some(op => PDF_REVIEW_KINDS.includes(op.kind))
      await rebuildTextIndex(); await refresh()
    } catch (error) {
      review.reset(); reviewPanel.hidden = true; confirmPreview.checked = false
      await leavePreview(); await refresh()
      throw error
    } finally { previewing = false; updateControls(); scheduleFit() }
  }
  async function prepareSave(): Promise<{ confirmedPreviewDigest?: string }> {
    const incomplete = staticText?.incompleteReason() ?? existingImagePanel?.incompleteReason(); if (incomplete) throw new Error(incomplete)
    if (hasUnstagedText()) throw new Error('请先点击“加入文字修改”，再预览并保存')
    if (!draft.operations.some(op => PDF_REVIEW_KINDS.includes(op.kind))) return {}
    if (previewing) throw new Error('正在生成实际 PDF 预览，请稍后保存')
    const confirmedPreviewDigest = review.confirmedDigest(draft.operations)
    if (confirmedPreviewDigest) return { confirmedPreviewDigest }
    if (!review.isPrepared(draft.operations)) await previewDraft()
    reviewPanel.scrollIntoView({ block: 'nearest' })
    throw new Error('请核对实际 PDF 预览与未执行清单，勾选确认后再次保存')
  }
  function thumbnailForPage(original: PDFPageProxy, page: PdfPageIdentity) {
    const doc = document!
    let entries = thumbnailCache.get(doc)
    if (!entries) { entries = new Map(); thumbnailCache.set(doc,entries) }
    const style = getComputedStyle(thumbs), px = (value: string) => Number.parseFloat(value) || 0
    const width = Math.max(1,committedSidebarWidth-px(style.paddingLeft)-px(style.paddingRight)-px(style.borderLeftWidth)-px(style.borderRightWidth))
    const unit = displayViewport(original,page,1), dpr = Math.min(2,window.devicePixelRatio||1)
    const initialScale = width/unit.width*dpr
    const factor = Math.min(1,16384/(unit.width*initialScale),16384/(unit.height*initialScale),Math.sqrt(4_000_000/(unit.width*unit.height*initialScale**2)))
    const view = displayViewport(original,page,initialScale*factor)
    const key = JSON.stringify([page.cropBox,page.rotation,Math.ceil(view.width),Math.ceil(view.height)])
    const previous = entries.get(page.pageId)
    if (previous?.key === key) return previous
    previous?.hide()
    const canvas = documentElement('canvas'); canvas.width = canvas.height = 1; canvas.style.aspectRatio = `${view.width} / ${view.height}`
    const entry: PdfThumbnailEntry = {key,canvas,loaded:false,wanted:false,show(){entry.wanted=true;draw()},hide(){entry.wanted=false;entry.loaded=false;entry.task?.cancel();canvas.width=canvas.height=1}}
    entries.set(page.pageId,entry)
    const draw = () => {
      if (disposed || doc !== document || !canvas.isConnected || !entry.wanted || entry.loaded || entry.task || entries!.get(page.pageId)!==entry) return
      entry.loaded=true;canvas.width=Math.ceil(view.width);canvas.height=Math.ceil(view.height)
      const context=canvas.getContext('2d');if(!context)return
      const task=original.render({canvas,canvasContext:context,viewport:view,annotationMode:AnnotationMode.ENABLE});entry.task=task;thumbnailTasks.add(task)
      void task.promise.catch(error=>{
        if(error instanceof Error&&error.name==='RenderingCancelledException')entry.loaded=false
        else if(!disposed&&doc===document&&entries!.get(page.pageId)===entry)showError(error)
      }).finally(()=>{entry.task=undefined;thumbnailTasks.delete(task);if(entry.wanted&&!entry.loaded)draw()})
    }
    return entry
  }
  async function refresh() {
    if (disposed || !document) return
    clearFormCanvases()
    clearDrawingCanvases()
    if (readingReady && !previewDocument && !previewing && !pendingReadingRestore) { pendingReadingRestore = capturePdfReading(viewport, model.pages.map(page => page.pageId), scale, fitMode); if (pendingReadingRestore) lastStableReading = pendingReadingRestore; readingRestoresSelection = false }
    searchRendering = true
    commentsGeneration++; clearAttachments()
    if (sidebar === 'comments') { commentRoots = []; commentsRead = commentsFailed = 0; commentsLoading = true; renderComments() }
    const structureKey = JSON.stringify(draft.operations.filter(op => !['addMarkup', 'removeMarkup', 'removeDrawing'].includes(op.kind)))
    if (markupStructureKey !== structureKey) { markupStructureKey = structureKey; markupSelection = [] }
    const operationsKey = JSON.stringify(draft.operations)
    if (lastOperationsKey !== operationsKey) { lastOperationsKey = operationsKey; textSelectionPage = '' }
    review.invalidate(draft.operations)
    renderFormControls(model.formFields ?? [])
    if (!review.isPrepared(draft.operations)) {
      reviewPanel.hidden = true; confirmPreview.checked = false
      if (previewDocument) { await leavePreview(); await rebuildTextIndex() }
    }
    const renderGeneration = ++generation
    if (!previewDocument && pendingReadingRestore) {
      const saved = pendingReadingRestore
      const readingPageId = state().find(page => page.index === Math.min(model.pages.length - 1, Math.max(0, saved.page - 1)))?.pageId ?? state()[0].pageId
      if (readingRestoresSelection) activeId = readingPageId
      if (!state().some(page => page.pageId === activeId)) activeId = state()[0].pageId
      fitMode = saved.fitMode; scale = clampPdfZoom(saved.scale)
      // Fit values depend on the reopened viewport; resolve source dimensions
      // before rendering rather than invoking a second concurrent refresh.
      const page = state().find(page => page.pageId === activeId)!
      await sourcePage(page.index)
      if (disposed || renderGeneration !== generation) return
      syncZoomControls()
    }
    if (fitMode) {
      for (const page of state()) { await sourcePage(page.index); if (disposed || renderGeneration !== generation) return }
      scale = fittedScale(fitMode) ?? scale; syncZoomControls()
    }
    if (thumbnailDocument !== document) { if (thumbnailDocument) for (const entry of thumbnailCache.get(thumbnailDocument)?.values() ?? []) entry.hide(); thumbnailDocument = document }
    const retainedThumbnailIds = new Set(state().map(page => page.pageId))
    for (const [id,entry] of thumbnailCache.get(document!) ?? []) if (!retainedThumbnailIds.has(id)) { entry.hide(); thumbnailCache.get(document!)!.delete(id) }
    thumbnailObserver?.disconnect(); thumbnailSlots = new Map()
    thumbnailObserver = typeof IntersectionObserver === 'undefined' ? undefined : new IntersectionObserver(entries => {
      if (disposed || renderGeneration !== generation) return
      for (const item of entries) { const entry = thumbnailSlots.get(item.target); if (entry) { if (item.isIntersecting) entry.show(); else entry.hide() } }
    }, { root: thumbs, rootMargin: '300px' })
    observer?.disconnect()
    for (const task of tasks) task.cancel()
    for (const layer of textLayers) layer.cancel()
    tasks.clear(); textLayers.clear(); visible.clear(); pageNodes.clear()
    viewport.replaceChildren(); thumbs.replaceChildren(); outlinePanel.replaceChildren()
    const pages = state()
    const rowByPosition = new Map<number, HTMLElement>()
    for (const indices of spreadRows(pages.map((_, index) => index), twoPageView ? 2 : 1)) {
      const row = documentElement('div', 'pdf-page-row'); viewport.append(row)
      for (const index of indices) rowByPosition.set(index, row)
    }
    const pendingOperations = draft.operations, pendingSnapshot = JSON.stringify(pendingOperations)
    if (!pages.some(page => page.pageId === activeId)) activeId = pages[0].pageId
    const render = (pageId: string) => {
      const page = pages.find(item => item.pageId === pageId), node = pageNodes.get(pageId)
      if (page && node) void renderPage(page, node.querySelector<HTMLElement>('.pdf-page-content')!, renderGeneration).catch(error => { if (renderGeneration === generation && !(error instanceof Error && error.name === 'RenderingCancelledException')) showError(error) })
    }
    observer = typeof IntersectionObserver === 'undefined' ? undefined : new IntersectionObserver(entries => {
      for (const entry of entries) {
        const id = (entry.target as HTMLElement).dataset.pageId!
        if (entry.isIntersecting) { visible.add(id); render(id) }
        else { visible.delete(id); entry.target.querySelector('.pdf-page-content')?.replaceChildren() }
      }
    }, { root: viewport, rootMargin: '600px' })
    for (const [position, page] of pages.entries()) {
      const original = await sourcePage(page.index)
      if (disposed || renderGeneration !== generation) return
      const dimensions = displayViewport(original, page, scale)
      const card = documentElement('section', 'pdf-page'); card.dataset.pageId = page.pageId; card.style.width = `${dimensions.width}px`; card.style.boxSizing = 'content-box'
      card.setAttribute('aria-label', `第 ${position + 1} 页`)
      const heading = documentElement('button', 'pdf-page-label'); heading.type = 'button'; heading.textContent = page.blank ? `第 ${position + 1} 页（新插入的空白页，保存后写入）` : layoutPreviewPages && previewDocument ? `第 ${position + 1} 页（重排版预览）` : `第 ${position + 1} 页（原第 ${page.index + 1} 页）`
      const content = documentElement('div', 'pdf-page-content'); content.style.width = `${dimensions.width}px`; content.style.height = `${dimensions.height}px`
      heading.addEventListener('click', () => { activeId = page.pageId; updateControls(); renderTextPanel(); for (const node of pageNodes.values()) node.classList.toggle('is-active', node === card) })
      card.addEventListener('pointerdown', () => { activeId = page.pageId; updateControls(); renderTextPanel() })
      card.append(heading, content)
      let comments = page.notes ?? []
      if (previewDocument || (!page.notesReadSafe && !comments.length)) comments = (await annotationCache.get(document!, previewDocument ? pages.findIndex(item => item.pageId === page.pageId) : page.index).catch(() => [])).filter(item => item.subtype === 'Text' && item.contentsObj?.str).map((item, index) => ({ annotationId: `readonly:${index}`, expectedAnnotationSha256: '', contents: item.contentsObj?.str ?? '', editable: false, removable: false, removalReason: '当前便签来源身份未完整读取，仅可查看' }))
      if (comments.length || draft.operations.some(op => op.pageId === page.pageId && ['editNote', 'removeNote'].includes(op.kind))) {
        const details = documentElement('details', 'pdf-saved-comments'), summary = documentElement('summary')
        summary.textContent = `${previewDocument ? '预览批注' : '已保存批注'}（${comments.length}）`; details.append(summary)
        details.open = draft.operations.some(op => op.pageId === page.pageId && ['editNote', 'removeNote'].includes(op.kind))
        for (const comment of comments) {
          const article = documentElement('article', 'pdf-saved-note'); article.dataset.noteId = comment.annotationId
          const text = documentElement('p'); text.textContent = comment.contents; article.append(text)
          const pendingReply = draft.operations.some(op => op.kind === 'replyNote' && op.annotationId === comment.annotationId)
          const canEdit = response.editingEnabled && !draft.closed && !locked && !previewing && !previewDocument && model.capabilities?.notes === true && page.notesReadSafe && comment.editable && !pendingReply && (comment.parentAnnotationId === undefined || model.capabilities?.savedReplyEdits === true)
          for (const [label, action] of [['编辑便签', () => editSavedNote(page.pageId, comment)], ['删除便签', () => changeSavedNote(page.pageId, comment.annotationId, null)]] as const) {
            const control = documentElement('button', 'pdf-tool'); control.type = 'button'; control.textContent = label; control.disabled = !canEdit; control.dataset.pdfNoteEditable = String(model.capabilities?.notes === true && page.notesReadSafe === true && comment.editable && !pendingReply && (comment.parentAnnotationId === undefined || model.capabilities?.savedReplyEdits === true))
            control.title = canEdit ? label : pendingReply ? '请先保存或取消此便签的回复' : comment.removalReason || '当前修订、预览或引擎不支持编辑已有便签'
            control.addEventListener('click', () => { void Promise.resolve().then(action).catch(showError) }); article.append(control)
          }
          details.append(article)
        }
        if (details.open && !previewDocument) { const pending = documentElement('p'); pending.textContent = '便签修改待保存；校验当前修改可查看实际 PDF。'; details.append(pending) }
        card.append(details)
      }
      if (!previewDocument) {
        const pendingNotes = pendingOperations.map((operation, index) => ({ operation, index })).filter(({ operation }) => operation.kind === 'addTextAnnotation' && operation.pageId === page.pageId)
        if (pendingNotes.length) {
          const details = documentElement('details', 'pdf-pending-comments'), summary = documentElement('summary')
          summary.textContent = `待保存便签（${pendingNotes.length}）`; details.open = true; details.append(summary)
          for (const { operation, index } of pendingNotes) {
            const reference: PendingPdfNoteReference = { index, snapshot: pendingSnapshot }
            const article = documentElement('article', 'pdf-pending-note'); article.dataset.operationIndex = String(index)
            const text = documentElement('p'); text.textContent = String(operation.text); article.append(text)
            for (const [label, action] of [['编辑便签', () => editNoteContents(String(operation.text), value => changePendingNote(reference, value))], ['删除便签', () => changePendingNote(reference, null)]] as const) {
              const control = documentElement('button', 'pdf-tool'); control.type = 'button'; control.textContent = label; control.dataset.pdfNoteEditable = 'true'
              control.disabled = locked || previewing || printing || !response.editingEnabled || draft.closed
              control.title = label
              control.addEventListener('click', () => { void Promise.resolve().then(action).catch(showError) }); article.append(control)
            }
            details.append(article)
          }
          card.append(details)
        }
      }
      rowByPosition.get(position)!.append(card); pageNodes.set(page.pageId, card)
      card.classList.toggle('is-active', activeId === page.pageId)
      if (observer) observer.observe(card)
      else { visible.add(page.pageId); render(page.pageId) }
      const thumbnail = documentElement('button', 'pdf-thumbnail'); thumbnail.type = 'button'; thumbnail.setAttribute('aria-label', `跳转第 ${position + 1} 页`)
      const thumbEntry = thumbnailForPage(original,page), thumbCanvas = thumbEntry.canvas
      const label = documentElement('span'); label.textContent = `${position + 1}`; thumbnail.append(thumbCanvas, label)
      thumbnail.addEventListener('click', () => { activeId = page.pageId; card.scrollIntoView({ block: 'start', behavior: 'smooth' }); updateControls(); renderTextPanel() })
      thumbs.append(thumbnail); thumbnailSlots.set(thumbCanvas,thumbEntry); if (thumbnailObserver) thumbnailObserver.observe(thumbCanvas); else thumbEntry.show()
    }
    for (const item of outline.filter(entry => pages.some(page => page.index === entry.pageIndex))) {
      const page = pages.find(candidate => candidate.index === item.pageIndex)!
      const link = documentElement('button', 'pdf-outline-link'); link.type = 'button'; link.textContent = item.title
      link.style.paddingInlineStart = `${8 + item.depth * 14}px`
      link.addEventListener('click', () => jumpToPageForIdentity(page.pageId))
      outlinePanel.append(link)
    }
    if (pendingCommentJump) pendingZoomAnchor = null
    const zoomOwnsPosition = !!pendingZoomAnchor
    if (pendingZoomAnchor) { restorePdfZoomAnchor(viewport, pendingZoomAnchor, scale); pendingZoomAnchor = null }
    status.textContent = previewDocument ? '正在显示实际写回的 PDF 预览；请核对执行结果与告警。返回原稿后可继续调整。' : draft.persistenceError ?? (draft.dirty ? `有 ${draft.operations.length} 项未保存修改；保存会创建新修订。` : response.editingEnabled ? `选择页面文字可添加或切换本次高亮、下划线、波浪线和删除线；文字批注为便签。${textEnabled ? '原位改字需核对实际预览后保存。' : '原位改字尚未开放。'}` : '当前为只读，原生编辑尚未开放；可下载文件。')
    if (textLoadWarning) status.textContent += ` ${textLoadWarning}`
    if (!previewDocument && pendingReadingRestore) {
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
      if (disposed || renderGeneration !== generation) return
      if (pendingReadingRestore && !zoomOwnsPosition && !pendingZoomAnchor && !pendingCommentJump && !searchJumpPending) {
        const pageId = restorePdfReading(viewport, model.pages.map(page => page.pageId), pendingReadingRestore)
        if (pageId && readingRestoresSelection) activeId = pageId
      }
      pendingReadingRestore = null; sourceReadingBeforePreview = null; readingRestoresSelection = false
    }
    readingReady = true; scheduleReading(); scheduleFit()
    searchRendering = false; if (pendingCommentJump) { pendingZoomAnchor = null; jumpComment() }; if (sidebar === 'comments') void loadComments(); if (sidebar === 'attachments') void loadAttachments(); runSearch(false, false); renderTextPanel(); updateControls(); onDraftChange?.()
  }
  setMode('select')
  updateControls()
  status.textContent = '正在读取 PDF…'
  const file = await api.file(abort.signal)
  const actualSha256 = await bytesSha256(new Uint8Array(file))
  if (actualSha256 !== context.sourceFile.sha256) throw new Error('PDF 来源摘要不匹配')
  const model: PdfModel = { sourceSha256: actualSha256, pageCount: 0, pages: [] }
  formDesignPanel = bindPdfFormDesignPanel({ root, draft, model: () => model, unavailable: formDesignUnavailable, refresh })
  root.insertBefore(formDesignPanel.element, layout)
  formCreatePanel=bindPdfFormCreatePanel({root,draft,model:()=>model,activePageId:()=>activeId,unavailable:objectDesignUnavailable,refresh});root.insertBefore(formCreatePanel.element,layout)
  textPropertiesPanel=bindPdfFormTextPropertiesPanel({root,draft,model:()=>model,unavailable:objectDesignUnavailable,refresh});root.insertBefore(textPropertiesPanel.element,layout)
  radioExtensionPanel=bindPdfRadioExtensionPanel({root,draft,model:()=>model,activePageId:()=>activeId,unavailable:objectDesignUnavailable,refresh});root.insertBefore(radioExtensionPanel.element,layout)
  existingImagePanel=bindPdfExistingImagePanel({root,draft,pages:()=>model.pages,images:()=>model.existingImages??[],unavailable:existingImageUnavailable,refresh,status:text=>{status.textContent=text}})
  staticText = bindPdfStaticText({ root, draft, pages: () => model.pages, unavailable: staticTextUnavailable, start: () => setMode('staticText'), stop: () => { if (mode === 'staticText') { mode = 'select'; root.dataset.pdfMode = 'select' } }, refresh, status: text => { status.textContent = text } })
  const loading = getDocument({ data: new Uint8Array(file), cMapUrl: `${ASSET_BASE}cmaps/`, cMapPacked: true, standardFontDataUrl: `${ASSET_BASE}standard_fonts/`, wasmUrl: `${ASSET_BASE}wasm/`, enableXfa: false })
  document = await loading.promise
  sourceDocument = document
  const metadata = await document.getMetadata()
  const info = metadata.info as Record<string, unknown>
  const propertyRows: [string, unknown][] = [
    ['Title', info.Title ?? metadata.metadata?.get('dc:title')],
    ['Author', info.Author ?? metadata.metadata?.get('dc:creator')],
    ['Subject', info.Subject ?? metadata.metadata?.get('dc:description')],
    ['Keywords', info.Keywords],
    ['Creator', info.Creator],
    ['Producer', info.Producer],
    ['Creation Date', info.CreationDate],
    ['Modified Date', info.ModDate],
    ['Pages', document.numPages],
    ['File Size', `${file.byteLength} bytes`],
  ]
  for (const [name, value] of propertyRows) {
    const term = documentElement('dt'); term.textContent = name
    const detail = documentElement('dd'); detail.textContent = value == null || value === '' ? '—' : String(value)
    detail.dataset.property = name
    propertiesList.append(term, detail)
  }
  model.pageCount = document.numPages
  for (let index = 0; index < document.numPages; index++) {
    const page = await document.getPage(index + 1)
    status.textContent = `正在读取 PDF 页面 ${index + 1} / ${document.numPages}…`
    pagesCached.set(index, page)
    const [x, y, right, top] = page.view
    const box = { x, y, width: right - x, height: top - y }
    model.pages.push({ pageId: `sha256:${actualSha256}:page:${index}`, index, mediaBox: box, cropBox: box, rotation: page.rotate })
  }
  try {
    outline = await resolvePdfOutline(await document.getOutline() ?? [], document)
    outlineToggle.disabled = outline.length === 0
    if (!outline.length) outlineToggle.title = '此 PDF 没有可导航的目录大纲'
  } catch {
    outline = []
    outlineToggle.disabled = true
    outlineToggle.title = 'PDF 目录大纲无法解析'
  }
  if (!model.pages.length) throw new Error('PDF 没有可显示页面')
  activeId = model.pages[0].pageId
  if (response.editingEnabled) {
    try {
      const sourceModel = await api.preview<PdfModel>({ expectedSha256: actualSha256, operations: [] }, abort.signal)
      if (sourceModel.sourceSha256 !== actualSha256 || sourceModel.model.sourceSha256 !== actualSha256) throw new Error('PDF 字段与文字对象来源不匹配')
      model.attachments = sourceModel.model.attachments ?? []
      model.attachmentsEditable = sourceModel.model.attachmentsEditable === true
      model.attachmentsReason = sourceModel.model.attachmentsReason
      if (model.attachmentsEditable !== true) attachmentNotice.textContent = `${model.attachmentsReason || '当前来源附件仅可查看和下载'}。删除附件目录不能擦除敏感数据。`
      model.capabilities = sourceModel.model.capabilities
      for (const page of model.pages) { const source = sourceModel.model.pages.find(item => item.pageId === page.pageId); page.markups = source?.markups ?? []; page.markupReadSafe = source?.markupReadSafe === true; page.notes = source?.notes ?? []; page.notesReadSafe = source?.notesReadSafe === true; page.drawings = source?.drawings ?? []; page.drawingsReadSafe = source?.drawingsReadSafe === true }
      model.formFields = sourceModel.model.formFields ?? []
      model.formDesignWidgets = sourceModel.model.formDesignWidgets ?? []
      model.existingImages=sourceModel.model.existingImages??[]
      renderFormControls(model.formFields)
      if (textEnabled) {
        for (const page of model.pages) {
          const sourcePage = sourceModel.model.pages.find(item => item.pageId === page.pageId)
          if (!sourcePage) throw new Error('PDF 文字对象页面身份不匹配')
          page.textObjects = sourcePage.textObjects ?? []
        }
        textLoaded = true
      }
    } catch (error) { textLoadWarning = `原位改字暂不可用，仍可查看、标注与下载 PDF：${error instanceof Error ? error.message : '文字对象读取失败'}` }
  }
  if (draft.operations.some(operation => ['editNote', 'removeNote'].includes(operation.kind)) && model.capabilities?.notes !== true) throw new Error('当前引擎未确认已有便签修改能力；原草稿已保留')
  if (draft.operations.some(operation => operation.kind === 'removeDrawing') && model.capabilities?.removeDrawing !== true) throw new Error('当前引擎未确认绘图删除能力；原草稿已保留')
  if (draft.operations.some(operation => operation.kind === 'insertText') && model.capabilities?.insertText !== true) throw new Error('当前引擎未确认插入文字能力；原草稿已保留')
  if (draft.operations.some(operation => operation.kind === 'removeFormWidget') && model.capabilities?.removeFormWidget !== true) throw new Error('当前引擎未确认表单控件删除能力；原草稿已保留')
  for(const operation of draft.operations.filter(op=>op.kind==='removeFormWidget')){
    if(operation.sourceSha256!==actualSha256)throw new Error('字段删除来源已变化；原草稿已保留')
    const expected=stagePdfFormWidgetRemoval(model,[],String(operation.widgetIdentity))[0]
    if(['fieldName','widgetId','expectedWidgetSha256'].some(key=>operation[key]!==expected[key]))throw new Error('字段删除控件身份已变化；原草稿已保留')
  }
  for(const[kind,capability]of [['transformExistingImage','editExistingImage'],['createFormField','createFormField'],['editFormFieldRequired','editFormFieldRequired'],['editFormWidget','editFormWidget'],['arrangeFormWidgets','arrangeFormWidgets'],['appendRadioWidget','appendRadioWidget'],['editFormTextProperties','editFormTextProperties']]as const){
    if(draft.operations.some(op=>op.kind===kind)&&model.capabilities?.[capability]!==true)throw new Error('当前引擎未确认对象设计能力；原草稿已保留')
  }
  validateRestoredPdfFormCreation(model,draft.operations)
  validateRestoredPdfRadioExtension(model,draft.operations)
  validateRestoredPdfFormTextProperties(model,draft.operations)
  validatePdfExistingImage(model.pages,draft.operations,model.existingImages)
  for(const operation of draft.operations.filter(op=>['createFormField','editFormFieldRequired'].includes(op.kind))){
    if(operation.sourceSha256!==actualSha256)throw new Error('字段设计来源已变化；原草稿已保留')
    if(operation.kind==='createFormField'){
      const {kind,sourceSha256,...input}=operation
      stagePdfFormCreation(model,[],input as unknown as PdfFormCreation)
    }else{
      const expected=stagePdfFormRequired(model,[],String(operation.widgetIdentity),operation.required as boolean)[0]
      if(['fieldName','widgetId','expectedWidgetSha256'].some(key=>operation[key]!==expected[key]))throw new Error('字段设计控件身份已变化；原草稿已保留')
    }
  }
  if (draft.operations.some(operation => operation.kind === 'removeMarkup') && model.capabilities?.removeMarkup !== true) throw new Error('当前引擎未确认已保存标注移除能力；原草稿已保留')
  for(const operation of draft.operations.filter(op=>['editFormWidget','arrangeFormWidgets'].includes(op.kind))){
    if(operation.sourceSha256!==actualSha256)throw new Error('字段设计来源已变化；原草稿已保留')
    if(operation.kind==='editFormWidget'){
      const target={fieldName:operation.fieldName,widgetId:operation.widgetId,widgetIdentity:operation.widgetIdentity,expectedWidgetSha256:operation.expectedWidgetSha256} as Parameters<typeof stagePdfFormWidgetProperties>[2]
      stagePdfFormWidgetProperties(model,[],target,{...(operation.rect!==undefined?{rect:operation.rect as [number,number,number,number]}:{}),...(operation.required!==undefined?{required:operation.required as boolean}:{}),...(operation.newFieldName!==undefined?{newFieldName:operation.newFieldName as string}:{}),...(operation.choiceOptions!==undefined?{choiceOptions:operation.choiceOptions as string[]}:{})})
    }else stagePdfFormWidgetArrangement(model,[],operation.targets as Parameters<typeof stagePdfFormWidgetArrangement>[2],operation.alignment as Parameters<typeof stagePdfFormWidgetArrangement>[3])
  }
  if (model.capabilities?.savedReplyEdits !== true && draft.operations.some(op => ['editNote','removeNote'].includes(op.kind) && model.pages.some(page => page.notes?.some(note => note.annotationId === op.annotationId && note.parentAnnotationId !== undefined)))) throw new Error('当前引擎未确认已保存回复修改能力；原草稿已保留')
  if (draft.operations.some(op => op.kind === 'replyPendingNote') && model.capabilities?.pendingNoteReplies !== true) throw new Error('当前来源或引擎未确认草稿回复写回能力；原草稿已保留')
  if (draft.operations.some(op => op.kind === 'replyNote') && model.capabilities?.noteReplies !== true) throw new Error('当前引擎未确认回复写回能力；原草稿已保留')
  if (draft.operations.some(isAttachmentEdit)) attachmentEditState(model, draft.operations)
  if (draft.operations.some(operation => operation.kind === 'setPageSize') && model.capabilities?.pageSize !== true) throw new Error('当前来源未确认尺寸变更能力；原草稿已保留')
  if (draft.operations.some(operation => operation.kind === 'cropPage') && model.capabilities?.cropPage !== true) throw new Error('当前 PDF 引擎未确认裁切能力；原草稿已保留')
  void rebuildTextIndex().catch(showError)
  pendingReadingRestore = loadViewState(readingKey, readingStorage); readingRestoresSelection = !!pendingReadingRestore
  locked = false
  await refresh()
  if (response.pdfReadAIEnabled) {
    pdfAssistant = bindNativePDFAssistant(root, { api, draft,
      selection: () => textSelectionPage && selectedTextId ? [{ pageId: textSelectionPage, objectId: selectedTextId }] : [],
      onNavigate: pageId => jumpToPageForIdentity(pageId),
    })
  }
  if(response.pdfFormAIEnabled&&response.editingEnabled){
    const {bindNativePDFFormAI}=await import('./native-pdf-form-ai')
    pdfFormAI=bindNativePDFFormAI(root,{api,draft,fields:()=>model.formFields??[],view:{refresh},canEdit:()=>!locked&&!previewing&&!printing&&response.editingEnabled,onDraftChange:()=>onDraftChange?.()})
  }
  if (response.pdfReviewAIEnabled) {
    pdfReview = bindNativePDFReview(root, {api, draft, view:{refresh},
      canEdit: () => !locked && !previewing && !printing && response.editingEnabled,
      onDraftChange: () => onDraftChange?.(),
    })
  }
  const {mountPdfTaskDock}=await import('./pdf-ai-dock')
  const pdfAIDock=mountPdfTaskDock(root,layout,{read:pdfAssistant,review:pdfReview,forms:pdfFormAI})
  return { refresh, prepareSave, setSaving(saving) { locked = saving; updateControls() }, dispose() {
    selectedFormWidget=undefined;clearFormCanvases()
    pdfAIDock.dispose();replacementStyle.dispose(); imageExport.dispose(); officeConversion.dispose(); textExport.dispose()
    staticText?.dispose(); textPropertiesPanel?.dispose(); radioExtensionPanel?.dispose(); existingImagePanel?.dispose(); formCreatePanel?.dispose(); formDesignPanel?.dispose(); extraction.dispose(); externalPages.dispose(); protection.dispose(); clearCropCanvas(); pdfFormAI?.dispose(); pdfReview?.dispose(); pdfAssistant?.dispose(); clearDrawingCanvases(); pendingDrawingDialog?.close(); saveReading(); if (readingTimer !== undefined) window.clearTimeout(readingTimer); disposed = true; sidebarSizing.dispose(); thumbnailObserver?.disconnect(); for (const entry of thumbnailSlots.values()) entry.hide(); thumbnailSlots.clear(); if (sidebarRasterFrame !== undefined) cancelAnimationFrame(sidebarRasterFrame); for (const task of thumbnailTasks) task.cancel(); thumbnailTasks.clear(); if (fitFrame !== undefined) cancelAnimationFrame(fitFrame); fitObserver?.disconnect(); attachmentsGeneration++; attachmentCache.clear(); for (const [url, timer] of attachmentDownloads) { window.clearTimeout(timer); URL.revokeObjectURL(url) }; attachmentDownloads.clear(); commentsGeneration++; annotationCache.clear(); if (searchTimer !== undefined) window.clearTimeout(searchTimer); searchCache.clear(); indexGeneration++; cleanupPrint(); onSelectionChange?.([]); abort.abort(); observer?.disconnect(); for (const task of tasks) task.cancel(); for (const layer of textLayers) layer.cancel(); void loading.destroy(); void previewLoading?.destroy(); ribbon.dispose(); root.replaceChildren()
  } }
}
