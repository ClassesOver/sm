import { afterEach, expect, it, vi } from 'vitest'
import { createDocxListGallery } from './docx-list-gallery'
import { MULTILEVEL_LIBRARY, rememberListPreset } from './vendor/genoffice-docs/apps/docs/src/renderer/list-presets'
const views: ReturnType<typeof createDocxListGallery>[] = []
afterEach(() => { views.splice(0).forEach(view => view.destroy()); document.body.replaceChildren(); vi.restoreAllMocks() })

it('源最近列表、文档列表和级别入口均可应用且不重捕获当前选区', () => {
  localStorage.clear(); rememberListPreset('multi', MULTILEVEL_LIBRARY[1]!)
  const apply = vi.fn(), level = vi.fn(), current = vi.fn(), report = vi.fn()
  const view = createDocxListGallery({ reason: () => null, styles: () => [], current, apply, clear: vi.fn(), report,
    definitions: () => [{ numId: '5', abstractNumId: '4', startOverrides: {}, levels: { 0: { numFmt: 'decimal', lvlText: '%1.', start: 1 }, 1: { numFmt: 'decimal', lvlText: '%1.%2.', start: 1 } } }],
    level: () => ({ current: 0, available: [true, true] }), changeLevel: level,
  })
  views.push(view); document.body.append(view.element)
  const toggle = view.element.querySelector<HTMLButtonElement>('[data-docx-list-toggle]')!
  toggle.click(); expect(current).toHaveBeenCalledTimes(1)
  expect(view.element.querySelectorAll('[data-docx-list-recent]')).toHaveLength(1)
  expect(view.element.querySelectorAll('[data-docx-list-document]')).toHaveLength(1)
  view.element.querySelector<HTMLButtonElement>('[data-docx-list-document]')!.click()
  expect(apply).toHaveBeenCalledOnce()
  toggle.click(); view.element.querySelector<HTMLButtonElement>('[data-docx-list-level="1"]')!.click()
  expect(level).toHaveBeenCalledWith(1); expect(current).toHaveBeenCalledTimes(2)
  expect(report).not.toHaveBeenCalled(); localStorage.clear()
})
function fixture() {
  let reason: string | null = null
  const current = vi.fn(() => [{ numFmt: 'decimal', lvlText: '%1.', indentLeft: 720, hanging: 360 }]), apply = vi.fn(), clear = vi.fn(), report = vi.fn()
  const editor = document.body.appendChild(document.createElement('div')); editor.contentEditable = 'true'; editor.tabIndex = 0; editor.textContent = '原生选区'; editor.focus()
  const range = document.createRange(); range.selectNodeContents(editor); window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range)
  const view = createDocxListGallery({ reason: () => reason, styles: () => [{ styleId: 'Heading1', name: '标题一', type: 'paragraph' } as never], current, apply, clear, report })
  views.push(view); document.body.append(view.element)
  const button = (selector: string) => view.element.querySelector<HTMLButtonElement>(selector)!
  const open = () => { button('[data-docx-list-toggle]').click(); return view.element.querySelector<HTMLElement>('[data-docx-list-gallery]')! }
  const define = () => { open(); button('[data-docx-list-define]').click(); return document.querySelector<HTMLElement>('.list-define-modal')! }
  return { view, editor, current, apply, clear, report, button, open, define, lock: (value: string | null) => { reason = value } }
}
function change(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }))
}
async function settle() { await new Promise(resolve => setTimeout(resolve, 0)) }
async function pick(d: HTMLElement, index: number, value: string) {
  d.querySelectorAll<HTMLButtonElement>('.gs-dd-btn')[index]!.click(); await settle()
  d.querySelector<HTMLButtonElement>(`.gs-dd-item[data-value="${value}"]`)!.click(); await settle()
}
it('每次打开捕获一次快照，源8预设各9级，mousedown保留原生选区', () => {
  const f = fixture(); expect(f.current).not.toHaveBeenCalled(); const selected = window.getSelection()!.toString(); f.open()
  expect(f.current).toHaveBeenCalledTimes(1); f.view.refresh(); expect(f.current).toHaveBeenCalledTimes(1)
  const cards = f.view.element.querySelectorAll<HTMLButtonElement>('[data-docx-list-preset]'); expect(cards).toHaveLength(8)
  cards.forEach(card => expect(card.querySelectorAll('span')).toHaveLength(3))
  expect(cards[0]!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))).toBe(false)
  expect(window.getSelection()!.toString()).toBe(selected); cards[0]!.click()
  expect(f.apply.mock.calls[0]![0]).toHaveLength(9); expect(f.apply.mock.calls[0]![0][0]).toMatchObject({ numFmt: 'decimal', lvlText: '%1)' })
  expect(f.view.element.querySelector('[data-docx-list-gallery]')).toBeNull(); f.open(); expect(f.current).toHaveBeenCalledTimes(2)
})
it('无列表仅清除；写入错误报告且不关闭会话', () => {
  const f = fixture(); f.open(); f.button('[data-docx-list-clear]').click(); expect(f.clear).toHaveBeenCalledOnce(); expect(f.apply).not.toHaveBeenCalled()
  f.open(); f.apply.mockImplementationOnce(() => { throw new Error('来源变化') }); f.button('[data-docx-list-preset]').click()
  expect(f.report.mock.calls[0]![0]).toEqual(new Error('来源变化')); expect(f.view.element.querySelector('[data-docx-list-gallery]')).not.toBeNull()
})
it('定义完整源字段和9级，进入定义不重捕获，取消不写入并恢复焦点', async () => {
  const f = fixture(), d = f.define(); await settle(); expect(f.current).toHaveBeenCalledTimes(1)
  expect(d.querySelectorAll('.list-define-levels [role=option]')).toHaveLength(9)
  expect(d.querySelectorAll('.gs-dd-btn')).toHaveLength(6); expect(d.querySelectorAll('input')).toHaveLength(9)
  d.querySelector<HTMLButtonElement>('.modal-actions button')!.click(); expect(f.apply).not.toHaveBeenCalled(); expect(f.clear).not.toHaveBeenCalled()
  expect(document.querySelector('.list-define-modal')).toBeNull(); expect(document.activeElement).toBe(f.editor)
})
it('全部定义字段传递：编号、起始、缩进、后缀、对齐、样式、重启、字体、法律编号', async () => {
  const f = fixture(), d = f.define(); await settle(); d.querySelectorAll<HTMLButtonElement>('.list-define-levels button')[1]!.click(); await settle()
  await pick(d, 0, 'upperRoman')
  change(d.querySelector<HTMLInputElement>('input[aria-label]')!, '第%2章'); await settle()
  const nums = d.querySelectorAll<HTMLInputElement>('.list-define-grid input')
  change(nums[0]!, '4'); await settle(); change(nums[2]!, '2 cm'); await settle(); change(nums[1]!, '1 cm'); await settle()
  await pick(d, 1, 'space'); await pick(d, 2, 'right'); await pick(d, 3, 'Heading1'); await pick(d, 4, '1'); await pick(d, 5, 'Arial')
  change(d.querySelector<HTMLInputElement>('.list-dialog-font input[type=number]')!, '13.5'); await settle()
  change(d.querySelector<HTMLInputElement>('input[type=color]')!, '#123abc'); await settle()
  d.querySelectorAll<HTMLInputElement>('input[type=checkbox]').forEach(input => input.click()); await settle()
  d.querySelector<HTMLButtonElement>('.modal-actions .primary')!.click()
  expect(f.apply).toHaveBeenCalledOnce(); const result = f.apply.mock.calls[0]![0]
  expect(result).toHaveLength(9); expect(result[1]).toMatchObject({ numFmt: 'upperRoman', lvlText: '第%2章', start: 4, indentLeft: 1134, hanging: 567, suff: 'space', lvlJc: 'right', pStyle: 'Heading1', lvlRestart: 1, font: 'Arial', szHalfPoints: 27, color: '123ABC', bold: true, italic: true, isLgl: true })
  expect(document.querySelector('.list-define-modal')).toBeNull()
})
it('打开后锁定阻止确定；refresh不重捕获，关闭后入口禁用', async () => {
  const f = fixture(), d = f.define(); await settle(); f.lock('保存中'); f.view.refresh()
  expect(d.querySelector<HTMLButtonElement>('.primary')!.disabled).toBe(true); expect(f.current).toHaveBeenCalledTimes(1)
  d.querySelector<HTMLButtonElement>('.primary')!.click(); expect(f.apply).not.toHaveBeenCalled()
  d.querySelector<HTMLButtonElement>('.modal-actions button')!.click(); f.view.refresh(); expect(f.button('[data-docx-list-toggle]').disabled).toBe(true)
})
it('IME Escape不关闭，普通Escape恢复焦点；销毁清理且不写入', async () => {
  const f = fixture(), d = f.define(); await settle(); const input = d.querySelector('input')!; input.focus()
  for (const options of [{ isComposing: true }, { keyCode: 229 }]) { input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', ...options, bubbles: true })); expect(d.isConnected).toBe(true) }
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); expect(d.isConnected).toBe(false); expect(document.activeElement).toBe(f.editor)
  f.define(); await settle(); f.view.destroy(); expect(document.querySelector('.list-define-modal')).toBeNull(); expect(f.apply).not.toHaveBeenCalled()
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); expect(f.report).not.toHaveBeenCalled()
})
it('定义使用打开时levels副本，应用错误保留字段，普通Tab在模态框内循环', async () => {
  const f = fixture(); f.open(); f.current.mock.results[0]!.value![0]!.lvlText = '外部变化'
  f.button('[data-docx-list-define]').click(); await settle(); const d = document.querySelector<HTMLElement>('.list-define-modal')!
  expect(d.getAttribute('aria-modal')).toBe('true'); expect(d.querySelector<HTMLInputElement>('input[aria-label]')!.value).toBe('%1.')
  const last = d.querySelector<HTMLButtonElement>('.modal-actions .primary')!, first = d.querySelector<HTMLButtonElement>('button')!
  last.focus(); last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })); expect(document.activeElement).toBe(first)
  f.apply.mockImplementationOnce(() => { throw new Error('来源已失效') }); last.click(); expect(d.isConnected).toBe(true); expect(f.report.mock.calls[0]![0]).toEqual(new Error('来源已失效'))
  d.closest<HTMLElement>('.modal-backdrop')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); expect(d.isConnected).toBe(false)
})
it('图库打开后即时锁定，即使没有refresh也拒绝预设和清除', () => {
  const f = fixture(); f.open(); f.lock('来源锁定'); f.button('[data-docx-list-preset]').click(); f.button('[data-docx-list-clear]').click()
  expect(f.apply).not.toHaveBeenCalled(); expect(f.clear).not.toHaveBeenCalled(); expect(f.report).toHaveBeenCalledTimes(2)
})
