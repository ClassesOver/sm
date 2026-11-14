import { afterEach, expect, it, vi } from 'vitest'
import { createDocxListGallery } from './docx-list-gallery'
import { BULLET_LIBRARY, NUMBER_LIBRARY, bulletPresetLevels, numberPresetLevels, rememberListPreset } from './vendor/genoffice-docs/apps/docs/src/renderer/list-presets'
const views: ReturnType<typeof createDocxListGallery>[] = []
afterEach(() => { views.splice(0).forEach(v => v.destroy()); document.body.replaceChildren(); localStorage.clear() })
function fixture(kind: 'bullets' | 'numbers') {
  const apply = vi.fn(), current = vi.fn(() => undefined), clear = vi.fn(), report = vi.fn()
  const v = createDocxListGallery({ kind, reason: () => null, styles: () => [], current, apply, clear, report,
    level: () => ({ current: 2, available: Array(9).fill(true) }),
    definitions: () => [{ numId: '1', abstractNumId: '1', startOverrides: {}, levels: { 0: { numFmt: kind === 'bullets' ? 'bullet' : 'decimal', lvlText: kind === 'bullets' ? '★' : '%1)', start: 1 } } }],
  }); views.push(v); document.body.append(v.element)
  const toggle = v.element.querySelector<HTMLButtonElement>('[data-docx-list-toggle]')!
  const open = () => { toggle.click(); return v.element }
  return { v, apply, current, clear, report, open }
}
it.each(['bullets', 'numbers'] as const)('普通%s源库按原定义应用，不误显示多级库', kind => {
  const f = fixture(kind); f.open()
  const cards = f.v.element.querySelectorAll<HTMLButtonElement>('[data-docx-list-preset]')
  expect(cards).toHaveLength(kind === 'bullets' ? BULLET_LIBRARY.length : NUMBER_LIBRARY.length)
  cards[1]!.click()
  expect(f.apply).toHaveBeenCalledWith(kind === 'bullets' ? bulletPresetLevels(BULLET_LIBRARY[1]!) : numberPresetLevels(NUMBER_LIBRARY[1]!.numFmt, NUMBER_LIBRARY[1]!.pattern))
  expect(f.current).toHaveBeenCalledTimes(1); expect(f.report).not.toHaveBeenCalled()
})
it.each(['bullets', 'numbers'] as const)('%s最近/文档库分区与独立清除', kind => {
  rememberListPreset(kind, kind === 'bullets' ? bulletPresetLevels('★') : numberPresetLevels('upperRoman', '%1.'))
  const f = fixture(kind);f.open()
  expect(f.v.element.querySelectorAll('[data-docx-list-recent]')).toHaveLength(1)
  expect(f.v.element.querySelectorAll('[data-docx-list-document]')).toHaveLength(1)
  f.v.element.querySelector<HTMLButtonElement>('[data-docx-list-clear]')!.click()
  expect(f.clear).toHaveBeenCalledOnce();expect(f.apply).not.toHaveBeenCalled()
})
it('自定义符号使用固定源对话框与当前级别，图片入口明确禁用', async () => {
  const f = fixture('bullets');f.open();f.v.element.querySelector<HTMLButtonElement>('[data-docx-list-define]')!.click()
  const dialog = document.querySelector<HTMLElement>('.list-bullet-dialog')!
  expect(dialog).not.toBeNull();const tabs = dialog.querySelectorAll<HTMLButtonElement>('[role=tab]')
  expect(tabs[1]!.disabled).toBe(true);expect(tabs[1]!.title).toContain('图片')
  dialog.querySelector<HTMLButtonElement>('[role=option][aria-selected=false]')!.click()
  await new Promise(r => setTimeout(r,0));dialog.querySelector<HTMLButtonElement>('.primary')!.click()
  expect(f.apply).toHaveBeenCalledOnce();expect(f.apply.mock.calls[0]![0][2].lvlText).not.toBe('•')
  expect(f.report).not.toHaveBeenCalled()
})
it('自定义编号使用固定源完整字段并传当前级别，不重捕获选区', async () => {
  const f=fixture('numbers');f.open();f.v.element.querySelector<HTMLButtonElement>('[data-docx-list-define]')!.click()
  const dialog=document.querySelector<HTMLElement>('.list-number-dialog')!
  expect(dialog).not.toBeNull();expect(dialog.querySelector('.list-dialog-font')).not.toBeNull()
  dialog.querySelector<HTMLButtonElement>('.primary')!.click()
  expect(f.current).toHaveBeenCalledTimes(1);expect(f.apply.mock.calls[0]![0][2]).toMatchObject({numFmt:'decimal',lvlText:'%3.',start:1})
})
it('源label内的Dropdown选项只选一次，不由label默认激活重新打开', async () => {
  const f=fixture('bullets');f.open();f.v.element.querySelector<HTMLButtonElement>('[data-docx-list-define]')!.click()
  const d=document.querySelector<HTMLElement>('.list-bullet-dialog')!,trigger=d.querySelector<HTMLButtonElement>('.gs-dd-btn')!
  trigger.click();await new Promise(r=>setTimeout(r,0));d.querySelector<HTMLButtonElement>('.gs-dd-item[data-value="Arial"]')!.click();await new Promise(r=>setTimeout(r,0))
  expect(trigger.dataset.value).toBe('Arial');expect(trigger.getAttribute('aria-expanded')).toBe('false')
})
