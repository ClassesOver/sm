import { Schema } from '@milkdown/kit/prose/model'
import { EditorState, type Transaction } from '@milkdown/kit/prose/state'
import { Decoration, type EditorView } from '@milkdown/kit/prose/view'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { TraceSources, TraceValidation } from './api'
import { documentValueMarks, findValueMarks, formatRegisteredValue, installValueCard, periodListText, restoreRegisteredValue, updateBodyValueMarks } from './body-value-marks'

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

afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })

describe('body value marks', () => {
  it('leads the card with the trust state readers see at a glance', () => {
    const text = '华东营收为 12,450 万元。[[citation:sub-1]]'
    const withSource = { ...sources, datasets: [{ datasetId: 'd1', requirementId: 'r1', periodRoles: ['current'], businessLabel: '收入汇总表' }] } as unknown as TraceSources
    const registered = validation('valid')
    registered.subjects[0].datasetIds = ['d1']
    const [plain] = findValueMarks(text, registered, withSource)
    expect(plain.computed).toBe(false)
    expect(plain.card[0]).toBe('✓ 已核对：与登记值一致')
    expect(plain.card).toContain('来源：收入汇总表')
    // 一致时首行已写明，不再重复一行“状态：与登记值一致”。
    expect(plain.card.filter(line => line.startsWith('状态：'))).toEqual([])
    // 服务端按运算式重算的数：单独标注，卡片写出计算结果与算式。
    const calc = validation('valid')
    calc.subjects[0].computation = 'calc'
    calc.subjects[0].formulaText = '药品（2025年1—9月）6,000万元 + 材料（2025年1—9月）6,450万元 = 12,450.00万元'
    const [computed] = findValueMarks(text, calc, sources)
    expect(computed.computed).toBe(true)
    expect(computed.card[0]).toBe('∑ 服务端计算：按登记原值计算，与正文一致')
    expect(computed.card).toContain('计算结果：12,450万元')
    expect(computed.card).toContain(`算式：${calc.subjects[0].formulaText}`)
    // 服务端按登记原值派生的数同样写出可验算的算式；直接登记值仍写“口径”。
    const derived = validation('valid')
    derived.subjects[0].computation = 'derived'
    derived.subjects[0].formulaText = '1月 6,000万元 + 2月 6,450万元 = 12,450万元'
    const [summed] = findValueMarks(text, derived, sources)
    expect(summed.card).toContain(`算式：${derived.subjects[0].formulaText}`)
    expect(plain.card).toContain('口径：sum(营收)')
    derived.subjects[0].formulaText = '2025年1—9月逐月比较，最高为2025年9月 12,450万元'
    expect(findValueMarks(text, derived, sources)[0].card).toContain(`取值：${derived.subjects[0].formulaText}`)
    const stale = validation('stale', 12780)
    stale.subjects[0].computation = 'derived'
    const [changed] = findValueMarks('华东营收为 12,780 万元。[[citation:sub-1]]', stale, sources)
    expect(changed.card[0]).toBe('! 需复核')
  })

  it('styles server-computed values apart from registered ones', () => {
    const inline = vi.spyOn(Decoration, 'inline')
    const view = fakeView('华东营收为 12,450 万元。[[citation:sub-1]]')
    const derived = validation('valid')
    derived.subjects[0].computation = 'derived'
    updateBodyValueMarks(view, derived, sources)
    const attributes = inline.mock.calls.at(-1)?.[2] as Record<string, string> | undefined
    expect(attributes?.class).toContain('report-value-mark--computed')
    expect(attributes?.['data-value-computed']).toBe('true')
    // 直接登记值不带计算标记。
    updateBodyValueMarks(view, validation('valid'), sources)
    const registered = inline.mock.calls.at(-1)?.[2] as Record<string, string> | undefined
    expect(registered?.class).not.toContain('report-value-mark--computed')
  })

  it('marks the cited number with its registered value and business name', () => {
    const text = '华东营收为 12,450 万元，同比增长 8.0%。[[citation:sub-1]]'
    const marks = findValueMarks(text, validation('valid'), sources)
    expect(marks).toHaveLength(1)
    expect(text.slice(marks[0].start, marks[0].end)).toBe('12,450 万元')
    expect(marks[0].state).toBe('valid')
    expect(marks[0].card).toEqual(expect.arrayContaining(['指标：华东营收', '登记值：12,450万元', '期间：2025年1月、2025年10月']))
  })

  it('writes periods the way readers do', () => {
    expect(periodListText(Array.from({ length: 9 }, (_, index) => `2025-0${index + 1}`))).toBe('2025年1—9月')
    expect(periodListText(['2024-11', '2024-12', '2025-01'])).toBe('2024年11月—2025年1月')
    expect(periodListText(['2025-09'])).toBe('2025年9月')
    // 同比的本期与基期分段书写；不连续的月份逐项列出；非逐月期间原样列出。
    expect(periodListText(['2025-01', '2025-02', '2024-01', '2024-02'])).toBe('2025年1—2月、2024年1—2月')
    expect(periodListText(['2025-01', '2025-03'])).toBe('2025年1月、2025年3月')
    expect(periodListText(['2025-09-01', '2025-09-02'])).toBe('2025-09-01、2025-09-02')
    expect(periodListText(['2025-13'])).toBe('2025-13')
    expect(periodListText(undefined)).toBe('')
  })

  it('shows semantic warnings without treating the matching value as an edited number', () => {
    const result = validation('valid')
    const warning = '业务范围需复核：登记范围为全院。'
    result.subjects[0].warnings = [warning]
    const text = '普通外科收入12,450万元[[citation:sub-1]]'
    const [mark] = findValueMarks(text, result)
    expect(mark.state).toBe('review')
    expect(mark.card).toContain('状态：数值一致，业务口径需复核')
    expect(mark.card).toContain(`提示：${warning}`)
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(view.state.doc.textContent).toBe(text)
  })

  it('keeps an edited value stale while displaying its semantic warnings', () => {
    const result = validation('stale', 12780)
    result.subjects[0].warnings = ['期间需复核']
    const [mark] = findValueMarks('营收12,780万元[[citation:sub-1]]', result)
    expect(mark.state).toBe('stale')
    expect(mark.card).toContain('提示：期间需复核')
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

  it.each([1.005, 2.675, -1.005])('matches server decimal rounding for %s', factValue => {
    const result = validation('valid')
    Object.assign(result.subjects[0], { factValue, unit: '元' })
    const written = factValue === 2.675 ? '2.68' : factValue < 0 ? '-1.01' : '1.01'
    expect(findValueMarks(`收入${written}元[[citation:sub-1]]`, result)[0]?.state).toBe('valid')
  })

  it.each([
    [-0.004, '0.00'], [-0.004, '-0.00'], [-0.4, '0'], [-0, '0.00'], [0, '-0.00'],
  ] as const)('matches zero after rounding %s to %s', (factValue, written) => {
    const result = validation('valid')
    Object.assign(result.subjects[0], { factValue, unit: '元' })
    expect(findValueMarks(`调整${written}元[[citation:sub-1]]`, result)[0]?.state).toBe('valid')
  })

  it.each([[-0.005, '0.01'], [0.005, '-0.01']] as const)(
    'preserves the sign of a nonzero rounded value %s against %s', (factValue, written) => {
      const result = validation('valid')
      Object.assign(result.subjects[0], { factValue, unit: '元' })
      expect(findValueMarks(`调整${written}元[[citation:sub-1]]`, result)).toEqual([])
    },
  )

  it('does not mark an opposite-sign number using the same absolute magnitude', () => {
    const result = validation('valid')
    Object.assign(result.subjects[0], { factValue: 10, unit: '元' })
    const text = '调整-10元，收入10元[[citation:sub-1]]'
    expect(findValueMarks(text, result).map(mark => text.slice(mark.start, mark.end))).toEqual(['10元'])
  })

  it('does not offer numeric restoration for a semantic-only edit', () => {
    const result = validation('stale')
    result.subjects[0].comparable = false
    const view = fakeView('成本12,450万元[[citation:sub-1]]')
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(view.state.doc.textContent).toBe('成本12,450万元[[citation:sub-1]]')
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

  it.each([
    { factValue: 2400, unit: '万元', draftValue: 2500, written: '2,500.00万元', restoreText: '2,400.00万元' },
    { factValue: 2400, unit: '万元', draftValue: 2500, written: '2,500万元', restoreText: '2,400.00万元' },
    { factValue: 0.505, unit: '元', draftValue: 0.52, written: '0.52元', restoreText: '0.51元' },
    { factValue: 240, unit: '万元', draftValue: 250, written: '250.000万元', restoreText: '240.00万元' },
    { factValue: 30, unit: '元/人次', draftValue: 31, written: '31元/人次', restoreText: '30元/人次' },
  ])('restores the signed display text $restoreText without reformatting', entry => {
    const result = validation('stale', entry.draftValue)
    Object.assign(result.subjects[0], entry, { comparable: true, draftUnit: entry.unit })
    const view = fakeView(`2025年10月收入${entry.written}[[citation:sub-1]]`)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(true)
    expect(view.state.doc.textContent).toBe(`2025年10月收入${entry.restoreText}[[citation:sub-1]]`)
  })

  it('preserves semantic-only edit protection even when a signed display text is available', () => {
    const result = validation('stale')
    Object.assign(result.subjects[0], { comparable: false, restoreText: '12,450.00万元' })
    const view = fakeView('成本12,450万元[[citation:sub-1]]')
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(view.state.doc.textContent).toBe('成本12,450万元[[citation:sub-1]]')
  })

  it.each(['下降', '减少了约', '回落 约'])(
    'restores a signed money magnitude after %s without adding a negative sign', verb => {
      const result = validation('stale', 3)
      Object.assign(result.subjects[0], { factValue: -2, unit: '元', draftUnit: '元', comparable: true, restoreText: '2元' })
      const text = `2025年10月收入${verb}3元[[citation:sub-1]]`
      const view = fakeView(text)
      expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(true)
      expect(view.state.doc.textContent).toBe(text.replace('3元', '2元'))
    },
  )

  it.each(['增长', '下降至', '为'])(
    'does not restore a signed positive magnitude after an unsupported direction %s', verb => {
      const result = validation('stale', 3)
      Object.assign(result.subjects[0], { factValue: -2, unit: '元', draftUnit: '元', comparable: true, restoreText: '2元' })
      const text = `2025年10月收入${verb}3元[[citation:sub-1]]`
      const view = fakeView(text)
      expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
      expect(view.state.doc.textContent).toBe(text)
    },
  )

  it('does not infer a decline magnitude from an old reference without a signed display text', () => {
    const result = validation('stale', 3)
    Object.assign(result.subjects[0], { factValue: -2, unit: '元', draftUnit: '元', comparable: true, restoreText: null })
    const view = fakeView('2025年10月收入下降3元[[citation:sub-1]]')
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
  })

  it('does not restore a negative signed display into a decline magnitude', () => {
    const result = validation('stale', -3)
    Object.assign(result.subjects[0], { factValue: -2, unit: '个百分点', draftUnit: '个百分点',
      comparable: true, draftDirection: 'decrease', restoreText: '-2.00个百分点' })
    const text = '2025年10月占比下降3个百分点[[citation:sub-1]]'
    const view = fakeView(text)
    expect(restoreRegisteredValue(view, 'sub-1', result)).toBe(false)
    expect(view.state.doc.textContent).toBe(text)
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

function unverifiedOriginal(originalText?: string | null, bound = true, occurrences = 1): TraceValidation {
  return { ...validation('valid'), subjects: [], summary: { valid: 0, stale: 0, unbound: 0 },
    reviewNotices: [{ claimId: 'original', sectionId: null, kind: 'numeric_unverified', originalText, bound, occurrences }] }
}

describe('original unverified values', () => {
  const text = '收入待核实[[claim:original]]。'
  it('shows the original spelling while keeping it unverified and without a fact binding', () => {
    const result = unverifiedOriginal('999,999.1234万元')
    const [mark] = findValueMarks(text, result)
    expect(mark.originalText).toBe('999,999.1234万元')
    expect(mark.state).toBe('unverified')
    expect(mark.subjectId).toBeUndefined()
    expect(mark.card).toContain('原始值：999,999.1234万元')
    expect(mark.card.join('')).toContain('尚未通过来源校验')
    expect(restoreRegisteredValue(fakeView(text), 'original', result)).toBe(false)
  })

  it.each([' ', '   ', '\t', '\u00a0', '\u3000', '\t \u00a0\u3000'])(
    'keeps an original value linked across horizontal whitespace %j', gap => {
      const marks = findValueMarks(`收入待核实${gap}[[claim:original]]。`, unverifiedOriginal('999元'))
      expect(marks).toHaveLength(1)
      expect(marks[0].originalText).toBe('999元')
      expect(marks[0].state).toBe('unverified')
    },
  )

  it.each(['\n', '\r\n', '\u2028', '\u2029', '另项', '，'])(
    'does not link an original value across a line or business text %j', gap => {
      expect(findValueMarks(`收入待核实${gap}[[claim:original]]。`, unverifiedOriginal('999元'))).toEqual([])
    },
  )

  it.each([undefined, null, ''])('does not invent an original value for an old notice (%s)', original => {
    const [mark] = findValueMarks(text, unverifiedOriginal(original))
    expect(mark.originalText).toBeUndefined()
    expect(mark.card).toContain('未保存原始值')
  })

  it('explains why a notice has no original value', () => {
    const result = unverifiedOriginal(null)
    result.reviewNotices![0].reason = '该指标没有登记这种取值方式（统计口径或期间）'
    const [mark] = findValueMarks(text, result)
    expect(mark.card).toContain('未保存原始值')
    expect(mark.card).toContain('原因：该指标没有登记这种取值方式（统计口径或期间）')
  })

  it.each([[false, 1], [false, 2], [true, 2]] as const)('hides ambiguous original values (bound=%s, occurrences=%s)', (bound, occurrences) => {
    expect(findValueMarks(text, unverifiedOriginal('999元', bound, occurrences))[0].originalText).toBeUndefined()
  })

  it('does not duplicate an original value when a marker is copied in the current block', () => {
    const marks = findValueMarks(text + text, unverifiedOriginal('999元'))
    expect(marks).toHaveLength(2)
    expect(marks.every(mark => mark.originalText === undefined)).toBe(true)
  })

  it('keeps originals attached to their own notices', () => {
    const result = unverifiedOriginal('999元')
    result.reviewNotices!.push({ claimId: 'other', sectionId: null, kind: 'numeric_unverified', originalText: '888人次', bound: true, occurrences: 1 })
    const marks = findValueMarks(text + '门诊待核实[[claim:other]]', result)
    expect(marks.map(mark => mark.originalText)).toEqual(['999元', '888人次'])
  })

  it('renders the original as plain text without writing it into the document', () => {
    const raw = '<img src=x onerror=alert(1)>999元'
    const widget = vi.spyOn(Decoration, 'widget')
    const inline = vi.spyOn(Decoration, 'inline')
    const view = fakeView(text)
    const before = view.state.doc.toJSON()
    updateBodyValueMarks(view, unverifiedOriginal(raw))
    expect(widget).toHaveBeenCalledTimes(1)
    const factory = widget.mock.calls[0][1]
    expect(typeof factory).toBe('function')
    if (typeof factory !== 'function') throw new Error('expected widget factory')
    const element = factory(view, () => 1) as HTMLElement
    // 原始值替代“待核实”显示，句子不被分隔符打断；“待核实”字样随之收起。
    expect(element.textContent).toBe(raw)
    expect(element.classList.contains('report-original-value')).toBe(true)
    expect(element.classList.contains('report-value-mark--collapsed')).toBe(false)
    const highlight = inline.mock.calls.at(-1)?.[2] as Record<string, string> | undefined
    expect(highlight?.class).toContain('report-value-mark--collapsed')
    expect(element.querySelector('img')).toBeNull()
    expect(element.contentEditable).toBe('false')
    expect(view.state.doc.toJSON()).toEqual(before)
    expect(view.state.doc.textContent).not.toContain('999元')
  })
})
