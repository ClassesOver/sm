import { renderEditorLayoutProvenance } from './editor-layout-provenance'
import { createModal } from './modal'
import { ReportEditorApiError } from './api'
import { applyCoverPreset, clampCoverBox, coverText } from './design-geometry'
import { readStorage, removeStorage, writeStorage } from './storage'
import type { ReportEditorClient } from './api'
import type { CoverRole, DesignDocument, DesignTemplate, ReportDesign, TextStyle, TypographyRole } from './design-types'
import './design.css'

type DesignClient = Pick<ReportEditorClient, 'saveDesign' | 'design' | 'designTemplates' | 'saveDesignTemplate' | 'deleteDesignTemplate' | 'startDesignPreview' | 'designPreview' | 'designPreviewUrl'>
interface Options {
  root: HTMLElement; editor: HTMLElement; basePath: string; initial: DesignDocument; client: DesignClient
  saveMarkdown(): Promise<string>; getMarkdown(): string; pollMs?: number; sourcesEnabled?: boolean
}
const roles: CoverRole[] = ['title', 'period', 'signature']
const labels = { title: '标题', period: '期间', signature: '落款' }
const typeRoles: TypographyRole[] = ['body', 'h1', 'h2', 'h3', 'table', 'caption']
const typeLabels = { body: '正文', h1: '一级标题', h2: '二级标题', h3: '三级标题', table: '表格', caption: '图注' }
const fonts = { sans: '"Noto Sans CJK SC", "Microsoft YaHei", sans-serif', serif: '"Noto Serif CJK SC", "Songti SC", serif' }
const copy = <T>(value: T): T => structuredClone(value)
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export function applyDesignTypography(editor: HTMLElement, design: ReportDesign) {
  for (const role of typeRoles) for (const [key, value] of Object.entries(design.typography[role])) {
    editor.style.setProperty(`--design-${role}-${key.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`, key === 'font' ? fonts[value as 'sans' | 'serif'] : key === 'bold' ? (value ? '700' : '400') : ['size', 'spaceBefore', 'spaceAfter', 'indent'].includes(key) ? `${value}pt` : String(value))
  }
  editor.classList.add('has-report-design')
}

export function createDesignPanel(options: Options) {
  let design = copy(options.initial.design)
  let saved = copy(design)
  let hash = options.initial.designSha256
  let context = options.initial.documentContext
  let selected: CoverRole = 'title'
  let typeRole: TypographyRole = 'body'
  let tab = 'cover'
  let timer: number | undefined
  let saving: Promise<void> | null = null
  let conflict = false
  let destroyed = false
  let history: ReportDesign[] = []
  let future: ReportDesign[] = []
  let templates: DesignTemplate[] = []
  let previewMarkdown: string | null = null
  let previewDesign: ReportDesign | null = null
  let previewing = false
  let note = ''
  const cacheKey = `smart-reporting-editor:design:v1:${options.basePath}`
  const modal = createModal({
    root: options.root, overlayClass: 'report-design-panel', cardClass: 'report-design-card', closeLabel: '关闭报告设计', labelledBy: 'report-design-title',
    content: `<header class="design-header"><div><h2 id="report-design-title">报告设计</h2><p>调整封面、水印与正文样式，设计自动保存</p></div><span class="design-save-status" role="status" aria-live="polite"></span></header>
      <div class="design-alert" role="status" hidden></div>
      <div class="design-conflict" hidden><p>报告设计已在其他页面更新。本地草稿已保留，请选择处理方式。</p><button type="button" data-design-action="reload">载入远端设计</button><button type="button" data-design-action="retry-local">保留本地并重新保存</button></div>
      <div class="design-recovery" hidden><span>发现此报告的未保存设计草稿。</span><button type="button" data-design-action="recover">恢复本地草稿</button><button type="button" data-design-action="discard-recovery">忽略草稿</button></div>
      <nav class="design-tabs" aria-label="设计分类"><button type="button" data-design-tab="cover">封面</button><button type="button" data-design-tab="watermark">水印</button><button type="button" data-design-tab="typography">正文样式</button><button type="button" data-design-tab="templates">个人模板</button></nav>
      <div class="design-workspace"><section class="design-controls" aria-label="设计属性"></section><section class="design-preview-area" aria-label="即时设计预览"><div class="design-canvas-toolbar"><span>A4 · 210 × 297 mm</span><button type="button" data-design-action="undo">撤销</button><button type="button" data-design-action="redo">重做</button></div><div class="design-cover-page" aria-label="A4 封面画布"><div class="design-cover-watermark" aria-hidden="true"></div></div><div class="design-type-sample"><h1>一、经营情况分析</h1><h2>1.1 核心指标</h2><h3>指标变化与趋势</h3><p>报告正文样式预览。业务事实与来源引用保持原有内容，设计仅调整展示方式。</p><table><thead><tr><th>指标</th><th>本期</th></tr></thead><tbody><tr><td>示例指标</td><td>123.45</td></tr></tbody></table><figcaption>图 1 · 趋势说明示例</figcaption><div class="design-body-watermark" aria-hidden="true"></div></div><p class="design-preview-hint">拖动文字框移动，右下角调整大小；方向键微调，Shift 加速。即时预览供排版参考，分页以 PDF 为准。</p></section></div>
      <footer class="design-footer"><div class="design-footer-tools"><button type="button" data-design-action="retry">立即保存 / 重试</button><button type="button" data-design-action="preview">生成 PDF 预览</button><a data-design-pdf hidden target="_blank" rel="noopener">打开 PDF 预览</a><span data-design-preview-status role="status"></span></div><div data-design-provenance></div><label class="design-note">版本备注<input name="design.note" maxlength="200" placeholder="例如：复核后发布"></label></footer>`,
  })
  const dialog = modal.overlay
  const controls = dialog.querySelector<HTMLElement>('.design-controls')!
  const page = dialog.querySelector<HTMLElement>('.design-cover-page')!
  const sample = dialog.querySelector<HTMLElement>('.design-type-sample')!
  const status = dialog.querySelector<HTMLElement>('.design-save-status')!
  const alert = dialog.querySelector<HTMLElement>('.design-alert')!
  const conflictBox = dialog.querySelector<HTMLElement>('.design-conflict')!
  const recovery = dialog.querySelector<HTMLElement>('.design-recovery')!
  const previewStatus = dialog.querySelector<HTMLElement>('[data-design-preview-status]')!
  const provenanceHost = dialog.querySelector<HTMLElement>('[data-design-provenance]')!
  const pdfLink = dialog.querySelector<HTMLAnchorElement>('[data-design-pdf]')!
  const blocks = new Map<CoverRole, HTMLDivElement>()
  for (const role of roles) {
    const block = document.createElement('div')
    block.className = 'design-cover-block'
    block.dataset.coverBlock = role
    block.tabIndex = 0
    block.setAttribute('role', 'button')
    block.setAttribute('aria-label', `${labels[role]}文字框，使用方向键移动`)
    const text = document.createElement('span')
    text.className = 'design-cover-text'
    const resize = document.createElement('span')
    resize.className = 'design-resize-handle'
    resize.title = '拖动调整大小'
    block.append(text, resize)
    block.addEventListener('click', () => select(role))
    block.addEventListener('keydown', event => {
      const delta: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }
      const direction = delta[event.key]
      if (!direction) return
      event.preventDefault()
      selected = role
      const step = event.shiftKey ? 5 : 1
      change(next => { next.cover[role] = clampCoverBox({ ...next.cover[role], x: next.cover[role].x + direction[0] * step, y: next.cover[role].y + direction[1] * step }) })
      renderControls()
    })
    block.addEventListener('pointerdown', event => {
      if (event.button !== 0) return
      event.preventDefault()
      select(role)
      block.focus()
      const original = copy(design)
      const origin = { x: event.clientX, y: event.clientY }
      const resizing = event.target === resize
      const pxPerMm = (page.getBoundingClientRect().width || 420) / 210
      block.setPointerCapture?.(event.pointerId)
      const move = (pointer: PointerEvent) => {
        const dx = (pointer.clientX - origin.x) / pxPerMm
        const dy = (pointer.clientY - origin.y) / pxPerMm
        const box = original.cover[role]
        design.cover[role] = clampCoverBox(resizing ? { ...box, width: Math.min(210 - box.x, box.width + dx), height: Math.min(297 - box.y, box.height + dy) } : { ...box, x: box.x + dx, y: box.y + dy })
        render()
      }
      const end = () => {
        block.removeEventListener('pointermove', move)
        block.removeEventListener('pointerup', end)
        block.removeEventListener('pointercancel', end)
        if (!same(original, design)) { history.push(original); future = []; changed() }
        renderControls()
      }
      block.addEventListener('pointermove', move)
      block.addEventListener('pointerup', end)
      block.addEventListener('pointercancel', end)
    })
    blocks.set(role, block)
    page.append(block)
  }

  function showError(message: string) { alert.hidden = false; alert.textContent = message }
  function select(role: CoverRole) { selected = role; renderControls(); render() }
  function cache() { writeStorage(cacheKey, JSON.stringify({ design, expectedDesignSha256: hash })) }
  function dirty() { return !same(design, saved) }
  function previewStale() { return previewDesign !== null && (!same(design, previewDesign) || options.getMarkdown() !== previewMarkdown) }
  function changed() {
    cache()
    status.textContent = dirty() ? '设计有未保存更改' : '设计已保存'
    status.dataset.state = dirty() ? 'dirty' : 'saved'
    window.clearTimeout(timer)
    if (dirty() && !conflict) timer = window.setTimeout(() => { void flush().catch(() => undefined) }, 700)
    render()
  }
  function change(update: (next: ReportDesign) => void) {
    const next = copy(design)
    update(next)
    if (same(next, design)) return
    history.push(copy(design))
    if (history.length > 60) history.shift()
    future = []
    design = next
    changed()
  }
  async function flush(): Promise<void> {
    window.clearTimeout(timer)
    if (conflict) throw new ReportEditorApiError(409, 'report_editor_design_conflict')
    if (saving) { await saving; if (dirty()) return flush(); return }
    if (!dirty()) return
    const draft = copy(design)
    const expected = hash
    status.textContent = '设计保存中…'
    status.dataset.state = 'saving'
    saving = options.client.saveDesign(draft, expected).then(result => {
      saved = copy(result.design)
      hash = result.designSha256
      context = result.documentContext
      if (same(design, draft)) design = copy(result.design)
      alert.hidden = true
      if (!dirty()) removeStorage(cacheKey)
      status.textContent = dirty() ? '设计有未保存更改' : '设计已保存'
      status.dataset.state = dirty() ? 'dirty' : 'saved'
      render()
    }).catch(error => {
      cache()
      status.textContent = '设计未保存'
      status.dataset.state = 'error'
      if (error instanceof ReportEditorApiError && error.status === 409) { conflict = true; conflictBox.hidden = false }
      else showError('设计保存失败，本地草稿已保留。请检查网络后点击“立即保存 / 重试”。')
      throw error
    }).finally(() => { saving = null })
    await saving
    if (dirty()) return flush()
  }
  function reset(state: DesignDocument) {
    provenanceHost.replaceChildren()
    window.clearTimeout(timer)
    design = copy(state.design); saved = copy(design); hash = state.designSha256; context = state.documentContext
    history = []; future = []; conflict = false; conflictBox.hidden = true; alert.hidden = true
    status.textContent = '设计已保存'; status.dataset.state = 'saved'
    removeStorage(cacheKey)
    renderControls(); render()
  }

  function field(name: string, label: string, value: string | number | boolean, config: { type?: string; min?: number; max?: number; step?: number; choices?: Record<string, string>; placeholder?: string; disabled?: boolean } = {}) {
    const wrapper = document.createElement('label')
    wrapper.className = config.type === 'checkbox' ? 'design-field design-checkbox' : 'design-field'
    const title = document.createElement('span'); title.textContent = label
    let input: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
    if (config.choices) {
      input = document.createElement('select')
      for (const [key, text] of Object.entries(config.choices)) { const option = document.createElement('option'); option.value = key; option.textContent = text; input.append(option) }
    } else if (config.type === 'textarea') { input = document.createElement('textarea'); input.rows = 3; input.maxLength = 600 }
    else { input = document.createElement('input'); input.type = config.type ?? 'text'; if (input.type === 'checkbox') input.checked = Boolean(value) }
    input.name = name
    input.value = String(value)
    input.disabled = Boolean(config.disabled)
    if ('placeholder' in input) input.placeholder = config.placeholder ?? ''
    for (const key of ['min', 'max', 'step'] as const) if (config[key] !== undefined) input.setAttribute(key, String(config[key]))
    wrapper.append(title, input)
    controls.append(wrapper)
    return input
  }
  function heading(text: string) { const h = document.createElement('h3'); h.textContent = text; controls.append(h) }
  function action(name: string, text: string, disabled = false) { const button = document.createElement('button'); button.type = 'button'; button.dataset.designAction = name; button.textContent = text; button.disabled = disabled; controls.append(button) }
  function styles(prefix: string, style: TextStyle, spacing: boolean) {
    field(`${prefix}.font`, '字体', style.font, { choices: { sans: '黑体 / 无衬线', serif: '宋体 / 衬线' } })
    field(`${prefix}.size`, '字号（pt）', style.size, { type: 'number', min: 6, max: 72, step: 0.5 })
    field(`${prefix}.color`, '文字颜色', style.color, { type: 'color' })
    field(`${prefix}.bold`, '加粗', style.bold, { type: 'checkbox' })
    field(`${prefix}.lineHeight`, '行距倍数', style.lineHeight, { type: 'number', min: 1, max: 3, step: 0.05 })
    if (spacing) for (const [key, text, max] of [['spaceBefore', '段前（pt）', 72], ['spaceAfter', '段后（pt）', 72], ['indent', '首行缩进（pt）', 48]] as const) field(`${prefix}.${key}`, text, style[key], { type: 'number', min: 0, max, step: 0.5 })
  }
  function renderControls() {
    controls.replaceChildren()
    if (tab === 'cover') {
      heading('封面布局')
      field('options.cover', '导出时包含封面', design.options.cover, { type: 'checkbox' })
      field('cover.preset', '布局预设', design.cover.preset, { choices: { formal: '正式居中', minimal: '简洁左对齐' } })
      action('preset', '重置为所选布局（可撤销）')
      field('cover.background', '页面背景', design.cover.background, { type: 'color' })
      field('cover.role', '选中文字框', selected, { choices: labels })
      const box = design.cover[selected]
      field('box.visible', '显示此文字框', box.visible, { type: 'checkbox' })
      for (const [name, label, max, min] of [['x', '左边距 x（mm）', 210, 0], ['y', '上边距 y（mm）', 297, 0], ['width', '宽度（mm）', 210, 10], ['height', '高度（mm）', 297, 5]] as const) field(`box.${name}`, label, box[name], { type: 'number', min, max, step: 0.5 })
      action('align-left', '靠左'); action('align-center', '水平居中'); action('align-right', '靠右')
      field('box.text', '自定义文字（留空则绑定报告信息）', box.text ?? '', { type: 'textarea', placeholder: coverText({ ...design, cover: { ...design.cover, [selected]: { ...box, text: null } } }, context, selected) })
      action('bound-text', '恢复绑定报告信息')
      styles('box', box, false)
      field('box.align', '文本对齐', box.align, { choices: { left: '左对齐', center: '居中', right: '右对齐' } })
      heading('落款组成')
      field('cover.showOrganization', '显示组织名称', design.cover.showOrganization, { type: 'checkbox' })
      field('cover.showGeneratedBy', '显示生成者', design.cover.showGeneratedBy, { type: 'checkbox' })
      field('cover.showDate', '显示日期', design.cover.showDate, { type: 'checkbox' })
    } else if (tab === 'watermark') {
      heading('全文水印')
      const wm = design.watermark
      field('watermark.enabled', '启用水印', wm.enabled, { type: 'checkbox' })
      field('watermark.text', '水印文字（留空则使用报告默认值）', wm.text ?? '', { placeholder: context.watermarkText }).setAttribute('maxlength', '200')
      field('watermark.font', '字体', wm.font, { choices: { sans: '黑体 / 无衬线', serif: '宋体 / 衬线' } })
      field('watermark.size', '字号（pt）', wm.size, { type: 'number', min: 8, max: 72 })
      field('watermark.color', '颜色', wm.color, { type: 'color' })
      field('watermark.opacity', '不透明度（0.01–0.5）', wm.opacity, { type: 'number', min: 0.01, max: 0.5, step: 0.005 })
      field('watermark.angle', '旋转角度（°）', wm.angle, { type: 'number', min: -90, max: 90 })
      field('watermark.placement', '分布方式', wm.placement, { choices: { center: '居中', tile: '平铺' } })
      field('watermark.cover', '封面也显示水印', wm.cover, { type: 'checkbox' })
    } else if (tab === 'typography') {
      heading('正文与标题样式')
      field('typography.role', '文字类型', typeRole, { choices: typeLabels })
      styles('type', design.typography[typeRole], true)
      heading('导出内容')
      for (const [name, text] of [['toc', '目录'], ['headerFooter', '页眉页脚'], ['pageNumbers', '页码'], ['sources', '来源编号与附录']] as const) {
        if (name === 'sources' && options.sourcesEnabled === false) continue
        field(`options.${name}`, text, design.options[name], { type: 'checkbox' })
      }
    } else {
      heading('个人模板')
      const selectedId = currentTemplateId
      field('templateId', '已保存模板', selectedId, { choices: { '': '选择模板', ...Object.fromEntries(templates.map(item => [item.templateId, item.name])) } })
      field('templateName', '模板名称', templateName, { placeholder: '输入易识别的名称' }).setAttribute('maxlength', '100')
      action('template-apply', '应用所选模板', !selectedId)
      action('template-new', '保存为新模板')
      action('template-update', '更新所选模板', !selectedId)
      action('template-rename', '重命名所选模板', !selectedId)
      action('template-delete', '删除所选模板', !selectedId)
      action('template-refresh', '刷新列表')
      const text = document.createElement('p'); text.className = 'design-help'; text.textContent = '模板保留布局、样式与水印。应用时封面文字重新绑定当前报告，不沿用其他报告的标题、期间与落款。'; controls.append(text)
    }
    for (const button of dialog.querySelectorAll<HTMLButtonElement>('[data-design-tab]')) { button.classList.toggle('is-active', button.dataset.designTab === tab); button.setAttribute('aria-pressed', String(button.dataset.designTab === tab)) }
  }

  function setStyle(element: HTMLElement, style: TextStyle, scale = 1) {
    element.style.fontFamily = fonts[style.font]
    element.style.fontSize = scale === 1 ? `${style.size}pt` : `${style.size * scale}px`
    element.style.color = style.color
    element.style.fontWeight = style.bold ? '700' : '400'
    element.style.lineHeight = String(style.lineHeight)
    element.style.marginTop = `${style.spaceBefore}pt`
    element.style.marginBottom = `${style.spaceAfter}pt`
    element.style.textIndent = `${style.indent}pt`
  }
  function watermark(target: HTMLElement, show: boolean, cover: boolean) {
    const wm = design.watermark
    target.hidden = !show
    target.replaceChildren()
    if (!show) return
    const count = wm.placement === 'tile' ? 9 : 1
    target.classList.toggle('is-tiled', count > 1)
    for (let i = 0; i < count; i++) {
      const text = document.createElement('span')
      text.textContent = wm.text ?? context.watermarkText
      Object.assign(text.style, { fontFamily: fonts[wm.font], fontSize: `${wm.size * (cover ? (page.clientWidth || 420) / 210 * 25.4 / 72 : 1)}${cover ? 'px' : 'pt'}`, color: wm.color, opacity: String(wm.opacity), transform: `rotate(${wm.angle}deg)` })
      target.append(text)
    }
  }
  function render() {
    page.style.background = design.cover.background
    for (const role of roles) {
      const box = design.cover[role]
      const block = blocks.get(role)!
      block.hidden = !box.visible
      block.classList.toggle('is-selected', selected === role)
      block.setAttribute('aria-pressed', String(selected === role))
      Object.assign(block.style, { left: `${box.x / 210 * 100}%`, top: `${box.y / 297 * 100}%`, width: `${box.width / 210 * 100}%`, height: `${box.height / 297 * 100}%`, textAlign: box.align })
      const text = block.querySelector<HTMLElement>('.design-cover-text')!
      text.textContent = coverText(design, context, role)
      setStyle(text, box, (page.clientWidth || 420) / 210 * 25.4 / 72)
    }
    watermark(page.querySelector<HTMLElement>('.design-cover-watermark')!, design.watermark.enabled && design.watermark.cover, true)
    watermark(sample.querySelector<HTMLElement>('.design-body-watermark')!, design.watermark.enabled, false)
    for (const role of typeRoles) {
      const style = design.typography[role]
      const selector = role === 'body' ? 'p' : role === 'caption' ? 'figcaption' : role
      sample.querySelectorAll<HTMLElement>(selector).forEach(element => setStyle(element, style))
    }
    applyDesignTypography(options.editor, design)
    dialog.querySelector<HTMLButtonElement>('[data-design-action="undo"]')!.disabled = !history.length
    dialog.querySelector<HTMLButtonElement>('[data-design-action="redo"]')!.disabled = !future.length
    provenanceHost.hidden = !provenanceHost.hasChildNodes() || previewStale()
    previewStatus.dataset.state = previewStale() ? 'stale' : 'ready'
    if (previewStale() && !previewing) previewStatus.textContent = 'PDF 预览已过期，请重新生成'
  }

  let currentTemplateId = ''
  let templateName = ''
  async function loadTemplates() {
    templates = (await options.client.designTemplates()).items
    if (!templates.some(item => item.templateId === currentTemplateId)) currentTemplateId = ''
    if (tab === 'templates') renderControls()
  }
  async function templateAction(action: string) {
    const item = templates.find(template => template.templateId === currentTemplateId)
    if (action === 'template-refresh') { await loadTemplates(); return }
    if (action === 'template-apply' && item) {
      change(next => {
        Object.assign(next, copy(item.design))
        roles.forEach(role => { next.cover[role].text = null })
        if (options.sourcesEnabled === false) next.options.sources = false
      })
      showError(`已应用“${item.name}”，封面信息已绑定当前报告。可撤销此次应用。`)
      renderControls(); return
    }
    if (action === 'template-delete' && item) {
      if (deletePending !== item.templateId) { deletePending = item.templateId; showError(`再次点击“删除所选模板”确认删除“${item.name}”。`); return }
      await options.client.deleteDesignTemplate(item.templateId); currentTemplateId = ''; templateName = ''; deletePending = ''; await loadTemplates(); return
    }
    if (!templateName.trim()) { showError('请先输入模板名称。'); return }
    const id = action === 'template-new' ? `design-${crypto.randomUUID()}` : item?.templateId
    if (!id) return
    const result = await options.client.saveDesignTemplate(id, templateName.trim(), action === 'template-rename' ? item!.design : design)
    currentTemplateId = result.templateId
    await loadTemplates()
    showError('个人模板已保存。')
  }
  let deletePending = ''

  const changeControl = (event: Event) => {
    const input = event.target as HTMLInputElement
    const name = input.name
    if (!name) return
    if (name === 'cover.role') { select(input.value as CoverRole); return }
    if (name === 'typography.role') { typeRole = input.value as TypographyRole; renderControls(); return }
    if (name === 'templateId') { currentTemplateId = input.value; templateName = templates.find(item => item.templateId === currentTemplateId)?.name ?? ''; deletePending = ''; renderControls(); return }
    if (name === 'templateName') { templateName = input.value; return }
    const value = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value
    if (typeof value === 'number' && (!Number.isFinite(value) || input.value.trim() === '')) { renderControls(); return }
    const bounded = typeof value === 'number' ? Math.max(input.min ? Number(input.min) : -Infinity, Math.min(input.max ? Number(input.max) : Infinity, value)) : value
    if (event.type === 'change' && typeof bounded === 'number') input.value = String(bounded)
    change(next => {
      const [section, key] = name.split('.')
      const target = section === 'box' ? next.cover[selected] : section === 'type' ? next.typography[typeRole] : next[section as 'cover' | 'watermark' | 'options']
      ;(target as unknown as Record<string, unknown>)[key] = key === 'text' && bounded === '' ? null : bounded
      if (section === 'box') next.cover[selected] = clampCoverBox(next.cover[selected])
    })
    if (event.type === 'change' && name.startsWith('box.') && ['x', 'y', 'width', 'height'].includes(name.split('.')[1])) renderControls()
  }
  controls.addEventListener('change', changeControl)
  controls.addEventListener('input', event => {
    const input = event.target as HTMLInputElement
    if (input.type !== 'checkbox' && input.tagName !== 'SELECT') changeControl(event)
  })
  dialog.querySelector<HTMLInputElement>('[name="design.note"]')!.addEventListener('input', event => { note = (event.target as HTMLInputElement).value.trim() })
  dialog.addEventListener('click', event => {
    const target = (event.target as Element).closest<HTMLButtonElement>('button')
    if (!target) return
    if (target.dataset.designTab) {
      tab = target.dataset.designTab
      renderControls()
      page.hidden = tab === 'typography' || tab === 'watermark'
      sample.hidden = tab === 'cover' || tab === 'templates'
      if (tab === 'templates') void loadTemplates().catch(() => showError('无法读取个人模板，请点击刷新列表重试。'))
      return
    }
    const action = target.dataset.designAction
    if (!action) return
    if (action === 'undo' && history.length) { future.push(copy(design)); design = history.pop()!; changed(); renderControls() }
    if (action === 'redo' && future.length) { history.push(copy(design)); design = future.pop()!; changed(); renderControls() }
    if (action === 'preset') { change(next => Object.assign(next, applyCoverPreset(next, next.cover.preset))); renderControls() }
    if (action === 'bound-text') { change(next => { next.cover[selected].text = null }); renderControls() }
    if (action.startsWith('align-')) { change(next => { const box = next.cover[selected]; box.x = action === 'align-left' ? 0 : action === 'align-right' ? 210 - box.width : (210 - box.width) / 2 }); renderControls() }
    if (action === 'retry') void flush().catch(() => undefined)
    if (action === 'preview') void preview().catch(() => undefined)
    if (action === 'reload') void options.client.design().then(reset).catch(() => showError('无法读取远端设计，请稍后重试。'))
    if (action === 'retry-local') void options.client.design().then(remote => { hash = remote.designSha256; saved = copy(remote.design); context = remote.documentContext; conflict = false; conflictBox.hidden = true; return flush() }).catch(() => showError('重新保存失败，本地设计仍然保留。'))
    if (action === 'recover') {
      try { const cached = JSON.parse(readStorage(cacheKey) ?? '{}'); if (cached.design?.version === 1) change(next => Object.assign(next, cached.design)) } catch { showError('本地草稿无法读取。') }
      recovery.hidden = true; renderControls()
    }
    if (action === 'discard-recovery') { removeStorage(cacheKey); recovery.hidden = true }
    if (action.startsWith('template-')) void templateAction(action).catch(() => showError('模板操作失败，请检查网络后重试。'))
  })

  async function preview() {
    if (previewing) return
    previewing = true
    provenanceHost.replaceChildren()
    const button = dialog.querySelector<HTMLButtonElement>('[data-design-action="preview"]')!
    button.disabled = true
    previewStatus.textContent = '正在保存并生成 PDF 预览…'
    try {
      let capturedMarkdown: string
      let documentHash: string
      do {
        documentHash = await options.saveMarkdown()
        capturedMarkdown = options.getMarkdown()
        await flush()
      } while (capturedMarkdown !== options.getMarkdown() || dirty())
      const capturedDesign = copy(design)
      let result = await options.client.startDesignPreview(documentHash, hash)
      while (result.status === 'running' && !destroyed) {
        await new Promise(resolve => window.setTimeout(resolve, options.pollMs ?? 1500))
        if (destroyed) return
        result = await options.client.designPreview(result.previewId)
      }
      if (result.status === 'failed') throw new Error(result.error?.message || 'PDF 预览生成失败')
      renderEditorLayoutProvenance(provenanceHost, result.validation?.layoutProvenance)
      previewMarkdown = capturedMarkdown
      previewDesign = capturedDesign
      pdfLink.href = options.client.designPreviewUrl(result.previewId)
      pdfLink.hidden = false
      previewStatus.textContent = result.validation?.ok === false ? `预览已生成，验收未通过：${result.validation.issues.map(issue => issue.message || issue.code).join('；')}` : 'PDF 预览已生成，未发布新版本'
      render()
    } catch (error) {
      previewStatus.textContent = error instanceof ReportEditorApiError && error.status === 409 ? '正文或设计已变化，请处理保存冲突后重试' : error instanceof Error && !(error instanceof ReportEditorApiError) ? error.message : '无法生成 PDF 预览，请稍后重试'
      throw error
    } finally { previewing = false; button.disabled = false; render() }
  }
  try { const cached = JSON.parse(readStorage(cacheKey) ?? '{}'); recovery.hidden = !cached.design || same(cached.design, design) } catch { recovery.hidden = true }
  status.textContent = '设计已保存'
  sample.hidden = true
  renderControls(); render()
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => render())
  observer?.observe(page)
  return {
    dialog, close: modal.close, flush, reset, preview, loadTemplates,
    open() { modal.open(); render() },
    read() { return { design: copy(design), designSha256: hash, note } },
    get dirty() { return dirty() },
    get previewStale() { return previewStale() },
    markMarkdownChanged() { render() },
    async refresh() {
      const remote = await options.client.design()
      if (dirty() && remote.designSha256 !== hash) { conflict = true; conflictBox.hidden = false; return }
      if (!dirty()) reset(remote)
    },
    destroy() { destroyed = true; window.clearTimeout(timer); observer?.disconnect(); modal.remove() },
  }
}
