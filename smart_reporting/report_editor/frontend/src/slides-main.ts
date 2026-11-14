import {validateZoomDraft} from './slides-zoom-model'
import {mountModel3d} from './slides-model3d-ui'
import {validateModelDraft,type ModelInsertion,type ModelViewEdit,type ModelSource} from './slides-model3d'
import {mountSlidesInk} from './slides-ink-controls'
import {inkSlide,type InkChanges} from './slides-ink-model'
import {openSlidesCutout} from './slides-cutout-dialog'
import {verifiedCutoutSource} from './slides-cutout-source'
import {openSlidesCustomShows,type CustomShow} from './slides-custom-show-dialog'
import {createSlidesBackgroundPane,type BackgroundPaneOp} from './slides-background-pane'
import {startSlideScreenRecording,type SlideScreenRecording} from './slides-screen-recording'
import {pickSlideMedia,prepareSlideMedia,validateSlideMediaInsertions,type SlideMediaInsertion,type SlideMediaSource} from './slides-media'
import {classifyDroppedFile} from '../../../reporting/slides_engine/bridge/source-media/media-kinds'
import {openSlideMediaPlayback} from './slides-media-playback'
import { validateMasterTextDraft, type MasterTextEdit, type MasterTextPart, type MasterTextRenderPart } from './slides-master-text-model'
import { validateMasterElementDraft, type MasterElementEdit } from './slides-master-elements-model'
import type { openSlidesMasterText } from './slides-master-text'
import {createSlidesNotesPane,slidesNotesReadOnlyReason,validateSlidesNotesDraft,type NotesEdit} from './slides-notes'
import {slidesAIObjects} from './slides-native-ai-context'
import { SLIDES_TABLE_PRESETS, SLIDES_TABLE_FLAG_FIELDS, type SlidesTablePresetName, type SlidesTableFlags } from './slides-table-presets'
import { TABLE_SHADING_COLORS } from './vendor/genoffice-slides/components/table-shading-colors'
import { applyTransitionToAll, restoredTransitions, SLIDE_TRANSITIONS, type SlideTransition } from './slides-transitions'
import { SMARTART_GALLERY, SMARTART_MAX_ITEMS, type SmartArtGalleryLayout } from './vendor/genoffice-slides/components/smartart-gallery-data'
import { CHART_GALLERY, chartSampleData, type ChartGalleryKind } from './vendor/genoffice-slides/components/chart-gallery-data'
import { WORDART_PRESETS } from './vendor/genoffice-docs/packages/ui/src/wordart-presets'
import { LINE_SHAPE_KINDS, SHAPE_GALLERY_GROUPS, SHAPE_PRESETS } from './vendor/genoffice-slides/components/shape-gallery-data'
import { PARAGRAPH_LIST_COMMANDS, BULLET_GLYPHS, paragraphCommandPatch, projectParagraphs, uniformParagraphValue, type ParagraphFormatting, type ParagraphSourceFormatting, type ParagraphList } from './slides-paragraph'
import { createElement, ArrowDown, ArrowUp, Copy, Download, Redo2, Save, Sparkles, Trash2, Undo2, X } from 'lucide'
import { binaryRefreshLock, mountOfficeReportRefresh } from './binary-refresh'
import './slides.css'
import type { RenderSlide } from '@genoffice/pptx-render'
import { requestJson } from './api-request'
import type { SlidesCanvasState } from './slides-canvas'
import type { createSlidesSorter } from './slides-view-modes'
import type { createSlidesOutline, createSlidesReading } from './slides-outline-reading'
import { applyCanvasEdits } from './slides-canvas-model'
import { createSlidesChartTools } from './slides-chart-tools'
import { createSlidesNativeRibbon, stepNativeFontSize, type NativeSlidesContext, type NativeSlidesRibbon } from './slides-native-ribbon'
import { slidesLayoutLabel } from './slides-native-ribbon-locales'
import { sourceComments, validateCommentEdits, type CommentEdit, type SlideComments } from './slides-comments'
import { createSlidesCommentsPane } from './slides-comments-pane'
import type { NativeDraft, NativeOperation } from './native-draft'
import { mountSlidesNativeAI, type SlidesNativeAIClient } from './slides-native-ai'
import { openSlidesSizeDialog } from './slides-size-dialog'
import { mountSlidesRuler } from './slides-ruler'
import { mountSlidesGuides } from './slides-guides'
import { showSlidesSettingsDialog } from './slides-settings-dialog'
import { equationTextBox, openSlidesEquationDialog } from './slides-equation'
import { EFFECT_LABELS, TRIGGER_LABELS, appendAnimation, defaultAnimationDuration, deleteSequenceItem, initialSequence, motionPathAnimation, moveSequenceItem, patchSequenceTiming, removeElementAnimations, resolvedItem, sequenceUnchanged, stepNumbers, validateSequence, type SequenceItem, type SourceAnimation } from './slides-animation-sequence'
import { isPortrait, matchSlideSizePreset, presetSize, SLIDE_SIZE_PRESETS, MIN_SLIDE_EMU, MAX_SLIDE_EMU, type SlideSizePreset } from './vendor/genoffice-slides/slide-size'
import { openSlidesFindReplace } from './slides-find-replace'
import { pickSlideImage, prepareSlideImage } from './slides-native-images'
import { createNativeChartEditDialog, type NativeChartKind, type NativeChartPatch, type NativeChartStyle } from './slides-native-chart-edit'
import { createSlidesChartFormatPane } from './slides-chart-format-pane'
import { createSlidesGeometryPane } from './slides-geometry-pane'
import { createSlidesShapeFormatPane, shapeStyleForCommand } from './slides-shape-format-pane'
import { planSlidesArrange, type SlidesArrangeOp } from './slides-arrange'
import { planSlidesElementOrder, validateSlidesElementOrders } from './slides-element-order'
import { openSlidesPictureCrop, type CropRect } from './slides-native-crop'
import { validateNativeMediaDraft } from './slides-native-media-draft'
import { transposeChartData, transposeChartPointColors, mergeChartPointColors, type ChartPointColors } from '../../../reporting/slides_engine/bridge/pptx-chart-data'
import { CHART_STYLE_PRESETS, chartColorSchemes, type ChartColorScheme } from '../../../reporting/slides_engine/bridge/pptx-chart-design'
import { validateSlidesGroupDraft, type GroupEdit } from './slides-groups'
import { captureSlidesBrush, planSlidesBrushApply, type BrushSource } from './slides-format-brush'
import { validateSlidesClipboardDraft, captureSlidesClipboard, planSlidesClipboardPaste } from './slides-native-clipboard'
import { validateSlidesLinkDraft, openSlidesLink } from './slides-native-link'

type DeckElement = { model3d?:ModelSource; mediaKind?:'video'|'audio'; id: string; type: string; name: string; text: string; editable: boolean; pictureOpacityEditable?: boolean; pictureOpacityReason?: string | null; pictureOpacity?: number; clipboardEditable?: boolean; clipboardReason?: string | null; linkEditable?: boolean; linkReason?: string | null; elementLink?: {kind:'url';url:string;tooltip?:string}|{kind:'slide';slideIndex:number;tooltip?:string}|{kind:'action';action:string;tooltip?:string}|null; brushSource?: BrushSource; groupEditable?: boolean; groupReason?: string | null; ungroupEditable?: boolean; ungroupReason?: string | null; arrangeEditable?: boolean; orderEditable?: boolean; pictureCropEditable?: boolean; pictureCropReason?: string | null; srcRect?: CropRect | null; pictureReplaceable?: boolean; pictureReplaceReason?: string | null; pictureSha256?: string | null; pictureSize?: number | null; chartEditSafe?: boolean; chartEditReason?: string | null; chartPointColors?: (string | null)[][] | null; chartSeriesColors?: (string | null)[] | null; chartStyle?: NativeChartStyle | null; chartColorSchemes?: ChartColorScheme[] | null; chartGapWidthPct?: number | null; chartKind?: NativeChartKind | null; chartCategories?: string[] | null; chartSeries?: { name: string; values: number[] }[] | null; findReplaceEditable?: boolean; tableCells?: (string | null)[][]; tableStructureEditable?: boolean; tableCellShadingEditable?: boolean; tableCellShadingReason?: string | null; tablePresetEditable?: boolean; tablePresetReason?: string | null; tableStyleName?: string | null; tableStyleFlags?: SlidesTableFlags; deletable?: boolean; geometry?: { x: number; y: number; width: number; height: number }; paragraphAlignments?: (ParagraphFormatting['align'] | null)[]; paragraphFormatting?: ParagraphSourceFormatting[]; paragraphLists?: ParagraphList[]; textStyle?: { fontSizePt?: number | null; fontFamily?: string | null; color?: string | null; bold?: boolean | null; italic?: boolean | null; underline?: boolean | null; strike?: boolean | null } }
type Animation = SourceAnimation
type DeckLayout = { path: string; name: string; layoutType: string; placeholders: { type: string; idx: string; hint: string }[] }
type HeaderFooterSetting = { footer: string | null; slideNum: boolean; date: string | null; dateAuto: boolean }
type BackgroundGradientFill = { from: string; to: string; angleDeg: 0 | 45 | 90; radial: boolean }
type BackgroundImageReuse={sourceSlideIndex:number;expectedSha256:string;expectedSize:number;slideIndices:number[];tile:boolean}
type DeckSlide = { slideIdentity?: string; backgroundImageSource?:{sha256:string;size:number}|null; backgroundImage?: { mode: 'stretch' | 'tile' } | null; backgroundOwn?: boolean; backgroundGraphicsHidden?: boolean; backgroundGradient?: BackgroundGradientFill | null; notesText?:string;notesEditable?:boolean;notesReason?:string|null; slideIndex: number; comments?: SlideComments; hidden?: boolean; headerFooter?: { footer: string | null; slideNum: boolean; date: string | null; dateAuto?: boolean }; background?: string | null; layoutPath?: string; masterPath?: string; themePath?: string; transition?: SlideTransition; transitionEditSafe?: boolean; transitionEditReason?: string | null; transitionApplyAllSafe?: boolean; transitionApplyAllReason?: string | null; animations?: Animation[]; elements: DeckElement[] }
type Deck = { customShows?:CustomShow[];customShowsEditable?:boolean;customShowsReason?:string|null; masterTextParts?: MasterTextPart[]; revision: number; sha256: string; size: { cx: number; cy: number }; layouts?: DeckLayout[]; sections?: { name: string; slideIndices: number[] }[]; masterParts?: { partPath: string; kind: 'master' | 'layout'; name: string }[]; slides: DeckSlide[] }
type Edit = {
  slideIndex: number
  elementId: string
  text?: string
  geometry?: { x: number; y: number; width: number; height: number }
}
type TextFormatting = { slideIndex: number; elementId: string; fontSizePt?: number; fontFamily?: string; color?: string; bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean }
type BusinessTheme = 'executive' | 'clinical' | 'modern'
type AIProposal = { summary: string; edits: Edit[]; order: number[]; theme?: BusinessTheme }
type AIStatus = { editId: string; status: string; proposal?: AIProposal; error?: { message: string } }
type GeneratedImage = { candidateId: string; mediaType: string; previewDataUrl: string }
type ImageEdit = { candidateId: string; slideIndex: number; geometry: { x: number; y: number; width: number; height: number } }
type AnimationEffect = 'appear' | 'fade' | 'flyIn' | 'wipe' | 'wipeDown' | 'splitIn' | 'bounce' | 'flipIn' | 'zoom' | 'pulse' | 'spin' | 'grow' | 'teeter' | 'disappear' | 'fadeOut' | 'flyOut' | 'wipeOut' | 'shrink' | 'zoomOut' | 'motionPath' | 'mediaPlay' | 'mediaPause' | 'mediaStop'
type AnimationTrigger = 'onClick' | 'withPrev' | 'afterPrev'
type TextBoxEdit = { slideIndex: number; text: string; geometry: { x: number; y: number; width: number; height: number }; fontSize: number; fontFamily: string; color: string; bold?: boolean; rotation?: number; field?: 'slidenum' | 'datetime1'; italic?: boolean; outline?: { color: string; widthEmu: number }; wordArt?: boolean; equation?: boolean; watermark: boolean }
type AnimationDirection = 'top' | 'bottom' | 'left' | 'right'
type AnimationEdit = { slideIndex: number; elementId: string; effect: AnimationEffect; trigger: AnimationTrigger; durationMs: number; delayMs: number; direction?: AnimationDirection; append?: true }
/** 固定源 Shape Format 填充/轮廓（setFill / setStroke） */
type ShapeStyleEdit = { slideIndex: number; elementId: string; fill?: string; stroke?: { color: string; widthPt: number } | null }
type ShapeEdit = { slideIndex: number; kind: string; geometry: { x: number; y: number; width: number; height: number } }
type SmartArtEdit = { slideIndex: number; layout: SmartArtGalleryLayout; items: string[] }
type ChartEdit = { slideIndex: number; kind: ChartGalleryKind; categories: string[]; series: { name: string; values: number[] }[] }
type NewSlide = { layoutFrom: number } | { duplicateOf: number } | { withLayout: string }
type CellShading = { row: number; col: number; shadingColor: string }
type TableStyleEdit = { cellShadings?: CellShading[]; slideIndex: number; elementId: string; shadingColor?: string; borderPreset?: 'all' | 'none'; styleName?: SlidesTablePresetName } & Partial<SlidesTableFlags>
type TableStructureEdit = { slideIndex:number; elementId:string; kind:'insert-row'|'delete-row'|'insert-col'|'delete-col'; index:number; before?:boolean }
type LinkEdit = {slideIndex:number;elementId:string;target:{kind:'url';url:string}|{kind:'slide';slideIndex:number}|null}
type ClipboardPaste = {sourceSlideIndex:number;elementIds:string[];slideIndex:number;dx:number;dy:number}
type ZoomInsertion = {slideIdentity:string;targetSlideIdentity:string;bytesBase64:string;geometry:{x:number;y:number;width:number;height:number};mode:'slide'|'section'}
type SlideChanges = {
  zoomInsertions?: ZoomInsertion[]
  customShows?:CustomShow[]
  modelInsertions?:ModelInsertion[]
  modelViews?:ModelViewEdit[]
  mediaInsertions?: SlideMediaInsertion[]
  masterTextEdits?: MasterTextEdit[]
  masterElementEdits?: MasterElementEdit[]
  notesEdits?: NotesEdit[]
  linkEdits?: LinkEdit[]
  clipboardPastes?: ClipboardPaste[]
  groupEdits?: GroupEdit[]
  elementOrders?: {slideIndex:number;elementIds:string[]}[]
  commentEdits?: CommentEdit[]
  tableStructures?: TableStructureEdit[]
  tableStyles?: TableStyleEdit[]
  edits?: Edit[]; order?: number[]; newSlides?: NewSlide[]; deletedSlides?: number[]; resetLayouts?: number[]; shapes?: ShapeEdit[]; shapeStyles?: ShapeStyleEdit[]; shapeKinds?: { slideIndex: number; elementId: string; kind: string }[]; sections?: { slideIndex: number; name: string }[]; headerFooter?: HeaderFooterSetting; tableCells?: { slideIndex: number; elementId: string; row: number; col: number; text: string }[]; charts?: ChartEdit[]; smartArts?: SmartArtEdit[]; tables?: { slideIndex: number; rows: number; cols: number }[]; theme?: BusinessTheme; slideSize?: { cx: number; cy: number }
  textFormatting?: TextFormatting[]; paragraphFormatting?: ParagraphFormatting[]
  images?: { slideIndex: number; bytesBase64: string; extension: 'png' | 'jpg'; geometry: { x: number; y: number; width: number; height: number }; descr?: string;name?:string }[]
  pictureReplacements?: { slideIndex: number; elementId: string; expectedSha256: string; expectedSize: number; bytesBase64: string; extension: 'png' | 'jpg';keepSrcRect?:true }[]
  pictureCrops?: { slideIndex:number; elementId:string; expectedSha256:string; expectedSize:number; srcRect:CropRect|null; geometry:{x:number;y:number;width:number;height:number} }[]
  /** 固定源 Picture Format ▸ Transparency：整图不透明度（0–1，整数百分比），按媒体身份绑定。 */
  pictureOpacities?: { slideIndex: number; elementId: string; expectedSha256: string; expectedSize: number; opacity: number }[]
  /** 固定源 FormatBackgroundPane 图片填充：一张图片应用到若干来源页，拉伸或平铺。 */
  backgroundImages?: { slideIndices: number[]; bytesBase64: string; extension: 'png' | 'jpg'; tile: boolean }[]
  backgroundImageReuses?: BackgroundImageReuse[]
  backgroundGradients?: (BackgroundGradientFill & { slideIndices: number[] })[]
  backgroundResets?: number[]
  backgroundGraphics?: { slideIndex: number; hidden: boolean }[]
  chartEdits?: ({ slideIndex: number; elementId: string } & NativeChartPatch)[]
  hiddenSlides?: { slideIndex: number; hidden: boolean }[]
  transitions?: { slideIndex: number; kind: SlideTransition }[]; animations?: AnimationEdit[]; animationSequences?: { slideIndex: number; items: SequenceItem[] }[]
  slideLayouts?: { slideIndex: number; layoutPath: string }[]; backgrounds?: { slideIndex: number; color: string }[]
  textBoxes?: Omit<TextBoxEdit, 'watermark'>[]; deletions?: { slideIndex: number; elementId: string }[]
}

export function createSlidesEditorView(host: HTMLElement, sharedShell?: {
  save?: HTMLButtonElement
  download?: HTMLAnchorElement
  request?: <T>(path: string, init?: RequestInit) => Promise<T>
  native?: boolean
  draft?: NativeDraft
  onAssistant?: () => void
  nativeAI?: SlidesNativeAIClient
}) {
const root = host
const basePath = location.pathname.replace(/\/$/, '')
const embedded = Boolean(sharedShell)
const native = sharedShell?.native === true
const nativeDraft = native ? sharedShell?.draft : undefined
let nativeAIHost: ReturnType<typeof mountSlidesNativeAI> | undefined
const request = sharedShell?.request ?? (<T>(path: string, init?: RequestInit): Promise<T> =>
  requestJson(`${basePath}/api/${path}`, init, 'report_slides_csrf'))

const buttonIcon = (icon: typeof Save, label: string) => {
  const button = document.createElement('button')
  button.type = 'button'
  button.title = label
  button.setAttribute('aria-label', label)
  button.append(createElement(icon, { width: 17, height: 17, 'aria-hidden': 'true' }))
  return button
}

root.innerHTML = `${embedded ? '' : `
  <header class="slides-topbar">
    <a class="slides-brand" href="#" aria-label="报告幻灯片"><span class="brand-mark"></span><span>报告幻灯片</span></a>
    <div class="slides-topbar-meta"><span class="revision"></span><span class="slides-save-state" role="status">正在载入</span></div>
    <div class="slides-topbar-actions"><button class="undo-button" type="button" title="撤销 AI 采纳" aria-label="撤销 AI 采纳" disabled></button><a class="download-link" hidden></a><button class="save-button" type="button"><span class="save-icon"></span><span>保存修订</span></button></div>
  </header>
`}
  <section class="slides-ai" aria-label="Ask AI"><form class="ai-form"><label for="ai-instruction">Ask AI</label><textarea id="ai-instruction" rows="2" maxlength="2000" placeholder="描述要调整的内容或页面顺序"></textarea><button class="ai-submit" type="submit">生成候选</button><button class="ai-cancel" type="button" hidden aria-label="取消 AI 任务"></button></form><div class="ai-result" role="status" aria-live="polite"></div><div class="ai-preview" hidden><strong class="ai-summary"></strong><ul class="ai-edits"></ul><button class="ai-accept" type="button">采纳候选</button></div></section>
  <section class="slides-image-tools" aria-label="AI 配图"><form class="image-form"><label for="image-prompt">AI 配图</label><textarea id="image-prompt" rows="1" maxlength="1000" placeholder="描述一张用于汇报的配图"></textarea><label class="image-target-label" for="image-target">目标页</label><select id="image-target"></select><button class="image-generate" type="submit">生成预览</button></form><div class="image-output"><span class="image-status" role="status">尚未生成配图</span><div class="image-candidate" hidden><img class="image-preview" alt="AI 配图预览"><button class="image-add" type="button">加入待保存配图</button></div><ul class="image-pending"></ul></div></section>
  <div class="slides-workspace">
    <aside class="slides-sidebar" aria-label="幻灯片列表"><div class="sidebar-heading">页面 <span class="slide-count"></span></div><ol class="slide-list"></ol></aside>
    <section class="slides-stage" aria-label="幻灯片预览"><div class="slides-canvas" role="group" aria-label="可编辑幻灯片画布" hidden></div><p class="canvas-status" role="status">画布载入中</p><iframe class="preview-frame" title="幻灯片预览"></iframe></section>
    <aside class="slides-inspector" aria-label="对象编辑"><div class="inspector-heading">对象</div><div class="slide-lineage"><span class="lineage-label">母版</span><span class="slide-master"></span><span class="lineage-label">版式</span><select id="layout-select" aria-label="当前页版式"></select></div><label class="field-label" for="object-select">可编辑对象</label><select id="object-select"></select><label class="field-label" for="object-text">文字</label><textarea id="object-text" rows="7" spellcheck="false"></textarea><div class="geometry-heading">位置与大小</div><div class="geometry-grid"><label>X <input name="x" type="number" min="0" step="1"></label><label>Y <input name="y" type="number" min="0" step="1"></label><label>宽 <input name="width" type="number" min="1" step="1"></label><label>高 <input name="height" type="number" min="1" step="1"></label></div><div class="structure-controls"><label class="field-label" for="background-color">页面背景</label><div class="structure-row"><input id="background-color" type="color" value="#ffffff" aria-label="当前页背景颜色"><button class="background-reset" type="button">恢复原背景</button></div><div class="field-label">页面对象</div><div class="structure-row"><button class="text-add" type="button">新增文本</button><button class="watermark-add" type="button">新增水印</button><button class="object-delete" type="button">删除对象</button></div><ul class="structure-pending" aria-label="待保存的页面结构修改"></ul></div><label class="field-label" for="theme-select">商务主题</label><select id="theme-select"><option value="">保持当前主题</option><option value="executive">执行汇报</option><option value="clinical">临床医疗</option><option value="modern">现代商务</option></select><label class="field-label" for="transition-select">页面转场</label><select id="transition-select"><option value="none">无</option><option value="fade">淡化</option><option value="push">推进</option><option value="wipe">擦除</option><option value="split">分割</option><option value="circle">圆形</option><option value="cover">覆盖</option><option value="pull">拉伸</option><option value="dissolve">溶解</option><option value="zoom">缩放</option><option value="morph">变形</option><option value="random">随机</option></select><div class="animation-controls"><label class="field-label" for="animation-effect">动画效果</label><select id="animation-effect"><option value="fade">淡化</option><option value="appear">出现</option><option value="flyIn">飞入</option><option value="wipe">擦除</option><option value="wipeDown">向下擦除</option><option value="splitIn">分割进入</option><option value="bounce">弹跳</option><option value="flipIn">翻转进入</option><option value="zoom">缩放进入</option><option value="pulse">脉冲</option><option value="spin">旋转</option><option value="grow">放大</option><option value="teeter">摇摆</option><option value="disappear">消失</option><option value="fadeOut">淡出</option><option value="flyOut">飞出</option><option value="wipeOut">擦除退出</option><option value="shrink">缩小退出</option><option value="zoomOut">缩小退出</option><option value="motionPath">路径</option><option value="mediaPlay">播放媒体</option><option value="mediaPause">暂停媒体</option><option value="mediaStop">停止媒体</option></select><label class="field-label" for="animation-trigger">触发方式</label><select id="animation-trigger"><option value="onClick">点击时</option><option value="withPrev">与上一动画同时</option><option value="afterPrev">上一动画后</option></select><div class="animation-timing"><label>持续 <input id="animation-duration" type="number" min="1" max="120000" step="50" value="500"> ms</label><label>延迟 <input id="animation-delay" type="number" min="0" max="120000" step="50" value="0"> ms</label></div><button class="animation-add" type="button">添加对象动画</button></div><p class="animation-state"></p><p class="object-note">未编辑对象会保留在原始 PPTX 中。</p></aside>
  </div>
  <footer class="slides-statusbar"><span class="status-dot"></span><span class="status-message">读取 PPTX…</span><span class="status-spacer"></span><span>编辑器</span></footer>
`
if (embedded) root.classList.add('slides-embedded')
if (native) for (const panel of root.querySelectorAll<HTMLElement>('.slides-ai, .slides-image-tools')) { panel.hidden = true; panel.inert = true }

const list = root.querySelector<HTMLOListElement>('.slide-list')!
const select = root.querySelector<HTMLSelectElement>('#object-select')!
select.setAttribute('aria-label', '可编辑对象')
const arrangeSelection = document.createElement('fieldset')
arrangeSelection.className = 'slides-arrange-selection'
arrangeSelection.hidden = !native
select.after(arrangeSelection)
const textArea = root.querySelector<HTMLTextAreaElement>('#object-text')!
// 表格单元格编辑：选中表格时在文字框下方显示单元格网格（合并单元格只读）。
const tableCellEditor = document.createElement('div'); tableCellEditor.className = 'table-cell-editor'; tableCellEditor.hidden = true
textArea.after(tableCellEditor)
const preview = root.querySelector<HTMLIFrameElement>('.preview-frame')!
const stateLabel = root.querySelector<HTMLElement>('.slides-save-state') ?? document.querySelector<HTMLElement>('.save-state-label')!
const statusMessage = root.querySelector<HTMLElement>('.status-message')!
const revisionLabel = root.querySelector<HTMLElement>('.revision') ?? document.querySelector<HTMLElement>('.revision-label')!
const downloadLink = root.querySelector<HTMLAnchorElement>('.download-link') ?? sharedShell?.download!
const aiForm = root.querySelector<HTMLFormElement>('.ai-form')!
const aiInstruction = root.querySelector<HTMLTextAreaElement>('#ai-instruction')!
const aiResult = root.querySelector<HTMLElement>('.ai-result')!
const aiPreview = root.querySelector<HTMLElement>('.ai-preview')!
const aiSummary = root.querySelector<HTMLElement>('.ai-summary')!
const aiEdits = root.querySelector<HTMLUListElement>('.ai-edits')!
const aiAccept = root.querySelector<HTMLButtonElement>('.ai-accept')!
const aiSubmit = root.querySelector<HTMLButtonElement>('.ai-submit')!
const aiCancel = root.querySelector<HTMLButtonElement>('.ai-cancel')!
const undoButton = root.querySelector<HTMLButtonElement>('.undo-button') ?? (() => {
  const button = buttonIcon(Undo2, '撤销 AI 采纳')
  button.className = 'undo-button'
  button.disabled = true
  root.querySelector('.ai-form')?.prepend(button)
  return button
})()
const themeSelect = root.querySelector<HTMLSelectElement>('#theme-select')!
const transitionSelect = root.querySelector<HTMLSelectElement>('#transition-select')!
const animationAdd = root.querySelector<HTMLButtonElement>('.animation-add')!
const animationState = root.querySelector<HTMLElement>('.animation-state')!
const animationEffect = root.querySelector<HTMLSelectElement>('#animation-effect')!
const animationTrigger = root.querySelector<HTMLSelectElement>('#animation-trigger')!
const animationDuration = root.querySelector<HTMLInputElement>('#animation-duration')!
const animationDelay = root.querySelector<HTMLInputElement>('#animation-delay')!
const layoutSelect = root.querySelector<HTMLSelectElement>('#layout-select')!
const slideMaster = root.querySelector<HTMLElement>('.slide-master')!
const imageForm = root.querySelector<HTMLFormElement>('.image-form')!
const imagePrompt = root.querySelector<HTMLTextAreaElement>('#image-prompt')!
const imageTarget = root.querySelector<HTMLSelectElement>('#image-target')!
const imageStatus = root.querySelector<HTMLElement>('.image-status')!
const imageCandidate = root.querySelector<HTMLElement>('.image-candidate')!
const imagePreview = root.querySelector<HTMLImageElement>('.image-preview')!
const imageGenerate = root.querySelector<HTMLButtonElement>('.image-generate')!
const imageAdd = root.querySelector<HTMLButtonElement>('.image-add')!
const imagePending = root.querySelector<HTMLUListElement>('.image-pending')!
const backgroundColor = root.querySelector<HTMLInputElement>('#background-color')!
const backgroundReset = root.querySelector<HTMLButtonElement>('.background-reset')!
const textAdd = root.querySelector<HTMLButtonElement>('.text-add')!
const watermarkAdd = root.querySelector<HTMLButtonElement>('.watermark-add')!
const objectDelete = root.querySelector<HTMLButtonElement>('.object-delete')!
const structurePending = root.querySelector<HTMLUListElement>('.structure-pending')!
objectDelete.prepend(createElement(Trash2, { width: 15, height: 15, 'aria-hidden': 'true' }))
const order: number[] = []
/** 固定源 onAddSlide：新建空白页只记录版式来源页；其索引为 来源页数 + k，位置由 order 决定，保存后由引擎写入。 */
const newSlides: NewSlide[] = []
/** 新页沿用/复制的来源页；按版式新建的页没有来源页（null）。 */
const newSlideSource = (item: NewSlide): number | null => 'duplicateOf' in item ? item.duplicateOf : 'layoutFrom' in item ? item.layoutFrom : null
/** 固定源缩略图 deleteSlide：删除的来源页；保存时按部件路径删除，order 只列保留页。 */
const deletedSlides = new Set<number>()
/** 固定源 onResetLayout：保存时先把这些来源页的占位符位置恢复为版式继承，再叠加同批其他修改。 */
const resetLayouts = new Set<number>()
/** 固定源 Insert ▸ Shapes：待插入的预设形状（96dpi 像素几何），保存后由引擎写入。 */
const shapeEdits: ShapeEdit[] = []
const shapeStyleEdits = new Map<string, ShapeStyleEdit>()
/** 固定源 Change Shape：对象 → 新预设（仅形状，非线条） */
const shapeKindEdits = new Map<string, { slideIndex: number; elementId: string; kind: string }>()
/** 固定源 onAddSection：在目标页（与 order 相同编号）之前新增节，保存时按最终位置写入。 */
const sectionEdits: { slideIndex: number; name: string }[] = []
/** 已有表格单元格改字：键为 页:对象:行:列 */
const tableStructureEdits = new Map<number,TableStructureEdit>()
const tableStyleEdits = new Map<string, TableStyleEdit>()
let tableShadingCell: { slideIndex: number; elementId: string; row: number; col: number } | undefined
let tableCellEditorGeneration = 0
const tableCellEdits = new Map<string, { slideIndex: number; elementId: string; row: number; col: number; text: string }>()
/** 固定源 Insert ▸ Chart：待插入图表（固定源示例数据），保存时最后写入。 */
const chartEdits: ChartEdit[] = []
const elementOrders = new Map<number,string[]>()
const groupEdits: GroupEdit[] = []
const notesEdits = new Map<number,string>()
let notesVisible=true
const linkEdits: LinkEdit[] = []
const clipboardPastes: ClipboardPaste[] = []
let nativeClipboard: {sourceSha:string;sourceSlideIndex:number;elementIds:string[];pasteCount:number} | undefined
let brush: ReturnType<typeof captureSlidesBrush>['brush'] = null
let brushMode: 'once' | 'continuous' | undefined
let linkDialog: ReturnType<typeof openSlidesLink> | undefined
let showOverlay: { dispose(): void } | undefined
let showOpening = false
let animationPreviewOverlay: { dispose(): void } | undefined
let animationPreviewGeneration = 0
const pendingGroup = (slideIndex: number) => groupEdits.some(item => item.slideIndex === slideIndex)
const pictureCrops: NonNullable<SlideChanges['pictureCrops']> = []
const pictureOpacities: NonNullable<SlideChanges['pictureOpacities']> = []
let cropOverlay: ReturnType<typeof openSlidesPictureCrop> | undefined
const nativeImages: NonNullable<SlideChanges['images']> = []
const zoomInsertions: ZoomInsertion[] = []
let zoomController:AbortController|undefined
let zoomDialog:HTMLDialogElement|undefined
const modelInsertions:ModelInsertion[]=[],modelViews:ModelViewEdit[]=[]
let modelControls:ReturnType<typeof mountModel3d>|undefined
const mediaInsertions: SlideMediaInsertion[] = []
let mediaPlayback: {dispose():void}|undefined
let mediaPickerController:AbortController|undefined
let screenRecording:SlideScreenRecording|undefined
let screenRecordingController:AbortController|undefined
const pictureReplacements: NonNullable<SlideChanges['pictureReplacements']> = []
const nativeChartEdits: NonNullable<SlideChanges['chartEdits']> = []
let masterTextDialog: ReturnType<typeof openSlidesMasterText> | undefined
let masterTextDialogGeneration = 0
let findDialog: ReturnType<typeof openSlidesFindReplace> | undefined
let chartDialog: ReturnType<typeof createNativeChartEditDialog> | undefined
const chartFormatPane = native ? createSlidesChartFormatPane(applyNativeChartPointColors) : undefined
if (chartFormatPane) arrangeSelection.after(chartFormatPane.element)
const geometryPane = native ? createSlidesGeometryPane((geometry, target) => {
  const element=currentElement()
  if(locked()||pendingGroup(selectedSlide)||selectedObjects.size!==1||!element?.arrangeEditable||target!==editKey(selectedSlide,element.id))throw new Error('选择已变化，请重新编辑大小与位置')
  const changes=slideChanges(),crop=changes.pictureCrops?.find(item=>item.slideIndex===selectedSlide&&item.elementId===element.id)
  const others=(changes.edits??[]).filter(item=>item.slideIndex!==selectedSlide||item.elementId!==element.id)
  if(crop){crop.geometry=geometry;if(others.length)changes.edits=others;else delete changes.edits}
  else changes.edits=[...others,{...edits.get(target),slideIndex:selectedSlide,elementId:element.id,geometry}]
  commitNativeChanges(changes)
}) : undefined
if(geometryPane){const heading=root.querySelector<HTMLElement>('.geometry-heading')!;heading.before(geometryPane.element);heading.style.display='none';root.querySelector<HTMLElement>('.geometry-grid')!.style.display='none'}
const shapeFormatPane = native ? createSlidesShapeFormatPane(()=>({slideIndex:selectedSlide,element:selectedObjects.size===1?currentElement():undefined,changes:slideChanges(),reason:locked()||pendingGroup(selectedSlide)||isNewSlide(selectedSlide)?'请先完成当前修订或保存结构修改':undefined}),commitNativeChanges,root) : undefined
if(shapeFormatPane)arrangeSelection.after(shapeFormatPane.element)
/** 固定源 Insert ▸ SmartArt：待插入布局与节点文字（可在待保存清单改写，每行一个节点）。 */
const smartArtEdits: SmartArtEdit[] = []
/** 固定源 HeaderFooterDialog：全部应用（含新建页），保存时最后写入。 */
let headerFooterEdit: HeaderFooterSetting | undefined
function openHeaderFooterDialog() {
  const initial = headerFooterEdit ?? { ...(slideAt(selectedSlide).headerFooter ?? { footer: null, slideNum: false, date: null }), dateAuto: slideAt(selectedSlide).headerFooter?.dateAuto ?? !slideAt(selectedSlide).headerFooter?.date }
  const dialog = document.createElement('dialog'); dialog.className = 'slides-table-dialog slides-hf-dialog'; dialog.setAttribute('aria-label', '页眉和页脚')
  dialog.innerHTML = '<header><h3>页眉和页脚</h3></header><div class="slides-settings-body"><label class="check"><input name="dateOn" type="checkbox"> 日期和时间</label><label class="check indent"><input name="dateAuto" type="checkbox"> 自动更新</label><label class="indent">日期文字 <input name="date" type="text" maxlength="500"></label><label class="check"><input name="slideNum" type="checkbox"> 幻灯片编号</label><label class="check"><input name="footerOn" type="checkbox"> 页脚</label><label class="indent">页脚文字 <input name="footer" type="text" maxlength="500" placeholder="页脚文字"></label><p role="alert" aria-label="页眉和页脚错误" tabindex="0"></p></div><footer class="slides-table-actions"><button type="button" value="cancel">取消</button><button type="button" value="ok">全部应用</button></footer>'
  host.append(dialog)
  const field = (name: string) => dialog.querySelector<HTMLInputElement>(`input[name=${name}]`)!
  field('dateOn').checked = !!initial.date; field('dateAuto').checked = initial.dateAuto; field('date').value = initial.date ?? new Date().toLocaleDateString('zh-CN')
  field('slideNum').checked = initial.slideNum; field('footerOn').checked = !!initial.footer; field('footer').value = initial.footer ?? ''
  dialog.querySelector<HTMLButtonElement>('button[value=cancel]')!.addEventListener('click', () => dialog.close())
  dialog.querySelector<HTMLButtonElement>('button[value=ok]')!.addEventListener('click', () => {
    headerFooterEdit = { footer: field('footerOn').checked && field('footer').value.trim() ? field('footer').value.trim() : null, slideNum: field('slideNum').checked, date: field('dateOn').checked && field('date').value.trim() ? field('date').value.trim() : null, dateAuto: field('dateAuto').checked }
    dialog.close(); canvasStatus.textContent = '页眉页脚将在保存并打开新修订后显示在画布中。'
    renderStructurePending(); markDirty()
  })
  showSlidesSettingsDialog(dialog)
}
/** 同一页只保留最新一种背景填充：清除这些页待保存的图片/渐变/重置（纯色由调用方处理）。 */
function dropBackgroundImages(slideIndices: number[]) {
  for (const list of [backgroundImageEdits, backgroundImageReuseEdits, backgroundGradientEdits] as { slideIndices: number[] }[][]) {
    for (let index = list.length - 1; index >= 0; index--) {
      const item = list[index]!
      item.slideIndices = item.slideIndices.filter(slideIndex => !slideIndices.includes(slideIndex))
      if (!item.slideIndices.length) list.splice(index, 1)
    }
  }
  for (const index of slideIndices) backgroundResetEdits.delete(index)
}
function backgroundPaneKey(){return `${deck?.sha256}:${selectedSlide}`}
function backgroundPaneSlide():RenderSlide|undefined {
 const source=slideForView(selectedSlide);if(!source)return undefined
 const gradient=backgroundGradientEdits.find(item=>item.slideIndices.includes(selectedSlide)),image=backgroundImageEdits.find(item=>item.slideIndices.includes(selectedSlide)),reuse=backgroundImageReuseEdits.find(item=>item.slideIndices.includes(selectedSlide)),color=backgroundEdits.get(selectedSlide)
 const background:RenderSlide['background']=gradient?{kind:'gradient',stops:[{pos:0,color:gradient.from},{pos:1,color:gradient.to}],angleDeg:gradient.angleDeg,radial:gradient.radial}:image?{kind:'image',dataUrl:`data:image/${image.extension};base64,${image.bytesBase64}`,mode:image.tile?'tile':'stretch'}:reuse&&source.background.kind==='image'?{...source.background,mode:reuse.tile?'tile':'stretch'}:color?{kind:'solid',color}:source.background
 return {...source,background,bgOwn:!backgroundResetEdits.has(selectedSlide)&&(!!slideAt(selectedSlide).backgroundOwn||!!gradient||!!image||!!reuse||!!color),bgGraphicsHidden:backgroundGraphicsEdits.get(selectedSlide)??source.bgGraphicsHidden}
}
let customShowEdits:CustomShow[]|undefined
let customShowDialog:ReturnType<typeof openSlidesCustomShows>|undefined
function openCustomShowDialog(){
 if(!nativeDraft||locked()||deck.customShowsEditable===false){statusMessage.textContent=deck.customShowsReason??'当前来源不能修改自定义放映';return}
 if(newSlides.length||deletedSlides.size){statusMessage.textContent='请先保存页面增删，再设置自定义放映';return}
 customShowDialog?.dispose()
 let snapshot=JSON.stringify(nativeDraft.operations)
 const current=()=>!disposed&&!locked()&&JSON.stringify(nativeDraft!.operations)===snapshot
 customShowDialog=openSlidesCustomShows(root,{shows:customShowEdits??deck.customShows??[],slideCount:deck.slides.length,onChange:shows=>{if(!current())throw Error('草稿已变化，请关闭并重新打开自定义放映');const changes=slideChanges();changes.customShows=shows;commitNativeChanges(changes);snapshot=JSON.stringify(nativeDraft!.operations)},onPlay:show=>{if(!current()){statusMessage.textContent='草稿已变化，请重新打开自定义放映';customShowDialog?.dispose();return}customShowDialog?.dispose();customShowDialog=undefined;void startSlidesShow(false,show)},onClose:()=>{customShowDialog=undefined}})
}
let backgroundPickGeneration=0
async function applyBackgroundPane(op:BackgroundPaneOp,all?:boolean){
 if(disposed||locked()||isNewSlide(selectedSlide))return
 const sourceIndex=selectedSlide,key=backgroundPaneKey(),snapshot=JSON.stringify(slideChanges()),draftSnapshot=JSON.stringify(nativeDraft?.operations),paneToken=backgroundPane?.token(),generation=++backgroundPickGeneration
 const targets=all?deck.slides.map((_,i)=>i).filter(i=>!deletedSlides.has(i)):[sourceIndex]
 try{
 const changes=structuredClone(slideChanges())
 if(op.kind==='hideGraphics'){changes.backgroundGraphics=(changes.backgroundGraphics??[]).filter(item=>!targets.includes(item.slideIndex));for(const slideIndex of targets)if(op.hidden!==!!deck.slides[slideIndex]?.backgroundGraphicsHidden)changes.backgroundGraphics.push({slideIndex,hidden:op.hidden})}
 else{
 let upload:NonNullable<SlideChanges['backgroundImages']>[number]|undefined
 let reuse:BackgroundImageReuse|undefined
 if(op.kind==='image'){
 const pending=backgroundImageEdits.find(item=>item.slideIndices.includes(sourceIndex)),existing=backgroundImageReuseEdits.find(item=>item.slideIndices.includes(sourceIndex))
 if(op.pick){const file=await pickSlideImage();if(!file||disposed||locked()||generation!==backgroundPickGeneration||key!==backgroundPaneKey()||paneToken!==backgroundPane?.token()||backgroundPane?.element.hidden)return;const image=await prepareSlideImage(file,deck.size);if(disposed||locked()||generation!==backgroundPickGeneration||key!==backgroundPaneKey()||snapshot!==JSON.stringify(slideChanges())||draftSnapshot!==JSON.stringify(nativeDraft?.operations)||paneToken!==backgroundPane?.token()||backgroundPane?.element.hidden)return;upload={slideIndices:targets,bytesBase64:image.bytesBase64,extension:image.extension,tile:op.mode==='tile'}}
 else if(pending)upload={...pending,slideIndices:targets,tile:op.mode==='tile'}
 else {const identity=deck.slides[sourceIndex]?.backgroundImageSource;if(existing)reuse={...existing,slideIndices:targets,tile:op.mode==='tile'};else if(identity)reuse={sourceSlideIndex:sourceIndex,expectedSha256:identity.sha256,expectedSize:identity.size,slideIndices:targets,tile:op.mode==='tile'};else throw Error('来源背景图片身份不可读取，请重新选择图片')}
 }
 changes.backgrounds=(changes.backgrounds??[]).filter(item=>!targets.includes(item.slideIndex))
 for(const name of ['backgroundImages','backgroundImageReuses','backgroundGradients'] as const){const list=changes[name]??[];for(const item of list)item.slideIndices=item.slideIndices.filter(i=>!targets.includes(i));(changes as any)[name]=list.filter(item=>item.slideIndices.length)}
 changes.backgroundResets=(changes.backgroundResets??[]).filter(i=>!targets.includes(i))
 if(op.kind==='solid')changes.backgrounds.push(...targets.map(slideIndex=>({slideIndex,color:op.color.toUpperCase()})))
 if(op.kind==='gradient')(changes.backgroundGradients??=[]).push({slideIndices:targets,from:op.from.toUpperCase(),to:op.to.toUpperCase(),angleDeg:op.radial?0:op.angleDeg as 0|45|90,radial:!!op.radial})
 if(op.kind==='reset')changes.backgroundResets.push(...targets.filter(i=>deck.slides[i]?.backgroundOwn))
 if(upload)(changes.backgroundImages??=[]).push(upload)
 if(reuse)(changes.backgroundImageReuses??=[]).push(reuse)
 }
 commitNativeChanges(changes)
 }catch(error){statusMessage.textContent=error instanceof Error?error.message:'背景处理失败'}
}
const backgroundPane=native?createSlidesBackgroundPane((op,all)=>{void applyBackgroundPane(op,all)}):undefined
if(backgroundPane)root.querySelector('.slides-inspector')!.prepend(backgroundPane.element)
const GRADIENT_DIRECTIONS = [['→ 水平', 0, false], ['↓ 垂直', 90, false], ['↘ 对角', 45, false], ['◎ 径向', 0, true]] as const
/** 固定源 FormatBackgroundPane：图片（拉伸/平铺）、渐变（→ ↓ ↘ 径向）、隐藏背景图形、重置背景、应用到全部页面。 */
function openBackgroundImageDialog(fill: 'image' | 'gradient' = 'image') {
  if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; return }
  const slide = slideAt(selectedSlide), pendingGradient = backgroundGradientEdits.find(item => item.slideIndices.includes(selectedSlide)), sourceGradient = slide.backgroundGradient
  const gradient = pendingGradient ?? sourceGradient ?? { from: '#FFFFFF', to: '#4472C4', angleDeg: 90 as const, radial: false }
  const dialog = document.createElement('dialog'); dialog.className = 'slides-table-dialog slides-bg-image-dialog'; dialog.setAttribute('aria-label', '设置背景格式')
  dialog.innerHTML = '<header><h3>设置背景格式</h3></header><div class="slides-background-body"><label>填充 <select name="fill" aria-label="背景填充类型"><option value="image">图片</option><option value="gradient">渐变</option></select></label>'
    + '<div data-fill="image"><label>填充方式 <select name="mode" aria-label="背景图片填充方式"><option value="stretch">拉伸</option><option value="tile">平铺</option></select></label></div>'
    + '<div data-fill="gradient"><label>起始颜色 <input name="from" type="color" aria-label="渐变起始颜色"></label><label>结束颜色 <input name="to" type="color" aria-label="渐变结束颜色"></label><label>方向 <select name="direction" aria-label="渐变方向">'
    + GRADIENT_DIRECTIONS.map(([label], index) => `<option value="${index}">${label}</option>`).join('') + '</select></label></div>'
    + '<label class="slides-bg-image-all"><input name="graphics" type="checkbox"> 隐藏背景图形</label><label class="slides-bg-image-all"><input name="all" type="checkbox"> 应用到全部页面</label><p role="status" aria-label="背景设置状态" aria-live="polite" tabindex="0"></p><p role="alert" aria-label="背景设置错误" tabindex="0"></p></div>'
    + '<footer class="slides-table-actions"><button type="button" value="reset">重置背景</button><button type="button" value="cancel">取消</button><button type="button" value="ok">确定</button></footer>'
  const field = <T extends HTMLElement>(selector: string) => dialog.querySelector<T>(selector)!
  const showError = (message: string) => { const alert = field('[role=alert]'); alert.textContent = message; alert.scrollIntoView?.({ block: 'nearest' }) }
  let choosing = false
  const setChoosing = (value: boolean) => {
    choosing = value; dialog.setAttribute('aria-busy', String(value))
    for (const control of dialog.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>('input,select,button[value=ok],button[value=reset]')) control.disabled = value
    field('[role=status]').textContent = value ? '正在选择或读取图片…' : ''
    if (value) field<HTMLButtonElement>('button[value=cancel]').focus({ preventScroll: true })
  }
  const current = backgroundImageEdits.find(item => item.slideIndices.includes(selectedSlide))
  field<HTMLSelectElement>('select[name=mode]').value = (current?.tile ?? slide.backgroundImage?.mode === 'tile') ? 'tile' : 'stretch'
  field<HTMLSelectElement>('select[name=fill]').value = fill
  field<HTMLInputElement>('input[name=from]').value = gradient.from.toLowerCase(); field<HTMLInputElement>('input[name=to]').value = gradient.to.toLowerCase()
  field<HTMLSelectElement>('select[name=direction]').value = String(Math.max(0, GRADIENT_DIRECTIONS.findIndex(([, angle, radial]) => radial === gradient.radial && (radial || angle === gradient.angleDeg))))
  field<HTMLInputElement>('input[name=graphics]').checked = backgroundGraphicsEdits.get(selectedSlide) ?? !!slide.backgroundGraphicsHidden
  const sync = () => { const value = field<HTMLSelectElement>('select[name=fill]').value; for (const section of dialog.querySelectorAll<HTMLElement>('[data-fill]')) section.hidden = section.dataset.fill !== value
    field<HTMLButtonElement>('button[value=ok]').textContent = value === 'image' ? '选择图片…' : '确定' }
  field<HTMLSelectElement>('select[name=fill]').addEventListener('change', sync); sync()
  host.append(dialog)
  const targets = () => field<HTMLInputElement>('input[name=all]').checked ? deck.slides.map((_, index) => index).filter(index => !deletedSlides.has(index)) : [selectedSlide]
  /** 隐藏背景图形与来源一致时撤回该页修改。 */
  const applyGraphics = (slideIndices: number[]) => {
    const hidden = field<HTMLInputElement>('input[name=graphics]').checked
    for (const index of slideIndices) { if (hidden === !!deck.slides[index]?.backgroundGraphicsHidden) backgroundGraphicsEdits.delete(index); else backgroundGraphicsEdits.set(index, hidden) }
  }
  const finish = (message: string) => { dialog.close(); renderStructurePending(); renderInspector(); markDirty(); refreshCanvasPreview(); canvasStatus.textContent = message }
  field<HTMLButtonElement>('button[value=cancel]').addEventListener('click', () => dialog.close())
  field<HTMLButtonElement>('button[value=reset]').addEventListener('click', () => {
    // 固定源 reset：去掉本页自有背景，回到版式/母版背景；只有待保存修改的页直接撤回这些修改。
    const slideIndices = targets()
    dropBackgroundImages(slideIndices)
    for (const index of slideIndices) { backgroundEdits.delete(index); if (deck.slides[index]?.backgroundOwn) backgroundResetEdits.add(index) }
    finish(slideIndices.length > 1 ? '已暂存：全部页面重置为版式背景' : '已暂存：当前页重置为版式背景')
  })
  field<HTMLButtonElement>('button[value=ok]').addEventListener('click', async () => {
    if (choosing) return
    const slideIndex = selectedSlide, snapshot = JSON.stringify(slideChanges()), slideIndices = targets()
    if (field<HTMLSelectElement>('select[name=fill]').value === 'gradient') {
      const [, angleDeg, radial] = GRADIENT_DIRECTIONS[Number(field<HTMLSelectElement>('select[name=direction]').value)] ?? GRADIENT_DIRECTIONS[0]
      if (backgroundGradientEdits.length >= 20 && !backgroundGradientEdits.every(item => item.slideIndices.every(index => slideIndices.includes(index)))) { showError('待保存的渐变背景已达 20 组，请先保存'); return }
      dropBackgroundImages(slideIndices)
      for (const index of slideIndices) backgroundEdits.delete(index)
      backgroundGradientEdits.push({ slideIndices, from: field<HTMLInputElement>('input[name=from]').value.toUpperCase(), to: field<HTMLInputElement>('input[name=to]').value.toUpperCase(), angleDeg, radial })
      applyGraphics(slideIndices)
      finish(slideIndices.length > 1 ? '渐变背景已暂存到全部页面' : '渐变背景已暂存到当前页')
      return
    }
    const tile = field<HTMLSelectElement>('select[name=mode]').value === 'tile'
    field('[role=alert]').textContent = ''; setChoosing(true)
    try {
      const file = await pickSlideImage()
      if (!file || !dialog.open || !dialog.isConnected) return
      const image = await prepareSlideImage(file, deck.size)
      if (!dialog.open || !dialog.isConnected) return
      if (disposed || locked() || selectedSlide !== slideIndex || JSON.stringify(slideChanges()) !== snapshot) throw new Error('页面或草稿已变化，请重新选择背景图片')
      if (backgroundImageEdits.length >= 10 && !backgroundImageEdits.every(item => item.slideIndices.every(index => slideIndices.includes(index)))) throw new Error('待保存的背景图片已达 10 张，请先保存')
      dropBackgroundImages(slideIndices)
      for (const index of slideIndices) backgroundEdits.delete(index)
      backgroundImageEdits.push({ slideIndices, bytesBase64: image.bytesBase64, extension: image.extension, tile })
      applyGraphics(slideIndices)
      finish(slideIndices.length > 1 ? '背景图片已暂存到全部页面' : '背景图片已暂存到当前页')
    } catch (error) { if (dialog.open && dialog.isConnected) showError(error instanceof Error ? error.message : '背景图片处理失败，原文件保留') }
    finally { if (dialog.open && dialog.isConnected) setChoosing(false) }
  })
  showSlidesSettingsDialog(dialog)
}
function openSectionDialog() {
  const dialog = document.createElement('dialog'); dialog.className = 'slides-table-dialog slides-section-dialog'; dialog.setAttribute('aria-label', '新增节')
  dialog.innerHTML = '<header><h3>新增节</h3></header><div class="slides-settings-body"><label>节名称 <input name="name" type="text" maxlength="100" value="无标题节"></label><p role="alert" aria-label="新增节错误" tabindex="0"></p></div><footer class="slides-table-actions"><button type="button" value="cancel">取消</button><button type="button" value="ok">确定</button></footer>'
  host.append(dialog)
  dialog.querySelector<HTMLButtonElement>('button[value=cancel]')!.addEventListener('click', () => dialog.close())
  dialog.querySelector<HTMLButtonElement>('button[value=ok]')!.addEventListener('click', () => {
    const name = dialog.querySelector<HTMLInputElement>('input[name=name]')!.value.trim()
    if (!name || /[\u0000-\u001f\u007f]/.test(name)) { dialog.querySelector('[role=alert]')!.textContent = '请输入节名称'; return }
    if (sectionEdits.length >= 100) { dialog.querySelector('[role=alert]')!.textContent = '一次最多新增 100 个节；请先保存'; return }
    sectionEdits.push({ slideIndex: selectedSlide, name })
    dialog.close(); renderSlides(); renderStructurePending(); markDirty()
  })
  showSlidesSettingsDialog(dialog)
  dialog.querySelector<HTMLInputElement>('input[name=name]')!.select()
}
/** 固定源 Insert ▸ Table：待插入表格（行×列，1–75）；位置由引擎按固定源规格计算。 */
const tableEdits: { slideIndex: number; rows: number; cols: number }[] = []
// 对话框按需创建、关闭即移除，不常驻编辑器 DOM。
function openTableDialog() {
const tableDialog = document.createElement('dialog'); tableDialog.className = 'slides-table-dialog slides-insert-table-dialog'; tableDialog.setAttribute('aria-label', '插入表格')
tableDialog.innerHTML = '<header><h3>插入表格</h3></header><div class="slides-settings-body"><label>列数 <input name="cols" type="number" min="1" max="75" value="5"></label><label>行数 <input name="rows" type="number" min="1" max="75" value="2"></label><p role="alert" aria-label="插入表格错误" tabindex="0"></p></div><footer class="slides-table-actions"><button type="button" value="cancel">取消</button><button type="button" value="ok">确定</button></footer>'
host.append(tableDialog)
tableDialog.querySelector<HTMLButtonElement>('button[value=cancel]')!.addEventListener('click', () => tableDialog.close())
tableDialog.querySelector<HTMLButtonElement>('button[value=ok]')!.addEventListener('click', () => {
  const read = (name: string) => Number(tableDialog.querySelector<HTMLInputElement>(`input[name=${name}]`)!.value)
  const rows = read('rows'), cols = read('cols')
  if (![rows, cols].every(value => Number.isInteger(value) && value >= 1 && value <= 75)) { tableDialog.querySelector('[role=alert]')!.textContent = '行数和列数须为 1–75 的整数'; return }
  if (tableEdits.length >= 100) { tableDialog.querySelector('[role=alert]')!.textContent = '一次最多插入 100 个表格；请先保存'; return }
  tableEdits.push({ slideIndex: selectedSlide, rows, cols })
  tableDialog.close()
  canvasStatus.textContent = '新增表格将在保存并打开新修订后显示在画布中。'
  renderStructurePending(); markDirty()
})
showSlidesSettingsDialog(tableDialog)
}
function paragraphCount(element: DeckElement) {
  const pending = edits.get(editKey(selectedSlide, element.id))?.text
  if (pending !== undefined) return pending.split(/\r?\n/).length
  return element.paragraphFormatting?.length ?? element.paragraphAlignments?.length ?? (element.text ? element.text.split('\n').length : 0) }
function sourceAnimations(): SourceAnimation[] { return isNewSlide(selectedSlide) ? [] : deck.slides[selectedSlide]?.animations ?? [] }
/** 新增页保存重开前没有可寻址对象，不能编辑动画。 */
function animationUnavailable() { return locked() || isNewSlide(selectedSlide) || selectedObjects.size!==1 }
/** 当前页的动画列表：已有整页序列则用它，否则由来源动画与尚未保存的逐条修改推导（不写入草稿）。 */
function currentSequence(): SequenceItem[] {
  return animationSequences.get(selectedSlide) ?? initialSequence(sourceAnimations(), animationEdits.filter(item => item.slideIndex === selectedSlide).map(({ slideIndex: _slideIndex, ...rest }) => rest))
}
function updateSequence(change: (items: SequenceItem[]) => SequenceItem[]) {
  if (animationUnavailable()) return
  try {
    const before = currentSequence(), next = change(before)
    if (next === before) return
    // 首次整页编辑时把本页逐条修改折叠进序列，避免同页两种写法并存（桥接会拒绝）。
    for (let index = animationEdits.length - 1; index >= 0; index--) if (animationEdits[index]!.slideIndex === selectedSlide) animationEdits.splice(index, 1)
    if (sequenceUnchanged(next, sourceAnimations())) animationSequences.delete(selectedSlide)
    else animationSequences.set(selectedSlide, next)
    if (selectedAnimationRow >= next.length) selectedAnimationRow = -1
    markDirty()
  } catch (error) { statusMessage.textContent = error instanceof Error ? error.message : String(error) }
}
const animationPane = document.createElement('section')
animationPane.className = 'slides-animation-pane'; animationPane.setAttribute('aria-label', '动画窗格'); animationPane.hidden = true
root.querySelector('.slides-inspector')!.prepend(animationPane)
function focusAnimationControl(index: number, action?: string) {
  const entry = animationPane.querySelector<HTMLElement>(`[data-animation-row="${index}"]`)
  const control = action ? entry?.querySelector<HTMLButtonElement>(`[data-animation-action="${action}"]:not([disabled])`) : undefined
  ;(control ?? entry?.querySelector<HTMLButtonElement>('.animation-pane-select') ?? animationPane.querySelector<HTMLButtonElement>('[data-animation-pane-close]'))?.focus()
}
/** 固定源 AnimationPane：当前页动画顺序列表，选择/上移/下移/删除；计时由 Ribbon 计时组修改选中行。 */
function renderAnimationPane() {
  animationPane.hidden = !animationPaneOpen
  if (!animationPaneOpen) return
  const scrollTop = animationPane.dataset.slideIndex === String(selectedSlide) ? animationPane.querySelector('ol')?.scrollTop ?? 0 : 0
  animationPane.dataset.slideIndex = String(selectedSlide)
  const items = currentSequence(), source = sourceAnimations(), steps = stepNumbers(items, source), slide = slideAt(selectedSlide)
  const heading = document.createElement('div'); heading.className = 'inspector-heading'
  const title = document.createElement('span'); title.textContent = `动画 · 第 ${order.indexOf(selectedSlide) + 1} 页`
  const close = buttonIcon(X, '关闭动画窗格'); close.dataset.animationPaneClose = ''
  close.addEventListener('click', () => {
    animationPaneOpen = false; selectedAnimationRow = -1; renderInspector()
    const opener = root.querySelector<HTMLButtonElement>('[data-command="toggleAnimationPane"]')
    const target = opener && !opener.disabled && !opener.closest('[hidden]') ? opener : root.querySelector<HTMLButtonElement>('.slides-native-ribbon-tabs [aria-selected="true"]')
    target?.focus()
  })
  heading.append(title, close)
  const list = document.createElement('ol'); list.className = 'animation-pane-list'
  const disabled = animationUnavailable()
  items.forEach((item, index) => {
    const row = resolvedItem(item, source), element = slide.elements.find(candidate => candidate.id === row.elementId)
    const entry = document.createElement('li'); entry.className = 'animation-pane-row'; entry.dataset.animationRow = String(index)
    if (index === selectedAnimationRow) entry.classList.add('is-selected')
    const select = document.createElement('button'); select.type = 'button'; select.className = 'animation-pane-select'; select.setAttribute('aria-pressed', String(index === selectedAnimationRow))
    const targetName = element ? element.name || element.text.split('\n')[0]?.slice(0, 24) || element.type : '对象已不存在'
    const seconds = (value: number) => (value / 1000).toFixed(2)
    select.textContent = `${steps[index] || '·'} ${EFFECT_LABELS[row.effect] ?? row.effect} · ${targetName}${row.paragraph !== undefined ? ` · 第 ${row.paragraph + 1} 段` : ''}`
    select.title = `${select.textContent}\n${TRIGGER_LABELS[row.trigger]} · ${seconds(row.durationMs)} 秒${row.delayMs ? ` · 延迟 ${seconds(row.delayMs)} 秒` : ''}${row.readonlyTiming ? ' · 原样保留的预设效果，只能移动或删除' : ''}`
    select.addEventListener('keydown', event => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || !['Home', 'End'].includes(event.key)) return
      event.preventDefault(); select.scrollTop = event.key === 'Home' ? 0 : select.scrollHeight
    })
    select.addEventListener('click', () => { selectedAnimationRow = selectedAnimationRow === index ? -1 : index; renderInspector(); focusAnimationControl(index) })
    const detail = document.createElement('span'); detail.className = 'animation-pane-detail'; detail.textContent = `${TRIGGER_LABELS[row.trigger]} · ${seconds(row.durationMs)} 秒`
    const action = (label: string, title: string, run: () => void, off: boolean) => {
      const control = document.createElement('button'); control.type = 'button'; control.textContent = label; control.title = title; control.setAttribute('aria-label', `${title}：第 ${index + 1} 条动画`); control.disabled = disabled || off
      control.dataset.animationAction = title
      control.addEventListener('click', run); return control
    }
    const move = (direction: -1 | 1) => () => {
      updateSequence(current => moveSequenceItem(current, index, direction))
      if (selectedAnimationRow === index) selectedAnimationRow = index + direction
      else if (selectedAnimationRow === index + direction) selectedAnimationRow = index
      renderInspector()
      focusAnimationControl(index + direction, direction === -1 ? '上移' : '下移')
    }
    const actions = document.createElement('span'); actions.className = 'animation-pane-actions'
    actions.append(action('↑', '上移', move(-1), index === 0), action('↓', '下移', move(1), index === items.length - 1), action('✕', '删除', () => {
      updateSequence(current => deleteSequenceItem(current, index))
      selectedAnimationRow = selectedAnimationRow === index ? -1 : selectedAnimationRow > index ? selectedAnimationRow - 1 : selectedAnimationRow
      renderInspector()
      focusAnimationControl(Math.min(index, currentSequence().length - 1))
    }, false))
    entry.append(select, detail, actions); list.append(entry)
  })
  const empty = document.createElement('p'); empty.className = 'animation-pane-empty'
  empty.textContent = isNewSlide(selectedSlide) ? NEW_SLIDE_REASON : items.length ? '选中一条动画后，可用“计时”组修改触发方式、时长与延迟。' : '本页还没有动画。选择对象后在“动画”选项卡添加。'
  animationPane.replaceChildren(heading, list, empty)
  list.scrollTop = scrollTop
}
/** 透明度可用性：单选、来源为单一嵌入位图的普通图片、没有待保存的替换。 */
function opacityReason(): string | null {
  const element = currentElement()
  if (isNewSlide(selectedSlide)) return NEW_SLIDE_REASON
  if (selectedObjects.size !== 1 || element?.type !== 'picture') return '请选择一张图片'
  if (!element.pictureOpacityEditable || !element.pictureSha256 || !element.pictureSize) return element.pictureOpacityReason ?? '此图片暂不支持调整透明度'
  if (pictureReplacements.some(item => item.slideIndex === selectedSlide && item.elementId === element.id)) return '请先保存或撤回此图片的替换'
  if (!pictureOpacities.some(item => item.slideIndex === selectedSlide && item.elementId === element.id) && pictureOpacities.length >= 50) return '待保存的图片透明度修改已达 50 项，请先保存'
  return null
}
function slideHasPendingEdits(slideIndex: number, ignoreNewSlideSources = false) {
  return backgroundImageReuseEdits.some(item=>item.slideIndices.includes(slideIndex)) || backgroundImageEdits.some(item => item.slideIndices.includes(slideIndex)) || backgroundGradientEdits.some(item => item.slideIndices.includes(slideIndex)) || backgroundResetEdits.has(slideIndex) || backgroundGraphicsEdits.has(slideIndex) || pictureOpacities.some(item => item.slideIndex === slideIndex) || notesEdits.has(slideIndex) || [...edits.values(), ...textFormattingEdits.values(), ...paragraphFormattingEdits, ...animationEdits, ...textBoxEdits, ...deletions.values(), ...imageEdits].some(item => item.slideIndex === slideIndex) || animationSequences.has(slideIndex) || elementOrders.has(slideIndex) || pendingGroup(slideIndex) || linkEdits.some(item=>item.slideIndex===slideIndex) || clipboardPastes.some(item=>item.slideIndex===slideIndex||item.sourceSlideIndex===slideIndex)
    || commentPane.hasDraft(slideIndex) || commentEdits.some(edit => edit.slideIndex === slideIndex) || hiddenSlideEdits.has(slideIndex) || transitionEdits.has(slideIndex) || layoutEdits.has(slideIndex) || backgroundEdits.has(slideIndex) || resetLayouts.has(slideIndex) || shapeEdits.some(item => item.slideIndex === slideIndex) || tableEdits.some(item => item.slideIndex === slideIndex) || [...shapeStyleEdits.values(), ...shapeKindEdits.values(), ...sectionEdits, ...tableCellEdits.values(), ...tableStyleEdits.values(), ...tableStructureEdits.values(), ...chartEdits, ...smartArtEdits, ...mediaInsertions, ...nativeImages, ...pictureReplacements, ...pictureCrops, ...nativeChartEdits].some(item => item.slideIndex === slideIndex)
    || (deck.slides[slideIndex]?.elements ?? []).some(element => chartTools.hasPending(slideIndex, element.id))
    || (!ignoreNewSlideSources && newSlides.some(item => newSlideSource(item) === slideIndex))
}
function deleteSourceSlide(slideIndex: number) {
  if (notesPane && !notesPane.flush()) return
  if (!deck || locked() || isNewSlide(slideIndex) || order.length <= 1) return
  if (slideHasPendingEdits(slideIndex)) { statusMessage.textContent = '该页有待保存修改或被新建页沿用版式，请先撤销或保存后再删除'; return }
  const position = order.indexOf(slideIndex)
  order.splice(position, 1); deletedSlides.add(slideIndex)
  selectedSlide = order[Math.min(position, order.length - 1)]!; selectedElement = ''
  undoSnapshot = undefined; undoButton.disabled = true
  renderSlides(); renderInspector(); markDirty()
}
const NEW_SLIDE_REASON = '新建的幻灯片保存并重新打开后才能编辑内容、背景、版式与转场'
const isNewSlide = (slideIndex: number) => !!deck && slideIndex >= deck.slides.length
function slideAt(slideIndex: number): DeckSlide {
  const source = deck.slides[slideIndex]
  if (source) {
    const rendered=typeof renderTree==='undefined'?undefined:renderTree?.slides.find(item=>item.slideIndex===slideIndex)
    const sources=rendered?.modelSources??[],known=new Set(source.elements.map(item=>item.id))
    return {...source,elements:[...source.elements.map(element=>{const model=sources.find(item=>item.sourceId===element.id);return model?{...element,model3d:model}:element}),...sources.filter(item=>!known.has(item.sourceId)).map(item=>({id:item.sourceId,type:'picture',name:'3D 模型',text:'',editable:false,deletable:false,model3d:item}))]}
  }
  const item = newSlides[slideIndex - deck.slides.length]
  const sourceIndex = item ? newSlideSource(item) : null
  const layoutSource = sourceIndex === null ? undefined : deck.slides[sourceIndex]
  if (item && 'withLayout' in item) return { slideIndex, elements: [], layoutPath: item.withLayout, masterPath: deck.slides[0]?.masterPath, themePath: deck.slides[0]?.themePath, transition: 'none', transitionEditSafe: false, transitionEditReason: NEW_SLIDE_REASON, transitionApplyAllSafe: false, transitionApplyAllReason: NEW_SLIDE_REASON, animations: [] }
  // 副本展示来源页已保存内容，但保存重开前只读（对象不可编辑/删除）。
  if (item && 'duplicateOf' in item && layoutSource) return { ...layoutSource, slideIndex, elements: layoutSource.elements.map(element => ({ ...element, editable: false, deletable: false })), transitionEditSafe: false, transitionEditReason: NEW_SLIDE_REASON, transitionApplyAllSafe: false, transitionApplyAllReason: NEW_SLIDE_REASON, animations: [] }
  return { slideIndex, elements: [], layoutPath: layoutSource?.layoutPath, masterPath: layoutSource?.masterPath, themePath: layoutSource?.themePath, transition: 'none', transitionEditSafe: false, transitionEditReason: NEW_SLIDE_REASON, transitionApplyAllSafe: false, transitionApplyAllReason: NEW_SLIDE_REASON, animations: [] }
}
function addNewSlide() {
  if (notesPane && !notesPane.flush()) return
  if (!deck || locked()) return
  if (newSlides.length >= 50 || order.length >= 500) { statusMessage.textContent = '一次最多新建 50 张幻灯片；请先保存'; return }
  const selectedNew = isNewSlide(selectedSlide) ? newSlides[selectedSlide - deck.slides.length]! : undefined
  newSlides.push(selectedNew && 'withLayout' in selectedNew ? { withLayout: selectedNew.withLayout } : { layoutFrom: selectedNew ? newSlideSource(selectedNew)! : selectedSlide })
  const slideIndex = deck.slides.length + newSlides.length - 1
  order.splice(order.indexOf(selectedSlide) + 1, 0, slideIndex)
  selectedSlide = slideIndex; selectedElement = ''
  undoSnapshot = undefined; undoButton.disabled = true
  renderSlides(); renderInspector(); markDirty()
}
/** 固定源 duplicateSlide：在来源页之后插入其已保存内容的副本；来源页有待保存修改时拒绝，避免副本只带部分修改。 */
function duplicateSourceSlide(slideIndex: number) {
  if (notesPane && !notesPane.flush()) return
  if (!deck || locked() || isNewSlide(slideIndex)) return
  if (newSlides.length >= 50 || order.length >= 500) { statusMessage.textContent = '一次最多新建 50 张幻灯片；请先保存'; return }
  if (slideHasPendingEdits(slideIndex, true)) { statusMessage.textContent = '该页有待保存修改，请先保存后再复制'; return }
  newSlides.push({ duplicateOf: slideIndex })
  const created = deck.slides.length + newSlides.length - 1
  order.splice(order.indexOf(slideIndex) + 1, 0, created)
  selectedSlide = created; selectedElement = ''
  undoSnapshot = undefined; undoButton.disabled = true
  renderSlides(); renderInspector(); markDirty()
}
function newSlideTitle(item: NewSlide) {
  if ('duplicateOf' in item) return `副本：${flatText(deck.slides[item.duplicateOf]!)}（保存后写入）`
  if ('withLayout' in item) {
    const layout = (deck.layouts ?? []).find(layout => layout.path === item.withLayout)
    return `新建幻灯片 · ${layout ? slidesLayoutLabel(layout) : item.withLayout}（保存后写入）`
  }
  return '新建幻灯片（保存后写入）'
}
/** 固定源 onAddSlideWithLayout：在当前页后新建所选版式的幻灯片（版式占位符由引擎生成）。 */
function addSlideWithLayout(layoutPath: string) {
  if (notesPane && !notesPane.flush()) return
  if (!deck || locked() || !layoutPath) return
  if (!(deck.layouts ?? []).some(layout => layout.path === layoutPath)) { statusMessage.textContent = '版式不存在，请重新打开'; return }
  if (newSlides.length >= 50 || order.length >= 500) { statusMessage.textContent = '一次最多新建 50 张幻灯片；请先保存'; return }
  newSlides.push({ withLayout: layoutPath })
  const created = deck.slides.length + newSlides.length - 1
  order.splice(order.indexOf(selectedSlide) + 1, 0, created)
  selectedSlide = created; selectedElement = ''
  undoSnapshot = undefined; undoButton.disabled = true
  renderSlides(); renderInspector(); markDirty()
}
function removeNewSlide(slideIndex: number) {
  if (notesPane && !notesPane.flush()) return
  if (!isNewSlide(slideIndex) || locked()) return
  const position = order.indexOf(slideIndex)
  newSlides.splice(slideIndex - deck.slides.length, 1)
  order.splice(position, 1)
  for (let index = 0; index < order.length; index++) if (order[index]! > slideIndex) order[index]! -= 1
  // Sections reference slide identities, not positions in the visible order.
  // Removing a pending slide must also drop its section and shift later IDs.
  for (let index = sectionEdits.length - 1; index >= 0; index--) {
    const section = sectionEdits[index]!
    if (section.slideIndex === slideIndex) sectionEdits.splice(index, 1)
    else if (section.slideIndex > slideIndex) section.slideIndex -= 1
  }
  selectedSlide = order[Math.max(0, position - 1)]!
  renderSlides(); renderInspector(); markDirty()
}
const backgroundEdits = new Map<number, string>()
const backgroundImageEdits: NonNullable<SlideChanges['backgroundImages']> = []
const backgroundImageReuseEdits:BackgroundImageReuse[]=[]
const backgroundGradientEdits: NonNullable<SlideChanges['backgroundGradients']> = []
const backgroundResetEdits = new Set<number>()
const backgroundGraphicsEdits = new Map<number, boolean>()
const textBoxEdits: TextBoxEdit[] = []
const textFormattingEdits = new Map<string, TextFormatting>()
const paragraphFormattingEdits: ParagraphFormatting[] = []
const deletions = new Map<string, { slideIndex: number; elementId: string; label: string }>()
const masterTextEdits: MasterTextEdit[] = []
const masterElementEdits: MasterElementEdit[] = []
const edits = new Map<string, Edit>()
const imageEdits: ImageEdit[] = []
const animationEdits: AnimationEdit[] = []
/** 整页动画序列（动画窗格/无/动作路径/按段）；键为来源页序号。 */
const animationSequences = new Map<number, SequenceItem[]>()
let animationPaneOpen = false
let selectedAnimationRow = -1
let animationByParagraph = false
const commentEdits: CommentEdit[] = []
let commentsPaneOpen = false
const hiddenSlideEdits = new Map<number, boolean>()
const transitionEdits = new Map<number, SlideTransition>()
const layoutEdits = new Map<number, string>()
let slideSizeEdit: { cx: number; cy: number } | undefined
let animationDirection: AnimationDirection = 'bottom'
let animationDurationMs = 500
let animationDelayMs = 0
let undoSnapshot: { order: number[]; edits: Edit[]; theme?: BusinessTheme } | undefined
let activeAIEditId = ''
let pendingAIEditId = ''
let pendingAIProposal: AIProposal | undefined
let selectedTheme: BusinessTheme | undefined
let generatedImage: GeneratedImage | undefined
let deck: Deck
let selectedSlide = 0
let selectedElement = ''
let selectedObjects = new Set<string>()
let selectionSlide = -1
let explicitEmptySelection = false
let dirty = false
let disposed = false
let structureDialog: HTMLDialogElement | undefined
let printDialog:ReturnType<typeof import('./slides-print-dialog').openSlidesPrintDialog>|undefined
let printOpening=false
let structureDialogGeneration = 0
let savedRevision = false
let saving = false
let refresh: Awaited<ReturnType<typeof mountOfficeReportRefresh>>
let loading = true
let mutationPending = 0
const locked = () => disposed || saving || savedRevision || nativeDraft?.closed === true || nativeDraft?.saving === true
let nativeUndo: HTMLButtonElement | undefined
let nativeRedo: HTMLButtonElement | undefined
function updateNativeHistory() {
  if (nativeUndo) nativeUndo.disabled = locked() || !nativeDraft?.canUndo
  if (nativeRedo) nativeRedo.disabled = locked() || !nativeDraft?.canRedo
}
const lockFields = new Map<HTMLInputElement | HTMLButtonElement | HTMLTextAreaElement | HTMLSelectElement, boolean>()
function setEditingLocked(value: boolean) {
  root.inert = value
  for (const field of root.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLTextAreaElement | HTMLSelectElement>('input, button, textarea, select')) {
    if (value) { if (!lockFields.has(field)) lockFields.set(field, field.disabled); field.disabled = true }
    else { field.disabled = lockFields.get(field) ?? field.disabled }
  }
  nativeRibbon?.setLocked(value)
  if(value)inkControls?.cancel();inkControls?.update()
  chartFormatPane?.setLocked(value)
  geometryPane?.setLocked(value)
  backgroundPane?.setLocked(value)
  shapeFormatPane?.setLocked(value)
  if (!value) lockFields.clear()
  updateNativeHistory()
  renderCanvas()
}
for (const kind of ['click', 'input', 'change', 'submit']) root.addEventListener(kind, event => {
  if (locked() && !(savedRevision && event.target instanceof Element && event.target.closest('a'))) { event.preventDefault(); event.stopImmediatePropagation() }
}, true)

let renderTree: { masterTextParts?: MasterTextRenderPart[]; slides: (RenderSlide & { slideIndex: number; slideIdentity?: string; mediaSources?:SlideMediaSource[];modelSources?:ModelSource[] })[] } | undefined
let slidesViewMode: 'normal' | 'outline' | 'sorter' | 'reading' = 'normal'
let slideSorter: ReturnType<typeof createSlidesSorter> | undefined
let slideOutline: ReturnType<typeof createSlidesOutline> | undefined
let slideReading: ReturnType<typeof createSlidesReading> | undefined
let sorterLoading: Promise<void> | undefined
let outlineReadingLoading: Promise<void> | undefined
const sorterHost = document.createElement('div')
sorterHost.hidden = true
root.querySelector<HTMLElement>('.slides-workspace')!.append(sorterHost)
const outlineHost = document.createElement('div'), readingHost = document.createElement('div')
outlineHost.hidden = true; readingHost.hidden = true
root.querySelector<HTMLElement>('.slides-sidebar')!.append(outlineHost)
root.querySelector<HTMLElement>('.slides-workspace')!.append(readingHost)
function syncSlidesViewMode() {
  for (const [command, mode] of [['normalView', 'normal'], ['outlineView', 'outline'], ['slideSorter', 'sorter'], ['readingView', 'reading']]) nativeRibbon?.setValue(command!, String(slidesViewMode === mode))
}
async function setSlidesViewMode(mode: typeof slidesViewMode) {
  if (disposed || locked() || !deck || (notesPane && !notesPane.flush()) || !commentPane.flush()) { syncSlidesViewMode(); return }
  stopBrush(); selectObjects('')
  slidesViewMode = mode
  root.querySelector<HTMLElement>('.slides-workspace')!.dataset.viewMode = mode
  sorterHost.hidden = mode !== 'sorter'
  outlineHost.hidden = mode !== 'outline'; readingHost.hidden = mode !== 'reading'
  nativeRibbon?.setContext(null)
  syncSlidesViewMode()
  if (mode === 'normal') { renderCanvas(); canvasHost.focus({ preventScroll: true }); return }
  if (mode === 'outline' || mode === 'reading') {
    outlineReadingLoading ??= import('./slides-outline-reading').then(({ createSlidesOutline, createSlidesReading }) => {
      if (disposed) return
      const options = {
        onSelect(id: number) {
          if (locked() || !order.includes(id) || (notesPane && !notesPane.flush()) || !commentPane.flush()) return false
          selectedSlide = id; selectObjects(''); renderSlides(); renderInspector(); return true
        },
        onDelete: deleteSorterSlides,
        onNormal: () => { void setSlidesViewMode('normal') },
      }
      slideOutline = createSlidesOutline(outlineHost, options); slideReading = createSlidesReading(readingHost, options)
    }).catch(() => { if (!disposed) statusMessage.textContent = '大纲或阅读视图未能载入，请切回普通视图后重试'; outlineReadingLoading = undefined })
    await outlineReadingLoading
    if (disposed || slidesViewMode !== mode) return
    renderSlideSorter()
    if (mode === 'outline') slideOutline?.focus(); else slideReading?.focus()
    return
  }
  if (!slideSorter) {
    sorterHost.textContent = '正在载入幻灯片缩略图…'
    sorterLoading ??= import('./slides-view-modes').then(({ createSlidesSorter }) => {
      if (disposed) return
      sorterHost.replaceChildren()
      slideSorter = createSlidesSorter(sorterHost, {
        onSelect(id) {
          if (locked() || !order.includes(id) || (notesPane && !notesPane.flush()) || !commentPane.flush()) return false
          selectedSlide = id; selectObjects(''); renderSlides(); renderInspector(); return true
        },
        onMove(ids, insertAt) {
          if (locked() || (notesPane && !notesPane.flush()) || !commentPane.flush()) return false
          if (ids.some(id => !order.includes(id)) || !ids.length || insertAt < 0 || insertAt > order.length) return false
          const block = order.filter(id => ids.includes(id)), rest = order.filter(id => !ids.includes(id))
          const at = insertAt - order.slice(0, insertAt).filter(id => ids.includes(id)).length
          const next = [...rest.slice(0, at), ...block, ...rest.slice(at)]
          if (next.every((id, position) => id === order[position])) return true
          order.splice(0, order.length, ...next)
          undoSnapshot = undefined; undoButton.disabled = true
          renderSlides(); renderInspector(); markDirty(); return true
        },
        onDelete: deleteSorterSlides,
        onNormal: () => { void setSlidesViewMode('normal') },
      })
    }).catch(() => { if (!disposed) sorterHost.textContent = '缩略图未能载入，请切回普通视图后重试'; sorterLoading = undefined })
  }
  await sorterLoading
  if (disposed || slidesViewMode !== 'sorter') return
  renderSlideSorter(); slideSorter?.focus()
}
function deleteSorterSlides(ids: number[]) {
  if (locked() || (notesPane && !notesPane.flush()) || !commentPane.flush()) return
  if (!ids.length || ids.some(id => !order.includes(id)) || ids.length >= order.length) { statusMessage.textContent = '至少保留一张幻灯片'; return }
  if (ids.some(id => !isNewSlide(id) && slideHasPendingEdits(id))) { statusMessage.textContent = '选择中有页面存在待保存修改或被新建页沿用版式，请先撤销或保存后再删除'; return }
  const position = Math.min(...ids.map(id => order.indexOf(id)))
  for (const id of [...ids].sort((a, b) => b - a)) {
    order.splice(order.indexOf(id), 1)
    if (!isNewSlide(id)) { deletedSlides.add(id); continue }
    newSlides.splice(id - deck.slides.length, 1)
    for (let index = 0; index < order.length; index++) if (order[index]! > id) order[index]! -= 1
    for (let index = sectionEdits.length - 1; index >= 0; index--) {
      const section = sectionEdits[index]!
      if (section.slideIndex === id) sectionEdits.splice(index, 1)
      else if (section.slideIndex > id) section.slideIndex -= 1
    }
  }
  selectedSlide = order[Math.min(position, order.length - 1)]!; selectObjects('')
  undoSnapshot = undefined; undoButton.disabled = true
  renderSlides(); renderInspector(); markDirty()
}
function slideForView(slideIndex: number) {
  const source = renderTree?.slides.find(item => item.slideIndex === slideIndex)
  const pending = isNewSlide(slideIndex) ? newSlides[slideIndex - deck.slides.length] : undefined
  const sourceIndex = pending ? newSlideSource(pending) : null
  const layout = pending ? (sourceIndex === null ? renderTree?.slides[0] : renderTree?.slides.find(item => item.slideIndex === sourceIndex)) : undefined
  return source ?? (layout ? { ...layout, slideIndex, nodes: pending && 'duplicateOf' in pending ? layout.nodes : [] } : undefined)
}
function renderSlideSorter() {
  if ((!slideSorter && !slideOutline && !slideReading) || !deck) return
  const state = { current: selectedSlide, locked: locked(), slides: order.map(id => {
    const source = slideAt(id), slide = slideForView(id)
    return { id, title: isNewSlide(id) ? newSlideTitle(newSlides[id - deck.slides.length]!) : flatText(source), hidden: hiddenSlideEdits.get(id) ?? source.hidden ?? false,
      slide: slide ? applyCanvasEdits(slide, [...edits.values()].filter(item => item.slideIndex === id)) : undefined }
  }) }
  slideSorter?.update(state); slideOutline?.update(state); slideReading?.update(state)
}
let inkControls:ReturnType<typeof mountSlidesInk>|undefined
let canvas: { update: (state: SlidesCanvasState) => void; destroy?: () => void } | undefined
let previewSequence = 0
let previewTimer: ReturnType<typeof setTimeout> | undefined
// 每个页面最多一个预览请求在途：服务端每次预览要启动两个引擎进程，连续输入时
// 只在上一请求结束后用最新修改补发一次，过期结果直接丢弃。
let previewInFlight = false
let previewQueued = false
function refreshCanvasPreview() {
  if (!canvas || locked()) return
  ++previewSequence
  clearTimeout(previewTimer)
  canvasStatus.textContent = '正在更新文字与版式预览…'
  previewTimer = setTimeout(sendCanvasPreview, 450)
}
function sendCanvasPreview() {
  if (!canvas || locked()) return
  if (previewInFlight) { previewQueued = true; return }
  previewInFlight = true
  const sequence = previewSequence
  void request<{ slides: (RenderSlide & { slideIndex: number;mediaSources?:SlideMediaSource[];modelSources?:ModelSource[] })[] }>('render-tree', {
    method: 'POST', body: JSON.stringify(native
      ? { expectedSha256: deck.sha256, operations: [{ kind: 'editSlides', ...(masterElementEdits.length ? { masterElementEdits: structuredClone(masterElementEdits) } : {}), ...(masterTextEdits.length ? { masterTextEdits: structuredClone(masterTextEdits) } : {}), edits: [...edits.values()], textFormatting: [...textFormattingEdits.values()], paragraphFormatting: [...paragraphFormattingEdits.values()], tableCells: [...tableCellEdits.values()], tableStyles: [...tableStyleEdits.values()], ...(modelInsertions.length?{modelInsertions:structuredClone(modelInsertions)}:{}),...(modelViews.length?{modelViews:structuredClone(modelViews)}:{}),...(mediaInsertions.length?{mediaInsertions:structuredClone(mediaInsertions)}:{}),...(zoomInsertions.length?{zoomInsertions:structuredClone(zoomInsertions)}:{}), backgrounds:slideChanges().backgrounds,backgroundImages:slideChanges().backgroundImages,backgroundImageReuses:slideChanges().backgroundImageReuses,backgroundGradients:slideChanges().backgroundGradients,backgroundResets:slideChanges().backgroundResets,backgroundGraphics:slideChanges().backgroundGraphics,customShows:slideChanges().customShows }] }
      : { expectedSha256: deck.sha256, edits: [...edits.values()] }),
  }).then(tree => {
    if (sequence !== previewSequence || locked()) return
    renderTree = tree
    renderInspector()
    renderCanvas()
    canvasStatus.textContent = '点击对象选择，拖动调整位置，拖动角点缩放'
  }).catch(() => {
    if (sequence === previewSequence) canvasStatus.textContent = '文字修改已保留；即时预览暂不可用，保存并打开新修订后更新。'
  }).finally(() => {
    previewInFlight = false
    if (previewQueued) { previewQueued = false; sendCanvasPreview() }
  })
}

const canvasHost = root.querySelector<HTMLElement>('.slides-canvas')!
if (native) canvasHost.tabIndex = 0
const onMediaDragOver=(event:DragEvent)=>{if(native&&event.dataTransfer?.types.includes('Files'))event.preventDefault()}
const onMediaDrop=(event:DragEvent)=>{
  const file=event.dataTransfer?.files[0];if(!native||!file)return
  const kind=classifyDroppedFile(file.name,file.type);if(kind!=='audio'&&kind!=='video')return
  event.preventDefault();event.stopPropagation()
  const rect=(canvasHost.querySelector<HTMLElement>('.konvajs-content')??canvasHost).getBoundingClientRect(),size=slideSizeEdit??deck.size
  const center=rect.width>0&&rect.height>0?{x:Math.max(0,Math.min(size.cx,(event.clientX-rect.left)/rect.width*size.cx)),y:Math.max(0,Math.min(size.cy,(event.clientY-rect.top)/rect.height*size.cy))}:undefined
  void chooseNativeMedia(kind,file,center)
}
canvasHost.addEventListener('dragover',onMediaDragOver);canvasHost.addEventListener('drop',onMediaDrop)
/** 固定源 View ▸ Gridlines：纯视图状态（不写入文件）；网格间距 48px = 0.5 英寸，随幻灯片尺寸换算为画布百分比。 */
let gridVisible = false
let rulerVisible = false
let guidesVisible = false
const slidePx = () => { const size = slideSizeEdit ?? deck.size; return { width: size.cx / 9525, height: size.cy / 9525 } }
const slideContent = () => canvasHost.querySelector<HTMLElement>('.konvajs-content')
const guides = mountSlidesGuides(slideContent, slidePx, `native-slides-guides:${location.pathname.replace(/\/\d+$/, '')}`, visible => { guidesVisible = visible; nativeRibbon?.setValue('guides', String(visible)) })
const ruler = mountSlidesRuler(root.querySelector<HTMLElement>('.slides-stage')!, slideContent, slidePx, 'cm', (axis, client, done) => guides.pull(axis, client, done), () => guides.cancelPull())
function syncGrid() {
  ruler.update(); nativeRibbon?.setValue('ruler', String(rulerVisible)); nativeRibbon?.setValue('guides', String(guidesVisible))
  const size = slideSizeEdit ?? deck.size
  canvasHost.dataset.grid = String(gridVisible)
  canvasHost.style.setProperty('--slides-grid-x', `${(457200 / size.cx) * 100}%`)
  canvasHost.style.setProperty('--slides-grid-y', `${(457200 / size.cy) * 100}%`)
  nativeRibbon?.setValue('grid', String(gridVisible))
}
const canvasStatus = root.querySelector<HTMLElement>('.canvas-status')!

let canvasSelectionGeneration = 0
function renderCanvas() {
  backgroundPane?.update(backgroundPaneSlide(),backgroundPaneKey(),locked())
  mediaPlayback?.dispose();mediaPlayback=undefined
  animationPreviewOverlay?.dispose()
  renderSlideSorter()
  const source = renderTree?.slides.find(item => item.slideIndex === selectedSlide)
  geometryPane?.setPictureSource(editKey(selectedSlide,selectedElement),source?.nodes.find(node=>node.sourceId===selectedElement),pictureReplacements.some(item=>item.slideIndex===selectedSlide&&item.elementId===selectedElement))
  // 新建页没有来源 RenderTree：沿用版式来源页的画布尺寸与背景，不含任何对象。
  const rawSlide = slideForView(selectedSlide)
  const slide = rawSlide&&native ? inkSlide(rawSlide,selectedSlide,slideChanges()) : rawSlide
  if (!canvas || !slide || !deck) return
  inkControls?.update()
  ruler.update()
  queueMicrotask(() => guides.render())
  const selectionGeneration=++canvasSelectionGeneration, canvasSlide=selectedSlide, canvasSource=deck.sha256
  const rank=new Map((elementOrders.get(selectedSlide)??[]).map((id,index)=>[id,index]))
  // 固定渲染树的图表附属装饰紧随宿主；块整体移动，页首母版装饰保留在底层。
  const prefix:RenderSlide['nodes']=[],blocks:RenderSlide['nodes'][]=[]
  for(const node of slide.nodes){
    if(node.decoration){if(blocks.length)blocks[blocks.length-1]!.push(node);else prefix.push(node)}
    else blocks.push([node])
  }
  const ordered=blocks.filter(block=>rank.has(block[0]!.sourceId)).sort((a,b)=>rank.get(a[0]!.sourceId)!-rank.get(b[0]!.sourceId)!)
  let orderedIndex=0
  const projectedNodes=[...prefix,...blocks.flatMap(block=>rank.has(block[0]!.sourceId)?ordered[orderedIndex++]!:block)]
  renderMediaControls(source)
  modelControls?.update()
  canvas.update({
    slide: {...slide,nodes:projectedNodes.map(node=>{const crop=pictureCrops.find(item=>item.slideIndex===selectedSlide&&item.elementId===node.sourceId);const faded=pictureOpacities.find(item=>item.slideIndex===selectedSlide&&item.elementId===node.sourceId);const base=faded&&node.type==='picture'?{...node,opacity:faded.opacity}:node;return crop&&base.type==='picture'?{...base,srcRect:crop.srcRect??undefined,box:{...base.box,x:crop.geometry.x,y:crop.geometry.y,w:crop.geometry.width,h:crop.geometry.height}}:base})}, selectedId: selectedElement, selectedIds:[...selectedObjects],
    selectableIds: new Set(locked()?[]:slideAt(selectedSlide).elements.filter(item=>!deletions.has(editKey(selectedSlide,item.id))).map(item=>item.id)),
    editableIds: new Set(locked() || pendingGroup(selectedSlide) ? [] : slideAt(selectedSlide).elements.filter(item => (item.editable || item.arrangeEditable) && !deletions.has(editKey(selectedSlide, item.id))).map(item => item.id)),
    edits: [...edits.values()].filter(item => item.slideIndex === selectedSlide),
    onMediaPlayback: id => playMedia(id),
    onSelect: (id, additive) => {
      if(disposed||locked()||selectionGeneration!==canvasSelectionGeneration||canvasSlide!==selectedSlide||canvasSource!==deck.sha256)return
      if(native)canvasHost.focus({preventScroll:true})
      if(brushMode&&id){applyBrush(id);return}
      selectObjects(id,additive); renderInspector()
    },
    onSelectMany: (ids, additive=false) => {
      if(disposed||locked()||selectionGeneration!==canvasSelectionGeneration||canvasSlide!==selectedSlide||canvasSource!==deck.sha256)return
      const allowed=new Set(slideAt(selectedSlide).elements.filter(item=>!deletions.has(editKey(selectedSlide,item.id))).map(item=>item.id))
      if(ids.some(id=>!allowed.has(id)))return
      if(native)canvasHost.focus({preventScroll:true})
      selectedObjects=new Set(additive?[...selectedObjects,...ids]:ids)
      selectedElement=selectedObjects.has(selectedElement)?selectedElement:[...selectedObjects][0]??''
      selectionSlide=selectedSlide;explicitEmptySelection=selectedObjects.size===0
      renderInspector()
    },
    onGeometry: (id, geometry) => {
      if (locked() || pendingGroup(selectedSlide)) return
      const key = editKey(selectedSlide, id)
      edits.set(key, { ...edits.get(key), slideIndex: selectedSlide, elementId: id, geometry })
      selectedElement = id
      undoSnapshot = undefined
      undoButton.disabled = true
      renderInspector()
      refreshCanvasPreview()
      markDirty()
    },
  })
}

const flatText = (slide: DeckSlide) => slide.elements.find(item => item.text.trim())?.text.split('\n')[0] || `第 ${slide.slideIndex + 1} 页`
const editKey = (slideIndex: number, elementId: string) => `${slideIndex}:${elementId}`
const currentElement = () => slideAt(selectedSlide).elements.find(item => item.id === selectedElement)
const currentGeometryInputs = () => [...root.querySelectorAll<HTMLInputElement>('.geometry-grid input')]

const arrangeCommands: Record<string, SlidesArrangeOp> = {
  alignLeft:'left', alignCenter:'center-h', alignRight:'right', alignTop:'top', alignMiddle:'center-v', alignBottom:'bottom',
  distributeHorizontal:'distribute-h', distributeVertical:'distribute-v',
}
function selectObjects(id: string, additive = false) {
  if(selectionSlide!==selectedSlide){selectedObjects.clear();selectionSlide=selectedSlide}
  if(additive&&id){if(selectedObjects.has(id))selectedObjects.delete(id);else selectedObjects.add(id)}
  else selectedObjects=new Set(id?[id]:[])
  selectedElement=selectedObjects.has(id)?id:[...selectedObjects][0]??''
  explicitEmptySelection=selectedObjects.size===0
}
function arrangeReason(): string | null {
  if(locked())return '当前修订不可编辑'
  if(isNewSlide(selectedSlide))return NEW_SLIDE_REASON
  if(resetLayouts.has(selectedSlide)||layoutEdits.has(selectedSlide)||slideSizeEdit)return '请先保存页面版式或尺寸修改，再排列对象'
  if(!selectedObjects.size)return '请先选择来源对象；按 Ctrl、⌘ 或 Shift 可多选'
  if([...selectedObjects].some(id=>!slideAt(selectedSlide).elements.some(element=>element.id===id&&element.arrangeEditable===true&&!deletions.has(editKey(selectedSlide,id)))))return '选择中包含暂不支持排列的对象'
  return null
}
function renderArrangeSelection(elements: DeckElement[]) {
  if(!native)return
  const legend=document.createElement('legend');legend.textContent='排列对象（可多选）'
  const labels=elements.filter(element=>element.arrangeEditable===true || element.groupEditable===true).map(element=>{
    const label=document.createElement('label'),input=document.createElement('input')
    input.type='checkbox';input.dataset.arrangeObject=element.id;input.checked=selectedObjects.has(element.id)
    input.disabled=locked()||isNewSlide(selectedSlide)
    input.addEventListener('change',()=>{selectObjects(element.id,true);renderInspector()})
    label.append(input,document.createTextNode(element.name||element.text.slice(0,40)||element.type));return label
  })
  arrangeSelection.replaceChildren(legend,...labels)
}
function updateArrangeControls() {
  for(const [command,op] of Object.entries(arrangeCommands)){
    const control=root.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)
    if(!control)continue
    const reason=arrangeReason()??(op.startsWith('distribute')&&selectedObjects.size<3?'均匀分布至少需要三个对象':null)
    control.disabled=!!reason;control.title=reason??'对齐按对象原始矩形计算，保留旋转和翻转'
  }
}
function arrangeObjects(op: SlidesArrangeOp) {
  try{
    const reason=arrangeReason();if(reason)throw new Error(reason)
    const plan=planSlidesArrange({...slideAt(selectedSlide),widthPx:deck.size.cx/9525,heightPx:deck.size.cy/9525},[...selectedObjects],[...edits.values()],op,
      new Map(pictureCrops.filter(item=>item.slideIndex===selectedSlide).map(item=>[item.elementId,item.geometry])))
    if(plan.count)commitNativeChanges({...slideChanges(),edits:plan.edits})
    statusMessage.textContent=plan.count?`已排列 ${plan.count} 个对象，可一次撤销`:'对象已在目标位置'
  }catch(error){statusMessage.textContent=error instanceof Error?error.message:'排列未应用'}
}
const elementOrderCommands:Record<string,'front'|'back'|'forward'|'backward'>={bringToFront:'front',sendToBack:'back',bringForward:'forward',sendBackward:'backward'}
function elementOrderReason():string|null {
  if(locked())return '当前修订不可编辑'
  if(isNewSlide(selectedSlide))return NEW_SLIDE_REASON
  if(resetLayouts.has(selectedSlide)||layoutEdits.has(selectedSlide)||slideSizeEdit)return '请先保存页面版式或尺寸修改，再调整对象层级'
  if([...deletions.values()].some(item=>item.slideIndex===selectedSlide))return '请先保存本页对象删除，再调整层级'
  if(!selectedObjects.size)return '请先选择来源对象'
  if([...selectedObjects].some(id=>!slideAt(selectedSlide).elements.some(item=>item.id===id&&item.orderEditable===true)))return '选择中包含暂不支持调整层级的对象'
  return null
}
function updateElementOrderControls(){
  for(const [command,direction] of Object.entries(elementOrderCommands)){
    const control=root.querySelector<HTMLButtonElement>(`[data-command="${command}"]`);if(!control)continue
    let reason=elementOrderReason()
    if(!reason){try{if(!planSlidesElementOrder(slideAt(selectedSlide).elements,[...selectedObjects],elementOrders.get(selectedSlide),direction).changed)reason='对象已在目标层级'}catch(error){reason=error instanceof Error?error.message:'不能调整来源对象层级'}}
    control.disabled=!!reason;control.title=reason??'保持所选对象相对顺序，可一次撤销'
  }
}
function reorderObjects(direction:'front'|'back'|'forward'|'backward'){
  try{
    const reason=elementOrderReason();if(reason)throw new Error(reason)
    const plan=planSlidesElementOrder(slideAt(selectedSlide).elements,[...selectedObjects],elementOrders.get(selectedSlide),direction)
    if(!plan.changed)return
    const changes=slideChanges(),sourceIds=slideAt(selectedSlide).elements.map(item=>item.id)
    changes.elementOrders=[...(changes.elementOrders??[]).filter(item=>item.slideIndex!==selectedSlide)]
    if(plan.elementIds.some((id,index)=>id!==sourceIds[index]))changes.elementOrders.push({slideIndex:selectedSlide,elementIds:plan.elementIds})
    if(!changes.elementOrders.length)delete changes.elementOrders
    commitNativeChanges(changes);statusMessage.textContent='已调整来源对象层级，可一次撤销'
  }catch(error){statusMessage.textContent=error instanceof Error?error.message:'层级未应用'}
}
function cropReason(): string | null {
  const element=currentElement()
  if(locked()||isNewSlide(selectedSlide)||selectedObjects.size!==1)return '请选择一张来源图片'
  if(!element?.pictureCropEditable)return element?.pictureCropReason??'此图片暂不支持安全裁切'
  if(resetLayouts.has(selectedSlide)||layoutEdits.has(selectedSlide)||slideSizeEdit)return '请先保存页面版式或尺寸修改，再裁切图片'
  if(pictureReplacements.some(item=>item.slideIndex===selectedSlide&&item.elementId===element.id))return '此图片有待保存的替换，请先保存或撤回替换再裁切'
  return null
}
function openPictureCrop() {
  try{
    const reason=cropReason();if(reason)throw new Error(reason)
    const element=currentElement()!,slideIndex=selectedSlide,sourceSha=deck.sha256,snapshot=JSON.stringify(slideChanges())
    const picture=renderTree?.slides.find(slide=>slide.slideIndex===slideIndex)?.nodes.find(node=>node.sourceId===element.id)
    if(picture?.type!=='picture'||!picture.dataUrl||!element.pictureSha256||!element.pictureSize)throw new Error('图片画布尚未就绪，请稍后重试')
    const pending=pictureCrops.find(item=>item.slideIndex===slideIndex&&item.elementId===element.id)
    const box=edits.get(editKey(slideIndex,element.id))?.geometry??pending?.geometry??element.geometry
    if(!box)throw new Error('图片来源位置无法读取')
    cropOverlay?.dispose()
    cropOverlay=openSlidesPictureCrop(canvasHost,{box,srcRect:pending?pending.srcRect:element.srcRect??null,imgSrc:picture.dataUrl,slideWidthPx:deck.size.cx/9525,
      onConfirm:({srcRect,geometry})=>{
        if(disposed||locked()||deck.sha256!==sourceSha||selectedSlide!==slideIndex||currentElement()?.id!==element.id||selectedObjects.size!==1||JSON.stringify(slideChanges())!==snapshot)throw new Error('页面、对象或草稿已变化，请取消后重新打开裁切')
        const changes=slideChanges()
        changes.edits=(changes.edits??[]).flatMap(edit=>{
          if(edit.slideIndex!==slideIndex||edit.elementId!==element.id)return [edit]
          const {geometry:_geometry,...rest}=edit
          return rest.text===undefined?[]:[rest]
        })
        changes.pictureCrops=[...pictureCrops.filter(item=>item.slideIndex!==slideIndex||item.elementId!==element.id),{slideIndex,elementId:element.id,expectedSha256:element.pictureSha256!,expectedSize:element.pictureSize!,srcRect,geometry}]
        commitNativeChanges(changes);cropOverlay=undefined
      },onCancel:()=>{cropOverlay=undefined},
    })
    canvasStatus.textContent='拖动裁切手柄；Enter 或点击外部确认，Esc 取消'
  }catch(error){statusMessage.textContent=error instanceof Error?error.message:'裁切未打开'}
}

function clipboardCopyReason(cut=false): string | null {
  if(!nativeDraft||!deck||locked())return '当前修订不可编辑'
  if(isNewSlide(selectedSlide))return NEW_SLIDE_REASON
  if(!selectedObjects.size)return '请先选择普通来源对象'
  if(slideHasPendingEdits(selectedSlide))return '对象剪贴板读取已保存来源；请先保存或撤销来源页修改'
  const elements=slideAt(selectedSlide).elements
  if([...selectedObjects].some(id=>!elements.some(item=>item.id===id&&item.clipboardEditable===true&&(!cut||item.deletable))))return '选择中包含尚不能安全复制的对象'
  return null
}
function clipboardPasteReason(): string | null {
  if(!nativeDraft||!deck||locked())return '当前修订不可编辑'
  if(!nativeClipboard||nativeClipboard.sourceSha!==deck.sha256)return '请先复制当前文档的来源对象；对象剪贴板仅当前会话有效'
  if(isNewSlide(selectedSlide))return NEW_SLIDE_REASON
  try{
    planSlidesClipboardPaste({sourceSha256:nativeClipboard.sourceSha,sourceSlideIndex:nativeClipboard.sourceSlideIndex,elementIds:nativeClipboard.elementIds},deck.sha256,selectedSlide,20*(nativeClipboard.pasteCount+1),20*(nativeClipboard.pasteCount+1),slideChanges(),deck.slides)
    return null
  }catch(error){return error instanceof Error?error.message:'当前页暂不能粘贴'}
}
function updateClipboardControls() {
  if(!native)return
  const set=(id:string,reason:string|null,title:string)=>{const control=root.querySelector<HTMLButtonElement>('[data-command="'+id+'"]');if(control){control.disabled=reason!==null;control.title=reason??title}}
  set('copy',clipboardCopyReason(),'复制所选已保存对象；仅当前文档会话')
  set('cut',clipboardCopyReason(true),'剪切所选已保存对象；可以撤销')
  set('paste',clipboardPasteReason(),'粘贴对象；保存并重开后显示新对象')
  const element=currentElement()
  const brushReason=locked()||!nativeDraft||selectedObjects.size!==1||!element||pendingGroup(selectedSlide)?'请选择可刷取格式的来源对象':element.brushSource?.supported!==true?(element.brushSource?.reason??'此来源尚不能安全刷取格式'):null
  set('formatBrush',brushReason,brushMode==='continuous'?'持续格式刷；Esc退出':brushMode?'单次格式刷；点击目标对象':'单击刷一次，双击持续刷；Esc退出')
  root.querySelector('[data-command="formatBrush"]')?.setAttribute('aria-pressed',String(!!brushMode))
  set('insertLink',locked()||!nativeDraft||selectedObjects.size!==1||!element||pendingGroup(selectedSlide)?'请选择单个来源对象':element.linkEditable===true?null:element.linkReason??'此对象链接暂不可编辑','设置对象网址、页跳转或移除链接')
}
function copyObjects(cut: boolean) {
  const reason=clipboardCopyReason(cut);if(reason){statusMessage.textContent=reason;return}
  stopBrush()
  const ids=slideAt(selectedSlide).elements.filter(item=>selectedObjects.has(item.id)).map(item=>item.id)
  try{
    const captured=captureSlidesClipboard(deck.sha256,selectedSlide,ids,slideChanges(),deck.slides)
    const next={sourceSha:captured.sourceSha256,sourceSlideIndex:captured.sourceSlideIndex,elementIds:captured.elementIds,pasteCount:0}
    if(cut){const changes=slideChanges();changes.deletions=[...(changes.deletions??[]),...ids.map(elementId=>({slideIndex:selectedSlide,elementId}))];commitNativeChanges(changes);selectObjects('');renderInspector()}
    nativeClipboard=next;updateClipboardControls()
    statusMessage.textContent=(cut?'已剪切':'已复制')+ids.length+'个来源对象；剪贴板仅当前文档会话有效'
  }catch(error){statusMessage.textContent=error instanceof Error?error.message:'对象未复制'}
}
function pasteObjects() {
  const reason=clipboardPasteReason();if(reason){statusMessage.textContent=reason;return}
  stopBrush()
  try{
    const item:ClipboardPaste={sourceSlideIndex:nativeClipboard!.sourceSlideIndex,elementIds:[...nativeClipboard!.elementIds],slideIndex:selectedSlide,dx:20*(nativeClipboard!.pasteCount+1),dy:20*(nativeClipboard!.pasteCount+1)}
    commitNativeChanges({...slideChanges(),clipboardPastes:[...clipboardPastes,item]})
    nativeClipboard!.pasteCount++;updateClipboardControls()
    statusMessage.textContent='粘贴已暂存；保存并打开新修订后可编辑新对象'
  }catch(error){statusMessage.textContent=error instanceof Error?error.message:'粘贴未应用'}
}
function stopBrush(){brush=null;brushMode=undefined;root.querySelector('[data-command="formatBrush"]')?.setAttribute('aria-pressed','false')}
function startBrush(continuous: boolean) {
  if(!deck)return
  const element=currentElement()
  if(!nativeDraft||locked()||selectedObjects.size!==1||!element||pendingGroup(selectedSlide))return
  const captured=captureSlidesBrush({...element,slideIndex:selectedSlide},slideChanges())
  if(!captured.brush){statusMessage.textContent=captured.issues.join('；')||'未找到可安全复制的格式';return}
  brush=captured.brush;brushMode=continuous?'continuous':'once';updateClipboardControls()
  statusMessage.textContent=(continuous?'持续':'单次')+'格式刷已开启；点击目标对象，Esc退出'+(captured.issues.length?'；'+captured.issues.join('；'):'')
}
function applyBrush(id: string) {
  if(!brush||!brushMode||locked())return
  const element=deck.slides[selectedSlide]?.elements.find(item=>item.id===id)
  if(!element)return
  try{
    const plan=planSlidesBrushApply(brush,{...element,slideIndex:selectedSlide},slideChanges())
    if(plan.changed)commitNativeChanges(plan.changes)
    if(plan.issues.length&&!plan.changed){statusMessage.textContent=plan.issues.join('；');return}
    if(brushMode==='once')stopBrush()
    renderInspector();statusMessage.textContent=plan.changed?'格式已应用；可一次撤销':'目标格式未变化，未新增历史'
  }catch(error){statusMessage.textContent=error instanceof Error?error.message:'格式未应用'}
}
function openLinkDialog() {
  if(!deck)return
  const element=currentElement()
  if(!nativeDraft||locked()||selectedObjects.size!==1||!element||element.linkEditable!==true||pendingGroup(selectedSlide))return
  stopBrush();linkDialog?.dispose()
  const slideIndex=selectedSlide,sourceSha=deck.sha256,snapshot=JSON.stringify(slideChanges())
  const pending=linkEdits.find(item=>item.slideIndex===slideIndex&&item.elementId===element.id)
  const currentTarget=pending?pending.target:element.elementLink?.kind==='action'?null:element.elementLink??null
  linkDialog=openSlidesLink(root,{elementLink:currentTarget,slides:order.filter(index=>!isNewSlide(index)).map(index=>({slideIndex:index,label:flatText(slideAt(index))})),onApply:target=>{
    if(disposed||locked()||deck.sha256!==sourceSha||selectedSlide!==slideIndex||currentElement()?.id!==element.id||JSON.stringify(slideChanges())!==snapshot)throw new Error('来源、对象或草稿已变化，请重新打开超链接')
    if(JSON.stringify(target)===JSON.stringify(currentTarget)){linkDialog=undefined;return}
    const changes=slideChanges();changes.linkEdits=[...linkEdits.filter(item=>item.slideIndex!==slideIndex||item.elementId!==element.id),{slideIndex,elementId:element.id,target}]
    commitNativeChanges(changes);linkDialog=undefined
  },onCancel:()=>{linkDialog=undefined}})
}
function onClipboardKey(event: KeyboardEvent) {
  if(event.key==='Escape'&&screenRecordingController&&!disposed){event.preventDefault();event.stopPropagation();screenRecordingController.abort();return}
  if(!native||!nativeDraft||disposed||event.defaultPrevented||event.isComposing||event.keyCode===229||!root.contains(document.activeElement))return
  const target=event.target
  // 固定源文件菜单 CmdOrCtrl+S：先提交失焦输入，再复用保存修订动作。
  if((event.ctrlKey||event.metaKey)&&!event.altKey&&!event.shiftKey&&event.key.toLowerCase()==='s'){
    if(target instanceof Element&&target.closest('dialog'))return
    event.preventDefault();event.stopPropagation()
    if(event.repeat||loading||locked()||mutationPending||saveButton.disabled)return
    const active=document.activeElement
    if(active instanceof HTMLElement&&root.contains(active)){active.blur();if(active.isConnected)active.focus({preventScroll:true})}
    saveButton.click();return
  }
  // 固定源菜单 CmdOrCtrl+P；浏览器入口仍使用同一份当前草稿快照。
  if((event.ctrlKey||event.metaKey)&&!event.altKey&&!event.shiftKey&&event.key.toLowerCase()==='p'){
    if(target instanceof Element&&target.closest('dialog'))return
    event.preventDefault();event.stopPropagation();void openPrint();return
  }
  if(target instanceof Element&&target.closest('.slides-sorter-view,.slides-outline-pane,.slides-reading-view'))return
  if(target instanceof Element&&target.closest('input,textarea,select,[contenteditable="true"],dialog'))return
  if(event.key==='Escape'&&brushMode){event.preventDefault();stopBrush();updateClipboardControls();statusMessage.textContent='已退出格式刷';return}
  if(!(event.ctrlKey||event.metaKey)||event.altKey||event.shiftKey)return
  const key=event.key.toLowerCase()
  if(!['c','x','v'].includes(key))return
  event.preventDefault();event.stopPropagation()
  if(key==='v')pasteObjects();else copyObjects(key==='x')
}
window.addEventListener('keydown',onClipboardKey)

function groupReason(ungroup: boolean): string | null {
  if (locked()) return '当前修订不可编辑'
  if (isNewSlide(selectedSlide)) return NEW_SLIDE_REASON
  if (slideHasPendingEdits(selectedSlide)) return '请先保存或撤销本页修改，再组合或取消组合'
  const item: GroupEdit = ungroup
    ? {slideIndex:selectedSlide,kind:'ungroup',elementId:selectedElement}
    : {slideIndex:selectedSlide,kind:'group',elementIds:[...selectedObjects]}
  try { validateSlidesGroupDraft({...slideChanges(), groupEdits:[...groupEdits,item]},deck.slides); return null }
  catch (error) { return error instanceof Error ? error.message : '来源对象暂不支持组合' }
}
function updateGroupControls() {
  for (const [command,ungroup] of [['groupObjects',false],['ungroupObjects',true]] as const) {
    const control=root.querySelector<HTMLButtonElement>('[data-command="'+command+'"]')
    if (!control) continue
    const reason=ungroup && selectedObjects.size!==1 ? '请选择一个来源组合' : groupReason(ungroup)
    control.disabled=reason!==null; control.title=reason??(ungroup?'取消组合':'组合所选对象；保存后生效')
  }
}
function changeGroup(ungroup: boolean) {
  const reason=ungroup && selectedObjects.size!==1 ? '请选择一个来源组合' : groupReason(ungroup)
  if (reason) { statusMessage.textContent=reason; return }
  try {
    const item: GroupEdit=ungroup?{slideIndex:selectedSlide,kind:'ungroup',elementId:selectedElement}:{slideIndex:selectedSlide,kind:'group',elementIds:[...selectedObjects]}
    const changes=slideChanges()
    changes.groupEdits=validateSlidesGroupDraft({...changes,groupEdits:[...groupEdits,item]},deck.slides)
    commitNativeChanges(changes)
    statusMessage.textContent='组合操作已暂存；保存并打开新修订后可编辑新对象'
  } catch (error) { statusMessage.textContent=error instanceof Error?error.message:'组合操作未应用' }
}
/** 固定源 File ▸ Export Images：当前草稿渲染树中的可见页 → PNG/JPG → ZIP 下载（浏览器宿主等效于写入文件夹）。 */
let exportingImages = false
function openExportImagesDialog() {
  if (!nativeDraft || disposed || saving || mutationPending || exportingImages) return
  const dialog = document.createElement('dialog'); dialog.className = 'slides-table-dialog slides-export-images-dialog'; dialog.setAttribute('aria-label', '导出图片')
  dialog.innerHTML = '<h3>导出图片</h3><label>格式 <select name="format" aria-label="图片格式"><option value="png">PNG</option><option value="jpg">JPG</option></select></label><p>导出全部可见页面（跳过隐藏页），包含尚未保存的修改，打包为一个 ZIP 下载。</p><p role="alert"></p><div class="slides-table-actions"><button type="button" value="cancel">取消</button><button type="button" value="ok">导出</button></div>'
  host.append(dialog)
  dialog.addEventListener('close', () => dialog.remove())
  dialog.querySelector<HTMLButtonElement>('button[value=cancel]')!.addEventListener('click', () => dialog.close())
  dialog.querySelector<HTMLButtonElement>('button[value=ok]')!.addEventListener('click', async () => {
    const alert = dialog.querySelector('[role=alert]')!, ok = dialog.querySelector<HTMLButtonElement>('button[value=ok]')!
    const format = dialog.querySelector<HTMLSelectElement>('select[name=format]')!.value === 'jpg' ? 'jpg' : 'png'
    exportingImages = true; ok.disabled = true; alert.textContent = '正在渲染页面…'
    try {
      const tree = await request<{slides:(RenderSlide & {slideIndex:number;hidden?:boolean})[]}>('render-tree', { method: 'POST', body: JSON.stringify({ expectedSha256: deck.sha256, operations: nativeDraft!.operations }) })
      if (!Array.isArray(tree.slides) || !tree.slides.every(slide => Array.isArray(slide.nodes) && Number.isFinite(slide.widthPx) && slide.widthPx > 0 && Number.isFinite(slide.heightPx) && slide.heightPx > 0)) throw new Error('渲染快照无效')
      const visible = tree.slides.filter(slide => !slide.hidden)
      if (!visible.length) throw new Error('没有可导出的可见页面')
      const { downloadSlideImages, exportBaseName } = await import('./slides-export-images')
      const source = sharedShell?.download?.getAttribute('download') || decodeURIComponent(sharedShell?.download?.getAttribute('href')?.split('?')[0]?.split('/').pop() ?? '')
      const names = await downloadSlideImages(visible, exportBaseName(source), format)
      dialog.close()
      statusMessage.textContent = `已导出 ${names.length} 页图片（${format.toUpperCase()}）`
    } catch (error) { alert.textContent = error instanceof Error ? error.message : '图片导出失败' }
    finally { exportingImages = false; ok.disabled = false }
  })
  dialog.showModal()
}
async function openZoom(mode:'slide'|'section') {
 if(!nativeDraft||locked()||mutationPending||zoomController||isNewSlide(selectedSlide))return
 const sourceSha=deck.sha256,sourceIndex=selectedSlide,snapshot=JSON.stringify(nativeDraft.operations)
 const current=()=>!disposed&&!locked()&&!mutationPending&&deck.sha256===sourceSha&&selectedSlide===sourceIndex&&JSON.stringify(nativeDraft.operations)===snapshot
 const identity=deck.slides[sourceIndex]?.slideIdentity
 if(!identity){statusMessage.textContent='当前页尚无服务端来源身份，请重新载入';return}
 const controller=new AbortController();zoomController=controller
 try{
  const tree=await request<{slides:RenderSlide[]}>('render-tree',{method:'POST',signal:controller.signal,body:JSON.stringify({expectedSha256:sourceSha,operations:JSON.parse(snapshot)})})
  if(!current())return
  const entries=order.map((index,position)=>({index,position,slide:tree.slides[position]})).filter(item=>item.slide&&deck.slides[item.index]?.slideIdentity)
  let candidates=entries.filter(item=>item.index!==sourceIndex).map(item=>({...item,caption:`第 ${item.position+1} 页`}))
  if(mode==='section'){
   if(sectionEdits.length||newSlides.length||deletedSlides.size||order.some((index,position)=>index!==position)){statusMessage.textContent='请先保存页面顺序或分节修改，再插入节缩放定位';return}
   const heads=(deck.sections??[]).filter(section=>section.slideIndices.length).map(section=>({index:Math.min(...section.slideIndices),name:section.name}))
   if(heads.length&&Math.min(...heads.map(head=>head.index))>0)heads.unshift({index:0,name:'默认节'})
   candidates=heads.flatMap(head=>{const item=entries.find(entry=>entry.index===head.index);return item?[{...item,caption:head.name}]:[]})
  }
  const dialog=document.createElement('dialog');zoomDialog=dialog;dialog.className='slides-table-dialog';dialog.setAttribute('aria-label',mode==='slide'?'幻灯片缩放定位':'节缩放定位')
  dialog.innerHTML='<header><h3></h3></header><p>插入目标页静态快照和页跳转链接</p><div class="zoom-items"></div><p role="alert"></p><footer class="slides-table-actions"><button value="cancel">取消</button><button value="insert" disabled>插入</button></footer>'
  dialog.querySelector('h3')!.textContent=dialog.getAttribute('aria-label');const list=dialog.querySelector<HTMLElement>('.zoom-items')!;list.style.cssText='display:flex;flex-wrap:wrap;gap:8px;max-height:50vh;overflow:auto'
  const selected=new Set<number>(),insert=dialog.querySelector<HTMLButtonElement>('[value=insert]')!
  const {mountZoomGrid}=await import('./slides-zoom-grid');await mountZoomGrid(list,candidates as {index:number;caption:string;slide:RenderSlide}[],indices=>{selected.clear();for(const index of indices)selected.add(index);insert.disabled=!selected.size},controller.signal)
  if(!current()){controller.abort();dialog.remove();zoomDialog=undefined;return}
  if(!candidates.length)dialog.querySelector('[role=alert]')!.textContent=mode==='section'?'当前文档没有可选分节':'没有其他可选页面'
  const close=()=>dialog.close()
  dialog.addEventListener('close',()=>{controller.abort();if(zoomDialog===dialog)zoomDialog=undefined;if(zoomController===controller)zoomController=undefined},{once:true})
  dialog.querySelector('[value=cancel]')!.addEventListener('click',close)
  insert.addEventListener('click',()=>{void(async()=>{insert.disabled=true;try{
   if(!current())throw Error('页面或草稿已变化，请重新打开缩放定位')
   const targets=candidates.filter(item=>selected.has(item.index));if(zoomInsertions.length+targets.length>50)throw Error('一次最多插入50个缩放定位，请先保存')
   const {renderSlidesPrintImages}=await import('./slides-print-render');const pngs=await renderSlidesPrintImages(targets.map(item=>item.slide!),controller.signal)
   if(!current())throw Error('页面或草稿已变化，请重新打开缩放定位')
   const width=(slideSizeEdit??deck.size).cx/9525,height=(slideSizeEdit??deck.size).cy/9525,w=Math.round(width/4),h=Math.round(height/4)
   const additions=targets.map((item,index)=>{const d=(index-(targets.length-1)/2)*16;return {slideIdentity:identity,targetSlideIdentity:deck.slides[item.index]!.slideIdentity!,bytesBase64:pngs[index]!.split(',')[1]!,geometry:{x:Math.max(0,Math.round((width-w)/2+d)),y:Math.max(0,Math.round((height-h)/2+d)),width:w,height:h},mode}})
   commitNativeChanges({...slideChanges(),zoomInsertions:[...zoomInsertions,...additions]});close();statusMessage.textContent=`已插入 ${targets.length} 个缩放定位；保存后保留页跳转`
  }catch(error){if(!controller.signal.aborted)dialog.querySelector('[role=alert]')!.textContent=error instanceof Error?error.message:'缩放定位未插入';insert.disabled=!selected.size}})()})
  root.append(dialog);showSlidesSettingsDialog(dialog)
 }catch(error){if(!controller.signal.aborted)statusMessage.textContent=error instanceof Error?error.message:'缩放定位未打开';controller.abort();zoomDialog?.remove();zoomDialog=undefined}
 finally{if(!zoomDialog&&zoomController===controller)zoomController=undefined}
}
async function openPrint() {
  if (!nativeDraft || disposed || loading || locked() || mutationPending || printOpening) return
  if (!commentPane.flush() || (notesPane && !notesPane.flush())) return
  if(chartFormatPane&&!chartFormatPane.flush()||geometryPane&&!geometryPane.flush()||backgroundPane&&!backgroundPane.flush()||shapeFormatPane&&!shapeFormatPane.flush())return
  const active=document.activeElement
  if(active instanceof HTMLElement&&root.contains(active)){
    active.blur()
    if(active.isConnected)active.focus({preventScroll:true})
  }
  if(disposed||locked()||mutationPending)return
  if (cropOverlay || structureDialog) { statusMessage.textContent='请先确认或取消当前编辑，再打开打印预览'; return }
  const sourceSha=deck.sha256,slideIndex=selectedSlide,snapshot=JSON.stringify(nativeDraft.operations)
  const isCurrent=()=>!disposed&&!saving&&!mutationPending&&!nativeDraft?.closed&&deck.sha256===sourceSha&&selectedSlide===slideIndex&&JSON.stringify(nativeDraft?.operations)===snapshot
  printOpening=true
  try {
    const [{openSlidesPrintDialog},{renderSlidesPrintImages}]=await Promise.all([import('./slides-print-dialog'),import('./slides-print-render')])
    if(!isCurrent())return
    printDialog?.dispose()
    printDialog=openSlidesPrintDialog(root,{isCurrent,async load(signal){
      const init={method:'POST',signal,body:JSON.stringify({expectedSha256:sourceSha,operations:JSON.parse(snapshot)})}
      const [tree,preview]=await Promise.all([
        request<{slides:RenderSlide[]}>('render-tree',init),
        request<{sourceSha256:string;model:{slides:DeckSlide[]}}>('preview',init),
      ])
      if(!isCurrent()||signal.aborted)throw Error('文档或草稿已变化，请重新打开打印预览')
      if(preview.sourceSha256!==sourceSha||!Array.isArray(tree.slides)||!tree.slides.length||!Array.isArray(preview.model?.slides)||tree.slides.length!==preview.model.slides.length)throw Error('打印模型与渲染快照不一致')
      const srcs=await renderSlidesPrintImages(tree.slides,signal)
      if(srcs.length!==tree.slides.length)throw Error('打印图片数量与页面不一致')
      return {ratio:tree.slides[0]!.widthPx/tree.slides[0]!.heightPx,current:order.indexOf(slideIndex),slides:srcs.map((src,index)=>({src,hidden:preview.model.slides[index]!.hidden===true,notes:preview.model.slides[index]!.notesText??''}))}
    }})
  }catch(error){if(!disposed)statusMessage.textContent=error instanceof Error?error.message:'打印预览未打开'}
  finally{printOpening=false}
}
async function startSlidesShow(fromCurrent: boolean, customShow?:CustomShow) {
  if (!nativeDraft || disposed || saving || mutationPending || showOpening || showOverlay) return
  if (cropOverlay || structureDialog || order.some(index=>commentPane.hasDraft(index))) { statusMessage.textContent='请先确认或取消当前编辑，再打开放映'; return }
  const sourceSha=deck.sha256, slideIndex=selectedSlide, snapshot=JSON.stringify(nativeDraft.operations)
  const requestedPosition=fromCurrent?order.indexOf(slideIndex):0
  showOpening=true
  animationPreviewOverlay?.dispose();mediaPlayback?.dispose();mediaPlayback=undefined
  statusMessage.textContent='正在读取当前草稿的放映快照…'
  try {
    const init={method:'POST',body:JSON.stringify({expectedSha256:sourceSha,operations:JSON.parse(snapshot)})}
    const [tree, preview] = await Promise.all([
      request<{slides:(RenderSlide & {slideIndex:number;hidden?:boolean})[]}>('render-tree',init),
      request<{sourceSha256:string;model:{slides:DeckSlide[]}}>('preview',init),
    ])
    const [{ openSlidesShow }, { slidesShowSnapshot }] = await Promise.all([import('./slides-show'),import('./slides-show-snapshot')])
    if(disposed||saving||mutationPending||deck.sha256!==sourceSha||selectedSlide!==slideIndex||JSON.stringify(nativeDraft.operations)!==snapshot)throw new Error('页面或草稿已变化，请重新打开放映')
    if(preview.sourceSha256!==sourceSha||!Array.isArray(preview.model?.slides)||!Array.isArray(tree.slides)||!tree.slides.every(slide=>Array.isArray(slide.nodes)&&Number.isFinite(slide.widthPx)&&slide.widthPx>0&&Number.isFinite(slide.heightPx)&&slide.heightPx>0))throw new Error('放映快照无效')
    if(!tree.slides.length)throw new Error('没有可放映页面')
    const customOrder=customShow?.slideIndices.map(index=>order.indexOf(index)).filter(index=>index>=0)
    if(customShow&&!customOrder?.length)throw Error('该自定义放映没有可放映页面')
    const first=tree.slides.findIndex(slide=>!slide.hidden), startIndex=fromCurrent?Math.max(0,requestedPosition):Math.max(0,first)
    const playback=slidesShowSnapshot(tree.slides,preview.model.slides)
    showOverlay=openSlidesShow(root,{slides:tree.slides,mediaSources:tree.slides.map(slide=>(slide as RenderSlide & {mediaSources?:SlideMediaSource[];modelSources?:ModelSource[]}).mediaSources??[]),startIndex:customOrder?.[0]??startIndex,customOrder,...playback,onClose:(lastIndex)=>{
      showOverlay=undefined
      if(!disposed){const id=order[lastIndex??startIndex];root.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="'+id+'"]')?.click();statusMessage.textContent='放映已结束；草稿未改动'}
    }})
    statusMessage.textContent='正在放映当前草稿：分步动画与转场；右键菜单可导航和切换黑白屏'
  } catch(error) { if(!disposed)statusMessage.textContent=error instanceof Error?error.message:'放映未打开' }
  finally { showOpening=false }
}

/** 固定源编辑画布 Preview：读取同一原生草稿的渲染快照及来源+草稿动画，不提交修改。 */
async function startAnimationPreview() {
  if (!nativeDraft || disposed || locked() || showOverlay || cropOverlay) return
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : undefined
  if (slidesViewMode === 'sorter' || slidesViewMode === 'reading') await setSlidesViewMode('normal')
  animationPreviewOverlay?.dispose()
  const generation = ++animationPreviewGeneration, sourceSha = deck.sha256, slideIndex = selectedSlide
  const snapshot = JSON.stringify(nativeDraft.operations), position = order.indexOf(slideIndex)
  const source = sourceAnimations(), sequence = currentSequence()
  if (!sequence.length) { statusMessage.textContent = '当前页没有动画可预览'; return }
  statusMessage.textContent = '正在读取当前草稿的动画预览快照…'
  try {
    const tree = await request<{ slides: RenderSlide[] }>('render-tree', { method: 'POST', body: JSON.stringify({ expectedSha256: sourceSha, operations: nativeDraft.operations }) })
    const [{ openSlidesAnimationPreview }, { previewAnimationItems }] = await Promise.all([import('./slides-animation-preview'), import('./slides-animation-preview-model')])
    if (disposed || locked() || generation !== animationPreviewGeneration || deck.sha256 !== sourceSha || selectedSlide !== slideIndex || JSON.stringify(nativeDraft.operations) !== snapshot) return
    const slide = tree.slides?.[position]
    if (!slide || !Number.isFinite(slide.widthPx) || slide.widthPx <= 0 || !Number.isFinite(slide.heightPx) || slide.heightPx <= 0 || !Array.isArray(slide.nodes)) throw new Error('动画预览快照无效')
    const ids: string[] = []
    const collect = (nodes: RenderSlide['nodes']) => { for (const node of nodes) { if (!node.decoration) ids.push(node.sourceId); if (node.type === 'group') collect(node.children) } }
    collect(slide.nodes)
    const preview = previewAnimationItems(sequence, source, ids)
    if (!preview.items.length) { statusMessage.textContent = preview.warnings.join('；') || '当前页没有可预览的动画'; return }
    opener?.focus({ preventScroll: true })
    animationPreviewOverlay = openSlidesAnimationPreview(root.querySelector<HTMLElement>('.slides-stage')!, { slide, ...preview, onClose: () => { animationPreviewOverlay = undefined } })
    statusMessage.textContent = preview.warnings.join('；') || '正在预览当前页动画；单击画面或按 Esc 结束，不修改草稿'
  } catch (error) { if (!disposed && generation === animationPreviewGeneration) statusMessage.textContent = error instanceof Error ? error.message : '动画预览未打开' }
}

function markDirty() {
  if (locked()) return
  if (nativeDraft) {
    try {
      const changes=slideChanges()
      validateSlidesGroupDraft(changes, deck.slides)
      validateSlidesClipboardDraft(changes, deck.slides)
      validateSlidesLinkDraft(changes, deck.slides)
      validateSlidesNotesDraft(changes, deck.slides)
    }
    catch (error) {
      restoreNativeDraft(); renderSlides(); renderInspector(); refreshCanvasPreview()
      statusMessage.textContent = error instanceof Error ? error.message : '请先保存或撤销组合操作'
      return
    }
  }
  nativeDraft?.setOperations([{ kind: 'editSlides', ...slideChanges() }])
  updateNativeHistory()
  renderCanvas()
  dirty = true
  stateLabel.textContent = '有未保存修改'
  statusMessage.textContent = nativeDraft?.persistenceError ?? '修改尚未保存'
  nativeAIHost?.refresh()
}

/** Validate a complete candidate before committing its single undo snapshot. */
function commitNativeChanges(changes: SlideChanges) {
  if (!nativeDraft || locked()) throw new Error('当前修订不可编辑')
  if(notesPane&&!notesPane.flush())throw new Error('请先完成或修正演讲者备注')
  validateNativeMediaDraft(changes,deck.slides,changes.deletedSlides??[],changes.deletions??[])
  validateSlideMediaInsertions(changes,deck.slides.length,changes.deletedSlides??[])
  restoreNativeDraft([{kind:'editSlides',...changes}], true)
  nativeDraft.setOperations([{kind:'editSlides',...changes}])
  restoreNativeDraft()
  renderSlides(); renderInspector(); refreshCanvasPreview(); renderCanvas()
  dirty = true
  stateLabel.textContent = '有未保存修改'
  statusMessage.textContent = nativeDraft.persistenceError ?? '修改尚未保存'
  nativeAIHost?.refresh()
}

async function openMasterText() {
  if (!nativeDraft || disposed || locked() || (notesPane && !notesPane.flush()) || !commentPane.flush()) return
  masterTextDialog?.dispose()
  const generation = ++masterTextDialogGeneration, sourceSha = deck.sha256, snapshot = JSON.stringify(nativeDraft.operations)
  const isCurrent = () => !disposed && !locked() && generation === masterTextDialogGeneration && sourceSha === deck.sha256 && snapshot === JSON.stringify(nativeDraft.operations)
  try {
    const [tree, { openSlidesMasterText }] = await Promise.all([
      request<{ masterTextParts?: MasterTextRenderPart[] }>('render-tree', { method: 'POST', body: JSON.stringify({ expectedSha256: sourceSha, operations: nativeDraft.operations }) }),
      import('./slides-master-text'),
    ])
    if (!isCurrent()) return
    masterTextDialog = openSlidesMasterText(root, {
      parts: deck.masterTextParts ?? [], edits: structuredClone(masterTextEdits), renders: tree.masterTextParts ?? [], isCurrent,
      onApply(items) { const changes = slideChanges(); if (items.length) changes.masterTextEdits = items; else delete changes.masterTextEdits; commitNativeChanges(changes) },
      elements: { edits: structuredClone(masterElementEdits), onApply(items) {
        const changes = slideChanges()
        if (items.length) changes.masterElementEdits = items; else delete changes.masterElementEdits
        const texts = masterTextEdits.filter(text => !items.some(item => item.kind === 'delete' && item.partPath === text.partPath && item.spid === text.spid))
        if (texts.length) changes.masterTextEdits = texts; else delete changes.masterTextEdits
        commitNativeChanges(changes)
      } },
      onClose() { masterTextDialog = undefined },
    })
  } catch (error) { if (isCurrent()) statusMessage.textContent = error instanceof Error ? error.message : '母版文字未能打开' }
}

function openFindReplace() {
  findDialog?.dispose()
  findDialog=openSlidesFindReplace(root,{
    getSlides:()=>deck.slides, getEdits:()=>[...edits.values()],
    getOptions:()=>({order,deletedSlides:[...deletedSlides],deletions:[...deletions.values()]}),
    isLocked:locked,
    onNavigate:(slideIndex,elementId)=>{if(notesPane&&!notesPane.flush())return;selectedSlide=slideIndex;selectObjects(elementId);renderSlides();renderInspector()},
    onReplace:plan=>{if(plan.count)commitNativeChanges({...slideChanges(),edits:plan.edits})},
  })
}

/** 源录制按钮是开始/停止切换；浏览器选择器授权后才捕获，不提供伪造画面。 */
async function toggleScreenRecording(){
 if(screenRecording){screenRecording.stop();return}
 if(screenRecordingController||!nativeDraft||disposed||locked()||mutationPending||isNewSlide(selectedSlide))return
 const slideIndex=selectedSlide,sourceSha=deck.sha256,snapshot=JSON.stringify(slideChanges()),draftSnapshot=JSON.stringify(nativeDraft.operations),controller=new AbortController()
 screenRecordingController=controller
 const button=root.querySelector<HTMLButtonElement>('[data-command="screenRecording"]')
 const label=(text:string)=>{if(!button)return;button.setAttribute('aria-label',text);const caption=[...button.childNodes].find(node=>node.nodeType===Node.TEXT_NODE);if(caption)caption.textContent=text}
 try{
  statusMessage.textContent='请选择要共享的屏幕或窗口；按 Esc 可取消本次录制'
  screenRecording=await startSlideScreenRecording(controller.signal)
  label('停止录制');button?.classList.add('active','rb-recording');button?.setAttribute('aria-pressed','true')
  statusMessage.textContent='屏幕录制中…再次点击「停止录制」停止并插入；Esc 取消'
  const {file,poster}=await screenRecording.result
  const asset=await prepareSlideMedia(file,'video',controller.signal)
  if(disposed||locked()||mutationPending||deck.sha256!==sourceSha||selectedSlide!==slideIndex||JSON.stringify(slideChanges())!==snapshot||JSON.stringify(nativeDraft.operations)!==draftSnapshot)throw Error('页面或草稿已变化，录制未插入，请重新录制')
  commitNativeChanges({...slideChanges(),mediaInsertions:[...mediaInsertions,{slideIndex,...asset,poster}]})
  statusMessage.textContent='屏幕录制和真实预览图已加入草稿，可撤销；保存后嵌入 PPTX'
 }catch(error){if(!disposed)statusMessage.textContent=controller.signal.aborted?'屏幕录制已取消，未插入媒体':error instanceof Error?error.message:'屏幕录制未完成，请确认浏览器授权'}
 finally{screenRecording=undefined;if(screenRecordingController===controller)screenRecordingController=undefined;label('屏幕录制');button?.classList.remove('active','rb-recording');button?.setAttribute('aria-pressed','false')}
}

/** 固定源 insertMediaFile / insertDroppedMedia：文件读取期间不锁住工作流，提交前重新核验快照。 */
async function chooseNativeMedia(kind:'video'|'audio',dropped?:File,center?:{x:number;y:number}) {
  if(!nativeDraft||disposed||locked()||mutationPending||isNewSlide(selectedSlide))return
  const slideIndex=selectedSlide,sourceSha=deck.sha256,snapshot=JSON.stringify(slideChanges()),draftSnapshot=JSON.stringify(nativeDraft.operations)
  mediaPickerController?.abort();const controller=new AbortController();mediaPickerController=controller
  try {
    const file=dropped??await pickSlideMedia(kind,controller.signal)
    if(!file)return
    const asset=await prepareSlideMedia(file,kind,controller.signal)
    if(disposed||locked()||mutationPending||deck.sha256!==sourceSha||selectedSlide!==slideIndex||JSON.stringify(slideChanges())!==snapshot||JSON.stringify(nativeDraft.operations)!==draftSnapshot)throw Error('页面或草稿已变化，请重新插入媒体')
    commitNativeChanges({...slideChanges(),mediaInsertions:[...mediaInsertions,{slideIndex,...asset,...(center?{center}:{})}]})
    statusMessage.textContent='媒体已加入草稿；正在从实际 PPTX 更新画布，可播放核验后保存新修订'
  }catch(error){if(!disposed&&!controller.signal.aborted)statusMessage.textContent=error instanceof Error?error.message:'媒体未插入，原文件保留'}
  finally{if(mediaPickerController===controller)mediaPickerController=undefined}
}
function renderMediaControls(source:(RenderSlide & {mediaSources?:SlideMediaSource[];modelSources?:ModelSource[]})|undefined){
  let controls=root.querySelector<HTMLElement>('.slides-media-controls')
  if(!controls){controls=document.createElement('div');controls.className='slides-media-controls';controls.setAttribute('aria-label','当前页媒体');canvasStatus.after(controls)}
  controls.replaceChildren()
  for(const media of source?.mediaSources??[]){
    const button=document.createElement('button');button.type='button';button.textContent=`播放${media.kind==='video'?'视频':'音频'}`;button.dataset.mediaPlay=media.sourceId;button.disabled=locked()||!media.dataUrl;button.title=media.reason??media.warning??'从实际 PPTX 嵌入媒体播放';button.addEventListener('click',()=>playMedia(media.sourceId));controls.append(button)
    if(media.reason||media.warning){const note=document.createElement('span');note.textContent=media.reason??media.warning??'';controls.append(note)}
  }
}
function playMedia(sourceId:string){
  if(disposed||locked())return
  const slide=renderTree?.slides.find(item=>item.slideIndex===selectedSlide),media=slide?.mediaSources?.find(item=>item.sourceId===sourceId),node=slide?.nodes.find(item=>item.sourceId===sourceId)
  if(!slide||!media||!node)return
  mediaPlayback?.dispose()
  try{mediaPlayback=openSlideMediaPlayback(canvasHost,media,node.box,slide.widthPx)}catch(error){statusMessage.textContent=error instanceof Error?error.message:'媒体无法读取'}
}

let cutoutDialog:ReturnType<typeof openSlidesCutout>|undefined
let cutoutGeneration=0
let cutoutCurrent:(()=>boolean)|undefined
function cutoutReason():string|null{
 const element=currentElement()
 if(!nativeDraft||locked()||isNewSlide(selectedSlide)||selectedObjects.size!==1)return '请选择一张已核验身份的来源图片'
 if(element?.type!=='picture'||element.mediaKind||!element.pictureReplaceable||!element.pictureSha256||!element.pictureSize)return element?.pictureReplaceReason??'此图片不能安全去背景'
 if(pendingGroup(selectedSlide)||resetLayouts.has(selectedSlide)||layoutEdits.has(selectedSlide)||slideSizeEdit)return '请先保存页面结构或版式修改，再去除背景'
 if([...pictureCrops,...pictureOpacities,...pictureReplacements].some(item=>item.slideIndex===selectedSlide&&item.elementId===element.id))return '请先保存或撤回此图片的裁切、透明度或替换修改'
 return null
}
async function openPictureCutout(){
 const reason=cutoutReason();if(reason){statusMessage.textContent=reason;return}
 const element=currentElement()!,slideIndex=selectedSlide,sourceSha=deck.sha256,snapshot=JSON.stringify(slideChanges()),draftSnapshot=JSON.stringify(nativeDraft!.operations),generation=++cutoutGeneration
 const current=()=>!disposed&&generation===cutoutGeneration&&!locked()&&deck.sha256===sourceSha&&selectedSlide===slideIndex&&selectedObjects.size===1&&currentElement()?.id===element.id&&JSON.stringify(slideChanges())===snapshot&&JSON.stringify(nativeDraft!.operations)===draftSnapshot
 cutoutDialog?.dispose();cutoutDialog=undefined
 try{
  const picture=renderTree?.slides.find(slide=>slide.slideIndex===slideIndex)?.nodes.find(node=>node.sourceId===element.id)
  if(picture?.type!=='picture'||!picture.dataUrl)throw Error('图片画布尚未就绪，请稍后重试')
  const dataUrl=await verifiedCutoutSource(picture.dataUrl,element.pictureSha256!,element.pictureSize!)
  if(!current())throw Error('页面、选择或草稿已变化，请重新打开去背景')
  cutoutCurrent=current
  cutoutDialog=openSlidesCutout(root,{dataUrl,isCurrent:current,onApply:png=>{
   if(!current())throw Error('页面、选择或草稿已变化，请重新打开去背景')
   const match=/^data:image\/png;base64,([A-Za-z0-9+/]+={0,2})$/.exec(png);if(!match)throw Error('去背景输出不是有效PNG')
   const changes=slideChanges();changes.pictureReplacements=[...pictureReplacements,{slideIndex,elementId:element.id,expectedSha256:element.pictureSha256!,expectedSize:element.pictureSize!,bytesBase64:match[1]!,extension:'png',keepSrcRect:true}]
   commitNativeChanges(changes);statusMessage.textContent='去背景已加入草稿，可撤销；保存新修订后保留透明PNG'
  }})
 }catch(error){if(!disposed&&generation===cutoutGeneration)statusMessage.textContent=error instanceof Error?error.message:'去背景未打开，原图片保留'}
}

async function chooseNativePicture(replace: boolean) {
  const slideIndex=selectedSlide, element=currentElement(), sourceSha=deck.sha256
  const snapshot=JSON.stringify(slideChanges())
  if(isNewSlide(slideIndex)) {statusMessage.textContent=NEW_SLIDE_REASON;return}
  if(replace && pictureOpacities.some(item=>item.slideIndex===slideIndex&&item.elementId===element?.id)) {statusMessage.textContent='此图片有待保存的透明度修改，请先保存或撤回再替换';return}
  if(replace && pictureCrops.some(item=>item.slideIndex===slideIndex&&item.elementId===element?.id)) {statusMessage.textContent='此图片有待保存的裁切，请先保存或撤回裁切再替换';return}
  if(replace && element?.mediaKind){statusMessage.textContent='此入口仅替换普通图片，不替换音视频文件';return}
  if(replace && !element?.pictureReplaceable) {statusMessage.textContent=element?.pictureReplaceReason??'请选择可替换的来源图片';return}
  try {
    const file=await pickSlideImage()
    if(!file)return
    const image=await prepareSlideImage(file,deck.size)
    if(disposed||locked()||deck.sha256!==sourceSha||selectedSlide!==slideIndex||JSON.stringify(slideChanges())!==snapshot||(replace&&currentElement()?.id!==element?.id))throw new Error('页面、选择或草稿已变化，请重新选择图片')
    const changes=slideChanges()
    if(replace && element?.pictureSha256 && element.pictureSize){
      changes.pictureReplacements=[...pictureReplacements.filter(item=>item.slideIndex!==slideIndex||item.elementId!==element.id),{slideIndex,elementId:element.id,expectedSha256:element.pictureSha256,expectedSize:element.pictureSize,bytesBase64:image.bytesBase64,extension:image.extension}]
    } else if(!replace) changes.images=[...nativeImages,{slideIndex,...image}]
    else throw new Error('图片来源身份无法核验')
    commitNativeChanges(changes)
    canvasStatus.textContent='图片修改已暂存；保存并打开新修订后显示新图片'
  } catch(error){statusMessage.textContent=error instanceof Error?error.message:'图片操作失败，原文件保留'}
}

function nativeChartData(element:DeckElement,pending?:NativeChartPatch) {
  const data={categories:pending?.categories??element.chartCategories!,series:pending?.series??element.chartSeries!}
  return pending?.switchRowCol&&pending.categories===undefined?transposeChartData(data):data
}

function nativeChartPointColors(element:DeckElement,pending?:NativeChartPatch):ChartPointColors {
  const source:ChartPointColors={}
  element.chartPointColors?.forEach((row,si)=>row.forEach((color,pi)=>{if(color)(source[si]??={})[pi]=color}))
  return mergeChartPointColors(pending?.switchRowCol?transposeChartPointColors(source):source,pending?.pointColors)
}

function applyNativeChartPointColors(points:ChartPointColors,target:string) {
  const slideIndex=selectedSlide,element=currentElement()
  const pending=nativeChartEdits.find(item=>item.slideIndex===slideIndex&&item.elementId===element?.id)
  if(locked()||selectedObjects.size!==1||!element?.chartEditSafe||(pending?.kind??element.chartKind)==='scatter'||target!==`${deck.sha256}:${slideIndex}:${element.id}`)throw new Error('图表来源或选择已变化，请重新选择图表')
  const current=nativeChartPointColors(element,pending),changed:ChartPointColors={}
  for(const [si,row] of Object.entries(points))for(const [pi,color] of Object.entries(row))if(color!==(current[Number(si)]?.[Number(pi)]??null))(changed[Number(si)]??={})[Number(pi)]=color
  if(!Object.keys(changed).length)return
  const merged={...pending,slideIndex,elementId:element.id,pointColors:mergeChartPointColors(pending?.pointColors,changed)}
  commitNativeChanges({...slideChanges(),chartEdits:[...nativeChartEdits.filter(item=>item.slideIndex!==slideIndex||item.elementId!==element.id),merged]})
  canvasStatus.textContent='图表单点配色已暂存；保存并打开新修订后显示新图表'
}

function switchNativeChartRowsColumns() {
  try {
    const slideIndex=selectedSlide,element=currentElement()
    if(selectedObjects.size!==1||!element?.chartEditSafe||!element.chartCategories||!element.chartSeries)throw new Error('请选择支持编辑的来源图表')
    const pending=nativeChartEdits.find(item=>item.slideIndex===slideIndex&&item.elementId===element.id)
    const merged:NonNullable<SlideChanges['chartEdits']>[number]={...pending,slideIndex,elementId:element.id,...transposeChartData(nativeChartData(element,pending)),switchRowCol:!pending?.switchRowCol}
    if(pending?.pointColors)merged.pointColors=transposeChartPointColors(pending.pointColors)
    if(!merged.switchRowCol){
      delete merged.switchRowCol
      if(JSON.stringify({categories:merged.categories,series:merged.series})===JSON.stringify({categories:element.chartCategories,series:element.chartSeries})){delete merged.categories;delete merged.series}
    }
    const others=nativeChartEdits.filter(item=>item.slideIndex!==slideIndex||item.elementId!==element.id)
    commitNativeChanges({...slideChanges(),chartEdits:Object.keys(merged).length>2?[...others,merged]:others})
    canvasStatus.textContent='图表行列交换已暂存；保存并打开新修订后显示新图表'
  }catch(error){statusMessage.textContent=error instanceof Error?error.message:'交换行列失败，原草稿已保留'}
}

function applyNativeChartGallery(command:string,value:unknown) {
  try {
    const slideIndex=selectedSlide,element=currentElement()
    if(locked()||selectedObjects.size!==1||!element?.chartEditSafe||!element.chartStyle)throw new Error('请选择可安全编辑的来源图表')
    const pending=nativeChartEdits.find(item=>item.slideIndex===slideIndex&&item.elementId===element.id)
    const patch:NativeChartPatch={}
    if(command==='chartStylePreset'){
      const preset=CHART_STYLE_PRESETS.find(item=>item.key===value)
      if(!preset)throw new Error('未知图表样式预设')
      const current={...element.chartStyle,gapWidthPct:element.chartGapWidthPct??150,...pending}
      for(const key of ['legendPos','dataLabels','gridlines','gapWidthPct'] as const)if(current[key]!==preset.style[key])Object.assign(patch,{[key]:preset.style[key]})
    }else{
      const scheme=(element.chartColorSchemes??chartColorSchemes()).find(item=>item.key===value)
      if(!scheme)throw new Error('此来源配色不可用')
      if(pending?.colorScheme!==scheme.key)patch.colorScheme=scheme.key
    }
    if(!Object.keys(patch).length)return
    const merged={...pending,slideIndex,elementId:element.id,...patch}
    commitNativeChanges({...slideChanges(),chartEdits:[...nativeChartEdits.filter(item=>item.slideIndex!==slideIndex||item.elementId!==element.id),merged]})
    canvasStatus.textContent='图表样式已暂存；保存并打开新修订后显示新图表'
  }catch(error){statusMessage.textContent=error instanceof Error?error.message:'图表样式未能应用，原草稿已保留'}
}

function openNativeChart(mode:'data'|'type'|'style'|'design'|'points') {
  if(chartFormatPane&&!chartFormatPane.flush())return
  const slideIndex=selectedSlide,element=currentElement()
  if(selectedObjects.size!==1||!element?.chartEditSafe||!element.chartKind||!element.chartCategories||!element.chartSeries){statusMessage.textContent='此来源图表不能安全编辑；保留原图表';return}
  if(mode==='points'&&(nativeChartEdits.find(item=>item.slideIndex===slideIndex&&item.elementId===element.id)?.kind??element.chartKind)==='scatter'){statusMessage.textContent='固定源散点图不支持单点颜色写入；请保留原图表';return}
  chartDialog?.dispose()
  const snapshot=JSON.stringify(slideChanges()),sourceSha=deck.sha256
  const pending=nativeChartEdits.find(item=>item.slideIndex===slideIndex&&item.elementId===element.id)
  chartDialog=createNativeChartEditDialog(root,{mode,colorSchemes:element.chartColorSchemes,
    initial:{...element.chartStyle,gapWidthPct:element.chartGapWidthPct??150,...pending,pointColors:nativeChartPointColors(element,pending),seriesColors:pending?.colorScheme?element.chartColorSchemes?.find(scheme=>scheme.key===pending.colorScheme)?.colors:element.chartSeriesColors??undefined,kind:pending?.kind??element.chartKind,...nativeChartData(element,pending)},
    onConfirm:patch=>{
      if(disposed||locked()||selectedObjects.size!==1||deck.sha256!==sourceSha||selectedSlide!==slideIndex||currentElement()?.id!==element.id||JSON.stringify(slideChanges())!==snapshot)throw new Error('页面、对象或草稿已变化，请重新打开图表编辑')
      const merged={...pending,slideIndex,elementId:element.id,...patch}
      if(patch.pointColors)merged.pointColors=mergeChartPointColors(pending?.pointColors,patch.pointColors)
      if(JSON.stringify(merged)===JSON.stringify(pending))return
      commitNativeChanges({...slideChanges(),chartEdits:[...nativeChartEdits.filter(item=>item.slideIndex!==slideIndex||item.elementId!==element.id),merged]})
      canvasStatus.textContent='图表修改已暂存；保存并打开新修订后显示新图表'
    },onClose:()=>{chartDialog=undefined},
  })
}

function slideChanges(): SlideChanges {
  return { ...(zoomInsertions.length?{zoomInsertions:structuredClone(zoomInsertions)}:{}), ...(customShowEdits!==undefined?{customShows:structuredClone(customShowEdits)}:{}), ...(masterElementEdits.length ? { masterElementEdits: structuredClone(masterElementEdits) } : {}), ...(masterTextEdits.length ? { masterTextEdits: structuredClone(masterTextEdits) } : {}), ...(notesEdits.size?{notesEdits:[...notesEdits].map(([slideIndex,text])=>({slideIndex,text}))}:{}), ...(linkEdits.length?{linkEdits:structuredClone(linkEdits)}:{}), ...(clipboardPastes.length?{clipboardPastes:structuredClone(clipboardPastes)}:{}), ...(groupEdits.length ? {groupEdits: structuredClone(groupEdits)} : {}), ...(tableStructureEdits.size ? {tableStructures:[...tableStructureEdits.values()].map(item=>({...item}))}:{}), ...(tableStyleEdits.size ? { tableStyles: [...tableStyleEdits.values()].map(item => structuredClone(item)) } : {}), edits: [...edits.values()], ...(native ? { textFormatting: [...textFormattingEdits.values()], paragraphFormatting: [...paragraphFormattingEdits.values()] } : {}),
    order: [...order], ...(newSlides.length ? { newSlides: newSlides.map(item => ({ ...item })) } : {}), ...(deletedSlides.size ? { deletedSlides: [...deletedSlides] } : {}), ...(resetLayouts.size ? { resetLayouts: [...resetLayouts] } : {}), ...(shapeEdits.length ? { shapes: shapeEdits.map(item => ({ ...item, geometry: { ...item.geometry } })) } : {}), ...(tableEdits.length ? { tables: tableEdits.map(item => ({ ...item })) } : {}), ...(shapeStyleEdits.size ? { shapeStyles: [...shapeStyleEdits.values()].map(item => structuredClone(item)) } : {}), ...(shapeKindEdits.size ? { shapeKinds: [...shapeKindEdits.values()].map(item => ({ ...item })) } : {}), ...(sectionEdits.length ? { sections: sectionEdits.map(item => ({ ...item })) } : {}), ...(headerFooterEdit ? { headerFooter: { ...headerFooterEdit } } : {}), ...(tableCellEdits.size ? { tableCells: [...tableCellEdits.values()].map(item => ({ ...item })) } : {}), ...(chartEdits.length ? { charts: chartEdits.map(item => structuredClone(item)) } : {}), ...(smartArtEdits.length ? { smartArts: smartArtEdits.map(item => structuredClone(item)) } : {}), ...(selectedTheme ? { theme: selectedTheme } : {}), ...(slideSizeEdit ? { slideSize: slideSizeEdit } : {}),
    ...(modelInsertions.length?{modelInsertions:structuredClone(modelInsertions)}:{}),...(modelViews.length?{modelViews:structuredClone(modelViews)}:{}),
    ...(mediaInsertions.length ? {mediaInsertions:structuredClone(mediaInsertions)} : {}),
    ...(nativeImages.length ? { images: structuredClone(nativeImages) } : {}),
    ...(elementOrders.size ? {elementOrders:[...elementOrders].map(([slideIndex,elementIds])=>({slideIndex,elementIds:[...elementIds]}))}:{}),
    ...(pictureCrops.length ? {pictureCrops:structuredClone(pictureCrops)}:{}),
    ...(pictureOpacities.length ? { pictureOpacities: structuredClone(pictureOpacities) } : {}),
    ...(pictureReplacements.length ? { pictureReplacements: structuredClone(pictureReplacements) } : {}),
    ...(nativeChartEdits.length ? { chartEdits: structuredClone(nativeChartEdits) } : {}),
    ...(commentEdits.length ? { commentEdits: commentEdits.map(edit => ({ ...edit })) } : {}),
    ...(hiddenSlideEdits.size ? { hiddenSlides: [...hiddenSlideEdits].map(([slideIndex, hidden]) => ({ slideIndex, hidden })) } : {}),
    transitions: [...transitionEdits].map(([slideIndex, kind]) => ({ slideIndex, kind })), animations: [...animationEdits],
    ...(animationSequences.size ? { animationSequences: [...animationSequences].map(([slideIndex, items]) => ({ slideIndex, items: items.map(item => ({ ...item })) })) } : {}),
    slideLayouts: [...layoutEdits].map(([slideIndex, layoutPath]) => ({ slideIndex, layoutPath })),
    backgrounds: [...backgroundEdits].map(([slideIndex, color]) => ({ slideIndex, color })),
    ...(backgroundImageEdits.length ? { backgroundImages: backgroundImageEdits.map(item => ({ ...item, slideIndices: [...item.slideIndices] })) } : {}),
    ...(backgroundImageReuseEdits.length ? {backgroundImageReuses:structuredClone(backgroundImageReuseEdits)}:{}),
    ...(backgroundGradientEdits.length ? { backgroundGradients: backgroundGradientEdits.map(item => ({ ...item, slideIndices: [...item.slideIndices] })) } : {}),
    ...(backgroundResetEdits.size ? { backgroundResets: [...backgroundResetEdits] } : {}),
    ...(backgroundGraphicsEdits.size ? { backgroundGraphics: [...backgroundGraphicsEdits].map(([slideIndex, hidden]) => ({ slideIndex, hidden })) } : {}),
    textBoxes: textBoxEdits.map(({ watermark: _watermark, ...box }) => box),
    deletions: [...deletions.values()].map(({ slideIndex, elementId }) => ({ slideIndex, elementId })) }
}

function restoreNativeDraft(candidate?: NativeOperation[], validateOnly = false) {
  if (!nativeDraft) return
  const operations = candidate ?? nativeDraft.operations
  const supported = new Set(['zoomInsertions','modelInsertions','modelViews','customShows', 'mediaInsertions', 'masterElementEdits', 'masterTextEdits', 'notesEdits', 'linkEdits', 'clipboardPastes', 'groupEdits', 'elementOrders', 'images', 'pictureReplacements', 'pictureCrops', 'pictureOpacities', 'backgroundImages', 'backgroundImageReuses', 'backgroundGradients', 'backgroundResets', 'backgroundGraphics', 'chartEdits', 'commentEdits', 'kind', 'edits', 'order', 'newSlides', 'deletedSlides', 'resetLayouts', 'shapes', 'tables', 'shapeStyles', 'shapeKinds', 'sections', 'headerFooter', 'tableCells', 'tableStyles', 'tableStructures', 'charts', 'smartArts', 'theme', 'slideSize', 'textFormatting', 'paragraphFormatting', 'animationSequences', 'hiddenSlides', 'transitions', 'animations', 'slideLayouts', 'backgrounds', 'textBoxes', 'deletions'])
  // 多操作批次不能安全折叠为对象面板快照；拒绝打开并保留原草稿，防止下一次输入覆盖它。
  if (operations.length > 1 || operations.some(operation => operation.kind !== 'editSlides' || Object.keys(operation).some(key => !supported.has(key)))) {
    throw new Error('当前 PPTX 草稿包含暂不支持恢复的操作，草稿已保留')
  }
  const changes = (operations[0] ?? {}) as SlideChanges
  validateZoomDraft(changes.zoomInsertions,deck.slides,changes.deletedSlides??[])
  validateModelDraft(changes,deck.slides.length,changes.deletedSlides??[])
  const restoredShows=changes.customShows
  if(restoredShows!==undefined&&(!deck.customShowsEditable||!Array.isArray(restoredShows)||restoredShows.length>100||new Set(restoredShows.map(item=>item?.id)).size!==restoredShows.length||restoredShows.some(item=>!item||Object.keys(item).sort().join()!=='id,name,slideIndices'||typeof item.id!=='string'||!(/^(?:0|[1-9]\d*|cs-[a-z0-9-]{1,80})$/.test(item.id))||typeof item.name!=='string'||!item.name.trim()||item.name.length>255||/[\u0000-\u001f\u007f-\u009f\ufffe\uffff]|\p{Cs}/u.test(item.name)||!Array.isArray(item.slideIndices)||item.slideIndices.length>500||item.slideIndices.some(index=>!Number.isInteger(index)||index<0||index>=deck.slides.length))))throw Error('自定义放映草稿无效；原草稿已保留')
  const restoredMasterText = validateMasterTextDraft(changes.masterTextEdits, deck.masterTextParts ?? [])
  const restoredMasterElements = validateMasterElementDraft(changes.masterElementEdits, deck.masterTextParts ?? [])
  const restoredNotes = validateSlidesNotesDraft(changes,deck.slides)
  const restoredGroups = validateSlidesGroupDraft(changes, deck.slides)
  const restoredLinks = validateSlidesLinkDraft(changes, deck.slides)
  const restoredPastes = validateSlidesClipboardDraft(changes, deck.slides)
  const transitions = restoredTransitions(changes.transitions, deck.slides.length)
  if (native && transitions.some(item => !transitionEditingAllowed(deck.slides[item.slideIndex]))) throw new Error('来源含尚不能安全修改的转场兼容性内容；原草稿已保留')
  const restoredBackgroundImages = changes.backgroundImages ?? []
  {
    const used = new Set<number>(), colors = new Set((changes.backgrounds ?? []).map(item => item.slideIndex)), removed = new Set(changes.deletedSlides ?? [])
    if (!Array.isArray(restoredBackgroundImages) || restoredBackgroundImages.length > 10 || restoredBackgroundImages.some(item => !item || Object.keys(item).sort().join() !== 'bytesBase64,extension,slideIndices,tile'
      || typeof item.tile !== 'boolean' || !['png', 'jpg'].includes(item.extension) || typeof item.bytesBase64 !== 'string' || !Array.isArray(item.slideIndices) || !item.slideIndices.length
      || item.slideIndices.some(index => !Number.isInteger(index) || index < 0 || index >= deck.slides.length || used.has(index) || colors.has(index) || removed.has(index) || !used.add(index))))
      throw new Error('背景图片草稿无效；原草稿已保留')
    const reuses=changes.backgroundImageReuses??[]
    if(!Array.isArray(reuses)||reuses.length>50||reuses.some(item=>{
      const identity=deck.slides[item?.sourceSlideIndex]?.backgroundImageSource
      return !item||Object.keys(item).sort().join()!=='expectedSha256,expectedSize,slideIndices,sourceSlideIndex,tile'||!Number.isInteger(item.sourceSlideIndex)||!identity||identity.sha256!==item.expectedSha256||identity.size!==item.expectedSize||typeof item.tile!=='boolean'||!Array.isArray(item.slideIndices)||!item.slideIndices.length||item.slideIndices.some(index=>!Number.isInteger(index)||index<0||index>=deck.slides.length||used.has(index)||colors.has(index)||removed.has(index)||!used.add(index))
    }))throw new Error('背景图片复用草稿与来源身份不一致；原草稿已保留')
    const gradients = changes.backgroundGradients ?? [], resets = changes.backgroundResets ?? [], graphics = changes.backgroundGraphics ?? []
    if (!Array.isArray(gradients) || gradients.length > 20 || gradients.some(item => !item || Object.keys(item).sort().join() !== 'angleDeg,from,radial,slideIndices,to' || !/^#[0-9A-F]{6}$/i.test(item.from) || !/^#[0-9A-F]{6}$/i.test(item.to)
      || typeof item.radial !== 'boolean' || ![0, 45, 90].includes(item.angleDeg) || (item.radial && item.angleDeg !== 0) || !Array.isArray(item.slideIndices) || !item.slideIndices.length
      || item.slideIndices.some(index => !Number.isInteger(index) || index < 0 || index >= deck.slides.length || used.has(index) || colors.has(index) || removed.has(index) || !used.add(index)))
      || !Array.isArray(resets) || resets.some(index => !Number.isInteger(index) || !deck.slides[index]?.backgroundOwn || used.has(index) || colors.has(index) || removed.has(index) || !used.add(index))
      || !Array.isArray(graphics) || new Set(graphics.map(item => item?.slideIndex)).size !== graphics.length || graphics.some(item => !item || Object.keys(item).sort().join() !== 'hidden,slideIndex' || typeof item.hidden !== 'boolean' || !deck.slides[item.slideIndex] || removed.has(item.slideIndex)))
      throw new Error('背景格式草稿无效；原草稿已保留')
  }
  const restoredOpacities = changes.pictureOpacities ?? []
  if (!Array.isArray(restoredOpacities) || restoredOpacities.length > 50 || new Set(restoredOpacities.map(item => `${item?.slideIndex}:${item?.elementId}`)).size !== restoredOpacities.length || restoredOpacities.some(item => {
    const element = deck.slides[item?.slideIndex]?.elements.find(candidate => candidate.id === item.elementId)
    return !item || Object.keys(item).sort().join() !== 'elementId,expectedSha256,expectedSize,opacity,slideIndex' || !element?.pictureOpacityEditable || element.pictureSha256 !== item.expectedSha256 || element.pictureSize !== item.expectedSize
      || typeof item.opacity !== 'number' || item.opacity < 0 || item.opacity > 1 || Math.abs(Math.round(item.opacity * 100) - item.opacity * 100) > 1e-9
      || (changes.pictureReplacements ?? []).some(other => other.slideIndex === item.slideIndex && other.elementId === item.elementId)
  })) throw new Error('图片透明度草稿与来源图片不一致；原草稿已保留')
  const restoredNew = changes.newSlides ?? []
  if (!Array.isArray(restoredNew) || restoredNew.length > 50 || restoredNew.some(item => !item || Object.keys(item).length !== 1 || !['layoutFrom', 'duplicateOf', 'withLayout'].includes(Object.keys(item)[0]!) || ('withLayout' in item ? !(deck.layouts ?? []).some(layout => layout.path === item.withLayout) : !Number.isInteger(newSlideSource(item)) || newSlideSource(item)! < 0 || newSlideSource(item)! >= deck.slides.length)) || (restoredNew.length && changes.order === undefined)) throw new Error('草稿中的新建幻灯片无效；原草稿已保留')
  const restoredDeleted = changes.deletedSlides ?? []
  if (!Array.isArray(restoredDeleted) || new Set(restoredDeleted).size !== restoredDeleted.length || restoredDeleted.some(index => !Number.isInteger(index) || index < 0 || index >= deck.slides.length) || (restoredDeleted.length && changes.order === undefined) || restoredNew.some(item => restoredDeleted.includes(newSlideSource(item) ?? -1))) throw new Error('草稿中的删除幻灯片无效；原草稿已保留')
  const restoredElementOrders=validateSlidesElementOrders(changes.elementOrders,deck.slides,restoredDeleted)
  const restoredComments = validateCommentEdits(changes.commentEdits, deck.slides, restoredDeleted)
  validateNativeMediaDraft(changes, deck.slides, restoredDeleted, changes.deletions ?? [])
  validateSlideMediaInsertions(changes,deck.slides.length,restoredDeleted)
  const restoredHidden = changes.hiddenSlides ?? []
  if (!Array.isArray(restoredHidden) || restoredHidden.length > 500 || new Set(restoredHidden.map(item => item?.slideIndex)).size !== restoredHidden.length || restoredHidden.some(item => !item || Object.keys(item).sort().join() !== 'hidden,slideIndex' || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= deck.slides.length || restoredDeleted.includes(item.slideIndex) || typeof item.hidden !== 'boolean')) throw new Error('草稿中的隐藏幻灯片无效；原草稿已保留')
  const restoredReset = changes.resetLayouts ?? []
  if (!Array.isArray(restoredReset) || new Set(restoredReset).size !== restoredReset.length || restoredReset.some(index => !Number.isInteger(index) || index < 0 || index >= deck.slides.length || restoredDeleted.includes(index))) throw new Error('草稿中的重置版式无效；原草稿已保留')
  const restoredStyles = changes.shapeStyles ?? []
  const hex = (value: unknown) => typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value)
  if (!Array.isArray(restoredStyles) || restoredStyles.length > 500 || restoredStyles.some(item => !item || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= deck.slides.length || restoredDeleted.includes(item.slideIndex)
    || !deck.slides[item.slideIndex]!.elements.some(element => element.id === item.elementId && ['text', 'shape'].includes(element.type))
    || Object.keys(item).some(key => !['slideIndex', 'elementId', 'fill', 'stroke'].includes(key)) || (item.fill === undefined && item.stroke === undefined)
    || (item.fill !== undefined && item.fill !== 'none' && !hex(item.fill)) || (item.stroke !== undefined && item.stroke !== null && (!hex(item.stroke.color) || !(item.stroke.widthPt > 0 && item.stroke.widthPt <= 100))))) throw new Error('草稿中的形状样式无效；原草稿已保留')
  const restoredSmartArts = changes.smartArts ?? []
  if (!Array.isArray(restoredSmartArts) || restoredSmartArts.length > 50 || restoredSmartArts.some(item => !item || Object.keys(item).sort().join() !== 'items,layout,slideIndex' || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= deck.slides.length || restoredDeleted.includes(item.slideIndex)
    || !SMARTART_GALLERY.some(entry => entry.layout === item.layout) || !Array.isArray(item.items) || item.items.length < 1 || item.items.length > SMARTART_MAX_ITEMS || item.items.some(text => typeof text !== 'string' || text.length > 200))) throw new Error('草稿中的新增 SmartArt 无效；原草稿已保留')
  const restoredCharts = changes.charts ?? []
  if (!Array.isArray(restoredCharts) || restoredCharts.length > 50 || restoredCharts.some(item => !item || Object.keys(item).sort().join() !== 'categories,kind,series,slideIndex' || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= deck.slides.length || restoredDeleted.includes(item.slideIndex)
    || !CHART_GALLERY.some(chart => chart.kind === item.kind) || !Array.isArray(item.categories) || !item.categories.length || !Array.isArray(item.series) || !item.series.length || item.series.some(series => !Array.isArray(series?.values) || series.values.length !== item.categories.length))) throw new Error('草稿中的新增图表无效；原草稿已保留')
  const restoredCells = changes.tableCells ?? []
  if (!Array.isArray(restoredCells) || restoredCells.length > 2000 || restoredCells.some(item => !item || Object.keys(item).sort().join() !== 'col,elementId,row,slideIndex,text' || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= deck.slides.length || restoredDeleted.includes(item.slideIndex)
    || typeof deck.slides[item.slideIndex]!.elements.find(element => element.id === item.elementId)?.tableCells?.[item.row]?.[item.col] !== 'string' || typeof item.text !== 'string' || item.text.length > 10000)) throw new Error('草稿中的表格单元格修改无效；原草稿已保留')
  const restoredHf = changes.headerFooter
  if (restoredHf !== undefined && (!restoredHf || Object.keys(restoredHf).sort().join() !== 'date,dateAuto,footer,slideNum' || typeof restoredHf.slideNum !== 'boolean' || typeof restoredHf.dateAuto !== 'boolean' || [restoredHf.footer, restoredHf.date].some(value => value !== null && (typeof value !== 'string' || value.length > 500)))) throw new Error('草稿中的页眉页脚无效；原草稿已保留')
  const restoredSections = changes.sections ?? []
  if (!Array.isArray(restoredSections) || restoredSections.length > 100 || restoredSections.some(item => !item || Object.keys(item).sort().join() !== 'name,slideIndex' || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= deck.slides.length + restoredNew.length || restoredDeleted.includes(item.slideIndex) || typeof item.name !== 'string' || !item.name.trim() || item.name.length > 100)) throw new Error('草稿中的新增节无效；原草稿已保留')
  const restoredKinds = changes.shapeKinds ?? []
  if (!Array.isArray(restoredKinds) || restoredKinds.length > 500 || restoredKinds.some(item => !item || Object.keys(item).sort().join() !== 'elementId,kind,slideIndex' || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= deck.slides.length || restoredDeleted.includes(item.slideIndex)
    || !deck.slides[item.slideIndex]!.elements.some(element => element.id === item.elementId && element.type === 'shape') || !SHAPE_PRESETS.includes(item.kind) || LINE_SHAPE_KINDS.includes(item.kind))) throw new Error('草稿中的更改形状无效；原草稿已保留')
  const restoredStructures=changes.tableStructures === undefined ? [] : changes.tableStructures
  if (!Array.isArray(restoredStructures) || restoredStructures.length>100 || new Set(restoredStructures.map(item=>item?.slideIndex)).size!==restoredStructures.length || restoredStructures.some(item=>{
    if (!item || Object.keys(item).some(key=>!['slideIndex','elementId','kind','index','before'].includes(key)) || !Number.isInteger(item.slideIndex) || restoredDeleted.includes(item.slideIndex) || !['insert-row','delete-row','insert-col','delete-col'].includes(item.kind) || !Number.isInteger(item.index) || item.index<0 || (item.kind.startsWith('insert-')?typeof item.before!=='boolean':Object.hasOwn(item,'before'))) return true
    const table=deck.slides[item.slideIndex]?.elements.find(el=>el.id===item.elementId), cells=table?.tableCells
    if (!structureDimensions(table) || !cells || changes.slideSize || restoredReset.includes(item.slideIndex) || (changes.slideLayouts??[]).some(v=>v.slideIndex===item.slideIndex) || [...(changes.tableCells??[]),...(changes.tableStyles??[])].some(v=>v.slideIndex===item.slideIndex&&v.elementId===item.elementId)) return true
    const count=item.kind.endsWith('row')?cells.length:cells[0]?.length??0
    return item.index>=count || (item.kind.startsWith('delete-')?count<=1:count>=75)
  })) throw new Error('草稿中的表格行列操作无效；原草稿已保留')
  const restoredTableStyles = changes.tableStyles === undefined ? [] : changes.tableStyles
  let restoredCellShadingCount = 0
  if (!Array.isArray(restoredTableStyles) || restoredTableStyles.length > 500 || new Set(restoredTableStyles.map(item => item && editKey(item.slideIndex,item.elementId))).size !== restoredTableStyles.length || restoredTableStyles.some(item => {
    if (!item || Object.keys(item).some(key => !['slideIndex','elementId','shadingColor','borderPreset','styleName','cellShadings',...SLIDES_TABLE_FLAG_FIELDS].includes(key)) || !Number.isInteger(item.slideIndex) || restoredDeleted.includes(item.slideIndex)) return true
    const target = deck.slides[item.slideIndex]?.elements.find(el => el.id === item.elementId && el.type === 'table')
    const hasPreset = item.styleName !== undefined || SLIDES_TABLE_FLAG_FIELDS.some(field => item[field] !== undefined)
    const cellShadings = item.cellShadings
    if (cellShadings !== undefined) {
      if (!Array.isArray(cellShadings) || !cellShadings.length || (restoredCellShadingCount += cellShadings.length) > 500 || target?.tableCellShadingEditable !== true || (changes.deletions ?? []).some(deletion => deletion.slideIndex === item.slideIndex && deletion.elementId === item.elementId)
        || new Set(cellShadings.map(cell => cell && `${cell.row}:${cell.col}`)).size !== cellShadings.length
        || cellShadings.some(cell => !cell || Object.keys(cell).sort().join() !== 'col,row,shadingColor' || !Number.isInteger(cell.row) || !Number.isInteger(cell.col) || cell.row < 0 || cell.col < 0 || typeof target.tableCells?.[cell.row]?.[cell.col] !== 'string' || (cell.shadingColor !== 'none' && !TABLE_SHADING_COLORS.includes(cell.shadingColor)))) return true
    }
    return !target || (!hasPreset && item.shadingColor === undefined && item.borderPreset === undefined && cellShadings === undefined)
      || (hasPreset && (target.tablePresetEditable !== true || (changes.deletions ?? []).some(deletion => deletion.slideIndex === item.slideIndex && deletion.elementId === item.elementId)))
      || (item.styleName !== undefined && !SLIDES_TABLE_PRESETS.some(preset => preset.name === item.styleName))
      || SLIDES_TABLE_FLAG_FIELDS.some(field => Object.hasOwn(item,field) && typeof item[field] !== 'boolean')
      || (item.shadingColor !== undefined && item.shadingColor !== 'none' && !TABLE_SHADING_COLORS.includes(item.shadingColor))
      || (item.borderPreset !== undefined && !['all','none'].includes(item.borderPreset))
  })) throw new Error('草稿中的表格样式、选项、底纹或边框无效；原草稿已保留')
  const restoredTables = changes.tables ?? []
  if (!Array.isArray(restoredTables) || restoredTables.length > 100 || restoredTables.some(item => !item || Object.keys(item).sort().join() !== 'cols,rows,slideIndex' || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= deck.slides.length || restoredDeleted.includes(item.slideIndex) || ![item.rows, item.cols].every(value => Number.isInteger(value) && value >= 1 && value <= 75))) throw new Error('草稿中的新增表格无效；原草稿已保留')
  const restoredShapes = changes.shapes ?? []
  if (!Array.isArray(restoredShapes) || restoredShapes.length > 500 || restoredShapes.some(item => !item || Object.keys(item).sort().join() !== 'geometry,kind,slideIndex' || !Number.isInteger(item.slideIndex) || item.slideIndex < 0 || item.slideIndex >= deck.slides.length || restoredDeleted.includes(item.slideIndex) || !SHAPE_PRESETS.includes(item.kind) || !item.geometry || !(item.geometry.width >= 1) || !(item.geometry.height >= 1))) throw new Error('草稿中的新增形状无效；原草稿已保留')
  const slideTotal = deck.slides.length + restoredNew.length
  if (changes.order !== undefined && (!Array.isArray(changes.order) || changes.order.length !== slideTotal - restoredDeleted.length || changes.order.length > 500 || new Set(changes.order).size !== changes.order.length || changes.order.some(index => !Number.isInteger(index) || index < 0 || index >= slideTotal || restoredDeleted.includes(index)))) throw new Error('草稿页面顺序无效；原草稿已保留')
  // Validate every step before mutating the recovered view or the persisted history.
  try {
    if ((changes.paragraphFormatting?.length ?? 0) > 500) throw new Error('段落格式操作超过 500 条；请分批保存')
    for (const slide of deck.slides) for (const element of slide.elements) {
      projectParagraphs(element.paragraphFormatting, element.paragraphLists, (changes.paragraphFormatting ?? []).filter(patch => patch.slideIndex === slide.slideIndex && patch.elementId === element.id))
    }
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.message : '段落操作无效'}；原草稿已保留`)
  }
  const restoredSequences = changes.animationSequences ?? []
  try {
    if (!Array.isArray(restoredSequences) || new Set(restoredSequences.map(item => item?.slideIndex)).size !== restoredSequences.length) throw new Error('动画序列无效')
    for (const item of restoredSequences) {
      const slide = deck.slides[item.slideIndex]
      if (!slide || Object.keys(item).sort().join() !== 'items,slideIndex' || (changes.animations ?? []).some(edit => edit.slideIndex === item.slideIndex)) throw new Error('动画序列无效')
      validateSequence(item.items, slide.animations ?? [], slide.elements.map(element => ({ id: element.id, type: element.type, mediaKind:element.mediaKind, paragraphs: (changes.edits ?? []).findLast(edit => edit.slideIndex === item.slideIndex && edit.elementId === element.id && edit.text !== undefined)?.text?.split(/\r?\n/).length ?? element.paragraphFormatting?.length ?? element.paragraphAlignments?.length ?? (element.text ? element.text.split('\n').length : 0) })))
    }
  } catch (error) { throw new Error(`${error instanceof Error ? error.message : '动画序列无效'}；原草稿已保留`) }
  if (validateOnly) return
  masterTextEdits.splice(0, masterTextEdits.length, ...restoredMasterText)
  masterElementEdits.splice(0, masterElementEdits.length, ...restoredMasterElements)
  notesEdits.clear();for(const item of restoredNotes)notesEdits.set(item.slideIndex,item.text)
  groupEdits.splice(0, groupEdits.length, ...restoredGroups)
  linkEdits.splice(0,linkEdits.length,...restoredLinks)
  clipboardPastes.splice(0,clipboardPastes.length,...restoredPastes)
  elementOrders.clear();for(const item of restoredElementOrders)elementOrders.set(item.slideIndex,[...item.elementIds])
  commentEdits.splice(0, commentEdits.length, ...restoredComments)
  hiddenSlideEdits.clear()
  for (const item of restoredHidden) hiddenSlideEdits.set(item.slideIndex, item.hidden)
  edits.clear(); textFormattingEdits.clear(); paragraphFormattingEdits.splice(0); transitionEdits.clear(); layoutEdits.clear(); backgroundEdits.clear(); deletions.clear()
  for (const edit of changes.edits ?? []) {
    const key = editKey(edit.slideIndex, edit.elementId)
    edits.set(key, { ...edits.get(key), ...edit })
  }
  for (const format of changes.textFormatting ?? []) {
    const key = editKey(format.slideIndex, format.elementId)
    textFormattingEdits.set(key, { ...textFormattingEdits.get(key), ...format })
  }
  // Older drafts already stored an array: retain every record, including noncommuting list commands.
  paragraphFormattingEdits.push(...(changes.paragraphFormatting ?? []).map(format => ({ ...format })))
  for (const transition of transitions) transitionEdits.set(transition.slideIndex, transition.kind)
  for (const layout of changes.slideLayouts ?? []) layoutEdits.set(layout.slideIndex, layout.layoutPath)
  for (const background of changes.backgrounds ?? []) backgroundEdits.set(background.slideIndex, background.color)
  customShowEdits=restoredShows===undefined?undefined:structuredClone(restoredShows)
  backgroundImageEdits.splice(0, backgroundImageEdits.length, ...restoredBackgroundImages.map(item => ({ ...item, slideIndices: [...item.slideIndices] })))
  backgroundImageReuseEdits.splice(0,backgroundImageReuseEdits.length,...structuredClone(changes.backgroundImageReuses??[]))
  backgroundGradientEdits.splice(0, backgroundGradientEdits.length, ...(changes.backgroundGradients ?? []).map(item => ({ ...item, slideIndices: [...item.slideIndices] })))
  backgroundResetEdits.clear(); for (const index of changes.backgroundResets ?? []) backgroundResetEdits.add(index)
  backgroundGraphicsEdits.clear(); for (const item of changes.backgroundGraphics ?? []) backgroundGraphicsEdits.set(item.slideIndex, item.hidden)
  for (const deletion of changes.deletions ?? []) {
    const element = deck.slides[deletion.slideIndex]?.elements.find(item => item.id === deletion.elementId)
    deletions.set(editKey(deletion.slideIndex, deletion.elementId), { ...deletion, label: element?.name || element?.text || deletion.elementId })
  }
  animationEdits.splice(0, animationEdits.length, ...(changes.animations ?? []))
  animationSequences.clear(); for (const item of restoredSequences) animationSequences.set(item.slideIndex, item.items.map(entry => ({ ...entry })))
  selectedAnimationRow = -1
  textBoxEdits.splice(0, textBoxEdits.length, ...(changes.textBoxes ?? []).map(box => ({ ...box, watermark: box.rotation === -25 })))
  newSlides.splice(0, newSlides.length, ...restoredNew.map((item): NewSlide => 'duplicateOf' in item ? { duplicateOf: item.duplicateOf } : 'withLayout' in item ? { withLayout: item.withLayout } : { layoutFrom: item.layoutFrom }))
  deletedSlides.clear(); for (const index of restoredDeleted) deletedSlides.add(index)
  resetLayouts.clear(); for (const index of restoredReset) resetLayouts.add(index)
  headerFooterEdit = restoredHf ? { ...restoredHf } : undefined
  smartArtEdits.splice(0, smartArtEdits.length, ...restoredSmartArts.map(item => structuredClone(item)))
  chartEdits.splice(0, chartEdits.length, ...restoredCharts.map(item => structuredClone(item)))
  modelInsertions.splice(0,modelInsertions.length,...structuredClone(changes.modelInsertions??[]));modelViews.splice(0,modelViews.length,...structuredClone(changes.modelViews??[]))
  mediaInsertions.splice(0,mediaInsertions.length,...structuredClone(changes.mediaInsertions??[]))
  zoomInsertions.splice(0,zoomInsertions.length,...structuredClone(changes.zoomInsertions??[]))
  nativeImages.splice(0,nativeImages.length,...structuredClone(changes.images??[]))
  pictureReplacements.splice(0,pictureReplacements.length,...structuredClone(changes.pictureReplacements??[]))
  pictureCrops.splice(0,pictureCrops.length,...structuredClone(changes.pictureCrops??[]))
  pictureOpacities.splice(0, pictureOpacities.length, ...restoredOpacities.map(item => ({ ...item })))
  nativeChartEdits.splice(0,nativeChartEdits.length,...structuredClone(changes.chartEdits??[]))
  tableStructureEdits.clear(); for(const item of restoredStructures) tableStructureEdits.set(item.slideIndex,{...item})
  tableShadingCell = undefined
  tableStyleEdits.clear(); for (const item of restoredTableStyles) tableStyleEdits.set(editKey(item.slideIndex,item.elementId), structuredClone(item))
  tableCellEdits.clear(); for (const item of restoredCells) tableCellEdits.set(`${item.slideIndex}:${item.elementId}:${item.row}:${item.col}`, { ...item })
  sectionEdits.splice(0, sectionEdits.length, ...restoredSections.map(item => ({ slideIndex: item.slideIndex, name: item.name })))
  shapeKindEdits.clear(); for (const item of restoredKinds) shapeKindEdits.set(editKey(item.slideIndex, item.elementId), { ...item })
  shapeStyleEdits.clear(); for (const item of restoredStyles) shapeStyleEdits.set(editKey(item.slideIndex, item.elementId), structuredClone(item))
  tableEdits.splice(0, tableEdits.length, ...restoredTables.map(item => ({ slideIndex: item.slideIndex, rows: item.rows, cols: item.cols })))
  shapeEdits.splice(0, shapeEdits.length, ...restoredShapes.map(item => ({ slideIndex: item.slideIndex, kind: item.kind, geometry: { ...item.geometry } })))
  order.splice(0, order.length, ...(changes.order ?? deck.slides.map(slide => slide.slideIndex)))
  if (!order.includes(selectedSlide)) selectedSlide = order[0] ?? 0
  selectedTheme = changes.theme
  slideSizeEdit = changes.slideSize
  dirty = nativeDraft.dirty
  renderStructurePending()
  updateNativeHistory()
}

/** 所有评论操作都保留原始来源页身份，整批验证后才更改草稿。 */
function changeComments(next: CommentEdit[]): boolean {
  try {
    const checked = validateCommentEdits(next, deck.slides, [...deletedSlides])
    commentEdits.splice(0, commentEdits.length, ...checked)
    const changes = slideChanges()
    const meaningful = Object.entries(changes).some(([key, value]) => key === 'order'
      ? JSON.stringify(value) !== JSON.stringify(deck.slides.map(slide => slide.slideIndex))
      : Array.isArray(value) ? value.length > 0 : value !== undefined)
    if (nativeDraft && !meaningful) {
      nativeDraft.setOperations([]); dirty = false; updateNativeHistory()
      stateLabel.textContent = '可编辑'; statusMessage.textContent = nativeDraft.persistenceError ?? '已撤回批注修改'
    } else markDirty()
    renderInspector()
    return true
  } catch (error) {
    statusMessage.textContent = error instanceof Error ? error.message : '批注修改无效'
    return false
  }
}
const commentPane = createSlidesCommentsPane({
  onAdd: items => changeComments([...commentEdits, ...items.map(item => ({ ...item, kind: 'add' as const, clientId: crypto.randomUUID() }))]),
  onDelete: (slideIndex, item) => { changeComments([...commentEdits, { slideIndex, kind: 'delete', authorId: item.authorId, idx: item.idx }]) },
  onWithdraw: clientId => { changeComments(commentEdits.filter(edit => edit.kind !== 'add' || edit.clientId !== clientId)) },
  onClose: () => {
    commentsPaneOpen = false; renderComments()
    const opener = root.querySelector<HTMLButtonElement>('[data-command="commentsPane"]')
    const target = opener && !opener.disabled && !opener.closest('[hidden]') ? opener : root.querySelector<HTMLButtonElement>('.slides-native-ribbon-tabs [aria-selected="true"]')
    target?.focus()
  },
})
root.querySelector('.slides-workspace')!.append(commentPane.element)
const notesPane=native?createSlidesNotesPane(root.querySelector<HTMLElement>('.slides-stage')!,{
  onChange:(slideIndex,text)=>{
    if(disposed||!deck||!nativeDraft||locked()||slideIndex!==selectedSlide||isNewSlide(slideIndex)||nativeDraft.identity.sourceSha256!==deck.sha256)throw new Error('备注来源或当前修订已变化，请重新打开')
    const source=deck.slides[slideIndex]!,current=notesEdits.get(slideIndex)??source.notesText??''
    if(text===current)return
    const changes=slideChanges(),items=[...(changes.notesEdits??[]).filter(item=>item.slideIndex!==slideIndex)]
    if(text!==(source.notesText??''))items.push({slideIndex,text})
    if(items.length)changes.notesEdits=items;else delete changes.notesEdits
    restoreNativeDraft([{kind:'editSlides',...changes}],true)
    nativeDraft.setOperations([{kind:'editSlides',...changes}])
    notesEdits.clear();for(const item of validateSlidesNotesDraft(changes,deck.slides))notesEdits.set(item.slideIndex,item.text)
    dirty=true;stateLabel.textContent='有未保存修改';statusMessage.textContent=nativeDraft.persistenceError??'备注修改尚未保存'
    updateNativeHistory();updateClipboardControls();renderStructurePending();nativeAIHost?.refresh()
  },
  onError:message=>{statusMessage.textContent=message},
  onVisibleChange:visible=>{notesVisible=visible;syncNotesVisibility()},
}):undefined
function syncNotesVisibility(){
  const pane=root.querySelector<HTMLElement>('[data-notes-panel]');if(pane)pane.hidden=!notesVisible
  nativeRibbon?.setValue('notes',String(notesVisible))
  syncGrid()
}
function renderNotes(){
  if(!notesPane||!deck)return
  const source=deck.slides[selectedSlide],fresh=isNewSlide(selectedSlide)
  notesPane.update({slideIndex:selectedSlide,text:notesEdits.get(selectedSlide)??source?.notesText??'',editable:!locked()&&!fresh&&source?.notesEditable===true,reason:fresh?NEW_SLIDE_REASON:source?.notesReason??'此来源备注暂不可编辑',visible:notesVisible})
  syncNotesVisibility()
}

function renderComments() {
  if (!native || !deck) return
  const reason = isNewSlide(selectedSlide) ? NEW_SLIDE_REASON : sourceComments(deck.slides[selectedSlide]?.comments).readOnlyReason
  root.querySelector<HTMLElement>('.slides-inspector')!.hidden = commentsPaneOpen
  commentPane.update({ visible: commentsPaneOpen, slideIndex: selectedSlide, pageNumber: order.indexOf(selectedSlide) + 1,
    source: deck.slides[selectedSlide]?.comments, edits: commentEdits, locked: locked(), ...(reason ? { reason } : {}) })
  nativeRibbon?.setValue('commentsPane', String(commentsPaneOpen))
  nativeRibbon?.setCommentEditEnabled(!reason, reason ?? undefined)
}

function renderPendingImages() {
  imagePending.replaceChildren()
  for (const [index, edit] of imageEdits.entries()) {
    const item = document.createElement('li')
    item.append(document.createTextNode(`第 ${order.indexOf(edit.slideIndex) + 1} 页 · AI 配图 ${index + 1}`))
    const remove = buttonIcon(X, '移除待保存配图')
    remove.addEventListener('click', () => {
      imageEdits.splice(index, 1)
      renderPendingImages()
      markDirty()
    })
    item.append(remove)
    imagePending.append(item)
  }
}

function renderSlides() {
  list.replaceChildren()
  for (const [position, slideIndex] of order.entries()) {
    const slide = slideAt(slideIndex)
    const row = document.createElement('li')
    row.className = 'slide-row'
    row.dataset.selected = String(slideIndex === selectedSlide)
    row.dataset.hidden = String(hiddenSlideEdits.get(slideIndex) ?? slide.hidden ?? false)
    const open = document.createElement('button')
    open.type = 'button'
    open.className = 'slide-open'
    open.dataset.slideIndex = String(slideIndex)
    open.innerHTML = `<span class="slide-number">${position + 1}</span><span class="slide-title"></span>`
    open.querySelector('.slide-title')!.textContent = isNewSlide(slideIndex) ? newSlideTitle(newSlides[slideIndex - deck.slides.length]!) : flatText(slide)
    if (row.dataset.hidden === 'true') { const badge = document.createElement('span'); badge.className = 'slide-hidden-badge'; badge.textContent = '已隐藏'; open.append(badge) }
    open.addEventListener('click', () => { if(notesPane&&!notesPane.flush())return;selectedSlide = slideIndex; renderSlides(); renderInspector() })
    const up = buttonIcon(ArrowUp, '上移页面')
    const down = buttonIcon(ArrowDown, '下移页面')
    up.disabled = position === 0
    down.disabled = position === order.length - 1
    up.addEventListener('click', () => move(position, -1))
    down.addEventListener('click', () => move(position, 1))
    row.append(open, up, down)
    if (!isNewSlide(slideIndex)) {
      row.dataset.sourceSlide = 'true'
      const duplicate = buttonIcon(Copy, '复制幻灯片')
      duplicate.disabled = locked()
      duplicate.addEventListener('click', () => duplicateSourceSlide(slideIndex))
      const remove = buttonIcon(Trash2, '删除幻灯片')
      remove.disabled = locked() || order.length <= 1
      remove.addEventListener('click', () => deleteSourceSlide(slideIndex))
      row.append(duplicate, remove)
    }
    if (isNewSlide(slideIndex)) {
      row.dataset.newSlide = 'true'
      const remove = buttonIcon(X, '移除新建的幻灯片')
      remove.disabled = locked()
      remove.addEventListener('click', () => removeNewSlide(slideIndex))
      row.append(remove)
    }
    // 节标题：已有节在其首页前显示；待新增的节在目标页前显示（保存后写入）。
    for (const section of deck.sections ?? []) if (section.slideIndices[0] === slideIndex) { const header = document.createElement('li'); header.className = 'slide-section'; header.textContent = section.name; list.append(header) }
    for (const section of sectionEdits) if (section.slideIndex === slideIndex) { const header = document.createElement('li'); header.className = 'slide-section'; header.dataset.pending = 'true'; header.textContent = `${section.name}（保存后写入）`; list.append(header) }
    list.append(row)
  }
  root.querySelector('.slide-count')!.textContent = String(order.length)
  renderStructurePending()
  renderCanvas()
  if (!canvas) preview.src = `${basePath}/api/preview.pdf#page=${selectedSlide + 1}&toolbar=0&navpanes=0`
}

function move(position: number, direction: -1 | 1) {
  if(notesPane&&!notesPane.flush())return
  const target = position + direction
  if (target < 0 || target >= order.length) return
  ;[order[position], order[target]] = [order[target]!, order[position]!]
  selectedSlide = order[target]!
  undoSnapshot = undefined
  undoButton.disabled = true
  renderSlides()
  renderInspector()
  markDirty()
}

function transitionEditingAllowed(slide: DeckSlide | undefined) {
  return !native || (slide?.transitionEditSafe ?? slide?.transitionApplyAllSafe) === true
}
function transitionEditUnavailable(): string | null {
  if (isNewSlide(selectedSlide)) return NEW_SLIDE_REASON
  return transitionEditingAllowed(deck.slides[selectedSlide]) ? null : '此页含尚不能安全修改的转场兼容性内容，请保留原转场'
}
function transitionApplyAllUnavailable(): string | null {
  if (!order.length || order.length > 500 || !order.includes(selectedSlide)) return '请先打开可编辑的演示文稿；一次最多支持 500 页'
  if (newSlides.length) return NEW_SLIDE_REASON
  if (order.some(index => deck.slides[index]?.transitionApplyAllSafe !== true)) return '部分页面含未支持的转场速度、换片、声音或效果变体设置，暂不能全部应用；原文件保持不变'
  return null
}

function renderInspector() {
  if(typeof nativeRibbon!=='undefined'){mountInkControls();mountModelControls()}
  modelControls?.update()
  inkControls?.update()
  if(cutoutCurrent&&!cutoutCurrent()){++cutoutGeneration;cutoutDialog?.dispose();cutoutDialog=undefined;cutoutCurrent=undefined}
  backgroundPane?.update(backgroundPaneSlide(),backgroundPaneKey(),locked())
  renderNotes()
  if(selectionSlide!==selectedSlide){selectedObjects.clear();selectionSlide=selectedSlide;explicitEmptySelection=false;cropOverlay?.dispose();cropOverlay=undefined}
  renderComments()
  // 表格虽不能整体编辑/删除，但单元格可改字，因此也列入可选对象。
  const elements = slideAt(selectedSlide).elements.filter(item => (item.editable || item.deletable || !!item.tableCells || item.type === 'chart' || item.type === 'group' || item.model3d) && !deletions.has(editKey(selectedSlide, item.id)))
  select.replaceChildren(...elements.map(item => {
    const option = document.createElement('option')
    option.value = item.id
    option.textContent = item.name || item.text.split('\n')[0]?.slice(0, 60) || item.type
    return option
  }))
  selectedObjects = new Set([...selectedObjects].filter(id=>elements.some(item=>item.id===id)))
  if (!elements.some(item => item.id === selectedElement)) selectedElement = [...selectedObjects][0] ?? (explicitEmptySelection?'':elements[0]?.id ?? '')
  if(selectedElement&&!selectedObjects.has(selectedElement))selectedObjects=new Set([selectedElement])
  renderArrangeSelection(elements)
  select.value = selectedElement
  nativeAIHost?.refresh()
  const element = currentElement()
  if(native){const chartSelected=element?.type==='chart';textArea.hidden=chartSelected;root.querySelector<HTMLElement>('label[for="object-text"]')!.hidden=chartSelected}
  textArea.disabled = pendingGroup(selectedSlide) || selectedObjects.size>1 || savedRevision || !element || !['text', 'shape'].includes(element.type)
  renderTableCellEditor(element)
  textArea.value = element ? edits.get(editKey(selectedSlide, element.id))?.text ?? element.text : ''
  const box = element && (edits.get(editKey(selectedSlide, element.id))?.geometry ?? pictureCrops.find(item=>item.slideIndex===selectedSlide&&item.elementId===element.id)?.geometry ?? element.geometry)
  const geometry = box ?? { x: 0, y: 0, width: 0, height: 0 }
  geometryPane?.update(selectedObjects.size===1&&element&&box?{target:editKey(selectedSlide,element.id),picture:element.type==='picture',geometry:box,slideSize:{width:deck.size.cx/9525,height:deck.size.cy/9525},reason:!element.arrangeEditable?'该来源对象暂不支持安全修改大小与位置':slideSizeEdit?'请先保存页面尺寸修改，再编辑对象大小与位置':undefined}:null,locked()||pendingGroup(selectedSlide))
  renderCanvas()
  for (const input of currentGeometryInputs()) {
    input.value = String(geometry[input.name as keyof typeof geometry] ?? 0)
    input.disabled = pendingGroup(selectedSlide) || selectedObjects.size>1 || savedRevision || !(element?.editable||element?.arrangeEditable)
  }
  backgroundColor.value = (backgroundEdits.get(selectedSlide) ?? slideAt(selectedSlide).background ?? '#FFFFFF').toLowerCase()
  backgroundReset.disabled = !backgroundEdits.has(selectedSlide)
  objectDelete.disabled = selectedObjects.size>1 || !element?.deletable || chartTools.hasPending(selectedSlide, element.id)
  objectDelete.title = element && chartTools.hasPending(selectedSlide, element.id) ? '该图表有待保存的 AI 改图，请先撤销采纳' : '删除对象'
  themeSelect.value = selectedTheme ?? ''
  transitionSelect.value = transitionEdits.get(selectedSlide) ?? slideAt(selectedSlide).transition ?? 'none'
  const slide = slideAt(selectedSlide)
  const layouts = deck.layouts ?? []
  layoutSelect.replaceChildren(...layouts.map(layout => {
    const option = document.createElement('option')
    option.value = layout.path
    option.textContent = slidesLayoutLabel(layout)
    return option
  }))
  layoutSelect.value = layoutEdits.get(selectedSlide) ?? slide.layoutPath ?? ''
  layoutSelect.disabled = locked() || tableStructureEdits.has(selectedSlide) || layouts.length === 0 || isNewSlide(selectedSlide)
  const newSlideSelected = isNewSlide(selectedSlide)
  for (const control of [backgroundColor, textAdd, watermarkAdd]) { control.disabled ||= newSlideSelected; control.title = newSlideSelected ? NEW_SLIDE_REASON : control.title === NEW_SLIDE_REASON ? '' : control.title }
  if (newSlideSelected) backgroundReset.disabled = true
  const masterPath = slide.masterPath ?? ''
  const master = (deck.masterParts ?? []).find(item => item.partPath === masterPath)
  slideMaster.textContent = master?.name || masterPath || '未读取'
  const existingAnimation = animationEdits.findLast(item => item.slideIndex === selectedSlide && item.elementId === selectedElement)
    ?? slide.animations?.find(item => item.elementId === selectedElement)
  animationEffect.value = existingAnimation?.effect ?? (element?.mediaKind?'mediaPlay':'fade')
  animationTrigger.value = existingAnimation?.trigger ?? 'onClick'
  animationDuration.value = String(existingAnimation?.durationMs ?? (element?.mediaKind?0:500))
  animationDelay.value = String(existingAnimation?.delayMs ?? 0)
  animationDurationMs = Number(animationDuration.value)
  animationDelayMs = Number(animationDelay.value)
  animationDirection = (existingAnimation?.direction as AnimationDirection | undefined) ?? 'bottom'
  animationAdd.disabled = selectedObjects.size!==1 || !(element?.editable||element?.mediaKind)
  animationState.textContent = existingAnimation ? `已有 ${existingAnimation.effect} 动画，可继续添加。` : ''
  renderAnimationPane()
  const selectedRow = selectedAnimationRow >= 0 ? currentSequence()[selectedAnimationRow] : undefined
  if (selectedRow) {
    // 窗格选中行时，计时控件显示并修改该动画（固定源 timingIdx）。
    const row = resolvedItem(selectedRow, sourceAnimations())
    animationTrigger.value = row.trigger; animationDuration.value = String(row.durationMs); animationDelay.value = String(row.delayMs)
    animationDurationMs = row.durationMs; animationDelayMs = row.delayMs
  } else selectedAnimationRow = -1
  nativeRibbon?.setValue('toggleAnimationPane', String(animationPaneOpen))
  nativeRibbon?.setValue('animationByParagraph', String(animationByParagraph))
  root.querySelector('.slides-inspector > .inspector-heading')!.textContent = `对象 · 第 ${order.indexOf(selectedSlide) + 1} 页`
  nativeRibbon?.setValue('hideSlide', String(hiddenSlideEdits.get(selectedSlide) ?? slideAt(selectedSlide).hidden ?? false))
  nativeRibbon?.setValue('theme', selectedTheme ?? '')
  const transitionReason = transitionEditUnavailable()
  transitionSelect.disabled = locked() || transitionReason !== null
  transitionSelect.title = transitionReason ?? '更改视觉转场效果；保留原速度、换片、声音及扩展设置'
  nativeRibbon?.setValue('transition', transitionSelect.value)
  nativeRibbon?.setTransitionEditEnabled(transitionReason === null, transitionReason ?? undefined)
  nativeRibbon?.setTransitionApplyAllEnabled(transitionApplyAllUnavailable() === null, transitionApplyAllUnavailable() ?? undefined)
  nativeRibbon?.setValue('layout', layoutSelect.value)
  const size = slideSizeEdit ?? deck.size
  nativeRibbon?.setValue('slideSize', matchSlideSizePreset(size) ?? '')
  nativeRibbon?.setValue('slideOrientation', isPortrait(size) ? 'portrait' : 'landscape')
  nativeRibbon?.setSlideOrientationEnabled(isWritableSlideSize(size))
  nativeRibbon?.setValue('background', backgroundColor.value)
  { const picture = currentElement(), pending = picture ? pictureOpacities.find(item => item.slideIndex === selectedSlide && item.elementId === picture.id) : undefined
    nativeRibbon?.setValue('pictureOpacity', picture?.type === 'picture' ? String(Math.round((1 - (pending?.opacity ?? picture.pictureOpacity ?? 1)) * 100)) : '') }
  nativeRibbon?.setValue('animationEffect', animationEffect.value)
  nativeRibbon?.setValue('animationTrigger', animationTrigger.value)
  nativeRibbon?.setValue('animationDuration', animationDuration.value)
  nativeRibbon?.setValue('animationDelay', animationDelay.value)
  nativeRibbon?.setValue('animationDirection', animationDirection)
  const textStyle = element?.textStyle ?? {}
  const textFormat = element ? textFormattingEdits.get(editKey(selectedSlide, element.id)) : undefined
  nativeRibbon?.setValue('bold', String(textFormat?.bold ?? textStyle.bold ?? false))
  nativeRibbon?.setValue('italic', String(textFormat?.italic ?? textStyle.italic ?? false))
  nativeRibbon?.setValue('underline', String(textFormat?.underline ?? textStyle.underline ?? false))
  nativeRibbon?.setValue('strike', String(textFormat?.strike ?? textStyle.strike ?? false))
  nativeRibbon?.setValue('fontSize', String(textFormat?.fontSizePt ?? textStyle.fontSizePt ?? ''))
  nativeRibbon?.setValue('fontFamily', textFormat?.fontFamily ?? textStyle.fontFamily ?? '')
  nativeRibbon?.setValue('fontColor', (textFormat?.color ?? textStyle.color ?? '#000000').toLowerCase())
  const paragraphs = projectedParagraphs(element)
  nativeRibbon?.setValue('paragraphAlign', uniformParagraphValue(paragraphs, 'align') ?? '')
  for (const field of ['lineSpacingPct', 'spaceBeforePt', 'spaceAfterPt'] as const) {
    const value = uniformParagraphValue(paragraphs, field)
    const supported = typeof value === 'number' && (field !== 'lineSpacingPct' || [100, 115, 150, 200, 250, 300].includes(value))
    nativeRibbon?.setValue(field, supported ? String(value) : '', supported ? (field === 'lineSpacingPct' ? '行距倍数' : '段距（磅）；Enter 提交') : '未设置、混合值或源单位不适用；可明确设置新值')
  }
  const unset = '未设置或混合值；作用于当前对象的全部段落'
  const kind = uniformParagraphValue(paragraphs, 'bulletKind')
  nativeRibbon?.setValue('bulletKind', kind ?? '')
  const char = uniformParagraphValue(paragraphs, 'bulletChar')
  const font = uniformParagraphValue(paragraphs, 'bulletFont')
  const glyphIndex = BULLET_GLYPHS.findIndex(([glyph, family]) => glyph === char && family === font)
  nativeRibbon?.setValue('bulletCharPreset', kind === 'char' && glyphIndex >= 0 ? String(glyphIndex) : '', unset)
  nativeRibbon?.setValue('bulletSymbol', kind === 'char' && font === 'Arial' ? char ?? '' : '', unset)
  nativeRibbon?.setValue('bulletCustomChar', kind === 'char' ? char ?? '' : '', unset)
  for (const field of ['numType', 'startAt', 'bulletSizePct', 'bulletColor'] as const) {
    const value = uniformParagraphValue(paragraphs, field)
    const shown = value === null || value === undefined ? '' : String(value)
    nativeRibbon?.setValue(field, shown, shown ? '当前对象全部段落；自定义输入 Enter 提交' : unset)
    if (field === 'bulletColor') nativeRibbon?.setValue('bulletColorPreset', shown, unset)
  }
  const indent = uniformParagraphValue(paragraphs, 'indentEmu')
  const hang = typeof indent === 'number' && (indent < 0 || (indent === 0 && !!kind && kind !== 'none')) ? -indent : undefined
  nativeRibbon?.setValue('bulletHangEmu', hang === undefined ? '' : String(hang), unset)
  nativeRibbon?.setValue('bulletHangPx', hang === undefined ? '' : String(hang / 9525), unset)
  const rtl = uniformParagraphValue(paragraphs, 'rtl')
  nativeRibbon?.setValue('paragraphDirection', typeof rtl === 'boolean' ? String(rtl) : '')
  const contextualType: NativeSlidesContext = !element ? null
    : element.model3d ? 'model3d'
    : element.type === 'table' ? 'table'
      : element.type === 'chart' ? 'chart'
        : element.type === 'picture' ? 'picture'
          : element.type === 'model3d' ? 'model3d'
            : ['shape', 'text'].includes(element.type) ? 'shape' : null
  nativeRibbon?.setContext(selectedObjects.size>1?null:contextualType)
  const chartPatch=nativeChartEdits.find(item=>item.slideIndex===selectedSlide&&item.elementId===element?.id)
  chartFormatPane?.update(selectedObjects.size===1&&element?.type==='chart'&&element.chartKind&&element.chartCategories&&element.chartSeries?{
    target:`${deck.sha256}:${selectedSlide}:${element.id}`,kind:chartPatch?.kind??element.chartKind,...nativeChartData(element,chartPatch),
    pointColors:nativeChartPointColors(element,chartPatch),seriesColors:chartPatch?.colorScheme?(element.chartColorSchemes??chartColorSchemes()).find(scheme=>scheme.key===chartPatch.colorScheme)?.colors:element.chartSeriesColors??undefined,
    reason:pendingGroup(selectedSlide)?'请先保存或撤销本页组合操作':!element.chartEditSafe?element.chartEditReason??'此来源图表不能安全修改单点配色':undefined,
  }:null,locked())
  nativeRibbon?.setChartDesign(selectedObjects.size===1&&element?.chartEditSafe&&element.chartKind&&element.chartStyle?{
    target:`${deck.sha256}:${selectedSlide}:${element.id}`,kind:chartPatch?.kind??element.chartKind,
    style:{...element.chartStyle,gapWidthPct:element.chartGapWidthPct??150,...chartPatch},colorSchemes:element.chartColorSchemes??chartColorSchemes(),
  }:null)
  shapeFormatPane?.update()
  updateArrangeControls(); updateElementOrderControls(); updateGroupControls(); updateClipboardControls()
  for(const [command,enabled,reason] of [
    ['removeBackground',!cutoutReason(),cutoutReason()??''],
    ['cropPicture',!cropReason(),cropReason()??''],
    ['pictureOpacity', !opacityReason(), opacityReason() ?? '图片透明度（0–100%）：0 为不透明'],
    ['replacePicture',selectedObjects.size===1&&!element?.mediaKind&&element?.pictureReplaceable===true&&!pictureCrops.some(item=>item.slideIndex===selectedSlide&&item.elementId===element?.id),pictureCrops.some(item=>item.slideIndex===selectedSlide&&item.elementId===element?.id)?'请先保存或撤回此图片裁切':element?.pictureReplaceReason??'请选择已核验身份的来源图片'],
    ['chartData',selectedObjects.size===1&&element?.chartEditSafe===true,'此来源图表不能安全编辑数据'],
    ['chartType',selectedObjects.size===1&&element?.chartEditSafe===true,'此来源图表不能安全更改类型'],
    ['chartElements',selectedObjects.size===1&&element?.chartEditSafe===true,'此来源图表不能安全修改图表元素'],
    ['chartDesignPresets',selectedObjects.size===1&&element?.chartEditSafe===true,'此来源图表不能安全修改配色与样式'],
    ['chartPointColors',selectedObjects.size===1&&element?.chartEditSafe===true&&(nativeChartEdits.find(item=>item.slideIndex===selectedSlide&&item.elementId===element.id)?.kind??element.chartKind)!=='scatter','此来源或散点图不能安全修改单点配色'],
    ['chartSwitchRowCol',selectedObjects.size===1&&element?.chartEditSafe===true,'此来源图表不能安全交换行列'],
    ['insertPicture',!isNewSlide(selectedSlide),NEW_SLIDE_REASON],
    ['insertAudio',!isNewSlide(selectedSlide),NEW_SLIDE_REASON],
    ['insertVideo',!isNewSlide(selectedSlide),NEW_SLIDE_REASON],
    ['screenRecording',!isNewSlide(selectedSlide),NEW_SLIDE_REASON],
    ['insertModel3d',!isNewSlide(selectedSlide),NEW_SLIDE_REASON],
  ] as const) {
    const button=root.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)
    if(button){button.disabled=locked()||!enabled;button.title=enabled?'':reason}
  }

  const structureButton=root.querySelector<HTMLButtonElement>('[data-command="tableStructure"]')
  if(structureButton){const reason=tableStructureReason(element);structureButton.disabled=!!reason;structureButton.title=reason??'增删来源表格行列'}
  for(const id of ['tableShading','tableAllBorders','tableNoBorders']) {const control=root.querySelector<HTMLInputElement>(`[data-command="${id}"]`);if(control) { const atLimit=!!element && !tableStyleEdits.has(editKey(selectedSlide,element.id)) && tableStyleEdits.size>=500; control.disabled=locked() || tableStructureEdits.get(selectedSlide)?.elementId===element?.id || atLimit; if(atLimit) control.title='表格样式修改已达到 500 项，请先保存'; else if(control.title==='表格样式修改已达到 500 项，请先保存') control.title='' }}
  const tablePatch = element ? tableStyleEdits.get(editKey(selectedSlide,element.id)) : undefined
  const tablePreset = SLIDES_TABLE_PRESETS.find(item => item.name === tablePatch?.styleName)
  const presetReason = tablePresetReason(element)
  for (const id of ['tableStyle','tableFirstRow','tableBandRow','tableRtl']) {
    const control = root.querySelector<HTMLSelectElement | HTMLButtonElement>(`[data-command="${id}"]`)
    if (control) { control.disabled = !!presetReason; control.title = presetReason ?? '固定表格预设与选项；预设会清除直接底纹和边框，保留文字与表格方向' }
  }
  nativeRibbon?.setValue('tableStyle', tablePatch?.styleName ?? (SLIDES_TABLE_PRESETS.some(item => item.name === element?.tableStyleName) ? element!.tableStyleName! : ''))
  nativeRibbon?.setValue('tableFirstRow', String(tablePatch?.firstRow ?? tablePreset?.firstRow ?? element?.tableStyleFlags?.firstRow ?? false))
  nativeRibbon?.setValue('tableBandRow', String(tablePatch?.bandRow ?? tablePreset?.bandRow ?? element?.tableStyleFlags?.bandRow ?? false))
  nativeRibbon?.setValue('tableRtl', String(tablePatch?.rtl ?? element?.tableStyleFlags?.rtl ?? false))
  updateTableShadingControls(element)
  nativeRibbon?.setListTargets({ bullets: paragraphs.some(p => !!p.bulletKind && p.bulletKind !== 'none'), numbers: paragraphs.some(p => p.bulletKind === 'number'), hanging: paragraphs.some(p => (!!p.bulletKind && p.bulletKind !== 'none') || (p.indentEmu ?? 0) < 0) })
  nativeRibbon?.setTextFormatEnabled(selectedObjects.size<=1 && !!element?.editable && !!element.text.trim())
}

function shadingCellFor(element = currentElement()) {
  if (tableShadingCell && (tableShadingCell.slideIndex !== selectedSlide || tableShadingCell.elementId !== element?.id || typeof element.tableCells?.[tableShadingCell.row]?.[tableShadingCell.col] !== 'string')) tableShadingCell = undefined
  return tableShadingCell
}
function updateTableShadingControls(element = currentElement()) {
  const selectedCell = shadingCellFor(element)
  const targetLabel = tableCellEditor.querySelector<HTMLElement>('[data-table-shading-target]')
  if (targetLabel) targetLabel.textContent = selectedCell ? `底纹目标：第 ${selectedCell.row + 1} 行 ${selectedCell.col + 1} 列` : '底纹目标：整表'
  const palette = root.querySelector<HTMLSelectElement>('[data-command="tableShading"]')
  const whole = root.querySelector<HTMLButtonElement>('[data-command="tableShadingWholeTable"]')
  const commonReason = selectedObjects.size>1 || locked() || isNewSlide(selectedSlide) || element?.type !== 'table' || deletions.has(editKey(selectedSlide,element.id)) || tableStructureEdits.get(selectedSlide)?.elementId === element.id
  const reason = element && !tableStyleEdits.has(editKey(selectedSlide,element.id)) && tableStyleEdits.size >= 500 ? '表格样式修改已达到 500 项，请先保存' : selectedCell && element?.tableCellShadingEditable !== true ? element?.tableCellShadingReason || '此来源表格暂不支持安全单格底纹' : ''
  if (palette) { palette.disabled = !!commonReason || !!reason; palette.title = reason || (selectedCell ? `只修改第 ${selectedCell.row + 1} 行 ${selectedCell.col + 1} 列底纹` : '修改整表底纹，并清除此前的单格底纹覆盖') }
  if (whole) { whole.disabled = !!commonReason || !selectedCell; whole.title = '将底纹作用目标改回整表；不修改草稿' }
  const patch = element ? tableStyleEdits.get(editKey(selectedSlide,element.id)) : undefined
  nativeRibbon?.setValue('tableShading', selectedCell ? patch?.cellShadings?.find(cell => cell.row === selectedCell.row && cell.col === selectedCell.col)?.shadingColor ?? '' : patch?.shadingColor ?? '')
}

function tablePresetReason(element = currentElement()): string | null {
  if (locked() || selectedObjects.size>1) return '请选择单一来源表格后编辑样式'
  if (isNewSlide(selectedSlide) || element?.type !== 'table' || deletions.has(editKey(selectedSlide,element.id))) return '请选择未删除的来源表格'
  if (tableStructureEdits.get(selectedSlide)?.elementId === element.id) return '请先保存或撤销此表的行列操作'
  if (element.tablePresetEditable !== true) return element.tablePresetReason || '来源表格样式或样式关系尚未确认可安全修改'
  if (!tableStyleEdits.has(editKey(selectedSlide,element.id)) && tableStyleEdits.size >= 500) return '表格样式修改已达到 500 项，请先保存'
  return null
}

function projectedParagraphs(element: DeckElement | undefined) {
  const formatting = element?.paragraphFormatting ?? element?.paragraphAlignments?.map(align => ({ align })) ?? []
  return projectParagraphs(formatting, element?.paragraphLists ?? [], paragraphFormattingEdits.filter(patch => patch.slideIndex === selectedSlide && patch.elementId === element?.id))
}
function updateSelectedParagraph(patch: Omit<ParagraphFormatting, 'slideIndex' | 'elementId'>) {
  const element = currentElement()
  if (selectedObjects.size>1 || !element?.editable || !element.text.trim()) return
  // Avoid recording conditional commands that have no target. The source only applies these to existing lists.
  const paragraphs = projectedParagraphs(element)
  const bulleted = paragraphs.some(p => p.bulletKind && p.bulletKind !== 'none')
  if (!patch.bullet && (patch.bulletSizePct !== undefined || patch.bulletColor !== undefined) && !bulleted) return
  if (!patch.bullet && patch.startAt !== undefined && !paragraphs.some(p => p.bulletKind === 'number')) return
  let proposal
  try {
    proposal = projectParagraphs(paragraphs, paragraphs, [patch])
  } catch (error) {
    statusMessage.textContent = error instanceof Error ? error.message : '段落操作无效；当前操作未应用'
    return
  }
  // Keep a repeated absolute value from manufacturing a history entry and a false undo step.
  if (JSON.stringify(proposal) === JSON.stringify(paragraphs)) return
  if (paragraphFormattingEdits.length >= 500) {
    statusMessage.textContent = '段落格式修改已达到 500 条；请先保存并打开新修订，再继续分批编辑。当前操作未应用。'
    return
  }
  paragraphFormattingEdits.push({ slideIndex: selectedSlide, elementId: element.id, ...patch })
  refreshCanvasPreview()
  markDirty()
}

function updateSelectedTextFormat(patch: Partial<Omit<TextFormatting, 'slideIndex' | 'elementId'>>) {
  const element = currentElement()
  if (selectedObjects.size>1 || !element?.editable || !element.text.trim()) return
  const key = editKey(selectedSlide, element.id)
  textFormattingEdits.set(key, {
    ...textFormattingEdits.get(key), slideIndex: selectedSlide, elementId: element.id, ...patch,
  })
  refreshCanvasPreview()
  markDirty()
}

function isWritableSlideSize(size: { cx: number; cy: number }) {
  return [size.cx, size.cy].every(value => Number.isInteger(value) && value >= MIN_SLIDE_EMU && value <= MAX_SLIDE_EMU)
}

let sizeDialog: ReturnType<typeof openSlidesSizeDialog> | undefined
let equationDialog: ReturnType<typeof openSlidesEquationDialog> | undefined
let nativeRibbon: NativeSlidesRibbon | undefined
function mountModelControls(){
 if(!native||modelControls)return
 const panel=root.querySelector<HTMLElement>('[data-ribbon-panel=model3dFormat]');if(!panel)return
 panel.replaceChildren();const host=document.createElement('div');panel.append(host)
 modelControls=mountModel3d(host,{canvas:()=>slideContent()??undefined,state:()=>{
  const tree=renderTree?.slides.find(item=>item.slideIndex===selectedSlide),source=tree?.modelSources?.find(item=>item.sourceId===selectedElement),node=tree?.nodes.find(item=>item.sourceId===selectedElement&&item.type==='picture')
  const original=new Set(deck.slides[selectedSlide]?.elements.filter(item=>item.model3d).map(item=>item.id)??[]),added=tree?.modelSources?.filter(item=>!original.has(item.sourceId))??[],index=added.findIndex(item=>item.sourceId===selectedElement)
  return {key:deck.sha256+'|'+selectedSlide+'|'+selectedElement+'|'+JSON.stringify(nativeDraft?.operations),available:!!nativeDraft&&!locked()&&!isNewSlide(selectedSlide)&&!pendingGroup(selectedSlide)&&slidesViewMode==='normal',slideIndex:selectedSlide,width:tree?.widthPx??deck.size.cx/9525,height:tree?.heightPx??deck.size.cy/9525,source,node:node?.type==='picture'?node:undefined,insertionKey:index>=0?modelInsertions.filter(item=>item.slideIndex===selectedSlide)[index]?.key:undefined,changes:slideChanges()}
 },commit:changes=>commitNativeChanges({...slideChanges(),...changes}),status:message=>{statusMessage.textContent=message}})
}
function mountInkControls(){
 if(!native||inkControls)return
 const panel=root.querySelector<HTMLElement>('[data-ribbon-panel=draw]');if(!panel)return
 panel.replaceChildren()
 const host=document.createElement('div');panel.append(host)
 inkControls=mountSlidesInk(host,{canvas:()=>slideContent()??undefined,state:()=>({slide:slideForView(selectedSlide),slideIndex:selectedSlide,changes:slideChanges(),key:deck.sha256+'|'+selectedSlide+'|'+JSON.stringify(nativeDraft?.operations),available:!!nativeDraft&&!locked()&&!isNewSlide(selectedSlide)&&!pendingGroup(selectedSlide)&&slidesViewMode==='normal'}),commit:changes=>commitNativeChanges({...slideChanges(),...changes}),status:message=>{statusMessage.textContent=message}})
}

if (native) nativeRibbon = createSlidesNativeRibbon(root, {
  onAssistant: sharedShell?.onAssistant ?? (sharedShell?.nativeAI ? () => nativeAIHost?.open() : undefined),
  onAction(command, value) {
    if (command === 'slideMaster') { void openMasterText(); return }
    if (['normalView', 'outlineView', 'slideSorter', 'readingView'].includes(command)) { void setSlidesViewMode(command === 'normalView' ? 'normal' : command === 'outlineView' ? 'outline' : command === 'readingView' ? 'reading' : 'sorter'); return }
    if(notesPane&&!notesPane.flush())return
    if(command==='print'){void openPrint();return}
    if(command==='notes'){notesPane?.setVisible(!notesVisible);syncNotesVisibility();return}
    if (command === 'grid') { gridVisible = !gridVisible; syncGrid(); return }
    if (command === 'ruler') { rulerVisible = !rulerVisible; ruler.setVisible(rulerVisible); syncGrid(); return }
    if (command === 'guides') { guidesVisible = !guidesVisible; guides.setVisible(guidesVisible); syncGrid(); return }
    if(command==='copy'||command==='cut'){copyObjects(command==='cut');return}
    if(command==='paste'){pasteObjects();return}
    if(command==='formatBrush'){startBrush(value==='continuous');return}
    if(command==='insertLink'){openLinkDialog();return}
    if (command === 'exportImages') { openExportImagesDialog(); return }
    if (command === 'startShow' || command === 'startShowCurrent') { stopBrush(); void startSlidesShow(command === 'startShowCurrent'); return }
    if (command === 'animationPreview') { stopBrush(); void startAnimationPreview(); return }
    if (command === 'groupObjects' || command === 'ungroupObjects') { changeGroup(command === 'ungroupObjects'); return }
    if (pendingGroup(selectedSlide) && !['saveRevision','movePrevious','moveNext','commentsPane','toggleAnimationPane','findReplace'].includes(command)) { statusMessage.textContent='请先保存或撤销本页组合操作，再修改页面内容'; return }
    if(elementOrderCommands[command]){reorderObjects(elementOrderCommands[command]!);return}
    if(arrangeCommands[command]){arrangeObjects(arrangeCommands[command]!);return}
    if(command==='cropPicture'){openPictureCrop();return}
    if ((tableStructureEdits.size && ['slideSize','customSlideSize','slideOrientation'].includes(command)) || (tableStructureEdits.has(selectedSlide) && ['layout','resetLayout'].includes(command))) {statusMessage.textContent='请先保存或撤销表格行列操作，再修改尺寸或版式';return}

    if (locked()) return
    // 新建页保存前只能移动/再新建；页面级与对象级修改需要来源身份，由引擎拒绝。
    if (isNewSlide(selectedSlide) && !['commentsPane', 'newComment', 'addSlide', 'addSlideWithLayout', 'movePrevious', 'moveNext', 'theme', 'slideSize', 'slideOrientation', 'customSlideSize', 'saveRevision'].includes(command)) { statusMessage.textContent = NEW_SLIDE_REASON; return }
    if (PARAGRAPH_LIST_COMMANDS.includes(command)) {
      const patch = paragraphCommandPatch(command, value)
      if (patch) updateSelectedParagraph(patch)
      renderInspector()
      return
    }
    switch (command) {
      case 'spelling': nativeAIHost?.openPreset({ kind: 'spelling' }); return
      case 'translate': nativeAIHost?.openPreset({ kind: 'translate', language: String(value ?? '') }); return
      case 'findReplace': openFindReplace(); return
      case 'slideZoom': void openZoom('slide'); return
      case 'sectionZoom': void openZoom('section'); return
      case 'insertAudio': void chooseNativeMedia('audio'); return
      case 'insertModel3d': mountModelControls();void modelControls?.insert();return
      case 'insertVideo': void chooseNativeMedia('video'); return
      case 'screenRecording': void toggleScreenRecording(); return
      case 'insertPicture': void chooseNativePicture(false); return
      case 'removeBackground': void openPictureCutout(); return
      case 'replacePicture': void chooseNativePicture(true); return
      case 'pictureOpacity': {
        // 固定源 onPictureOpacity：控件输入的是透明度百分比，写回不透明度（1 − 透明度）。
        const target = currentElement(), reason = opacityReason()
        if (!target || reason) { if (reason) statusMessage.textContent = reason; break }
        const transparency = Math.max(0, Math.min(100, Math.round(Number(value))))
        if (!Number.isFinite(transparency)) break
        const opacity = (100 - transparency) / 100
        const index = pictureOpacities.findIndex(item => item.slideIndex === selectedSlide && item.elementId === target.id)
        if (index >= 0) pictureOpacities.splice(index, 1)
        if (opacity === (target.pictureOpacity ?? 1)) { if (index < 0) break }
        else pictureOpacities.push({ slideIndex: selectedSlide, elementId: target.id, expectedSha256: target.pictureSha256!, expectedSize: target.pictureSize!, opacity })
        markDirty()
        break
      }
      case 'chartData': openNativeChart('data'); return
      case 'chartType': openNativeChart('type'); return
      case 'chartElements': openNativeChart('style'); return
      case 'chartDesignPresets': openNativeChart('design'); return
      case 'chartStylePreset': case 'chartColorScheme': applyNativeChartGallery(command,value); return
      case 'chartPointColors': openNativeChart('points'); return
      case 'chartSwitchRowCol': switchNativeChartRowsColumns(); return
      case 'commentsPane': commentsPaneOpen = !commentsPaneOpen; renderComments(); return
      case 'newComment': commentsPaneOpen = true; renderComments(); commentPane.openComposer(); return
      case 'hideSlide': {
        const original = deck.slides[selectedSlide]?.hidden ?? false
        const hidden = !(hiddenSlideEdits.get(selectedSlide) ?? original)
        if (hidden === original) hiddenSlideEdits.delete(selectedSlide)
        else hiddenSlideEdits.set(selectedSlide, hidden)
        renderSlides(); renderInspector(); markDirty(); break
      }
      case 'addSlide': addNewSlide(); break
      case 'headerFooter':
        openHeaderFooterDialog(); break
      case 'addSection':
        openSectionDialog(); break
      case 'changeShape': {
        const kind = String(value ?? ''), element = currentElement()
        if (!kind) break
        if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; break }
        if (!element || element.type !== 'shape' || deletions.has(editKey(selectedSlide, element.id))) { statusMessage.textContent = '更改形状仅适用于形状（不含文本框与线条）'; break }
        if (!SHAPE_PRESETS.includes(kind) || LINE_SHAPE_KINDS.includes(kind)) break
        shapeKindEdits.set(editKey(selectedSlide, element.id), { slideIndex: selectedSlide, elementId: element.id, kind })
        canvasStatus.textContent = '形状类型修改将在保存并打开新修订后显示在画布中。'
        renderStructurePending(); markDirty(); break
      }
      case 'tableStyle':
      case 'tableFirstRow':
      case 'tableBandRow':
      case 'tableRtl': {
        const target = currentElement(), reason = tablePresetReason(target)
        if (reason || !target) { if (reason) statusMessage.textContent = reason; break }
        const key = editKey(selectedSlide,target.id), previous = tableStyleEdits.get(key)
        let patch: TableStyleEdit
        if (command === 'tableStyle') {
          const preset = SLIDES_TABLE_PRESETS.find(item => item.name === value)
          if (!preset) break
          // Source presets replace flags/direct cell formatting but preserve RTL.
          patch = { slideIndex: selectedSlide, elementId: target.id, styleName: preset.name, ...(previous?.rtl === undefined ? {} : { rtl: previous.rtl }) }
        } else {
          if (typeof value !== 'boolean') break
          patch = { ...(previous ?? {slideIndex:selectedSlide,elementId:target.id}), [command === 'tableFirstRow' ? 'firstRow' : command === 'tableBandRow' ? 'bandRow' : 'rtl']: value }
        }
        if (JSON.stringify(patch) === JSON.stringify(previous)) break
        tableStyleEdits.set(key,patch); renderStructurePending(); markDirty(); refreshCanvasPreview(); break
      }
      case 'tableShadingWholeTable':
        if (!locked()) { tableShadingCell = undefined; updateTableShadingControls() }
        break
      case 'tableStructure': openTableStructure(); break
      case 'tableShading':
      case 'tableAllBorders':
      case 'tableNoBorders': {
        const target=currentElement()
        if (locked() || isNewSlide(selectedSlide) || target?.type !== 'table') break
        if (tableStructureEdits.get(selectedSlide)?.elementId===target.id) {statusMessage.textContent='请先保存或撤销此表的行列操作';break}
        const key=editKey(selectedSlide,target.id)
        if (!tableStyleEdits.has(key) && tableStyleEdits.size >= 500) { statusMessage.textContent='表格样式修改已达到 500 项，请先保存'; break }
        const patch=tableStyleEdits.get(key) ?? {slideIndex:selectedSlide,elementId:target.id}
        if (command === 'tableShading') {
          if (value !== 'none' && !TABLE_SHADING_COLORS.includes(String(value))) break
          const cell = shadingCellFor(target)
          if (cell) {
            if (target.tableCellShadingEditable !== true) { statusMessage.textContent = target.tableCellShadingReason || '此来源表格暂不支持安全单格底纹'; break }
            const previous = patch.cellShadings ?? [], existing = previous.some(item => item.row === cell.row && item.col === cell.col)
            if (!existing && [...tableStyleEdits.values()].reduce((total,item) => total + (item.cellShadings?.length ?? 0),0) >= 500) { statusMessage.textContent = '单格底纹已达到 500 项，请先保存'; break }
            patch.cellShadings = [...previous.filter(item => item.row !== cell.row || item.col !== cell.col), { row: cell.row, col: cell.col, shadingColor: String(value) }].sort((a,b) => a.row - b.row || a.col - b.col)
          } else {
            patch.shadingColor=String(value)
            delete patch.cellShadings
          }
        } else patch.borderPreset=command === 'tableAllBorders' ? 'all' : 'none'
        tableStyleEdits.set(key,patch); renderStructurePending(); markDirty(); refreshCanvasPreview(); break
      }
      case 'shapeFill':
      case 'shapeNoFill':
      case 'shapeOutline':
      case 'shapeOutlineWidth':
      case 'shapeNoOutline': {
        if(shapeFormatPane){shapeFormatPane.command(command,value);break}
        const element = currentElement()
        if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; break }
        if (!element || !['text', 'shape'].includes(element.type) || deletions.has(editKey(selectedSlide, element.id))) { statusMessage.textContent = '请先选择一个形状或文本框'; break }
        const key = editKey(selectedSlide, element.id)
        const style=shapeStyleForCommand(command,value,shapeStyleEdits.get(key)??{slideIndex:selectedSlide,elementId:element.id})
        if(!style)break
        shapeStyleEdits.set(key, style)
        canvasStatus.textContent = '形状填充与轮廓将在保存并打开新修订后显示在画布中。'
        renderStructurePending(); markDirty(); break
      }
      case 'insertSmartArt': {
        const preset = SMARTART_GALLERY.find(item => item.layout === String(value ?? ''))
        if (!preset) break
        if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; break }
        if (smartArtEdits.length >= 50) { statusMessage.textContent = '一次最多插入 50 个 SmartArt；请先保存'; break }
        smartArtEdits.push({ slideIndex: selectedSlide, layout: preset.layout, items: [...preset.defaultItems] })
        canvasStatus.textContent = '新增 SmartArt 将在保存并打开新修订后显示在画布中；可在待保存清单中改写节点文字。'
        renderStructurePending(); markDirty(); break
      }
      case 'insertChart': {
        const kind = String(value ?? '') as ChartGalleryKind
        if (!CHART_GALLERY.some(item => item.kind === kind)) break
        if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; break }
        if (chartEdits.length >= 50) { statusMessage.textContent = '一次最多插入 50 个图表；请先保存'; break }
        chartEdits.push({ slideIndex: selectedSlide, kind, ...chartSampleData(kind) })
        canvasStatus.textContent = '新增图表将在保存并打开新修订后显示在画布中，可再用 AI 改图替换数据。'
        renderStructurePending(); markDirty(); break
      }
      case 'insertEquation': {
        if (textBoxEdits.length >= 200) { statusMessage.textContent = '一次最多插入 200 个文本框；请先保存'; break }
        const sourceSlide = selectedSlide
        equationDialog?.dispose()
        equationDialog = openSlidesEquationDialog(root, text => {
          if (locked() || selectedSlide !== sourceSlide || isNewSlide(sourceSlide) || deletedSlides.has(sourceSlide)) return
          textBoxEdits.push({ ...equationTextBox(sourceSlide, deck.size, text), watermark: false })
          canvasStatus.textContent = '新增公式文本将在保存并打开新修订后显示在画布中。'
          renderStructurePending(); markDirty()
        })
        break
      }
      case 'insertWordArt': {
        // 固定源 insertWordArt + wordart-insert.ts：354.6×72.7pt 居中、54pt、不换行随文字调整。
        const preset = WORDART_PRESETS.find(item => item.id === String(value ?? ''))
        if (!preset) break
        if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; break }
        const w = Math.round(354.6 * 96 / 72), h = Math.round(72.7 * 96 / 72)
        textBoxEdits.push({ slideIndex: selectedSlide, text: '请在此放置您的文字', fontSize: 54, fontFamily: 'Microsoft YaHei', color: preset.fill.toUpperCase(), bold: !!preset.bold, ...(preset.italic ? { italic: true } : {}), ...(preset.outline ? { outline: { color: preset.outline.color.toUpperCase(), widthEmu: preset.outline.widthEmu } } : {}), wordArt: true, watermark: false,
          geometry: { x: Math.round((deck.size.cx / 9525 - w) / 2), y: Math.round((deck.size.cy / 9525 - h) / 2), width: w, height: h } })
        canvasStatus.textContent = '新增艺术字将在保存并打开新修订后显示在画布中。'
        renderStructurePending(); markDirty(); break
      }
      case 'dateTime':
      case 'slideNumber': {
        // 固定源 insertField：居中文本框内的动态字段（PowerPoint 打开时刷新），缓存值为当前页码/日期。
        if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; break }
        const isDate = command === 'dateTime', w = isDate ? 240 : 100, h = 44
        const slideWidth = deck.size.cx / 9525, slideHeight = deck.size.cy / 9525
        textBoxEdits.push({ slideIndex: selectedSlide, text: isDate ? new Date().toLocaleDateString('zh-CN') : String(order.indexOf(selectedSlide) + 1), field: isDate ? 'datetime1' : 'slidenum', fontSize: 18, fontFamily: 'Microsoft YaHei', color: '#000000', watermark: false,
          geometry: { x: Math.round((slideWidth - w) / 2), y: Math.round((slideHeight - h) / 2), width: w, height: h } })
        canvasStatus.textContent = '新增字段将在保存并打开新修订后显示在画布中。'
        renderStructurePending(); markDirty(); break
      }
      case 'insertTable':
        if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; break }
        openTableDialog(); break
      case 'insertShape': {
        const kind = String(value ?? '')
        if (!kind) break
        if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; break }
        if (!SHAPE_PRESETS.includes(kind) || shapeEdits.length >= 500) { statusMessage.textContent = '形状不可用或已达 500 个待插入形状'; break }
        const width = deck.size.cx / 9525, height = deck.size.cy / 9525
        const line = LINE_SHAPE_KINDS.includes(kind)
        shapeEdits.push({ slideIndex: selectedSlide, kind, geometry: { x: Math.round(width * 0.35), y: Math.round(height * (line ? 0.5 : 0.35)), width: Math.round(width * 0.3), height: line ? 1 : Math.round(height * 0.3) } })
        canvasStatus.textContent = '新增形状将在保存并打开新修订后显示在画布中。'
        renderStructurePending(); markDirty(); break
      }
      case 'resetLayout':
        if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; break }
        resetLayouts.add(selectedSlide); renderStructurePending()
        statusMessage.textContent = '已加入重置版式：保存时占位符恢复版式默认位置，同批其他修改叠加其上'
        markDirty(); break
      case 'addSlideWithLayout': addSlideWithLayout(String(value ?? '')); break
      case 'movePrevious': move(order.indexOf(selectedSlide), -1); break
      case 'moveNext': move(order.indexOf(selectedSlide), 1); break
      case 'theme':
        selectedTheme = value ? value as BusinessTheme : undefined
        markDirty()
        break
      case 'transition':
        if (transitionEditUnavailable()) { statusMessage.textContent = transitionEditUnavailable()!; break }
        if (SLIDE_TRANSITIONS.includes(value as SlideTransition) && order.includes(selectedSlide)) { transitionEdits.set(selectedSlide, value as SlideTransition); markDirty() }
        break
      case 'applyTransitionAll': {
        const effect = transitionEdits.get(selectedSlide) ?? deck?.slides[selectedSlide]?.transition ?? 'none'
        const unavailable = transitionApplyAllUnavailable()
        if (unavailable) { statusMessage.textContent = unavailable; break }
        if (applyTransitionToAll(order, effect, transitionEdits)) markDirty()
        break
      }
      case 'layout':
        if (typeof value === 'string' && value) { layoutEdits.set(selectedSlide, value); markDirty() }
        break
      case 'customSlideSize':
        sizeDialog?.dispose()
        sizeDialog = openSlidesSizeDialog(root, slideSizeEdit ?? deck.size, size => {
          if (locked() || tableStructureEdits.size) return
          slideSizeEdit = size
          renderInspector()
          canvasStatus.textContent = '页面尺寸将在保存并打开新修订后更新；页面内容会按宽高比例缩放。'
          markDirty()
        })
        break
      case 'slideSize':
        if (typeof value !== 'string' || !Object.hasOwn(SLIDE_SIZE_PRESETS, value)) return
        slideSizeEdit = presetSize(value as SlideSizePreset, isPortrait(slideSizeEdit ?? deck.size))
        canvasStatus.textContent = '页面尺寸将在保存并打开新修订后更新；页面内容会按宽高比例缩放。'
        markDirty()
        break
      case 'slideOrientation': {
        const size = slideSizeEdit ?? deck.size
        if (!['landscape', 'portrait'].includes(String(value)) || !isWritableSlideSize(size)) return
        if (isPortrait(size) === (value === 'portrait')) return
        slideSizeEdit = { cx: size.cy, cy: size.cx }
        canvasStatus.textContent = '页面方向将在保存并打开新修订后更新；页面内容会按宽高比例缩放。'
        markDirty()
        break
      }
      case 'backgroundImage': openBackgroundImageDialog('image'); return
      case 'customShows': openCustomShowDialog(); return
      case 'formatBackground': if(backgroundPane){const slide=backgroundPaneSlide();if(slide)backgroundPane.open(slide,backgroundPaneKey())}else openBackgroundImageDialog('gradient'); return
      case 'background':
        if (typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)) {
          backgroundEdits.set(selectedSlide, value.toUpperCase()); dropBackgroundImages([selectedSlide]); renderStructurePending(); markDirty()
        }
        break
      case 'bold':
        updateSelectedTextFormat({ bold: value === true })
        break
      case 'italic':
        updateSelectedTextFormat({ italic: value === true })
        break
      case 'underline':
        updateSelectedTextFormat({ underline: value === true })
        break
      case 'strike':
        updateSelectedTextFormat({ strike: value === true })
        break
      case 'fontSize': {
        const fontSizePt = Number(value)
        if (Number.isFinite(fontSizePt) && fontSizePt >= 1 && fontSizePt <= 400) updateSelectedTextFormat({ fontSizePt })
        break
      }
      case 'fontSizeUp':
      case 'fontSizeDown': {
        const element = currentElement()
        const current = element ? textFormattingEdits.get(editKey(selectedSlide, element.id))?.fontSizePt ?? element.textStyle?.fontSizePt : null
        updateSelectedTextFormat({ fontSizePt: stepNativeFontSize(current, command === 'fontSizeUp' ? 1 : -1) })
        break
      }
      case 'fontFamily': {
        const fontFamily = String(value ?? '').trim()
        if (fontFamily && fontFamily.length <= 200 && !/[\x00-\x1f]/.test(fontFamily)) updateSelectedTextFormat({ fontFamily })
        break
      }
      case 'fontColor':
        if (typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)) updateSelectedTextFormat({ color: value.toUpperCase() })
        break
      case 'paragraphAlignLeft':
      case 'paragraphAlignCenter':
      case 'paragraphAlignRight':
      case 'paragraphAlignJustify': {
        const element = currentElement()
        if (!element?.editable || !element.text.trim()) break
        const align = command.replace('paragraphAlign', '').toLowerCase() as ParagraphFormatting['align']
        updateSelectedParagraph({ align })
        break
      }
      case 'lineSpacingPct':
      case 'spaceBeforePt':
      case 'spaceAfterPt': {
        const element = currentElement()
        if (!element?.editable || !element.text.trim() || typeof value !== 'string' || !value.trim()) break
        const normalized = value.trim().replace(',', '.')
        if (!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(normalized)) break
        const number = Number(normalized)
        if (!Number.isFinite(number) || (command === 'lineSpacingPct' ? ![100, 115, 150, 200, 250, 300].includes(number) : number < 0 || number > 500)) break
        updateSelectedParagraph({ [command]: command === 'lineSpacingPct' ? number : Math.round(number * 100) / 100 })
        break
      }
      case 'addText': addTextBox(false); break
      case 'addWatermark': addTextBox(true); break
      case 'deleteObject': objectDelete.click(); break
      case 'saveRevision': saveButton.click(); return
      case 'shapeGeometry': if(geometryPane)geometryPane.focus();else{currentGeometryInputs()[0]?.focus();root.querySelector('.geometry-heading')?.scrollIntoView({ block: 'nearest' })} return
      case 'animationEffect': animationEffect.value = String(value); if(animationEffect.value.startsWith('media')){animationDurationMs=0;animationDuration.value='0';nativeRibbon?.setValue('animationDuration','0')} nativeRibbon?.setValue(command, String(value)); return
      case 'animationDirection': animationDirection = value as AnimationDirection; return
      // 固定源 onAnimTiming：计时控件绑定到窗格选中的动画；未选中时作为下一条新增动画的计时。
      case 'animationTrigger':
        animationTrigger.value = String(value) as AnimationTrigger
        if (selectedAnimationRow >= 0) { updateSequence(items => patchSequenceTiming(items, sourceAnimations(), selectedAnimationRow, { trigger: animationTrigger.value as AnimationTrigger })); break }
        return
      case 'animationDuration':
        animationDurationMs = Math.max(selectedAnimationRow >= 0 ? 0 : 1, Math.min(120000, Math.round(Number(value)) || (selectedAnimationRow >= 0 ? 0 : 500)))
        animationDuration.value = String(animationDurationMs)
        if (selectedAnimationRow >= 0) { updateSequence(items => patchSequenceTiming(items, sourceAnimations(), selectedAnimationRow, { durationMs: animationDurationMs })); break }
        return
      case 'animationDelay':
        animationDelayMs = Math.max(0, Math.min(120000, Math.round(Number(value)) || 0))
        animationDelay.value = String(animationDelayMs)
        if (selectedAnimationRow >= 0) { updateSequence(items => patchSequenceTiming(items, sourceAnimations(), selectedAnimationRow, { delayMs: animationDelayMs })); break }
        return
      case 'toggleAnimationPane': animationPaneOpen = !animationPaneOpen; if (!animationPaneOpen) selectedAnimationRow = -1; break
      case 'animationByParagraph': animationByParagraph = !animationByParagraph; break
      case 'animationNone': {
        // 固定源 applyAnimation('none')：移除所选对象的全部动画。
        const target = currentElement()
        if (!(target?.editable||target?.mediaKind) || animationUnavailable()) break
        const before = currentSequence().length
        for (let index = animationEdits.length - 1; index >= 0; index--) if (animationEdits[index]!.slideIndex === selectedSlide && animationEdits[index]!.elementId === target.id) animationEdits.splice(index, 1)
        updateSequence(items => removeElementAnimations(items, sourceAnimations(), target.id))
        if (before === currentSequence().length) statusMessage.textContent = '所选对象没有动画'
        break
      }
      case 'motionPathRight': case 'motionPathDown': case 'motionPathDiagonal': case 'motionPathCircle': case 'motionPathZigzag': {
        const target = currentElement()
        if (!target?.editable || animationUnavailable()) break
        updateSequence(items => appendAnimation(items, motionPathAnimation(target.id, command)))
        break
      }
      case 'addAnimation':
        if (animationUnavailable() || !(currentElement()?.editable||currentElement()?.mediaKind)) break
        if(animationEffect.value.startsWith('media')!==!!currentElement()?.mediaKind){statusMessage.textContent='媒体动作需要选择音频或视频，形状动画需要选择文字或形状';break}
        if (animationSequences.has(selectedSlide) || animationByParagraph) {
          if (animationUnavailable()) break
          const target = currentElement()!
          updateSequence(items => appendAnimation(items, { elementId: target.id, effect: animationEffect.value as AnimationEffect, trigger: animationTrigger.value as AnimationTrigger,
            durationMs: animationEffect.value.startsWith('media')?0:selectedAnimationRow >= 0 ? defaultAnimationDuration(animationEffect.value) : animationDurationMs, delayMs: selectedAnimationRow >= 0 ? 0 : animationDelayMs,
            ...(['flyIn', 'flyOut', 'wipe', 'wipeOut'].includes(animationEffect.value) ? { direction: animationDirection } : {}) }, animationByParagraph ? paragraphCount(target) : 0))
          break
        }
        animationEdits.push({ slideIndex: selectedSlide, elementId: selectedElement,
          effect: animationEffect.value as AnimationEffect, trigger: animationTrigger.value as AnimationTrigger,
          durationMs: animationEffect.value.startsWith('media')?0:animationDurationMs, delayMs: animationDelayMs, append: true,
          ...( ['flyIn', 'flyOut', 'wipe', 'wipeOut'].includes(animationEffect.value) ? { direction: animationDirection } : {}),
        })
        renderInspector(); markDirty()
        break
      default: break
    }
    renderInspector()
  },
})

if (native) {
  syncSlidesViewMode()
  const history = document.createElement('div')
  history.className = 'slides-native-ribbon-group'
  history.setAttribute('aria-label', '编辑历史')
  nativeUndo = buttonIcon(Undo2, '撤销')
  nativeRedo = buttonIcon(Redo2, '重做')
  nativeUndo.dataset.sourceAction = 'onUndo'
  nativeRedo.dataset.sourceAction = 'onRedo'
  for (const [button, direction] of [[nativeUndo, 'undo'], [nativeRedo, 'redo']] as const) {
    button.title = direction === 'undo' ? '撤销本次页面中的修改；刷新后仅恢复草稿内容，不恢复历史' : '重做本次页面中撤销的修改'
    button.addEventListener('mousedown', event => event.preventDefault())
    button.addEventListener('click', () => {
      if (locked() || !nativeDraft) return
      if(notesPane&&!notesPane.flush())return
      stopBrush()
      customShowDialog?.dispose();customShowDialog=undefined
      nativeDraft[direction]()
      restoreNativeDraft()
      renderSlides(); renderInspector(); refreshCanvasPreview()
      stateLabel.textContent = dirty ? '有未保存修改' : '可编辑'
      statusMessage.textContent = nativeDraft.persistenceError ?? (dirty ? '修改尚未保存' : '已恢复原始幻灯片')
    })
    history.append(button)
  }
  root.querySelector('.slides-native-ribbon')!.prepend(history)
  updateNativeHistory()
}

const guardPendingGroup = (event: Event) => {
  if (!deck || !pendingGroup(selectedSlide) || !(event.target instanceof Element)) return
  const target=event.target
  if (!target.closest('.slides-inspector') || target.closest('#object-select,.slides-arrange-selection,.structure-pending')) return
  event.preventDefault(); event.stopImmediatePropagation()
  statusMessage.textContent='请先保存或撤销本页组合操作，再编辑内容'
}
for (const type of ['input','change','click']) root.addEventListener(type,guardPendingGroup,true)
select.addEventListener('change', () => { if(brushMode&&select.value){applyBrush(select.value);return} selectObjects(select.value); renderInspector() })
textArea.addEventListener('input', () => {
  const element = currentElement()
  if (selectedObjects.size>1 || !element) return
  const edit = edits.get(editKey(selectedSlide, element.id)) ?? { slideIndex: selectedSlide, elementId: element.id }
  edit.text = textArea.value
  edits.set(editKey(selectedSlide, element.id), edit)
  // Text and its paragraph targets form one history snapshot. Drop only targets
  // whose paragraphs were removed, so reload never traps an invalid draft.
  const source = sourceAnimations(), before = currentSequence()
  const count = edit.text.split(/\r?\n/).length
  const after = before.filter(item => {
    const resolved = resolvedItem(item, source)
    return resolved.elementId !== element.id || resolved.paragraph === undefined || resolved.paragraph < count
  })
  if (after.length !== before.length) {
    for (let index=animationEdits.length-1; index>=0; index--) if (animationEdits[index]!.slideIndex === selectedSlide) animationEdits.splice(index,1)
    if (sequenceUnchanged(after, source)) animationSequences.delete(selectedSlide)
    else animationSequences.set(selectedSlide, after)
  }
  refreshCanvasPreview()
  undoSnapshot = undefined
  undoButton.disabled = true
  markDirty(); renderAnimationPane()
  if (after.length !== before.length) statusMessage.textContent = `已移除 ${before.length-after.length} 条超出新段落范围的动画；可撤销恢复`
})
for (const input of native?[]:currentGeometryInputs()) input.addEventListener('change', () => {
  const element = currentElement()
  if (!element || selectedObjects.size>1) return
  const edit = edits.get(editKey(selectedSlide, element.id)) ?? { slideIndex: selectedSlide, elementId: element.id }
  refreshCanvasPreview()
  edit.geometry = Object.fromEntries(currentGeometryInputs().map(field => [field.name, Number(field.value)])) as Edit['geometry']
  edits.set(editKey(selectedSlide, element.id), edit)
  undoSnapshot = undefined
  undoButton.disabled = true
  markDirty()
})
themeSelect.addEventListener('change', () => {
  selectedTheme = themeSelect.value ? themeSelect.value as BusinessTheme : undefined
  canvasStatus.textContent = '主题修改将在保存并打开新修订后更新画布。'
  undoSnapshot = undefined
  undoButton.disabled = true
  markDirty()
})
transitionSelect.addEventListener('change', () => {
  if (locked() || transitionEditUnavailable()) { statusMessage.textContent = transitionEditUnavailable() ?? '当前不可编辑'; return }
  transitionEdits.set(selectedSlide, transitionSelect.value as SlideTransition)
  markDirty()
})
layoutSelect.addEventListener('change', () => {
  if(tableStructureEdits.has(selectedSlide)){renderInspector();statusMessage.textContent='请先保存或撤销表格行列操作';return}
  if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; renderInspector(); return }
  if (!layoutSelect.value) return
  layoutEdits.set(selectedSlide, layoutSelect.value)
  nativeRibbon?.setValue('layout', layoutSelect.value)
  canvasStatus.textContent = '版式修改将在保存并打开新修订后更新画布。'
  markDirty()
})
animationAdd.addEventListener('click', () => {
  if (animationUnavailable() || !(currentElement()?.editable||currentElement()?.mediaKind)) return
  if(animationEffect.value.startsWith('media')!==!!currentElement()?.mediaKind){statusMessage.textContent='请为所选对象选择对应的媒体或形状动画';return}
  if (animationSequences.has(selectedSlide)) {
    const target = currentElement()!
    updateSequence(items => appendAnimation(items, { elementId: target.id, effect: animationEffect.value as AnimationEffect, trigger: animationTrigger.value as AnimationTrigger, durationMs: animationEffect.value.startsWith('media')?0:Math.max(0, Math.round(Number(animationDuration.value)) || 500), delayMs: Math.max(0, Math.round(Number(animationDelay.value)) || 0) }))
    renderInspector()
    return
  }
  animationEdits.push({
    slideIndex: selectedSlide,
    elementId: selectedElement,
    effect: animationEffect.value as AnimationEffect,
    trigger: animationTrigger.value as AnimationTrigger,
    durationMs: animationEffect.value.startsWith('media')?0:Math.max(1, Number(animationDuration.value) || 500),
    delayMs: Math.max(0, Number(animationDelay.value) || 0),
  })
  renderInspector()
  markDirty()
})
function structureDimensions(element: DeckElement | undefined): { rows: number; cols: number } | null {
  const cells = element?.tableCells
  const rows = cells?.length ?? 0, cols = cells?.[0]?.length ?? 0
  return element?.type === 'table' && element.tableStructureEditable === true && Array.isArray(cells) && rows >= 1 && rows <= 75 && cols >= 1 && cols <= 75 && cells!.every(row => Array.isArray(row) && row.length === cols && row.every(cell => typeof cell === 'string')) ? { rows, cols } : null
}
function closeStructureDialog() {
  ++structureDialogGeneration
  const dialog = structureDialog
  structureDialog = undefined
  if (dialog?.open) dialog.close()
  dialog?.remove()
}
function tableStructureReason(element=currentElement()): string | null {
  if (locked() || isNewSlide(selectedSlide) || element?.type!=='table') return '请先选择来源表格'
  if (!structureDimensions(element)) return '含合并单元格、特殊尺寸、扩展标记或超出 75 行列的表格暂不支持结构调整'
  if (tableStructureEdits.has(selectedSlide)) return '本页已有行列操作，请先保存重开或撤销'
  if (tableStructureEdits.size >= 100) return '每批最多调整 100 页表格，请先保存重开'
  if (slideSizeEdit || resetLayouts.has(selectedSlide) || layoutEdits.has(selectedSlide)) return '请先保存页面尺寸或版式调整，再修改行列'
  if (tableStyleEdits.has(editKey(selectedSlide,element.id)) || [...tableCellEdits.values()].some(v=>v.slideIndex===selectedSlide&&v.elementId===element.id)) return '请先保存或撤销此表的文字、底纹和边框修改'
  return null
}
function openTableStructure() {
  const reason=tableStructureReason(),target=currentElement()
  if (reason || !target?.tableCells) {statusMessage.textContent=reason??'请选择表格';return}
  closeStructureDialog()
  const slideIndex=selectedSlide,snapshot=JSON.stringify(slideChanges()),cells=target.tableCells,generation=structureDialogGeneration
  const sourceSha=deck.sha256,draftSnapshot=JSON.stringify(nativeDraft?.operations)
  const dialog=document.createElement('dialog');structureDialog=dialog;dialog.className='slides-table-dialog slides-table-structure-dialog';dialog.setAttribute('aria-label','调整表格行列')
  const title=document.createElement('h3');title.textContent='调整表格行列'
  const hint=document.createElement('p');hint.textContent='按来源行列操作，新增行列继承参考行列的单元格格式并留空；表格尺寸相应变化。每页每批一次，保存重开后显示新结构。'
  hint.id='slides-table-structure-hint';dialog.setAttribute('aria-describedby',hint.id)
  const rowSelect=document.createElement('select'),colSelect=document.createElement('select')
  rowSelect.setAttribute('aria-label','参考行');colSelect.setAttribute('aria-label','参考列')
  cells.forEach((_,i)=>rowSelect.add(new Option(`第 ${i+1} 行`,String(i))))
  cells[0]!.forEach((_,i)=>colSelect.add(new Option(`第 ${i+1} 列`,String(i))))
  const error=document.createElement('p');error.setAttribute('role','alert')
  const groups=[rowSelect,colSelect].map((select,i)=>{
    const group=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent=i===0?'行':'列'
    const label=document.createElement('label');label.append(i===0?'参考行':'参考列',select)
    const actions=document.createElement('div');actions.className='slides-structure-actions'
    group.append(legend,label,actions);return {group,actions}
  })
  dialog.append(title,hint,...groups.map(item=>item.group),error)
  for(const [kind,before,label] of [['insert-row',true,'在上方插入行'],['insert-row',false,'在下方插入行'],['delete-row',undefined,'删除行'],['insert-col',true,'在左侧插入列'],['insert-col',false,'在右侧插入列'],['delete-col',undefined,'删除列']] as const) {
    const button=document.createElement('button');button.type='button';button.textContent=label
    const count=kind.endsWith('row')?cells.length:cells[0]!.length
    button.disabled=kind.startsWith('delete-')?count<=1:count>=75
    button.addEventListener('click',()=>{try{
      if (disposed || !dialog.open || !dialog.isConnected || structureDialog!==dialog || generation!==structureDialogGeneration || deck.sha256!==sourceSha || JSON.stringify(nativeDraft?.operations)!==draftSnapshot || selectedSlide!==slideIndex || currentElement()?.id!==target.id || JSON.stringify(slideChanges())!==snapshot || tableStructureReason()) throw new Error('草稿或选择已变化，请重新打开行列操作')
      const value=kind.endsWith('row')?rowSelect.value:colSelect.value
      const index=Number(value)
      if (!/^\d+$/.test(value) || !Number.isInteger(index) || index<0 || index>=count || (kind.startsWith('delete-')?count<=1:count>=75)) throw new Error('参考行列无效，请重新选择')
      tableStructureEdits.set(slideIndex,{slideIndex,elementId:target.id,kind,index,...(before!==undefined?{before}:{})})
      closeStructureDialog();undoSnapshot=undefined;undoButton.disabled=true;renderInspector();renderStructurePending();markDirty();canvasStatus.textContent='行列修改已暂存；保存并打开新修订后显示新结构'
    }catch(e){error.textContent=e instanceof Error?e.message:'操作失败'}})
    if(kind.startsWith('delete-'))button.className='slides-structure-delete'
    groups[kind.endsWith('row')?0:1]!.actions.append(button)
  }
  const actions=document.createElement('div');actions.className='slides-table-actions'
  const cancel=document.createElement('button');cancel.type='button';cancel.textContent='取消';cancel.addEventListener('click',closeStructureDialog);actions.append(cancel);dialog.append(actions)
  dialog.addEventListener('close',()=>{if(structureDialog===dialog){structureDialog=undefined;++structureDialogGeneration};dialog.remove()},{once:true});root.append(dialog);showSlidesSettingsDialog(dialog)
}
function renderTableCellEditor(element: DeckElement | undefined) {
  const generation = ++tableCellEditorGeneration, sourceSlide = selectedSlide, sourceSha = deck.sha256
  tableCellEditor.replaceChildren()
  const cells = selectedObjects.size<=1 && element?.type === 'table' && !isNewSlide(selectedSlide) ? element.tableCells : undefined
  tableCellEditor.hidden = !cells
  if (!cells || !element) return
  const grid = document.createElement('div'); grid.className = 'table-cell-grid'
  grid.style.gridTemplateColumns = `repeat(${Math.max(1, ...cells.map(row => row.length))}, minmax(60px, 1fr))`
  for (const [rowIndex, rowCells] of cells.entries()) for (const [colIndex, original] of rowCells.entries()) {
    const input = document.createElement('textarea')
    const key = `${selectedSlide}:${element.id}:${rowIndex}:${colIndex}`
    input.setAttribute('aria-label', `表格单元格 ${rowIndex + 1} 行 ${colIndex + 1} 列`)
    input.dataset.tableCell = `${rowIndex}:${colIndex}`
    input.value = original === null ? '' : tableCellEdits.get(key)?.text ?? original
    input.disabled = original === null || locked() || isNewSlide(selectedSlide) || tableStructureEdits.get(selectedSlide)?.elementId===element.id || deletions.has(editKey(selectedSlide, element.id))
    if (original === null) input.title = '合并单元格不可单独编辑'
    input.maxLength = 10000
    const current = () => generation === tableCellEditorGeneration && input.isConnected && sourceSha === deck.sha256 && sourceSlide === selectedSlide && currentElement()?.id === element.id && !locked() && !input.disabled
    input.addEventListener('focus', () => {
      if (!current() || original === null) return
      tableShadingCell = { slideIndex: sourceSlide, elementId: element.id, row: rowIndex, col: colIndex }
      updateTableShadingControls(element)
    })
    input.addEventListener('change', () => {
      if(!current() || isNewSlide(selectedSlide) || tableStructureEdits.get(selectedSlide)?.elementId===element.id){input.value=tableCellEdits.get(key)?.text??original??'';return}
      if (input.value.length > 10000 || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(input.value) || (!tableCellEdits.has(key) && tableCellEdits.size >= 500 && input.value !== original)) {
        input.value = tableCellEdits.get(key)?.text ?? original ?? ''; statusMessage.textContent = '每次最多编辑 500 个单元格，每格最多 10000 字符，文字不能包含控制字符'; return
      }
      if (input.value === original) tableCellEdits.delete(key)
      else if (input.value.length <= 10000) tableCellEdits.set(key, { slideIndex: selectedSlide, elementId: element.id, row: rowIndex, col: colIndex, text: input.value })
      renderStructurePending(); markDirty(); refreshCanvasPreview()
    })
    grid.append(input)
  }
  const label = document.createElement('div'); label.className = 'field-label'; label.textContent = '表格单元格'
  const targetLabel = document.createElement('p'); targetLabel.dataset.tableShadingTarget = ''; targetLabel.setAttribute('aria-label','底纹目标')
  tableCellEditor.append(label, targetLabel, grid)
  updateTableShadingControls(element)
}
function renderStructurePending() {
  structurePending.replaceChildren()
  const row = (label: string, onRemove: () => void, extra?: HTMLElement) => {
    const item = document.createElement('li')
    item.append(document.createTextNode(label))
    if (extra) item.append(extra)
    const remove = buttonIcon(X, '撤销此项修改')
    remove.addEventListener('click', () => { if (notesPane && !notesPane.flush()) return; onRemove(); renderStructurePending(); renderInspector(); markDirty() })
    item.append(remove)
    structurePending.append(item)
  }
  for(const [slideIndex] of notesEdits)row('第 '+(order.indexOf(slideIndex)+1)+' 页 · 演讲者备注',()=>notesEdits.delete(slideIndex))
  for(const [index,item] of linkEdits.entries())row('第 '+(order.indexOf(item.slideIndex)+1)+' 页 · 对象超链接'+(item.target===null?'移除':''),()=>linkEdits.splice(index,1))
  for(const [index,item] of clipboardPastes.entries())row('第 '+(order.indexOf(item.slideIndex)+1)+' 页 · 粘贴 '+item.elementIds.length+' 个对象（保存后生效）',()=>clipboardPastes.splice(index,1))
  for (const [index, item] of groupEdits.entries()) row('第 ' + (order.indexOf(item.slideIndex)+1) + ' 页 · ' + (item.kind === 'group' ? '组合对象' : '取消组合') + '（保存后生效）', () => groupEdits.splice(index,1))
  for (const [index, smartArt] of smartArtEdits.entries()) {
    const items = document.createElement('textarea')
    items.className = 'smartart-items'; items.rows = Math.min(SMARTART_MAX_ITEMS, smartArt.items.length + 1)
    items.setAttribute('aria-label', 'SmartArt 节点文字（每行一个）'); items.value = smartArt.items.join('\n')
    items.addEventListener('change', () => {
      const next = items.value.split(/\r?\n/).map(text => text.trim()).filter(Boolean).slice(0, SMARTART_MAX_ITEMS)
      if (!next.length) { items.value = smartArt.items.join('\n'); statusMessage.textContent = 'SmartArt 至少需要 1 个节点'; return }
      smartArt.items = next.map(text => text.slice(0, 200)); items.value = smartArt.items.join('\n'); markDirty()
    })
    row(`第 ${order.indexOf(smartArt.slideIndex) + 1} 页 · SmartArt ${SMARTART_GALLERY.find(item => item.layout === smartArt.layout)?.label ?? smartArt.layout}`, () => smartArtEdits.splice(index, 1), items)
  }
  for(const [index,media] of mediaInsertions.entries())row(`第 ${order.indexOf(media.slideIndex)+1} 页 · ${media.kind==='video'?'视频':'音频'} ${media.name??''}`,()=>{mediaInsertions.splice(index,1);refreshCanvasPreview()})
  for(const [index,image] of nativeImages.entries()) row(`第 ${order.indexOf(image.slideIndex)+1} 页 · 图片 ${image.descr??''}`,()=>nativeImages.splice(index,1))
  for(const [slideIndex] of elementOrders)row(`第 ${order.indexOf(slideIndex)+1} 页 · 对象层级`,()=>elementOrders.delete(slideIndex))
  for(const [index,crop] of pictureCrops.entries())row(`第 ${order.indexOf(crop.slideIndex)+1} 页 · 图片裁切`,()=>pictureCrops.splice(index,1))
  for (const [index, item] of pictureOpacities.entries()) row(`第 ${order.indexOf(item.slideIndex) + 1} 页 · 图片透明度 ${Math.round((1 - item.opacity) * 100)}%`, () => pictureOpacities.splice(index, 1))
  for(const [index,image] of pictureReplacements.entries()) row(`第 ${order.indexOf(image.slideIndex)+1} 页 · 替换图片`,()=>pictureReplacements.splice(index,1))
  for(const [index,chart] of nativeChartEdits.entries()) row(`第 ${order.indexOf(chart.slideIndex)+1} 页 · 图表数据/类型/元素修改`,()=>nativeChartEdits.splice(index,1))
  for (const [index, chart] of chartEdits.entries()) row(`第 ${order.indexOf(chart.slideIndex) + 1} 页 · 图表 ${CHART_GALLERY.find(item => item.kind === chart.kind)?.label ?? chart.kind}（示例数据）`, () => chartEdits.splice(index, 1))
  for(const [slideIndex,item] of tableStructureEdits) row(`第 ${order.indexOf(slideIndex)+1} 页 · 表格${item.kind.startsWith('insert-')?'插入':'删除'}${item.kind.endsWith('row')?'行':'列'}（参考 ${item.index+1}）`,()=>tableStructureEdits.delete(slideIndex))
  for (const [key, style] of tableStyleEdits) row(`第 ${order.indexOf(style.slideIndex)+1} 页 · 表格${style.styleName ? `样式 ${SLIDES_TABLE_PRESETS.find(item => item.name === style.styleName)?.label ?? style.styleName}` : '选项/底纹/边框'}${style.cellShadings?.length ? ` · ${style.cellShadings.length} 格底纹` : ''}`, () => { tableStyleEdits.delete(key); refreshCanvasPreview() })
  for (const [key, cell] of tableCellEdits) row(`第 ${order.indexOf(cell.slideIndex) + 1} 页 · 表格单元格（${cell.row + 1}行${cell.col + 1}列）「${cell.text.slice(0, 20)}」`, () => tableCellEdits.delete(key))
  if (headerFooterEdit) row(`全部页面 · 页眉页脚：${[headerFooterEdit.date ? `日期 ${headerFooterEdit.dateAuto ? '（自动更新）' : headerFooterEdit.date}` : '', headerFooterEdit.slideNum ? '幻灯片编号' : '', headerFooterEdit.footer ? `页脚「${headerFooterEdit.footer}」` : ''].filter(Boolean).join('、') || '全部关闭'}`, () => { headerFooterEdit = undefined })
  for (const [index, section] of sectionEdits.entries()) row(`第 ${order.indexOf(section.slideIndex) + 1} 页前 · 新增节「${section.name}」`, () => { sectionEdits.splice(index, 1); renderSlides() })
  for (const [key, item] of shapeKindEdits) {
    const name = deck.slides[item.slideIndex]?.elements.find(element => element.id === item.elementId)?.name || item.elementId
    row(`第 ${order.indexOf(item.slideIndex) + 1} 页 · ${name} · 更改为${SHAPE_GALLERY_GROUPS.flatMap(group => group.shapes).find(shape => shape.prst === item.kind)?.label ?? item.kind}`, () => shapeKindEdits.delete(key))
  }
  for (const [key, style] of shapeStyleEdits) {
    const name = deck.slides[style.slideIndex]?.elements.find(element => element.id === style.elementId)?.name || style.elementId
    const parts = [style.fill === 'none' ? '无填充' : style.fill ? `填充 ${style.fill}` : '', style.stroke === null ? '无轮廓' : style.stroke ? `轮廓 ${style.stroke.color} ${style.stroke.widthPt} 磅` : ''].filter(Boolean)
    row(`第 ${order.indexOf(style.slideIndex) + 1} 页 · ${name} · ${parts.join('、')}`, () => shapeStyleEdits.delete(key))
  }
  for (const [index, table] of tableEdits.entries()) row(`第 ${order.indexOf(table.slideIndex) + 1} 页 · 表格 ${table.rows}×${table.cols}`, () => tableEdits.splice(index, 1))
  for (const [index, edit] of masterTextEdits.entries()) row(`母版/版式 ${deck.masterTextParts?.find(part => part.partPath === edit.partPath)?.name ?? edit.partPath} · 文字 ${edit.spid}`, () => masterTextEdits.splice(index, 1))
  for (const [index, edit] of masterElementEdits.entries()) row(`母版/版式 ${deck.masterTextParts?.find(part => part.partPath === edit.partPath)?.name ?? edit.partPath} · ${edit.kind === 'delete' ? `删除文字 ${edit.spid}` : edit.kind === 'setFill' ? `对象 ${edit.spid} · 填充 ${edit.fill === 'none' ? '无填充' : edit.fill}` : edit.kind === 'setStroke' ? `对象 ${edit.spid} · 轮廓 ${edit.stroke?.color ?? '无'}` : edit.kind === 'setTransform' ? `对象 ${edit.spid} · 位置/旋转` : `新增文字框 ${(edit.kind === "addTextBox" ? edit.text : "").slice(0, 20)}`}`, () => masterElementEdits.splice(index, 1))
  for (const [index, shape] of shapeEdits.entries()) row(`第 ${order.indexOf(shape.slideIndex) + 1} 页 · 形状 ${SHAPE_GALLERY_GROUPS.flatMap(group => group.shapes).find(item => item.prst === shape.kind)?.label ?? shape.kind}`, () => shapeEdits.splice(index, 1))
  for (const slideIndex of resetLayouts) row(`第 ${order.indexOf(slideIndex) + 1} 页 · 重置版式`, () => resetLayouts.delete(slideIndex))
  for (const [slideIndex, color] of backgroundEdits) {
    row(`第 ${order.indexOf(slideIndex) + 1} 页 · 背景 ${color}`, () => backgroundEdits.delete(slideIndex))
  }
  for (const [index, item] of backgroundImageEdits.entries()) {
    const pages = item.slideIndices.length === deck.slides.length ? '全部页面' : item.slideIndices.map(slideIndex => `第 ${order.indexOf(slideIndex) + 1} 页`).join('、')
    row(`${pages} · 背景图片（${item.tile ? '平铺' : '拉伸'}）`, () => backgroundImageEdits.splice(index, 1))
  }
  for(const [index,item] of backgroundImageReuseEdits.entries())row(`${item.slideIndices.map(i=>i+1).join('、')} · 复用背景图片（${item.tile?'平铺':'拉伸'}）`,()=>backgroundImageReuseEdits.splice(index,1))
  for (const [index, item] of backgroundGradientEdits.entries()) {
    const pages = item.slideIndices.length === deck.slides.length ? '全部页面' : item.slideIndices.map(slideIndex => `第 ${order.indexOf(slideIndex) + 1} 页`).join('、')
    row(`${pages} · 渐变背景 ${item.from}→${item.to}（${item.radial ? '径向' : `${item.angleDeg}°`}）`, () => backgroundGradientEdits.splice(index, 1))
  }
  for (const slideIndex of backgroundResetEdits) row(`第 ${order.indexOf(slideIndex) + 1} 页 · 重置背景`, () => backgroundResetEdits.delete(slideIndex))
  for (const [slideIndex, hidden] of backgroundGraphicsEdits) row(`第 ${order.indexOf(slideIndex) + 1} 页 · ${hidden ? '隐藏' : '显示'}背景图形`, () => backgroundGraphicsEdits.delete(slideIndex))
  for (const box of textBoxEdits) {
    const text = document.createElement('input')
    text.type = 'text'
    text.value = box.text
    text.maxLength = 20000
    text.setAttribute('aria-label', box.equation ? '新增公式文本' : box.watermark ? '水印文字' : '新增文本内容')
    text.addEventListener('input', () => { box.text = text.value; markDirty() })
    row(`第 ${order.indexOf(box.slideIndex) + 1} 页 · ${box.field === 'slidenum' ? '页码字段' : box.field === 'datetime1' ? '日期字段' : box.equation ? '公式文本' : box.wordArt ? '艺术字' : box.watermark ? '水印' : '文本'} `, () => {
      textBoxEdits.splice(textBoxEdits.indexOf(box), 1)
    }, text)
  }
  for (const [key, deletion] of deletions) {
    row(`第 ${order.indexOf(deletion.slideIndex) + 1} 页 · 删除 ${deletion.label}`, () => deletions.delete(key))
  }
}

function addTextBox(watermark: boolean) {
  if (locked() || !deck) return
  const width = deck.size.cx / 9525
  const height = deck.size.cy / 9525
  textBoxEdits.push(watermark
    ? { slideIndex: selectedSlide, text: '内部资料', watermark, fontSize: 64, fontFamily: 'Microsoft YaHei', color: '#DCE3EB', rotation: -25,
        geometry: { x: Math.round(width * 0.2), y: Math.round(height * 0.4), width: Math.round(width * 0.6), height: 120 } }
    : { slideIndex: selectedSlide, text: '请输入文本', watermark, fontSize: 28, fontFamily: 'Microsoft YaHei', color: '#1B2A41',
        geometry: { x: Math.round(width * 0.1), y: Math.round(height * 0.2), width: Math.round(width * 0.6), height: 90 } })
  canvasStatus.textContent = '新增文本与水印将在保存并打开新修订后显示在画布中。'
  renderStructurePending()
  markDirty()
}
textAdd.addEventListener('click', () => { if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; return } addTextBox(false) })
watermarkAdd.addEventListener('click', () => { if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; return } addTextBox(true) })
backgroundColor.addEventListener('change', () => {
  if (isNewSlide(selectedSlide)) { statusMessage.textContent = NEW_SLIDE_REASON; renderInspector(); return }
  backgroundEdits.set(selectedSlide, backgroundColor.value.toUpperCase())
  dropBackgroundImages([selectedSlide])
  canvasStatus.textContent = '背景修改将在保存并打开新修订后更新画布。'
  renderStructurePending()
  renderInspector()
  markDirty()
})
backgroundReset.addEventListener('click', () => {
  backgroundEdits.delete(selectedSlide)
  renderStructurePending()
  renderInspector()
  markDirty()
})
objectDelete.addEventListener('click', () => {
  const element = currentElement()
  if (locked() || !element?.deletable || chartTools.hasPending(selectedSlide, element.id)) return
  const key = editKey(selectedSlide, element.id)
  // 删除优先：同一对象的文字、位置、格式和动画修改一并撤回，避免保存时引用已删除对象。
  for(let index=pictureCrops.length-1;index>=0;index--)if(editKey(pictureCrops[index]!.slideIndex,pictureCrops[index]!.elementId)===key)pictureCrops.splice(index,1)
  for (let index = pictureOpacities.length - 1; index >= 0; index--) if (editKey(pictureOpacities[index]!.slideIndex, pictureOpacities[index]!.elementId) === key) pictureOpacities.splice(index, 1)
  for(let index=pictureReplacements.length-1;index>=0;index--)if(editKey(pictureReplacements[index]!.slideIndex,pictureReplacements[index]!.elementId)===key)pictureReplacements.splice(index,1)
  edits.delete(key)
  textFormattingEdits.delete(key)
  shapeStyleEdits.delete(key)
  for (const cellKey of [...tableCellEdits.keys()]) if (cellKey.startsWith(`${key}:`)) tableCellEdits.delete(cellKey)
  shapeKindEdits.delete(key)
  for (let index = paragraphFormattingEdits.length - 1; index >= 0; index--) {
    const patch = paragraphFormattingEdits[index]!
    if (editKey(patch.slideIndex, patch.elementId) === key) paragraphFormattingEdits.splice(index, 1)
  }
  for (let index = animationEdits.length - 1; index >= 0; index--) {
    if (editKey(animationEdits[index]!.slideIndex, animationEdits[index]!.elementId) === key) animationEdits.splice(index, 1)
  }
  if (animationSequences.has(selectedSlide)) { animationSequences.set(selectedSlide, removeElementAnimations(animationSequences.get(selectedSlide)!, slideAt(selectedSlide)?.animations ?? [], element.id)); selectedAnimationRow = -1 }
  deletions.set(key, { slideIndex: selectedSlide, elementId: element.id, label: element.name || element.text.split('\n')[0]?.slice(0, 30) || element.type })
  selectedElement = ''
  undoSnapshot = undefined
  undoButton.disabled = true
  renderStructurePending()
  renderInspector()
  refreshCanvasPreview()
  markDirty()
})

imageForm.addEventListener('submit', async event => {
  event.preventDefault()
  if (native) return
  if (!imagePrompt.value.trim() || imageGenerate.disabled) return
  imageGenerate.disabled = true
  imageStatus.textContent = '正在生成配图…'
  imageCandidate.hidden = true
  try {
    generatedImage = await request<GeneratedImage>('ai/image', {
      method: 'POST', body: JSON.stringify({ prompt: imagePrompt.value }),
    })
    imagePreview.src = generatedImage.previewDataUrl
    imageCandidate.hidden = false
    imageStatus.textContent = '预览已生成，检查后可加入幻灯片。'
  } catch (error) {
    generatedImage = undefined
    imageStatus.textContent = error instanceof Error ? error.message : '配图生成失败，幻灯片未改变。'
  } finally {
    imageGenerate.disabled = false
  }
})
imageAdd.addEventListener('click', () => {
  if (!generatedImage || !deck) return
  const slideIndex = Number(imageTarget.value)
  const width = Math.min(420, deck.size.cx / 9525 * 0.75)
  const height = Math.min(240, deck.size.cy / 9525 * 0.45)
  imageEdits.push({
    candidateId: generatedImage.candidateId,
    slideIndex,
    geometry: {
      x: Math.round((deck.size.cx / 9525 - width) / 2),
      y: Math.round((deck.size.cy / 9525 - height) / 2),
      width: Math.round(width),
      height: Math.round(height),
    },
  })
  generatedImage = undefined
  imageCandidate.hidden = true
  imageStatus.textContent = '配图已加入待保存列表。'
  renderPendingImages()
  markDirty()
})

const chartTools = createSlidesChartTools(root.querySelector<HTMLElement>('.slides-inspector')!, request, markDirty, { enabled: !native })

const saveButton = root.querySelector<HTMLButtonElement>('.save-button') ?? sharedShell?.save!
if (!saveButton) throw new Error('slides save action is missing')
if (root.querySelector('.save-icon')) saveButton.querySelector('.save-icon')!.append(createElement(Save, { width: 16, height: 16, 'aria-hidden': 'true' }))
undoButton.replaceChildren(createElement(Undo2, { width: 17, height: 17, 'aria-hidden': 'true' }))
aiCancel.append(createElement(X, { width: 16, height: 16, 'aria-hidden': 'true' }))
undoButton.addEventListener('click', () => {
  if (!undoSnapshot) return
  order.splice(0, order.length, ...undoSnapshot.order)
  edits.clear()
  for (const edit of undoSnapshot.edits) edits.set(editKey(edit.slideIndex, edit.elementId), edit)
  selectedTheme = undoSnapshot.theme
  undoSnapshot = undefined
  undoButton.disabled = true
  dirty = true
  renderSlides()
  renderInspector()
  refreshCanvasPreview()
  markDirty()
})

function renderAIProposal(proposal: AIProposal) {
  pendingAIProposal = proposal
  aiSummary.textContent = proposal.summary
  aiEdits.replaceChildren()
  for (const edit of proposal.edits) {
    const item = document.createElement('li')
    const existing = deck.slides[edit.slideIndex]?.elements.find(element => element.id === edit.elementId)
    item.textContent = `第 ${edit.slideIndex + 1} 页 · ${existing?.name || existing?.text.split('\n')[0] || edit.elementId}${edit.text !== undefined ? `：${edit.text}` : ' · 调整位置与大小'}`
    aiEdits.append(item)
  }
  if (proposal.order.some((slide, index) => order[index] !== slide)) {
    const item = document.createElement('li')
    item.textContent = `页面顺序：${proposal.order.map(index => index + 1).join(' → ')}`
    aiEdits.append(item)
  }
  if (proposal.theme) {
    const item = document.createElement('li')
    item.textContent = `商务主题：${{ executive: '执行汇报', clinical: '临床医疗', modern: '现代商务' }[proposal.theme]}`
    aiEdits.append(item)
  }
  if (!proposal.edits.length && !proposal.theme && !proposal.order.some((slide, index) => order[index] !== slide)) {
    const item = document.createElement('li')
    item.textContent = '没有需要应用的变化'
    aiEdits.append(item)
  }
  aiPreview.hidden = false
  aiAccept.disabled = false
}

aiForm.addEventListener('submit', async (event) => {
  event.preventDefault()
  if (native || !aiInstruction.value.trim() || activeAIEditId) return
  aiPreview.hidden = true
  pendingAIProposal = undefined
  aiSubmit.disabled = true
  aiResult.textContent = '正在规划幻灯片调整…'
  try {
    const started = await request<{ editId: string }>('ai/start', {
      method: 'POST', body: JSON.stringify({ instruction: aiInstruction.value }),
    })
    activeAIEditId = started.editId
    aiCancel.hidden = false
    let status: AIStatus
    do {
      status = await request<AIStatus>(`ai/${encodeURIComponent(activeAIEditId)}?wait_ms=20000`)
    } while (status.status === 'running')
    if (status.status === 'succeeded' && status.proposal) {
      pendingAIEditId = activeAIEditId
      aiResult.textContent = '候选已就绪，请检查后采纳。'
      renderAIProposal(status.proposal)
    } else {
      aiResult.textContent = status.error?.message ?? 'AI 编辑已取消。'
    }
  } catch (error) {
    aiResult.textContent = error instanceof Error ? error.message : 'AI 编辑失败'
  } finally {
    activeAIEditId = ''
    aiSubmit.disabled = false
    aiCancel.hidden = true
  }
})

aiCancel.addEventListener('click', async () => {
  if (!activeAIEditId) return
  aiCancel.disabled = true
  try {
    await request(`ai/${encodeURIComponent(activeAIEditId)}/cancel`, { method: 'POST' })
  } catch (error) {
    aiResult.textContent = error instanceof Error ? error.message : '取消失败'
  } finally {
    aiCancel.disabled = false
  }
})

aiAccept.addEventListener('click', async () => {
  if (locked() || !pendingAIProposal || !pendingAIEditId) return
  if (newSlides.length || deletedSlides.size) { statusMessage.textContent = '请先保存新建或删除的幻灯片，再采纳 AI 页面修改'; return }
  ++mutationPending
  aiAccept.disabled = true
  try {
    await request(`ai/${encodeURIComponent(pendingAIEditId)}/accept`, { method: 'POST' })
    if (locked()) return
    undoSnapshot = { order: [...order], edits: [...edits.values()].map(edit => ({ ...edit })), ...(selectedTheme ? { theme: selectedTheme } : {}) }
    for (const edit of pendingAIProposal.edits) {
      const key = editKey(edit.slideIndex, edit.elementId)
      if (deletions.has(key)) continue
      edits.set(key, { ...edits.get(key), ...edit })
    }
    if (pendingAIProposal.theme) selectedTheme = pendingAIProposal.theme
    order.splice(0, order.length, ...pendingAIProposal.order)
    undoButton.disabled = false
    pendingAIProposal = undefined
    pendingAIEditId = ''
    aiPreview.hidden = true
    aiResult.textContent = '候选已采纳，可撤销或保存为新修订。'
    dirty = true
    refreshCanvasPreview()
    renderSlides()
    renderInspector()
    markDirty()
  } catch (error) {
    aiAccept.disabled = false
    aiResult.textContent = error instanceof Error ? error.message : '采纳失败'
  } finally { --mutationPending }
})

const save = async () => {
  if (refresh?.busy || locked() || mutationPending || saveButton.disabled) return
  stopBrush()
  if (native && (!commentPane.flush()||notesPane&&!notesPane.flush())) return
  if(chartFormatPane&&!chartFormatPane.flush())return
  if(geometryPane&&!geometryPane.flush())return
  if(backgroundPane&&!backgroundPane.flush())return
  ++backgroundPickGeneration
  if(shapeFormatPane&&!shapeFormatPane.flush())return
  if (!dirty && imageEdits.length === 0) return
  ++cutoutGeneration;cutoutDialog?.dispose();cutoutDialog=undefined
  customShowDialog?.dispose();customShowDialog=undefined
  mediaPickerController?.abort();mediaPlayback?.dispose();mediaPlayback=undefined
  saving = true
  refresh?.update()
  closeStructureDialog()
  ++previewSequence
  clearTimeout(previewTimer)
  setEditingLocked(true)
  saveButton.disabled = true
  stateLabel.textContent = '正在保存'
  try {
    const result = await request<{ revision: number; revisionRegistered?: boolean; pptx?: { downloadUrl?: string }; editor?: { openUrl: string }; validation: { issues: { message: string }[] } }>('save', {
      method: 'POST',
    body: JSON.stringify({ expectedSha256: deck.sha256, ...(nativeDraft ? { operations: nativeDraft.operations }
      : { ...slideChanges(), ...(!native ? { chartEdits: chartTools.pendingEdits() } : {}), ...(imageEdits.length ? { imageEdits } : {}) }) }),
    })
    if (result.revisionRegistered !== true) {
      stateLabel.textContent = '修订未登记，草稿已保留'
      statusMessage.textContent = result.validation.issues.map(issue => issue.message).join('；') || '文件已生成，可重试保存登记'
      if (result.pptx?.downloadUrl) { downloadLink.href = result.pptx.downloadUrl; downloadLink.hidden = false; downloadLink.textContent = '下载 PPTX' }
      return
    }
    dirty = false
    savedRevision = true
    ++previewSequence
    clearTimeout(previewTimer)
    chartTools.saved()
    renderCanvas()
    imageEdits.splice(0, imageEdits.length)
    animationEdits.splice(0, animationEdits.length)
    animationSequences.clear(); selectedAnimationRow = -1
    commentEdits.splice(0); commentPane.clearDrafts()
    hiddenSlideEdits.clear()
    transitionEdits.clear()
    layoutEdits.clear()
    slideSizeEdit = undefined
    groupEdits.splice(0)
    notesEdits.clear();linkEdits.splice(0);clipboardPastes.splice(0);nativeClipboard=undefined;stopBrush()
    backgroundEdits.clear()
    customShowEdits=undefined
    backgroundImageEdits.splice(0); backgroundImageReuseEdits.splice(0); backgroundGradientEdits.splice(0); backgroundResetEdits.clear(); backgroundGraphicsEdits.clear()
    textBoxEdits.splice(0, textBoxEdits.length)
    textFormattingEdits.clear()
    paragraphFormattingEdits.splice(0)
    deletions.clear()
    renderStructurePending()
    renderPendingImages()
    revisionLabel.textContent = `修订 ${result.revision}`
    stateLabel.textContent = result.validation.issues.length ? '已保存，存在告警' : '已保存'
    statusMessage.textContent = result.validation.issues.map(issue => issue.message).join('；') || '已创建新的 PPTX 修订'
    if (result.pptx?.downloadUrl) {
      downloadLink.href = result.pptx.downloadUrl
      downloadLink.hidden = false
      downloadLink.textContent = '下载 PPTX'
      downloadLink.prepend(createElement(Download, { width: 16, height: 16, 'aria-hidden': 'true' }))
    }
    statusMessage.append(' · 打开新修订后继续编辑')
    if (result.editor?.openUrl) {
      const reopen = document.createElement('a')
      reopen.href = result.editor.openUrl
      reopen.className = 'revision-link'
      reopen.textContent = '打开新修订'
      statusMessage.append(' · ', reopen)
    }
  } catch (error) {
    stateLabel.textContent = '保存失败'
    statusMessage.textContent = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving = false
    root.inert = false
    if (!savedRevision) setEditingLocked(false)
    updateNativeHistory()
    saveButton.disabled = savedRevision
    refresh?.update()
  }
}
saveButton.addEventListener('click', save)

async function start() {
  try {
    if (!native && basePath.startsWith('/reports/v1/slides/')) refresh = await mountOfficeReportRefresh(root.closest<HTMLElement>('.report-app') ?? root.parentElement!, 'pptx', request, {
      saving: () => saving,
      blocked: () => loading || locked() || mutationPending > 0 || saveButton.disabled,
      flush: () => {
        if (native && !commentPane.flush() || notesPane && !notesPane.flush() || chartFormatPane && !chartFormatPane.flush()
          || geometryPane && !geometryPane.flush() || shapeFormatPane && !shapeFormatPane.flush()) throw new Error('请先完成当前输入')
        if (document.activeElement instanceof HTMLElement && root.contains(document.activeElement)) document.activeElement.blur()
      }, dirty: () => dirty || imageEdits.length > 0 || chartTools.pendingEdits().length > 0,
      save, setRefreshing: binaryRefreshLock(root, saveButton, () => saving || savedRevision || disposed),
    })
    deck = await request<Deck>('deck')
    nativeRibbon?.setLayouts(deck.layouts ?? [])
    order.push(...deck.slides.map(slide => slide.slideIndex))
    restoreNativeDraft()
    imageTarget.replaceChildren(...deck.slides.map((slide, index) => {
      const option = document.createElement('option')
      option.value = String(slide.slideIndex)
      option.textContent = `第 ${index + 1} 页`
      return option
    }))
    revisionLabel.textContent = `修订 ${deck.revision}`
    renderSlides()
    renderInspector()
    if (native && nativeDraft && sharedShell?.nativeAI) {
      const aiHost = document.createElement('div'); aiHost.style.display = 'contents'
      root.querySelector('.slides-workspace')!.before(aiHost)
      nativeAIHost = mountSlidesNativeAI(aiHost, { api: sharedShell.nativeAI, locked,
        context: scope => {
          if(notesPane&&!notesPane.flush())throw new Error('请先完成或修正演讲者备注输入，再生成 AI 候选')
          if (newSlides.length || deletedSlides.size) throw new Error('请先保存新建或删除的页面，再生成 AI 候选')
          if(scope==='notes'||scope==='deckNotes'){
            const pages=scope==='notes'?deck.slides.filter(slide=>slide.slideIndex===selectedSlide):deck.slides
            if(!pages.length||pages.length>100)throw new Error('请选择不超过100页的演讲者备注')
            const unsafe=pages.find(slide=>slide.notesEditable!==true)
            if(unsafe)throw new Error('第'+(order.indexOf(unsafe.slideIndex)+1)+'页备注不可编辑：'+slidesNotesReadOnlyReason(unsafe.notesReason))
            return {expectedSha256:deck.sha256,operations:nativeDraft.operations,selection:pages.map(slide=>({slideIndex:slide.slideIndex})),scope:'notes',objects:[],
              notes:pages.map(slide=>({slideIndex:slide.slideIndex,text:notesEdits.get(slide.slideIndex)??slide.notesText??''})),
              label:scope==='notes'?'第'+(order.indexOf(selectedSlide)+1)+'页 · 仅授权演讲者备注':'整稿 · 仅授权演讲者备注'}
          }
          const objects = slidesAIObjects(deck.slides,nativeDraft.operations,scope,selectedSlide,selectedObjects)
          return { expectedSha256: deck.sha256, operations: nativeDraft.operations, selection: scope === 'deck' ? [] : objects.map(({ slideIndex, elementId }) => ({ slideIndex, elementId })),
            scope: scope === 'deck' ? 'deck' : 'selection', objects, label: scope === 'deck' ? '整份演示文稿 · 已有可编辑对象' : '第 ' + (order.indexOf(selectedSlide) + 1) + ' 页 · ' + (scope === 'slide' ? '本页可编辑对象' : objects[0]?.name || '请选择可编辑对象') }
        }, accepting: value => { mutationPending += value ? 1 : -1 },
        apply: operations => {
          const previous = nativeDraft.operations
          nativeDraft.setOperations(operations)
          try { restoreNativeDraft() } catch (error) { nativeDraft.setOperations(previous); restoreNativeDraft(); throw error }
          renderSlides(); renderInspector(); refreshCanvasPreview(); updateNativeHistory()
          stateLabel.textContent = '有未保存修改'; statusMessage.textContent = nativeDraft.persistenceError ?? 'AI 候选已加入草稿，尚未保存'
        } })
      nativeRibbon?.setAIEditEnabled(true)
    }
    void request<{ slides: (RenderSlide & { slideIndex: number;mediaSources?:SlideMediaSource[];modelSources?:ModelSource[] })[] }>('render-tree').then(async tree => {
      if (!Array.isArray(tree.slides) || !tree.slides.every(slide => Array.isArray(slide.nodes))) throw new Error('画布数据无效')
      const { mountSlidesCanvas } = await import('./slides-canvas')
      renderTree = tree
      canvasHost.hidden = false
      preview.hidden = true
      canvas = mountSlidesCanvas(canvasHost)
      canvasStatus.textContent = '点击对象选择，拖动调整位置，拖动角点缩放'
      renderCanvas()
      if (nativeDraft?.dirty) refreshCanvasPreview()
    }).catch(() => { canvasStatus.textContent = '画布暂不可用，显示 PDF 兼容预览；可继续使用对象面板编辑。' })
    loading = false
    refresh?.update()
    stateLabel.textContent = dirty ? '有未保存修改' : '可编辑'
    statusMessage.textContent = nativeDraft?.persistenceError ?? `${deck.slides.length} 页 · 已核验 PPTX 身份${dirty ? ' · 已恢复本地草稿' : ''}`
  } catch (error) {
    stateLabel.textContent = '载入失败'
    statusMessage.textContent = error instanceof Error ? error.message : '无法载入幻灯片'
    if (native) throw error
  }
}

if (root.querySelector('.slides-brand')) root.querySelector('.slides-brand')!.append(createElement(Sparkles, { width: 18, height: 18, 'aria-hidden': 'true' }))
if (root.querySelector('.download-link')) root.querySelector('.download-link')!.append(createElement(Download, { width: 16, height: 16, 'aria-hidden': 'true' }))
const ready = start()
return { ready, get officeEditAssistant() { return nativeAIHost }, async officeReadContext(scope: 'document' | 'selection'): Promise<import('./native-api').NativeOfficeReadContext> {
  if (disposed || locked() || mutationPending || !nativeDraft) throw new Error('当前文档暂不可读取，请完成正在进行的操作')
  if (notesPane && !notesPane.flush()) throw new Error('请先完成当前演讲者备注输入')
  if (!commentPane.flush()) throw new Error('请先完成当前批注输入')
  // 对象正文 input 事件已同步进入 slideChanges/nativeDraft；此处再核对完整当前状态。
  const operations = nativeDraft.operations.length || dirty ? [{kind:'editSlides', ...slideChanges()}] : []
  let selection: import('./native-api').NativeOfficeReadSelection = null
  if (scope === 'selection') {
    if (newSlides.length || deletedSlides.size || groupEdits.length) throw new Error('页面或组合结构已变化，请先保存再选择阅读范围')
    const ids = [...selectedObjects]
    if (selectionSlide !== selectedSlide || !ids.length || ids.some(id=>!slideAt(selectedSlide).elements.some(item=>item.id===id) || deletions.has(editKey(selectedSlide,id)))) throw new Error('选区无法可靠对应来源，请重新选择对象')
    selection = ids.map(elementId=>({slideIndex:selectedSlide,elementId}))
  }
  nativeDraft.setOperations(operations)
  return {operations:structuredClone(operations),selection}
}, dispose() { disposed = true; zoomController?.abort();zoomDialog?.remove(); screenRecordingController?.abort(); printDialog?.dispose(); inkControls?.dispose(); modelControls?.dispose(); ++cutoutGeneration;cutoutDialog?.dispose(); customShowDialog?.dispose(); mediaPickerController?.abort(); mediaPlayback?.dispose();canvasHost.removeEventListener('dragover',onMediaDragOver);canvasHost.removeEventListener('drop',onMediaDrop); ++masterTextDialogGeneration; masterTextDialog?.dispose(); ++animationPreviewGeneration; animationPreviewOverlay?.dispose(); slideOutline?.dispose(); slideReading?.dispose(); slideSorter?.dispose(); ruler.dispose(); guides.dispose(); refresh?.dispose(); notesPane?.dispose(); stopBrush(); nativeClipboard=undefined; linkDialog?.dispose(); window.removeEventListener('keydown',onClipboardKey); showOverlay?.dispose(); nativeAIHost?.dispose(); closeStructureDialog(); ++previewSequence; clearTimeout(previewTimer); saveButton.removeEventListener('click', save); for(const type of ['input','change','click'])root.removeEventListener(type,guardPendingGroup,true); nativeRibbon?.dispose(); chartFormatPane?.dispose(); geometryPane?.dispose(); shapeFormatPane?.dispose(); backgroundPane?.dispose(); findDialog?.dispose(); chartDialog?.dispose(); cropOverlay?.dispose(); sizeDialog?.dispose(); equationDialog?.dispose(); canvas?.destroy?.() } }
}

if (document.querySelector('#slides-app')) createSlidesEditorView(document.querySelector('#slides-app')!)
