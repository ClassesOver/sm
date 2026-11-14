import { installFocusTrap } from './focus-trap'
import { buttonClasses } from './button'

/** Web adapter for GenOffice f8c17004 FindReplaceDialog: literal search, element navigation,
 * and first/all replacement. Only source text explicitly proven safe by the bridge is edited. */
export interface SlidesFindSource {
  slideIndex: number
  elements: { id: string; type: string; text: string; editable: boolean; findReplaceEditable?: boolean }[]
}
export interface SlidesFindEdit {
  slideIndex: number
  elementId: string
  text?: string
  geometry?: { x: number; y: number; width: number; height: number }
}
export interface SlidesFindOptions {
  order?: number[]
  deletedSlides?: number[]
  deletions?: { slideIndex: number; elementId: string }[]
}
export interface SlidesFindMatch { slideIndex: number; elementId: string; count: number }
export interface SlidesReplacePlan { edits: SlidesFindEdit[]; count: number }
interface ReplaceConditions {
  query: string
  replacement: string
  matchCase: boolean
  target?: { slideIndex: number; elementId: string }
}
const keyOf = (value: { slideIndex: number; elementId: string }) => JSON.stringify([value.slideIndex, value.elementId])
function pattern(query: string, matchCase: boolean) {
  return new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), matchCase ? 'g' : 'gi')
}
function textSources(slides: SlidesFindSource[], edits: SlidesFindEdit[], options: SlidesFindOptions) {
  const pending = new Map(edits.map(edit => [keyOf(edit), edit]))
  const deleted = new Set(options.deletions?.map(keyOf))
  const byIndex = new Map(slides.map(slide => [slide.slideIndex, slide]))
  return (options.order ?? slides.map(slide => slide.slideIndex)).flatMap(slideIndex => {
    const slide = byIndex.get(slideIndex)
    if (!slide || options.deletedSlides?.includes(slideIndex)) return []
    return slide.elements.filter(element => element.editable && element.findReplaceEditable === true &&
      (element.type === 'text' || element.type === 'shape') && !deleted.has(keyOf({ slideIndex, elementId: element.id })))
      .map(element => ({ slideIndex, elementId: element.id, text: pending.get(keyOf({ slideIndex, elementId: element.id }))?.text ?? element.text }))
  })
}

export function buildSlidesFindMatches(slides: SlidesFindSource[], edits: SlidesFindEdit[], query: string,
  matchCase = false, options: SlidesFindOptions = {}): SlidesFindMatch[] {
  // Native text writes split paragraphs: a match must never cross a paragraph/soft-break boundary.
  if (!query || /[\r\n]/.test(query)) return []
  const re = pattern(query, matchCase)
  return textSources(slides, edits, options).flatMap(({ text, ...target }) => {
    const count = [...text.matchAll(re)].length
    return count ? [{ ...target, count }] : []
  })
}

/** Pure, all-or-nothing plan. The caller commits its complete edits array as ONE NativeDraft snapshot. */
export function planSlidesReplace(slides: SlidesFindSource[], edits: SlidesFindEdit[], conditions: ReplaceConditions,
  options: SlidesFindOptions = {}): SlidesReplacePlan {
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(conditions.replacement)) throw new Error('替换文字含不支持的控制字符')
  const result = structuredClone(edits)
  if (!conditions.query || /[\r\n]/.test(conditions.query)) return { edits: result, count: 0 }
  // Replacing paragraph boundaries would also invalidate paragraph formatting/animation targets.
  if (/[\r\n]/.test(conditions.replacement)) throw new Error('替换文字不能包含换行；请使用文字编辑器调整段落')
  let count = 0
  for (const source of textSources(slides, edits, options)) {
    if (conditions.target && keyOf(source) !== keyOf(conditions.target)) continue
    const re = pattern(conditions.query, conditions.matchCase)
    let replaced = 0
    const text = source.text.replace(re, match => {
      if (conditions.target && replaced) return match
      replaced++
      return conditions.replacement // Callback keeps "$&" and "$1" literal, matching the source model.
    })
    if (text === source.text) continue
    if (text.length > 20000) throw new Error('替换后的对象文字超过 20000 字符，请缩小替换范围')
    const index = result.findIndex(edit => keyOf(edit) === keyOf(source))
    const edit = { ...(index >= 0 ? result[index]! : { slideIndex: source.slideIndex, elementId: source.elementId }), text }
    if (index >= 0) result[index] = edit
    else result.push(edit)
    count += replaced
  }
  return { edits: result, count }
}

interface FindReplaceController {
  getSlides: () => SlidesFindSource[]
  getEdits: () => SlidesFindEdit[]
  getOptions?: () => SlidesFindOptions
  isLocked: () => boolean
  onNavigate: (slideIndex: number, elementId: string) => void
  onReplace: (plan: SlidesReplacePlan) => void
}

export function openSlidesFindReplace(host: HTMLElement, controller: FindReplaceController) {
  const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const dialog = document.createElement('dialog')
  dialog.className = 'slides-find-replace'
  dialog.setAttribute('aria-label', '查找和替换')
  const heading = document.createElement('h2')
  heading.textContent = '查找和替换'
  let active = true
  const release = installFocusTrap(dialog)
  const dispose = () => { if (!active) return; active = false; release(); dialog.remove(); if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  const close = document.createElement('button'); close.type = 'button'; close.className = 'slides-find-close ' + buttonClasses('quiet', true); close.setAttribute('aria-label', '关闭查找和替换'); close.textContent = '×'; close.addEventListener('click', dispose)
  const query = document.createElement('input')
  query.setAttribute('aria-label', '查找文字')
  const replacement = document.createElement('input')
  replacement.setAttribute('aria-label', '替换为')
  const matchCase = document.createElement('input')
  matchCase.type = 'checkbox'
  matchCase.setAttribute('aria-label', '区分大小写')
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  status.setAttribute('aria-live', 'polite')
  status.setAttribute('aria-label', '查找替换结果')
  status.tabIndex = 0
  const showStatus = (message: string) => { status.textContent = message; status.scrollIntoView?.({ block: 'nearest' }) }
  const scope = document.createElement('p')
  scope.setAttribute('role', 'region')
  scope.setAttribute('aria-label', '查找替换范围说明')
  scope.tabIndex = 0
  scope.textContent = '仅查找可安全编辑的来源文本框和形状；不含混合样式、域、表格、组合、母版和新增对象。替换不跨段落。'
  let current: { slideIndex: number; elementId: string } | undefined
  let cursor = -1
  let signature = ''
  const reset = () => { current = undefined; cursor = -1; signature = ''; status.textContent = '' }
  query.addEventListener('input', reset)
  matchCase.addEventListener('change', reset)
  const snapshot = () => {
    const slides = controller.getSlides(), edits = controller.getEdits(), options = controller.getOptions?.() ?? {}
    const matches = buildSlidesFindMatches(slides, edits, query.value, matchCase.checked, options)
    const nextSignature = JSON.stringify([query.value, matchCase.checked, matches, textSources(slides, edits, options)])
    if (signature && signature !== nextSignature) { current = undefined; cursor = -1 }
    signature = nextSignature
    return { slides, edits, options, matches }
  }
  const next = () => {
    const { matches } = snapshot()
    if (!matches.length) { showStatus('未找到可编辑的匹配文字'); return }
    cursor = (cursor + 1) % matches.length
    current = matches[cursor]!
    controller.onNavigate(current.slideIndex, current.elementId)
    showStatus(`第 ${cursor + 1}/${matches.length} 个对象，共 ${matches.reduce((sum, item) => sum + item.count, 0)} 处匹配`)
  }
  const replace = (all: boolean) => {
    try {
      if (controller.isLocked()) { showStatus('当前为只读状态或正在保存，不能替换'); return }
      const { slides, edits, options } = snapshot()
      if (!all && !current) { next(); return }
      const plan = planSlidesReplace(slides, edits, { query: query.value, replacement: replacement.value,
        matchCase: matchCase.checked, ...(!all ? { target: current } : {}) }, options)
      if (!plan.count) { showStatus('没有需要替换的文字'); return }
      controller.onReplace(plan)
      const previousCursor = cursor
      reset()
      if (!all) cursor = previousCursor - 1
      showStatus(`已替换 ${plan.count} 处；保存新修订后生效`)
    } catch (error) { showStatus(error instanceof Error ? error.message : '替换失败，未提交修改') }
  }
  const actions = document.createElement('div')
  actions.className = 'slides-table-actions slides-find-actions'
  for (const [command, label, action] of [
    ['findNext', '查找下一个', next], ['replace', '替换', () => replace(false)],
    ['replaceAll', '全部替换', () => replace(true)], ['closeFindReplace', '关闭', dispose],
  ] as const) {
    const button = document.createElement('button')
    button.type = 'button'
    button.dataset.command = command
    button.textContent = label
    button.className = buttonClasses(command === 'findNext' ? 'primary' : 'secondary')
    button.addEventListener('click', action)
    actions.append(button)
  }
  const header = document.createElement('header')
  header.append(heading, close)
  const body = document.createElement('div')
  body.className = 'slides-find-body'
  for (const [label, input] of [['查找 ', query], ['替换为 ', replacement], ['区分大小写 ', matchCase]] as const) {
    const row = document.createElement('label')
    row.className = input === matchCase ? 'slides-find-option' : 'slides-find-field'
    row.append(label, input)
    body.append(row)
  }
  body.append(scope, status)
  const footer = document.createElement('footer')
  footer.append(actions)
  dialog.append(header, body, footer)
  dialog.addEventListener('keydown', event => {
    if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return
    if (event.key === 'Escape') { event.preventDefault(); dispose() }
    if (event.key === 'Enter' && event.target === query) { event.preventDefault(); next() }
  })
  dialog.addEventListener('cancel', event => { event.preventDefault(); dispose() })
  dialog.addEventListener('close', dispose)
  host.append(dialog)
  if (typeof dialog.showModal === 'function') dialog.showModal()
  else dialog.setAttribute('open', '')
  query.focus()
  return { dispose }
}
