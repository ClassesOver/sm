import type { Node as ProseNode } from '@milkdown/kit/prose/model'
import { Plugin, PluginKey, type Transaction } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet, type EditorView } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'

import type { TraceSources, TraceValidation } from './api'
import { datasetLabel } from './evidence-relations'
import { findProtocolMarkers, groupProtocolMarkers } from './protocol'
import { isExplanatoryUnverified } from './unverified-text'

export type ValueMarkState = 'valid' | 'review' | 'stale' | 'unverified'

export interface ValueMark {
  start: number
  end: number
  state: ValueMarkState
  subjectId?: string
  /** 未获校验通过的原始写法，仅用于编辑器展示。 */
  originalText?: string
  /** 由服务端按登记原值派生或按运算式重算，而非直接取登记事实。 */
  computed?: boolean
  /** 悬停卡片的逐行说明（可信状态、指标、登记值、正文值、期间、口径、来源、状态）。 */
  card: string[]
}

type Subject = TraceValidation['subjects'][number]

const UNIT_SCALES: Record<string, Record<string, number>> = {
  money: { 元: 1, 千元: 1e3, 万元: 1e4, 亿元: 1e8 },
  visits: { 人次: 1, 万人次: 1e4 },
}
// 正文数值：千分位数字 + 可选单位；“待核实”是服务端替换无依据数值后的占位。
const VALUE_PATTERN = /(?<![\dA-Za-z_.,+−－-])[+−－-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.,eE])/g
const UNIT_TOKENS = ['亿元', '万元', '千元', '元', '万人次', '人次', '万人', '床日', '床', '张', '次', '人', '个百分点', '%', '‰']
const DECLINE_MAGNITUDE_PREFIX = /(?:下降|减少|降低|回落|下滑|降幅|减幅|跌幅|下跌|缩减)(?:\s*(?:了|约|为|达|幅度为))*\s*$/

function unitAfter(tail: string, subject: Subject): { unit: string; length: number } {
  const spaces = /^\s*/.exec(tail)![0].length
  // 优先完整的登记/草稿单位，防止复合单位被短前缀截断。
  const unit = [...UNIT_TOKENS, subject.unit ?? '', subject.draftUnit ?? '']
    .filter(Boolean).sort((a, b) => b.length - a.length)
    .find(candidate => tail.startsWith(candidate, spaces)) ?? ''
  return { unit, length: unit ? spaces + unit.length : 0 }
}
// 日期中的数字不能作为正文事实恢复；覆盖中文和常见 ISO/斜线日期。
const DATE_PATTERN = /\d{4}\s*(?:年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|[-/]\s*\d{1,2}(?:\s*[-/]\s*\d{1,2})?|\.\s*\d{1,2}\s*\.\s*\d{1,2})(?!\d)|\d{1,2}\s*月?\s*[-—~～至]\s*\d{1,2}\s*月/g
const UNVERIFIED = '待核实'

function unitFamily(unit: string): Record<string, number> | undefined {
  return Object.values(UNIT_SCALES).find(scales => unit in scales)
}

/** 正文写法换算到登记单位后，按正文书写精度舍入比较。 */
function sameValue(written: string, writtenUnit: string, registered: number, registeredUnit: string,
  declineMagnitude = false): boolean {
  const number = Number(written.replace(/,/g, '').replace(/[−－]/g, '-'))
  if (!Number.isFinite(number)) return false
  let target = registered
  if (writtenUnit && registeredUnit && writtenUnit !== registeredUnit) {
    const family = unitFamily(registeredUnit)
    if (!family || !(writtenUnit in family)) return false
    target = registered * family[registeredUnit] / family[writtenUnit]
  }
  if (declineMagnitude && target < 0 && number >= 0) target = -target
  const digits = written.includes('.') ? written.split('.')[1].length : 0
  // Intl 按十进制显示精度舍入，与服务端 ROUND_HALF_UP 一致（1.005 → 1.01）。
  // 超出通用浏览器精度范围时只接受完全相等，不把两个微小值一起舍入成零。
  if (digits > 20) return number === target
  const formatter = new Intl.NumberFormat('en-US', {
    useGrouping: false, minimumFractionDigits: digits, maximumFractionDigits: digits,
  })
  const rounded = (value: number) => {
    const formatted = formatter.format(value)
    // 与服务端一致：舍入后的零不保留负号，非零结果仍须核对符号。
    return /^-0(?:\.0+)?$/.test(formatted) ? formatted.slice(1) : formatted
  }
  return rounded(number) === rounded(target)
}

export function formatRegisteredValue(value: unknown, unit?: string | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '暂无法确认'
  const digits = Number.isInteger(value) ? 0 : 2
  return `${value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}${unit ?? ''}`
}

/**
 * 期间按读者习惯书写，与服务端 period_list_text 同一规则：连续月份写成“2025年1—9月”，
 * 跨年写成“2024年11月—2025年2月”，不连续的各段分别列出；不是逐月期间时原样列出。
 */
export function periodListText(periods: unknown): string {
  const values = Array.isArray(periods) ? periods.filter((item): item is string => typeof item === 'string')
    : typeof periods === 'string' && periods ? [periods] : []
  const parsed = values.map(value => /^(\d{4})-(0[1-9]|1[0-2])$/.exec(value))
  if (!values.length || parsed.some(match => !match)) return values.join('、')
  const runs: number[][] = []
  for (const match of parsed) {
    const month = Number(match![1]) * 12 + Number(match![2]) - 1
    const run = runs.at(-1)
    if (run && month === run[run.length - 1] + 1) run.push(month)
    else runs.push([month])
  }
  const year = (month: number) => Math.floor(month / 12)
  const label = (month: number) => `${year(month)}年${month % 12 + 1}月`
  return runs.map(run => {
    const [first, last] = [run[0], run[run.length - 1]]
    if (first === last) return label(first)
    return year(first) === year(last) ? `${year(first)}年${first % 12 + 1}—${last % 12 + 1}月` : `${label(first)}—${label(last)}`
  }).join('、')
}

function computedSubject(subject: Subject): boolean {
  return subject.computation === 'derived' || subject.computation === 'calc'
}

/** 卡片首行（加粗）：读者一眼可见的可信状态。 */
function trustHeadline(subject: Subject, consistent: boolean): string {
  if (!consistent || subject.status !== 'valid' || subject.sourceStatus === 'integrity_failed' || subject.warnings?.length) return '! 需复核'
  return computedSubject(subject) ? '∑ 服务端计算：按登记原值计算，与正文一致' : '✓ 已核对：与登记值一致'
}

function sourceText(subject: Subject, sources: TraceSources | undefined): string {
  const datasets = sources?.datasets ?? []
  const labels = (subject.datasetIds ?? []).map(id => datasets.find(item => item.datasetId === id))
    .filter((item): item is NonNullable<typeof item> => !!item).map(item => datasetLabel(item, datasets))
  return [...new Set(labels)].join('、')
}

function subjectCard(subject: Subject, sources: TraceSources | undefined, written?: string, consistent = true): string[] {
  const ref = sources?.subjects?.find(item => item.subjectId === subject.subjectId)?.factRefs[0]
  const fact = sources?.facts?.find(item => item.analysisId === ref?.analysisId && item.factId === ref?.factId)
  const computed = computedSubject(subject)
  const source = sourceText(subject, sources)
  // 服务端计算的数：带等号的写“算式”，逐月比较等取值说明写“取值”；直接登记值写“口径”。
  const method = subject.formulaText || subject.formula
  return [
    trustHeadline(subject, consistent),
    fact?.name ? `指标：${fact.name}` : '',
    `${computed ? '计算结果' : '登记值'}：${formatRegisteredValue(subject.factValue, subject.unit)}`,
    written ? `正文值：${written}` : '',
    periodListText(subject.periods) ? `期间：${periodListText(subject.periods)}` : '',
    method ? `${computed ? (method.includes(' = ') ? '算式' : '取值') : '口径'}：${method}` : '',
    source ? `来源：${source}` : '',
    subject.sourceStatus === 'integrity_failed'
      ? '状态：来源身份无法核验；其余来源已独立检查'
      : subject.status === 'unbound'
      ? '状态：尚未建立有效来源绑定'
      : subject.status === 'valid'
      // 一致时首行已写明，不再重复。
      ? (subject.warnings?.length ? '状态：数值一致，业务口径需复核' : '')
      : '状态：正文已改动，需复核',
    ...(subject.warnings ?? []).map(warning => `提示：${warning}`),
  ].filter(Boolean)
}

/**
 * 一段正文中可溯源的数值与“待核实”占位。只标注紧邻来源标记之前、同一句内且与登记值
 * （或正文提取值）一致的数字，不为无法确认的数字猜测来源。
 */
export function findValueMarks(text: string, validation: TraceValidation | null, sources?: TraceSources): ValueMark[] {
  const marks: ValueMark[] = []
  const markers = findProtocolMarkers(text)
  const hidden = (index: number) => markers.some(marker => index >= marker.start && index < marker.end)
  const dates = [...text.matchAll(DATE_PATTERN)]
  let segmentStart = 0
  for (const marker of markers) {
    if (marker.kind !== 'citation') {
      if (marker.kind !== 'analysis') segmentStart = marker.end
      continue
    }
    const subject = validation?.subjects.find(item => item.subjectId === marker.value)
    // 与服务端保持相同句界；引用可位于句末标点和空白之后。
    const before = text.slice(segmentStart, marker.start).replace(/[。！？;；\n]+\s*$/, '')
    const lastStop = [...before.matchAll(/[。！？;；\n]/g)].at(-1)
    const sentenceStart = segmentStart + (lastStop ? lastStop.index! + 1 : 0)
    if (subject && typeof subject.factValue === 'number') {
      const segment = text.slice(sentenceStart, marker.start)
      for (const match of segment.matchAll(VALUE_PATTERN)) {
        const start = sentenceStart + match.index!
        if (hidden(start)) continue
        const tail = text.slice(start + match[0].length)
        if (dates.some(date => start >= date.index! && start < date.index! + date[0].length) ||
          (/^\d+$/.test(match[0]) && /^\s*[年月日]/.test(tail))) continue
        const unit = unitAfter(tail, subject)
        // 数字或完整单位后仍紧接标识符字符时，不把前缀当成独立事实。
        if (/^[\dA-Za-z_]/.test(tail.slice(unit.length))) continue
        const writtenUnit = unit.unit
        const registeredUnit = subject.unit ?? ''
        const declineMagnitude = DECLINE_MAGNITUDE_PREFIX.test(text.slice(sentenceStart, start))
        const matchesRegistered = sameValue(match[0], writtenUnit, subject.factValue, registeredUnit, declineMagnitude)
        const matchesDraft = subject.status !== 'valid' && typeof subject.draftValue === 'number' &&
          sameValue(match[0], writtenUnit, subject.draftValue, subject.draftUnit ?? registeredUnit, declineMagnitude)
        if (!matchesRegistered && !matchesDraft) continue
        const end = start + match[0].length + unit.length
        const written = text.slice(start, end).replace(/\s+/g, '')
        marks.push({
          start, end, subjectId: subject.subjectId,
          state: subject.status === 'valid' && matchesRegistered
            ? (subject.warnings?.length ? 'review' : 'valid') : 'stale',
          computed: computedSubject(subject),
          card: subjectCard(subject, sources, written, matchesRegistered),
        })
      }
    }
    segmentStart = marker.end
  }
  for (let index = text.indexOf(UNVERIFIED); index >= 0; index = text.indexOf(UNVERIFIED, index + UNVERIFIED.length)) {
    if (hidden(index)) continue
    if (validation?.reviewNotices !== undefined) {
      const tail = text.slice(index + UNVERIFIED.length)
      const marker = findProtocolMarkers(tail)[0]
      // 后端允许占位与锚点之间有空白；仅跨同一文本块内的水平空白，不借用下一行。
      const notice = marker?.kind === 'claim' && /^[\p{Zs}\t]*$/u.test(tail.slice(0, marker.start))
        ? validation.reviewNotices.find(item => item.claimId === marker.value) : undefined
      if (notice?.kind !== 'numeric_unverified') continue
      // 重复标记不能把一个原始值关联到多个占位；等待用户消歧。
      const originalText = notice.bound && notice.occurrences === 1 &&
        markers.filter(item => item.kind === 'claim' && item.value === notice.claimId).length === 1
        ? notice.originalText || undefined : undefined
      marks.push({ start: index, end: index + UNVERIFIED.length, state: 'unverified',
        originalText,
        card: [originalText ? `原始值：${originalText}` : '未保存原始值',
          notice.reason ? `原因：${notice.reason}` : '状态：待核实，原始值尚未通过来源校验', '请核对数据后改写或删除'] })
      continue
    }
    if (isExplanatoryUnverified(text, index)) continue
    // 只接受紧邻占位的唯一引用组；同句只有一个来源也可能属于另一项指标。
    // 整组核对，不能把连续多个引用中的第一项当成占位的确定来源。
    const tail = text.slice(index + UNVERIFIED.length)
    const group = groupProtocolMarkers(tail)[0]
    const adjacent = group && /^[\s，、。！？;；]*$/.test(tail.slice(0, group[0].start))
    const citations = adjacent ? [...new Set(group.filter(marker => marker.kind === 'citation').map(marker => marker.value))] : []
    const linked = citations.length === 1 ? citations[0] : undefined
    const subject = linked ? validation?.subjects.find(item => item.subjectId === linked) : undefined
    marks.push({
      start: index, end: index + UNVERIFIED.length, state: 'unverified', subjectId: subject?.subjectId,
      card: ['缺少登记依据的数值，发布前已替换为“待核实”',
        subject && typeof subject.factValue === 'number' ? `同句来源登记值：${formatRegisteredValue(subject.factValue, subject.unit)}` : '请核对数据后改写或删除'],
    })
  }
  return marks.sort((left, right) => left.start - right.start)
}

/** 只拼接连续文本节点（可跨粗体等样式）；硬换行、图片等非文本节点分隔引用窗口。 */
function textBlocks(doc: ProseNode): Array<{ text: string; positions: number[] }> {
  const blocks: Array<{ text: string; positions: number[] }> = []
  doc.descendants((node, position) => {
    // 与服务端 trace_body 一致，代码示例不参与正文数值绑定。
    if (node.type.spec.code) return false
    if (!node.isTextblock) return true
    let text = ''
    let positions: number[] = []
    const flush = () => {
      if (text) blocks.push({ text, positions })
      text = ''
      positions = []
    }
    node.forEach((child, offset) => {
      if (!child.isText || !child.text || child.marks.some(mark => mark.type.spec.code)) { flush(); return }
      for (let index = 0; index < child.text.length; index++) positions.push(position + 1 + offset + index)
      text += child.text
    })
    flush()
    return false
  })
  return blocks
}

export function documentValueMarks(doc: ProseNode, validation: TraceValidation | null, sources?: TraceSources) {
  return textBlocks(doc).flatMap(block => findValueMarks(block.text, validation, sources).map(mark => ({
    ...mark, from: block.positions[mark.start], to: block.positions[mark.end - 1] + 1,
  })))
}

const key = new PluginKey<DecorationSet>('SMART_REPORT_BODY_VALUE_MARKS')

export function createBodyValueMarksPlugin(): Plugin<DecorationSet> {
  return new Plugin<DecorationSet>({
  key,
  state: {
    init: () => DecorationSet.empty,
    // 正文改动后旧标注位置失效，等待新一轮来源校验再标注。
    apply: (tr, previous) => tr.getMeta(key) ?? (tr.docChanged ? DecorationSet.empty : previous),
  },
  props: { decorations: state => key.getState(state) ?? DecorationSet.empty },
  })
}

export const bodyValueMarksPlugin = $prose(createBodyValueMarksPlugin)

export function updateBodyValueMarks(view: EditorView, validation: TraceValidation | null, sources?: TraceSources): void {
  const decorations = documentValueMarks(view.state.doc, validation, sources).flatMap(mark => {
    // 有原始值时正文显示原始值、收起“待核实”字样，句子照常可读；悬停卡片说明未通过核对。
    const computed = mark.computed && mark.state === 'valid'
    const attributes = {
      class: `report-value-mark report-value-mark--${mark.state}${computed ? ' report-value-mark--computed' : ''}${mark.originalText ? ' report-value-mark--collapsed' : ''}`,
      'data-value-state': mark.state,
      ...(computed ? { 'data-value-computed': 'true' } : {}),
      'data-value-card': JSON.stringify(mark.card),
      ...(mark.subjectId ? { 'data-value-subject': mark.subjectId } : {}),
      'aria-label': mark.card.join('；'),
    }
    const highlight = Decoration.inline(mark.from, mark.to, attributes)
    if (!mark.originalText) return [highlight]
    const originalText = mark.originalText
    const original = Decoration.widget(mark.from, () => {
      const element = document.createElement('span')
      for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value)
      element.classList.remove('report-value-mark--collapsed')
      element.classList.add('report-original-value')
      element.contentEditable = 'false'
      element.textContent = originalText
      return element
    }, { side: -1 })
    return [original, highlight]
  })
  view.dispatch(view.state.tr.setMeta(key, DecorationSet.create(view.state.doc, decorations)).setMeta('addToHistory', false))
}

/**
 * 把来源对应的改动数值或同句“待核实”替换为登记值。只改写正文文字，不改动来源标记；
 * 找不到唯一可替换位置时返回 false，由调用方提示用户手动处理。
 */
export function restoreRegisteredValue(view: EditorView, subjectId: string, validation: TraceValidation | null,
  sources?: TraceSources): boolean {
  const subject = validation?.subjects.find(item => item.subjectId === subjectId)
  // 缺失或重复引用尚未形成唯一绑定，不能仅凭一个候选数值自动写入。
  if (!subject || subject.status === 'unbound' || typeof subject.factValue !== 'number' || !Number.isFinite(subject.factValue)) return false
  // 只改了指标、期间或范围时，重填相同数字无法修复语义，须保留人工复核。
  if (subject.status === 'stale' && subject.comparable === false) return false
  const targets = documentValueMarks(view.state.doc, validation, sources)
    .filter(mark => mark.subjectId === subjectId && (mark.state === 'stale' || mark.state === 'unverified'))
  if (targets.length !== 1) return false
  const [target] = targets
  const written = view.state.doc.textBetween(target.from, target.to)
  // 旧响应或未识别修饰语不能把正登记值写进下降表述；样式节点已由 textBetween 合并。
  if (subject.unit === '个百分点' && !subject.draftDirection) {
    const position = view.state.doc.resolve(target.from)
    const prefix = position.parent.textBetween(0, position.parentOffset, '\n', '\n')
    if (/(?:增长|上升|增加|提高|增幅|涨幅|上涨|回升|下降|减少|降低|回落|下滑|降幅|减幅|跌幅|下跌|缩减)[^\d。！？;；\n，,]*$/.test(prefix)) return false
  }
  let replacementValue = subject.factValue
  if (subject.draftDirection) {
    // 只恢复幅度，不猜测或改写方向；登记方向与正文冲突时保留人工处理。
    if ((subject.draftDirection === 'decrease' && replacementValue > 0) ||
      (subject.draftDirection === 'increase' && replacementValue < 0)) return false
    if (subject.restoreText && /^[−－-]/.test(subject.restoreText.trimStart())) return false
    replacementValue = Math.abs(replacementValue)
  } else if (replacementValue < 0 && !/^[−－-]/.test(written)) {
    // 只有已签发的正幅度原文和当前紧邻的下降词能共同确认方向；旧响应或“下降至”仍不猜测。
    const magnitude = /^\+?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?/.exec(subject.restoreText ?? '')?.[0]
    const position = view.state.doc.resolve(target.from)
    const prefix = position.parent.textBetween(0, position.parentOffset, '\n', '\n')
    if (!magnitude || Number(magnitude.replace(/,/g, '')) <= 0 || !DECLINE_MAGNITUDE_PREFIX.test(prefix)) return false
  }
  // 沿用正文原有的数字与单位间距写法，只替换数值。
  const spaced = /\d\s+\D/.test(written)
  // 写回正文保留登记值精度；卡片的两位小数仅用于展示，不能用于数据恢复。
  const exactValue = replacementValue.toLocaleString('zh-CN', { maximumSignificantDigits: 21 })
  // 新引用恢复签发时的显示原文，避免正确值因 .00、单位或舍入写法变化再次触发陈述告警。
  // 旧引用未保存该文本时仍保留原有精度与方向保护。
  const replacement = subject.restoreText || `${exactValue}${spaced && subject.unit ? ' ' : ''}${subject.unit ?? ''}`
  const tr: Transaction = view.state.tr.insertText(replacement, target.from, target.to)
  view.dispatch(tr)
  return true
}

/**
 * 悬停数值标注或光标移入时显示核对卡片；卡片只读，不改写正文。返回卸载函数。
 * 标注位于可编辑正文内无法单独获得焦点，键盘用户通过光标位置触发；读屏内容由标注自身的
 * aria-label 提供。不得改写标注元素属性：ProseMirror 会把这类 DOM 变动当作外部修改而重绘，
 * 光标在标注内时重绘又触发 selectionchange，形成死循环。
 */
export function installValueCard(root: HTMLElement): () => void {
  const card = document.createElement('div')
  card.className = 'report-value-card'
  card.setAttribute('role', 'tooltip')
  card.id = 'report-value-card'
  card.hidden = true
  document.body.append(card)
  let active: HTMLElement | null = null
  const show = (event: Event | { target: Node | null }) => {
    const target = event.target instanceof Element ? event.target : (event.target as Node | null)?.parentElement
    const mark = target?.closest<HTMLElement>('.report-value-mark')
    if (!mark || !root.contains(mark) || mark === active) return
    active = mark
    byCaret = false
    let lines: string[] = []
    try { lines = JSON.parse(mark.dataset.valueCard ?? '[]') } catch { lines = [] }
    card.replaceChildren(...lines.map(line => {
      const row = document.createElement('div')
      row.textContent = line
      return row
    }))
    card.dataset.state = mark.dataset.valueState ?? ''
    card.dataset.computed = mark.dataset.valueComputed ?? ''
    card.hidden = !lines.length
    const box = mark.getBoundingClientRect()
    card.style.left = `${Math.max(8, Math.min(window.scrollX + box.left, window.scrollX + window.innerWidth - 300))}px`
    card.style.top = `${window.scrollY + box.bottom + 6}px`
  }
  const hide = (event?: Event) => {
    const next = (event as FocusEvent | MouseEvent | undefined)?.relatedTarget as HTMLElement | null | undefined
    if (!active || (next && active.contains(next))) return
    active = null
    card.hidden = true
  }
  // Esc 关闭；开始键入时收起指针或跳转打开的卡片，避免遮挡正文。
  const escape = (event: KeyboardEvent) => { if (active && (event.key === 'Escape' || !byCaret)) hide() }
  // 光标打开的卡片随光标离开关闭；指针打开的卡片只随指针离开关闭。
  let byCaret = false
  const caret = () => {
    const anchor = document.getSelection()?.anchorNode ?? null
    if (anchor && root.contains(anchor) && (anchor instanceof Element ? anchor : anchor.parentElement)?.closest('.report-value-mark')) {
      const before = active
      show({ target: anchor })
      if (active !== before) byCaret = true
    } else if (active && byCaret) hide()
  }
  root.addEventListener('mouseover', show)
  root.addEventListener('focusin', show)
  document.addEventListener('selectionchange', caret)
  root.addEventListener('mouseout', hide)
  root.addEventListener('focusout', hide)
  root.addEventListener('keydown', escape)
  return () => {
    root.removeEventListener('mouseover', show)
    root.removeEventListener('focusin', show)
    root.removeEventListener('mouseout', hide)
    root.removeEventListener('focusout', hide)
    root.removeEventListener('keydown', escape)
    document.removeEventListener('selectionchange', caret)
    card.remove()
  }
}
