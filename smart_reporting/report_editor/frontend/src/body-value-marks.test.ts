import { Schema } from '@milkdown/kit/prose/model'
import { EditorState, type Transaction } from '@milkdown/kit/prose/state'
import type { EditorView } from '@milkdown/kit/prose/view'
import { afterEach, describe, expect, it } from 'vitest'

import type { TraceSources, TraceValidation } from './api'
import { documentValueMarks, findValueMarks, formatRegisteredValue, installValueCard, restoreRegisteredValue } from './body-value-marks'

const schema = new Schema({
  nodes: { doc: { content: 'block+' }, code_block: { content: 'text*', group: 'block', code: true, toDOM: () => ['pre', ['code', 0]] }, paragraph: { group: 'block', content: 'inline*', toDOM: () => ['p', 0] },
    text: { group: 'inline' }, hard_break: { inline: true, group: 'inline', toDOM: () => ['br'] } },
  marks: { code: { code: true, toDOM: () => ['code', 0] }, strong: { toDOM: () => ['strong', 0] } },
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

  it.each(['2026年1月', '2026-01', '2026/01/12', '2026.01.12', '1—10月'])('does not restore a calendar number in %s', (period) => {
    const result = validation('stale')
    Object.assign(result.subjects[0], { factValue: period.includes('月') ? 1 : 2026, unit: '个百分点' })
    const text = `${period}占比提高3个百分点。[[citation:sub-1]]`
    expect(findValueMarks(text, result)).toEqual([])
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(view.state.doc.textContent).toBe(text)
  })

  it('keeps decimal amounts distinct from calendar dates', () => {
    const result = validation('valid')
    Object.assign(result.subjects[0], { factValue: 2026.01 })
    const text = '收入2026.01万元[[citation:sub-1]]'
    const marks = findValueMarks(text, result)
    expect(marks).toHaveLength(1)
    expect(text.slice(marks[0].start, marks[0].end)).toBe('2026.01万元')
  })

  it('does not join digits across a hard break and delete that break on restore', () => {
    const view = fakeView('占位')
    view.state = EditorState.create({ doc: schema.node('doc', null, [schema.node('paragraph', null, [
      schema.text('12'), schema.node('hard_break'), schema.text('780万元[[citation:sub-1]]'),
    ])]) })
    const before = view.state.doc
    expect(documentValueMarks(before, validation('stale', 12780))).toEqual([])
    expect(restoreRegisteredValue(view, 'sub-1', validation('stale', 12780))).toBe(false)
    expect(view.state.doc.eq(before)).toBe(true)
  })

  it('still restores a number split only by bold styling', () => {
    const view = fakeView('占位')
    view.state = EditorState.create({ doc: schema.node('doc', null, [schema.node('paragraph', null, [
      schema.text('12'), schema.text('780', [schema.marks.strong.create()]), schema.text('万元[[citation:sub-1]]'),
    ])]) })
    expect(restoreRegisteredValue(view, 'sub-1', validation('stale', 12780))).toBe(true)
    expect(view.state.doc.textContent).toBe('12,450万元[[citation:sub-1]]')
  })

  it('restores a complete value after a hard break without changing that break', () => {
    const view = fakeView('占位')
    view.state = EditorState.create({ doc: schema.node('doc', null, [schema.node('paragraph', null, [
      schema.text('前文'), schema.node('hard_break'), schema.text('12780万元[[citation:sub-1]]'),
    ])]) })
    expect(restoreRegisteredValue(view, 'sub-1', validation('stale', 12780))).toBe(true)
    expect(view.state.doc.firstChild!.child(1).type.name).toBe('hard_break')
    expect(view.state.doc.textContent).toBe('前文12,450万元[[citation:sub-1]]')
  })

  it.each(['！', '？', ';'])('does not borrow the preceding sentence across %s', (stop) => {
    const text = `前句收入12,450万元${stop}本句无数值[[citation:sub-1]]`
    expect(findValueMarks(text, validation('stale'))).toEqual([])
    const placeholder = `前句待核实${stop}本句无数值[[citation:sub-1]]`
    expect(findValueMarks(placeholder, validation('stale'))[0].subjectId).toBeUndefined()
  })

  it('keeps a citation attached to the preceding sentence across trailing punctuation and spaces', () => {
    const text = '收入12,780万元。  [[citation:sub-1]]'
    const marks = findValueMarks(text, validation('stale', 12780))
    expect(marks).toHaveLength(1)
    expect(text.slice(marks[0].start, marks[0].end)).toBe('12,780万元')
  })

  it('marks and restores an edited percentage-point value', () => {
    const result = validation('stale', 2)
    Object.assign(result.subjects[0], { factValue: 1, unit: '个百分点', draftUnit: '个百分点', draftDirection: 'increase' })
    const text = '2026年10月东院占比提高2个百分点。[[citation:sub-1]]'
    const marks = findValueMarks(text, result)
    expect(marks).toHaveLength(1)
    expect(text.slice(marks[0].start, marks[0].end)).toBe('2个百分点')
    expect(marks[0].state).toBe('stale')
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(true)
    expect(view.state.doc.textContent).toBe(text.replace('2个百分点', '1个百分点'))
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

  it.each(['千元', '万人', '床日', '床', '张', '次', '人', '家', '元/人'])('restores the whole value without duplicating unit %s', (unit) => {
    const result = validation('stale', 37)
    Object.assign(result.subjects[0], { factValue: 35, unit, draftUnit: unit })
    const view = fakeView(`指标37${unit}[[citation:sub-1]]`)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(true)
    expect(view.state.doc.textContent).toBe(`指标35${unit}[[citation:sub-1]]`)
  })

  it('converts thousands of yuan without leaving the original unit behind', () => {
    const result = validation('stale', 370)
    Object.assign(result.subjects[0], { factValue: 35, unit: '万元', draftUnit: '千元' })
    const view = fakeView('收入370 千元[[citation:sub-1]]')
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(true)
    expect(view.state.doc.textContent).toBe('收入35 万元[[citation:sub-1]]')
    const marks = findValueMarks('收入350千元[[citation:sub-1]]', { ...result, subjects: [{ ...result.subjects[0], status: 'valid' }] })
    expect(marks).toHaveLength(1)
    expect(marks[0].state).toBe('valid')
  })

  it.each([3.14159, 0.00001, 1e-25])('restores registered precision for %s without display rounding', (factValue) => {
    const result = validation('stale', 2)
    Object.assign(result.subjects[0], { factValue, unit: '%' })
    const view = fakeView('占比2%[[citation:sub-1]]')
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(true)
    const restored = view.state.doc.textContent.split('%')[0].slice(2).replace(/,/g, '')
    expect(Number(restored)).toBe(factValue)
    expect(restored).not.toMatch(/[eE]/)
  })

  it.each(['block', 'inline'])('does not restore a placeholder inside %s code', (kind) => {
    const view = fakeView('占位')
    const literal = '待核实[[citation:sub-1]]'
    const node = kind === 'block' ? schema.node('code_block', null, schema.text(literal))
      : schema.node('paragraph', null, schema.text(literal, [schema.marks.code.create()]))
    view.state = EditorState.create({ doc: schema.node('doc', null, [node]) })
    const before = view.state.doc
    expect(documentValueMarks(before, validation('stale'))).toEqual([])
    expect(restoreRegisteredValue(view, 'sub-1', validation('stale'))).toBe(false)
    expect(view.state.doc.eq(before)).toBe(true)
  })

  it('does not join numbers through inline code to find a citation', () => {
    const view = fakeView('占位')
    view.state = EditorState.create({ doc: schema.node('doc', null, schema.node('paragraph', null, [
      schema.text('12780'), schema.text('万元', [schema.marks.code.create()]), schema.text('[[citation:sub-1]]'),
    ])) })
    expect(documentValueMarks(view.state.doc, validation('stale', 12780))).toEqual([])
    expect(restoreRegisteredValue(view, 'sub-1', validation('stale', 12780))).toBe(false)
  })

  it('ignores a code example while restoring the actual prose', () => {
    const view = fakeView('占位')
    const literal = '12780万元[[citation:sub-1]]'
    view.state = EditorState.create({ doc: schema.node('doc', null, [
      schema.node('code_block', null, schema.text(literal)),
      schema.node('paragraph', null, schema.text(literal)),
    ]) })
    expect(restoreRegisteredValue(view, 'sub-1', validation('stale', 12780))).toBe(true)
    expect(view.state.doc.child(0).textContent).toBe(literal)
    expect(view.state.doc.child(1).textContent).toBe('12,450万元[[citation:sub-1]]')
  })

  it('does not restore an unbound subject even when only one duplicate has a placeholder', () => {
    const result = validation('stale')
    result.subjects[0].status = 'unbound'
    const text = '待核实[[citation:sub-1]]。另一个引用[[citation:sub-1]]'
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(view.state.doc.textContent).toBe(text)
  })

  it.each(['37ABC', '37_code', '37万元ABC', '37万元2'])('does not restore a numeric prefix inside identifier %s', (token) => {
    const result = validation('stale')
    Object.assign(result.subjects[0], { factValue: 37 })
    const text = `编号${token}，金额另行核实[[citation:sub-1]]`
    const view = fakeView(text)
    expect(findValueMarks(text, result)).toEqual([])
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(view.state.doc.textContent).toBe(text)
  })

  it('still accepts a registered Latin unit and Chinese continuation', () => {
    const result = validation('stale', 37)
    Object.assign(result.subjects[0], { factValue: 35, unit: 'USD', draftUnit: 'USD' })
    const view = fakeView('收入37USD后趋稳[[citation:sub-1]]')
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(true)
    expect(view.state.doc.textContent).toBe('收入35USD后趋稳[[citation:sub-1]]')
  })

  it('formats unknown registered values without inventing data', () => {
    expect(formatRegisteredValue(null, '万元')).toBe('暂无法确认')
    expect(formatRegisteredValue(3.14159, '%')).toBe('3.14%')
  })

  it.each(['−', '－'])('restores the entire negative value including the %s sign', (minus) => {
    const result = validation('stale', -2)
    Object.assign(result.subjects[0], { factValue: -1, unit: '个百分点', draftUnit: '个百分点' })
    const text = `2026年10月东院变化${minus}2个百分点。[[citation:sub-1]]`
    const marks = findValueMarks(text, result)
    expect(marks).toHaveLength(1)
    expect(text.slice(marks[0].start, marks[0].end)).toBe(`${minus}2个百分点`)
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(true)
    expect(view.state.doc.textContent).toBe(text.replace(`${minus}2`, '-1'))
  })

  it.each(['1e2个百分点', 'metric2个百分点', '1,23个百分点'])('does not mark a numeric suffix in %s', (written) => {
    const result = validation('stale', 2)
    Object.assign(result.subjects[0], { factValue: 1, unit: '个百分点', draftUnit: '个百分点' })
    expect(findValueMarks(`${written}。[[citation:sub-1]]`, result)).toEqual([])
  })

  it.each(['下降', '降低了', '回落约', '下降了约', '下降 约'])('preserves the %s wording when restoring a registered decline', (verb) => {
    const result = validation('stale', -2)
    Object.assign(result.subjects[0], { factValue: -1, unit: '个百分点', draftUnit: '个百分点', draftDirection: 'decrease' })
    const text = `2026年10月东院占比${verb}2个百分点。[[citation:sub-1]]`
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(true)
    expect(view.state.doc.textContent).toBe(text.replace('2个百分点', '1个百分点'))
  })

  it.each([
    { verb: '下降', factValue: 1, draftValue: -2, draftDirection: 'decrease' },
    { verb: '提高', factValue: -1, draftValue: 2, draftDirection: 'increase' },
    { verb: '下降', factValue: -1, draftValue: 2, draftDirection: undefined },
    { verb: '下降了约', factValue: 1, draftValue: 2, draftDirection: undefined },
    { verb: '提高', factValue: 1, draftValue: 2, draftDirection: undefined },
    { verb: '下降 约', factValue: 1, draftValue: 2, draftDirection: undefined },
    { verb: '下降了约', factValue: 1, draftValue: -2, draftDirection: 'decrease' },
  ] as const)('does not guess a replacement when direction conflicts or is unknown: $verb / $factValue', (entry) => {
    const result = validation('stale', entry.draftValue)
    Object.assign(result.subjects[0], entry, { unit: '个百分点', draftUnit: '个百分点' })
    const text = `占比${entry.verb}2个百分点。[[citation:sub-1]]`
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(view.state.doc.textContent).toBe(text)
  })

  it.each([undefined, 'decrease'] as const)('rejects an opposite positive fact with bold magnitude (%s)', (draftDirection) => {
    const result = validation('stale', draftDirection ? -2 : 2)
    Object.assign(result.subjects[0], { factValue: 1, unit: '个百分点', draftUnit: '个百分点', draftDirection })
    const view = fakeView('占位')
    view.state = EditorState.create({ doc: schema.node('doc', null, [schema.node('paragraph', null, [
      schema.text('2026年10月占比下降'), schema.text('2个百分点', [schema.marks.strong.create()]),
      schema.text('。[[citation:sub-1]]'),
    ])]) })
    const before = view.state.doc
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(view.state.doc.eq(before)).toBe(true)
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

  it.each([
    '营收待核实，门店37家[[citation:sub-2]]',
    '营收待核实，另一个指标说明[[citation:sub-2]]',
    '待核实[[citation:sub-1]][[citation:sub-2]]',
    '待核实。[[analysis:a]][[citation:sub-1]] [[citation:sub-2]]',
  ])('does not guess a placeholder source in %s', (text) => {
    const result = stale()
    expect(findValueMarks(text, result).find(mark => mark.state === 'unverified')?.subjectId).toBeUndefined()
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(restoreRegisteredValue(view, 'sub-2', result)).toBe(false)
    expect(view.state.doc.textContent).toBe(text)
  })

  it('accepts an adjacent source group with one unique citation', () => {
    const text = '营收待核实。[[analysis:a]][[citation:sub-1]]'
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', stale())).toBe(true)
    expect(view.state.doc.textContent).toBe('营收12,450万元。[[analysis:a]][[citation:sub-1]]')
  })

  it.each(['原因待核实', '金额单位待核实', '统计口径待核实', '是否涉及跨期结算或集中入账待核实', '数据完整性待核实', '入账状态待核实'])('preserves the explanatory caveat %s instead of filling in a number', (caveat) => {
    const text = `营收12,450万元，${caveat}[[citation:sub-1]]`
    const view = fakeView(text)
    const marks = findValueMarks(text, stale())
    expect(marks.filter(mark => mark.state === 'unverified')).toEqual([])
    expect(restoreRegisteredValue(view, 'sub-1', stale())).toBe(false)
    expect(view.state.doc.textContent).toBe(text)
  })

  it('does not restore a placeholder from another sentence’s source', () => {
    const view = fakeView('华北营收为待核实。门店共 37 家。[[citation:sub-2]]')
    expect(restoreRegisteredValue(view, 'sub-2', stale())).toBe(false)
    expect(view.state.doc.textContent).toContain('待核实')
  })
})

it('uses typed notices regardless of business wording and never offers a guessed restore', () => {
  const result = validation('valid')
  result.reviewNotices = [
    { claimId: 'note', sectionId: null, kind: 'source_review', occurrences: 1, bound: true },
    { claimId: 'number', sectionId: null, kind: 'numeric_unverified', occurrences: 1, bound: true },
  ]
  const text = '供应商回复待核实[[claim:note]]。任意指标待核实[[claim:number]]。'
  const marks = findValueMarks(text, result, sources)
  expect(marks).toHaveLength(1)
  expect(marks[0].start).toBe(text.lastIndexOf('待核实'))
  expect(marks[0].subjectId).toBeUndefined()
  expect(findValueMarks('供应商回复待核实。', { ...result, reviewNotices: [] }, sources)).toHaveLength(0)
})
