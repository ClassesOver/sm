import type { Node as ProseNode } from '@milkdown/kit/prose/model'
import { Plugin, PluginKey, type Transaction } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet, type EditorView } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'

import type { TraceSources, TraceValidation } from './api'
import { findProtocolMarkers } from './protocol'

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
  money: { 元: 1, 万元: 1e4, 亿元: 1e8 },
  visits: { 人次: 1, 万人次: 1e4 },
}
// 正文数值：千分位数字 + 可选单位；“待核实”是服务端替换无依据数值后的占位。
const VALUE_PATTERN = /(?<![\dA-Za-z_.,+−－-])[+−－-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.,eE])/g
const UNIT_AFTER = /^\s*(亿元|万元|元|万人次|人次|个百分点|%|‰)/
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
  let segmentStart = 0
  for (const marker of markers) {
    if (marker.kind !== 'citation') {
      if (marker.kind !== 'analysis') segmentStart = marker.end
      continue
    }
    const subject = validation?.subjects.find(item => item.subjectId === marker.value)
    // 句号之后的数字属于下一句，不归入当前来源。
    const sentenceStart = Math.max(segmentStart, ...['。', '；', '\n'].map(mark => text.lastIndexOf(mark, marker.start - 2) + 1))
    if (subject && typeof subject.factValue === 'number') {
      const segment = text.slice(sentenceStart, marker.start)
      for (const match of segment.matchAll(VALUE_PATTERN)) {
        const start = sentenceStart + match.index!
        if (hidden(start)) continue
        const unit = UNIT_AFTER.exec(text.slice(start + match[0].length))
        const writtenUnit = unit?.[1] ?? ''
        const registeredUnit = subject.unit ?? ''
        const matchesRegistered = sameValue(match[0], writtenUnit, subject.factValue, registeredUnit)
        const matchesDraft = subject.status !== 'valid' && typeof subject.draftValue === 'number' &&
          sameValue(match[0], writtenUnit, subject.draftValue, subject.draftUnit ?? registeredUnit)
        if (!matchesRegistered && !matchesDraft) continue
        const end = start + match[0].length + (unit?.[0].length ?? 0)
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
    // 只关联同一句内唯一的来源（句末标点后紧跟的标记也算本句）；跨句或多个来源时不猜测，
    // 避免“恢复为登记值”把别的指标的数值填进来。
    const tail = text.slice(index)
    const stop = tail.search(/[。；\n]/)
    const sentence = stop < 0 ? tail : tail.slice(0, stop + 1) + (/^(?:\s*\[\[[a-z/-]+(?::[^\]]*)?\]\])*/.exec(tail.slice(stop + 1))?.[0] ?? '')
    const citations = [...new Set(findProtocolMarkers(sentence).filter(marker => marker.kind === 'citation').map(marker => marker.value))]
    // 占位后紧跟的来源标记（中间只有标点）直接归属该来源。
    const adjacent = /^[\s，、。；]*\[\[citation:([^\]]+)\]\]/.exec(tail.slice(UNVERIFIED.length))?.[1]
    const linked = adjacent ?? (citations.length === 1 ? citations[0] : undefined)
    const subject = linked ? validation?.subjects.find(item => item.subjectId === linked) : undefined
    marks.push({
      start: index, end: index + UNVERIFIED.length, state: 'unverified', subjectId: subject?.subjectId,
      card: ['缺少登记依据的数值，发布前已替换为“待核实”',
        subject && typeof subject.factValue === 'number' ? `同句来源登记值：${formatRegisteredValue(subject.factValue, subject.unit)}` : '请核对数据后改写或删除'],
    })
  }
  return marks.sort((left, right) => left.start - right.start)
}

/** 文本块中各文本节点的拼接文本及其在文档中的起点，用于跨粗体等标记定位。 */
function textBlocks(doc: ProseNode): Array<{ text: string; positions: number[] }> {
  const blocks: Array<{ text: string; positions: number[] }> = []
  doc.descendants((node, position) => {
    if (!node.isTextblock) return true
    let text = ''
    const positions: number[] = []
    node.forEach((child, offset) => {
      if (!child.isText || !child.text) return
      for (let index = 0; index < child.text.length; index++) positions.push(position + 1 + offset + index)
      text += child.text
    })
    blocks.push({ text, positions })
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
  if (!subject || typeof subject.factValue !== 'number') return false
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
  const replacement = spaced && subject.unit
    ? `${formatRegisteredValue(replacementValue)} ${subject.unit}` : formatRegisteredValue(replacementValue, subject.unit)
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
