import { describe, expect, it } from 'vitest'

import type { TraceSources, TraceValidation } from './api'
import { buildTraceListCsv, csvCell } from './trace-list'

const sources = {
  available: true,
  subjects: [
    { subjectId: 'sub-a', subjectKind: 'text_claim', locator: {}, factRefs: [{ analysisId: 'a', factId: 'f' }], computationId: null },
    { subjectId: 'sub-b', subjectKind: 'table_cell', locator: { tableId: 't', rowKey: 'period:2025-01', columnKey: 'c' }, factRefs: [{ analysisId: 'a', factId: 'f' }], computationId: null },
  ],
  facts: [{ analysisId: 'a', factId: 'f', factKind: 'metric', label: 'revenue', name: '华东营收', unit: '万元', displayValue: 12450, datasetIds: ['d'], periodStart: '2025-01', periodEnd: '2025-10' }],
  datasets: [{ datasetId: 'd', sourceType: 'csv', requirementId: 'r', filename: '收入.csv', businessLabel: '收入台账', rowCount: 1200, size: 1, materializedAt: null, periodRoles: ['current'], queryWindowId: 'current' }],
} as unknown as TraceSources

const validation: TraceValidation = {
  draftSha256: 'x', summary: { valid: 0, stale: 1, unbound: 0 },
  subjects: [{ subjectId: 'sub-a', claimId: 'c', sectionId: null, status: 'stale', factValue: 12450, unit: '万元', draftValue: 12780, periods: ['2025-01', '2025-10'], formulaText: '营收 求和' }],
  tables: [{ tableId: 't', cells: { valid: 1, stale: 0, unbound: 0 }, locations: [{ status: 'valid', rowKey: 'period:2025-01', columnKey: 'c', rowIndex: 0, columnIndex: 1, rowLabel: '1月', text: '1,200' }] }],
}

describe('trace list csv', () => {
  it('lists each registered source with body context, values and snapshot', () => {
    const markdown = '# 报告\n\n## 核心结论\n\n上年持平。华东营收为 12,780 万元，增长较快。[[citation:sub-a]]\n'
    const csv = buildTraceListCsv(markdown, sources, validation)
    expect(csv.startsWith('﻿序号,章节,正文语句,来源,指标,正文值,登记值')).toBe(true)
    const lines = csv.slice(1).trim().split('\r\n')
    expect(lines).toHaveLength(3)
    expect(lines[1]).toBe('1,核心结论,"华东营收为 12,780 万元，增长较快。",正文引用 · 华东营收 #a,华东营收,"12,780万元","12,450万元",2025年1月、2025年10月,营收 求和,需复核,收入台账,1200,,sub-a')
    expect(lines[2]).toContain(',表格单元格,')
    expect(lines[2]).toContain(',与登记值一致,')
  })

  it('reports unvalidated sources without inventing a status', () => {
    const csv = buildTraceListCsv('', sources, null)
    expect(csv).toContain(',未校验,')
  })

  it('escapes quotes and neutralises spreadsheet formulas but keeps negative numbers', () => {
    expect(csvCell('a"b')).toBe('"a""b"')
    expect(csvCell('=SUM(A1)')).toBe("'=SUM(A1)")
    expect(csvCell('-cmd')).toBe("'-cmd")
    expect(csvCell('-3.5')).toBe('-3.5')
    expect(csvCell(null)).toBe('')
  })

  it.each([
    ['-1+SUM(A1)', "'-1+SUM(A1)"],
    ['-1+cmd|...', "'-1+cmd|..."],
    ['-.+1', "'-.+1"],
    ['-1e2+3', "'-1e2+3"],
    ['-', "'-"],
    ['-1\n', '"\'-1\n"'],
    ['-1+SUM(A1,B1)', '"\'-1+SUM(A1,B1)"'],
  ])('neutralises the complete minus-leading cell %j', (text, expected) => {
    expect(csvCell(text)).toBe(expected)
  })

  it.each(['-123', '-3.5', '-.5', '-1.', '-1e-2', '-1E+3'])('keeps the negative numeric literal %s', (text) => {
    expect(csvCell(text)).toBe(text)
  })
})
