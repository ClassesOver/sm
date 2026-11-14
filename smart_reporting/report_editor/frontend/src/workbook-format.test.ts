import { afterEach, expect, it, vi } from 'vitest'
import {
  selectedWorkbookFormat, validateNumberFormat, captureNumberFormatTarget, applyCapturedNumberFormat,
  validateNumberFormatBudget, createNumberFormatDialog, omitCalculatedNumberFormats, type FormatWorkbook, type FormatRange,
} from './workbook-format'
import { mountWorkbookRibbon, applyWorkbookRibbonCommand, type RibbonWorkbook } from './workbook-ribbon'
import { fromUniverStyle, styleDelta, type UniverStyleData } from './workbook-vendor/core/style-map'
import { readBackSnapshot } from './workbook-vendor/grid/sync'
import { diffToEdits } from './workbook-vendor/core/session-core'
import type { WorkbookModel } from '@sheets-web/xlsx-engine'

afterEach(() => document.body.replaceChildren())
function fixture(styles: UniverStyleData[] = [{ ff: 'Calibri', fs: 14, bl: 1, cl: { rgb: '#123456' }, bg: { rgb: '#abcdef' }, n: { pattern: '#,##0.00' } }]) {
  const setNumberFormat = vi.fn()
  const range: FormatRange = { getRow: () => 0, getColumn: () => 0, getHeight: () => styles.length, getWidth: () => 1, setNumberFormat }
  let active: FormatRange | null = range
  const sheet = { getSheetId: () => 's', getSheetName: () => '明细', getSelection: () => ({ getActiveRange: () => active }), getRange: (row: number) => ({ getCellStyleData: () => styles[row]! }) }
  const underlying = {}
  const workbook: FormatWorkbook = { getId: () => 'book', getWorkbook: () => underlying, getActiveSheet: () => sheet, getSheetBySheetId: id => id === 's' ? sheet : null }
  return { workbook, sheet, range, setNumberFormat, select(value: FormatRange | null) { active = value } }
}
const model = (): WorkbookModel => ({ sheets: [{ name: '明细', path: 'xl/worksheets/sheet1.xml', cells: { A1: { value: 1234.567 }, B1: { value: null, formula: '=A1*2' } }, merges: [], rows: [], columns: [], freeze: null, showGridlines: true, zoomScale: 100, dimension: null }], styles: { fonts: [], fills: [], borders: [], cellXfs: [], numFmts: new Map() }, themePalette: undefined })

it('strips only formula-result inferred number formats while preserving explicit n and other styles', () => {
  const snapshot: any = { styles: { source: { n: { pattern: '#,##0.00' }, ff: 'Calibri', fs: 14, bl: 1, cl: { rgb: '#123456' } }, explicit: { n: { pattern: '#,##0.0000' }, it: 1 } } }
  const command: any = { id: 'sheet.mutation.set-range-values', params: { trigger: 'sheet.command.set-range-values', unitId: 'book', subUnitId: 'details', cellValue: { 0: { 0: { f: '=Summary!A1', v: 1234.567, s: 'source' }, 1: { v: 7, s: 'explicit' } } } } }
  expect(omitCalculatedNumberFormats(command, snapshot)).toBe(false)
  expect(command.params.cellValue[0][0].s).toBe('source')
  command.options = { fromFormula: true, applyFormulaCalculationResult: true }
  expect(omitCalculatedNumberFormats(command, snapshot)).toBe(true)
  expect(command.params.trigger).toBe('sheet.command.set-range-values')
  expect(command.params.cellValue[0][0]).toMatchObject({ f: '=Summary!A1', v: 1234.567, s: { ff: 'Calibri', fs: 14, bl: 1, cl: { rgb: '#123456' } } })
  expect(command.params.cellValue[0][0].s.n).toBeUndefined()
  expect(command.params.cellValue[0][1]).toEqual({ v: 7, s: { it: 1 } })
  expect(snapshot.styles.explicit.n.pattern).toBe('#,##0.0000')
  const manual: any = { id: 'sheet.mutation.set-range-values', options: { fromFormula: false }, params: { cellValue: { 0: { 0: { s: { n: { pattern: 'General' }, bl: 1 } } } } } }
  expect(omitCalculatedNumberFormats(manual, snapshot)).toBe(false)
  expect(manual.params.cellValue[0][0].s).toMatchObject({ n: { pattern: 'General' }, bl: 1 })
  const missingOptions: any = { id: 'sheet.mutation.set-range-values', params: { cellValue: { 0: { 0: { s: { n: { pattern: '0.00' } } } } } } }
  expect(omitCalculatedNumberFormats(missingOptions, snapshot)).toBe(false)
  expect(missingOptions.params.cellValue[0][0].s.n.pattern).toBe('0.00')
})

it('reads each selected property independently and never uses the first cell for mixed formatting', () => {
  const f = fixture([
    { ff: 'Calibri', fs: 14, bl: 1, it: 1, ul: { s: 1 }, cl: { rgb: '#123456' }, bg: { rgb: '#abcdef' }, n: { pattern: '0.00' } },
    { ff: 'Arial', fs: 12, bl: 0, it: 1, ul: { s: 0 }, cl: { rgb: '#654321' }, bg: { rgb: '#abcdef' }, n: { pattern: '0%' } },
  ])
  const state = selectedWorkbookFormat(f.workbook)
  for (const key of ['fontFamily', 'fontSize', 'bold', 'underline', 'fontColor', 'numberFormat'] as const) expect(state[key]).toEqual({ kind: 'mixed' })
  expect(state.italic).toEqual({ kind: 'value', value: true })
  expect(state.fillColor).toEqual({ kind: 'value', value: '#abcdef' })
})

it('uses the composed public single-cell API and marks missing source inheritance unavailable', () => {
  const f = fixture()
  expect(selectedWorkbookFormat(f.workbook).fontSize).toEqual({ kind: 'value', value: 14 })
  const source = model(); source.sheets[0]!.rotationReadOnlyReason = 'xlsx_rotation_inherited_style_unsupported'
  expect(selectedWorkbookFormat(f.workbook, source).fontColor).toMatchObject({ kind: 'unavailable', reason: expect.stringContaining('继承样式') })
  f.select(null)
  expect(selectedWorkbookFormat(f.workbook).numberFormat).toMatchObject({ kind: 'unavailable' })
})

it('validates with the pinned number-format parser and preserves significant literal spaces', () => {
  for (const code of ['#,##0.000', '0.00%;[Red]-0.00%', 'yyyy-mm-dd', '[h]:mm:ss', 'General', '0.00" 元" ']) expect(validateNumberFormat(code)).toBe(code)
  for (const code of ['', ' ', '0'.repeat(256), '0\n', '[invalid]0', '"unterminated']) expect(() => validateNumberFormat(code), JSON.stringify(code)).toThrow()
})

it('applies only the captured range across facade wrappers, rejects no target/save lock/stale workbook', () => {
  const f = fixture(), target = captureNumberFormatTarget(f.workbook)
  f.select({ ...f.range, getRow: () => 50, setNumberFormat: vi.fn() })
  applyCapturedNumberFormat(target, { ...f.workbook }, '#,##0.000', true)
  expect(f.setNumberFormat).toHaveBeenCalledExactlyOnceWith('#,##0.000')
  for (const run of [
    () => applyCapturedNumberFormat(undefined, f.workbook, '0.00', true),
    () => applyCapturedNumberFormat(target, f.workbook, '0.00', false),
    () => applyCapturedNumberFormat(target, { ...f.workbook, getWorkbook: () => ({}) }, '0.00', true),
    () => applyCapturedNumberFormat(target, f.workbook, '[invalid]0', true),
  ]) expect(run).toThrow()
  expect(f.setNumberFormat).toHaveBeenCalledTimes(1)
  f.select({ ...f.range, getHeight: () => 10001 })
  expect(() => captureNumberFormatTarget(f.workbook)).toThrow('预算')
})

it('projects only numberFormat edits, preserves formulas/values, and persists explicit General resets', () => {
  const data = { styles: { custom: { ff: 'Calibri', fs: 14, n: { pattern: '0.000' } } }, sheets: { s: { name: '明细', cellData: { 0: { 0: { v: 1234.567, s: 'custom' }, 1: { f: '=A1*2' } } } } }, sheetOrder: ['s'] }
  const f = fixture(), target = captureNumberFormatTarget(f.workbook)!
  expect(() => validateNumberFormatBudget(data, model(), [], 0, target, '#,##0.000')).not.toThrow()
  expect(data.styles.custom.n.pattern).toBe('0.000')
  expect(() => validateNumberFormatBudget(data, model(), Array.from({ length: 500 }, () => ({ kind: 'applyCellEdits', edits: [] })), 0, target, '0.00')).toThrow('预算')
  expect(fromUniverStyle({ n: { pattern: 'General' } })).toEqual({ numberFormat: 'General' })
  expect(styleDelta({ numberFormat: '0.000' }, fromUniverStyle({ n: { pattern: 'General' } }))).toEqual({ numberFormat: 'General' })
  const before = model()
  const after = structuredClone(data)
  after.styles.custom = { ...after.styles.custom, n: { pattern: 'General' } }
  const edits = diffToEdits(before, readBackSnapshot(after))
  expect(edits).toHaveLength(1)
  expect(edits[0]).toMatchObject({ row: 0, column: 0, writeValue: false, style: { numberFormat: 'General' } })
  expect(after.sheets.s.cellData[0][1].f).toBe('=A1*2')
})

it('dialog cancellation and invalid submissions never mutate; valid application keeps its frozen target', () => {
  const f = fixture(), target = captureNumberFormatTarget(f.workbook), apply = vi.fn()
  const dialog = createNumberFormatDialog(document.body, { apply, initial: () => ({ kind: 'mixed' }) })
  dialog.open(target)
  const input = document.querySelector<HTMLInputElement>('.workbook-ribbon-format-code')!
  expect(input.value).toBe('')
  input.value = '0.000'; document.querySelector<HTMLButtonElement>('.workbook-ribbon-format-cancel')!.click()
  expect(apply).not.toHaveBeenCalled()
  dialog.open(target); input.value = '[invalid]0'
  document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).not.toHaveBeenCalled(); expect(input.getAttribute('aria-invalid')).toBe('true')
  input.value = '#,##0.000'; document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).toHaveBeenCalledExactlyOnceWith(target, '#,##0.000')
  dialog.dispose()
})

it('renders mixed state, actual single-cell state, Chinese tabs, roving focus and accurate save locks', () => {
  const f = fixture(), command = vi.fn(); let editable = true
  const host = document.createElement('div'); document.body.append(host)
  const ribbon = mountWorkbookRibbon(host, command, { rotation: () => 0, editable: () => editable, hasSelection: () => true, format: () => selectedWorkbookFormat(f.workbook), captureTarget: () => captureNumberFormatTarget(f.workbook) })
  expect(host.querySelector<HTMLSelectElement>('[data-ribbon-control="font-family"]')!.value).toBe('Calibri')
  expect(host.querySelector<HTMLInputElement>('[data-ribbon-control="fill"]')!.value).toBe('#abcdef')
  expect(host.querySelector('[data-ribbon-command="bold"]')!.getAttribute('aria-pressed')).toBe('true')
  const tabs = [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
  // 固定源页签顺序以"文件"开头；激活页签仍是"开始"，roving tabindex 只落在它上面。
  expect(tabs.map(tab => tab.dataset.ribbonTab)).toEqual(['File', 'Home', 'Insert', 'Page Layout', 'Formulas', 'Data', 'Review', 'View', 'Chart Design'])
  expect(tabs.map(tab => tab.tabIndex)).toEqual([-1, 0, -1, -1, -1, -1, -1, -1, -1])
  tabs[1]!.focus(); tabs[1]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
  expect((document.activeElement as HTMLElement).dataset.ribbonTab).toBe('Insert')
  host.querySelector<HTMLElement>('[role="tablist"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }))
  // Home 键回到首个页签（文件）；数字格式命令位于"开始"页签，点回后再操作。
  expect((document.activeElement as HTMLElement).dataset.ribbonTab).toBe('File')
  host.querySelector<HTMLButtonElement>('[role="tab"][data-ribbon-tab="Home"]')!.click()
  const custom = host.querySelector<HTMLButtonElement>('[data-ribbon-command="format:custom-open"]')!
  custom.focus(); custom.click(); expect(command.mock.calls[0]![1]).toMatchObject({ row: 0, height: 1 })
  editable = false; ribbon.refreshState()
  for (const el of host.querySelectorAll<HTMLButtonElement | HTMLSelectElement | HTMLInputElement>('[data-ribbon-control]:not(span), [data-ribbon-command="bold"], [data-ribbon-command="replace"], [data-ribbon-command="format:custom-open"]')) expect(el.disabled).toBe(true)
  expect(host.querySelector<HTMLButtonElement>('[data-ribbon-command="find"]')!.disabled).toBe(false)
  ribbon.dispose()
})

it('mixed bold toggles on rather than using the first selected bold cell to toggle off', () => {
  const f = fixture([{ bl: 1 }, { bl: 0 }]), setFontWeight = vi.fn()
  Object.assign(f.range, { setFontWeight })
  applyWorkbookRibbonCommand('bold', f.workbook as unknown as RibbonWorkbook)
  expect(setFontWeight).toHaveBeenCalledWith('bold')
})
