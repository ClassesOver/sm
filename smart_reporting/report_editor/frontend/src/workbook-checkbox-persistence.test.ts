import { expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
it('retains the actual checkbox type through the workbook save/read chain', async () => {
 const bytes = await applyWorkbookOperations(await createBlankWorkbook(), [{kind:'replaceSheetDataValidations', sheetName:'Sheet1',rules:[{ranges:[{startRow:0,endRow:0,startColumn:0,endColumn:0}],rule:{type:'checkbox'}}]}])
 const model = await readWorkbook(bytes)
 expect(model.sheets[0]!.dataValidations!.rules[0]!.rule.type).toBe('checkbox')
})

import { applyDvRules } from '@sheets-web/xlsx-engine/data-validation'
import { readDataValidations } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/data-validation-read'
const area = [{startRow:0,endRow:1,startColumn:0,endColumn:0}]
const base = '<worksheet><sheetData/><extLst><ext uri="foreign"><other keep="yes"/></ext></extLst></worksheet>'
it('distinguishes ordinary lists and retains custom checkbox values and full fallback options', () => {
 const rules = [{ranges:area,rule:{type:'checkbox',formula1:'Yes & <',formula2:'No',allowBlank:true,error:'提示',showErrorMessage:true}},
  {ranges:[{startRow:0,endRow:0,startColumn:1,endColumn:1}],rule:{type:'list',formula1:'1,0'}}]
 const saved = applyDvRules(base,rules), model = readDataValidations(saved)
 expect(model.readOnlyReason).toBeUndefined()
 expect(model.rules[0]!.rule).toMatchObject(rules[0]!.rule)
 expect(model.rules[1]!.rule.type).toBe('list')
 expect(saved).toContain('<ext uri="foreign"><other keep="yes"/></ext>')
 expect(applyDvRules(saved,[])).not.toContain('sr:checkboxes')
 expect(applyDvRules(saved,[])).toContain('<ext uri="foreign"><other keep="yes"/></ext>')
})
it.each([
 ['range', (xml:string)=>xml.replace('sqref="A1:A2"','sqref="C1:C2"')],
 ['value', (xml:string)=>xml.replace('<formula1>"1,0"</formula1>','<formula1>"Yes,No"</formula1>')],
 ['option', (xml:string)=>xml.replace('type="list"','type="list" allowBlank="1"')],
 ['namespace', (xml:string)=>xml.replace('https://smart-reporting.local/ns/xlsx/checkbox/1','https://foreign.invalid')],
 ['payload', (xml:string)=>xml.replace('version="1">[', 'version="1">invalid[')],
])('ignores %s metadata mismatch while preserving ordinary fallback validation', (_name, mutate) => {
 const saved=applyDvRules(base,[{ranges:area,rule:{type:'checkbox'}}])
 const model=readDataValidations(mutate(saved))
 expect(model.readOnlyReason).toBeUndefined()
 expect(model.rules).toHaveLength(1)
 expect(model.rules[0]!.rule.type).toBe('list')
})
it('requires unique actual fallback identity and preserves append/replace/remove cycles', () => {
 const rule={ranges:area,rule:{type:'checkbox'}}
 const first=applyDvRules(base,[rule])
 const duplicated=first.replace('</dataValidations>',first.match(/<dataValidation type[\s\S]*?<\/dataValidation>/)![0]+'</dataValidations>').replace('count="1"','count="2"')
 expect(readDataValidations(duplicated).rules.map(item=>item.rule.type)).toEqual(['list','list'])
 const appended=applyDvRules(first,[rule],{append:true})
 expect(readDataValidations(appended).rules[0]!.rule.type).toBe('checkbox')
 const replaced=applyDvRules(appended,[{ranges:area,rule:{type:'list',formula1:'1,0'}}],{append:true})
 expect(readDataValidations(replaced).rules[0]!.rule.type).toBe('list')
 const removed=applyDvRules(first,[],{append:true,remove:area})
 expect(readDataValidations(removed).rules).toEqual([])
 const readded=applyDvRules(removed,[{ranges:area,rule:{type:'list',formula1:'1,0'}}],{append:true})
 expect(readDataValidations(readded).rules[0]!.rule.type).toBe('list')
})
it('never reauthorizes stale metadata while appending an unrelated validation', () => {
 const first=applyDvRules(base,[{ranges:area,rule:{type:'checkbox'}}])
 const stale=first.replace('"fallback":','"fallback":"foreign","discard":')
 expect(readDataValidations(stale).rules[0]!.rule.type).toBe('list')
 const appended=applyDvRules(stale,[{ranges:[{startRow:0,endRow:0,startColumn:4,endColumn:4}],rule:{type:'list',formula1:'other'}}],{append:true})
 expect(readDataValidations(appended).rules[0]!.rule.type).toBe('list')
})
