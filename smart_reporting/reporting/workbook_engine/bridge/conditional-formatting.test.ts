import {expect,it} from 'vitest'
import { createBlankWorkbook, readWorkbook, applyCfRules } from '../packages/xlsx-engine/src/index'
import { applyWorkbookOperations } from './operations'
import { createBufferEntrySource, assemblePackage } from '../packages/xlsx-engine/src/zip'
const ranges=[{startRow:0,endRow:2,startColumn:0,endColumn:0}]
const rule={ranges,stopIfTrue:false,rule:{type:'highlightCell',subType:'number',operator:'greaterThan',value:[5],style:{bl:1,bg:{rgb:'#C6EFCE'}}}}
it('replaces and clears native full rules through the bridge and exposes them on the workbook model',async()=>{
 const source=await createBlankWorkbook()
 const first=await applyWorkbookOperations(source,[{kind:'replaceSheetConditionalFormats',sheetName:'Sheet1',rules:[rule]}])
 const model=await readWorkbook(first)
 expect((model.sheets[0] as any).conditionalFormatting.rules).toHaveLength(1)
 expect((model.sheets[0] as any).conditionalFormatting.rules[0].rule).toMatchObject(rule.rule)
 const updated=await applyWorkbookOperations(first,[{kind:'replaceSheetConditionalFormats',sheetName:'Sheet1',rules:[{...rule,rule:{...rule.rule,value:[9]}}]}])
 expect((await readWorkbook(updated)).sheets[0]!.conditionalFormatting!.rules).toHaveLength(1)
 const cleared=await applyWorkbookOperations(updated,[{kind:'replaceSheetConditionalFormats',sheetName:'Sheet1',rules:[]}])
 expect((await readWorkbook(cleared)).sheets[0]!.conditionalFormatting!.rules).toEqual([])
})
it('retains the old append operation alongside the new explicit replace operation',async()=>{
 const source=await applyCfRules(await createBlankWorkbook(),[{sheet:'Sheet1',sqref:'A1:A3',operator:'greaterThan',formula1:'5',bold:true}])
 const appended=await applyWorkbookOperations(source,[{kind:'applyCfRules',rules:[{sheet:'Sheet1',sqref:'B1:B3',operator:'lessThan',formula1:'10',fillColor:'#FF0000'}]}])
 expect((await readWorkbook(appended)).sheets[0]!.conditionalFormatting!.rules).toHaveLength(2)
})
it.each([
 {...rule,ranges:[{startRow:3,endRow:0,startColumn:0,endColumn:0}]},
 {...rule,stopIfTrue:'false'},
 {...rule,rule:{type:'highlightCell',subType:'timePeriod',value:'today'}},
 {...rule,rule:{type:'unknown'}},
 {...rule,foreign:true},
])('rejects invalid rule wire %j before changing file bytes',async invalid=>{
 const bytes=await createBlankWorkbook()
 await expect(applyWorkbookOperations(bytes,[{kind:'replaceSheetConditionalFormats',sheetName:'Sheet1',rules:[invalid]}])).rejects.toThrow()
 expect((await readWorkbook(bytes)).sheets[0]!.conditionalFormatting!.rules).toEqual([])
})
it('reports unknown original CF instead of projecting an editable empty snapshot and refuses destructive replacement',async()=>{
 const bytes=await createBlankWorkbook(),source=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml',before=await source.readText(path)
 const xml=before.replace('</worksheet>','<conditionalFormatting sqref="A1"><cfRule type="future" priority="1"><alien/></cfRule></conditionalFormatting></worksheet>')
 const input=(await assemblePackage(bytes,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const model=await readWorkbook(input)
 expect(model.sheets[0]!.conditionalFormatting!.issues.length).toBeGreaterThan(0)
 await expect(applyWorkbookOperations(input,[{kind:'replaceSheetConditionalFormats',sheetName:'Sheet1',rules:[]}])).rejects.toThrow(/incomplete/)
 expect(await(await createBufferEntrySource(input)).readText(path)).toBe(xml)
})
it('preserves linked source XML through bridge read/save and rejects its deletion without mutating input',async()=>{
 const bytes=await createBlankWorkbook(),source=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml',before=await source.readText(path)
 const id='{00000000-0000-0000-0000-000000000001}',ns='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
 const linked='<conditionalFormatting sqref="B1:B3"><cfRule type="dataBar" priority="3"><dataBar><cfvo type="min"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar><extLst><ext uri="{B025F937-C7B1-47D3-B67F-A62EFF666E3E}" xmlns:x14="'+ns+'"><x14:id>'+id+'</x14:id></ext></extLst></cfRule></conditionalFormatting>'
 const twin='<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}" xmlns:x14="'+ns+'"><x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"><x14:cfRule type="dataBar" priority="3" id="'+id+'"><x14:dataBar gradient="0"/></x14:cfRule><xm:sqref>B1:B3</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext></extLst>'
 const xml=before.replace('</worksheet>',linked+twin+'</worksheet>'),input=(await assemblePackage(bytes,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const model=(await readWorkbook(input)).sheets[0]!.conditionalFormatting!
 expect(model.issues).toEqual([]);expect(model.linkedRuleIds).toEqual([id]);expect(model.linkedRules).toHaveLength(1)
 expect(model).not.toHaveProperty('sourceXml')
 const saved=await applyWorkbookOperations(input,[{kind:'replaceSheetConditionalFormats',sheetName:'Sheet1',rules:[...model.rules,rule]}])
 const output=await(await createBufferEntrySource(saved)).readText(path);expect(output).toContain(linked);expect(output).toContain(twin)
 await expect(applyWorkbookOperations(input,[{kind:'replaceSheetConditionalFormats',sheetName:'Sheet1',rules:[]}])).rejects.toThrow(/linked/)
 expect(await(await createBufferEntrySource(input)).readText(path)).toBe(xml)
})
it.each([
 {kind:'replaceSheetConditionalFormats',sheetName:'Missing',rules:[]},
 {kind:'replaceSheetConditionalFormats',sheetName:'Sheet1',rules:[],sourceXml:'<forged/>'},
 {kind:'replaceSheetConditionalFormats',sheetName:'Sheet1',rules:[{...rule,ranges:[{startRow:0,endRow:1048576,startColumn:0,endColumn:0}]}]},
])('rejects invalid full-snapshot operation identity %j',async operation=>{
 await expect(applyWorkbookOperations(await createBlankWorkbook(),[operation])).rejects.toThrow()
})
