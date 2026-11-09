import { afterEach, expect, it, vi } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Univer, UniverInstanceType, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { readBackSnapshot } from './workbook-vendor/grid/sync'
import { diffToEdits } from './workbook-vendor/core/session-core'
import { fromUniverStyle, indentToUniverPadding, styleDelta, toUniverStyle, univerPaddingToIndent, INDENT_STEP_PX } from './workbook-vendor/core/style-map'
import { applyWorkbookRibbonCommand, mountWorkbookRibbon, type RibbonWorkbook } from './workbook-ribbon'
import { CLIPBOARD_COMMANDS, PASTE_SPECIAL_CHOICES, clipboardCommandParams } from './workbook-clipboard'
import { independentPython } from './test-independent-python'

const univers: Univer[] = []
afterEach(() => { univers.splice(0).forEach(univer => univer.dispose()); document.body.replaceChildren() })

it('maps OOXML indent steps to the fixed-source 8px left padding and keeps an explicit clear distinct from untouched', () => {
  expect(INDENT_STEP_PX).toBe(8)
  expect(toUniverStyle({ indent: 3 }).pd).toEqual({ l: 24 })
  expect(fromUniverStyle(toUniverStyle({ indent: 3 }))).toEqual({ indent: 3 })
  // 清零写 Univer 默认 2px（显示等同无缩进），回读为显式 0。
  expect(indentToUniverPadding(0)).toEqual({ l: 2 })
  expect(univerPaddingToIndent({ l: 2 })).toBe(0)
  expect(univerPaddingToIndent(undefined)).toBeUndefined()
  expect(indentToUniverPadding(999)).toEqual({ l: 250 * 8 })
  // 未触碰（无 pd）不产生编辑；显式清除才写回 0；无缩进单元格"减到 0"不是编辑。
  expect(styleDelta({ indent: 2 }, {})).toBeUndefined()
  expect(styleDelta({ indent: 2 }, { indent: 0 })).toEqual({ indent: 0 })
  expect(styleDelta(undefined, { indent: 0 })).toBeUndefined()
  expect(styleDelta({ indent: 1 }, { indent: 2 })).toEqual({ indent: 2 })
})

it('indent-step moves every selected cell one level relative to itself on real Univer and persists to the XLSX', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '二级' }, style: { indent: 2, bold: true } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: '无缩进' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 42 }, style: { numberFormat: '0.00' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: '选区外' }, style: { indent: 4 } },
  ])
  const model = await readWorkbook(source)
  expect(model.sheets[0]!.indentReadOnlyReason).toBeUndefined()
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  univers.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, buildWorkbookData(model, 'indent', 'indent'))
  const workbook = FUniver.newAPI(univer).getActiveWorkbook()!
  const sheet = workbook.getActiveSheet()
  // 加载后未修改：缩进投影回读无差分。
  expect(diffToEdits(model, readBackSnapshot(workbook.getSnapshot()))).toEqual([])
  const selected = sheet.getRange(0, 0, 3, 1)
  const ribbonWorkbook = { getActiveSheet: () => Object.assign(Object.create(sheet), { getSelection: () => ({ getActiveRange: () => selected }) }) } as unknown as RibbonWorkbook
  expect(applyWorkbookRibbonCommand('indent-step:increase', ribbonWorkbook)).toBe(true)
  expect([0, 1, 2].map(row => univerPaddingToIndent(sheet.getRange(row, 0).getCellStyleData()?.pd as never))).toEqual([3, 1, 1])
  // 值、粗体、数字格式不被缩进写入覆盖。
  expect(sheet.getRange(0, 0, 3, 1).getValues().map(row => row[0])).toEqual(['二级', '无缩进', 42])
  const increased = diffToEdits(model, readBackSnapshot(workbook.getSnapshot()))
  expect(increased.map(edit => `${edit.row},${edit.column}:${JSON.stringify(edit.style)}`)).toEqual(['0,0:{"indent":3}', '1,0:{"indent":1}', '2,0:{"indent":1}'])
  let saved = await readWorkbook(await applyWorkbookOperations(source, [{ kind: 'applyCellEdits', edits: increased }]))
  const indentOf = (address: string) => saved.styles.cellXfs[saved.sheets[0]!.cells[address]!.styleIndex ?? 0]?.alignment?.indent ?? 0
  expect(['A1', 'A2', 'A3', 'B1'].map(indentOf)).toEqual([3, 1, 1, 4])
  expect(saved.styles.fonts[saved.styles.cellXfs[saved.sheets[0]!.cells.A1!.styleIndex!]!.fontId]?.bold).toBe(true)
  // 再减少两次：A2/A3 显式清零写回 0，A1 降到 1。
  applyWorkbookRibbonCommand('indent-step:decrease', ribbonWorkbook)
  applyWorkbookRibbonCommand('indent-step:decrease', ribbonWorkbook)
  const decreased = diffToEdits(model, readBackSnapshot(workbook.getSnapshot()))
  const bytes = await applyWorkbookOperations(source, [{ kind: 'applyCellEdits', edits: decreased }])
  saved = await readWorkbook(bytes)
  expect(['A1', 'A2', 'A3', 'B1'].map(indentOf)).toEqual([1, 0, 0, 4])
  expect(saved.sheets[0]!.cells.A3!.value).toBe(42)
  // 独立 openpyxl 回读 alignment.indent 与数字格式。
  const file = join(await mkdtemp(join(tmpdir(), 'xlsx-indent-')), 'indent.xlsx')
  await writeFile(file, bytes)
  const checked = spawnSync(independentPython(), ['-I', '-c', "import json,openpyxl,sys; s=openpyxl.load_workbook(sys.argv[1]).active; print(json.dumps([[s[c].value, s[c].alignment.indent, s[c].number_format] for c in ['A1','A2','A3','B1']]))", file], { encoding: 'utf8' })
  expect(checked.status, checked.stderr).toBe(0)
  expect(JSON.parse(checked.stdout)).toEqual([['二级', 1, 'General'], ['无缩进', 0, 'General'], [42, 0, '0.00'], ['选区外', 4, 'General']])
})

it('refuses indent for oversized selections and unknown steps', () => {
  const range = { getHeight: () => 101, getWidth: () => 100, getRow: () => 0, getColumn: () => 0, setValues: vi.fn() }
  const workbook = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => range }), getRange: () => ({}) }) } as unknown as RibbonWorkbook
  expect(() => applyWorkbookRibbonCommand('indent-step:increase', workbook)).toThrow('10000')
  expect(() => applyWorkbookRibbonCommand('indent-step:sideways' as never, workbook)).toThrow('不支持此缩进操作')
  expect(range.setValues).not.toHaveBeenCalled()
})

it('wires the clipboard group to the official Univer commands with read-only-safe copy', () => {
  expect(CLIPBOARD_COMMANDS).toMatchObject({ copy: 'univer.command.copy', cut: 'univer.command.cut', paste: 'univer.command.paste', 'paste-special:value': 'sheet.command.paste-value', 'paste-special:formula': 'sheet.command.paste-formula', 'paste-special:format': 'sheet.command.paste-format', 'paste-special:col-width': 'sheet.command.paste-col-width', 'paste-special:besides-border': 'sheet.command.paste-besides-border' })
  // Univer 0.25.1 粘贴权限检查读取 params.value：普通粘贴必须带空参数对象。
  expect(clipboardCommandParams('paste')).toEqual({})
  expect(clipboardCommandParams('copy')).toBeUndefined()
  const host = document.createElement('div'); document.body.append(host)
  const command = vi.fn(); let editable = true, selected = true, indentReason: string | undefined
  const ribbon = mountWorkbookRibbon(host, command, { rotation: () => 0, editable: () => editable, hasSelection: () => selected, indentReason: () => indentReason })
  host.querySelector<HTMLButtonElement>('[role="tab"][data-ribbon-tab="Home"]')!.click()
  const button = (id: string) => host.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
  const pasteSpecial = host.querySelector<HTMLSelectElement>('[data-ribbon-menu="paste-special"]')!
  for (const id of ['paste', 'cut', 'copy', 'indent-step:increase', 'indent-step:decrease']) {
    expect(button(id).disabled, id).toBe(false)
    expect(button(id).dataset.unavailableReason, id).toBeUndefined()
    button(id).click()
  }
  expect(command.mock.calls.map(call => call[0])).toEqual(['paste', 'cut', 'copy', 'indent-step:increase', 'indent-step:decrease'])
  expect([...pasteSpecial.options].slice(1).map(option => option.value)).toEqual(PASTE_SPECIAL_CHOICES.map(choice => choice.value))
  pasteSpecial.value = 'paste-special:value'; pasteSpecial.dispatchEvent(new Event('change'))
  expect(command).toHaveBeenLastCalledWith('paste-special:value')
  expect(pasteSpecial.value).toBe('')
  // 只读/保存中：复制仍可用，剪切/粘贴/选择性粘贴/缩进禁用。
  editable = false; ribbon.refreshState()
  expect(button('copy').disabled).toBe(false)
  for (const id of ['paste', 'cut', 'indent-step:increase']) expect(button(id).disabled, id).toBe(true)
  expect(pasteSpecial.disabled).toBe(true)
  // 无选区：复制也禁用。
  selected = false; ribbon.refreshState(); expect(button('copy').disabled).toBe(true)
  // 继承缩进来源：缩进按钮以原因禁用，其余剪贴板命令不受影响。
  editable = true; selected = true; indentReason = '继承格式不可回读'; ribbon.refreshState()
  expect(button('indent-step:increase').disabled).toBe(true)
  expect(button('indent-step:increase').title).toBe('继承格式不可回读')
  expect(button('paste').disabled).toBe(false)
  ribbon.dispose()
})
