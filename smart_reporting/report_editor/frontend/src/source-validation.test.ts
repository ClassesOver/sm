import { describe, expect, it, vi } from 'vitest'

import type { TraceValidation } from './api'
import { createSourceValidationController, markdownSha256, nextSourceIssue, sourceCoverageSummary, sourceValidationIssueCount } from './source-validation'

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
  it('counts amount conversion warnings even without a nearby claim binding', () => {
    const result = validation('draft')
    result.warnings = ['金额单位换算不一致']
    expect(sourceValidationIssueCount(result)).toBe(1)
  })
  it('counts deleted or stale charts alongside claim and table issues', () => {
    const result = validation('draft')
    result.charts = [
      { chartId: 'chart1', imagePath: 'chart1.png', status: 'valid' },
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
  it('summarises traceable, review and unverified counts', () => {
    const result: TraceValidation = {
      draftSha256: 'x',
      subjects: [
        { subjectId: 'a', claimId: 'a', sectionId: null, status: 'valid', factValue: 1 },
        { subjectId: 'b', claimId: 'b', sectionId: null, status: 'stale', factValue: 2 },
      ],
      summary: { valid: 1, stale: 1, unbound: 0 },
      tableSummary: { valid: 3, stale: 0, unbound: 0, insertedRows: 0, copiedCells: 0 },
      charts: [{ chartId: 'c', imagePath: null, status: 'valid' }],
    }
    expect(sourceCoverageSummary(result, '收入待核实，利润待核实')).toEqual({ text: '可溯源 5/6 · 待复核 1 · 待核实 2', state: 'stale' })
    expect(sourceCoverageSummary({ ...result, subjects: [], summary: { valid: 0, stale: 0, unbound: 0 }, tableSummary: undefined, charts: [] }, ''))
      .toEqual({ text: '当前内容无精确来源绑定', state: 'unknown' })
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
})
