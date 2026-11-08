import { afterEach, expect, it } from 'vitest'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { FUniver } from '@univerjs/core/lib/facade'
import { ICommandService, IUniverInstanceService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { applyWorkbookRibbonCommand, type RibbonWorkbook } from './workbook-ribbon'
import { diffToEdits } from './workbook-vendor/core/session-core'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { readBackSnapshot } from './workbook-vendor/grid/sync'
import { independentPython } from './test-independent-python'

afterEach(() => document.body.replaceChildren())

const styledBook = async () => applyCellEdits(await createBlankWorkbook(), [
  { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 1234.567 }, style: { bold: true, fillColor: '#FFF2CC', numberFormat: '0.000', borderBottom: { style: 'thin', color: '#654321' } } },
  { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null, formula: '=A1*2' }, style: { italic: true } },
  // 纯样式格（无值）：清除格式 → styleReset；全部清除 → 整格退回默认样式。
  { sheetName: 'Sheet1', row: 0, column: 2, writeValue: true, cell: { value: null }, style: { underline: true } },
  // 无显式样式的值格：格式清除不得产生任何编辑。
  { sheetName: 'Sheet1', row: 0, column: 3, writeValue: true, cell: { value: 'plain' } },
])

const openRealGrid = async (bytes: Uint8Array) => {
  const model = await readWorkbook(bytes)
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  univer.registerPlugin(UniverSheetsPlugin)
  const api = FUniver.newAPI(univer)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, buildWorkbookData(model, 'clear-book', 'clear'))
  const workbook = api.getActiveWorkbook()!
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  const commands = univer.__getInjector().get(ICommandService)
  return { model, univer, workbook, commands, api }

}

const clearThroughRibbon = (workbook: ReturnType<FUniver['getActiveWorkbook']>, commands: ICommandService) =>
  applyWorkbookRibbonCommand('clear-formats', workbook as unknown as RibbonWorkbook,
    undefined, undefined, undefined,
    kind => !!commands.syncExecuteCommand(kind === 'all' ? 'sheet.command.clear-selection-all' : 'sheet.command.clear-selection-format'),
  )

it('clear-formats resets mixed styles to the default xf through the official command and survives openpyxl readback', async () => {
  const original = await styledBook()
  const { model, univer, workbook, commands } = await openRealGrid(original)
  try {
    workbook.getActiveSheet()!.setActiveSelection(workbook.getActiveSheet()!.getRange('A1:D1'))
    const before = diffToEdits(model, readBackSnapshot(workbook.save()))
    expect(before).toEqual([])
    // 与固定源一致：清除格式走官方 sheet.command.clear-selection-format。
    expect(clearThroughRibbon(workbook, commands)).toBe(true)
    const edits = diffToEdits(model, readBackSnapshot(workbook.save()))
    expect(edits).toEqual([
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: false, cell: { value: 1234.567 }, styleReset: true },
      { sheetName: 'Sheet1', row: 0, column: 1, writeValue: false, cell: { value: null, formula: '=A1*2' }, styleReset: true },
      { sheetName: 'Sheet1', row: 0, column: 2, writeValue: false, cell: { value: null }, styleReset: true },
    ])
    // Undo/恢复：官方撤销后差分回到空，重做后样式清除再次被捕。
    expect(commands.syncExecuteCommand('univer.command.undo')).toBe(true)
    expect(diffToEdits(model, readBackSnapshot(workbook.save()))).toEqual(before)
    expect(commands.syncExecuteCommand('univer.command.redo')).toBe(true)
    expect(diffToEdits(model, readBackSnapshot(workbook.save()))).toEqual(edits)
    const cleared = await readWorkbook(await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits }]))
    const cells = cleared.sheets[0]!.cells
    for (const address of ['A1', 'B1', 'C1']) {
      expect(cells[address]!.styleIndex, address).toBe(0)
    }
    expect(cells.A1!.value).toBe(1234.567)
    expect(cells.B1!.formula).toBe('=A1*2')
    expect(cells.D1!.value).toBe('plain')
    const dir = await mkdtemp(join(tmpdir(), 'xlsx-clearfmt-'))
    const file = resolve(dir, 'clear-formats.xlsx')
    await writeFile(file, await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits }]))
    const checked = spawnSync(independentPython(), ['-I', '-c',
      "import json,openpyxl,sys; w=openpyxl.load_workbook(sys.argv[1],data_only=False); s=w.active; print(json.dumps({'a':[s['A1'].value,s['A1'].font.bold,s['A1'].fill.fill_type,s['A1'].number_format,s['A1'].border.bottom.style],'b':[s['B1'].value,s['B1'].font.italic],'c':[s['C1'].font.underline],'d':s['D1'].value}))", file], { encoding: 'utf8' })
    expect(checked.status, checked.stderr).toBe(0)
    expect(JSON.parse(checked.stdout)).toEqual({
      a: [1234.567, false, null, 'General', null], b: ['=A1*2', false], c: [null], d: 'plain',
    })
    console.info(`Independent openpyxl verified clear-formats XLSX: ${file}`)
  } finally { univer.dispose() }
})

it('clear-all empties values and formulas with the style reset, keeping the cell at the default xf', async () => {
  const original = await styledBook()
  const { model, univer, workbook, commands } = await openRealGrid(original)
  try {
    workbook.getActiveSheet()!.setActiveSelection(workbook.getActiveSheet()!.getRange('A1:C1'))
    // clear-all 与固定源一致走官方 sheet.command.clear-selection-all。
    expect(applyWorkbookRibbonCommand('clear-all', workbook as unknown as RibbonWorkbook,
      undefined, undefined, undefined,
      kind => !!commands.syncExecuteCommand(kind === 'all' ? 'sheet.command.clear-selection-all' : 'sheet.command.clear-selection-format'),
    )).toBe(true)
    const readback = readBackSnapshot(workbook.save())
    const edits = diffToEdits(model, readBackSnapshot(workbook.save()))
    expect(edits).toEqual([
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: null }, styleReset: true },
      { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null }, styleReset: true },
      { sheetName: 'Sheet1', row: 0, column: 2, writeValue: false, cell: { value: null }, styleReset: true },
    ])
    expect(commands.syncExecuteCommand('univer.command.undo')).toBe(true)
    expect(diffToEdits(model, readBackSnapshot(workbook.save()))).toEqual([])
    expect(commands.syncExecuteCommand('univer.command.redo')).toBe(true)
    const cleared = await readWorkbook(await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits }]))
    const cells = cleared.sheets[0]!.cells
    for (const address of ['A1', 'B1', 'C1']) {
      expect(cells[address]!.value ?? null, address).toBeNull()
      expect(cells[address]!.formula, address).toBeUndefined()
      expect(cells[address]!.styleIndex, address).toBe(0)
    }
    expect(cells.D1!.value).toBe('plain')
    const dir = await mkdtemp(join(tmpdir(), 'xlsx-clearall-'))
    const file = resolve(dir, 'clear-all.xlsx')
    await writeFile(file, await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits }]))
    const checked = spawnSync(independentPython(), ['-I', '-c',
      "import json,openpyxl,sys; s=openpyxl.load_workbook(sys.argv[1],data_only=False).active; print(json.dumps({'a':[s['A1'].value,s['A1'].font.bold],'b':s['B1'].value,'c':s['C1'].value,'d':s['D1'].value}))", file], { encoding: 'utf8' })
    expect(checked.status, checked.stderr).toBe(0)
    expect(JSON.parse(checked.stdout)).toEqual({ a: [null, false], b: null, c: null, d: 'plain' })
    console.info(`Independent openpyxl verified clear-all XLSX: ${file}`)
  } finally { univer.dispose() }
})
