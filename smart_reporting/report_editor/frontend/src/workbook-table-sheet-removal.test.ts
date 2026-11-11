import { expect, it } from 'vitest'
import { assertTableSheetRemoval, type TableSheetRemovalSource } from './workbook-table-sheet-removal'
const source = (): TableSheetRemovalSource => ({ tables: [{ name: 'SalesData', displayName: 'SalesData' }], workbookXml: '<workbook><sheets><sheet name="Source"/><sheet name="Other"/></sheets></workbook>' })
function book(formula = '', names: any[] = [], cf: any[] = [], dv: any[] = []) {
  const make = (id: string, name: string, value: string) => ({ getSheetId: () => id, getSheetName: () => name,
    getSheet: () => ({ getCellMatrix: () => ({ forValue: (visit: any) => { if (value) visit(99999, 123, { f: value }) } }) }),
    getRange: () => ({ getFormula: () => value }), getConditionalFormattingRules: () => cf, getDataValidations: () => dv })
  const target = make('source', 'Source', '=SalesData[Amount]'), other = make('other', 'Other', formula)
  return { getActiveSheet: () => target, getSheetBySheetId: (id: string) => [target, other].find(sheet => sheet.getSheetId() === id), getSheets: () => [target, other], getDefinedNames: () => names,
    getTableList: () => [{ name: 'RenamedTable', subUnitId: 'source' }] }
}
const name = (formula: string, scope = 'AllDefaultWorkbook') => ({ getName: () => 'Dependency', getFormulaOrRefString: () => formula, getLocalSheetId: () => scope })
it.each(['=SUM(salesdata[Amount])', '=SUM(RenamedTable[Amount])'])('rejects offscreen live table dependency %s', formula => {
  expect(() => assertTableSheetRemoval(book(formula), 'source', source())).toThrow('表格')
})
it('permits a cleared dependency and ignores formulas and names owned by the removed sheet', () => {
  expect(() => assertTableSheetRemoval(book('=1', [name('SalesData[Amount]', 'source')]), 'source', source())).not.toThrow()
})
it.each(['AllDefaultWorkbook', 'other'])('protects surviving name scope %s', scope => {
  expect(() => assertTableSheetRemoval(book('', [name('sAlEsDaTa[Amount]', scope)]), 'source', source())).toThrow('Dependency')
})
it('checks actual conditional formatting and validation formula projections', () => {
  expect(() => assertTableSheetRemoval(book('', [], [{ rule: { type: 'formula', value: '=SalesData[Amount]>0' } }]), 'source', source())).toThrow('SalesData')
  expect(() => assertTableSheetRemoval(book('', [], [], [{ rule: { type: 'custom', formula2: '=SalesData[Amount]' } }]), 'source', source())).toThrow('SalesData')
})
it('protects only unprojected raw formula/CF/DV fragments, leaving cleared ordinary source formulas editable', () => {
  const raw = source()
  raw.worksheet = () => ({ xml: '<worksheet><sheetData><row><c><f>SUM(SalesData[Amount])</f></c></row></sheetData></worksheet>' })
  expect(() => assertTableSheetRemoval(book(), 'source', raw)).not.toThrow()
  raw.worksheet = () => ({ xml: '<worksheet><sheetData><row><c><f t="shared">SUM(SalesData[Amount])</f></c></row></sheetData></worksheet>' })
  expect(() => assertTableSheetRemoval(book(), 'source', raw)).toThrow('SalesData')
  raw.worksheet = () => ({ xml: '<worksheet><dataValidations><dataValidation><formula1>SUM(SalesData[Amount])</formula1></dataValidation></dataValidations></worksheet>', dataValidationIncomplete: true })
  expect(() => assertTableSheetRemoval(book(), 'source', raw)).toThrow('SalesData')
})
it('protects failed imported and built-in source names while permitting removed local scope', () => {
  const raw = source()
  raw.workbookXml = raw.workbookXml.replace('</workbook>', '<definedNames><definedName name="_xlnm.Print_Area" localSheetId="1">SalesData[Amount]</definedName></definedNames></workbook>')
  expect(() => assertTableSheetRemoval(book(), 'source', raw)).toThrow('完整投影')
  raw.workbookXml = raw.workbookXml.replace('localSheetId="1"', 'localSheetId="0"')
  expect(() => assertTableSheetRemoval(book(), 'source', raw)).not.toThrow()
})
it('preserves dependencies on a table part shared with a surviving sheet', () => {
  const raw = { ...source(), retainedNames: ['SalesData'] }, workbook = book('=SUM(SalesData[Amount])')
  workbook.getTableList = () => [{ name: 'SalesData', subUnitId: 'source' }]
  expect(() => assertTableSheetRemoval(workbook, 'source', raw)).not.toThrow()
})
it('refuses actual unregistered table ownership before live table access',async()=>{
 const {applyTableAdditions,createBlankWorkbook,readWorkbook}=await import('@sheets-web/xlsx-engine')
 const {assemblePackage,createBufferEntrySource}=await import('@sheets-web/xlsx-engine/zip')
 const bytes=await applyTableAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',name:'SalesData',area:{startRow:0,startColumn:0,endRow:2,endColumn:0},columnNames:['Amount'],bandedRows:true}]),zip=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml'
 const incomplete=(await assemblePackage(bytes,{replaced:new Map([[path,(await zip.readText(path)).replace(/<tableParts\b[\s\S]*?<\/tableParts>/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const sheet=(await readWorkbook(incomplete)).sheets[0]!,workbook=book()
 let reads=0;workbook.getTableList=()=>{reads++;return[]}
 expect(()=>assertTableSheetRemoval(workbook,'source',{...source(),tables:sheet.tableSources??[],readOnlyReason:sheet.tableSourcesReadOnlyReason})).toThrow('未完整登记')
 expect(reads).toBe(0)
})
