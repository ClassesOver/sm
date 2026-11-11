import { expect, it } from 'vitest'
import { applyDefinedNameAction, liveDefinedNames } from './workbook-defined-names'
import { installDefinedNameScopes } from './workbook-defined-name-scope'

it('reload preserves scope dispatch registration and same-name CRUD', async () => {
  const { Univer, LocaleType, IUniverInstanceService } = await import('@univerjs/core')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverFormulaEnginePlugin } = await import('@univerjs/engine-formula')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  await import('@univerjs/sheets/facade')
  const { createBlankWorkbook, applyDefinedNames, readWorkbook } = await import('@sheets-web/xlsx-engine')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { loadWorkbookData } = await import('./workbook-vendor/grid/sync')
  const source = await applyDefinedNames(await createBlankWorkbook(), { sets: [{ name: 'Rate', refersTo: '10' }, { name: 'Rate', refersTo: '20', scopeSheetName: 'Sheet1' }] })
  const model = await readWorkbook(source), univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  let installed: ReturnType<typeof installDefinedNameScopes> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin)
    const api = FUniver.newAPI(univer), runtime = { univer, univerAPI: api }
    loadWorkbookData(runtime as any, buildWorkbookData(model, 'review-scope', 'scope'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('review-scope')
    installed = installDefinedNameScopes(runtime)
    loadWorkbookData(runtime as any, buildWorkbookData(model, 'review-scope', 'scope'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('review-scope')
    const current = api.getActiveWorkbook()!
    const result = applyDefinedNameAction(current, { kind: 'update', originalName: 'Rate', name: 'Rate', ref: '21', scopeSheetId: 'sheet-0' }, liveDefinedNames(current)!)
    expect(result).toBeNull()
    expect(liveDefinedNames(current)).toContainEqual({ name: 'Rate', refersTo: '21', scopeSheetId: 'sheet-0' })
    expect(liveDefinedNames(current)).toContainEqual({ name: 'Rate', refersTo: '10' })
    expect(applyDefinedNameAction(current, { kind: 'update', originalName: 'Rate', name: 'RenamedRate', ref: '22', scopeSheetId: 'sheet-0' }, liveDefinedNames(current)!)).toBeNull()
    await api.undo()
    expect(liveDefinedNames(current)).toContainEqual({ name: 'Rate', refersTo: '21', scopeSheetId: 'sheet-0' })
  } finally { installed?.dispose(); univer.dispose() }
})


it('sheet reorder retains opaque invalid scope ordinals', async () => {
  const { applySheetPlanToWorkbookXml } = await import('../../../reporting/workbook_engine/packages/xlsx-engine/src/sheets-edit')
  const opaque = '<definedName name="Opaque" localSheetId="99">999</definedName>'
  const xml = '<workbook><sheets><sheet name="One" sheetId="1" r:id="rId1"/><sheet name="Two" sheetId="2" r:id="rId2"/></sheets><definedNames>' + opaque + '</definedNames></workbook>'
  expect(applySheetPlanToWorkbookXml(xml, { renames: [], removals: [], additions: [], order: ['Two', 'One'] }, [])).toContain(opaque)
})

it('local unqualified references shift only with their owning sheet', async () => {
  const { shiftDefinedNames } = await import('../../../reporting/workbook_engine/packages/xlsx-engine/src/structural')
  const xml = '<workbook><sheets><sheet name="One" sheetId="1" r:id="rId1"/><sheet name="Two" sheetId="2" r:id="rId2"/></sheets><definedNames><definedName name="Local" localSheetId="0">$A$1</definedName><definedName name="Local" localSheetId="1">$A$1</definedName></definedNames></workbook>'
  const result = shiftDefinedNames(xml, { axis: 'row', start: 0, delta: 1 }, 'One')
  expect(result).toContain('<definedName name="Local" localSheetId="0">$A$2</definedName>')
  expect(result).toContain('<definedName name="Local" localSheetId="1">$A$1</definedName>')
})

it('decodes local scope sheet names before shifting unqualified references', async () => {
  const { shiftDefinedNames } = await import('../../../reporting/workbook_engine/packages/xlsx-engine/src/structural')
  const xml = '<workbook><sheets custom="1"><sheet name="财务&amp;&quot;预算&quot;" sheetId="1"/></sheets><definedNames><definedName name="Local" localSheetId="0">$A$1</definedName><definedName name="Global">$A$1</definedName></definedNames></workbook>'
  const result = shiftDefinedNames(xml, { axis: 'row', start: 0, delta: 1 }, '财务&"预算"')
  expect(result).toContain('<definedName name="Local" localSheetId="0">$A$2</definedName>')
  expect(result).toContain('<definedName name="Global">$A$1</definedName>')
})
