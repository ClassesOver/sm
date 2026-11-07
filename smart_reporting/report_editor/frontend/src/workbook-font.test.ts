import { afterEach, expect, it, vi } from 'vitest'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { NativeDraft } from './native-draft'
import { FUniver } from '@univerjs/core/lib/facade'
import { BooleanNumber, ICommandService, IUniverInstanceService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { applyWorkbookFontDecoration } from './workbook-font'
import { selectedWorkbookFormat, type FormatWorkbook } from './workbook-format'
import { applyWorkbookRibbonCommand, mountWorkbookRibbon, type RibbonWorkbook } from './workbook-ribbon'
import { diffToEdits } from './workbook-vendor/core/session-core'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { fromUniverStyle, styleDelta, toUniverStyle, type UniverStyleData } from './workbook-vendor/core/style-map'
import { readBackSnapshot } from './workbook-vendor/grid/sync'

afterEach(() => document.body.replaceChildren())

it('aggregates mixed strike, applies a style-only patch, and honors selection/save locks', () => {
  const styles = [{ st: { s: 1 } }, { st: { s: 0 } }]
  const setValue = vi.fn((patch: { s: { st: { s: number } } }) => styles.forEach(style => { style.st = { ...patch.s.st } }))
  const range: any = { getRow: () => 0, getColumn: () => 0, getHeight: () => 2, getWidth: () => 1, setValue }
  let selected = true, editable = true
  const workbook: any = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => selected ? range : null }), getRange: (row: number) => ({ getCellStyleData: () => styles[row] }) }) }
  const host = document.createElement('div'), dispatch = vi.fn(() => applyWorkbookRibbonCommand('strike', workbook))
  const ribbon = mountWorkbookRibbon(host, dispatch, { rotation: () => 0, editable: () => editable, hasSelection: () => selected, format: () => selectedWorkbookFormat(workbook) })
  const button = host.querySelector<HTMLButtonElement>('[data-ribbon-command="strike"]')!
  expect(button.getAttribute('aria-pressed')).toBe('mixed')
  button.click()
  expect(setValue).toHaveBeenCalledExactlyOnceWith({ s: { st: { s: 1 } } })
  ribbon.refreshState(); expect(button.getAttribute('aria-pressed')).toBe('true')
  editable = false; ribbon.refreshState(); button.click()
  expect(button.disabled).toBe(true); expect(setValue).toHaveBeenCalledTimes(1)
  editable = true; selected = false; ribbon.refreshState(); button.click()
  expect(button.disabled).toBe(true); expect(setValue).toHaveBeenCalledTimes(1)
  expect(applyWorkbookRibbonCommand('strike', workbook)).toBe(false)
  expect(() => applyWorkbookFontDecoration('strike', range, selectedWorkbookFormat(null))).toThrow('选择')
  selected = true; range.getHeight = () => 10001
  expect(() => applyWorkbookRibbonCommand('strike', workbook)).toThrow('预算')
  expect(setValue).toHaveBeenCalledTimes(1)
  expect(() => applyWorkbookFontDecoration('strike', {}, selectedWorkbookFormat({ ...workbook, getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => ({ ...range, getHeight: () => 1 }) }), getRange: () => ({ getCellStyleData: () => ({}) }) }) }))).toThrow('命令')
  ribbon.dispose()
})

it('allows only note navigation/display in a readonly ribbon and still enforces noteReason', () => {
  const host = document.createElement('div'), command = vi.fn()
  let selected = true, noteReason: string | undefined
  const ribbon = mountWorkbookRibbon(host, command, { rotation: () => 0, editable: () => false, hasSelection: () => selected, noteReason: () => noteReason })
  host.querySelector<HTMLButtonElement>('[data-ribbon-tab="Review"]')!.click()
  const readCommands = ['note-prev', 'note-next', 'note-show-toggle']
  for (const id of readCommands) {
    const button = host.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
    expect(button.disabled).toBe(false); button.click()
  }
  expect(command.mock.calls.map(call => call[0])).toEqual(readCommands)
  for (const id of ['note-open', 'note-delete']) {
    const button = host.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
    expect(button.disabled).toBe(true); button.click()
  }
  expect(command).toHaveBeenCalledTimes(3)
  noteReason = '当前工作表没有批注'; ribbon.refreshState()
  for (const id of readCommands) {
    const button = host.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
    expect(button.disabled).toBe(true); expect(button.title).toBe(noteReason)
  }
  noteReason = undefined; selected = false; ribbon.refreshState()
  for (const id of readCommands) expect(host.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!.disabled).toBe(true)
  ribbon.dispose()
})


it('maps double underline without spurious edits and distinguishes single/double mixed state', () => {
  const source = { underline: true, underlineStyle: 'double' as const, strikethrough: true }
  expect(toUniverStyle(source)).toEqual({ ul: { s: 1, t: 10 }, st: { s: 1 } })
  expect(fromUniverStyle(toUniverStyle(source))).toEqual(source)
  expect(styleDelta(source, fromUniverStyle(toUniverStyle(source)))).toBeUndefined()
  expect(styleDelta(source, { underline: true, underlineStyle: 'single', strikethrough: true })).toEqual({ underlineStyle: 'single' })
  expect(styleDelta(source, { underline: false, strikethrough: true })).toEqual({ underline: false })
  const styles: UniverStyleData[] = [{ ul: { s: 1, t: 10 }, st: { s: 1 } }, { ul: { s: 1, t: 0 }, st: { s: 1 } }]
  const range: any = { getRow: () => 0, getColumn: () => 0, getHeight: () => 2, getWidth: () => 1,
    setValue: (patch: { s: { ul?: { s: number; t: number }; st?: { s: number } } }) => styles.forEach(style => Object.assign(style, patch.s)) }
  let editable = true, selected = true
  const workbook: any = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => selected ? range : null }), getRange: (row: number) => ({ getCellStyleData: () => styles[row] }) }) }
  const host = document.createElement('div')
  const ribbon = mountWorkbookRibbon(host, command => { applyWorkbookRibbonCommand(command, workbook) }, { rotation: () => 0, editable: () => editable, hasSelection: () => selected, format: () => selectedWorkbookFormat(workbook) })
  const button = host.querySelector<HTMLButtonElement>('[data-ribbon-command="underline:double"]')!
  expect(button.getAttribute('aria-pressed')).toBe('mixed')
  button.click(); ribbon.refreshState()
  expect(button.getAttribute('aria-pressed')).toBe('true')
  expect(styles).toEqual([{ ul: { s: 1, t: 10 }, st: { s: 1 } }, { ul: { s: 1, t: 10 }, st: { s: 1 } }])
  button.click(); ribbon.refreshState()
  expect(button.getAttribute('aria-pressed')).toBe('false')
  expect(styles[0]).toEqual({ ul: { s: 0, t: 10 }, st: { s: 1 } })
  applyWorkbookRibbonCommand('underline', workbook)
  expect(styles[0]).toEqual({ ul: { s: 1, t: 12 }, st: { s: 1 } })
  editable = false; ribbon.refreshState(); expect(button.disabled).toBe(true)
  editable = true; selected = false; ribbon.refreshState(); expect(button.disabled).toBe(true)
  ribbon.dispose()
})

it('double underline uses actual Univer Undo/Redo, preserves strike, and survives draft and independent openpyxl readback', async () => {
  const original = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 1234.567 }, style: { strikethrough: true, bold: true, fontColor: '#123456', numberFormat: '0.000' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null, formula: '=A1*2' }, style: { strikethrough: true, underline: true } },
  ])
  const model = await readWorkbook(original)
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    const api = FUniver.newAPI(univer)
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, buildWorkbookData(model, 'double-book', 'double'))
    const workbook = api.getActiveWorkbook()!, sheet = workbook.getActiveSheet()!
    univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
    const commands = univer.__getInjector().get(ICommandService)
    sheet.setActiveSelection(sheet.getRange('A1:B1'))
    const before = workbook.save()
    expect(applyWorkbookRibbonCommand('underline:double', workbook as unknown as RibbonWorkbook)).toBe(true)
    expect(selectedWorkbookFormat(workbook as unknown as FormatWorkbook).doubleUnderline).toEqual({ kind: 'value', value: true })
    expect(selectedWorkbookFormat(workbook as unknown as FormatWorkbook).strikethrough).toEqual({ kind: 'value', value: true })
    expect(commands.syncExecuteCommand('univer.command.undo')).toBe(true)
    expect(diffToEdits(model, readBackSnapshot(workbook.save()))).toEqual(diffToEdits(model, readBackSnapshot(before)))
    expect(commands.syncExecuteCommand('univer.command.redo')).toBe(true)
    const edits = diffToEdits(model, readBackSnapshot(workbook.save()))
    expect(edits.map(edit => edit.style)).toEqual([{ underline: true, underlineStyle: 'double' }, { underlineStyle: 'double' }])
    expect(edits.every(edit => edit.writeValue === false)).toBe(true)
    const store = new Map<string, string>(), storage = { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => { store.set(key, value) }, removeItem: (key: string) => { store.delete(key) } }
    const identity = { documentId: 'double', revision: 1, sourceSha256: 'b'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'user', threadId: 'thread' } }
    new NativeDraft(identity, storage).setOperations([{ kind: 'applyCellEdits', edits }])
    const bytes = await applyWorkbookOperations(original, new NativeDraft(identity, storage).operations)
    const reread = await readWorkbook(bytes)
    const projected = buildWorkbookData(reread, 'double-restored', 'restored')
    const cells = projected.sheets[projected.sheetOrder[0]!]!.cellData
    for (const col of [0, 1]) expect(projected.styles[String(cells[0]![col]!.s)]).toMatchObject({ st: { s: 1 }, ul: { s: 1, t: 10 } })
    const dir = await mkdtemp(join(tmpdir(), 'xlsx-double-')), file = join(dir, 'double.xlsx')
    await writeFile(file, bytes)
    const result = spawnSync('/home/junge/pros/smart_reporting/.venv/bin/python', ['-I', '-c', "import json,openpyxl,sys; s=openpyxl.load_workbook(sys.argv[1],data_only=False).active; print(json.dumps([[s[c].value,s[c].font.underline,s[c].font.strike] for c in ['A1','B1']]))", file], { encoding: 'utf8' })
    expect(result.status, result.stderr).toBe(0)
    expect(JSON.parse(result.stdout)).toEqual([[1234.567, 'double', true], ['=A1*2', 'double', true]])
    console.info(`Independent openpyxl verified double underline XLSX: ${file}`)
    applyWorkbookRibbonCommand('underline:double', workbook as unknown as RibbonWorkbook)
    expect(selectedWorkbookFormat(workbook as unknown as FormatWorkbook).doubleUnderline).toEqual({ kind: 'value', value: false })
    expect(selectedWorkbookFormat(workbook as unknown as FormatWorkbook).strikethrough).toEqual({ kind: 'value', value: true })
    const cleared = await readWorkbook(await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits: diffToEdits(model, readBackSnapshot(workbook.save())) }]))
    for (const cell of ['A1', 'B1']) expect(cleared.styles.fonts[cleared.styles.cellXfs[cleared.sheets[0]!.cells[cell]!.styleIndex!]!.fontId]!.underline).toBe('none')
  } finally { univer.dispose() }
})

it('routes deletion strike through the Home ribbon and displays its pressed state', () => {
  const style: any = { st: { s: BooleanNumber.FALSE }, ul: { s: BooleanNumber.TRUE } }
  const range: any = {
    getRow: () => 0, getColumn: () => 0, getHeight: () => 1, getWidth: () => 1,
    getCellStyleData: () => style,
    setValue: (value: any) => { Object.assign(style, value.s) },
  }
  const workbook: any = { getActiveSheet: () => ({
    getSelection: () => ({ getActiveRange: () => range }),
    getRange: () => ({ getCellStyleData: () => style }),
  }) }
  const host = document.createElement('div')
  document.body.append(host)
  const ribbon = mountWorkbookRibbon(host, () => undefined, {
    rotation: () => 0, editable: () => true, hasSelection: () => true,
    format: () => selectedWorkbookFormat(workbook as FormatWorkbook),
  })
  const button = host.querySelector<HTMLButtonElement>('[data-ribbon-command="strike"]')!
  expect(button.disabled).toBe(false)
  expect(button.getAttribute('aria-pressed')).toBe('false')
  expect(applyWorkbookRibbonCommand('strike', workbook as RibbonWorkbook)).toBe(true)
  expect(style.st.s).toBe(BooleanNumber.TRUE)
  expect(style.ul.s).toBe(BooleanNumber.TRUE)
  ribbon.refreshState()
  expect(button.getAttribute('aria-pressed')).toBe('true')
  expect(applyWorkbookRibbonCommand('strike', workbook as RibbonWorkbook)).toBe(true)
  expect(style.st.s).toBe(BooleanNumber.FALSE)
  expect(style.ul.s).toBe(BooleanNumber.TRUE)
  ribbon.dispose()
})

it('uses official Univer style commands with undo/redo and roundtrips only strike to an XLSX file', async () => {
  const preservedStyle = { bold: true, italic: true, underline: true, underlineStyle: 'double' as const, fontFamily: 'Calibri', fontSize: 14, fontColor: '#123456', fillColor: '#ABCDEF', numberFormat: '0.000', textRotation: 45, borderBottom: { style: 'double' as const, color: '#654321' } }
  const original = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'label' }, style: preservedStyle },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 2, formula: '=1+1' }, style: { ...preservedStyle, strikethrough: true } },
  ])
  const model = await readWorkbook(original)
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    const api = FUniver.newAPI(univer)
    const data = (await import('./workbook-vendor/core/univer-data')).buildWorkbookData(model, 'font-book', '字体')
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, data)
    const workbook = api.getActiveWorkbook()!
    const sheet = workbook.getActiveSheet()!
    const commands = univer.__getInjector().get(ICommandService)
    univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
    const range = sheet.getRange(0, 0)
    sheet.setActiveSelection(sheet.getRange('A1'))
    const before = range.getCellStyleData()
    applyWorkbookFontDecoration('strike', range, selectedWorkbookFormat(workbook as unknown as FormatWorkbook))
    expect(range.getCellStyleData()?.st?.s).toBe(BooleanNumber.TRUE)
    expect(range.getCellStyleData()?.ul?.s).toBe(before?.ul?.s)
    expect(commands.syncExecuteCommand('univer.command.undo')).toBe(true)
    expect(range.getCellStyleData()?.st?.s).toBe(before?.st?.s)
    expect(commands.syncExecuteCommand('univer.command.redo')).toBe(true)
    expect(range.getCellStyleData()?.st?.s).toBe(BooleanNumber.TRUE)

    const edits = diffToEdits(model, readBackSnapshot(workbook.getSnapshot()))
    expect(edits).toEqual([{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: false, cell: { value: 'label' }, style: { strikethrough: true } }])
    const reopened = await readWorkbook(await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits }]))
    expect(reopened.sheets[0]!.cells.A1!.value).toBe('label')
    expect(reopened.sheets[0]!.cells.B1!.formula).toBe('=1+1')
    expect(reopened.styles.fonts[reopened.styles.cellXfs[reopened.sheets[0]!.cells.A1!.styleIndex!]!.fontId]!.underline).toBe('double')
    expect(reopened.styles.fonts[reopened.styles.cellXfs[reopened.sheets[0]!.cells.A1!.styleIndex!]!.fontId]!.bold).toBe(true)
    expect(reopened.styles.fonts[reopened.styles.cellXfs[reopened.sheets[0]!.cells.A1!.styleIndex!]!.fontId]!.italic).toBe(true)
    expect(reopened.styles.fonts[reopened.styles.cellXfs[reopened.sheets[0]!.cells.A1!.styleIndex!]!.fontId]!.size).toBe(14)
    expect(reopened.styles.fonts[reopened.styles.cellXfs[reopened.sheets[0]!.cells.A1!.styleIndex!]!.fontId]!.family).toBe('Calibri')
    expect(reopened.styles.fonts[reopened.styles.cellXfs[reopened.sheets[0]!.cells.A1!.styleIndex!]!.fontId]!.strikethrough).toBe(true)
    expect(reopened.sheets[0]!.cells.B1!.formula).toBe('=1+1')
    const dir = await mkdtemp(join(tmpdir(), 'xlsx-strike-'))
    const file = resolve(dir, 'strike.xlsx')
    await writeFile(file, await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits }]))
    const checked = spawnSync('/home/junge/pros/smart_reporting/.venv/bin/python', ['-I', '-c', "import json,openpyxl,sys; w=openpyxl.load_workbook(sys.argv[1],data_only=False); s=w.active; print(json.dumps({'value':s['A1'].value,'formula':s['B1'].value,'strike':s['A1'].font.strike,'bold':s['A1'].font.bold,'italic':s['A1'].font.italic,'underline':s['A1'].font.underline,'size':s['A1'].font.sz,'family':s['A1'].font.name,'rotation':s['A1'].alignment.textRotation,'fill':s['A1'].fill.fgColor.rgb,'number_format':s['A1'].number_format}))", file], { encoding: 'utf8' })
    expect(checked.status, checked.stderr).toBe(0)
    expect(JSON.parse(checked.stdout)).toMatchObject({ value: 'label', formula: '=1+1', strike: true, bold: true, italic: true, underline: 'double', size: 14, family: 'Calibri', rotation: 45, fill: 'FFABCDEF', number_format: '0.000' })
    expect(fromUniverStyle(range.getCellStyleData()! as import('./workbook-vendor/core/style-map').UniverStyleData)).toMatchObject({ strikethrough: true })

    sheet.setActiveSelection(sheet.getRange('A1:B1'))
    // A1 on, B1 on: toggle both off without touching the double underline.
    expect(applyWorkbookRibbonCommand('strike', workbook as unknown as RibbonWorkbook)).toBe(true)
    expect(selectedWorkbookFormat(workbook as unknown as FormatWorkbook).strikethrough).toEqual({ kind: 'value', value: false })
    const offEdits = diffToEdits(model, readBackSnapshot(workbook.getSnapshot()))
    expect(offEdits.map(edit => edit.style)).toEqual([{ strikethrough: false }])
    expect(offEdits.every(edit => edit.writeValue === false)).toBe(true)
    const store = new Map<string, string>()
    const storage = { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => { store.set(key, value) }, removeItem: (key: string) => { store.delete(key) } }
    const identity = { documentId: 'strike', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'user', threadId: 'thread' } }
    new NativeDraft(identity, storage).setOperations([{ kind: 'applyCellEdits', edits: offEdits }])
    const restored = new NativeDraft(identity, storage)
    const restoredModel = await readWorkbook(await applyWorkbookOperations(original, restored.operations))
    const restoredData = (await import('./workbook-vendor/core/univer-data')).buildWorkbookData(restoredModel, 'restored', 'restored')
    const cells = restoredData.sheets[restoredData.sheetOrder[0]!]!.cellData
    expect(restoredModel.sheets[0]!.cells.A1!.value).toBe('label')
    expect(restoredModel.sheets[0]!.cells.B1!.formula).toBe('=1+1')
    expect(restoredData.styles[String(cells[0]![1]!.s)]?.st?.s ?? 0).toBe(0)
    expect(restoredData.styles[String(cells[0]![1]!.s)]?.ul).toEqual({ s: 1, t: 10 })
  } finally {
    univer.dispose()
  }
})
