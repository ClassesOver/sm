import {expect,it} from 'vitest'
import {applySheetEdits,createBlankWorkbook,readWorkbook} from '../src'
import {assemblePackage,createBufferEntrySource} from '../src/zip'
import {escapeXmlText} from '../src/xml'

it.each([
 ['Source!$A$1:$A$5',true],
 ['source!$a$1:$a$5',true],
 ['"Source!A1,Other"',false],
 ['[book.xlsx]Source!$A$1:$A$5',false],
])('retains fixed-source DV removal refusal for %s',async(formula,referenced)=>{
 const base=await applySheetEdits(await createBlankWorkbook(),{renames:[{sheetName:'Sheet1',newName:'Source'}],additions:[{name:'Other'}],removals:[],order:['Source','Other']})
 const before=await createBufferEntrySource(base),path='xl/worksheets/sheet2.xml',xml=(await before.readText(path)).replace('</worksheet>',`<dataValidations count="1"><dataValidation type="list" sqref="B1:B4"><formula1>${escapeXmlText(formula)}</formula1></dataValidation></dataValidations></worksheet>`)
 const input=(await assemblePackage(base,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const result=applySheetEdits(input,{renames:[],additions:[],removals:['Source'],order:['Other']})
 if(referenced)await expect(result).rejects.toThrow('已拒绝删除')
 else{
  const changed=await result,after=await createBufferEntrySource(changed)
  expect((await readWorkbook(changed)).sheets.map(sheet=>sheet.name)).toEqual(['Other'])
  expect(await after.readText(path)).toBe(xml)
 }
})
