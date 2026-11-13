import { afterEach, describe, expect, it, vi } from 'vitest'
import { createWorkbookLinkDialog, LINK_TEXT, normalizeLinkTarget } from './workbook-link-dialog'
import { mountWorkbookRibbon } from './workbook-ribbon'

afterEach(() => { document.body.replaceChildren() })

describe('XLSX Insert ▸ Link (pinned ExcelShell LinkDialog + normalizeLinkTarget)', () => {
  it('normalizes addresses exactly like the pinned univer-sync helper', () => {
    expect(normalizeLinkTarget('  https://example.com/a  ')).toBe('https://example.com/a')
    expect(normalizeLinkTarget('MAILTO:team@example.com')).toBe('MAILTO:team@example.com')
    expect(normalizeLinkTarget('example.com/path')).toBe('https://example.com/path')
    expect(normalizeLinkTarget('Sheet1!A1')).toBe('#Sheet1!A1')
    expect(normalizeLinkTarget("#'数据 表'!$B$2")).toBe("#'数据 表'!$B$2")
    for (const bad of ['', '   ', 'javascript:alert(1)', 'not a link', 'x'.repeat(2084)]) expect(normalizeLinkTarget(bad)).toBeNull()
  })

  it('opens as insert or edit, validates input, applies, removes and keeps errors in the dialog', async () => {
    const apply = vi.fn(async (_target: string | null) => {})
    const dialog = createWorkbookLinkDialog(document.body, apply)
    dialog.open(null)
    const card = document.querySelector<HTMLElement>('.workbook-link-dialog')!
    const input = card.querySelector<HTMLInputElement>('[data-link-address]')!, ok = card.querySelector<HTMLButtonElement>('[data-link-ok]')!
    expect(card.querySelector('[data-link-title]')!.textContent).toBe(LINK_TEXT.insertTitle)
    expect(card.querySelector<HTMLButtonElement>('[data-link-remove]')!.hidden).toBe(true)
    expect(ok.disabled).toBe(true)
    input.value = 'not a link'; input.dispatchEvent(new Event('input'))
    ok.click()
    expect(card.querySelector('[role="alert"]')!.textContent).toBe(LINK_TEXT.invalid)
    expect(apply).not.toHaveBeenCalled()
    input.value = 'example.com'; input.dispatchEvent(new Event('input'))
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await vi.waitFor(() => expect(apply).toHaveBeenCalledWith('https://example.com'))
    dialog.open('#Sheet1!A1')
    expect(card.querySelector('[data-link-title]')!.textContent).toBe(LINK_TEXT.editTitle)
    expect(input.value).toBe('#Sheet1!A1')
    const remove = card.querySelector<HTMLButtonElement>('[data-link-remove]')!
    expect(remove.hidden).toBe(false)
    remove.click()
    await vi.waitFor(() => expect(apply).toHaveBeenLastCalledWith(null))
    apply.mockRejectedValueOnce(new Error('单元格 A1 的链接已变化，请刷新后重试。'))
    dialog.open(null); input.value = 'https://a.example'; input.dispatchEvent(new Event('input')); ok.click()
    await vi.waitFor(() => expect(card.querySelector('[role="alert"]')!.textContent).toContain('已变化'))
    dialog.dispose()
  })

  it('wires the Insert ▸ Link ribbon command on editable sheets', () => {
    const command = vi.fn()
    let editable = true
    const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => editable, rotation: () => 0, protection: () => ({ sheet: { protected: false }, workbook: { locked: false } }) })
    document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Insert"]')!.click()
    const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="link-open"]')!
    expect(button.disabled).toBe(false)
    expect(button.dataset.unavailableReason).toBeUndefined()
    button.click(); expect(command).toHaveBeenLastCalledWith('link-open')
    editable = false; ribbon.refreshState(); expect(button.disabled).toBe(true)
    ribbon.dispose()
  })
})
