/** Sheet rename/reorder CF investigation: controls and active next-stage REDs. */
import {expect,it} from 'vitest'
import {applySheetEdits,createBlankWorkbook,readWorkbook} from '../src'
import {applyWorkbookOperations} from '../../../bridge/operations'
import {assemblePackage,createBufferEntrySource} from '../src/zip'
import {renameSheetInFormula} from '../src/sheets-edit'
import {readConditionalFormattingSnapshot} from '../src/conditional-formatting-read'
const area=[{startRow:0,endRow:3,startColumn:1,endColumn:1}]
const stop={ranges:area,stopIfTrue:true,rule:{type:'highlightCell',subType:'formula',value:'TRUE',style:{bg:{rgb:'#FF0000'}}}}
async function fixture(name:string,formula:string){
 return applyWorkbookOperations(await createBlankWorkbook(),[
  {kind:'applySheetEdits',plan:{renames:[{sheetName:'Sheet1',newName:name}],additions:[{name:'Other'}],removals:[],order:[name,'Other']}},
  {kind:'replaceSheetConditionalFormats',sheetName:'Other',rules:[stop,{ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:formula,style:{bg:{rgb:'#00FF00'}}}}]},
 ])
}
const rename=(oldName:string,newName:string)=>({renames:[{sheetName:oldName,newName}],additions:[],removals:[],order:['Other',newName]})
it.each([
 ['Source','Source!A1>0','财务 O\'Brien',"'财务 O''Brien'!A1>0"],
 ["Bob's Data","'Bob''s Data'!A1>0",'财务',"'财务'!A1>0"],
 ['预算','预算!A1>0','预算修订',"'预算修订'!A1>0"],
])('renames and reorders ordinary exact-case CF from %s without changing priority or literals',async(oldName,formula,newName,expected)=>{
 const bytes=await fixture(oldName,`AND(${formula},"${oldName}!A1"="${oldName}!A1")`)
 const changed=await applySheetEdits(bytes,rename(oldName,newName)),model=await readWorkbook(changed),rules=model.sheets.find(sheet=>sheet.name==='Other')!.conditionalFormatting!
 const before=await createBufferEntrySource(bytes),after=await createBufferEntrySource(changed)
 for(const path of ['xl/worksheets/sheet1.xml','xl/styles.xml'])expect(await after.readText(path)).toBe(await before.readText(path))
 expect(model.sheets.map(sheet=>sheet.name)).toEqual(['Other',newName]);expect(rules.issues).toEqual([])
 expect(rules.rules[0]).toEqual(stop);expect(rules.rules[1]!.rule.value).toBe(`AND(${expected},"${oldName}!A1"="${oldName}!A1")`)
})
it.each(['source!A1>0','Source!a1>0'])('renames equivalent case-insensitive CF formula %s',async(formula)=>{
 const changed=await applySheetEdits(await fixture('Source',formula),rename('Source','Renamed'))
 const rules=(await readWorkbook(changed)).sheets.find(sheet=>sheet.name==='Other')!.conditionalFormatting!
 expect(rules.issues).toEqual([]);expect(rules.rules[0]).toEqual(stop);expect(String(rules.rules[1]!.rule.value).toUpperCase()).toBe('RENAMED!A1>0')
})
it('renames differential visual CF formula thresholds while retaining source priority',async()=>{
 let input=await fixture('Source','Source!A1>0')
 input=await applyWorkbookOperations(input,[{kind:'replaceSheetConditionalFormats',sheetName:'Other',rules:[stop,{ranges:area,stopIfTrue:false,rule:{type:'dataBar',isShowValue:true,config:{min:{type:'formula',value:'Source!A1'},max:{type:'max'},positiveColor:'#638EC6'}}}]}])
 const changed=await applySheetEdits(input,rename('Source','财务')),other=(await readWorkbook(changed)).sheets.find(sheet=>sheet.name==='Other')!.conditionalFormatting!
 expect(other.issues).toEqual([]);expect(other.rules[0]).toEqual(stop);expect(other.rules[1]!.rule.config).toMatchObject({min:{type:'formula',value:"'财务'!A1"}})
})
it('keeps linked base and x14 formula thresholds consistent across rename and tab reorder',async()=>{
 const bytes=await fixture('Source','Source!A1>0'),source=await createBufferEntrySource(bytes),path='xl/worksheets/sheet2.xml'
 const id='{30000000-0000-0000-0000-000000000001}',ns='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
 const base='<conditionalFormatting sqref="D1:D4"><cfRule type="dataBar" priority="3"><dataBar><cfvo type="formula" val="Source!A1"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar><extLst><ext uri="{B025F937-C7B1-47D3-B67F-A62EFF666E3E}" xmlns:x14="'+ns+'"><x14:id>'+id+'</x14:id></ext></extLst></cfRule></conditionalFormatting>'
 const ext='<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}" xmlns:x14="'+ns+'"><x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"><x14:cfRule type="dataBar" priority="3" id="'+id+'"><x14:dataBar gradient="0"><x14:cfvo type="formula"><xm:f>Source!A1</xm:f></x14:cfvo><x14:cfvo type="autoMax"/><x14:negativeFillColor rgb="FF112233"/></x14:dataBar></x14:cfRule><xm:sqref>D1:D4</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext></extLst>'
 const xml=(await source.readText(path)).replace('</worksheet>',base+ext+'</worksheet>')
 const input=(await assemblePackage(bytes,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const changed=await applySheetEdits(input,rename('Source',"财务 O'Brien")),next=await(await createBufferEntrySource(changed)).readText(path)
 const model=(await readWorkbook(changed)).sheets.find(sheet=>sheet.name==='Other')!.conditionalFormatting!
 expect(model.issues).toEqual([]);expect(model.linkedRuleIds).toEqual([id]);expect(model.rules[0]).toEqual(stop)
 expect(next).toContain('<xm:f>\'财务 O\'\'Brien\'!A1</xm:f>')
 expect(model.rules[2]!.rule.config).toMatchObject({min:{value:"'财务 O''Brien'!A1"},nativeColor:'#112233',isGradient:false})
})
it('preserves complete worksheet and style bytes on a tab-only move',async()=>{
 const input=await fixture('Source','Source!A1>0'),before=await createBufferEntrySource(input)
 const changed=await applySheetEdits(input,{renames:[],additions:[],removals:[],order:['Other','Source']}),after=await createBufferEntrySource(changed)
 for(const path of ['xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml','xl/styles.xml'])expect(await after.readText(path)).toBe(await before.readText(path))
})
it('renames local lowercase refs while preserving external workbooks and escaped string literals',()=>{
 const formula=`AND(source!a1>0,[book.xlsx]Source!A1>0,'[book.xlsx]Source'!A1>0,"Source!A1"="a""Source!A1",'SOURCE'!$a$2>0)`
 expect(renameSheetInFormula(formula,'Source',"财务 O'Brien")).toBe(`AND('财务 O''Brien'!a1>0,[book.xlsx]Source!A1>0,'[book.xlsx]Source'!A1>0,"Source!A1"="a""Source!A1",'财务 O''Brien'!$a$2>0)`)
})
function linkedThresholds(base:string,twin:string){
 const id='{40000000-0000-0000-0000-000000000001}'
 return `<worksheet xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main" xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"><conditionalFormatting sqref="A1:A4"><cfRule type="dataBar" priority="1"><dataBar>${base}<cfvo type="max"/><color rgb="FF638EC6"/></dataBar><extLst><ext><x14:id>${id}</x14:id></ext></extLst></cfRule></conditionalFormatting><extLst><ext><x14:conditionalFormattings><x14:conditionalFormatting><x14:cfRule type="dataBar" priority="1" id="${id}"><x14:dataBar>${twin}<x14:cfvo type="autoMax"/></x14:dataBar></x14:cfRule><xm:sqref>A1:A4</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext></extLst></worksheet>`
}
it.each([
 ['<cfvo type="formula" val="Source!A1"/>','<x14:cfvo type="formula"><xm:f>Renamed!A1</xm:f></x14:cfvo>'],
 ['<cfvo type="formula" val="Source!A1"/>','<x14:cfvo type="formula"/>'],
 ['<cfvo type="formula" val="Source!A1"/>','<x14:cfvo type="num"><xm:f>1</xm:f></x14:cfvo>'],
 ['<cfvo type="num" val="1"/>','<x14:cfvo type="num"><xm:f>2</xm:f></x14:cfvo>'],
 ['<cfvo type="formula" val="IF(Source!A1=1,&quot;yes&quot;,&quot;no&quot;)"/>','<x14:cfvo type="formula"><xm:f>IF(Source!A1=1,"YES","no")</xm:f></x14:cfvo>'],
])('reports a linked threshold semantic mismatch instead of complete projection %#', (base,twin)=>{
 const result=readConditionalFormattingSnapshot(linkedThresholds(base,twin),'<styleSheet/>')
 expect(result.issues).toContain('CF linked extension threshold differs from its base rule');expect(result.rules).toEqual([])
})
it('accepts equivalent linked formula case and quoting without normalizing string values',()=>{
 const result=readConditionalFormattingSnapshot(linkedThresholds('<cfvo type="formula" val="IF(Source!A1=1,&quot;yes&quot;,&quot;no&quot;)"/>',`<x14:cfvo type="formula"><xm:f>if('source'!a1=1,"yes","no")</xm:f></x14:cfvo>`),'<styleSheet/>')
 expect(result.issues).toEqual([]);expect(result.rules).toHaveLength(1)
})
