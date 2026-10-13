import { describe, expect, it } from 'vitest'
import { renderEvidenceNotes } from './evidence-notes'

const notes = [
  '期间索引存在重复，行级 ACF/PACF 和季节性统计已禁用；需先按月及组织粒度聚合。',
  '[company] has a constant value',
  '[area] is highly overall correlated with [stlevel_analytic_unit] and 1 other fields',
  '[stlevel_analytic_unit] is highly overall correlated with [area] and 3 other fields',
  '[income_type] is highly overall correlated with [stlevel_analytic_unit] and 1 other fields',
  '[rdlevel_analytic_unit] is highly overall correlated with [area] and 3 other fields',
  '[analytic_unit_classification] is highly overall correlated with [stlevel_analytic_unit] and 1 other fields',
  '[analytic_unit_classification] is highly imbalanced (0.8827529713824287)',
  '[rdlevel_analytic_unit] 23646 (78.7%) missing values',
  '固定范围 income_nature=开单收入 已由受审核 SQL 应用，CSV 未投影该范围字段。',
]

describe('evidence diagnostic presentation', () => {
  it('keeps missing department data prominent while grouping scope and distribution notes', () => {
    const root = renderEvidenceNotes(notes)!
    const warnings = root.querySelector('[data-note-kind="warnings"]')!
    expect(warnings.textContent).toContain('数据限制（1）')
    expect(warnings.textContent).toContain('三级科室缺失 23,646 条（78.7%）')
    expect(warnings.textContent).toContain('三级科室下钻')
    expect(warnings.textContent).not.toContain('constant')
    expect(warnings.hasAttribute('open')).toBe(true)
    const context = root.querySelector('[data-note-kind="context"]')!
    expect(context.hasAttribute('open')).toBe(false)
    expect(context.textContent).toContain('医院字段只有一个取值')
    expect(context.textContent).toContain('收入性质=开单收入')
    expect(context.textContent).toContain('分布集中')
    expect(context.textContent).not.toContain('88.27%')
    expect(context.querySelectorAll('[data-note-type="correlation"]')).toHaveLength(1)
    const method = root.querySelector('[data-note-kind="method"]')!
    expect(method.textContent).toContain('连续性和期间长度')
    expect(method.textContent).toContain('不等同于重复记录')
    for (const note of notes) expect(root.querySelector('[data-note-kind="raw"]')?.textContent).toContain(note)
  })

  it('keeps unknown alerts and unexpected constant metrics as warnings without claiming verification', () => {
    const root = renderEvidenceNotes(['口径与上期不一致', '[revenue] has a constant value', '固定范围 income_nature=开单收入 未应用', '[revenue] is highly overall correlated with [cost] and 1 other fields'])!
    expect(root.querySelector('[data-note-kind="warnings"]')?.textContent).toContain('数据限制（4）')
    expect(root.querySelector('[data-note-kind="context"]')).toBeNull()
    expect(root.textContent).not.toContain('校验通过')
  })

  it('renders diagnostic strings as text and does not interpret them as markup', () => {
    const root = renderEvidenceNotes(['<img src=x onerror=alert(1)>'])!
    expect(root.querySelector('img')).toBeNull()
    expect(root.textContent).toContain('<img')
    expect(renderEvidenceNotes([])).toBeNull()
  })
})
