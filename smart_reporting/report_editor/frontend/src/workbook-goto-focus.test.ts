import { afterEach, expect, it, vi } from 'vitest'
import { Univer, IUniverInstanceService, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { DesktopLayoutService, ILayoutService } from '@univerjs/ui'
import { createGoToDialog, focusWorkbookGrid } from './workbook-goto'
import '@univerjs/sheets/facade'

afterEach(() => document.body.replaceChildren())
it('hands focus to the official sheet handler after successful Go To closes its modal', () => {
  const univer = new Univer(); univer.registerPlugin(UniverSheetsPlugin)
  const injector = univer.__getInjector(), api = FUniver.newAPI(univer)
  const book = api.createWorkbook({ id: 'goto-focus', name: 'Go To', sheetOrder: ['s'], sheets: { s: { id: 's', name: 'Data', rowCount: 20, columnCount: 10 } } })
  const instance = injector.get(IUniverInstanceService)
  instance.focusUnit(book.getId())
  injector.add([ILayoutService, { useClass: DesktopLayoutService }])
  const layout = injector.get(ILayoutService)
  const root = document.createElement('main'), opener = document.createElement('button'), editorHost = document.createElement('textarea')
  root.append(opener, editorHost); document.body.append(root)
  const registered = layout.registerFocusHandler(UniverInstanceType.UNIVER_SHEET, unitId => { expect(unitId).toBe(book.getId()); editorHost.focus() })
  let afterCloseHidden = false
  const dialog = createGoToDialog(root, () => { book.setActiveRange(book.getActiveSheet()!.getRange('D5')); return null }, () => { afterCloseHidden = root.querySelector<HTMLElement>('[role="dialog"]')!.hidden; focusWorkbookGrid({ univer }) })
  try {
    opener.focus(); dialog.open([])
    const input = root.querySelector<HTMLInputElement>('[data-goto-reference]')!
    input.value = 'D5'; root.querySelector<HTMLFormElement>('form')!.requestSubmit()
    expect(afterCloseHidden).toBe(true)
    expect(book.getActiveRange()!.getA1Notation()).toContain('D5')
    expect(document.activeElement).toBe(editorHost)
  } finally { dialog.dispose(); registered.dispose(); univer.dispose() }
})

it('preserves dialog focus for invalid targets and restores the opener on cancel without handing off', () => {
  const root = document.createElement('main'), opener = document.createElement('button'), navigated = vi.fn()
  document.body.append(root, opener)
  const dialog = createGoToDialog(root, () => '无法定位', navigated)
  try {
    opener.focus(); dialog.open([])
    const input = root.querySelector<HTMLInputElement>('[data-goto-reference]')!
    input.value = 'invalid'; root.querySelector<HTMLFormElement>('form')!.requestSubmit()
    expect(root.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(false)
    expect(root.querySelector('[role="alert"]')!.textContent).toBe('无法定位')
    expect(document.activeElement).toBe(input); expect(navigated).not.toHaveBeenCalled()
    root.querySelector<HTMLButtonElement>('.workbook-ribbon-format-cancel')!.click()
    expect(document.activeElement).toBe(opener); expect(navigated).not.toHaveBeenCalled()
    dialog.open([]); dialog.dispose(); expect(navigated).not.toHaveBeenCalled()
  } finally { dialog.dispose() }
})

it('uses the same post-close handoff for double-clicked defined names', () => {
  const root = document.createElement('main'), opener = document.createElement('button'), grid = document.createElement('textarea')
  document.body.append(root, opener, grid)
  const go = vi.fn(() => null), navigated = vi.fn(() => grid.focus()), dialog = createGoToDialog(root, go, navigated)
  try {
    opener.focus(); dialog.open([{ name: 'Target', ref: 'Data!D5' }])
    root.querySelector<HTMLButtonElement>('[data-goto-name]')!.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
    expect(go).toHaveBeenCalledWith('Target'); expect(navigated).toHaveBeenCalledOnce()
    expect(document.activeElement).toBe(grid)
  } finally { dialog.dispose() }
})

it('skips absent layout service in headless hosts and propagates real focus errors', () => {
  expect(() => focusWorkbookGrid({ univer: {} })).not.toThrow()
  const univer = new Univer()
  try { expect(() => focusWorkbookGrid({ univer })).not.toThrow() } finally { univer.dispose() }
  const runtime = { univer: { __getInjector: () => ({ has: () => true, get: () => ({ focus: () => { throw new Error('focus failed') } }) }) } } as never
  expect(() => focusWorkbookGrid(runtime)).toThrow('focus failed')
})
