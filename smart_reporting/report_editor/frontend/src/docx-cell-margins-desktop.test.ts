import { afterEach, expect, it, vi } from 'vitest'
import { openDocxCellMarginOverridesDialog } from './docx-table-cell-margin-overrides-controls'

const initial = { top: 0, right: 109, bottom: 7, left: 108 }
afterEach(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); document.body.replaceChildren() })

it('边距窗口区分固定标题、滚动正文和紧凑操作，并提供具名阅读区', () => {
 const apply = vi.fn()
 openDocxCellMarginOverridesDialog(document.body, initial, '四个单元格', apply)
 const dialog = document.querySelector('[role="dialog"]')!
 expect(dialog.querySelector('header h2')!.textContent).toBe('单元格边距')
 expect(dialog.querySelector('.docx-cell-margins-body fieldset legend')!.textContent).toBe('自定义边距')
 for (const name of ['来源边距状态', '边距设置说明']) expect(dialog.querySelector(`[aria-label="${name}"]`)!.getAttribute('tabindex')).toBe('0')
 expect(dialog.querySelector('footer [data-action="inherit"]')!.textContent).toBe('恢复继承')
 expect(dialog.querySelector('[role="alert"]')!.hasAttribute('hidden')).toBe(true)
 expect(dialog.querySelectorAll('[data-margin]')).toHaveLength(4)
 expect(apply).not.toHaveBeenCalled()
})

it('提交失败揭示具名错误，保留输入和焦点，取消后回到入口', () => {
 const opener = document.createElement('button'); document.body.append(opener); opener.focus()
 const apply = vi.fn(() => { throw new Error('来源已变化，请重试') })
 openDocxCellMarginOverridesDialog(document.body, initial, '当前单元格', apply)
 const dialog = document.querySelector('[role="dialog"]')!, input = dialog.querySelector<HTMLInputElement>('[data-margin="left"]')!
 input.value = '0'; input.focus()
 dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
 expect(apply).toHaveBeenCalledWith({ ...initial, left: 0 })
 const error = dialog.querySelector<HTMLElement>('[role="alert"]')!
 expect(error.hidden).toBe(false); expect(error.getAttribute('aria-label')).toBe('边距设置错误'); expect(error.tabIndex).toBe(0)
 expect(error.textContent).toBe('来源已变化，请重试'); expect(input.value).toBe('0'); expect(document.activeElement).toBe(input)
 dialog.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
 expect(document.querySelector('[role="dialog"]')).toBeNull(); expect(document.activeElement).toBe(opener)
})
