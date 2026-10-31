import { describe, expect, it } from 'vitest'
import { chartSuggestionsFromProfile, presetCaution, tableProfile, tableSuggestions } from './ai-suggestions'

const profile = (overrides = {}) => ({ inputCount: 1, rowCount: 10, categoryCount: 10, textFieldCount: 1,
  numericFieldCount: 1, unitCount: 1, hasPeriod: false, hasNegative: false, magnitudeRatio: 2, ...overrides })
const base = ['在图上显示数值标签', '只保留金额最大的前 5 组，其余合并为“其他”并标注为子集', '把标题改得更简洁']

describe('按数据概况推荐', () => {
  it('概况缺失时保持按图形的原建议', () => {
    expect(chartSuggestionsFromProfile(base, undefined)).toEqual(base)
  })

  it('类别少时不推荐 TopN，类别多、单位多、量级悬殊、有期间时优先给出对应建议', () => {
    expect(chartSuggestionsFromProfile(base, profile({ categoryCount: 4 }))).not.toContain(base[1])
    const rich = chartSuggestionsFromProfile(base, profile({ categoryCount: 40, unitCount: 2, magnitudeRatio: 500, hasPeriod: true }))
    expect(rich.slice(0, 4)).toEqual([
      '将全部类别分页展示，保持统一颜色和值域', '不同单位的系列分别使用左右坐标轴并标明单位',
      '数值差距很大，使用断轴让较小的值也能看清', '标注最高和最低的期间'])
    expect(rich.length).toBeLessThanOrEqual(6)
  })

  it.each([
    ['pie', { hasNegative: true }, '含负值'],
    ['radar', { numericFieldCount: 2 }, '3–8'],
    ['bubble', { numericFieldCount: 2 }, '三个数值字段'],
    ['dual', { unitCount: 1 }, '单位一致'],
    ['vertical-break', { magnitudeRatio: 3 }, '差距不大'],
    ['pagination', { categoryCount: 8 }, '无需分页'],
  ])('%s 在不合适的数据上给出提示', (id, overrides, text) => {
    expect(presetCaution(id, profile(overrides))).toContain(text)
  })

  it('适合或未知时不提示', () => {
    expect(presetCaution('pie', profile())).toBeNull()
    expect(presetCaution('dual', profile({ unitCount: 2 }))).toBeNull()
    expect(presetCaution('pie', undefined)).toBeNull()
  })
})

describe('表格建议', () => {
  const table = '| 科室 | 收入 | 完成率 |\n| --- | ---: | ---: |\n| 内科 | 1,200 | 95% |\n| 外科 | 900 | 102% |'

  it('从 Markdown 表格识别数值列与比率列', () => {
    expect(tableProfile(table)).toEqual({ rowCount: 2, columnCount: 3, numericColumns: ['收入', '完成率'], percentColumns: ['完成率'] })
    expect(tableProfile('没有表格')).toBeNull()
  })

  it('按真实列名给出建议，比率列不直接相加', () => {
    const suggestions = tableSuggestions(tableProfile(table))
    expect(suggestions[0]).toBe('按「收入」从高到低排序')
    expect(suggestions).toContain('标注「完成率」低于 100% 的行')
    expect(suggestions.join()).toContain('比率列不直接相加')
    expect(tableSuggestions(null).length).toBeGreaterThan(0)
  })
})
