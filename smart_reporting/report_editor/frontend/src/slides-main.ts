import { applyTransitionToAll, restoredTransitions, SLIDE_TRANSITIONS, type SlideTransition } from './slides-transitions'
import { PARAGRAPH_LIST_COMMANDS, BULLET_GLYPHS, paragraphCommandPatch, projectParagraphs, uniformParagraphValue, type ParagraphFormatting, type ParagraphSourceFormatting, type ParagraphList } from './slides-paragraph'
import { createElement, ArrowDown, ArrowUp, Download, Redo2, Save, Sparkles, Trash2, Undo2, X } from 'lucide'
import './slides.css'
import type { RenderSlide } from '@genoffice/pptx-render'
import { requestJson } from './api-request'
import type { SlidesCanvasState } from './slides-canvas'
import { createSlidesChartTools } from './slides-chart-tools'
import { createSlidesNativeRibbon, stepNativeFontSize, type NativeSlidesContext, type NativeSlidesRibbon } from './slides-native-ribbon'
import type { NativeDraft } from './native-draft'
import { openSlidesSizeDialog } from './slides-size-dialog'
import { isPortrait, matchSlideSizePreset, presetSize, SLIDE_SIZE_PRESETS, MIN_SLIDE_EMU, MAX_SLIDE_EMU, type SlideSizePreset } from './vendor/genoffice-slides/slide-size'

type DeckElement = { id: string; type: string; name: string; text: string; editable: boolean; deletable?: boolean; geometry?: { x: number; y: number; width: number; height: number }; paragraphAlignments?: (ParagraphFormatting['align'] | null)[]; paragraphFormatting?: ParagraphSourceFormatting[]; paragraphLists?: ParagraphList[]; textStyle?: { fontSizePt?: number | null; fontFamily?: string | null; color?: string | null; bold?: boolean | null; italic?: boolean | null; underline?: boolean | null; strike?: boolean | null } }
type Animation = { elementId: string; effect: string; trigger: string; durationMs?: number; delayMs?: number; direction?: string }
type DeckLayout = { path: string; name: string; layoutType: string; placeholders: { type: string; idx: string; hint: string }[] }
type DeckSlide = { slideIndex: number; background?: string | null; layoutPath?: string; masterPath?: string; themePath?: string; transition?: SlideTransition; transitionEditSafe?: boolean; transitionEditReason?: string | null; transitionApplyAllSafe?: boolean; transitionApplyAllReason?: string | null; animations?: Animation[]; elements: DeckElement[] }
type Deck = { revision: number; sha256: string; size: { cx: number; cy: number }; layouts?: DeckLayout[]; masterParts?: { partPath: string; kind: 'master' | 'layout'; name: string }[]; slides: DeckSlide[] }
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
type AnimationEffect = 'appear' | 'fade' | 'flyIn' | 'wipe' | 'wipeDown' | 'splitIn' | 'bounce' | 'flipIn' | 'zoom' | 'pulse' | 'spin' | 'grow' | 'teeter' | 'disappear' | 'fadeOut' | 'flyOut' | 'wipeOut' | 'shrink' | 'zoomOut' | 'motionPath'
type AnimationTrigger = 'onClick' | 'withPrev' | 'afterPrev'
type TextBoxEdit = { slideIndex: number; text: string; geometry: { x: number; y: number; width: number; height: number }; fontSize: number; fontFamily: string; color: string; bold?: boolean; rotation?: number; watermark: boolean }
type AnimationDirection = 'top' | 'bottom' | 'left' | 'right'
type AnimationEdit = { slideIndex: number; elementId: string; effect: AnimationEffect; trigger: AnimationTrigger; durationMs: number; delayMs: number; direction?: AnimationDirection; append?: true }
type SlideChanges = {
  edits?: Edit[]; order?: number[]; theme?: BusinessTheme; slideSize?: { cx: number; cy: number }
  textFormatting?: TextFormatting[]; paragraphFormatting?: ParagraphFormatting[]
  transitions?: { slideIndex: number; kind: SlideTransition }[]; animations?: AnimationEdit[]
  slideLayouts?: { slideIndex: number; layoutPath: string }[]; backgrounds?: { slideIndex: number; color: string }[]
  textBoxes?: Omit<TextBoxEdit, 'watermark'>[]; deletions?: { slideIndex: number; elementId: string }[]
}

export function createSlidesEditorView(host: HTMLElement, sharedShell?: {
  save?: HTMLButtonElement
  download?: HTMLAnchorElement
  request?: <T>(path: string, init?: RequestInit) => Promise<T>
  native?: boolean
  draft?: NativeDraft
}) {
const root = host
const basePath = location.pathname.replace(/\/$/, '')
const embedded = Boolean(sharedShell)
const native = sharedShell?.native === true
const nativeDraft = native ? sharedShell?.draft : undefined
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
    <aside class="slides-inspector" aria-label="对象编辑"><div class="inspector-heading">对象</div><div class="slide-lineage"><span class="lineage-label">母版</span><span class="slide-master"></span><span class="lineage-label">版式</span><select id="layout-select" aria-label="当前页版式"></select></div><label class="field-label" for="object-select">可编辑对象</label><select id="object-select"></select><label class="field-label" for="object-text">文字</label><textarea id="object-text" rows="7" spellcheck="false"></textarea><div class="geometry-heading">位置与大小</div><div class="geometry-grid"><label>X <input name="x" type="number" min="0" step="1"></label><label>Y <input name="y" type="number" min="0" step="1"></label><label>宽 <input name="width" type="number" min="1" step="1"></label><label>高 <input name="height" type="number" min="1" step="1"></label></div><div class="structure-controls"><label class="field-label" for="background-color">页面背景</label><div class="structure-row"><input id="background-color" type="color" value="#ffffff" aria-label="当前页背景颜色"><button class="background-reset" type="button">恢复原背景</button></div><div class="field-label">页面对象</div><div class="structure-row"><button class="text-add" type="button">新增文本</button><button class="watermark-add" type="button">新增水印</button><button class="object-delete" type="button">删除对象</button></div><ul class="structure-pending" aria-label="待保存的页面结构修改"></ul></div><label class="field-label" for="theme-select">商务主题</label><select id="theme-select"><option value="">保持当前主题</option><option value="executive">执行汇报</option><option value="clinical">临床医疗</option><option value="modern">现代商务</option></select><label class="field-label" for="transition-select">页面转场</label><select id="transition-select"><option value="none">无</option><option value="fade">淡化</option><option value="push">推进</option><option value="wipe">擦除</option><option value="split">分割</option><option value="circle">圆形</option><option value="cover">覆盖</option><option value="pull">拉伸</option><option value="dissolve">溶解</option><option value="zoom">缩放</option><option value="morph">变形</option><option value="random">随机</option></select><div class="animation-controls"><label class="field-label" for="animation-effect">动画效果</label><select id="animation-effect"><option value="fade">淡化</option><option value="appear">出现</option><option value="flyIn">飞入</option><option value="wipe">擦除</option><option value="wipeDown">向下擦除</option><option value="splitIn">分割进入</option><option value="bounce">弹跳</option><option value="flipIn">翻转进入</option><option value="zoom">缩放进入</option><option value="pulse">脉冲</option><option value="spin">旋转</option><option value="grow">放大</option><option value="teeter">摇摆</option><option value="disappear">消失</option><option value="fadeOut">淡出</option><option value="flyOut">飞出</option><option value="wipeOut">擦除退出</option><option value="shrink">缩小退出</option><option value="zoomOut">缩小退出</option><option value="motionPath">路径</option></select><label class="field-label" for="animation-trigger">触发方式</label><select id="animation-trigger"><option value="onClick">点击时</option><option value="withPrev">与上一动画同时</option><option value="afterPrev">上一动画后</option></select><div class="animation-timing"><label>持续 <input id="animation-duration" type="number" min="1" max="120000" step="50" value="500"> ms</label><label>延迟 <input id="animation-delay" type="number" min="0" max="120000" step="50" value="0"> ms</label></div><button class="animation-add" type="button">添加对象动画</button></div><p class="animation-state"></p><p class="object-note">未编辑对象会保留在原始 PPTX 中。</p></aside>
  </div>
  <footer class="slides-statusbar"><span class="status-dot"></span><span class="status-message">读取 PPTX…</span><span class="status-spacer"></span><span>编辑器</span></footer>
`
if (embedded) root.classList.add('slides-embedded')
if (native) for (const panel of root.querySelectorAll<HTMLElement>('.slides-ai, .slides-image-tools')) { panel.hidden = true; panel.inert = true }

const list = root.querySelector<HTMLOListElement>('.slide-list')!
const select = root.querySelector<HTMLSelectElement>('#object-select')!
const textArea = root.querySelector<HTMLTextAreaElement>('#object-text')!
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
const backgroundEdits = new Map<number, string>()
const textBoxEdits: TextBoxEdit[] = []
const textFormattingEdits = new Map<string, TextFormatting>()
const paragraphFormattingEdits: ParagraphFormatting[] = []
const deletions = new Map<string, { slideIndex: number; elementId: string; label: string }>()
const edits = new Map<string, Edit>()
const imageEdits: ImageEdit[] = []
const animationEdits: AnimationEdit[] = []
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
let dirty = false
let savedRevision = false
let saving = false
let mutationPending = 0
const locked = () => saving || savedRevision
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
  if (!value) lockFields.clear()
  updateNativeHistory()
  renderCanvas()
}
for (const kind of ['click', 'input', 'change', 'submit']) root.addEventListener(kind, event => {
  if (locked() && !(savedRevision && event.target instanceof Element && event.target.closest('a'))) { event.preventDefault(); event.stopImmediatePropagation() }
}, true)

let renderTree: { slides: (RenderSlide & { slideIndex: number })[] } | undefined
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
  void request<{ slides: (RenderSlide & { slideIndex: number })[] }>('render-tree', {
    method: 'POST', body: JSON.stringify(native
      ? { expectedSha256: deck.sha256, operations: [{ kind: 'editSlides', edits: [...edits.values()], textFormatting: [...textFormattingEdits.values()], paragraphFormatting: [...paragraphFormattingEdits.values()] }] }
      : { expectedSha256: deck.sha256, edits: [...edits.values()] }),
  }).then(tree => {
    if (sequence !== previewSequence || locked()) return
    renderTree = tree
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
const canvasStatus = root.querySelector<HTMLElement>('.canvas-status')!

function renderCanvas() {
  const slide = renderTree?.slides.find(item => item.slideIndex === selectedSlide)
  if (!canvas || !slide || !deck) return
  canvas.update({
    slide, selectedId: selectedElement,
    editableIds: new Set(locked() ? [] : deck.slides[selectedSlide]!.elements.filter(item => item.editable && !deletions.has(editKey(selectedSlide, item.id))).map(item => item.id)),
    edits: [...edits.values()].filter(item => item.slideIndex === selectedSlide),
    onSelect: id => { selectedElement = id; renderInspector() },
    onGeometry: (id, geometry) => {
      if (locked()) return
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
const currentElement = () => deck.slides[selectedSlide]?.elements.find(item => item.id === selectedElement)
const currentGeometryInputs = () => [...root.querySelectorAll<HTMLInputElement>('.geometry-grid input')]

function markDirty() {
  if (locked()) return
  nativeDraft?.setOperations([{ kind: 'editSlides', ...slideChanges() }])
  updateNativeHistory()
  renderCanvas()
  dirty = true
  stateLabel.textContent = '有未保存修改'
  statusMessage.textContent = nativeDraft?.persistenceError ?? '修改尚未保存'
}

function slideChanges(): SlideChanges {
  return { edits: [...edits.values()], ...(native ? { textFormatting: [...textFormattingEdits.values()], paragraphFormatting: [...paragraphFormattingEdits.values()] } : {}),
    order: [...order], ...(selectedTheme ? { theme: selectedTheme } : {}), ...(slideSizeEdit ? { slideSize: slideSizeEdit } : {}),
    transitions: [...transitionEdits].map(([slideIndex, kind]) => ({ slideIndex, kind })), animations: [...animationEdits],
    slideLayouts: [...layoutEdits].map(([slideIndex, layoutPath]) => ({ slideIndex, layoutPath })),
    backgrounds: [...backgroundEdits].map(([slideIndex, color]) => ({ slideIndex, color })),
    textBoxes: textBoxEdits.map(({ watermark: _watermark, ...box }) => box),
    deletions: [...deletions.values()].map(({ slideIndex, elementId }) => ({ slideIndex, elementId })) }
}

function restoreNativeDraft() {
  if (!nativeDraft) return
  const operations = nativeDraft.operations
  const supported = new Set(['kind', 'edits', 'order', 'theme', 'slideSize', 'textFormatting', 'paragraphFormatting', 'transitions', 'animations', 'slideLayouts', 'backgrounds', 'textBoxes', 'deletions'])
  // 多操作批次不能安全折叠为对象面板快照；拒绝打开并保留原草稿，防止下一次输入覆盖它。
  if (operations.length > 1 || operations.some(operation => operation.kind !== 'editSlides' || Object.keys(operation).some(key => !supported.has(key)))) {
    throw new Error('当前 PPTX 草稿包含暂不支持恢复的操作，草稿已保留')
  }
  const changes = (operations[0] ?? {}) as SlideChanges
  const transitions = restoredTransitions(changes.transitions, deck.slides.length)
  if (native && transitions.some(item => !transitionEditingAllowed(deck.slides[item.slideIndex]))) throw new Error('来源含尚不能安全修改的转场兼容性内容；原草稿已保留')
  if (changes.order !== undefined && (!Array.isArray(changes.order) || changes.order.length !== deck.slides.length || changes.order.length > 500 || new Set(changes.order).size !== changes.order.length || changes.order.some(index => !Number.isInteger(index) || index < 0 || index >= deck.slides.length))) throw new Error('草稿页面顺序无效；原草稿已保留')
  // Validate every step before mutating the recovered view or the persisted history.
  try {
    if ((changes.paragraphFormatting?.length ?? 0) > 500) throw new Error('段落格式操作超过 500 条；请分批保存')
    for (const slide of deck.slides) for (const element of slide.elements) {
      projectParagraphs(element.paragraphFormatting, element.paragraphLists, (changes.paragraphFormatting ?? []).filter(patch => patch.slideIndex === slide.slideIndex && patch.elementId === element.id))
    }
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.message : '段落操作无效'}；原草稿已保留`)
  }
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
  for (const deletion of changes.deletions ?? []) {
    const element = deck.slides[deletion.slideIndex]?.elements.find(item => item.id === deletion.elementId)
    deletions.set(editKey(deletion.slideIndex, deletion.elementId), { ...deletion, label: element?.name || element?.text || deletion.elementId })
  }
  animationEdits.splice(0, animationEdits.length, ...(changes.animations ?? []))
  textBoxEdits.splice(0, textBoxEdits.length, ...(changes.textBoxes ?? []).map(box => ({ ...box, watermark: box.rotation === -25 })))
  order.splice(0, order.length, ...(changes.order ?? deck.slides.map(slide => slide.slideIndex)))
  selectedTheme = changes.theme
  slideSizeEdit = changes.slideSize
  dirty = nativeDraft.dirty
  renderStructurePending()
  updateNativeHistory()
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
    const slide = deck.slides[slideIndex]!
    const row = document.createElement('li')
    row.className = 'slide-row'
    row.dataset.selected = String(slideIndex === selectedSlide)
    const open = document.createElement('button')
    open.type = 'button'
    open.className = 'slide-open'
    open.innerHTML = `<span class="slide-number">${position + 1}</span><span class="slide-title"></span>`
    open.querySelector('.slide-title')!.textContent = flatText(slide)
    open.addEventListener('click', () => { selectedSlide = slideIndex; renderSlides(); renderInspector() })
    const up = buttonIcon(ArrowUp, '上移页面')
    const down = buttonIcon(ArrowDown, '下移页面')
    up.disabled = position === 0
    down.disabled = position === order.length - 1
    up.addEventListener('click', () => move(position, -1))
    down.addEventListener('click', () => move(position, 1))
    row.append(open, up, down)
    list.append(row)
  }
  root.querySelector('.slide-count')!.textContent = String(order.length)
  renderCanvas()
  if (!canvas) preview.src = `${basePath}/api/preview.pdf#page=${selectedSlide + 1}&toolbar=0&navpanes=0`
}

function move(position: number, direction: -1 | 1) {
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
  return transitionEditingAllowed(deck.slides[selectedSlide]) ? null : '此页含尚不能安全修改的转场兼容性内容，请保留原转场'
}
function transitionApplyAllUnavailable(): string | null {
  if (!order.length || order.length > 500 || !order.includes(selectedSlide)) return '请先打开可编辑的演示文稿；一次最多支持 500 页'
  if (order.some(index => deck.slides[index]?.transitionApplyAllSafe !== true)) return '部分页面含未支持的转场速度、换片、声音或效果变体设置，暂不能全部应用；原文件保持不变'
  return null
}

function renderInspector() {
  renderCanvas()
  const elements = deck.slides[selectedSlide]!.elements.filter(item => (item.editable || item.deletable) && !deletions.has(editKey(selectedSlide, item.id)))
  select.replaceChildren(...elements.map(item => {
    const option = document.createElement('option')
    option.value = item.id
    option.textContent = item.name || item.text.split('\n')[0]?.slice(0, 60) || item.type
    return option
  }))
  if (!elements.some(item => item.id === selectedElement)) selectedElement = elements[0]?.id ?? ''
  select.value = selectedElement
  const element = currentElement()
  textArea.disabled = savedRevision || !element || !['text', 'shape'].includes(element.type)
  textArea.value = element ? edits.get(editKey(selectedSlide, element.id))?.text ?? element.text : ''
  const box = element && (edits.get(editKey(selectedSlide, element.id))?.geometry ?? element.geometry)
  const geometry = box ?? { x: 0, y: 0, width: 0, height: 0 }
  for (const input of currentGeometryInputs()) {
    input.value = String(geometry[input.name as keyof typeof geometry] ?? 0)
    input.disabled = savedRevision || !element?.editable
  }
  backgroundColor.value = (backgroundEdits.get(selectedSlide) ?? deck.slides[selectedSlide]!.background ?? '#FFFFFF').toLowerCase()
  backgroundReset.disabled = !backgroundEdits.has(selectedSlide)
  objectDelete.disabled = !element?.deletable || chartTools.hasPending(selectedSlide, element.id)
  objectDelete.title = element && chartTools.hasPending(selectedSlide, element.id) ? '该图表有待保存的 AI 改图，请先撤销采纳' : '删除对象'
  themeSelect.value = selectedTheme ?? ''
  transitionSelect.value = transitionEdits.get(selectedSlide) ?? deck.slides[selectedSlide]!.transition ?? 'none'
  const slide = deck.slides[selectedSlide]!
  const layouts = deck.layouts ?? []
  layoutSelect.replaceChildren(...layouts.map(layout => {
    const option = document.createElement('option')
    option.value = layout.path
    option.textContent = `${layout.name || layout.path} · ${layout.layoutType}`
    return option
  }))
  layoutSelect.value = layoutEdits.get(selectedSlide) ?? slide.layoutPath ?? ''
  layoutSelect.disabled = layouts.length === 0
  const masterPath = slide.masterPath ?? ''
  const master = (deck.masterParts ?? []).find(item => item.partPath === masterPath)
  slideMaster.textContent = master?.name || masterPath || '未读取'
  const existingAnimation = animationEdits.findLast(item => item.slideIndex === selectedSlide && item.elementId === selectedElement)
    ?? slide.animations?.find(item => item.elementId === selectedElement)
  animationEffect.value = existingAnimation?.effect ?? 'fade'
  animationTrigger.value = existingAnimation?.trigger ?? 'onClick'
  animationDuration.value = String(existingAnimation?.durationMs ?? 500)
  animationDelay.value = String(existingAnimation?.delayMs ?? 0)
  animationDurationMs = Number(animationDuration.value)
  animationDelayMs = Number(animationDelay.value)
  animationDirection = (existingAnimation?.direction as AnimationDirection | undefined) ?? 'bottom'
  animationAdd.disabled = !element?.editable
  animationState.textContent = existingAnimation ? `已有 ${existingAnimation.effect} 动画，可继续添加。` : ''
  root.querySelector('.inspector-heading')!.textContent = `对象 · 第 ${order.indexOf(selectedSlide) + 1} 页`
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
  nativeRibbon?.setValue('animationEffect', animationEffect.value)
  nativeRibbon?.setValue('animationTrigger', animationTrigger.value)
  nativeRibbon?.setValue('animationDuration', animationDuration.value)
  nativeRibbon?.setValue('animationDelay', animationDelay.value)
  nativeRibbon?.setValue('animationDirection', animationDirection)
  nativeRibbon?.setValue('text', textArea.value)
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
    : element.type === 'table' ? 'table'
      : element.type === 'chart' ? 'chart'
        : element.type === 'picture' ? 'picture'
          : element.type === 'model3d' ? 'model3d'
            : ['shape', 'text'].includes(element.type) ? 'shape' : null
  nativeRibbon?.setContext(contextualType)
  nativeRibbon?.setListTargets({ bullets: paragraphs.some(p => !!p.bulletKind && p.bulletKind !== 'none'), numbers: paragraphs.some(p => p.bulletKind === 'number'), hanging: paragraphs.some(p => (!!p.bulletKind && p.bulletKind !== 'none') || (p.indentEmu ?? 0) < 0) })
  nativeRibbon?.setTextFormatEnabled(!!element?.editable && !!element.text.trim())
}

function projectedParagraphs(element: DeckElement | undefined) {
  const formatting = element?.paragraphFormatting ?? element?.paragraphAlignments?.map(align => ({ align })) ?? []
  return projectParagraphs(formatting, element?.paragraphLists ?? [], paragraphFormattingEdits.filter(patch => patch.slideIndex === selectedSlide && patch.elementId === element?.id))
}
function updateSelectedParagraph(patch: Omit<ParagraphFormatting, 'slideIndex' | 'elementId'>) {
  const element = currentElement()
  if (!element?.editable || !element.text.trim()) return
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
  if (!element?.editable || !element.text.trim()) return
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
let nativeRibbon: NativeSlidesRibbon | undefined
if (native) nativeRibbon = createSlidesNativeRibbon(root, {
  onAction(command, value) {
    if (locked()) return
    if (PARAGRAPH_LIST_COMMANDS.includes(command)) {
      const patch = paragraphCommandPatch(command, value)
      if (patch) updateSelectedParagraph(patch)
      renderInspector()
      return
    }
    switch (command) {
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
          if (locked()) return
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
      case 'background':
        if (typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)) {
          backgroundEdits.set(selectedSlide, value.toUpperCase()); renderStructurePending(); markDirty()
        }
        break
      case 'text': {
        const element = currentElement()
        if (!element || !['text', 'shape'].includes(element.type)) break
        const edit = edits.get(editKey(selectedSlide, element.id)) ?? { slideIndex: selectedSlide, elementId: element.id }
        edit.text = String(value ?? '')
        edits.set(editKey(selectedSlide, element.id), edit)
        refreshCanvasPreview(); markDirty()
        break
      }
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
      case 'shapeGeometry': currentGeometryInputs()[0]?.focus(); root.querySelector('.geometry-heading')?.scrollIntoView({ block: 'nearest' }); return
      case 'animationEffect': animationEffect.value = String(value); nativeRibbon?.setValue(command, String(value)); return
      case 'animationDirection': animationDirection = value as AnimationDirection; return
      case 'animationTrigger': animationTrigger.value = String(value) as AnimationTrigger; return
      case 'animationDuration':
        animationDurationMs = Math.max(1, Math.min(120000, Number(value) || 500))
        animationDuration.value = String(animationDurationMs)
        return
      case 'animationDelay':
        animationDelayMs = Math.max(0, Math.min(120000, Number(value) || 0))
        animationDelay.value = String(animationDelayMs)
        return
      case 'addAnimation':
        if (!currentElement()?.editable) break
        animationEdits.push({ slideIndex: selectedSlide, elementId: selectedElement,
          effect: animationEffect.value as AnimationEffect, trigger: animationTrigger.value as AnimationTrigger,
          durationMs: animationDurationMs, delayMs: animationDelayMs, append: true,
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

select.addEventListener('change', () => { selectedElement = select.value; renderInspector() })
textArea.addEventListener('input', () => {
  const element = currentElement()
  if (!element) return
  const edit = edits.get(editKey(selectedSlide, element.id)) ?? { slideIndex: selectedSlide, elementId: element.id }
  edit.text = textArea.value
  refreshCanvasPreview()
  edits.set(editKey(selectedSlide, element.id), edit)
  undoSnapshot = undefined
  undoButton.disabled = true
  markDirty()
})
for (const input of currentGeometryInputs()) input.addEventListener('change', () => {
  const element = currentElement()
  if (!element) return
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
  if (!layoutSelect.value) return
  layoutEdits.set(selectedSlide, layoutSelect.value)
  canvasStatus.textContent = '版式修改将在保存并打开新修订后更新画布。'
  markDirty()
})
animationAdd.addEventListener('click', () => {
  if (!currentElement()) return
  animationEdits.push({
    slideIndex: selectedSlide,
    elementId: selectedElement,
    effect: animationEffect.value as AnimationEffect,
    trigger: animationTrigger.value as AnimationTrigger,
    durationMs: Math.max(1, Number(animationDuration.value) || 500),
    delayMs: Math.max(0, Number(animationDelay.value) || 0),
  })
  renderInspector()
  markDirty()
})
function renderStructurePending() {
  structurePending.replaceChildren()
  const row = (label: string, onRemove: () => void, extra?: HTMLElement) => {
    const item = document.createElement('li')
    item.append(document.createTextNode(label))
    if (extra) item.append(extra)
    const remove = buttonIcon(X, '撤销此项修改')
    remove.addEventListener('click', () => { onRemove(); renderStructurePending(); renderInspector(); markDirty() })
    item.append(remove)
    structurePending.append(item)
  }
  for (const [slideIndex, color] of backgroundEdits) {
    row(`第 ${order.indexOf(slideIndex) + 1} 页 · 背景 ${color}`, () => backgroundEdits.delete(slideIndex))
  }
  for (const box of textBoxEdits) {
    const text = document.createElement('input')
    text.type = 'text'
    text.value = box.text
    text.maxLength = 20000
    text.setAttribute('aria-label', box.watermark ? '水印文字' : '新增文本内容')
    text.addEventListener('input', () => { box.text = text.value; markDirty() })
    row(`第 ${order.indexOf(box.slideIndex) + 1} 页 · ${box.watermark ? '水印' : '文本'} `, () => {
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
textAdd.addEventListener('click', () => addTextBox(false))
watermarkAdd.addEventListener('click', () => addTextBox(true))
backgroundColor.addEventListener('change', () => {
  backgroundEdits.set(selectedSlide, backgroundColor.value.toUpperCase())
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
  edits.delete(key)
  textFormattingEdits.delete(key)
  for (let index = paragraphFormattingEdits.length - 1; index >= 0; index--) {
    const patch = paragraphFormattingEdits[index]!
    if (editKey(patch.slideIndex, patch.elementId) === key) paragraphFormattingEdits.splice(index, 1)
  }
  for (let index = animationEdits.length - 1; index >= 0; index--) {
    if (editKey(animationEdits[index]!.slideIndex, animationEdits[index]!.elementId) === key) animationEdits.splice(index, 1)
  }
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
  if (locked() || mutationPending || (!dirty && imageEdits.length === 0) || saveButton.disabled) return
  saving = true
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
    if (native && result.revisionRegistered !== true) {
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
    transitionEdits.clear()
    layoutEdits.clear()
    slideSizeEdit = undefined
    backgroundEdits.clear()
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
  }
}
saveButton.addEventListener('click', save)

async function start() {
  try {
    deck = await request<Deck>('deck')
    nativeRibbon?.setLayouts((deck.layouts ?? []).map(layout => ({ path: layout.path, name: layout.name })))
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
    void request<{ slides: (RenderSlide & { slideIndex: number })[] }>('render-tree').then(async tree => {
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
return { ready, dispose() { ++previewSequence; clearTimeout(previewTimer); saveButton.removeEventListener('click', save); nativeRibbon?.dispose(); sizeDialog?.dispose(); canvas?.destroy?.() } }
}

if (document.querySelector('#slides-app')) createSlidesEditorView(document.querySelector('#slides-app')!)
