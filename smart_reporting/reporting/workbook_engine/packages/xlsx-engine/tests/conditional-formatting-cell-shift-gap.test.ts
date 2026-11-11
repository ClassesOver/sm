/** Cell-shift CF contracts captured as real package RED before integration. */
import {expect,it} from 'vitest'
import {applyCellShift,createBlankWorkbook,readWorkbook} from '../src'
import {applyWorkbookOperations} from '../../../bridge/operations'
import {planConditionalFormattingStructure} from '../src/conditional-formatting-structure'
const green={type:'highlightCell',subType:'formula',value:'TRUE',style:{bg:{rgb:'#00FF00'}}}
async function fixture(sheetName:string,value:string,ranges=[{startRow:0,endRow:3,startColumn:1,endColumn:1}]){
 return applyWorkbookOperations(await createBlankWorkbook(),[
  {kind:'applySheetEdits',plan:{renames:[{sheetName:'Sheet1',newName:'Source'}],additions:[{name:'Other'}],removals:[],order:['Source','Other']}},
  {kind:'replaceSheetConditionalFormats',sheetName,rules:[{ranges,stopIfTrue:false,rule:{...green,value}}]},
 ])
}
it('moves intersecting base CF on inserted cells down without painting the inserted gap',async()=>{
 const bytes=await fixture('Source','TRUE')
 const output=await applyCellShift(bytes,'Source',{range:'B2',shift:'down'})
 const rules=(await readWorkbook(output)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!.rules
 expect(rules).toEqual([{ranges:[{startRow:0,endRow:0,startColumn:1,endColumn:1},{startRow:2,endRow:4,startColumn:1,endColumn:1}],stopIfTrue:false,rule:green}])
})
it('moves intersecting base CF on inserted cells right without painting the inserted gap',async()=>{
 const bytes=await fixture('Source','TRUE',[{startRow:1,endRow:1,startColumn:0,endColumn:3}])
 const output=await applyCellShift(bytes,'Source',{range:'B2',shift:'right'})
 const rules=(await readWorkbook(output)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!.rules
 expect(rules).toEqual([{ranges:[{startRow:1,endRow:1,startColumn:0,endColumn:0},{startRow:1,endRow:1,startColumn:2,endColumn:4}],stopIfTrue:false,rule:green}])
})
it('updates cross-sheet relative CF dependencies on banded insertion even when no host CF scope intersects',async()=>{
 const bytes=await fixture('Other','Source!A1>0')
 const output=await applyCellShift(bytes,'Source',{range:'A2',shift:'down'})
 const model=(await readWorkbook(output)).sheets.find(sheet=>sheet.name==='Other')!.conditionalFormatting!
 expect(model.issues).toEqual([])
 expect(model.rules).toEqual([
  {ranges:[{startRow:0,endRow:0,startColumn:1,endColumn:1}],stopIfTrue:false,rule:{...green,value:'Source!A1>0'}},
  {ranges:[{startRow:1,endRow:3,startColumn:1,endColumn:1}],stopIfTrue:false,rule:{...green,value:'Source!A3>0'}},
 ])
})
it('turns deleted cross-sheet CF dependency cells into REF partitions while retaining the host cells',async()=>{
 const output=await applyCellShift(await fixture('Other','Source!A1>0'),'Source',{range:'A2',shift:'up'})
 const rules=(await readWorkbook(output)).sheets.find(sheet=>sheet.name==='Other')!.conditionalFormatting!.rules
 expect(rules.map(rule=>rule.rule.value)).toEqual(['Source!A1>0','Source!#REF!>0','Source!A2>0'])
 expect(rules.map(rule=>rule.ranges)).toEqual([[{startRow:0,endRow:0,startColumn:1,endColumn:1}],[{startRow:1,endRow:1,startColumn:1,endColumn:1}],[{startRow:2,endRow:3,startColumn:1,endColumn:1}]])
})
it('does not conflate whole-row CF expansion with official insert-cells coverage movement',()=>{
 const input={ranges:[{startRow:0,endRow:3,startColumn:1,endColumn:1}],stopIfTrue:false,rule:green}
 const groups=planConditionalFormattingStructure([input],'Source','Source',{axis:'row',start:1,delta:1,band:{start:1,end:1}},{geometry:'cells'})[0]!.groups
 expect(groups).toEqual([{...input,ranges:[{startRow:0,endRow:0,startColumn:1,endColumn:1},{startRow:2,endRow:4,startColumn:1,endColumn:1}]}])
})
it('deletes intersecting base CF cells up and shifts surviving coverage without losing its priority',async()=>{
 const output=await applyCellShift(await fixture('Source','TRUE'),'Source',{range:'B2',shift:'up'})
 const model=(await readWorkbook(output)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!
 expect(model.issues).toEqual([])
 expect(model.rules).toEqual([{ranges:[{startRow:0,endRow:2,startColumn:1,endColumn:1}],stopIfTrue:false,rule:green}])
})
it('deletes intersecting base CF cells left and preserves out-of-band rows',async()=>{
 const input=await fixture('Source','TRUE',[{startRow:0,endRow:1,startColumn:0,endColumn:3}])
 const output=await applyCellShift(input,'Source',{range:'B2',shift:'left'})
 const model=(await readWorkbook(output)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!
 expect(model.issues).toEqual([])
 const ranges=model.rules.flatMap(rule=>rule.ranges)
 expect(ranges).toEqual([{startRow:0,endRow:0,startColumn:0,endColumn:3},{startRow:1,endRow:1,startColumn:0,endColumn:2}])
 expect(model.rules.every(rule=>rule.rule.value==='TRUE')).toBe(true)
})
it('drops an entirely deleted own CF while retaining the other sheet CF bytes',async()=>{
 const {createBufferEntrySource}=await import('../src/zip')
 const input=await fixture('Source','TRUE',[{startRow:1,endRow:1,startColumn:1,endColumn:1}]),before=await createBufferEntrySource(input)
 const output=await applyCellShift(input,'Source',{range:'B2',shift:'up'})
 const actual=await readWorkbook(output),source=actual.sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!
 expect(source.issues).toEqual([]);expect(source.rules).toEqual([])
 expect(await(await createBufferEntrySource(output)).readText('xl/worksheets/sheet2.xml')).toBe(await before.readText('xl/worksheets/sheet2.xml'))
})
it('keeps unchanged adjacent columns while shifting only the intersecting CF band',async()=>{
 const input=await fixture('Source','TRUE',[{startRow:0,endRow:3,startColumn:1,endColumn:2}])
 const output=await applyCellShift(input,'Source',{range:'B2',shift:'down'})
 const model=(await readWorkbook(output)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!
 expect(model.issues).toEqual([])
 const cells=model.rules.flatMap(rule=>rule.ranges.flatMap(range=>Array.from({length:range.endRow-range.startRow+1},(_,row)=>Array.from({length:range.endColumn-range.startColumn+1},(_,column)=>`${range.startRow+row}:${range.startColumn+column}`)).flat())).sort()
 expect(cells).toEqual(['0:1','0:2','1:2','2:1','2:2','3:1','3:2','4:1'])
 expect(model.rules).toHaveLength(1);expect(model.rules[0]!.rule).toEqual(green)
})
it('keeps whole-column inserted-cell coverage bounded with an explicit unpainted top gap',async()=>{
 const input=await fixture('Source','TRUE',[{startRow:0,endRow:1048575,startColumn:1,endColumn:1}])
 const output=await applyCellShift(input,'Source',{range:'B1',shift:'down'})
 const model=(await readWorkbook(output)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!
 expect(model.issues).toEqual([])
 expect(model.rules).toEqual([{ranges:[{startRow:1,endRow:1048575,startColumn:1,endColumn:1}],stopIfTrue:false,rule:green}])
})
it('keeps whole-row inserted-cell coverage bounded with an explicit unpainted left gap',async()=>{
 const input=await fixture('Source','TRUE',[{startRow:1,endRow:1,startColumn:0,endColumn:16383}])
 const output=await applyCellShift(input,'Source',{range:'A2',shift:'right'})
 const model=(await readWorkbook(output)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!
 expect(model.issues).toEqual([])
 expect(model.rules).toEqual([{ranges:[{startRow:1,endRow:1,startColumn:1,endColumn:16383}],stopIfTrue:false,rule:green}])
})
it('moves linked cell-shift scopes together and preserves source-only extension visuals',async()=>{
 const {assemblePackage,createBufferEntrySource}=await import('../src/zip')
 const bytes=await fixture('Other','TRUE'),source=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml'
 const id='{20000000-0000-0000-0000-000000000001}',ns='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
 const base='<conditionalFormatting sqref="B1:B4"><cfRule type="dataBar" priority="1"><dataBar><cfvo type="min"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar><extLst><ext uri="{B025F937-C7B1-47D3-B67F-A62EFF666E3E}" xmlns:x14="'+ns+'"><x14:id>'+id+'</x14:id></ext></extLst></cfRule></conditionalFormatting>'
 const ext='<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}" xmlns:x14="'+ns+'"><x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"><x14:cfRule type="dataBar" priority="1" id="'+id+'"><x14:dataBar gradient="0"><x14:cfvo type="autoMin"/><x14:cfvo type="autoMax"/><x14:negativeFillColor rgb="FF112233"/></x14:dataBar></x14:cfRule><xm:sqref>B1:B4</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext><ext uri="unrelated"><raw keep="B1:B4"/></ext></extLst>'
 const xml=(await source.readText(path)).replace('</worksheet>',base+ext+'</worksheet>')
 const input=(await assemblePackage(bytes,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const moved=await applyCellShift(input,'Source',{range:'B2',shift:'down'}),model=(await readWorkbook(moved)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!
 expect(model.issues).toEqual([]);expect(model.linkedRuleIds).toEqual([id]);expect(model.rules[0]!.ranges).toEqual([{startRow:0,endRow:0,startColumn:1,endColumn:1},{startRow:2,endRow:4,startColumn:1,endColumn:1}])
 expect(model.rules[0]!.rule.config).toMatchObject({nativeColor:'#112233',isGradient:false})
 const output=await(await createBufferEntrySource(moved)).readText(path)
 expect(output).toContain('<xm:sqref>B1:B1 B3:B5</xm:sqref>');expect(output).toContain('<ext uri="unrelated"><raw keep="B1:B4"/></ext>')
 expect(await(await createBufferEntrySource(moved)).readText('xl/worksheets/sheet2.xml')).toBe(await source.readText('xl/worksheets/sheet2.xml'))
 const removed=await applyCellShift(input,'Source',{range:'B1:B4',shift:'up'}),cleared=await(await createBufferEntrySource(removed)).readText(path)
 expect(cleared).not.toContain(id);expect(cleared).not.toContain('<x14:conditionalFormatting');expect(cleared).toContain('<ext uri="unrelated"><raw keep="B1:B4"/></ext>')
})
it('retains validation and unknown CF source boundaries while admitting only verified CF',async()=>{
 const {assemblePackage,createBufferEntrySource}=await import('../src/zip')
 const input=await fixture('Source','TRUE'),source=await createBufferEntrySource(input),path='xl/worksheets/sheet1.xml',xml=await source.readText(path)
 const change=async(value:string)=>(await assemblePackage(input,{replaced:new Map([[path,value]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const validated=await change(xml.replace('</worksheet>','<dataValidations count="1"><dataValidation type="whole" sqref="B2"><formula1>1</formula1></dataValidation></dataValidations></worksheet>'))
 await expect(applyCellShift(validated,'Source',{range:'B2',shift:'down'})).rejects.toThrow(/数据验证/)
 const extended=await change(xml.replace('</worksheet>','<extLst><ext uri="{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}"><x14:dataValidations xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main" xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main" count="1"><x14:dataValidation type="list"><x14:formula1><xm:f>Other!$A$1</xm:f></x14:formula1><xm:sqref>B2</xm:sqref></x14:dataValidation></x14:dataValidations></ext></extLst></worksheet>'))
 await expect(applyCellShift(extended,'Source',{range:'B2',shift:'down'})).rejects.toThrow(/数据验证/)

 const unknown=await change(xml.replace('type="expression"','type="future"'))
 await expect(applyCellShift(unknown,'Source',{range:'B2',shift:'down'})).rejects.toThrow(/条件格式无法完整迁移/)
 const foreign=await change(xml.replace('priority="1"','priority="1" future="1"'))
 await expect(applyCellShift(foreign,'Source',{range:'B2',shift:'down'})).rejects.toThrow(/条件格式无法完整迁移/)
 expect(await source.readText(path)).toBe(xml)
})
it('roundtrips mixed-axis formula CF through banded insert and delete without changing styles or stop',async()=>{
 const ranges=[{startRow:0,endRow:3,startColumn:1,endColumn:2}],input=await fixture('Source','AND($A1>0,B$1>0,"B2"="B2")',ranges)
 const before=(await readWorkbook(input)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!.rules
 const inserted=await applyCellShift(input,'Source',{range:'B2',shift:'down'})
 const model=(await readWorkbook(inserted)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!
 expect(model.issues).toEqual([])
 expect(model.rules.every(rule=>String(rule.rule.value).includes('"B2"="B2"')&&JSON.stringify(rule.rule.style)===JSON.stringify(green.style))).toBe(true)
 const removed=await applyCellShift(inserted,'Source',{range:'B2',shift:'up'})
 const after=(await readWorkbook(removed)).sheets.find(sheet=>sheet.name==='Source')!.conditionalFormatting!
 expect(after.issues).toEqual([])
 const {offsetFormulaRefs}=await import('../src/conditional-formatting-offset-source')
 const actual:Record<string,string>={}
 for(const rule of after.rules){const anchor=[...rule.ranges].sort((a,b)=>a.startRow-b.startRow||a.startColumn-b.startColumn)[0]!
  for(const range of rule.ranges)for(let row=range.startRow;row<=range.endRow;row++)for(let col=range.startColumn;col<=range.endColumn;col++){
   const key=`${row}:${col}`;expect(actual[key]).toBeUndefined();actual[key]=offsetFormulaRefs(String(rule.rule.value),row-anchor.startRow,col-anchor.startColumn)
  }
 }
 expect(actual).toEqual(Object.fromEntries(Array.from({length:4},(_,row)=>[1,2].map(col=>[`${row}:${col}`,`AND($A${row+1}>0,${col===1?'B':'C'}$1>0,"B2"="B2")`])).flat()))
 expect(after.rules.every(rule=>rule.stopIfTrue===before[0]!.stopIfTrue)).toBe(true)
})
