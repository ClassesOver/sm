import {expect,it} from 'vitest'
import {pivotSourceColumnValues,projectPivotSourceGrid} from '../src/pivot-source-format'
const values=[{field:'Amount',agg:'sum' as const}]
it('keeps distinct display identities for equal raw numbers with different formats',()=>{
 expect(pivotSourceColumnValues([1,1,null,true],['0000','0','0','0'],'Code',{values},false)).toEqual(['0001','1',null,true])
})
it('keeps measures numeric even when the same field is also a dimension',()=>{
 expect(pivotSourceColumnValues([2],['$0.00'],'Amount',{values},false)).toEqual([2])
})
it('preserves numeric inputs to grouping and calculated expressions',()=>{
 expect(pivotSourceColumnValues([45292],['yyyy-mm-dd'],'Code',{values,groupings:[{field:'Code',kind:'date',dateUnit:'year'}]},false)).toEqual([45292])
 expect(pivotSourceColumnValues([2],['0.00'],'Code',{values:[{field:'Calc',agg:'sum',formula:'Code*2'}]},false)).toEqual([2])
})
it('shifts 1904 calendar dates but keeps durations and time-only patterns unshifted',()=>{
 expect(pivotSourceColumnValues([0,.5,1.5],['yyyy-mm-dd','hh:mm','[h]:mm'],'Code',{values},true)).toEqual(['1904-01-01','12:00','36:00'])
})
it('preserves raw headers, default formats and source input arrays',()=>{
 const grid=[['Code','Amount'],[1,2]],patterns=[['0000','General'],['General','$0.00']]
 expect(projectPivotSourceGrid(grid,patterns,{values},false)).toEqual(grid)
 expect(grid).toEqual([['Code','Amount'],[1,2]])
})

it.each(['row','column'] as const)('projects an inherited %s number format',async kind=>{
 const {applyCellEdits,createBlankWorkbook,createBufferEntrySource}=await import('../src/index'),{assemblePackage}=await import('../src/zip'),{readPivotSourcePatterns}=await import('../src/pivot-source-format')
 const bytes=await applyCellEdits(await createBlankWorkbook(),[{sheetName:'Sheet1',row:1,column:0,writeValue:true,cell:{value:1},style:{numberFormat:'0000'}}])
 const source=await createBufferEntrySource(bytes),xml=await source.readText('xl/worksheets/sheet1.xml'),cell=xml.match(/<c\b[^>]*r="A2"[^>]*>/)![0],style=cell.match(/\bs="(\d+)"/)![1]
 let next=xml.replace(cell,cell.replace(/\s+s="\d+"/,''))
 next=kind==='row'?next.replace(/<row\b[^>]*r="2"[^>]*>/,tag=>tag.replace('>',` s="${style}" customFormat="1">`)):next.replace('<sheetData>',`<cols><col min="1" max="1" style="${style}"/></cols><sheetData>`)
 const saved=(await assemblePackage(bytes,{replaced:new Map([['xl/worksheets/sheet1.xml',next]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:['xl/worksheets/sheet1.xml']})).buffer
 const patterns=await readPivotSourcePatterns(await createBufferEntrySource(saved),next,{startRow:1,endRow:1,startColumn:0,endColumn:0})
 expect(patterns).toEqual([['0000']])
})

it('applies cell, custom row, column and default XF precedence including explicit style zero',async()=>{
 const {applyCellEdits,createBlankWorkbook,createBufferEntrySource}=await import('../src/index'),{readPivotSourcePatterns}=await import('../src/pivot-source-format')
 const bytes=await applyCellEdits(await createBlankWorkbook(),[{sheetName:'Sheet1',row:0,column:0,writeValue:true,cell:{value:1},style:{numberFormat:'0000'}},{sheetName:'Sheet1',row:0,column:1,writeValue:true,cell:{value:2},style:{numberFormat:'0.00'}}]),source=await createBufferEntrySource(bytes),xml=await source.readText('xl/worksheets/sheet1.xml')
 const digit=xml.match(/<c\b[^>]*r="A1"[^>]*s="(\d+)"/)![1],decimal=xml.match(/<c\b[^>]*r="B1"[^>]*s="(\d+)"/)![1]
 for(const [cell,rowStyle,custom,expected]of [['',decimal,'true','0.00'],[' s="0"',decimal,'1','General'],['',decimal,'0','0000'],['','0','1','General']] as const){
  const sheet=`<worksheet><cols><col min="1" max="1" style="${digit}"/></cols><sheetData><row r="2" s="${rowStyle}" customFormat="${custom}"><c r="A2"${cell}><v>1</v></c></row></sheetData></worksheet>`
  expect(await readPivotSourcePatterns(source,sheet,{startRow:1,endRow:1,startColumn:0,endColumn:0})).toEqual([[expected]])
 }
})
