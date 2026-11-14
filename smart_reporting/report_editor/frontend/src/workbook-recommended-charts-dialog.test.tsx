import { afterEach, expect, it, vi } from 'vitest'
import { recommendCharts, type RecommendedKind } from '@sheets-web/xlsx-engine'
import { createWorkbookRecommendedChartsDialog } from './workbook-recommended-charts-dialog'

const dialogs: { dispose(): void }[] = []
afterEach(() => { dialogs.splice(0).forEach(dialog => dialog.dispose()); document.body.replaceChildren() })
const values = [['Quarter', 'Sales'], ['Q1', 10], ['Q2', 20], ['Q3', 30]]
function setup() {
  const pick = vi.fn(), dialog = createWorkbookRecommendedChartsDialog(document.body, pick), target = { source: 'trusted' }
  dialogs.push(dialog); dialog.open(recommendCharts(values)!, target)
  return { dialog, target, pick, overlay: document.querySelector<HTMLElement>('.workbook-recommended-charts-overlay')! }
}
it('shows source ranked types/reasons and an actual selection-driven SVG preview', () => {
  const c = setup(), recommendations = recommendCharts(values)!
  expect([...document.querySelectorAll('[data-recommended-chart]')].map(node => node.getAttribute('data-recommended-chart'))).toEqual(recommendations.items.map(item => item.kind))
  expect(document.querySelector('[data-recommended-chart="line"]')!.textContent).toContain('时间序列适合用趋势展示')
  const before = document.querySelector('[data-recommended-chart="line"] path')!.getAttribute('d')
  c.dialog.open(recommendCharts([['Quarter', 'Sales'], ['Q1', 30], ['Q2', 1], ['Q3', 10]])!, c.target)
  expect(document.querySelector('[data-recommended-chart="line"] path')!.getAttribute('d')).not.toBe(before)
  expect(c.pick).not.toHaveBeenCalled()
})
it('renders the nine source preview kinds and preserves the captured insertion target on pick', () => {
  const c = setup(), recommendations = recommendCharts(values)!
  const kinds: RecommendedKind[] = ['column', 'bar', 'line', 'area', 'pie', 'doughnut', 'scatter', 'radar', 'combo']
  c.dialog.open({ ...recommendations, items: kinds.map(kind => ({ kind, reason: 'comparison' })) }, c.target)
  for (const kind of kinds) expect(document.querySelector(`[data-recommended-chart="${kind}"] svg`)).not.toBeNull()
  document.querySelector<HTMLButtonElement>('[data-recommended-chart="doughnut"]')!.click()
  expect(c.pick).toHaveBeenCalledExactlyOnceWith('doughnut', c.target)
  expect(c.overlay.hidden).toBe(true)
})
it.each(['button', 'Escape', 'backdrop'])('closes by %s without inserting or mutating input', action => {
  const c = setup()
  if (action === 'button') document.querySelector<HTMLButtonElement>('[data-recommended-close]')!.click()
  else if (action === 'Escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
  else c.overlay.click()
  expect(c.overlay.hidden).toBe(true); expect(c.pick).not.toHaveBeenCalled()
})
it('drops detached picks and cannot reopen after disposal', () => {
  const c = setup(), pick = document.querySelector<HTMLButtonElement>('[data-recommended-chart]')!
  c.dialog.dispose(); pick.click(); c.dialog.open(recommendCharts(values)!, c.target)
  expect(c.pick).not.toHaveBeenCalled(); expect(document.querySelector('.workbook-recommended-charts-overlay')).toBeNull()
})
