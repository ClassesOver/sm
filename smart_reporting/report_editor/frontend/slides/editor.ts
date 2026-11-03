import { ApiError, SlidesState, requestJson, safeImageSource, type ElementChanges, type Slide, type SlideElement, type SlidesDocument, type Validation, type PublicationGate } from './state'

interface ExportResult {
  pptx: { downloadUrl: string; size: number; sha256: string; expiresAt: string }
  validation: Validation
  publicationGate?: PublicationGate
}

function node<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text?: string): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag)
  if (className) element.className = className
  if (text !== undefined) element.textContent = text
  return element
}
function action(text: string, click: () => void, className = ''): HTMLButtonElement {
  const button = node('button', className, text)
  button.type = 'button'
  button.addEventListener('click', click)
  return button
}
const supportedShapes = new Set(['rect', 'rectangle', 'roundRect', 'roundRectangle', 'ellipse', 'line'])
function editable(element: SlideElement): boolean {
  return element.editable !== false && (element.kind !== 'shape' || supportedShapes.has(element.shape ?? ''))
}
function color(value: string | undefined, fallback: string): string {
  return value && /^#[0-9a-f]{6}$/i.test(value) ? value : fallback
}
function issueText(issue: unknown): string {
  if (typeof issue === 'string') return issue
  if (issue && typeof issue === 'object') {
    const entry = issue as Record<string, unknown>
    for (const key of ['message', 'reason', 'detail', 'code']) if (typeof entry[key] === 'string') return entry[key] as string
  }
  return JSON.stringify(issue) ?? '未知告警'
}
function downloadSource(value: string): string | undefined {
  try {
    const url = new URL(value, location.origin)
    return url.origin === location.origin && ['http:', 'https:'].includes(url.protocol) ? url.href : undefined
  } catch { return undefined }
}

function drawElement(element: SlideElement, scale: number, fontScale = 4 / 3): HTMLElement {
  const view = node('div', `slide-element slide-element-${element.kind}`)
  position(view, element, scale)
  if (element.kind === 'text') {
    view.textContent = element.text ?? ''
    view.style.fontSize = `${(element.fontSize ?? 24) * fontScale * scale}px`
    view.style.fontFamily = element.fontFamily || 'Microsoft YaHei, sans-serif'
    view.style.color = color(element.color, '#1b2a41')
    view.style.fontWeight = element.bold ? '700' : '400'
    view.style.lineHeight = String(element.lineSpacing ?? 1.2)
    if (element.fill) view.style.backgroundColor = color(element.fill, 'transparent')
  } else if (element.kind === 'image') {
    const source = safeImageSource(element.imageDataUrl)
    if (source) {
      const image = node('img')
      image.src = source
      image.alt = '幻灯片图片'
      image.draggable = false
      view.append(image)
    } else view.append(node('span', 'element-placeholder', '图片无法预览'))
  } else if (supportedShapes.has(element.shape ?? '')) {
    if (element.shape === 'line') view.style.borderBottom = `${Math.max(1, scale)}px solid ${color(element.fill, '#5b6b7a')}`
    else view.style.backgroundColor = color(element.fill, '#d8e3ed')
    if (element.shape === 'ellipse') view.style.borderRadius = '50%'
    if (element.shape?.startsWith('round')) view.style.borderRadius = `${12 * scale}px`
  } else view.append(node('span', 'element-placeholder', '复杂对象 · 保留原样'))
  return view
}
function position(view: HTMLElement, element: SlideElement, scale: number): void {
  view.style.left = `${element.x * scale}px`
  view.style.top = `${element.y * scale}px`
  view.style.width = `${element.width * scale}px`
  view.style.height = `${element.height * scale}px`
  view.style.transform = `rotate(${element.rotation ?? 0}deg)`
}

export function mountEditor(root: HTMLElement, initialDocument: SlidesDocument, endpoint: string, send: typeof fetch = fetch): void {
  const state = new SlidesState(initialDocument)
  let activeSlide = state.document.slides[0]?.index ?? 0
  let selectedId = ''
  let taskBusy = false
  let scale = 0.6
  let exported: ExportResult | undefined
  let warningSource: { validation?: Validation; publicationGate?: PublicationGate } = initialDocument
  let statusMessage = ''
  let statusError = false

  const shell = node('div', 'slides-app')
  const header = node('header', 'slides-header')
  const identity = node('div', 'slides-identity')
  identity.append(node('p', 'eyebrow', 'SMART REPORTING'), node('h1', '', '幻灯片编辑器'))
  const saveStatus = node('span', 'save-status')
  saveStatus.setAttribute('role', 'status')
  const saveButton = action('保存草稿', () => { void persist(false) })
  const exportButton = action('保存并导出 PPTX', () => { void persist(true) }, 'primary')
  const topActions = node('div', 'header-actions')
  topActions.append(saveStatus, saveButton, exportButton)
  header.append(identity, topActions)
  const message = node('div', 'editor-message')
  message.setAttribute('role', 'status')
  const warnings = node('div', 'editor-warnings')
  const layout = node('div', 'slides-layout')
  const sidebar = node('nav', 'slides-sidebar')
  sidebar.setAttribute('aria-label', '幻灯片页面')
  const sidebarHeading = node('div', 'sidebar-heading')
  const thumbs = node('div', 'slide-thumbnails')
  sidebar.append(sidebarHeading, thumbs)
  const work = node('main', 'slides-workspace')
  const toolbar = node('div', 'slides-toolbar')
  const pageLabel = node('span', 'page-label')
  toolbar.append(pageLabel, action('新增文本', () => addText(false)), action('新增水印', () => addText(true)))
  const stageArea = node('div', 'stage-area')
  const stage = node('div', 'slide-canvas')
  stage.setAttribute('aria-label', '当前幻灯片画布')
  stage.addEventListener('click', (event) => { if (event.target === stage && !taskBusy) { selectedId = ''; renderCanvas(); renderInspector() } })
  stageArea.append(stage)
  const help = node('p', 'canvas-help', '选择对象后拖动移动，拖动右下角调整大小；精确尺寸与旋转可在右侧修改。复杂对象保留原样。')
  work.append(toolbar, stageArea, help)
  const inspector = node('aside', 'slides-inspector')
  inspector.setAttribute('aria-label', '幻灯片与对象属性')
  layout.append(sidebar, work, inspector)
  const download = node('div', 'download-result')
  shell.append(header, message, warnings, download, layout)
  root.replaceChildren(shell)

  function currentSlide(): Slide | undefined { return state.document.slides.find((page) => page.index === activeSlide) }
  function selection(): SlideElement | undefined { return state.element(activeSlide, selectedId) }
  function invalidFields(): boolean { return [...inspector.querySelectorAll<HTMLInputElement>('input')].some((input) => !input.validity.valid) }
  function dirty(): boolean { return state.dirty || invalidFields() }

  function renderStatus(): void {
    saveStatus.textContent = taskBusy ? '正在处理…' : dirty() ? '有未保存修改' : '草稿已保存'
    saveStatus.classList.toggle('dirty', dirty())
    saveButton.disabled = taskBusy || !dirty()
    exportButton.disabled = taskBusy
    for (const button of toolbar.querySelectorAll('button')) button.disabled = taskBusy
    for (const button of thumbs.querySelectorAll('button')) button.disabled = taskBusy
    for (const control of inspector.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLButtonElement>('input, textarea, button, select')) {
      control.disabled = taskBusy || control.dataset.readonly === 'true'
    }
    message.textContent = statusMessage
    message.classList.toggle('is-error', statusError)
    message.hidden = !statusMessage
    stage.classList.toggle('is-busy', taskBusy)
    shell.setAttribute('aria-busy', String(taskBusy))
  }
  function edited(): void {
    exported = undefined
    download.replaceChildren()
    statusMessage = ''
    statusError = false
    renderStatus()
    renderCanvas()
    renderThumbs()
  }
  function renderWarnings(): void {
    warnings.replaceChildren()
    const groups: (Validation & { title: string })[] = []
    if (warningSource.validation) groups.push({ ...warningSource.validation, title: '验收' })
    if (warningSource.publicationGate) groups.push({
      ok: warningSource.publicationGate.formalReleaseAllowed,
      issues: warningSource.publicationGate.issues, title: '发布检查',
    })
    for (const result of groups) {
      const issues = result.issues ?? []
      if (result.ok && issues.length === 0) continue
      const group = node('details')
      group.open = !result.ok
      group.append(node('summary', '', result.ok ? `${result.title}提示（${issues.length}）` : `${result.title}未通过 · 仍可下载已生成的 PPTX`))
      const list = node('ul')
      for (const issue of issues) list.append(node('li', '', issueText(issue)))
      if (!issues.length) list.append(node('li', '', '服务端未提供具体原因。'))
      group.append(list)
      warnings.append(group)
    }
    warnings.hidden = warnings.childElementCount === 0
  }
  function renderThumbs(): void {
    thumbs.replaceChildren()
    sidebarHeading.textContent = `幻灯片 · ${state.document.slides.length} 页`
    for (const page of state.document.slides) {
      const item = action('', () => {
        if (taskBusy) return
        activeSlide = page.index
        selectedId = ''
        renderCanvas(); renderThumbs(); renderInspector(); renderStatus()
      }, 'slide-thumbnail')
      item.setAttribute('aria-label', `第 ${page.index + 1} 页：${page.title}`)
      item.setAttribute('aria-current', String(page.index === activeSlide))
      item.disabled = taskBusy
      const preview = node('div', 'thumbnail-preview')
      const thumbScale = 164 / state.document.width
      preview.style.width = '164px'
      preview.style.height = `${state.document.height * thumbScale}px`
      preview.style.backgroundColor = color(page.background, '#ffffff')
      preview.setAttribute('aria-hidden', 'true')
      for (const element of page.elements) preview.append(drawElement(element, thumbScale, state.document.fontScale))
      item.append(preview, node('span', 'thumbnail-title', `${page.index + 1}. ${page.title || '无标题'}`))
      thumbs.append(item)
    }
  }
  function renderCanvas(): void {
    const page = currentSlide()
    stage.replaceChildren()
    if (!page) { pageLabel.textContent = '暂无幻灯片'; return }
    pageLabel.textContent = `第 ${page.index + 1} / ${state.document.slides.length} 页`
    const available = stageArea.clientWidth > 0 ? stageArea.clientWidth - 48 : 800
    scale = Math.max(0.15, Math.min(1, available / state.document.width))
    stage.style.width = `${state.document.width * scale}px`
    stage.style.height = `${state.document.height * scale}px`
    stage.style.backgroundColor = color(page.background, '#ffffff')
    for (const element of page.elements) {
      const view = drawElement(element, scale, state.document.fontScale)
      view.dataset.elementId = element.id
      view.setAttribute('role', 'button')
      view.tabIndex = 0
      view.setAttribute('aria-label', `${element.kind === 'text' ? (element.text?.slice(0, 40) || '空文本') : element.kind === 'image' ? '图片' : '形状'}${editable(element) ? '' : '（只读）'}`)
      view.classList.toggle('is-selected', element.id === selectedId)
      view.classList.toggle('is-readonly', !editable(element))
      view.addEventListener('click', (event) => { event.stopPropagation(); select(element.id) })
      view.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(element.id) } })
      view.addEventListener('pointerdown', (event) => startDrag(event, element, false))
      if (element.id === selectedId && editable(element)) {
        const resize = node('button', 'resize-handle')
        resize.type = 'button'
        resize.setAttribute('aria-label', '拖动调整大小')
        resize.addEventListener('pointerdown', (event) => startDrag(event, element, true))
        view.append(resize)
      }
      stage.append(view)
    }
  }
  function select(id: string): void {
    if (taskBusy || selectedId === id) return
    selectedId = id
    renderCanvas(); renderInspector(); renderStatus()
  }
  function startDrag(event: PointerEvent, element: SlideElement, resize: boolean): void {
    if (taskBusy || !editable(element) || event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    selectedId = element.id
    renderCanvas(); renderInspector()
    const start = { x: event.clientX, y: event.clientY, left: element.x, top: element.y, width: element.width, height: element.height }
    const dragScale = scale
    let moved = false
    const move = (next: PointerEvent) => {
      if (taskBusy) return
      const dx = (next.clientX - start.x) / dragScale
      const dy = (next.clientY - start.y) / dragScale
      if (Math.abs(dx) + Math.abs(dy) < 1) return
      moved = true
      const radians = (element.rotation ?? 0) * Math.PI / 180
      const changes = resize ? { width: Math.max(8, Math.round(start.width + dx * Math.cos(radians) + dy * Math.sin(radians))), height: Math.max(8, Math.round(start.height - dx * Math.sin(radians) + dy * Math.cos(radians))) } : { x: Math.round(start.left + dx), y: Math.round(start.top + dy) }
      state.update(activeSlide, element.id, changes)
      renderCanvas(); renderStatus()
    }
    const finish = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
      if (moved) { edited(); renderInspector() }
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
  }
  function field(labelText: string, input: HTMLElement): HTMLElement {
    const label = node('label', 'property-field')
    label.append(node('span', '', labelText), input)
    return label
  }
  function numberField(form: HTMLElement, labelText: string, key: keyof ElementChanges, value: number, min: number, max: number, step = 'any'): void {
    const input = node('input')
    input.type = 'number'; input.value = String(value); input.min = String(min); input.max = String(max); input.step = step; input.required = true
    input.addEventListener('input', () => {
      if (input.validity.valid && Number.isFinite(input.valueAsNumber)) {
        state.update(activeSlide, selectedId, { [key]: input.valueAsNumber })
        edited()
      } else renderStatus()
    })
    form.append(field(labelText, input))
  }
  function renderInspector(): void {
    inspector.replaceChildren(node('h2', '', '页面设置'))
    const page = currentSlide()
    if (!page) return
    const background = node('input')
    background.type = 'color'; background.value = color(page.background, '#ffffff')
    background.addEventListener('input', () => { state.background(activeSlide, background.value); edited() })
    inspector.append(field('页面背景', background))
    const element = selection()
    inspector.append(node('hr'), node('h2', '', element ? '对象属性' : '选择对象'))
    if (!element) { inspector.append(node('p', 'muted', '点击画布中的文字、图片或形状查看属性。')); return }
    if (!editable(element)) { inspector.append(node('p', 'readonly-note', '此对象为只读，导出时保留原始内容。')); return }
    const form = node('form', 'property-form')
    form.addEventListener('submit', (event) => event.preventDefault())
    if (element.kind === 'text') {
      const text = node('textarea')
      text.rows = 5; text.value = element.text ?? ''
      text.addEventListener('input', () => { state.update(activeSlide, selectedId, { text: text.value }); edited() })
      form.append(field('文案', text))
      const font = node('input')
      font.type = 'text'; font.value = element.fontFamily?.trim() || 'Microsoft YaHei'; font.maxLength = 100; font.required = true
      font.addEventListener('input', () => {
        const value = font.value.trim()
        font.setCustomValidity(value ? '' : '请输入字体名称。')
        if (!font.validity.valid) { renderStatus(); return }
        state.update(activeSlide, selectedId, { fontFamily: value }); edited()
      })
      form.append(field('字体', font), node('p', 'field-hint', '字体显示取决于当前设备；导出保留字体名称。'))
      const typography = node('div', 'property-grid')
      numberField(typography, '字号（pt）', 'fontSize', element.fontSize ?? 24, 6, 144)
      numberField(typography, '行距（倍）', 'lineSpacing', element.lineSpacing ?? 1.2, 1, 3)
      const foreground = node('input')
      foreground.type = 'color'; foreground.value = color(element.color, '#1b2a41')
      foreground.addEventListener('input', () => { state.update(activeSlide, selectedId, { color: foreground.value }); edited() })
      const bold = node('input')
      bold.type = 'checkbox'; bold.checked = !!element.bold
      bold.addEventListener('change', () => { state.update(activeSlide, selectedId, { bold: bold.checked }); edited() })
      typography.append(field('文字颜色', foreground), field('加粗', bold))
      form.append(typography)
    }
    if (element.kind === 'shape') {
      const fill = node('input')
      fill.type = 'color'; fill.value = color(element.fill, element.shape === 'line' ? '#5b6b7a' : '#d8e3ed')
      fill.addEventListener('input', () => { state.update(activeSlide, selectedId, { fill: fill.value }); edited() })
      form.append(field(element.shape === 'line' ? '线条颜色' : '填充颜色', fill))
    }
    const geometry = node('div', 'property-grid')
    numberField(geometry, 'X 位置', 'x', element.x, -state.document.width * 2, state.document.width * 2)
    numberField(geometry, 'Y 位置', 'y', element.y, -state.document.height * 2, state.document.height * 2)
    numberField(geometry, '宽度', 'width', element.width, 1, state.document.width * 4)
    numberField(geometry, '高度', 'height', element.height, 1, state.document.height * 4)
    numberField(geometry, '旋转（度）', 'rotation', element.rotation ?? 0, -360, 360)
    form.append(geometry, action('删除对象', () => { if (!taskBusy) { state.delete(activeSlide, selectedId); selectedId = ''; edited(); renderInspector() } }, 'danger'))
    inspector.append(form)
  }
  function addText(watermark: boolean): void {
    if (taskBusy || !currentSlide()) return
    selectedId = state.addText(activeSlide, { text: watermark ? '内部资料' : '请输入文本', x: state.document.width * (watermark ? 0.2 : 0.1), y: state.document.height * (watermark ? 0.4 : 0.2), width: state.document.width * 0.6, height: watermark ? 120 : 90, fontSize: watermark ? 64 : 28, fontFamily: 'Microsoft YaHei', color: watermark ? '#dce3eb' : '#1b2a41', rotation: watermark ? -25 : 0, lineSpacing: 1.2 })
    edited(); renderInspector()
  }
  function csrfHeaders(): HeadersInit { return { 'x-csrf-token': state.document.csrfToken } }
  async function persist(shouldExport: boolean): Promise<void> {
    if (taskBusy) return
    const form = inspector.querySelector('form')
    if (form && !form.reportValidity()) return
    taskBusy = true
    statusError = false
    statusMessage = shouldExport ? '正在保存草稿并生成可编辑 PPTX…' : '正在保存草稿…'
    renderStatus()
    try {
      await state.save((body) => requestJson<SlidesDocument>(`${endpoint}/draft`, { method: 'PUT', headers: csrfHeaders(), body: JSON.stringify(body) }, send))
      selectedId = ''
      warningSource = state.document
      if (shouldExport) {
        exported = await requestJson<ExportResult>(`${endpoint}/export`, { method: 'POST', headers: csrfHeaders(), body: JSON.stringify({ expectedSha256: state.document.sha256 }) }, send)
        warningSource = exported
        const source = downloadSource(exported.pptx.downloadUrl)
        if (!source) throw new Error('导出已完成，但下载地址无效，请重试。')
        const link = node('a', 'primary download-link', '下载可编辑 PPTX')
        link.href = source; link.download = `${state.document.reportId}.pptx`
        download.replaceChildren(node('span', '', 'PPTX 已生成。'), link, node('span', 'muted', `下载链接有效期至 ${exported.pptx.expiresAt}`))
        const failedChecks = [!exported.validation.ok ? '验收' : '', exported.publicationGate?.formalReleaseAllowed === false ? '发布检查' : ''].filter(Boolean)
        statusMessage = failedChecks.length ? `PPTX 已生成，${failedChecks.join('、')}未通过；请查看告警后下载。` : 'PPTX 已生成，可下载并继续编辑。'
      } else statusMessage = '草稿已保存。'
      renderThumbs(); renderCanvas(); renderInspector(); renderWarnings()
    } catch (error) {
      statusError = true
      const detail = error instanceof Error ? error.message : '请求失败，请重试。'
      statusMessage = error instanceof ApiError && error.status === 409 ? `版本冲突：${detail}。本地修改已保留，请先复制需保留的文案，再重新打开页面。` : `${detail} 本地修改已保留，可重试。`
    } finally {
      taskBusy = false
      renderStatus()
    }
  }

  window.addEventListener('beforeunload', (event) => {
    if (root.isConnected && (dirty() || taskBusy)) { event.preventDefault(); event.returnValue = '' }
  })
  window.addEventListener('keydown', (event) => {
    if (!root.isConnected) return
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); void persist(false) }
    const target = event.target as HTMLElement | null
    if ((event.key === 'Delete' || event.key === 'Backspace') && selectedId && !taskBusy && !target?.closest('input, textarea, select, [contenteditable]')) {
      const element = selection()
      if (element && editable(element)) { event.preventDefault(); state.delete(activeSlide, selectedId); selectedId = ''; edited(); renderInspector() }
    }
  })
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => renderCanvas()).observe(stageArea)
  renderThumbs(); renderCanvas(); renderInspector(); renderWarnings(); renderStatus()
}
