import { Schema } from '@milkdown/kit/prose/model'
import { EditorState, type Transaction } from '@milkdown/kit/prose/state'
import type { EditorView } from '@milkdown/kit/prose/view'
import { afterEach, describe, expect, it } from 'vitest'

import type { TraceSources, TraceValidation } from './api'
import { documentValueMarks, findValueMarks, formatRegisteredValue, installValueCard, restoreRegisteredValue } from './body-value-marks'

const schema = new Schema({
  nodes: { doc: { content: 'paragraph+' }, paragraph: { content: 'text*', toDOM: () => ['p', 0] }, text: {} },
  marks: { strong: { toDOM: () => ['strong', 0] } },
})

function validation(status: 'valid' | 'stale', draftValue?: number): TraceValidation {
  return {
    draftSha256: 'x',
    summary: { valid: status === 'valid' ? 1 : 0, stale: status === 'stale' ? 1 : 0, unbound: 0 },
    subjects: [{ subjectId: 'sub-1', claimId: 'c', sectionId: null, status, factValue: 12450, unit: '万元', draftValue,
      periods: ['2025-01', '2025-10'], formula: 'sum(营收)' }],
  }
}
const sources: TraceSources = {
  available: true,
  subjects: [{ subjectId: 'sub-1', subjectKind: 'claim', locator: {}, factRefs: [{ analysisId: 'a', factId: 'f' }], computationId: null }],
  facts: [{ analysisId: 'a', factId: 'f', factKind: 'metric', label: '营收', name: '华东营收', unit: '万元', displayValue: 12450, datasetIds: [] }],
} as unknown as TraceSources

function fakeView(text: string) {
  const view = {
    state: EditorState.create({ doc: schema.node('doc', null, [schema.node('paragraph', null, [schema.text(text)])]) }),
    dispatch(tr: Transaction) { view.state = view.state.apply(tr) },
  }
  return view as unknown as EditorView & { state: EditorState }
}

afterEach(() => document.body.replaceChildren())

describe('body value marks', () => {
  it('marks the cited number with its registered value and business name', () => {
    const text = '华东营收为 12,450 万元，同比增长 8.0%。[[citation:sub-1]]'
    const marks = findValueMarks(text, validation('valid'), sources)
    expect(marks).toHaveLength(1)
    expect(text.slice(marks[0].start, marks[0].end)).toBe('12,450 万元')
    expect(marks[0].state).toBe('valid')
    expect(marks[0].card).toEqual(expect.arrayContaining(['指标：华东营收', '登记值：12,450万元', '期间：2025-01、2025-10']))
  })

  it('converts units and ignores numbers from the previous sentence', () => {
    const text = '上年为 9,000 万元。今年华东营收 1.245 亿元[[citation:sub-1]]'
    const marks = findValueMarks(text, validation('valid'))
    expect(marks.map(mark => text.slice(mark.start, mark.end))).toEqual(['1.245 亿元'])
  })

  it('marks an edited draft value as stale and unverified placeholders separately', () => {
    const text = '华东营收为 12,780 万元[[citation:sub-1]]，另有一项待核实。'
    const marks = findValueMarks(text, validation('stale', 12780))
    expect(marks.map(mark => mark.state)).toEqual(['stale', 'unverified'])
    expect(marks[0].card).toContain('状态：正文已改动，需复核')
  })

  it('does not guess a source for an unrelated number', () => {
    expect(findValueMarks('共有 37 家门店[[citation:sub-1]]', validation('valid'))).toEqual([])
  })

  it('restores the registered value into the single stale mark only', () => {
    const view = fakeView('华东营收为 12,780 万元[[citation:sub-1]]')
    expect(documentValueMarks(view.state.doc, validation('stale', 12780))).toHaveLength(1)
    expect(restoreRegisteredValue(view, 'sub-1', validation('stale', 12780))).toBe(true)
    expect(view.state.doc.textContent).toBe('华东营收为 12,450 万元[[citation:sub-1]]')
    expect(restoreRegisteredValue(view, 'sub-1', validation('valid'))).toBe(false)
    const compact = fakeView('营收12,780万元[[citation:sub-1]]')
    expect(restoreRegisteredValue(compact, 'sub-1', validation('stale', 12780))).toBe(true)
    expect(compact.state.doc.textContent).toBe('营收12,450万元[[citation:sub-1]]')
  })

  it('formats unknown registered values without inventing data', () => {
    expect(formatRegisteredValue(null, '万元')).toBe('暂无法确认')
    expect(formatRegisteredValue(3.14159, '%')).toBe('3.14%')
  })

  it('shows and hides the read-only hover card', () => {
    const root = document.createElement('div')
    root.innerHTML = '<span class="report-value-mark" tabindex="0" data-value-state="valid" data-value-card=\'["指标：华东营收","登记值：12,450万元"]\'>12,450 万元</span>'
    document.body.append(root)
    const uninstall = installValueCard(root)
    const mark = root.querySelector<HTMLElement>('.report-value-mark')!
    mark.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    const card = document.querySelector<HTMLElement>('.report-value-card')!
    expect(card.hidden).toBe(false)
    expect(card.textContent).toBe('指标：华东营收登记值：12,450万元')
    // 不改写编辑器内的标注元素，避免 ProseMirror 重绘循环。
    expect(mark.hasAttribute('aria-describedby')).toBe(false)
    mark.dispatchEvent(new FocusEvent('focusout', { bubbles: true }))
    expect(card.hidden).toBe(true)
    uninstall()
    expect(document.querySelector('.report-value-card')).toBeNull()
  })
})

it('shows the hover card when the caret moves into a value mark without touching editor DOM', async () => {
  const root = document.createElement('div')
  root.innerHTML = '<p>营收 <span class="report-value-mark" data-value-state="stale" data-value-card=\'["状态：正文已改动，需复核"]\'>12,780 万元</span></p>'
  document.body.append(root)
  const uninstall = installValueCard(root)
  const text = root.querySelector('.report-value-mark')!.firstChild!
  document.getSelection()!.collapse(text, 2)
  document.dispatchEvent(new Event('selectionchange'))
  const card = document.querySelector<HTMLElement>('.report-value-card')!
  expect(card.hidden).toBe(false)
  expect(card.dataset.state).toBe('stale')
  const mutations: MutationRecord[] = []
  const observer = new MutationObserver(records => mutations.push(...records))
  observer.observe(root, { subtree: true, attributes: true, childList: true })
  document.dispatchEvent(new Event('selectionchange'))
  await Promise.resolve()
  expect([...mutations, ...observer.takeRecords()]).toEqual([])
  observer.disconnect()
  uninstall()
})

it('keeps a pointer-opened card when the caret moves elsewhere', () => {
  const root = document.createElement('div')
  root.innerHTML = '<p id="plain">正文</p><p><span class="report-value-mark" data-value-state="stale" data-value-card=\'["状态：正文已改动，需复核"]\'>12,780 万元</span></p>'
  document.body.append(root)
  const uninstall = installValueCard(root)
  root.querySelector('.report-value-mark')!.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
  document.getSelection()!.collapse(root.querySelector('#plain')!.firstChild!, 1)
  document.dispatchEvent(new Event('selectionchange'))
  const card = document.querySelector<HTMLElement>('.report-value-card')!
  expect(card.hidden).toBe(false)
  uninstall()
})

describe('unverified placeholders', () => {
  const stale = (): TraceValidation => ({
    draftSha256: 'x', summary: { valid: 1, stale: 0, unbound: 0 },
    subjects: [
      { subjectId: 'sub-1', claimId: 'c', sectionId: null, status: 'valid', factValue: 12450, unit: '万元' },
      { subjectId: 'sub-2', claimId: 'd', sectionId: null, status: 'valid', factValue: 37, unit: '家' },
    ],
  })

  it('links a placeholder only to the single source in its own sentence', () => {
    const own = findValueMarks('华东营收为待核实。[[citation:sub-1]]', stale())
    expect(own[0].subjectId).toBe('sub-1')
    const nextSentence = findValueMarks('华北营收为待核实。门店共 37 家。[[citation:sub-2]]', stale())
    expect(nextSentence.find(mark => mark.state === 'unverified')?.subjectId).toBeUndefined()
    const two = findValueMarks('营收为待核实[[citation:sub-1]]，门店 37 家[[citation:sub-2]]。', stale())
    expect(two.find(mark => mark.state === 'unverified')?.subjectId).toBe('sub-1')
    const ambiguous = findValueMarks('营收为待核实，利润 12,450 万元[[citation:sub-1]]，门店 37 家[[citation:sub-2]]。', stale())
    expect(ambiguous.find(mark => mark.state === 'unverified')?.subjectId).toBeUndefined()
  })

  it('does not restore a placeholder from another sentence’s source', () => {
    const view = fakeView('华北营收为待核实。门店共 37 家。[[citation:sub-2]]')
    expect(restoreRegisteredValue(view, 'sub-2', stale())).toBe(false)
    expect(view.state.doc.textContent).toContain('待核实')
  })
})
