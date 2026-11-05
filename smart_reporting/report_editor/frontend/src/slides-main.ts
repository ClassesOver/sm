import { askAIPanel } from './ask-ai-panel'
import { createAITaskAdapter } from './ai-task'
import { renderAITextPreview } from './ai-text-preview'
import { createToolbar } from './toolbar'
import type { EditorShell } from './shell'
import { createElement, ArrowDown, ArrowUp, Download, Save, Sparkles, Trash2, X } from 'lucide'
import './slides.css'
import type { RenderSlide } from '@genoffice/pptx-render'
import { requestJson } from './api-request'
import type { SlidesCanvasState } from './slides-canvas'
import { createSlidesChartTools } from './slides-chart-tools'

type DeckElement = { id: string; type: string; name: string; text: string; editable: boolean; deletable?: boolean; geometry?: { x: number; y: number; width: number; height: number } }
type SlideTransition = 'none' | 'morph' | 'fade' | 'push' | 'wipe' | 'split' | 'circle' | 'cover' | 'pull' | 'dissolve' | 'zoom' | 'random'
type Animation = { elementId: string; effect: string; trigger: string; durationMs?: number; delayMs?: number; direction?: string }
type DeckLayout = { path: string; name: string; layoutType: string; placeholders: { type: string; idx: string; hint: string }[] }
type DeckSlide = { slideIndex: number; background?: string | null; layoutPath?: string; masterPath?: string; themePath?: string; transition?: SlideTransition; animations?: Animation[]; elements: DeckElement[] }
type Deck = { revision: number; sha256: string; size: { cx: number; cy: number }; layouts?: DeckLayout[]; masterParts?: { partPath: string; kind: 'master' | 'layout'; name: string }[]; slides: DeckSlide[] }
type Edit = {
  slideIndex: number
  elementId: string
  text?: string
  geometry?: { x: number; y: number; width: number; height: number }
}
type BusinessTheme = 'executive' | 'clinical' | 'modern'
type AIProposal = { summary: string; edits: Edit[]; order: number[]; theme?: BusinessTheme }
type GeneratedImage = { candidateId: string; mediaType: string; previewDataUrl: string }
type ImageEdit = { candidateId: string; slideIndex: number; geometry: { x: number; y: number; width: number; height: number } }
type AnimationEffect = 'appear' | 'fade' | 'flyIn' | 'wipe' | 'wipeDown' | 'splitIn' | 'bounce' | 'flipIn' | 'zoom' | 'pulse' | 'spin' | 'grow' | 'teeter' | 'disappear' | 'fadeOut' | 'flyOut' | 'wipeOut' | 'shrink' | 'zoomOut' | 'motionPath'
type AnimationTrigger = 'onClick' | 'withPrev' | 'afterPrev'
type TextBoxEdit = { slideIndex: number; text: string; geometry: { x: number; y: number; width: number; height: number }; fontSize: number; fontFamily: string; color: string; bold?: boolean; rotation?: number; watermark: boolean }
type AnimationEdit = { slideIndex: number; elementId: string; effect: AnimationEffect; trigger: AnimationTrigger; durationMs: number; delayMs: number; direction?: string }

export function createSlidesEditorView(host: HTMLElement, sharedShell?: {
  save?: HTMLButtonElement
  download?: HTMLAnchorElement
} & Partial<Pick<EditorShell, 'registerToolbarAction' | 'setContextTarget' | 'refreshToolbar'>>) {
const root = host
const basePath = location.pathname.replace(/\/$/, '')
const embedded = Boolean(sharedShell)
const request = <T>(path: string, init?: RequestInit): Promise<T> =>
  requestJson(`${basePath}/api/${path}`, init, 'report_slides_csrf')

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
    <div class="slides-topbar-actions"><a class="download-link" hidden></a><button class="save-button" type="button"><span class="save-icon"></span><span>保存修订</span></button></div>
  </header>
`}
  <section class="slides-image-tools" aria-label="AI 配图"><form class="image-form"><label for="image-prompt">AI 配图</label><textarea id="image-prompt" rows="1" maxlength="1000" placeholder="描述一张用于汇报的配图"></textarea><label class="image-target-label" for="image-target">目标页</label><select id="image-target"></select><button class="image-generate" type="submit">生成预览</button></form><div class="image-output"><span class="image-status" role="status">尚未生成配图</span><div class="image-candidate" hidden><img class="image-preview" alt="AI 配图预览"><button class="image-add" type="button">加入待保存配图</button></div><ul class="image-pending"></ul></div></section>
  <div class="slides-workspace">
    <aside class="slides-sidebar" aria-label="幻灯片列表"><div class="sidebar-heading">页面 <span class="slide-count"></span></div><ol class="slide-list"></ol></aside>
    <section class="slides-stage" aria-label="幻灯片预览"><div class="slides-canvas" role="group" aria-label="可编辑幻灯片画布" hidden></div><p class="canvas-status" role="status">画布载入中</p><iframe class="preview-frame" title="幻灯片预览"></iframe></section>
    <aside class="slides-inspector" aria-label="对象编辑"><div class="inspector-heading">对象</div><div class="slide-lineage"><span class="lineage-label">母版</span><span class="slide-master"></span><span class="lineage-label">版式</span><select id="layout-select" aria-label="当前页版式"></select></div><label class="field-label" for="object-select">可编辑对象</label><select id="object-select"></select><label class="field-label" for="object-text">文字</label><textarea id="object-text" rows="7" spellcheck="false"></textarea><div class="geometry-heading">位置与大小</div><div class="geometry-grid"><label>X <input name="x" type="number" min="0" step="1"></label><label>Y <input name="y" type="number" min="0" step="1"></label><label>宽 <input name="width" type="number" min="1" step="1"></label><label>高 <input name="height" type="number" min="1" step="1"></label></div><div class="structure-controls"><label class="field-label" for="background-color">页面背景</label><div class="structure-row"><input id="background-color" type="color" value="#ffffff" aria-label="当前页背景颜色"><button class="background-reset" type="button">恢复原背景</button></div><div class="field-label">页面对象</div><div class="structure-row"><button class="text-add" type="button">新增文本</button><button class="watermark-add" type="button">新增水印</button><button class="object-delete" type="button">删除对象</button></div><ul class="structure-pending" aria-label="待保存的页面结构修改"></ul></div><label class="field-label" for="theme-select">商务主题</label><select id="theme-select"><option value="">保持当前主题</option><option value="executive">执行汇报</option><option value="clinical">临床医疗</option><option value="modern">现代商务</option></select><label class="field-label" for="transition-select">页面转场</label><select id="transition-select"><option value="none">无</option><option value="fade">淡化</option><option value="push">推进</option><option value="wipe">擦除</option><option value="split">分割</option><option value="circle">圆形</option><option value="cover">覆盖</option><option value="pull">拉伸</option><option value="dissolve">溶解</option><option value="zoom">缩放</option><option value="morph">变形</option><option value="random">随机</option></select><div class="animation-controls"><label class="field-label" for="animation-effect">动画效果</label><select id="animation-effect"><option value="fade">淡化</option><option value="appear">出现</option><option value="flyIn">飞入</option><option value="wipe">擦除</option><option value="wipeDown">向下擦除</option><option value="splitIn">分割进入</option><option value="bounce">弹跳</option><option value="flipIn">翻转进入</option><option value="zoom">缩放进入</option><option value="pulse">脉冲</option><option value="spin">旋转</option><option value="grow">放大</option><option value="teeter">摇摆</option><option value="disappear">消失</option><option value="fadeOut">淡出</option><option value="flyOut">飞出</option><option value="wipeOut">擦除退出</option><option value="shrink">缩小退出</option><option value="zoomOut">缩小退出</option><option value="motionPath">路径</option></select><label class="field-label" for="animation-trigger">触发方式</label><select id="animation-trigger"><option value="onClick">点击时</option><option value="withPrev">与上一动画同时</option><option value="afterPrev">上一动画后</option></select><div class="animation-timing"><label>持续 <input id="animation-duration" type="number" min="1" max="120000" step="50" value="500"> ms</label><label>延迟 <input id="animation-delay" type="number" min="0" max="120000" step="50" value="0"> ms</label></div><button class="animation-add" type="button">添加对象动画</button></div><p class="animation-state"></p><p class="object-note">未编辑对象会保留在原始 PPTX 中。</p></aside>
  </div>
  <footer class="slides-statusbar"><span class="status-dot"></span><span class="status-message">读取 PPTX…</span><span class="status-spacer"></span><span>编辑器</span></footer>
`
if (embedded) root.classList.add('slides-embedded')

const list = root.querySelector<HTMLOListElement>('.slide-list')!
const select = root.querySelector<HTMLSelectElement>('#object-select')!
const textArea = root.querySelector<HTMLTextAreaElement>('#object-text')!
const preview = root.querySelector<HTMLIFrameElement>('.preview-frame')!
const stateLabel = root.querySelector<HTMLElement>('.slides-save-state') ?? document.querySelector<HTMLElement>('.save-state-label')!
const statusMessage = root.querySelector<HTMLElement>('.status-message')!
const revisionLabel = root.querySelector<HTMLElement>('.revision') ?? document.querySelector<HTMLElement>('.revision-label')!
const downloadLink = root.querySelector<HTMLAnchorElement>('.download-link') ?? sharedShell?.download!
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
const deletions = new Map<string, { slideIndex: number; elementId: string; label: string }>()
const edits = new Map<string, Edit>()
const imageEdits: ImageEdit[] = []
const animationEdits: AnimationEdit[] = []
const transitionEdits = new Map<number, SlideTransition>()
const layoutEdits = new Map<number, string>()
let undoSnapshot: { order: number[]; edits: Edit[]; theme?: BusinessTheme } | undefined
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
const lockFields = new Map<HTMLInputElement | HTMLButtonElement | HTMLTextAreaElement | HTMLSelectElement, boolean>()
function setEditingLocked(value: boolean) {
  root.inert = value
  for (const field of root.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLTextAreaElement | HTMLSelectElement>('input, button, textarea, select')) {
    if (value) { if (!lockFields.has(field)) lockFields.set(field, field.disabled); field.disabled = true }
    else { field.disabled = lockFields.get(field) ?? field.disabled }
  }
  if (!value) lockFields.clear()
  renderCanvas()
}
for (const kind of ['click', 'input', 'change', 'submit']) root.addEventListener(kind, event => {
  if ((locked() || mutationPending > 0) && !(savedRevision && event.target instanceof Element && event.target.closest('a'))) { event.preventDefault(); event.stopImmediatePropagation() }
}, true)

let renderTree: { slides: (RenderSlide & { slideIndex: number })[] } | undefined
let canvas: { update: (state: SlidesCanvasState) => void } | undefined
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
    method: 'POST', body: JSON.stringify({ expectedSha256: deck.sha256, edits: [...edits.values()] }),
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
  sharedShell?.refreshToolbar?.()
  if (locked()) return
  renderCanvas()
  dirty = true
  stateLabel.textContent = '有未保存修改'
  statusMessage.textContent = '修改尚未保存'
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
  renderSlides()
  renderInspector()
  markDirty()
}

function renderInspector() {
  sharedShell?.setContextTarget?.({ kind: selectedElement ? 'object' : 'slide', id: `${selectedSlide}:${selectedElement}`, label: `第 ${selectedSlide + 1} 页` })
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
  toolbar.setContextTarget?.({ kind: 'slide-object', id: selectedElement, label: `第 ${order.indexOf(selectedSlide) + 1} 页${element?.name ? ` · ${element.name}` : ''}` })
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
  animationAdd.disabled = !element?.editable
  animationState.textContent = existingAnimation ? `已有 ${existingAnimation.effect} 动画，可继续添加。` : ''
  root.querySelector('.inspector-heading')!.textContent = `对象 · 第 ${order.indexOf(selectedSlide) + 1} 页`
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
  markDirty()
})
themeSelect.addEventListener('change', () => {
  selectedTheme = themeSelect.value ? themeSelect.value as BusinessTheme : undefined
  canvasStatus.textContent = '主题修改将在保存并打开新修订后更新画布。'
  undoSnapshot = undefined
  markDirty()
})
transitionSelect.addEventListener('change', () => {
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
  // 删除优先：同一对象的文字/位置/动画修改一并撤回，避免保存时引用已删除对象。
  edits.delete(key)
  for (let index = animationEdits.length - 1; index >= 0; index--) {
    if (editKey(animationEdits[index]!.slideIndex, animationEdits[index]!.elementId) === key) animationEdits.splice(index, 1)
  }
  deletions.set(key, { slideIndex: selectedSlide, elementId: element.id, label: element.name || element.text.split('\n')[0]?.slice(0, 30) || element.type })
  selectedElement = ''
  undoSnapshot = undefined
  renderStructurePending()
  renderInspector()
  refreshCanvasPreview()
  markDirty()
})

imageForm.addEventListener('submit', async event => {
  event.preventDefault()
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

const chartTools = createSlidesChartTools(root.querySelector<HTMLElement>('.slides-inspector')!, request, markDirty, sharedShell?.registerToolbarAction, () => locked() || mutationPending > 0)

const saveButton = root.querySelector<HTMLButtonElement>('.save-button') ?? sharedShell?.save!
if (!saveButton) throw new Error('slides save action is missing')
if (root.querySelector('.save-icon')) saveButton.querySelector('.save-icon')!.append(createElement(Save, { width: 16, height: 16, 'aria-hidden': 'true' }))
const toolbar = sharedShell?.registerToolbarAction ? sharedShell as Pick<EditorShell, 'registerToolbarAction' | 'setContextTarget' | 'refreshToolbar'>
  : createToolbar(root.querySelector<HTMLElement>('.slides-topbar-actions') ?? root.insertBefore(document.createElement('nav'), root.firstChild))
const draftPayload = () => ({ expectedSha256: deck.sha256, chartEdits: chartTools.pendingEdits(), edits: [...edits.values()], order, ...(selectedTheme ? { theme: selectedTheme } : {}), ...(imageEdits.length ? { imageEdits } : {}), transitions: [...transitionEdits].map(([slideIndex, kind]) => ({ slideIndex, kind })), animations: animationEdits, slideLayouts: [...layoutEdits].map(([slideIndex, layoutPath]) => ({ slideIndex, layoutPath })), backgrounds: [...backgroundEdits].map(([slideIndex, color]) => ({ slideIndex, color })), textBoxes: textBoxEdits.map(({ watermark: _watermark, ...box }) => box), deletions: [...deletions.values()].map(({ slideIndex, elementId }) => ({ slideIndex, elementId })) })
let acceptedSnapshot = ''
let aiTarget: { slideIndex: number; elementId: string } | undefined
const aiSession = askAIPanel().createTaskSession({
  kind: 'slides', label: '幻灯片',
  context: '预览各页文字、位置、页序与主题调整，采纳后可撤销，保存为新修订。',
  suggestions: [
    { label: '精简页面文字', instruction: '精简各页文字，保留全部数字、事实和页面顺序。' },
    { label: '标题突出结论', instruction: '将各页标题调整为结论式标题，保留原有事实。' },
    { label: '梳理汇报顺序', instruction: '按结论、分析、行动的顺序整理页面，并说明调整理由。' },
  ],
  refinements: ['标题再精简一些', '保留当前页面顺序', '使用执行汇报主题'],
  captureInput: async () => ({ snapshot: structuredClone(draftPayload()) }),
  adapter: createAITaskAdapter<AIProposal>({
    kind: 'slides-edit', request,
    validateTarget: () => { if (locked() || !deck) throw new Error('请在当前可编辑修订中重试。') },
    withDraftLock: async action => {
      if (locked() || mutationPending) throw new Error('幻灯片正在处理其他操作。')
      ++mutationPending; setEditingLocked(true); saveButton.disabled = true; toolbar.refreshToolbar()
      try { return await action() }
      finally { --mutationPending; setEditingLocked(false); saveButton.disabled = savedRevision; toolbar.refreshToolbar() }
    },
    renderProposal: (proposal, target) => {
      const summary = document.createElement('p'); summary.textContent = proposal.summary
      const changes = document.createElement('ul'); changes.className = 'ai-proposal-changes'
      const pages = new Map<number, HTMLUListElement>()
      for (const edit of proposal.edits) {
        if (!pages.has(edit.slideIndex)) {
          const page = document.createElement('li'); page.className = 'ai-proposal-page'
          const heading = document.createElement('h4'); heading.textContent = `第 ${edit.slideIndex + 1} 页`
          const items = document.createElement('ul'); items.className = 'ai-proposal-changes'
          page.append(heading, items); changes.append(page); pages.set(edit.slideIndex, items)
        }
        const existing = deck.slides[edit.slideIndex]?.elements.find(element => element.id === edit.elementId)
        const current = edits.get(editKey(edit.slideIndex, edit.elementId))
        const item = document.createElement('li')
        const title = document.createElement('h4'); title.textContent = `第 ${edit.slideIndex + 1} 页 · ${existing?.name || existing?.text.split('\n')[0] || edit.elementId}`
        item.append(title)
        if (edit.text !== undefined) {
          const comparison = document.createElement('div'); renderAITextPreview(current?.text ?? existing?.text ?? '', edit.text, comparison); item.append(comparison)
        }
        if (edit.geometry) {
          const position = document.createElement('p'); const { x, y, width, height } = edit.geometry
          position.textContent = `位置与大小：X ${x}，Y ${y}，宽 ${width}，高 ${height}`; item.append(position)
        }
        pages.get(edit.slideIndex)!.append(item)
      }
      const add = (text: string) => { const item = document.createElement('li'); item.textContent = text; changes.append(item) }
      if (proposal.order.some((slide, index) => order[index] !== slide)) add(`页面顺序：${order.map(index => index + 1).join(' → ')} → 调整为 ${proposal.order.map(index => index + 1).join(' → ')}`)
      if (proposal.theme) add(`商务主题：${{ executive: '执行汇报', clinical: '临床医疗', modern: '现代商务' }[proposal.theme]}`)
      if (!changes.childElementCount) add('没有需要应用的变化')
      target.replaceChildren(summary, changes)
    },
    locateTarget: () => {
      if (!aiTarget || !deck.slides[aiTarget.slideIndex] || deletions.has(editKey(aiTarget.slideIndex, aiTarget.elementId))) return false
      selectedSlide = aiTarget.slideIndex; selectedElement = aiTarget.elementId
      renderSlides(); renderInspector(); renderCanvas(); return true
    },
    applyProposal: async proposal => {
      aiTarget = proposal.edits[0] ?? { slideIndex: proposal.order[0] ?? selectedSlide, elementId: '' }
      undoSnapshot = { order: [...order], edits: structuredClone([...edits.values()]), ...(selectedTheme ? { theme: selectedTheme } : {}) }
      for (const edit of proposal.edits) {
        const key = editKey(edit.slideIndex, edit.elementId)
        edits.set(key, { ...edits.get(key), ...edit })
      }
      if (proposal.theme) selectedTheme = proposal.theme
      order.splice(0, order.length, ...proposal.order)
      acceptedSnapshot = JSON.stringify(draftPayload())
      refreshCanvasPreview(); renderSlides(); renderInspector(); markDirty()
    },
    undo: async () => {
      if (locked() || !undoSnapshot || JSON.stringify(draftPayload()) !== acceptedSnapshot) throw new Error('采纳后已有其他修改，无法直接撤销此候选。')
      order.splice(0, order.length, ...undoSnapshot.order)
      edits.clear()
      for (const edit of undoSnapshot.edits) edits.set(editKey(edit.slideIndex, edit.elementId), edit)
      selectedTheme = undoSnapshot.theme; undoSnapshot = undefined
      refreshCanvasPreview(); renderSlides(); renderInspector(); markDirty()
    },
  }),
})
toolbar.registerToolbarAction({ id: 'slides-ai', bar: 'context', label: 'Ask AI', disabled: () => locked() || mutationPending > 0 || !deck, run: () => aiSession.open() })
for (const [id, label, element] of [
  ['slides-structure', '页面结构', layoutSelect], ['slides-text', '新增文本', textAdd],
  ['slides-image', 'AI 配图', imagePrompt],
] as const) toolbar.registerToolbarAction({ id, label, bar: 'format', disabled: () => locked() || mutationPending > 0 || !deck,
  run: () => { if (element instanceof HTMLButtonElement) element.click(); else { element.scrollIntoView({ block: 'nearest' }); element.focus() } },
})

toolbar.registerToolbarAction({ id: 'save', element: saveButton, bar: 'public', label: '保存', disabled: () => locked() || mutationPending > 0, run: async () => {
  if (locked() || mutationPending || (!dirty && imageEdits.length === 0)) return
  saving = true
  ++previewSequence
  clearTimeout(previewTimer)
  setEditingLocked(true)
  saveButton.disabled = true
  stateLabel.textContent = '正在保存'
  try {
    const result = await request<{ revision: number; pptx?: { downloadUrl?: string }; editor?: { openUrl: string }; validation: { issues: { message: string }[] } }>('save', {
      method: 'POST',
    body: JSON.stringify(draftPayload()),
    })
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
    backgroundEdits.clear()
    textBoxEdits.splice(0, textBoxEdits.length)
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
    saveButton.disabled = savedRevision
  }
} })

async function start() {
  try {
    deck = await request<Deck>('deck')
    order.push(...deck.slides.map(slide => slide.slideIndex))
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
    }).catch(() => { canvasStatus.textContent = '画布暂不可用，显示 PDF 兼容预览；可继续使用对象面板编辑。' })
    stateLabel.textContent = '可编辑'
    statusMessage.textContent = `${deck.slides.length} 页 · 已核验 PPTX 身份`
  } catch (error) {
    stateLabel.textContent = '载入失败'
    statusMessage.textContent = error instanceof Error ? error.message : '无法载入幻灯片'
  }
}

if (root.querySelector('.slides-brand')) root.querySelector('.slides-brand')!.append(createElement(Sparkles, { width: 18, height: 18, 'aria-hidden': 'true' }))
if (root.querySelector('.download-link')) root.querySelector('.download-link')!.append(createElement(Download, { width: 16, height: 16, 'aria-hidden': 'true' }))
void start()
}

if (document.querySelector('#slides-app')) createSlidesEditorView(document.querySelector('#slides-app')!)
