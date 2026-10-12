import type { Node as ProseNode } from '@milkdown/kit/prose/model'
import { Plugin, PluginKey, type Transaction } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet, type EditorView } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'

import type { TraceSources, TraceValidation } from './api'
import { findProtocolMarkers, groupProtocolMarkers } from './protocol'

export type ValueMarkState = 'valid' | 'stale' | 'unverified'

export interface ValueMark {
  start: number
  end: number
  state: ValueMarkState
  subjectId?: string
  /** 悬停卡片的逐行说明（指标、登记值、正文值、期间、口径、状态）。 */
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
function sameValue(written: string, writtenUnit: string, registered: number, registeredUnit: string): boolean {
  const number = Number(written.replace(/,/g, '').replace(/[−－]/g, '-'))
  if (!Number.isFinite(number)) return false
  let target = registered
  if (writtenUnit && registeredUnit && writtenUnit !== registeredUnit) {
    const family = unitFamily(registeredUnit)
    if (!family || !(writtenUnit in family)) return false
    target = registered * family[registeredUnit] / family[writtenUnit]
  }
  const digits = written.includes('.') ? written.split('.')[1].length : 0
  const rounded = (value: number) => Math.round(Math.abs(value) * 10 ** digits) / 10 ** digits
  return rounded(number) === rounded(target)
}

export function formatRegisteredValue(value: unknown, unit?: string | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '暂无法确认'
  const digits = Number.isInteger(value) ? 0 : 2
  return `${value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}${unit ?? ''}`
}

function periodText(periods: unknown): string {
  if (Array.isArray(periods)) return periods.filter(item => typeof item === 'string').join('、')
  return typeof periods === 'string' ? periods : ''
}

function subjectCard(subject: Subject, sources: TraceSources | undefined, written?: string): string[] {
  const ref = sources?.subjects?.find(item => item.subjectId === subject.subjectId)?.factRefs[0]
  const fact = sources?.facts?.find(item => item.analysisId === ref?.analysisId && item.factId === ref?.factId)
  return [
    fact?.name ? `指标：${fact.name}` : '',
    `登记值：${formatRegisteredValue(subject.factValue, subject.unit)}`,
    written ? `正文值：${written}` : '',
    periodText(subject.periods) ? `期间：${periodText(subject.periods)}` : '',
    subject.formulaText || subject.formula ? `口径：${subject.formulaText || subject.formula}` : '',
    subject.status === 'valid' ? '状态：与登记值一致' : '状态：正文已改动，需复核',
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
        const writtenUnit = unit.unit
        const registeredUnit = subject.unit ?? ''
        const matchesRegistered = sameValue(match[0], writtenUnit, subject.factValue, registeredUnit)
        const matchesDraft = subject.status !== 'valid' && typeof subject.draftValue === 'number' &&
          sameValue(match[0], writtenUnit, subject.draftValue, subject.draftUnit ?? registeredUnit)
        if (!matchesRegistered && !matchesDraft) continue
        const end = start + match[0].length + unit.length
        const written = text.slice(start, end).replace(/\s+/g, '')
        marks.push({
          start, end, subjectId: subject.subjectId,
          state: subject.status === 'valid' && matchesRegistered ? 'valid' : 'stale',
          card: subjectCard(subject, sources, written),
        })
      }
    }
    segmentStart = marker.end
  }
  for (let index = text.indexOf(UNVERIFIED); index >= 0; index = text.indexOf(UNVERIFIED, index + UNVERIFIED.length)) {
    if (hidden(index)) continue
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

export const bodyValueMarksPlugin = $prose(() => new Plugin<DecorationSet>({
  key,
  state: {
    init: () => DecorationSet.empty,
    // 正文改动后旧标注位置失效，等待新一轮来源校验再标注。
    apply: (tr, previous) => tr.getMeta(key) ?? (tr.docChanged ? DecorationSet.empty : previous),
  },
  props: { decorations: state => key.getState(state) ?? DecorationSet.empty },
}))

export function updateBodyValueMarks(view: EditorView, validation: TraceValidation | null, sources?: TraceSources): void {
  const decorations = documentValueMarks(view.state.doc, validation, sources).map(mark => Decoration.inline(mark.from, mark.to, {
    class: `report-value-mark report-value-mark--${mark.state}`,
    'data-value-state': mark.state,
    'data-value-card': JSON.stringify(mark.card),
    ...(mark.subjectId ? { 'data-value-subject': mark.subjectId } : {}),
    'aria-label': mark.card.join('；'),
  }))
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
  const targets = documentValueMarks(view.state.doc, validation, sources)
    .filter(mark => mark.subjectId === subjectId && mark.state !== 'valid')
  if (targets.length !== 1) return false
  const [target] = targets
  const written = view.state.doc.textBetween(target.from, target.to)
  let replacementValue = subject.factValue
  if (subject.draftDirection) {
    // 只恢复幅度，不猜测或改写方向；登记方向与正文冲突时保留人工处理。
    if ((subject.draftDirection === 'decrease' && replacementValue > 0) ||
      (subject.draftDirection === 'increase' && replacementValue < 0)) return false
    replacementValue = Math.abs(replacementValue)
  } else if (replacementValue < 0 && !/^[−－-]/.test(written)) {
    // 旧校验响应或占位没有足够的方向信息，不能把负值填到可能是“下降”的正幅度中。
    return false
  }
  // 沿用正文原有的数字与单位间距写法，只替换数值。
  const spaced = /\d\s+\D/.test(written)
  // 写回正文保留登记值精度；卡片的两位小数仅用于展示，不能用于数据恢复。
  const exactValue = replacementValue.toLocaleString('zh-CN', { maximumSignificantDigits: 21 })
  const replacement = `${exactValue}${spaced && subject.unit ? ' ' : ''}${subject.unit ?? ''}`
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
