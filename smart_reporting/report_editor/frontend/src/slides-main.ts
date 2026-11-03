import { createElement, ArrowDown, ArrowUp, Download, Save, Sparkles, Undo2, X } from 'lucide'
import './slides.css'

type DeckElement = { id: string; type: string; name: string; text: string; editable: boolean; geometry?: { x: number; y: number; width: number; height: number } }
type SlideTransition = 'none' | 'morph' | 'fade' | 'push' | 'wipe' | 'split' | 'circle' | 'cover' | 'pull' | 'dissolve' | 'zoom' | 'random'
type Animation = { elementId: string; effect: string; trigger: string; durationMs?: number; delayMs?: number; direction?: string }
type DeckLayout = { path: string; name: string; layoutType: string; placeholders: { type: string; idx: string; hint: string }[] }
type DeckSlide = { slideIndex: number; layoutPath?: string; masterPath?: string; themePath?: string; transition?: SlideTransition; animations?: Animation[]; elements: DeckElement[] }
type Deck = { revision: number; sha256: string; size: { cx: number; cy: number }; layouts?: DeckLayout[]; masterParts?: { partPath: string; kind: 'master' | 'layout'; name: string }[]; slides: DeckSlide[] }
type Edit = {
  slideIndex: number
  elementId: string
  text?: string
  geometry?: { x: number; y: number; width: number; height: number }
}
type BusinessTheme = 'executive' | 'clinical' | 'modern'
type AIProposal = { summary: string; edits: Edit[]; order: number[]; theme?: BusinessTheme }
type AIStatus = { editId: string; status: string; proposal?: AIProposal; error?: { message: string } }
type GeneratedImage = { candidateId: string; mediaType: string; previewDataUrl: string }
type ImageEdit = { candidateId: string; slideIndex: number; geometry: { x: number; y: number; width: number; height: number } }
type AnimationEffect = 'appear' | 'fade' | 'flyIn' | 'wipe' | 'wipeDown' | 'splitIn' | 'bounce' | 'flipIn' | 'zoom' | 'pulse' | 'spin' | 'grow' | 'teeter' | 'disappear' | 'fadeOut' | 'flyOut' | 'wipeOut' | 'shrink' | 'zoomOut' | 'motionPath'
type AnimationTrigger = 'onClick' | 'withPrev' | 'afterPrev'
type AnimationEdit = { slideIndex: number; elementId: string; effect: AnimationEffect; trigger: AnimationTrigger; durationMs: number; delayMs: number; direction?: string }

export function createSlidesEditorView(host: HTMLElement, sharedShell?: {
  save?: HTMLButtonElement
  download?: HTMLAnchorElement
}) {
const root = host
const basePath = location.pathname.replace(/\/$/, '')
const embedded = Boolean(sharedShell)
const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const csrfToken = document.cookie.split('; ').find(value => value.startsWith('report_slides_csrf='))?.split('=', 2)[1] ?? ''
  const response = await fetch(`${basePath}/api/${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.method === 'POST' ? { 'X-CSRF-Token': decodeURIComponent(csrfToken) } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail?.message ?? `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}

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
    <section class="slides-stage" aria-label="幻灯片预览"><iframe class="preview-frame" title="幻灯片预览"></iframe></section>
    <aside class="slides-inspector" aria-label="对象编辑"><div class="inspector-heading">对象</div><div class="slide-lineage"><span class="lineage-label">母版</span><span class="slide-master"></span><span class="lineage-label">版式</span><select id="layout-select" aria-label="当前页版式"></select></div><label class="field-label" for="object-select">可编辑对象</label><select id="object-select"></select><label class="field-label" for="object-text">文字</label><textarea id="object-text" rows="7" spellcheck="false"></textarea><div class="geometry-heading">位置与大小</div><div class="geometry-grid"><label>X <input name="x" type="number" min="0" step="1"></label><label>Y <input name="y" type="number" min="0" step="1"></label><label>宽 <input name="width" type="number" min="1" step="1"></label><label>高 <input name="height" type="number" min="1" step="1"></label></div><label class="field-label" for="theme-select">商务主题</label><select id="theme-select"><option value="">保持当前主题</option><option value="executive">执行汇报</option><option value="clinical">临床医疗</option><option value="modern">现代商务</option></select><label class="field-label" for="transition-select">页面转场</label><select id="transition-select"><option value="none">无</option><option value="fade">淡化</option><option value="push">推进</option><option value="wipe">擦除</option><option value="split">分割</option><option value="circle">圆形</option><option value="cover">覆盖</option><option value="pull">拉伸</option><option value="dissolve">溶解</option><option value="zoom">缩放</option><option value="morph">变形</option><option value="random">随机</option></select><div class="animation-controls"><label class="field-label" for="animation-effect">动画效果</label><select id="animation-effect"><option value="fade">淡化</option><option value="appear">出现</option><option value="flyIn">飞入</option><option value="wipe">擦除</option><option value="wipeDown">向下擦除</option><option value="splitIn">分割进入</option><option value="bounce">弹跳</option><option value="flipIn">翻转进入</option><option value="zoom">缩放进入</option><option value="pulse">脉冲</option><option value="spin">旋转</option><option value="grow">放大</option><option value="teeter">摇摆</option><option value="disappear">消失</option><option value="fadeOut">淡出</option><option value="flyOut">飞出</option><option value="wipeOut">擦除退出</option><option value="shrink">缩小退出</option><option value="zoomOut">缩小退出</option><option value="motionPath">路径</option></select><label class="field-label" for="animation-trigger">触发方式</label><select id="animation-trigger"><option value="onClick">点击时</option><option value="withPrev">与上一动画同时</option><option value="afterPrev">上一动画后</option></select><div class="animation-timing"><label>持续 <input id="animation-duration" type="number" min="1" max="120000" step="50" value="500"> ms</label><label>延迟 <input id="animation-delay" type="number" min="0" max="120000" step="50" value="0"> ms</label></div><button class="animation-add" type="button">添加对象动画</button></div><p class="animation-state"></p><p class="object-note">未编辑对象会保留在原始 PPTX 中。</p></aside>
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
const order: number[] = []
const edits = new Map<string, Edit>()
const imageEdits: ImageEdit[] = []
const animationEdits: AnimationEdit[] = []
const transitionEdits = new Map<number, SlideTransition>()
const layoutEdits = new Map<number, string>()
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

const flatText = (slide: DeckSlide) => slide.elements.find(item => item.text.trim())?.text.split('\n')[0] || `第 ${slide.slideIndex + 1} 页`
const editKey = (slideIndex: number, elementId: string) => `${slideIndex}:${elementId}`
const currentElement = () => deck.slides[selectedSlide]?.elements.find(item => item.id === selectedElement)
const currentGeometryInputs = () => [...root.querySelectorAll<HTMLInputElement>('.geometry-grid input')]

function markDirty() {
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
  preview.src = `${basePath}/api/preview.pdf#page=${selectedSlide + 1}&toolbar=0&navpanes=0`
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

function renderInspector() {
  const elements = deck.slides[selectedSlide]!.elements.filter(item => item.editable && item.text.trim())
  select.replaceChildren(...elements.map(item => {
    const option = document.createElement('option')
    option.value = item.id
    option.textContent = item.name || item.text.split('\n')[0]?.slice(0, 60) || item.type
    return option
  }))
  if (!elements.some(item => item.id === selectedElement)) selectedElement = elements[0]?.id ?? ''
  select.value = selectedElement
  const element = currentElement()
  textArea.disabled = !element
  textArea.value = element ? edits.get(editKey(selectedSlide, element.id))?.text ?? element.text : ''
  const box = element && (element as DeckElement & { geometry?: { x: number; y: number; width: number; height: number } }).geometry
  const geometry = box ?? { x: 0, y: 0, width: 0, height: 0 }
  for (const input of currentGeometryInputs()) input.value = String(geometry[input.name as keyof typeof geometry] ?? 0)
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
  const existingAnimation = [...(slide.animations ?? []), ...animationEdits].find(item => item.elementId === selectedElement)
  animationEffect.value = existingAnimation?.effect ?? 'fade'
  animationTrigger.value = existingAnimation?.trigger ?? 'onClick'
  animationDuration.value = String(existingAnimation?.durationMs ?? 500)
  animationDelay.value = String(existingAnimation?.delayMs ?? 0)
  animationAdd.disabled = !element
  animationState.textContent = existingAnimation ? `已有 ${existingAnimation.effect} 动画，可继续添加。` : ''
  root.querySelector('.inspector-heading')!.textContent = `对象 · 第 ${order.indexOf(selectedSlide) + 1} 页`
}

select.addEventListener('change', () => { selectedElement = select.value; renderInspector() })
textArea.addEventListener('input', () => {
  const element = currentElement()
  if (!element) return
  const edit = edits.get(editKey(selectedSlide, element.id)) ?? { slideIndex: selectedSlide, elementId: element.id }
  edit.text = textArea.value
  edits.set(editKey(selectedSlide, element.id), edit)
  undoSnapshot = undefined
  undoButton.disabled = true
  markDirty()
})
for (const input of currentGeometryInputs()) input.addEventListener('change', () => {
  const element = currentElement()
  if (!element) return
  const edit = edits.get(editKey(selectedSlide, element.id)) ?? { slideIndex: selectedSlide, elementId: element.id }
  edit.geometry = Object.fromEntries(currentGeometryInputs().map(field => [field.name, Number(field.value)])) as Edit['geometry']
  edits.set(editKey(selectedSlide, element.id), edit)
  undoSnapshot = undefined
  undoButton.disabled = true
  markDirty()
})
themeSelect.addEventListener('change', () => {
  selectedTheme = themeSelect.value ? themeSelect.value as BusinessTheme : undefined
  undoSnapshot = undefined
  undoButton.disabled = true
  markDirty()
})
transitionSelect.addEventListener('change', () => {
  transitionEdits.set(selectedSlide, transitionSelect.value as SlideTransition)
  markDirty()
})
layoutSelect.addEventListener('change', () => {
  if (!layoutSelect.value) return
  layoutEdits.set(selectedSlide, layoutSelect.value)
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

const saveButton = root.querySelector<HTMLButtonElement>('.save-button') ?? sharedShell?.save!
if (!saveButton) throw new Error('slides save action is missing')
if (root.querySelector('.save-icon')) saveButton.querySelector('.save-icon')!.append(createElement(Save, { width: 16, height: 16, 'aria-hidden': 'true' }))
undoButton.append(createElement(Undo2, { width: 17, height: 17, 'aria-hidden': 'true' }))
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
  if (!aiInstruction.value.trim() || activeAIEditId) return
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
  if (!pendingAIProposal || !pendingAIEditId) return
  aiAccept.disabled = true
  try {
    await request(`ai/${encodeURIComponent(pendingAIEditId)}/accept`, { method: 'POST' })
    undoSnapshot = { order: [...order], edits: [...edits.values()].map(edit => ({ ...edit })), ...(selectedTheme ? { theme: selectedTheme } : {}) }
    for (const edit of pendingAIProposal.edits) {
      const key = editKey(edit.slideIndex, edit.elementId)
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
    renderSlides()
    renderInspector()
    markDirty()
  } catch (error) {
    aiAccept.disabled = false
    aiResult.textContent = error instanceof Error ? error.message : '采纳失败'
  }
})

saveButton.addEventListener('click', async () => {
  if ((!dirty && imageEdits.length === 0) || saveButton.disabled) return
  saveButton.disabled = true
  stateLabel.textContent = '正在保存'
  try {
    const result = await request<{ revision: number; pptx?: { downloadUrl?: string }; editor?: { openUrl: string }; validation: { issues: { message: string }[] } }>('save', {
      method: 'POST',
    body: JSON.stringify({ expectedSha256: deck.sha256, edits: [...edits.values()], order, ...(selectedTheme ? { theme: selectedTheme } : {}), ...(imageEdits.length ? { imageEdits } : {}), transitions: [...transitionEdits].map(([slideIndex, kind]) => ({ slideIndex, kind })), animations: animationEdits, slideLayouts: [...layoutEdits].map(([slideIndex, layoutPath]) => ({ slideIndex, layoutPath })) }),
    })
    dirty = false
    imageEdits.splice(0, imageEdits.length)
    animationEdits.splice(0, animationEdits.length)
    transitionEdits.clear()
    layoutEdits.clear()
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
    saveButton.disabled = false
  }
})

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
