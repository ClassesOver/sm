import {expect,it} from 'vitest'
import {applyDefinedNames,applySheetEdits,createBlankWorkbook,readWorkbook} from '../src'
import {createBufferEntrySource} from '../src/zip'

it.each([
 ['Source!$A$1',undefined,true],
 ["'source'!$a$1",'Other',true],
 ['Source!$A$1','Source',false],
 ['Other!$A$1',undefined,false],
 ['"Source!A1"',undefined,false],
 ['[book.xlsx]Source!A1',undefined,false],
 ["'[book.xlsx]Source'!A1",'Other',false],
])('retains source defined-name deletion scope contract for %s / %s',async(refersTo,scopeSheetName,referenced)=>{
 const base=await applySheetEdits(await createBlankWorkbook(),{renames:[{sheetName:'Sheet1',newName:'Source'}],additions:[{name:'Other'}],removals:[],order:['Source','Other']})
 const input=await applyDefinedNames(base,{sets:[{name:'DeleteDependency',refersTo,...(scopeSheetName?{scopeSheetName}: {})}]})
 const result=applySheetEdits(input,{renames:[],additions:[],removals:['Source'],order:['Other']})
 if(referenced)await expect(result).rejects.toThrow('仍有定义名称引用')
 else{
  const changed=await result,model=await readWorkbook(changed),before=await createBufferEntrySource(input),after=await createBufferEntrySource(changed)
  expect(model.sheets.map(sheet=>sheet.name)).toEqual(['Other'])
  expect(model.definedNames??[]).toEqual(scopeSheetName==='Source'?[]:[{name:'DeleteDependency',refersTo,...(scopeSheetName?{scopeSheetName}: {})}])
  for(const path of ['xl/worksheets/sheet2.xml','xl/styles.xml'])expect(await after.readText(path)).toBe(await before.readText(path))
 }
})
