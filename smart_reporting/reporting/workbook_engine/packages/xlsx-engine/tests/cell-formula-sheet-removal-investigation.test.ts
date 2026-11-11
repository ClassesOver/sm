import {expect,it} from 'vitest'
import {applySheetEdits,createBlankWorkbook,readWorkbook} from '../src'
import {assemblePackage,createBufferEntrySource} from '../src/zip'
import {escapeXmlText} from '../src/xml'

it.each([
 ['Source!A1',true],
 ['source!a1',true],
 ["'SOURCE'!$a$1",true],
 ['IF("Source!A1"="Source!A1",0,1)',false],
 ['[book.xlsx]Source!A1',false],
 ["'[book.xlsx]SOURCE'!a1",false],
])('retains fixed-source ordinary formula removal refusal for %s',async(formula,referenced)=>{
 const base=await applySheetEdits(await createBlankWorkbook(),{renames:[{sheetName:'Sheet1',newName:'Source'}],additions:[{name:'Other'}],removals:[],order:['Source','Other']})
 const before=await createBufferEntrySource(base),path='xl/worksheets/sheet2.xml',xml=(await before.readText(path)).replace('<sheetData/>',`<sheetData><row r="1"><c r="C1"><f>${escapeXmlText(formula)}</f><v>0</v></c></row></sheetData>`)
 const input=(await assemblePackage(base,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const result=applySheetEdits(input,{renames:[],additions:[],removals:['Source'],order:['Other']})
 if(referenced)await expect(result).rejects.toThrow('已拒绝删除')
 else{
  const changed=await result,after=await createBufferEntrySource(changed)
  expect((await readWorkbook(changed)).sheets.map(sheet=>sheet.name)).toEqual(['Other'])
  for(const part of [path,'xl/styles.xml'])expect(await after.readText(part)).toBe(await(await createBufferEntrySource(input)).readText(part))
 }
})
