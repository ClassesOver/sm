import { afterEach, expect, it } from 'vitest'
import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import { createWorkbookChartDescriptions } from './workbook-chart-descriptions'
import { mountWorkbookRibbon } from './workbook-ribbon'

const panels: Array<{ dispose(): void }> = []
afterEach(() => { panels.splice(0).forEach(panel => panel.dispose()); document.body.replaceChildren() })
const chart = (overrides: Partial<ChartReadSpec> = {}): ChartReadSpec => ({
  chartPath: 'xl/charts/chart1.xml', kind: 'column', title: '完整季度收入标题'.repeat(8),
  anchor: { fromRow: 1, fromColumn: 4, toRow: 9, toColumn: 12 },
  series: [{ index: 0, name: '收入', valuesRef: "'华东'!$B$2:$B$9", categoriesRef: "'华东'!$A$2:$A$9" }],
  ...overrides,
})
function fixture() {
  const panel = createWorkbookChartDescriptions(document.body)
  panels.push(panel)
  return panel
}

it('提供多图全文标题、类型和系列来源，按文本处理文档内容', () => {
  const panel = fixture(), first = chart(), second = chart({ title: '<img src=x onerror=alert(1)>', kind: 'line' })
  panel.open('华东', [first, second])
  const dialog = document.querySelector<HTMLElement>('[role=dialog]:not([hidden])')!
  expect(dialog.getAttribute('aria-label')).toBe('图表说明')
  expect(dialog.textContent).toContain(first.title)
  expect(dialog.textContent).toContain('华东')
  expect(dialog.textContent).toContain('柱形图')
  expect(dialog.textContent).toContain('折线图')
  expect(dialog.textContent).toContain('收入')
  expect(dialog.textContent).toContain("'华东'!$B$2:$B$9")
  expect(dialog.textContent).toContain("'华东'!$A$2:$A$9")
  expect(dialog.textContent).toContain(second.title)
  expect(dialog.querySelector('img')).toBeNull()
  expect(dialog.querySelectorAll('[data-chart-description]')).toHaveLength(2)
})

it('给无标题无名称系列提供可区分的名称，不把常量或未知来源假称为空图', () => {
  const panel = fixture()
  panel.open('Sheet1', [chart({ title: '', series: [{ index: 0, valuesRef: '' }, { index: 1, valuesRef: 'Sheet1!C2:C3' }] })])
  expect(document.querySelector('[data-chart-description]')!.textContent).toContain('未命名图表 1')
  expect(document.querySelector('[data-chart-description]')!.textContent).toContain('系列 1')
  expect(document.querySelector('[data-chart-description]')!.textContent).toContain('系列 2')
  expect(document.querySelector('[data-chart-description]')!.textContent).toContain('来源区域未提供')
})

it('重新打开只展示当前表的图表，空态不继续显示前一表的内容', () => {
  const panel = fixture()
  panel.open('华东', [chart()]); panel.close(); panel.open('空表', [])
  const dialog = document.querySelector('[role=dialog]:not([hidden])')!
  expect(dialog.querySelectorAll('[data-chart-description]')).toHaveLength(0)
  expect(dialog.textContent).toContain('空表')
  expect(dialog.textContent).toContain('没有可预览的图表')
  expect(dialog.textContent).not.toContain('华东')
})

it('Escape关闭回到入口，销毁后不再创建说明或移动焦点', () => {
  const panel = fixture(), trigger = document.body.appendChild(document.createElement('button'))
  trigger.focus(); panel.open('Sheet1', [chart()])
  expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭图表说明')
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(document.activeElement).toBe(trigger)
  expect(document.querySelector('[role=dialog]:not([hidden])')).toBeNull()
  panel.dispose(); panel.open('Sheet1', [chart()])
  expect(document.querySelector('[role=dialog]')).toBeNull()
  expect(document.activeElement).toBe(trigger)
})

it('图表说明入口在只读且无单元格选区时仍可打开', () => {
  const commands: string[] = []
  const ribbon = mountWorkbookRibbon(document.body, command => commands.push(command), { editable: () => false, hasSelection: () => false, rotation: () => undefined })
  panels.push(ribbon)
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Chart Design"]')!.click()
  const entry = document.querySelector<HTMLButtonElement>('[data-ribbon-command="chart-descriptions"]')
  expect(entry).not.toBeNull()
  expect(entry!.disabled).toBe(false)
  entry!.click(); expect(commands).toEqual(['chart-descriptions'])
})

it('系列缓存名称可读，缺少缓存时分别说明系列编号和名称来源', () => {
  const panel = fixture()
  panel.open('Sheet1', [chart({ series: [
    { name: 'Sheet1!B1', nameRef: 'Sheet1!B1', nameCache: '营业收入', valuesRef: 'Sheet1!B2:B5' },
    { name: 'Sheet1!C1', nameRef: 'Sheet1!C1', valuesRef: 'Sheet1!C2:C5' },
  ] })])
  const names = [...document.querySelectorAll('[data-chart-description] strong')].map(node => node.textContent)
  expect(names).toEqual(['营业收入', '系列 2'])
  expect(document.querySelector('[data-chart-description]')!.textContent).toContain('名称：Sheet1!C1')
})

it('已打开时更新说明不覆盖原入口，关闭仍回到原按钮', () => {
  const panel = fixture(), trigger = document.body.appendChild(document.createElement('button'))
  trigger.focus(); panel.open('Sheet1', [chart()]); panel.open('Sheet2', [chart({ title: '更新标题' })])
  panel.close(); expect(document.activeElement).toBe(trigger)
})

it('使用当前网格的系列名，外部引用保留缓存名称而不冒读当前表', () => {
  const panel = fixture()
  panel.open('Sheet1', [chart({ series: [
    { nameRef: 'Sheet1!B1', nameCache: '旧标题', valuesRef: 'Sheet1!B2:B5' },
    { nameRef: "'[外部.xlsx]Sheet1'!B1", nameCache: '外部缓存标题', valuesRef: "'[外部.xlsx]Sheet1'!B2:B5" },
  ] })], { getName: () => 'Sheet1', getCell: () => ({ v: '当前收入标题' }) })
  expect([...document.querySelectorAll('[data-chart-description] strong')].map(node => node.textContent)).toEqual(['当前收入标题', '外部缓存标题'])
})

it('关闭后重新打开从首项开始，不沿用上一次说明的滚动位置', () => {
  const panel = fixture()
  panel.open('Sheet1', [chart(), chart(), chart()])
  const scroll = document.querySelector<HTMLElement>('.workbook-chart-descriptions-scroll')!
  scroll.scrollTop = 180
  panel.close(); panel.open('Sheet2', [chart()])
  expect(scroll.scrollTop).toBe(0)
})

it('按文本说明来源系列填充及逐点覆盖，颜色信息不只依赖色块', () => {
  const panel = fixture()
  panel.open('Sheet1', [chart({ series: [{ name: '收入', valuesRef: 'B2:B4', color: '#136B4A', pointColors: { 0: 'transparent', 2: '#A02040' } }] })])
  const text = document.querySelector('[data-chart-description]')!.textContent!
  expect(text).toContain('系列填充：#136B4A')
  expect(text).toContain('第 1 个数据点：无填充')
  expect(text).toContain('第 3 个数据点：#A02040')
})

it('复杂来源填充不可预览时明确说明原因，仍保留数据来源', () => {
  const panel = fixture()
  panel.open('Sheet1', [chart({ series: [{ name: '收入', valuesRef: 'B2:B4', colorPreviewUnavailable: true }] })])
  const text = document.querySelector('[data-chart-description]')!.textContent!
  expect(text).toContain('来源填充暂不支持预览，请下载原件查看')
  expect(text).toContain('B2:B4')
})
