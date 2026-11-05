import { expect, it, vi } from 'vitest'
import { renderAITextPreview } from './ai-text-preview'
import { renderWorkbookProposal } from './workbook-ai-preview'

it('renders safe text differences and lets the reviewer switch between original and candidate', () => {
  const target = document.createElement('div')
  renderAITextPreview('收入 100 万', '收入 120 万<img src=x onerror=alert(1)>', target)
  expect(target.querySelector('ins')?.textContent).toContain('2')
  expect(target.querySelector('img')).toBeNull()
  target.querySelector<HTMLButtonElement>('[data-preview-mode="original"]')!.click()
  expect(target.querySelector('.ai-preview-text')?.textContent).toBe('收入 100 万')
  target.querySelector<HTMLButtonElement>('[data-preview-mode="candidate"]')!.click()
  expect(target.querySelector('.ai-preview-text')?.textContent).toContain('<img src=x')
})
it('summarizes workbook cell locations, formulas and styles while retaining complete operations', async () => {
  const target = document.createElement('div')
  const proposal = { summary: '调整公式与格式', operations: [
    { kind: 'applyCellEdits', edits: [{ sheetName: '经营指标', row: 4, column: 27, writeValue: true, cell: { value: null, formula: 'SUM(A1:A4)' }, style: { numberFormat: '#,##0' } }] },
    { kind: 'applyColumnWidths', sheetName: '经营指标', entries: [{ column: 0, width: 20 }] },
  ] }
  renderWorkbookProposal(proposal, target)
  expect(target.querySelector('tbody')?.textContent).toContain('经营指标 · AB5')
  expect(target.querySelector('tbody')?.textContent).toContain('公式：SUM(A1:A4)；更新单元格样式')
  expect(target.textContent).toContain('列宽 · 经营指标')
  expect(target.querySelector('pre')!.textContent).toBe('')
  const details = target.querySelector('details')!; details.open = true; details.dispatchEvent(new Event('toggle'))
  expect(JSON.parse(target.querySelector('pre')!.textContent!)).toEqual(proposal.operations[0])
})

it('navigates contiguous differences and disables navigation at the boundaries', () => {
  const target = document.createElement('div')
  renderAITextPreview('收入甲，成本乙', '收入丙，成本丁', target)
  const next = target.querySelector<HTMLButtonElement>('[data-diff-action="next"]')!
  const previous = target.querySelector<HTMLButtonElement>('[data-diff-action="previous"]')!
  const scroll = vi.fn()
  target.querySelectorAll<HTMLElement>('ins,del').forEach(node => { node.scrollIntoView = scroll })
  expect(previous.disabled).toBe(true)
  expect(target.querySelector('[role="status"]')?.textContent).toBe('1 / 2 处修改')
  next.click(); expect(scroll).toHaveBeenCalled()
  expect(next.disabled).toBe(true); expect(previous.disabled).toBe(false)
  expect(target.querySelector('[role="status"]')?.textContent).toBe('2 / 2 处修改')
  target.querySelector<HTMLButtonElement>('[data-preview-mode="compare"]')!.click()
  expect(target.querySelector<HTMLElement>('.ai-diff-navigation')!.hidden).toBe(true)
})
it('provides human-readable paging beyond the first hundred workbook edits', () => {
  const target = document.createElement('div')
  renderWorkbookProposal({ summary: '批量格式调整', operations: [{ kind: 'applyCellEdits', edits: Array.from({length: 121}, (_, row) => ({ sheetName: '指标', row, column: 0, writeValue: true, cell: { value: row } })) }] }, target)
  expect(target.querySelectorAll('tbody tr')).toHaveLength(50)
  const pager = target.querySelector('.ai-workbook-pagination')!
  const [previous, next] = [...pager.querySelectorAll('button')]
  expect(previous!.disabled).toBe(true)
  next!.click(); next!.click()
  expect(target.querySelectorAll('tbody tr')).toHaveLength(21)
  expect(target.querySelector('tbody')?.textContent).toContain('指标 · A121')
  expect(pager.textContent).toContain('第 3 / 3 页 · 121 项')
  expect(next!.disabled).toBe(true)
  previous!.click(); expect(target.querySelectorAll('tbody tr')).toHaveLength(50)
})
it('keeps full originals and candidates available when a large diff exceeds its work budget', () => {
  const target = document.createElement('div')
  const before = '甲'.repeat(20000); const after = '乙'.repeat(20000)
  renderAITextPreview(before, after, target)
  expect(target.textContent).toContain('内容较长')
  target.querySelector<HTMLButtonElement>('[data-preview-mode="compare"]')!.click()
  expect([...target.querySelectorAll('.ai-preview-text')].map(node => node.textContent)).toEqual([before, after])
})
