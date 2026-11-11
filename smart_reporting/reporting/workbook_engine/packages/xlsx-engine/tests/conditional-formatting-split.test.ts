import {expect,it} from 'vitest'
import {columnLabel} from '../src/cell-address'
import {applyRowColumnOps,createBlankWorkbook,readWorkbook} from '../src'
import {applyWorkbookOperations} from '../../../bridge/operations'
it('partitions cross-sheet relative CF dependencies without moving host coverage or overtaking stopIfTrue',async()=>{
 const areas=[{startRow:0,endRow:3,startColumn:1,endColumn:1}]
 const first={ranges:areas,stopIfTrue:true,rule:{type:'highlightCell',subType:'formula',value:'TRUE',style:{bg:{rgb:'#FF0000'}}}}
 const dependent={ranges:areas,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'Source!A1>0',style:{bg:{rgb:'#00FF00'}}}}
 const bytes=await applyWorkbookOperations(await createBlankWorkbook(),[
  {kind:'applySheetEdits',plan:{renames:[{sheetName:'Sheet1',newName:'Source'}],additions:[{name:'Other'}],removals:[],order:['Source','Other']}},
  {kind:'replaceSheetConditionalFormats',sheetName:'Other',rules:[first,dependent]},
 ])
 const changed=await applyRowColumnOps(bytes,'Source',[{kind:'insert-rows',index:1,count:1}])
 const actual=(await readWorkbook(changed)).sheets.find(sheet=>sheet.name==='Other')!.conditionalFormatting!
 expect(actual.issues).toEqual([])
 expect(actual.rules).toEqual([first,
  {...dependent,ranges:[{startRow:0,endRow:0,startColumn:1,endColumn:1}]},
  {...dependent,ranges:[{startRow:1,endRow:3,startColumn:1,endColumn:1}],rule:{...dependent.rule,value:'Source!A3>0'}},
 ])
})
it('plans the crosssheet split in the original parent priority slot',async()=>{
 const {planConditionalFormattingStructure}=await import('../src/conditional-formatting-structure')
 const area=[{startRow:0,endRow:3,startColumn:1,endColumn:1}]
 const rules=[{ranges:area,stopIfTrue:true,rule:{type:'highlightCell',subType:'formula',value:'TRUE',style:{}}},{ranges:area,stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'Source!A1>0',style:{}}}]
 const plan=planConditionalFormattingStructure(rules,'Other','Source',{axis:'row',start:1,delta:1})
 expect(plan.map(item=>item.sourceRuleIndex)).toEqual([0,1]);expect(plan[0]!.groups).toEqual([rules[0]])
 expect(plan[1]!.groups).toEqual([{...rules[1],ranges:[{startRow:0,endRow:0,startColumn:1,endColumn:1}]},{...rules[1],ranges:[{startRow:1,endRow:3,startColumn:1,endColumn:1}],rule:{...rules[1]!.rule,value:'Source!A3>0'}}])
})
it('cuts a whole-column crosssheet dependency by interval boundaries and respects mixed absolute axes',async()=>{
 const {planConditionalFormattingStructure}=await import('../src/conditional-formatting-structure')
 const rule=(value:string)=>({ranges:[{startRow:0,endRow:1048575,startColumn:1,endColumn:1}],stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value,style:{}}})
 const relative=planConditionalFormattingStructure([rule('Source!$A1>0')],'Other','Source',{axis:'row',start:1,delta:1})[0]!.groups
 expect(relative).toHaveLength(2);expect(relative[0]!.ranges).toEqual([{startRow:0,endRow:0,startColumn:1,endColumn:1}]);expect(relative[1]!.ranges[0]).toMatchObject({startRow:1,endRow:1048575});expect(relative[1]!.rule.value).toBe('Source!$A3>0')
 const absolute=planConditionalFormattingStructure([rule('Source!A$2>0')],'Other','Source',{axis:'row',start:1,delta:1})[0]!.groups
 expect(absolute).toHaveLength(1);expect(absolute[0]!.rule.value).toBe('Source!A$3>0')
})
it('partitions deleted dependency cells to REF without dropping host coverage',async()=>{
 const {planConditionalFormattingStructure}=await import('../src/conditional-formatting-structure')
 const input={ranges:[{startRow:0,endRow:3,startColumn:1,endColumn:1}],stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'Source!A1>0',style:{}}}
 const groups=planConditionalFormattingStructure([input],'Other','Source',{axis:'row',start:1,delta:-1})[0]!.groups
 expect(groups.map(rule=>rule.rule.value)).toEqual(['Source!A1>0','Source!#REF!>0','Source!A2>0'])
 expect(groups.map(rule=>rule.ranges)).toEqual([[{startRow:0,endRow:0,startColumn:1,endColumn:1}],[{startRow:1,endRow:1,startColumn:1,endColumn:1}],[{startRow:2,endRow:3,startColumn:1,endColumn:1}]])
})
it('rebases every formula threshold and sorted disjoint anchor without changing styles',async()=>{
 const {planConditionalFormattingStructure}=await import('../src/conditional-formatting-structure')
 const input={ranges:[{startRow:10,endRow:11,startColumn:1,endColumn:1},{startRow:0,endRow:3,startColumn:1,endColumn:1}],stopIfTrue:false,rule:{type:'dataBar',isShowValue:true,config:{min:{type:'formula',value:'Source!A1'},max:{type:'formula',value:'Source!$A$5'},positiveColor:'#112233',nativeColor:'#445566',isGradient:false}}}
 const groups=planConditionalFormattingStructure([input],'Other','Source',{axis:'row',start:1,delta:1})[0]!.groups
 expect(groups).toHaveLength(2);expect(groups[0]!.ranges).toEqual([{startRow:0,endRow:0,startColumn:1,endColumn:1}]);expect(groups[1]!.ranges).toEqual([{startRow:1,endRow:3,startColumn:1,endColumn:1},{startRow:10,endRow:11,startColumn:1,endColumn:1}])
 expect(groups[1]!.rule.config).toMatchObject({min:{value:'Source!A3'},max:{value:'Source!$A$6'},positiveColor:'#112233',nativeColor:'#445566',isGradient:false})
})
it('derives linked base/twin splits from the original ZIP with matching priorities and preserved extension visuals',async()=>{
 const {assemblePackage,createBufferEntrySource}=await import('../src/zip')
 const bytes=await applyWorkbookOperations(await createBlankWorkbook(),[{kind:'applySheetEdits',plan:{renames:[{sheetName:'Sheet1',newName:'Source'}],additions:[{name:'Other'}],removals:[],order:['Source','Other']}}])
 const src=await createBufferEntrySource(bytes),model=await readWorkbook(bytes),other=model.sheets.find(sheet=>sheet.name==='Other')!,path='xl/worksheets/sheet2.xml'
 const id='{10000000-0000-0000-0000-000000000001}',ns='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
 const base='<conditionalFormatting sqref="B1:B4"><cfRule type="dataBar" priority="1"><dataBar><cfvo type="formula" val="Source!A1"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar><extLst><ext uri="{B025F937-C7B1-47D3-B67F-A62EFF666E3E}" xmlns:x14="'+ns+'"><x14:id>'+id+'</x14:id></ext></extLst></cfRule></conditionalFormatting>'
 const ext='<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}" xmlns:x14="'+ns+'"><x14:conditionalFormattings><x14:conditionalFormatting xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main"><x14:cfRule type="dataBar" priority="1" id="'+id+'"><x14:dataBar gradient="0"><x14:cfvo type="formula"><xm:f>Source!A1</xm:f></x14:cfvo><x14:cfvo type="autoMax"/><x14:negativeFillColor rgb="FF112233"/></x14:dataBar></x14:cfRule><xm:sqref>B1:B4</xm:sqref></x14:conditionalFormatting></x14:conditionalFormattings></ext><ext uri="unrelated"><raw keep="Source!A1"/></ext></extLst>'
 const xml=(await src.readText(path)).replace('</worksheet>',base+ext+'</worksheet>')
 const input=(await assemblePackage(bytes,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 expect((await readWorkbook(input)).sheets.find(sheet=>sheet.name===other.name)!.conditionalFormatting!.issues).toEqual([])
 const shifted=await applyRowColumnOps(input,'Source',[{kind:'insert-rows',index:1,count:1}]),read=(await readWorkbook(shifted)).sheets.find(sheet=>sheet.name==='Other')!.conditionalFormatting!
 expect(read.issues).toEqual([]);expect(read.rules).toHaveLength(2);expect(new Set(read.linkedRuleIds).size).toBe(2)
 const output=await(await createBufferEntrySource(shifted)).readText(path)
 expect(output).toContain('<xm:sqref>B1:B1</xm:sqref>');expect(output).toContain('<xm:sqref>B2:B4</xm:sqref>');expect(output).toContain('<xm:f>Source!A3</xm:f>')
 expect(output.match(/<x14:negativeFillColor rgb="FF112233"\/>/g)).toHaveLength(2);expect(output).toContain('<ext uri="unrelated"><raw keep="Source!A1"/></ext>')
 expect(read.rules.every(rule=>(rule.rule.config as any).nativeColor==='#112233'&&(rule.rule.config as any).isGradient===false)).toBe(true)
})
it('keeps quoted literals and quoted sheet names while partitioning mixed row/column bands',async()=>{
 const {planConditionalFormattingStructure}=await import('../src/conditional-formatting-structure')
 const rule={ranges:[{startRow:0,endRow:3,startColumn:1,endColumn:2}],stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'AND(\'Source Data\'!A1>0,"Source Data!A1"="Source Data!A1")',style:{}}}
 const groups=planConditionalFormattingStructure([rule],'Other','Source Data',{axis:'row',start:1,delta:1,band:{start:0,end:0}})[0]!.groups
 expect(groups).toHaveLength(2)
 expect(groups.every(group=>(group.rule.value as string).includes('"Source Data!A1"="Source Data!A1"'))).toBe(true)
 expect(groups.map(group=>group.ranges).flat().reduce((count,range)=>count+(range.endRow-range.startRow+1)*(range.endColumn-range.startColumn+1),0)).toBe(8)
 const same=planConditionalFormattingStructure([rule],'Other','Other',{axis:'row',start:1,delta:1,band:{start:1,end:1}})[0]!.groups
 expect(same.map(group=>group.ranges).flat().some(range=>range.startColumn===2&&range.startRow===0&&range.endRow===3)).toBe(true)
})
it('bounds partition multiplication before traversing a many-reference whole-grid rule',async()=>{
 const {planConditionalFormattingStructure}=await import('../src/conditional-formatting-structure')
 const formula=Array.from({length:101},(_,index)=>`Source!${columnLabel(index)}${index+1}`).join('+')
 const rule={ranges:[{startRow:0,endRow:1048575,startColumn:0,endColumn:16383}],stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:formula,style:{}}}
 expect(()=>planConditionalFormattingStructure([rule],'Other','Source',{axis:'row',start:500,delta:1})).toThrow(/budget/)
})
it('keeps semantic planner and raw XML identical for same-sheet relative conditions and bounded band materialization',async()=>{
 const {shiftConditionalFormattingXml}=await import('../src/conditional-formatting-structure-xml')
 const {readConditionalFormattingSnapshot}=await import('../src/conditional-formatting-read')
 const xml='<worksheet><sheetData/><conditionalFormatting sqref="B1:C4"><cfRule type="expression" priority="1"><formula>A2&gt;0</formula></cfRule></conditionalFormatting></worksheet>'
 const shifted=shiftConditionalFormattingXml(xml,'<styleSheet/>',undefined,'Host','Host',{axis:'row',start:1,delta:1,band:{start:1,end:1}})
 const model=readConditionalFormattingSnapshot(shifted,'<styleSheet/>')
 expect(model.issues).toEqual([])
 expect(model.rules.flatMap(rule=>rule.ranges).filter(range=>range.startColumn===2).reduce((count,range)=>count+range.endRow-range.startRow+1,0)).toBe(4)
 expect(model.rules.flatMap(rule=>rule.ranges).filter(range=>range.startColumn===1).reduce((count,range)=>count+range.endRow-range.startRow+1,0)).toBe(5)
})
it.each([0,500])('keeps an own-sheet whole-column CF inside grid bounds on insertion at %s',async(index)=>{
 const {planConditionalFormattingStructure}=await import('../src/conditional-formatting-structure')
 const rule={ranges:[{startRow:0,endRow:1048575,startColumn:0,endColumn:0}],stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'TRUE',style:{}}}
 const groups=planConditionalFormattingStructure([rule],'Host','Host',{axis:'row',start:index,delta:1})[0]!.groups
 expect(groups).toEqual([rule])
})
it('partitions lowercase references consistently with fixed-source offset and structural shift',async()=>{
 const {planConditionalFormattingStructure}=await import('../src/conditional-formatting-structure')
 const input={ranges:[{startRow:0,endRow:3,startColumn:1,endColumn:1}],stopIfTrue:false,rule:{type:'highlightCell',subType:'formula',value:'Source!a1>0',style:{}}}
 const groups=planConditionalFormattingStructure([input],'Other','Source',{axis:'row',start:1,delta:1})[0]!.groups
 expect(groups).toHaveLength(2);expect(groups[0]!.ranges).toEqual([{startRow:0,endRow:0,startColumn:1,endColumn:1}]);expect(groups[1]!.rule.value).toBe('Source!A3>0')
})
