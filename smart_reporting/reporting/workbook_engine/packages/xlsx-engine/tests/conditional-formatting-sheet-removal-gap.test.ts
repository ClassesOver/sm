/** Fixed-source referenced-removal refusal, including formula threshold nodes. */
import {expect,it} from 'vitest'
import {applySheetEdits,createBlankWorkbook,readWorkbook} from '../src'
import {applyWorkbookOperations} from '../../../bridge/operations'
import {assemblePackage,createBufferEntrySource} from '../src/zip'
const area=[{startRow:0,endRow:3,startColumn:1,endColumn:1}]
const stop={ranges:area,stopIfTrue:true,rule:{type:'highlightCell',subType:'formula',value:'TRUE',style:{bg:{rgb:'#FF0000'}}}}
const removal={renames:[],additions:[],removals:['Source'],order:['Other']}
async function fixture(rule:Record<string,unknown>){
 return applyWorkbookOperations(await createBlankWorkbook(),[
  {kind:'applySheetEdits',plan:{renames:[{sheetName:'Sheet1',newName:'Source'}],additions:[{name:'Other'}],removals:[],order:['Source','Other']}},
  {kind:'replaceSheetConditionalFormats',sheetName:'Other',rules:[stop,{ranges:area,stopIfTrue:false,rule}]},
 ])
}
it.each(['Source!A1>0','source!a1>0',"'Source'!$A$1>0"])('preserves the source refusal contract for ordinary expression %s',async formula=>{
 const bytes=await fixture({type:'highlightCell',subType:'formula',value:formula,style:{bg:{rgb:'#00FF00'}}})
 await expect(applySheetEdits(bytes,removal)).rejects.toThrow('已拒绝删除')
})
it.each(['dataBar','colorScale','iconSet'])('refuses referenced sheet removal through %s formula cfvo',async type=>{
 const value={type:'formula',value:'Source!A1'},rule=type==='dataBar'?{type,config:{min:value,max:{type:'max'},positiveColor:'#638EC6'}}:type==='colorScale'?{type,config:[{index:0,value,color:'#FF0000'},{index:1,value:{type:'max'},color:'#00FF00'}]}:{type,config:[{iconType:'3TrafficLights1',iconId:'2',operator:'greaterThanOrEqual',value:{type:'num',value:2}},{iconType:'3TrafficLights1',iconId:'1',operator:'greaterThanOrEqual',value},{iconType:'3TrafficLights1',iconId:'0',operator:'greaterThanOrEqual',value:{type:'min'}}]}
 const bytes=await fixture(rule)
 await expect(applySheetEdits(bytes,removal)).rejects.toThrow('已拒绝删除')
})
it('refuses a source-verified linked threshold reference through xm:f',async()=>{
 const bytes=await fixture({type:'dataBar',config:{min:{type:'formula',value:'Source!A1'},max:{type:'max'},positiveColor:'#638EC6'}}),source=await createBufferEntrySource(bytes),path='xl/worksheets/sheet2.xml',id='{50000000-0000-0000-0000-000000000001}'
 let xml=await source.readText(path)
 xml=xml.replace(/(<cfRule type="dataBar"[\s\S]*?)(<\/cfRule>)/,`$1<extLst><ext><x14:id>${id}</x14:id></ext></extLst>$2`).replace('<worksheet ','<worksheet xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main" xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main" ')
 xml=xml.replace('</worksheet>',`<extLst><ext><x14:conditionalFormattings><x14:conditionalFormatting><x14:cfRule type="dataBar" priority="2" id="${id}"><x14:dataBar gradient="0"><x14:cfvo type="formula"><xm:f>Source!A1</xm:f></x14:cfvo><x14:cfvo type="autoMax"/><x14:negativeFillColor rgb="FF112233"/></x14:dataBar></x14:cfRule><xm:sqref>B1:B4</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext></extLst></worksheet>`)
 const input=(await assemblePackage(bytes,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 expect((await readWorkbook(input)).sheets[1]!.conditionalFormatting!.issues).toEqual([])
 await expect(applySheetEdits(input,removal)).rejects.toThrow('已拒绝删除')
})
it.each(['TRUE','"Source!A1"="Source!A1"','[book.xlsx]Source!A1>0',"'[book.xlsx]Source'!A1>0"])('allows removal when only unrelated or literal/external references remain: %s',async formula=>{
 const bytes=await fixture({type:'highlightCell',subType:'formula',value:formula,style:{bg:{rgb:'#00FF00'}}}),before=await createBufferEntrySource(bytes)
 const changed=await applySheetEdits(bytes,removal),after=await createBufferEntrySource(changed)
 expect((await readWorkbook(changed)).sheets.map(sheet=>sheet.name)).toEqual(['Other'])
 for(const path of ['xl/worksheets/sheet2.xml','xl/styles.xml'])expect(await after.readText(path)).toBe(await before.readText(path))
})
it.each(['source!a1',"'SOURCE'!$a$1"])('refuses equivalent lowercase or quoted formula thresholds: %s',async formula=>{
 const bytes=await fixture({type:'dataBar',config:{min:{type:'formula',value:formula},max:{type:'max'},positiveColor:'#638EC6'}})
 await expect(applySheetEdits(bytes,removal)).rejects.toThrow('已拒绝删除')
})
it.each(['Other!A1','IF("Source!A1"="Source!A1",0,1)','[book.xlsx]Source!A1',"'[book.xlsx]Source'!A1"])('allows unrelated, XML-escaped literal and external formula thresholds: %s',async formula=>{
 const bytes=await fixture({type:'dataBar',config:{min:{type:'formula',value:formula},max:{type:'max'},positiveColor:'#638EC6'}}),before=await createBufferEntrySource(bytes)
 const changed=await applySheetEdits(bytes,removal),after=await createBufferEntrySource(changed),model=await readWorkbook(changed)
 expect(model.sheets.map(sheet=>sheet.name)).toEqual(['Other']);expect(model.sheets[0]!.conditionalFormatting!.issues).toEqual([])
 for(const path of ['xl/worksheets/sheet2.xml','xl/styles.xml'])expect(await after.readText(path)).toBe(await before.readText(path))
})
