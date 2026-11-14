import { afterEach, expect, it, vi } from 'vitest'
import { mountWorkbookRibbon } from './workbook-ribbon'
import type { ChartPresetSource } from './workbook-chart-presets'

afterEach(() => document.body.replaceChildren())

it('快速布局和更改颜色使用源菜单命令、中文标签及真实图标', () => {
  const command = vi.fn()
  const ribbon = mountWorkbookRibbon(document.body, command, {
    editable: () => true, rotation: () => undefined,
    chart: () => ({ isPie: true, canLabel: true, seriesCount: 1, categoryCount: 3 }),
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Chart Design"]')!.click()
  const layout = document.querySelector<HTMLSelectElement>('[aria-label="快速布局"]')!
  const colors = document.querySelector<HTMLSelectElement>('[aria-label="更改颜色"]')!
  expect(layout).not.toBeNull(); expect(colors).not.toBeNull()
  expect(layout.disabled).toBe(false); expect(colors.disabled).toBe(false)
  expect(layout.parentElement!.querySelector('svg')).not.toBeNull()
  expect(colors.parentElement!.querySelector('svg')).not.toBeNull()
  expect([...layout.options].map(option => option.textContent).join(' ')).toContain('名称 + % 标签')
  layout.value = 'chart-layout:2'; layout.dispatchEvent(new Event('change'))
  expect(command).toHaveBeenLastCalledWith('chart-layout:2'); expect(layout.value).toBe('')
  colors.value = 'chart-colors:warm'; colors.dispatchEvent(new Event('change'))
  expect(command).toHaveBeenLastCalledWith('chart-colors:warm'); expect(colors.value).toBe('')
  ribbon.dispose()
})

it('选图变化刷新布局措辞，失去目标、只读或受保护时阻止预设命令', () => {
  let source: ChartPresetSource | null = null, editable = true, protectedSheet = false
  const command = vi.fn()
  const ribbon = mountWorkbookRibbon(document.body, command, {
    editable: () => editable, rotation: () => 0, chart: () => source,
    protection: () => ({ sheet: { protected: protectedSheet }, workbook: { locked: false } }),
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Chart Design"]')!.click()
  const layout = document.querySelector<HTMLSelectElement>('[aria-label="快速布局"]')!
  const colors = document.querySelector<HTMLSelectElement>('[aria-label="更改颜色"]')!
  expect(layout).not.toBeNull()
  expect(layout.disabled).toBe(true); expect(colors.disabled).toBe(true)
  source = { isPie: false, canLabel: true, seriesCount: 2, categoryCount: 3 }
  ribbon.refreshState()
  expect(layout.disabled).toBe(false); expect(colors.disabled).toBe(false)
  expect(layout.options[1]!.textContent).toContain('数值标签')
  source = { ...source, canLabel: false }; ribbon.refreshState()
  expect(layout.options[1]!.textContent).not.toContain('标签')
  for (const reason of ['protected', 'readonly', 'missing'] as const) {
    protectedSheet = reason === 'protected'; editable = reason !== 'readonly'
    source = reason === 'missing' ? null : { isPie: false, canLabel: true, seriesCount: 2, categoryCount: 3 }
    ribbon.refreshState()
    expect(layout.disabled, reason).toBe(true); expect(colors.disabled, reason).toBe(true)
    layout.value = 'chart-layout:1'; layout.dispatchEvent(new Event('change'))
    colors.value = 'chart-colors:blue'; colors.dispatchEvent(new Event('change'))
  }
  expect(command).not.toHaveBeenCalled()
  ribbon.dispose()
})
