/** PDF.js canvas/text-layer hosting follows GenOffice PdfPage.tsx at 4b55db9.
 * Desktop IPC is replaced by the native API; original source page IDs stay authoritative.
 */
import { AnnotationMode, GlobalWorkerOptions, TextLayer, getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs'
import type { PDFDocumentProxy, PDFDocumentLoadingTask, PDFPageProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import 'pdfjs-dist/web/pdf_viewer.css'
import './pdf.css'
import './pdf-ribbon.css'
import type { NativeContextResponse, createNativeApi } from './native-api'
import { NativeDraft, type NativeOperation } from './native-draft'
import type { EditorShell } from './shell'
import { bytesSha256 } from './source-validation'
import { PDF_PAPER_SIZES, setPdfPageSize, cropAllPdfPages, cropPdfPage, pdfCropFromMargins, pdfPageViewport, deletePdfPage, movePdfPage, pdfCanPrint, pdfPageState, pdfPrintPages, pdfRectFromClient, renderPdfPrintHost, reversePdfPages, rotateAllPdfPages, stickyNoteRect, PdfPreviewReview, type PdfFormField, type PdfTextObject, type PdfModel, type PdfPageIdentity, type PdfRect } from './pdf-operations'
import { createPdfRibbon } from './pdf-ribbon'
import { PDF_PAGE_RIBBON_GROUPS } from './pdf-page-ribbon'
import { PDF_HOME_READ_ONLY_COMMANDS } from './pdf-home-ribbon'
import { PDF_VIEW_RIBBON_GROUPS, resolvePdfOutline, type ResolvedPdfOutlineItem } from './pdf-view-ribbon'
import { createPdfRibbonIcon, type PdfRibbonIconName } from './pdf-ribbon-icons'
import { pdfRibbonLabel } from './pdf-ribbon-locales'

import { MARKUP_COLORS, quadToRect, selectionQuadsByPage } from './genoffice-pdf-annotations'
import { PDF_MARKUP_TYPES, markupSelectionState, togglePdfMarkup, type MarkupType, type PdfMarkupSelection } from './pdf-markup'

GlobalWorkerOptions.workerSrc = workerUrl
const ASSET_BASE = '/reports/v1/editor/assets/pdfjs/'
const MAX_PAGE_PIXELS = 48_000_000
interface Options { api: ReturnType<typeof createNativeApi>; context: NativeContextResponse; draft: NativeDraft; onDraftChange?: () => void; onSelectionChange?: (selection: {pageId: string; objectId: string}[]) => void }
export interface PdfEditorHandle { setSaving(saving: boolean): void; refresh(): Promise<void>; dispose(): void; prepareSave(): Promise<{ confirmedPreviewDigest?: string }> }

export async function createPdfEditorView(shell: EditorShell, { api, context: response, draft, onDraftChange, onSelectionChange }: Options): Promise<PdfEditorHandle> {
  const root = shell.editor
  const context = response.context
  if (context.format !== 'pdf') throw new Error('文件格式不是 PDF')
  root.classList.add('native-pdf-editor')
  root.replaceChildren()
  const abort = new AbortController()
  let disposed = false, locked = true, generation = 0, document: PDFDocumentProxy | undefined
  let mode: 'select' | 'highlight' | 'note' | 'text' = 'select'
  const textEnabled = response.pdfTextEnabled === true && response.editingEnabled
  const review = new PdfPreviewReview()
  let previewing = false, previewDocument: PDFDocumentProxy | undefined, previewLoading: PDFDocumentLoadingTask | undefined
  let sourceDocument: PDFDocumentProxy | undefined, indexGeneration = 0
  let textLoaded = !textEnabled, textLoadWarning = ''
  let reportedSelectionPage = ''
  let textSelectionPage = '', selectedTextId = '', lastOperationsKey = JSON.stringify(draft.operations)
  let scale = 1
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
  const textIndex = new Map<string, string>()
  let observer: IntersectionObserver | undefined
  const visible = new Set<string>()
  let activeId = '', currentSearch = '', searchPosition = -1
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
  layout.append(thumbs, outlinePanel, viewport)
  const textPanel = documentElement('section', 'pdf-text-editor'); textPanel.hidden = true
  const textObjects = documentElement('select'); textObjects.setAttribute('aria-label', '待修改文字对象')
  const originalText = documentElement('p', 'pdf-original-text')
  const replacement = documentElement('textarea'); replacement.setAttribute('aria-label', '替换后的文字'); replacement.maxLength = 4000
  const stageText = documentElement('button'); stageText.type = 'button'; stageText.textContent = '加入文字修改'
  const textHelp = documentElement('p'); textHelp.textContent = '仅修改选中的原始文字对象；最多 4000 字符。请生成实际预览，核对未执行的修改后保存。'
  textPanel.append(textObjects, originalText, replacement, stageText, textHelp)
  const reviewPanel = documentElement('section', 'pdf-preview-review'); reviewPanel.hidden = true
  const reviewTitle = documentElement('p'); reviewTitle.textContent = '实际 PDF 预览与执行清单'
  const reviewList = documentElement('ul')
  const confirmLabel = documentElement('label'), confirmPreview = documentElement('input'); confirmPreview.type = 'checkbox'
  const confirmText = documentElement('span')
  confirmLabel.append(confirmPreview, confirmText); reviewPanel.append(reviewTitle, reviewList, confirmLabel)
  confirmPreview.addEventListener('change', () => { try { review.confirm(draft.operations, confirmPreview.checked) } catch (error) { confirmPreview.checked = false; showError(error) } })
  root.append(noteInput, textPanel, status, propertiesPanel, reviewPanel, layout)
  const editableButtons: HTMLButtonElement[] = []
  const pageInputs: HTMLInputElement[] = []
  function button(label: string, action: () => void | Promise<void>, editable = true, icon?: PdfRibbonIconName) {
    const element = documentElement('button', 'pdf-tool')
    element.type = 'button'
    if (icon) element.append(createPdfRibbonIcon(icon, 18))
    const text = documentElement('span'); text.textContent = pdfRibbonLabel(label); element.append(text)
    element.addEventListener('click', () => { void Promise.resolve().then(action).catch(showError) })
    commandGroup.append(element)
    if (editable) editableButtons.push(element)
    return element
  }
  const sourceCommand = (element: HTMLElement, id: string) => {
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
      action.setAttribute('aria-label', `${label}，${reason}`)
      group.append(action)
    }
  }
  unavailableSourceGroup('home', 'AI', [
    { id: 'home.ai.openAssistant', label: 'Genspark AI', reason: 'PDF 原生编辑上下文未接入通用 AI 助手面板' },
    { id: 'home.ai.summarize', label: 'AI 总结', reason: 'PDF 原生 AI 总结入口尚未绑定服务端 AI 任务' },
    { id: 'home.ai.keyPoints', label: 'AI 关键要点', reason: 'PDF 原生 AI 要点入口尚未绑定服务端 AI 任务' },
  ])
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
  unavailableSourceGroup('home', 'Edit', [
    { id: 'home.edit.insertText', label: '插入文字', reason: '原生 PDF 尚无可验证静态文字插入操作与输出复读' },
  ], homeEditGroup)
  commandGroup = ribbon.group('home', 'Convert & Export')
  const homeConvertGroup = commandGroup
  const downloads = documentElement('a', 'pdf-original-download')
  downloads.textContent = pdfRibbonLabel('下载当前 PDF'); downloads.href = `/reports/v1/native/${encodeURIComponent(context.documentId)}/${context.revision}/api/file`; downloads.download = 'report.pdf'
  sourceCommand(downloads, 'home.convert.downloadOriginal')
  commandGroup.append(downloads)
  unavailableSourceGroup('home', 'Convert & Export', [
    { id: 'home.convert.toWord', label: '转换为 Word', reason: '原生 PDF 转 Word 未接入授权输出与新修订登记' },
    { id: 'home.convert.toExcel', label: '转换为 Excel', reason: '原生 PDF 转 Excel 未接入授权输出与新修订登记' },
    { id: 'home.convert.toPowerPoint', label: '转换为演示文稿', reason: '原生 PDF 转演示文稿未接入授权输出与新修订登记' },
    { id: 'home.convert.toMarkdown', label: '转换为 Markdown', reason: '原生 PDF 转 Markdown 未接入授权输出与新修订登记' },
    { id: 'home.convert.toHtml', label: '转换为 HTML', reason: '原生 PDF 转 HTML 未接入授权输出与新修订登记' },
    { id: 'home.convert.exportImagesPng', label: '导出图像 PNG', reason: '页面图像导出尚未接入受控下载与文件身份登记' },
    { id: 'home.convert.exportImagesJpg', label: '导出图像 JPG', reason: '页面图像导出尚未接入受控下载与文件身份登记' },
  ], homeConvertGroup)
  commandGroup = ribbon.group('home', 'Page & Zoom')
  const homePageInput = createPageInput('home.pageZoom.goToPage')
  commandGroup.append(homePageInput.row)
  const homeZoom = documentElement('select', 'pdf-zoom')
  homeZoom.setAttribute('aria-label', '页面缩放')
  for (const value of [.5, .75, 1, 1.25, 1.5, 2]) { const option = documentElement('option'); option.value = String(value); option.textContent = `${value * 100}%`; homeZoom.append(option) }
  homeZoom.value = '1'; homeZoom.addEventListener('change', () => { scale = Number(homeZoom.value); void refresh().catch(showError) }); commandGroup.append(homeZoom)
  const fitScale = (mode: 'width' | 'page') => {
    const page = state().find(item => item.pageId === activeId)
    const original = page && pagesCached.get(previewDocument ? state().findIndex(item => item.index === page.index) : page.index)
    if (!page || !original) return
    const availableWidth = Math.max(1, viewport.clientWidth - 36)
    const availableHeight = Math.max(1, viewport.clientHeight - 36)
    const unit = displayViewport(original, page, 1)
    scale = Math.min(availableWidth / unit.width, mode === 'page' ? availableHeight / unit.height : Number.POSITIVE_INFINITY, 4)
    let option = [...homeZoom.options].find(item => Number(item.value) === scale)
    if (!option) { option = documentElement('option'); option.value = String(scale); option.textContent = `${Math.round(scale * 100)}%`; homeZoom.append(option) }
    homeZoom.value = option.value
    void refresh().catch(showError)
  }
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
  search.addEventListener('input', () => { currentSearch = search.value.trim(); searchPosition = -1; markSearch() })
  const stepSearch = async (direction: -1 | 1) => {
    if (!currentSearch) return
    const matches = state().filter(page => textIndex.get(page.pageId)?.includes(currentSearch.toLocaleLowerCase()))
    if (!matches.length) { status.textContent = '未找到匹配文字；扫描页需要 OCR 后才能搜索。'; return }
    searchPosition = (searchPosition + direction + matches.length) % matches.length
    const page = matches[searchPosition]
    pageNodes.get(page.pageId)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    activeId = page.pageId
    for (const node of pageNodes.values()) node.classList.toggle('is-active', node.dataset.pageId === activeId)
    updateControls(); renderTextPanel(true)
    status.textContent = `匹配页面 ${searchPosition + 1} / ${matches.length}`
  }
  const previousSearch = button('上一处', () => stepSearch(-1), false)
  sourceCommand(previousSearch, 'home.search.previousMatch')
  const nextSearch = button('下一处', () => stepSearch(1), false)
  sourceCommand(nextSearch, 'home.search.nextMatch')
  searchPrintGroup.append(previousSearch, nextSearch, printButton)
  const propertiesButton = button(PDF_HOME_READ_ONLY_COMMANDS[0].label, () => { propertiesPanel.hidden = !propertiesPanel.hidden }, false)
  sourceCommand(propertiesButton, 'home.properties.documentProperties')
  const toggleThumbnails = documentElement('button', 'pdf-tool'); toggleThumbnails.type = 'button'; toggleThumbnails.textContent = pdfRibbonLabel('缩略图'); toggleThumbnails.setAttribute('aria-pressed', 'true')
  toggleThumbnails.addEventListener('click', () => { thumbs.hidden = !thumbs.hidden; toggleThumbnails.setAttribute('aria-pressed', String(!thumbs.hidden)) })
  let outline: ResolvedPdfOutlineItem[] = []
  const viewNavigation = ribbon.group('view', 'Navigation')
  commandGroup = viewNavigation
  sourceCommand(toggleThumbnails, 'view.navigation.thumbnails')
  viewNavigation.append(toggleThumbnails)
  const focusSearch = button('搜索', () => search.focus(), false)
  sourceCommand(focusSearch, 'view.navigation.search')
  commandGroup = viewNavigation
  const outlineToggle = button('目录大纲', () => {
    outlinePanel.hidden = !outlinePanel.hidden
    outlineToggle.setAttribute('aria-pressed', String(!outlinePanel.hidden))
  }, false)
  sourceCommand(outlineToggle, 'view.navigation.outline')
  let twoPageView = false
  const pageSpreadToggle = button('双页视图', () => {
    twoPageView = !twoPageView
    viewport.dataset.spread = twoPageView ? 'two' : 'single'
    pageSpreadToggle.textContent = pdfRibbonLabel(twoPageView ? '单页视图' : '双页视图')
    pageSpreadToggle.setAttribute('aria-pressed', String(twoPageView))
  }, false)
  sourceCommand(pageSpreadToggle, 'view.navigation.pageSpread')
  unavailableSourceGroup('view', 'Navigation', PDF_VIEW_RIBBON_GROUPS[0].commands.filter(item => !item.enabled).map(item => ({ id: item.id.replace('genoffice.pdf.', ''), label: item.label, reason: item.reason! })), viewNavigation)
  const viewZoomGroup = ribbon.group('view', 'Page & Zoom')
  const viewPageInput = createPageInput('view.pageZoom.goToPage')
  viewZoomGroup.append(viewPageInput.row)
  commandGroup = viewZoomGroup
  const setZoom = (value: number) => {
    scale = Math.max(.25, Math.min(4, value))
    const option = [...homeZoom.options].find(item => Number(item.value) === scale)
    if (!option) { const added = documentElement('option'); added.value = String(scale); added.textContent = `${Math.round(scale * 100)}%`; homeZoom.append(added) }
    homeZoom.value = String(scale)
    void refresh().catch(showError)
  }
  const zoomOut = button('缩小', () => setZoom(scale / 1.2), false)
  const zoomIn = button('放大', () => setZoom(scale * 1.2), false)
  sourceCommand(zoomOut, 'view.pageZoom.zoomOut'); sourceCommand(zoomIn, 'view.pageZoom.zoomIn')
  const viewFitWidth = button('适合宽度', () => fitScale('width'), false)
  const viewFitPage = button('适合页面', () => fitScale('page'), false)
  sourceCommand(viewFitWidth, 'view.pageZoom.fitWidth'); sourceCommand(viewFitPage, 'view.pageZoom.fitPage')
  viewZoomGroup.append(zoomOut, zoomIn, viewFitWidth, viewFitPage)
  const formGroup = ribbon.group('fillForm', '填写可填写域')
  const formControls = documentElement('div', 'pdf-form-controls')
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
  unavailableGroup('fillForm', '静态表单', ['添加文本', '添加勾选', '添加叉号', '完成表单'], '静态表单填值尚未接入 PDF 写回契约')
  unavailableGroup('formDesign', '创建字段', ['文本字段', '日期字段', '复选框', '单选按钮', '下拉列表', '签名字段'], '字段创建尚未接入带来源身份及输出复读验证的 PDF 操作契约')
  unavailableGroup('formDesign', '设计、检测与排列', ['自动检测', '排列', '删除字段', '预览'], '现有 widget writer 仍有身份回退与跳过语义，安全桥接 schema/字段快照回读完成前保持禁用')
  unavailableSourceGroup('annotate', 'AI Review', [
    { id: 'annotate.aiReview.summary', label: 'AI 总结审阅', reason: 'PDF 原生 AI 审阅入口尚未绑定服务端审阅任务' },
    { id: 'annotate.aiReview.processNotes', label: 'AI 处理批注', reason: 'PDF 原生 AI 批注处理入口尚未绑定服务端审阅任务' },
  ])
  commandGroup = ribbon.group('annotate', 'Markup')
  const annotateMarkupGroup = commandGroup
  const select = button('选择文字', () => setMode('select'), false)
  for (const [type, label] of [['highlight', '高亮'], ['underline', '下划线'], ['squiggly', '波浪线'], ['strikeout', '删除线']] as const) selectionMarkupButton(type, label, `annotate.markup.${type}`)
  commandGroup.append(createMarkupPalette())
  const note = button('文字批注', () => setMode('note'), true, 'note')
  sourceCommand(note, 'annotate.drawTools.note')
  commandGroup = ribbon.group('annotate', 'Draw Tools')
  const annotateDrawGroup = commandGroup
  commandGroup.append(note)
  unavailableSourceGroup('annotate', 'Draw Tools', [
    { id: 'annotate.drawTools.ink', label: '手绘', reason: 'PDF 操作桥尚未实现笔迹路径写回及输出复读' },
    { id: 'annotate.drawTools.measure', label: '测量', reason: '原生视图尚未实现可校准比例与来源坐标绑定的测量工具' },
    { id: 'annotate.drawTools.rectangle', label: '矩形', reason: 'PDF 操作桥尚未实现矩形绘图身份与输出复读' },
    { id: 'annotate.drawTools.ellipse', label: '椭圆', reason: 'PDF 操作桥尚未实现椭圆绘图身份与输出复读' },
    { id: 'annotate.drawTools.arrow', label: '箭头', reason: 'PDF 操作桥尚未实现箭头绘图身份与输出复读' },
    { id: 'annotate.drawTools.polygon', label: '多边形', reason: 'PDF 操作桥尚未实现多边形路径写回及输出复读' },
    { id: 'annotate.drawTools.caret', label: '插入符号', reason: 'PDF 操作桥尚未实现插入符号标注写回及输出复读' },
    { id: 'annotate.drawTools.redact', label: '涂黑', reason: '安全涂黑需移除底层内容并独立验证，当前桥接尚未实现' },
    { id: 'annotate.drawTools.clearRedaction', label: '清除涂黑', reason: '当前编辑器不生成涂黑标记，不能提供清除动作' },
    { id: 'annotate.drawTools.applyRedaction', label: '应用涂黑', reason: '安全涂黑需移除底层内容并独立验证，当前桥接尚未实现' },
    { id: 'annotate.drawTools.color', label: '绘图颜色', reason: '当前仅支持高亮颜色；绘图操作及对应颜色写回尚未实现' },
  ], annotateDrawGroup)
  unavailableSourceGroup('annotate', 'Signature & Protection', [
    { id: 'annotate.signature.sign', label: '签名', reason: '签名图片写回和字段身份验证尚未接入' },
    { id: 'annotate.signature.certificateSign', label: '证书签名', reason: '证书签名需要独立密钥托管与签名服务，浏览器端不持有私钥' },
    { id: 'annotate.protection.protect', label: '保护 PDF', reason: '加密权限修改尚未接入新修订输出与权限复读' },
    { id: 'annotate.signature.signaturePanel', label: '数字签名面板', reason: '数字签名列表与验证状态尚未接入原生 PDF 服务' },
  ])
  const cropDialog = documentElement('dialog', 'pdf-crop-dialog')
  cropDialog.setAttribute('aria-label', '裁切当前页面')
  const cropTitle = documentElement('h3'); cropTitle.textContent = '裁切当前页面'
  const cropHelp = documentElement('p'); cropHelp.textContent = '按当前显示方向输入四边裁去的百分比。只隐藏边缘内容，文字、表单和批注仍保留；裁切不能用于删除敏感信息。'
  const cropError = documentElement('p', 'pdf-crop-error'); cropError.setAttribute('role', 'alert')
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
  cropFields.append(cropApply, cropCancel); cropDialog.append(cropTitle, cropHelp, cropError, cropFields); root.append(cropDialog)
  let cropPageId = ''
  cropCancel.addEventListener('click', () => cropDialog.close())
  cropApply.addEventListener('click', () => { void applyCrop().catch(error => { cropError.textContent = error instanceof Error ? error.message : String(error); showError(error) }) })
  async function openCrop() {
    if (draft.operations.some(op => op.kind === 'setPageSize') || cropApplying || !document || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed || model.capabilities?.cropPage !== true) return
    const page = state().find(item => item.pageId === activeId)
    if (!page) return
    cropError.textContent = ''; cropAll.checked = false; cropTitle.textContent = '裁切当前页面'; cropDialog.setAttribute('aria-label', cropTitle.textContent); cropAllText.textContent = `裁切全部保留页（${state().length} 页，各按当前显示方向和可见范围）`; cropPageId = page.pageId; cropInputs.forEach(input => { input.value = '0' })
    cropDialog.showModal()
  }
  async function applyCrop() {
    if (cropApplying || !cropDialog.open || locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed || model.capabilities?.cropPage !== true) return
    const page = state().find(item => item.pageId === cropPageId)
    if (!page) throw new Error('裁切目标页面已变化，请重新选择')
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
      draft.setOperations(next)
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
    if (draft.operations.some(op => ['cropPage', 'replaceText'].includes(op.kind))) return '请先保存裁切或原位改字并重开，再变更页面尺寸'
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
      draft.setOperations(setPdfPageSize(draft.operations, preset))
      sizeDialog.close(); await refresh(); await previewDraft()
    } finally { sizeApplying = false; updateControls() }
  }
  function displayViewport(original: PDFPageProxy, page: PdfPageIdentity, scale: number) {
    return previewDocument ? original.getViewport({ scale, rotation: page.rotation }) : pdfPageViewport(original, page, scale)
  }
  const pageButtons = new Map<string, HTMLButtonElement>()
  const pageActions: Record<string, () => void | Promise<void>> = {
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
  unavailableGroup('edit', '图像、链接与水印', ['插入图像', '编辑图像', '编辑链接', '水印'], '对象级图像、链接与水印写回尚未接入 PDF 操作契约')
  textObjects.addEventListener('change', () => { selectedTextId = textObjects.value; fillReplacement(); notifyTextSelection() })
  stageText.addEventListener('click', () => {
    if (locked || previewing || previewDocument || draft.closed || draft.operations.some(op => op.kind === 'setPageSize')) return
    const target = activeTextObject()
    if (!target) return
    try {
      const operations = draft.operations.filter(op => !(op.kind === 'replaceText' && op.objectId === target.objectId))
      if (replacement.value !== target.text) operations.push({ kind: 'replaceText', pageId: activeId, objectId: target.objectId, expectedTextSha256: target.expectedTextSha256, newText: replacement.value })
      draft.setOperations(operations); notifyTextSelection(); void refresh().catch(showError)
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
    markupSelection = [...quads].map(([index, selected]) => ({ pageId: pages[index].pageId, quads: selected, saved: pages[index].markups ?? [] }))
    updateControls()
  }
  window.document.addEventListener('selectionchange', captureMarkupSelection, { signal: abort.signal })
  viewport.addEventListener('pointerdown', () => { markupSelection = []; updateControls() })
  viewport.addEventListener('pointerup', captureMarkupSelection)
  async function applySelectedMarkup(type: MarkupType) {
    if (locked || previewing || printing || previewDocument || !response.editingEnabled || draft.closed || !model.capabilities?.selectionMarkup) return
    if (markupSelection.some(selection => !state().find(page => page.pageId === selection.pageId)?.markupReadSafe)) throw new Error('此页已有标注尚不能完整读取，原草稿已保留')
    const color = type === 'highlight' ? markupColor : MARKUP_COLORS[type]
    const next = togglePdfMarkup(markupSelection, draft.operations, type, color)
    pdfPageState(model.pages, next)
    draft.setOperations(next); await refresh()
  }
  function documentElement<K extends keyof HTMLElementTagNameMap>(tag: K, className = ''): HTMLElementTagNameMap[K] {
    const element = window.document.createElement(tag); element.className = className; return element
  }
  function showError(error: unknown) { if (!disposed) status.textContent = error instanceof Error ? error.message : 'PDF 操作失败，请重试' }
  function state() { return pdfPageState(model.pages, draft.operations) }
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
  function setMode(next: typeof mode) { mode = next; noteInput.hidden = mode !== 'note'; root.dataset.pdfMode = mode; if (mode !== 'text') { reportedSelectionPage = ''; onSelectionChange?.([]) }; textPanel.hidden = mode !== 'text' || !!previewDocument; for (const [button, value] of [[select, 'select'], [note, 'note']] as const) button.setAttribute('aria-pressed', String(mode === value)) }
  function updateControls() {
    for (const button of editableButtons) button.disabled = locked || previewing || printing || !!previewDocument || !response.editingEnabled || draft.closed
    sizeOptions.disabled = sizeApplying || locked || previewing || printing || !!previewDocument || !response.editingEnabled || draft.closed
    cropFields.disabled = cropApplying || locked || previewing || printing || !!previewDocument || !response.editingEnabled || draft.closed
    undo.disabled ||= !draft.canUndo; redo.disabled ||= !draft.canRedo
    noteInput.disabled = locked || previewing || !!previewDocument || !response.editingEnabled || draft.closed
    textObjects.disabled = replacement.disabled = stageText.disabled = draft.operations.some(op => op.kind === 'setPageSize') || locked || previewing || !!previewDocument || draft.closed
    for (const control of formControls.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select')) control.disabled = control.dataset.pdfEditable !== 'true' || locked || previewing || !!previewDocument || !response.editingEnabled || draft.closed
    if (textEditButton) textEditButton.disabled ||= !textLoaded
    previewButton.disabled = locked || previewing || !response.editingEnabled || draft.closed
    printButton.disabled = !pdfCanPrint({ loaded: !!document, locked, dirty: draft.dirty, previewing, printing, previewDocument: !!previewDocument })
    backToSource.disabled = locked || previewing
    confirmPreview.disabled = locked || previewing || draft.closed
    for (const input of pageInputs) input.disabled = !document
    zoomOut.disabled = zoomIn.disabled = viewFitWidth.disabled = viewFitPage.disabled = !document
    if (document) {
      const pages = state()
      const current = String(Math.max(1, pages.findIndex(page => page.pageId === activeId) + 1))
      for (const input of pageInputs) { input.max = String(pages.length); input.value = current }
      for (const total of root.querySelectorAll('.pdf-view-page-row span')) total.textContent = ` / ${pages.length}`
    }
    for (const id of ['genoffice.pdf.page.rotateLeft', 'genoffice.pdf.page.rotateRight']) pageButtons.get(id)!.disabled ||= !activeId
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
    for (const { button, type } of markupButtons) {
      const state = markupSelectionState(markupSelection, draft.operations, type)
      const savedRemoval = state.active && state.matches.some(match => match.saved)
      button.disabled ||= !document || model.capabilities?.selectionMarkup !== true || !markupSelection.length || markupSelection.some(selection => !model.pages.find(page => page.pageId === selection.pageId)?.markupReadSafe) || savedRemoval
      button.setAttribute('aria-pressed', String(state.active))
      button.title = !document ? '请先打开 PDF' : !response.editingEnabled || draft.closed ? '当前修订为只读' : model.capabilities?.selectionMarkup !== true ? '当前引擎未确认文字选区标注能力' : markupSelection.some(selection => !model.pages.find(page => page.pageId === selection.pageId)?.markupReadSafe) ? '此页已有文字标注尚不能完整读取' : savedRemoval ? '此选区已有保存的同类标注，移除尚未接通' : '选择页面文字后添加；再次点击可移除本次草稿标注'
    }
    status.dataset.dirty = String(draft.dirty)
  }
  async function append(operation: NativeOperation) {
    if (locked || previewing || previewDocument || !response.editingEnabled || draft.closed) return
    draft.setOperations([...draft.operations, operation]); await refresh()
  }
  function cleanupPrint() {
    if (printTimer !== undefined) window.clearTimeout(printTimer)
    printTimer = undefined
    printRoot?.remove(); printRoot = undefined; printing = false
    window.removeEventListener('afterprint', cleanupPrint)
    updateControls()
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
  function markSearch() {
    for (const node of viewport.querySelectorAll<HTMLSpanElement>('.textLayer span')) node.classList.toggle('pdf-search-hit', !!currentSearch && (node.textContent ?? '').toLocaleLowerCase().includes(currentSearch.toLocaleLowerCase()))
  }
  async function sourcePage(index: number) {
    if (!document) throw new Error('PDF 尚未载入')
    if (previewDocument) index = state().findIndex(page => page.index === index)
    let page = pagesCached.get(index)
    if (!page) { page = await document.getPage(index + 1); pagesCached.set(index, page) }
    return page
  }
  function overlays(holder: HTMLElement, page: PdfPageIdentity, pdfViewport: ReturnType<PDFPageProxy['getViewport']>) {
    const layer = documentElement('div', 'pdf-draft-overlays')
    for (const operation of draft.operations.filter(op => op.pageId === page.pageId && ['addMarkup', 'highlight', 'addTextAnnotation'].includes(op.kind))) {
      const type = operation.kind === 'addMarkup' ? String(operation.markupType) : operation.kind === 'highlight' ? 'highlight' : 'note'
      const rects = operation.kind === 'addMarkup' ? (operation.quads as number[][]).map(quadToRect) : [operation.rect as PdfRect]
      for (const rect of rects) {
        const converted = [...pdfViewport.convertToViewportPoint(rect[0], rect[1]), ...pdfViewport.convertToViewportPoint(rect[2], rect[3])]
        const overlay = documentElement('span', type === 'highlight' ? 'pdf-highlight' : type === 'note' ? 'pdf-note' : `pdf-pending-markup pdf-${type}`)
        Object.assign(overlay.style, { left: `${Math.min(converted[0], converted[2])}px`, top: `${Math.min(converted[1], converted[3])}px`, width: `${Math.abs(converted[2] - converted[0])}px`, height: `${Math.abs(converted[3] - converted[1])}px` })
        const rgb = (operation.color as number[] | undefined)?.map(value => Math.round(value * 255)).join(',') ?? '255,217,0'
        overlay.style.color = `rgb(${rgb})`
        if (type === 'highlight') overlay.style.backgroundColor = `rgba(${rgb},.4)`
        if (type === 'squiggly') overlay.style.backgroundImage = `url("data:image/svg+xml,${encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' width='8' height='4'><path d='M0 2 Q2 0 4 2 T8 2' fill='none' stroke='rgb(${rgb})'/></svg>`)}")`
        if (type === 'note') { overlay.textContent = '▤'; overlay.title = String(operation.text) }
        layer.append(overlay)
      }
    }
    holder.append(layer)
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
    if (disposed || renderGeneration !== generation) return
    markSearch(); if (!previewDocument) overlays(holder, page, pdfViewport)
    let start: [number, number] | undefined
    holder.onpointerdown = event => {
      if (mode === 'select' || mode === 'text' || locked || previewing || previewDocument || !response.editingEnabled || draft.closed) return
      event.preventDefault(); start = [event.clientX, event.clientY]; holder.setPointerCapture?.(event.pointerId)
    }
    holder.onpointerup = event => {
      if (!start || locked || previewing || previewDocument || draft.closed) return
      const begin = start; start = undefined
      try {
        if (mode === 'highlight') {
          const rect = pdfRectFromClient(pdfViewport, holder.getBoundingClientRect(), begin, [event.clientX, event.clientY], page.cropBox)
          void append({ kind: 'highlight', pageId: page.pageId, rect, color: markupColor }).catch(showError)
        } else if (mode === 'note') {
          const content = noteInput.value.trim()
          if (!content) throw new Error('请先输入批注内容，再点击页面')
          const bounds = holder.getBoundingClientRect()
          const point = pdfViewport.convertToPdfPoint((event.clientX - bounds.left) * pdfViewport.width / bounds.width, (event.clientY - bounds.top) * pdfViewport.height / bounds.height)
          void append({ kind: 'addTextAnnotation', pageId: page.pageId, rect: stickyNoteRect(point, page.cropBox), text: content }).catch(showError)
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
    originalText.textContent = target ? `原文：${target.text}` : '本页没有可改文字；扫描页 OCR 尚未开放。'
    replacement.value = target ? String(draft.operations.find(op => op.kind === 'replaceText' && op.objectId === target.objectId)?.newText ?? target.text) : ''
    replacement.hidden = stageText.hidden = !target
  }
  function renderFormControls(fields: PdfFormField[]) {
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
        const operation: NativeOperation = { kind: 'setFormValue', fieldId: field.fieldId, expectedFieldSha256: field.expectedFieldSha256, name: field.name, fieldKind: field.kind,
          ...(field.kind === 'checkbox' ? { checked: (control as HTMLInputElement).checked } : { value: control.value }) }
        draft.setOperations([...draft.operations.filter(op => !(op.kind === 'setFormValue' && op.name === field.name)), operation])
        void refresh().catch(showError)
      })
      label.append(control); formControls.append(label)
    }
    ribbon.setHasForms(fields.length > 0)
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
    return !textPanel.hidden && !!target && replacement.value !== String(draft.operations.find(op => op.kind === 'replaceText' && op.objectId === target.objectId)?.newText ?? target.text)
  }
  async function rebuildTextIndex() {
    const version = ++indexGeneration
    textIndex.clear()
    for (const page of state()) {
      if (disposed || version !== indexGeneration) return
      const original = await sourcePage(page.index), content = await original.getTextContent()
      if (disposed || version !== indexGeneration) return
      textIndex.set(page.pageId, content.items.map(item => 'str' in item ? item.str : '').join(' ').toLocaleLowerCase())
    }
    markSearch()
  }
  async function leavePreview() {
    for (const task of tasks) task.cancel()
    for (const layer of textLayers) layer.cancel()
    generation++; indexGeneration++; observer?.disconnect(); visible.clear(); tasks.clear(); textLayers.clear()
    document = sourceDocument; previewDocument = undefined; pagesCached.clear()
    const loading = previewLoading; previewLoading = undefined; await loading?.destroy()
    backToSource.hidden = true; root.dataset.pdfPreview = 'false'
  }
  function operationLabel(operation: NativeOperation, index: number) {
    const labels: Record<string, string> = { replaceText: '原位改字', highlight: '高亮', addTextAnnotation: '文字批注', rotatePage: '旋转', deletePage: '删页', addMarkup: '文字标注', reorderPages: '页面重排', cropPage: '裁切页面', setPageSize: '页面尺寸' }
    return `第 ${index + 1} 项 · ${labels[operation.kind] ?? operation.kind}${operation.kind === 'replaceText' ? `：${String(operation.newText).slice(0,120) || '删除文字'}` : ''}`
  }
  function skipReason(reason: string) {
    if (/identity|located|match/i.test(reason)) return '无法唯一定位原文字对象，已保留原文'
    if (/overflow|multiline/i.test(reason)) return '替换超出原行、页面或会与其他文字重叠，已保留原文'
    if (/font|characters|glyph/i.test(reason)) return '当前字体无法完整显示替换文字，已保留原文'
    return reason
  }
  async function previewDraft() {
    if (hasUnstagedText()) throw new Error('请先点击“加入文字修改”，再生成预览或保存')
    if (previewing || locked || draft.closed) throw new Error('正在处理 PDF，请稍后重试')
    const operations = structuredClone(draft.operations), key = JSON.stringify(operations)
    previewing = true; updateControls(); status.textContent = '正在生成实际 PDF 预览…'
    try {
      const result = await api.preview<PdfModel>({ expectedSha256: context.sourceFile.sha256, operations }, abort.signal)
      if (result.sourceSha256 !== context.sourceFile.sha256 || key !== JSON.stringify(draft.operations)) throw new Error('草稿或文件来源已变化，请重新预览')
      if (!operations.some(op => ['addMarkup', 'replaceText', 'setPageSize'].includes(op.kind))) { status.textContent = `当前 ${operations.length} 项修改已校验；保存后仍需核验业务内容。`; return }
      if (!result.previewDigest) throw new Error('服务端未返回 PDF 预览确认摘要')
      const bytes = await api.previewFile({ expectedSha256: context.sourceFile.sha256, operations, expectedPreviewDigest: result.previewDigest }, abort.signal)
      if (key !== JSON.stringify(draft.operations)) throw new Error('草稿已变化，请重新预览')
      await leavePreview()
      previewLoading = getDocument({ data: new Uint8Array(bytes), cMapUrl: `${ASSET_BASE}cmaps/`, cMapPacked: true, standardFontDataUrl: `${ASSET_BASE}standard_fonts/`, wasmUrl: `${ASSET_BASE}wasm/`, enableXfa: false })
      previewDocument = await previewLoading.promise
      if (previewDocument.numPages !== state().length) throw new Error('实际 PDF 预览页数不匹配，请重新预览')
      document = previewDocument; pagesCached.clear()
      mode = 'select'; setMode('select'); backToSource.hidden = false; root.dataset.pdfPreview = 'true'
      review.stage(operations, result.previewDigest); reviewList.replaceChildren()
      const skips = result.skippedOperations ?? [], applied = result.appliedOperationIndices ?? []
      for (const index of applied) { const item = documentElement('li'); item.textContent = `已执行：${operationLabel(operations[index], index)}`; reviewList.append(item) }
      for (const skipped of skips) { const item = documentElement('li'); item.className = 'pdf-skipped-operation'; item.textContent = `未执行，保留原文：${operationLabel(operations[skipped.operationIndex], skipped.operationIndex)}；${skipReason(skipped.reason)}`; item.title = skipped.reason; reviewList.append(item) }
      confirmText.textContent = `我已核对实际 PDF 预览，确认保存 ${applied.length} 项已执行修改及 ${skips.length} 项未执行修改（保留原文）`
      confirmPreview.checked = false; reviewPanel.hidden = !operations.some(op => op.kind === 'replaceText')
      await rebuildTextIndex(); await refresh()
    } catch (error) {
      review.reset(); reviewPanel.hidden = true; confirmPreview.checked = false
      await leavePreview(); await refresh()
      throw error
    } finally { previewing = false; updateControls() }
  }
  async function prepareSave(): Promise<{ confirmedPreviewDigest?: string }> {
    if (hasUnstagedText()) throw new Error('请先点击“加入文字修改”，再预览并保存')
    if (!draft.operations.some(op => op.kind === 'replaceText')) return {}
    if (previewing) throw new Error('正在生成实际 PDF 预览，请稍后保存')
    const confirmedPreviewDigest = review.confirmedDigest(draft.operations)
    if (confirmedPreviewDigest) return { confirmedPreviewDigest }
    if (!review.isPrepared(draft.operations)) await previewDraft()
    reviewPanel.scrollIntoView({ block: 'nearest' })
    throw new Error('请核对实际 PDF 预览与未执行清单，勾选确认后再次保存')
  }
  async function refresh() {
    if (disposed || !document) return
    const structureKey = JSON.stringify(draft.operations.filter(op => op.kind !== 'addMarkup'))
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
    observer?.disconnect()
    for (const task of tasks) task.cancel()
    for (const layer of textLayers) layer.cancel()
    tasks.clear(); textLayers.clear(); visible.clear(); pageNodes.clear()
    viewport.replaceChildren(); thumbs.replaceChildren(); outlinePanel.replaceChildren()
    const pages = state()
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
      const card = documentElement('section', 'pdf-page'); card.dataset.pageId = page.pageId
      card.setAttribute('aria-label', `第 ${position + 1} 页`)
      const heading = documentElement('button', 'pdf-page-label'); heading.type = 'button'; heading.textContent = `第 ${position + 1} 页（原第 ${page.index + 1} 页）`
      const content = documentElement('div', 'pdf-page-content'); content.style.width = `${dimensions.width}px`; content.style.height = `${dimensions.height}px`
      heading.addEventListener('click', () => { activeId = page.pageId; updateControls(); renderTextPanel(); for (const node of pageNodes.values()) node.classList.toggle('is-active', node === card) })
      card.addEventListener('pointerdown', () => { activeId = page.pageId; updateControls(); renderTextPanel() })
      card.append(heading, content)
      const savedAnnotations = await original.getAnnotations()
      const comments = savedAnnotations.filter(item => item.subtype === 'Text' && item.contentsObj?.str)
      if (comments.length) {
        const details = documentElement('details', 'pdf-saved-comments'), summary = documentElement('summary')
        summary.textContent = `已保存批注（${comments.length}）`; details.append(summary)
        for (const comment of comments) { const text = documentElement('p'); text.textContent = comment.contentsObj.str; details.append(text) }
        card.append(details)
      }
      viewport.append(card); pageNodes.set(page.pageId, card)
      card.classList.toggle('is-active', activeId === page.pageId)
      if (observer) observer.observe(card)
      else { visible.add(page.pageId); render(page.pageId) }
      const thumbnail = documentElement('button', 'pdf-thumbnail'); thumbnail.type = 'button'; thumbnail.setAttribute('aria-label', `跳转第 ${position + 1} 页`)
      const thumbCanvas = documentElement('canvas'); const thumbViewport = displayViewport(original, page, .15)
      thumbCanvas.width = Math.ceil(thumbViewport.width); thumbCanvas.height = Math.ceil(thumbViewport.height)
      const thumbTask = original.render({ canvas: thumbCanvas, viewport: thumbViewport, annotationMode: AnnotationMode.ENABLE })
      tasks.add(thumbTask); void thumbTask.promise.catch(() => {}).finally(() => tasks.delete(thumbTask))
      const label = documentElement('span'); label.textContent = `${position + 1}`; thumbnail.append(thumbCanvas, label)
      thumbnail.addEventListener('click', () => { activeId = page.pageId; card.scrollIntoView({ block: 'start', behavior: 'smooth' }); updateControls(); renderTextPanel() })
      thumbs.append(thumbnail)
    }
    for (const item of outline.filter(entry => pages.some(page => page.index === entry.pageIndex))) {
      const page = pages.find(candidate => candidate.index === item.pageIndex)!
      const link = documentElement('button', 'pdf-outline-link'); link.type = 'button'; link.textContent = item.title
      link.style.paddingInlineStart = `${8 + item.depth * 14}px`
      link.addEventListener('click', () => jumpToPageForIdentity(page.pageId))
      outlinePanel.append(link)
    }
    status.textContent = previewDocument ? '正在显示实际写回的 PDF 预览；未执行的修改仍保留原文。返回原稿后可继续调整。' : draft.persistenceError ?? (draft.dirty ? `有 ${draft.operations.length} 项未保存修改；保存会创建新修订。` : response.editingEnabled ? `选择页面文字可添加或切换本次高亮、下划线、波浪线和删除线；文字批注为便签。${textEnabled ? '原位改字需核对实际预览后保存。' : '原位改字尚未开放。'}` : '当前为只读，原生编辑尚未开放；可下载文件。')
    if (textLoadWarning) status.textContent += ` ${textLoadWarning}`
    renderTextPanel(); updateControls(); onDraftChange?.()
  }
  setMode('select')
  updateControls()
  status.textContent = '正在读取 PDF…'
  const file = await api.file(abort.signal)
  const actualSha256 = await bytesSha256(new Uint8Array(file))
  if (actualSha256 !== context.sourceFile.sha256) throw new Error('PDF 来源摘要不匹配')
  const model: PdfModel = { sourceSha256: actualSha256, pageCount: 0, pages: [] }
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
  {
    try {
      const sourceModel = await api.preview<PdfModel>({ expectedSha256: actualSha256, operations: [] }, abort.signal)
      if (sourceModel.sourceSha256 !== actualSha256 || sourceModel.model.sourceSha256 !== actualSha256) throw new Error('PDF 字段与文字对象来源不匹配')
      model.capabilities = sourceModel.model.capabilities
      for (const page of model.pages) { const source = sourceModel.model.pages.find(item => item.pageId === page.pageId); page.markups = source?.markups ?? []; page.markupReadSafe = source?.markupReadSafe === true }
      model.formFields = sourceModel.model.formFields ?? []
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
  if (draft.operations.some(operation => operation.kind === 'setPageSize') && model.capabilities?.pageSize !== true) throw new Error('当前来源未确认尺寸变更能力；原草稿已保留')
  if (draft.operations.some(operation => operation.kind === 'cropPage') && model.capabilities?.cropPage !== true) throw new Error('当前 PDF 引擎未确认裁切能力；原草稿已保留')
  void rebuildTextIndex().catch(showError)
  locked = false
  await refresh()
  return { refresh, prepareSave, setSaving(saving) { locked = saving; updateControls() }, dispose() {
    disposed = true; cleanupPrint(); onSelectionChange?.([]); abort.abort(); observer?.disconnect(); for (const task of tasks) task.cancel(); for (const layer of textLayers) layer.cancel(); void loading.destroy(); void previewLoading?.destroy(); ribbon.dispose(); root.replaceChildren()
  } }
}
