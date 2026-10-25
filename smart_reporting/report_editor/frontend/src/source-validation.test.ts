import { describe, expect, it, vi } from 'vitest'

import type { TraceValidation } from './api'
import { findValueMarks } from './body-value-marks'
import { checkNeedsReview, createSourceValidationController, markdownSha256, nextSourceIssue, notEvaluatedQualityCount, semanticReviewGroupCount, sourceCoverageSummary, sourceValidationIssueCount } from './source-validation'

const validation = (draftSha256: string): TraceValidation => ({
  draftSha256,
  subjects: [],
  summary: { valid: 0, stale: 0, unbound: 0 },
})

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('source validation', () => {
  it('counts server-computed values among the traceable ones', () => {
    const result = validation('draft')
    result.summary.valid = 3
    result.subjects = [
      { subjectId: 's1', claimId: 'c1', sectionId: null, status: 'valid', factValue: 20, computation: 'registered' },
      { subjectId: 's2', claimId: 'c2', sectionId: null, status: 'valid', factValue: 30, computation: 'calc' },
      { subjectId: 's3', claimId: 'c3', sectionId: null, status: 'valid', factValue: 40, computation: 'derived' },
    ]
    expect(sourceCoverageSummary(result, '').text).toBe('可溯源 3/3（服务端计算 2）')
    // 表格单元格同一口径：已核对表格中由服务端派生的单元格计入，改动过的不计。
    const location = { rowKey: 'r', columnKey: 'c', rowIndex: 0, columnIndex: 1, rowLabel: '1月', text: '1', computation: 'derived' as const }
    result.tables = [{ tableId: 't', cells: { valid: 1, stale: 1, unbound: 0 }, dataCheck: { status: 'verified', scope: 'frozen_cells', reasons: [] },
      locations: [{ ...location, status: 'valid' }, { ...location, rowKey: 'r2', status: 'stale' }] }]
    result.tableSummary = { valid: 1, stale: 1, unbound: 0, insertedRows: 0, copiedCells: 0 }
    expect(sourceCoverageSummary(result, '').text).toContain('（服务端计算 3）')
  })

  it('separates diagnostics the checker could not evaluate from findings to confirm', () => {
    const result = validation('draft')
    result.summary.valid = 1
    result.subjects = [{ subjectId: 's1', claimId: 'c1', sectionId: null, status: 'valid', factValue: 20 }]
    result.quality = { status: 'evaluated', allKeyFactsEvaluated: false, inputSha256: 'current', issues: [
      { code: 'assertion_support_unknown', subjectId: 's1', reasons: ['scope_unknown'] },
      { code: 'assertion_support_unknown', subjectId: 's2', reasons: ['operation_semantics_not_evaluated', 'scope_unknown'] },
      { code: 'chart_support_unknown', subjectId: 'chart1', reasons: ['interactive_spec_unregistered'] },
    ] }
    // 回放：400 余条“范围未确认/运算未评估/图表未核对”曾计入语义待确认，淹没真正的提醒。
    expect(notEvaluatedQualityCount(result)).toBe(3)
    expect(semanticReviewGroupCount(result)).toBe(0)
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 1/1 · 未自动核对 3', state: 'valid' })
    // 只要有一个理由不是“未评估”，仍按语义待确认处理。
    result.quality.issues[1].reasons = ['scope_unknown', 'statement_not_supported']
    expect(semanticReviewGroupCount(result)).toBe(1)
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 1/1 · 语义待确认 1组 · 未自动核对 2', state: 'stale' })
  })

  it('shows unresolved business support even when the source value remains traceable', () => {
    const result = validation('draft')
    result.summary.valid = 1
    result.subjects = [{ subjectId: 's1', claimId: 'c1', sectionId: null, status: 'valid', factValue: 20 }]
    result.quality = { status: 'evaluated', allKeyFactsEvaluated: false, inputSha256: 'current', issues: [
      { code: 'assertion_support_unknown', subjectId: 's1', reasons: ['statement_not_supported'] },
      { code: 'assertion_support_unknown', subjectId: 's2', reasons: ['statement_not_supported'] },
    ], warningLedger: { qualityInputSha256: 'current', originalIssueCount: 2, groups: [{ groupId: 'same-fact', issueIndices: [0, 1] }] } }
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 1/1 · 语义待确认 1组', state: 'stale' })
    expect(sourceValidationIssueCount(result)).toBe(0)
    result.quality.warningLedger!.qualityInputSha256 = 'old'
    expect(semanticReviewGroupCount(result)).toBe(2)
    result.quality.warningLedger!.qualityInputSha256 = 'current'
    result.quality.warningLedger!.groups = []
    expect(semanticReviewGroupCount(result)).toBe(2)
  })

  it('retains unregistered tables and unknown future diagnostics without duplicating chart dependencies', () => {
    const result = validation('draft')
    result.summary.valid = 1
    result.subjects = [{ subjectId: 's1', claimId: 'c1', sectionId: null, status: 'valid', factValue: 20, warnings: ['period warning'] }]
    result.tables = [{ tableId: 't1', cells: { valid: 1, stale: 0, unbound: 0 },
      dataCheck: { status: 'unknown', scope: 'frozen_cells', reasons: ['cell_period_label_mismatch'] } }]
    result.charts = [{ chartId: 'chart1', imagePath: 'chart.png', status: 'valid',
      dataCheck: { status: 'unknown', scope: 'registered_arrays', reason: 'interactive_spec_unregistered' } }]
    result.quality = { status: 'evaluated', allKeyFactsEvaluated: false, issues: [
      { code: 'chart_support_unknown', subjectId: 'chart1' },
      { code: 'chart_semantic_alignment_unknown', subjectId: 'chart1' },
      { code: 'assertion_support_unknown', subjectId: 's1' },
      { code: 'table_support_unknown', subjectId: 't1' },
      { code: 'table_coverage_unknown', subjectId: 'markdown-table:L362' },
      { code: 'future_check' },
    ] }
    expect(sourceValidationIssueCount(result)).toBe(3)
    expect(semanticReviewGroupCount(result)).toBe(2)
    expect(sourceCoverageSummary(result, '').state).toBe('stale')
  })

  it('does not turn unreviewed answer coverage into a successful report', () => {
    const result = validation('draft')
    result.quality = { status: 'evaluated', allKeyFactsEvaluated: false, issues: [],
      questionCoverage: { required: 1, evaluated: 0, answered: 0, effectiveAnswerRate: null, evaluationStatus: 'not_fully_evaluated' } }
    expect(sourceCoverageSummary(result, '').text).toContain('回答覆盖待核验')
    expect(sourceCoverageSummary(result, '').state).toBe('stale')
    result.quality.questionCoverage = { required: 1, evaluated: 1, answered: 0, effectiveAnswerRate: 0, evaluationStatus: 'evaluated' }
    expect(sourceCoverageSummary(result, '').text).toContain('已核验回答 0/1')
    result.quality.questionCoverage.answered = 1
    result.quality.questionCoverage.effectiveAnswerRate = 1
    expect(sourceCoverageSummary(result, '').text).toContain('已核验回答 1/1')
    expect(sourceCoverageSummary(result, '').state).toBe('unknown')
  })

  it('keeps a matching array pending when its metric identity conflicts', () => {
    const result = validation('draft')
    result.charts = [{ chartId: 'chart1', imagePath: 'chart1.png', status: 'valid',
      dataCheck: { status: 'verified', scope: 'registered_arrays', reason: 'registered_arrays_match' },
      semanticCheck: { status: 'conflicting', scope: 'registered_fact_projection', reasons: ['chart_fact_projection_mismatch'] } }]
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 0/1 · 待复核 1', state: 'stale' })
    result.charts[0].semanticCheck!.status = 'verified'
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 1/1', state: 'valid' })
  })

  it('keeps table source binding separate from frozen cell verification', () => {
    const result = validation('draft')
    result.tableSummary = { valid: 2, stale: 0, unbound: 0, insertedRows: 0, copiedCells: 0 }
    result.tables = [{ tableId: 'table1', cells: { valid: 2, stale: 0, unbound: 0 },
      dataCheck: { status: 'unknown', scope: 'frozen_cells', reasons: ['cell_period_binding_mismatch'] } }]
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 0/2 · 待复核 1', state: 'stale' })
    result.tables[0].dataCheck!.status = 'verified'
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 2/2', state: 'valid' })
  })

  it('keeps source failures and unavailable semantic checks visible with no bound subjects', () => {
    const result = validation('draft')
    result.sourceIssues = [{ resourceId: 'source', code: 'snapshot_integrity_failed' }]
    result.quality = { status: 'failed', allKeyFactsEvaluated: false, issues: [{ code: 'quality_evaluation_unavailable' }] }
    expect(sourceCoverageSummary(result, '')).toEqual({
      text: '当前内容无精确来源绑定 · 来源异常 1 · 语义检查暂不可用', state: 'stale',
    })
  })
  it('separates content warnings from source binding issues', () => {
    const result = validation('draft')
    result.warnings = ['金额单位换算不一致']
    expect(sourceValidationIssueCount(result)).toBe(0)
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '当前内容无精确来源绑定 · 内容提示 1', state: 'stale' })
  })
  it('counts deleted or stale charts alongside claim and table issues', () => {
    const result = validation('draft')
    result.charts = [
      { chartId: 'chart1', imagePath: 'chart1.png', status: 'valid', dataCheck: { status: 'verified', scope: 'registered_arrays', reason: 'registered_arrays_match' }, semanticCheck: { status: 'verified', scope: 'registered_fact_projection', reasons: [] } },
      { chartId: 'chart2', imagePath: 'chart2.png', status: 'unbound' },
      { chartId: 'chart3', imagePath: 'chart3.png', status: 'stale' },
    ]
    expect(sourceValidationIssueCount(result)).toBe(2)
    result.summary.stale = 1
    result.tableSummary = { valid: 1, stale: 1, unbound: 0, insertedRows: 0, copiedCells: 0 }
    expect(sourceValidationIssueCount(result)).toBe(4)
    delete result.charts
    expect(sourceValidationIssueCount(result)).toBe(2)
  })

  it('counts valid claims with semantic warnings once without hiding table issues', () => {
    const result = validation('draft')
    result.subjects = [{
      subjectId: 's1', claimId: 'c1', sectionId: null, status: 'valid', factValue: 3600,
      warnings: ['unit changed', 'period changed'],
    }]
    result.summary.valid = 1
    expect(sourceValidationIssueCount(result)).toBe(1)
    result.tableSummary = { valid: 1, stale: 1, unbound: 0, insertedRows: 0, copiedCells: 1 }
    expect(sourceValidationIssueCount(result)).toBe(3)
    delete result.subjects[0].warnings
    expect(sourceValidationIssueCount(result)).toBe(2)
  })

  it('hashes the actual Markdown bytes', async () => {
    expect(await markdownSha256('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
  })

  it('hashes Markdown on HTTP origins without Web Crypto', async () => {
    const original = crypto.subtle
    Object.defineProperty(globalThis.crypto, 'subtle', { configurable: true, value: undefined })
    try {
      await expect(markdownSha256('abc')).resolves.toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
    } finally {
      Object.defineProperty(globalThis.crypto, 'subtle', { configurable: true, value: original })
    }
  })

  it('accepts only the current draft when requests resolve out of order', async () => {
    let markdown = 'first'
    const first = deferred<TraceValidation>()
    const second = deferred<TraceValidation>()
    const validateSources = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const onResult = vi.fn()
    const onChecking = vi.fn()
    const controller = createSourceValidationController({ validateSources }, () => markdown, onResult, onChecking, 10)

    controller.schedule()
    await vi.waitFor(() => expect(validateSources).toHaveBeenCalledTimes(1))
    markdown = 'second'
    controller.schedule()
    await vi.waitFor(() => expect(validateSources).toHaveBeenCalledTimes(2))
    second.resolve(validation(await markdownSha256('second')))
    await vi.waitFor(() => expect(onResult).toHaveBeenCalledTimes(1))
    first.resolve(validation(await markdownSha256('first')))
    await Promise.resolve()

    expect(onChecking).toHaveBeenCalledTimes(2)
    expect(onResult).toHaveBeenCalledTimes(1)
    expect(onResult).toHaveBeenCalledWith(validation(await markdownSha256('second')))
    expect(validateSources.mock.calls[0][2].aborted).toBe(true)
  })

  it('does not report an old failure after the Markdown changes without another schedule', async () => {
    let markdown = 'first'
    let reject!: (reason: Error) => void
    const response = new Promise<TraceValidation>((_resolve, fail) => { reject = fail })
    const validateSources = vi.fn().mockReturnValue(response)
    const onResult = vi.fn()
    const controller = createSourceValidationController({ validateSources }, () => markdown, onResult, vi.fn(), 10)
    controller.schedule()
    await vi.waitFor(() => expect(validateSources).toHaveBeenCalledTimes(1))
    markdown = 'changed'
    reject(new Error('network'))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(onResult).not.toHaveBeenCalled()
    controller.cancel()
  })

  it('shows unknown for a current request failure', async () => {
    const validateSources = vi.fn().mockRejectedValue(new Error('network'))
    const onResult = vi.fn()
    const controller = createSourceValidationController({ validateSources }, () => 'current', onResult, vi.fn(), 10)
    controller.schedule()
    await vi.waitFor(() => expect(onResult).toHaveBeenCalledWith(null))
    controller.cancel()
  })

  it('reports the validation failure so the UI can show its cause', async () => {
    const error = new Error('network')
    const validateSources = vi.fn().mockRejectedValue(error)
    const onError = vi.fn()
    const controller = createSourceValidationController({ validateSources }, () => 'current', vi.fn(), vi.fn(), 10, onError)
    controller.schedule()
    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith(error))
    controller.cancel()
  })

  it('clears the previous result before showing an error so the cause remains visible', async () => {
    const error = new Error('source_missing: request-123')
    let status = '来源校验中'
    const events: string[] = []
    const controller = createSourceValidationController(
      { validateSources: vi.fn().mockRejectedValue(error) }, () => 'current',
      result => { expect(result).toBeNull(); status = '来源暂无法校验'; events.push('result') },
      vi.fn(), 10,
      failure => { status = (failure as Error).message; events.push('error') },
    )
    controller.schedule()
    await vi.waitFor(() => expect(events).toEqual(['result', 'error']))
    expect(status).toBe('source_missing: request-123')
    controller.cancel()
  })

  it('ignores a mismatched response digest and cancels a pending check', async () => {
    const validateSources = vi.fn().mockResolvedValue(validation('0'.repeat(64)))
    const onResult = vi.fn()
    const controller = createSourceValidationController({ validateSources }, () => 'current', onResult, vi.fn(), 10)
    controller.schedule()
    await vi.waitFor(() => expect(validateSources).toHaveBeenCalledTimes(1))
    await vi.waitFor(() => expect(onResult).not.toHaveBeenCalled())
    controller.schedule()
    controller.cancel()
    expect(validateSources).toHaveBeenCalledTimes(1)
  })
})

describe('source coverage summary', () => {
  it('does not count an unchanged chart caption as verified data', () => {
    const result = validation('draft')
    result.charts = [{ chartId: 'chart', imagePath: 'chart.png', status: 'valid' }]
    expect(sourceValidationIssueCount(result)).toBe(1)
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 0/1 · 待复核 1', state: 'stale' })
    result.charts[0].dataCheck = { status: 'unknown', scope: 'registered_arrays', reason: 'chart_source_unavailable' }
    expect(sourceValidationIssueCount(result)).toBe(1)
    result.charts[0].dataCheck = { status: 'verified', scope: 'registered_arrays', reason: 'registered_arrays_match' }
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 0/1 · 待复核 1', state: 'stale' })
    result.charts[0].semanticCheck = { status: 'verified', scope: 'registered_fact_projection', reasons: [] }
    expect(sourceCoverageSummary(result, '')).toEqual({ text: '可溯源 1/1', state: 'valid' })
  })
  it('summarises traceable, review and unverified counts', () => {
    const result: TraceValidation = {
      draftSha256: 'x',
      subjects: [
        { subjectId: 'a', claimId: 'a', sectionId: null, status: 'valid', factValue: 1 },
        { subjectId: 'b', claimId: 'b', sectionId: null, status: 'stale', factValue: 2 },
      ],
      summary: { valid: 1, stale: 1, unbound: 0 },
      tableSummary: { valid: 3, stale: 0, unbound: 0, insertedRows: 0, copiedCells: 0 },
      charts: [{ chartId: 'c', imagePath: null, status: 'valid', dataCheck: { status: 'verified', scope: 'registered_arrays', reason: 'registered_arrays_match' }, semanticCheck: { status: 'verified', scope: 'registered_fact_projection', reasons: [] } }],
    }
    expect(sourceCoverageSummary(result, '收入待核实，利润待核实')).toEqual({ text: '可溯源 5/6 · 待复核 1 · 待核实数值 2', state: 'stale' })
    expect(sourceCoverageSummary({ ...result, subjects: [], summary: { valid: 0, stale: 0, unbound: 0 }, tableSummary: undefined, charts: [] }, ''))
      .toEqual({ text: '当前内容无精确来源绑定', state: 'unknown' })
  })

  it('counts only visible numerical placeholders', () => {
    const result = validation('draft')
    const visible = '执行率约待核实。金额单位待核实，零值原因待核实。'
    expect(sourceCoverageSummary(result, visible)).toEqual({
      text: '当前内容无精确来源绑定 · 待核实数值 1', state: 'stale',
    })
  })

  it('cycles through issue positions in document order', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p><span class="report-value-mark report-value-mark--valid">1</span><span id="a" class="report-value-mark report-value-mark--stale">2</span></p>' +
      '<p><span id="b" class="report-value-mark report-value-mark--unverified">待核实</span><span id="c" class="report-object-source-marker" data-marker-state="stale"></span></p>'
    document.body.append(root)
    const order = [...root.querySelectorAll<HTMLElement>('span')]
    const position = (element: HTMLElement) => order.indexOf(element)
    expect(nextSourceIssue(root, null, position)?.id).toBe('a')
    expect(nextSourceIssue(root, position(root.querySelector('#a')!), position)?.id).toBe('b')
    expect(nextSourceIssue(root, position(root.querySelector('#c')!), position)?.id).toBe('a')
    expect(nextSourceIssue(document.createElement('div'), null, position)).toBeNull()
    root.remove()
  })

  it('locates stale citations without draft values, including grouped analysis/citation markers', () => {
    const root = document.createElement('div')
    const add = (id: string, references: Array<{ kind: string; value: string }>) => {
      const marker = document.createElement('span')
      marker.id = id
      marker.className = 'report-protocol-marker report-citation-marker'
      marker.dataset.markerReferences = JSON.stringify(references)
      root.append(marker)
    }
    add('valid', [{ kind: 'citation', value: 'valid' }])
    add('stale', [{ kind: 'citation', value: 'a' }])
    add('group', [{ kind: 'analysis', value: 'analysis' }, { kind: 'citation', value: 'valid' }, { kind: 'citation', value: 'b' }])
    const result = validation('draft')
    result.summary.stale = 2
    result.subjects = ['a', 'b'].map(subjectId => ({ subjectId, claimId: subjectId, sectionId: null, status: 'stale', factValue: 1 }))
    expect(findValueMarks('提高2个百分点。[[citation:a]]', result)).toEqual([])
    const position = (element: HTMLElement) => [...root.children].indexOf(element)
    expect(nextSourceIssue(root, null, position, result)?.id).toBe('stale')
    expect(nextSourceIssue(root, 1, position, result)?.id).toBe('group')
    expect(nextSourceIssue(root, 2, position, result)?.id).toBe('stale')
    expect(nextSourceIssue(root, null, position, null)).toBeNull()
    result.subjects.forEach(subject => { subject.status = 'valid' })
    expect(nextSourceIssue(root, null, position, result)).toBeNull()
  })

  it('prefers the marked value over its fallback citation', () => {
    const root = document.createElement('div')
    root.innerHTML = '<span id="value" class="report-value-mark--stale" data-value-subject="a">2</span>' +
      '<span id="citation" class="report-protocol-marker" data-marker-references=\'[{"kind":"citation","value":"a"}]\'></span>' +
      '<span id="other" class="report-value-mark--unverified">待核实</span>'
    const result = validation('draft')
    result.subjects = [{ subjectId: 'a', claimId: 'a', sectionId: null, status: 'stale', factValue: 1, draftValue: 2 }]
    const position = (element: HTMLElement) => [...root.children].indexOf(element)
    expect(nextSourceIssue(root, null, position, result)?.id).toBe('value')
    expect(nextSourceIssue(root, 0, position, result)?.id).toBe('other')
    expect(nextSourceIssue(root, 2, position, result)?.id).toBe('value')
  })
})

it('excludes explanatory uncertainty from numeric counts and navigation', () => {
  const text = '是否涉及跨期结算或集中入账待核实。零值原因待核实。数据完整性待核实。执行率约待核实。'
  expect(sourceCoverageSummary(validation('x'), text).text).toBe('当前内容无精确来源绑定 · 待核实数值 1')
  expect(findValueMarks(text, validation('x')).map(mark => text.slice(mark.start, mark.end))).toEqual(['待核实'])
})

it('locates present unbound charts in order without inventing source links', () => {
  const root = document.createElement('div')
  root.innerHTML = '<p id="first"><img src="chart-013.png"></p>' +
    '<p><span id="stale" class="report-object-source-marker" data-marker-state="stale"></span></p>' +
    '<p id="last"><img src="chart-014.png"></p>'
  const result = validation('x')
  result.charts = [
    { chartId: 'missing-2', imagePath: 'chart-014.png', locationSource: 'chart-014.png', status: 'unbound' },
    { chartId: 'missing-1', imagePath: 'chart-013.png', locationSource: 'chart-013.png', status: 'unbound' },
    { chartId: 'deleted', imagePath: 'chart-015.png', locationSource: null, status: 'unbound' },
  ]
  const order = ['first', 'stale', 'last']
  const position = (element: HTMLElement) => order.indexOf(element.id)
  expect(nextSourceIssue(root, null, position, result)?.id).toBe('first')
  expect(nextSourceIssue(root, 0, position, result)?.id).toBe('stale')
  expect(nextSourceIssue(root, 1, position, result)?.id).toBe('last')
  expect(nextSourceIssue(root, 2, position, result)?.id).toBe('first')
})

it('counts typed numeric placeholders independently of visible wording', () => {
  const result = validation('draft')
  result.reviewNotices = [
    { claimId: 'note', sectionId: null, kind: 'source_review', occurrences: 1, bound: true },
    { claimId: 'number', sectionId: null, kind: 'numeric_unverified', occurrences: 2, bound: false },
  ]
  expect(sourceCoverageSummary(result, '任意业务描述待核实').text).toContain('待核实数值 2')
  expect(sourceCoverageSummary(result, '任意业务描述待核实').text).toContain('文字待确认 1')
  result.reviewNotices = []
  expect(sourceCoverageSummary(result, '任意业务描述待核实').text).not.toContain('待核实数值')
})

it('does not count the original-value widget as another review location', () => {
  const root = document.createElement('div')
  root.innerHTML = '<span class="report-value-mark--unverified report-original-value" data-pos="1">999元 · </span><span class="report-value-mark--unverified" data-pos="2">待核实</span>'
  const position = (element: HTMLElement) => Number(element.dataset.pos)
  expect(nextSourceIssue(root, null, position)?.dataset.pos).toBe('2')
  expect(nextSourceIssue(root, 2, position)?.dataset.pos).toBe('2')
})

it('locates a valid claim with business warnings using its citation', () => {
  const result = validation('draft')
  result.summary.valid = 1
  result.subjects = [{ subjectId: 'a', claimId: 'a', sectionId: null, status: 'valid',
    factValue: 30, warnings: ['业务范围需复核'] }]
  const root = document.createElement('div')
  const marker = document.createElement('span')
  marker.className = 'report-protocol-marker'
  marker.dataset.markerReferences = JSON.stringify([{ kind: 'citation', value: 'a' }])
  root.append(marker)
  expect(sourceCoverageSummary(result, '').text).toContain('待复核 1')
  expect(nextSourceIssue(root, null, () => 1, result)).toBe(marker)
})

it('navigates review marks once each without stopping again at their citations', () => {
  const result = validation('draft')
  result.subjects = [{ subjectId: 'a', claimId: 'a', sectionId: null, status: 'valid',
    factValue: 30, warnings: ['期间需复核'] }]
  const root = document.createElement('div')
  root.innerHTML = '<span id="value" class="report-value-mark--review" data-value-subject="a">30元</span>' +
    '<span class="report-protocol-marker" data-marker-references=\'[{"kind":"citation","value":"a"}]\'></span>' +
    '<span id="other" class="report-value-mark--unverified">待核实</span>'
  const position = (element: HTMLElement) => [...root.children].indexOf(element)
  expect(nextSourceIssue(root, null, position, result)?.id).toBe('value')
  expect(nextSourceIssue(root, 0, position, result)?.id).toBe('other')
  expect(nextSourceIssue(root, 2, position, result)?.id).toBe('value')
})

describe('unevaluated data checks', () => {
  it('does not mark unchanged static charts or unregistered tables as needing review', () => {
    // 审阅：静态 PNG 与未登记表格的核对结果永远是 unknown，未改动的来源被显示为“待复核”并计入问题。
    const result = validation('draft')
    result.tables = [{ tableId: 't', cells: { valid: 1, stale: 0, unbound: 0 },
      dataCheck: { status: 'unknown', scope: 'frozen_cells', reasons: ['table_unregistered'] } }]
    result.charts = [{ chartId: 'c', imagePath: 'c.png', status: 'valid',
      dataCheck: { status: 'unknown', scope: 'registered_arrays', reason: 'static_image_not_evaluated' },
      semanticCheck: { status: 'unknown', scope: 'registered_fact_projection', reasons: ['chart_semantics_unregistered'] } }]
    expect(sourceValidationIssueCount(result)).toBe(0)
    result.charts[0].dataCheck = { status: 'unknown', scope: 'registered_arrays', reason: 'chart_input_projection_mismatch' }
    expect(sourceValidationIssueCount(result)).toBe(1)
    expect(checkNeedsReview({ status: 'conflicting', reasons: ['chart_semantics_unregistered'] })).toBe(true)
  })
})
