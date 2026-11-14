import { expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, LocaleType, Univer, UniverInstanceType, IUndoRedoService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { AddCfCommand, SetCfCommand, DeleteCfCommand, UniverSheetsConditionalFormattingPlugin } from '@univerjs/sheets-conditional-formatting'
import { createBlankWorkbook, readWorkbook, type WorkbookModel } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-conditional-formatting/facade'
const implementation = './workbook-conditional-formatting'
const ranges = [{ startRow: 1, endRow: 4, startColumn: 1, endColumn: 1 }]
const wire = { ranges, stopIfTrue: true, rule: { type: 'highlightCell', subType: 'number', operator: 'greaterThan', value: [10], style: { bg: { rgb: '#FF0000' } } } }
async function source() {
  const bytes = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'replaceSheetConditionalFormats', sheetName: 'Sheet1', rules: [wire] }])
  return { bytes, model: await readWorkbook(bytes) }
}
async function runtime(model: WorkbookModel) {
  const { withWorkbookConditionalFormatting } = await import(/* @vite-ignore */ implementation)
  const univer = new Univer({ locale: LocaleType.EN_US })
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsConditionalFormattingPlugin)
  univer.__getInjector().get(IUndoRedoService)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookConditionalFormatting(buildWorkbookData(model, 'cf-module', 'CF'), model))
  univer.__getInjector().get(IUniverInstanceService).focusUnit('cf-module')
  const univerAPI = FUniver.newAPI(univer), workbook = univerAPI.getActiveWorkbook()!, sheet = workbook.getActiveSheet()
  return { univer, univerAPI, workbook, sheet, commands: univer.__getInjector().get(ICommandService), params: { unitId: workbook.getId(), subUnitId: sheet.getSheetId() } }
}
it('imports complete official CF resource without history and captures edit, removal, undo and redo through save/read', async () => {
  const { workbookConditionalFormattingOperations } = await import(/* @vite-ignore */ implementation)
  const { bytes, model } = await source(), c = await runtime(model)
  try {
    const rules = c.sheet.getConditionalFormattingRules()
    expect(rules).toHaveLength(1); expect(rules[0]).toMatchObject({ ...wire, rule: { ...wire.rule, value: 10 } })
    expect(workbookConditionalFormattingOperations(model, c.workbook)).toEqual([])
    expect(await c.univerAPI.undo()).toBe(false)
    const changed = { ...rules[0]!, stopIfTrue: false, rule: { ...rules[0]!.rule, value: [20] } }
    expect(c.commands.syncExecuteCommand(SetCfCommand.id, { ...c.params, rule: changed, cfId: rules[0]!.cfId })).toBe(true)
    const operations = workbookConditionalFormattingOperations(model, c.workbook)
    expect(operations).toMatchObject([{ kind: 'replaceSheetConditionalFormats', rules: [{ stopIfTrue: false, rule: { value: [20] } }] }])
    const saved = await readWorkbook(await applyWorkbookOperations(bytes, operations))
    expect(saved.sheets[0]!.conditionalFormatting!.rules[0]).toMatchObject({ stopIfTrue: false, rule: { value: [20] } })
    expect(workbookConditionalFormattingOperations(saved, c.workbook)).toEqual([])
    expect(await c.univerAPI.undo()).toBe(true)
    expect(workbookConditionalFormattingOperations(model, c.workbook)).toEqual([])
    expect(await c.univerAPI.redo()).toBe(true)
    expect(c.commands.syncExecuteCommand(DeleteCfCommand.id, { ...c.params, cfId: rules[0]!.cfId })).toBe(true)
    expect(workbookConditionalFormattingOperations(model, c.workbook)).toEqual([{ kind: 'replaceSheetConditionalFormats', sheetName: 'Sheet1', rules: [] }])
    expect(await c.univerAPI.undo()).toBe(true); expect(c.sheet.getConditionalFormattingRules()).toHaveLength(1)
  } finally { c.univer.dispose() }
})
it('keeps ordered full rules including offscreen disjoint formula, scale/bar and stopIfTrue', async () => {
  const { withWorkbookConditionalFormatting, workbookConditionalFormattingOperations } = await import(/* @vite-ignore */ implementation)
  const model = await readWorkbook(await createBlankWorkbook())
  const rules = [wire, { ranges: [{ startRow: 5000, endRow: 9000, startColumn: 22, endColumn: 22 }, ...ranges], stopIfTrue: false, rule: { type: 'highlightCell', subType: 'formula', value: '$B5001>0', style: {} } },
    { ranges, stopIfTrue: false, rule: { type: 'colorScale', config: [{ index: 0, color: '#FF0000', value: { type: 'min' } }, { index: 1, color: '#00FF00', value: { type: 'max' } }] } },
    { ranges, stopIfTrue: false, rule: { type: 'dataBar', isShowValue: true, config: { min: { type: 'min' }, max: { type: 'max' }, positiveColor: '#00FF00', nativeColor: '#FF0000', isGradient: true } } }]
  model.sheets[0]!.conditionalFormatting = { rules, issues: [], linkedRuleIds: [], linkedRules: [] }
  const c = await runtime(model)
  try {
    expect(c.sheet.getConditionalFormattingRules()).toHaveLength(4)
    expect(c.sheet.getConditionalFormattingRules()[1]!.rule).toMatchObject({ value: '=$B5001>0' })
    expect(workbookConditionalFormattingOperations(model, c.workbook)).toEqual([])
    const resources = withWorkbookConditionalFormatting({ sheets: { x: { id: 'x', name: 'Sheet1' } }, resources: [{ name: 'other', data: 'keep' }] }, model).resources
    expect(resources.find((item: {name:string}) => item.name === 'other')!.data).toBe('keep')
  } finally { c.univer.dispose() }
})
it('preflights unsupported edits and preserves linked or incomplete source snapshots', async () => {
  const { validateConditionalFormattingEdit, workbookConditionalFormattingOperations, withWorkbookConditionalFormatting } = await import(/* @vite-ignore */ implementation)
  const { model } = await source(), c = await runtime(model)
  try {
    const current = c.sheet.getConditionalFormattingRules(), source = model.sheets[0]!.conditionalFormatting!
    expect(() => validateConditionalFormattingEdit(AddCfCommand.id, { rule: { ...current[0], rule: { type: 'highlightCell', subType: 'timePeriod', style: {} } } }, current, source)).toThrow()
    const linked = { ...source, linkedRules: source.rules, linkedRuleIds: ['linked'] }
    expect(() => validateConditionalFormattingEdit(DeleteCfCommand.id, { cfId: current[0]!.cfId }, current, linked)).toThrow(/linked|关联/i)
    expect(() => validateConditionalFormattingEdit(SetCfCommand.id, { cfId: current[0]!.cfId, rule: { ...current[0], stopIfTrue: false } }, current, linked)).toThrow(/linked|关联/i)
    model.sheets[0]!.conditionalFormatting = { ...source, issues: ['unknown extension'] }
    expect(withWorkbookConditionalFormatting({ sheets: { x: { id: 'x', name: 'Sheet1' } } }, model).resources).toEqual([])
    expect(workbookConditionalFormattingOperations(model, c.workbook)).toEqual([])
    expect(() => validateConditionalFormattingEdit(AddCfCommand.id, { rule: current[0] }, current, model.sheets[0]!.conditionalFormatting)).toThrow(/unknown extension/)
  } finally { c.univer.dispose() }
})

it('normalizes native scalar number rules through writer and reader without a phantom follow-up edit', async () => {
  const { workbookConditionalFormattingOperations } = await import(/* @vite-ignore */ implementation)
  const bytes = await createBlankWorkbook(), model = await readWorkbook(bytes), c = await runtime(model)
  try {
    expect(c.commands.syncExecuteCommand(AddCfCommand.id, { ...c.params, rule: { ranges, stopIfTrue: false, rule: { type: 'highlightCell', subType: 'number', operator: 'greaterThan', value: 5, style: {} } } })).toBe(true)
    const operations = workbookConditionalFormattingOperations(model, c.workbook)
    const saved = await readWorkbook(await applyWorkbookOperations(bytes, operations))
    expect(workbookConditionalFormattingOperations(saved, c.workbook)).toEqual([])
  } finally { c.univer.dispose() }
})

it('does not persist implicit conditional-formatting colors when only the rule value changes', async () => {
  const { workbookConditionalFormattingOperations } = await import(/* @vite-ignore */ implementation)
  const blank = await createBlankWorkbook(), model = await readWorkbook(await applyWorkbookOperations(blank, [{
    kind: 'replaceSheetConditionalFormats', sheetName: 'Sheet1', rules: [{ ...wire, rule: { ...wire.rule, value: [10], style: {} } }],
  }]))
  const c = await runtime(model)
  try {
    const rule = c.sheet.getConditionalFormattingRules()[0]!
    const changed = { ...rule, rule: { ...rule.rule, value: 20, style: { cl: { rgb: '#2f56ef' }, bg: { rgb: '#e8ecfc' } } } }
    expect(c.commands.syncExecuteCommand(SetCfCommand.id, { ...c.params, cfId: rule.cfId, rule: changed })).toBe(true)
    expect(workbookConditionalFormattingOperations(model, c.workbook)).toEqual([{
      kind: 'replaceSheetConditionalFormats', sheetName: 'Sheet1',
      rules: [{ ranges, stopIfTrue: true, rule: { ...wire.rule, value: [20], style: {} } }],
    }])
  } finally { c.univer.dispose() }
})

it('keeps conditional-formatting colors that differ from the framework defaults', async () => {
  const { workbookConditionalFormattingOperations } = await import(/* @vite-ignore */ implementation)
  const blank = await createBlankWorkbook(), model = await readWorkbook(await applyWorkbookOperations(blank, [{
    kind: 'replaceSheetConditionalFormats', sheetName: 'Sheet1', rules: [{ ...wire, rule: { ...wire.rule, style: {} } }],
  }]))
  const c = await runtime(model)
  try {
    const rule = c.sheet.getConditionalFormattingRules()[0]!
    const changed = { ...rule, rule: { ...rule.rule, style: { cl: { rgb: '#123456' }, bg: { rgb: '#abcdef' } } } }
    expect(c.commands.syncExecuteCommand(SetCfCommand.id, { ...c.params, cfId: rule.cfId, rule: changed })).toBe(true)
    expect(workbookConditionalFormattingOperations(model, c.workbook)[0]).toMatchObject({
      rules: [{ rule: { style: { cl: { rgb: '#123456' }, bg: { rgb: '#abcdef' } } } }],
    })
  } finally { c.univer.dispose() }
})

it('extends native sheet dimensions to offscreen CF and rejects out-of-file-grid ranges before hydration', async () => {
  const { withWorkbookConditionalFormatting } = await import(/* @vite-ignore */ implementation)
  const model = await readWorkbook(await createBlankWorkbook())
  model.sheets[0]!.conditionalFormatting = { rules: [{ ...wire, ranges: [{ startRow: 0, endRow: 1048575, startColumn: 3, endColumn: 3 }] }], issues: [], linkedRuleIds: [], linkedRules: [] }
  const data = withWorkbookConditionalFormatting({ sheets: { x: { id: 'x', name: 'Sheet1', rowCount: 1000, columnCount: 26 } } }, model)
  expect(data.sheets.x.rowCount).toBe(1048576)
  expect(data.sheets.x.columnCount).toBe(26)
  model.sheets[0]!.conditionalFormatting.rules = [{ ...wire, ranges: [{ startRow: 0, endRow: 1048576, startColumn: 0, endColumn: 0 }] }]
  expect(() => withWorkbookConditionalFormatting({ sheets: { x: { id: 'x', name: 'Sheet1' } } }, model)).toThrow()
})
