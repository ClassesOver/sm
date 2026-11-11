import {expect,it} from 'vitest'
import {Univer,LocaleType,IUniverInstanceService,ICommandService} from '@univerjs/core'
import {FUniver} from '@univerjs/core/lib/facade'
import {UniverSheetsPlugin} from '@univerjs/sheets'
import {UniverSheetsFilterPlugin} from '@univerjs/sheets-filter'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-filter/facade'
import {withWorkbookFilters,workbookFilterOperations} from './workbook-filters'
const range={startRow:4,endRow:8,startColumn:2,endColumn:4}
function source(custom=true){
 const columns=custom?[{colId:1,customs:{filters:[{val:'10',operator:'greaterThanOrEqual'}]}}]:[{colId:2,values:['keep']}]
 const hidden=custom?[5]:[7,8]
 const model:any={sheets:[{name:'Data',filter:{range,columns},rows:hidden.map(row=>({row:row+1,hidden:true}))}]}
 const data:any={id:'visibility',name:'Visibility',sheetOrder:['s'],styles:{},sheets:{s:{id:'s',name:'Data',rowCount:30,columnCount:10,rowData:Object.fromEntries(hidden.map(row=>[row,{hd:1,h:23,custom:{keep:true}}])),cellData:Object.fromEntries([['Group','Value','Other'],['A',5,'keep'],['B',10,'keep'],['A',20,'keep'],['B',30,'drop']].map((row,r)=>[r+4,Object.fromEntries(row.map((v,c)=>[c+2,{v,t:typeof v==='number'?2:1}]))]))}}}
 return {model,data}
}
function open(custom=true){
 const {model,data}=source(custom),univer=new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}});univer.registerPlugin(UniverSheetsPlugin);univer.registerPlugin(UniverSheetsFilterPlugin)
 const api=FUniver.newAPI(univer),book=api.createWorkbook(withWorkbookFilters(data,model));univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId())
 return {model,univer,api,book,sheet:book.getActiveSheet()!,commands:univer.__getInjector().get(ICommandService)}
}
it('releases source filter hd while preserving initial visibility and unrelated save; criteria changes and undo restore correctly',async()=>{
 const f=open();try{
 expect(f.sheet.getSheet().getRowManager().getRowData()[5]).toEqual({h:23,custom:{keep:true}})
 expect(f.sheet.getSheet().getRowVisible(5)).toBe(false);expect(workbookFilterOperations(f.model,f.book as any)).toEqual([])
 f.commands.syncExecuteCommand('sheet.command.set-filter-criteria',{unitId:'visibility',subUnitId:'s',col:3,criteria:{colId:3,customFilters:{customFilters:[{operator:'lessThan',val:'10'}]}}})
 expect(f.sheet.getSheet().getRowVisible(5)).toBe(true);expect(workbookFilterOperations(f.model,f.book as any)[0]).toMatchObject({hiddenRows:[6,7,8]})
 await f.api.undo();expect(f.sheet.getSheet().getRowVisible(5)).toBe(false);expect(workbookFilterOperations(f.model,f.book as any)).toEqual([])
 await f.api.redo();expect(f.sheet.getSheet().getRowVisible(5)).toBe(true)
 }finally{f.univer.dispose()}
})
it('keeps source matching-but-hidden rows and subsequent session hides across filter clearing',async()=>{
 const f=open(false);try{
 expect(f.sheet.getSheet().getRowManager().getRowData()[7].hd).toBe(1);expect(f.sheet.getSheet().getRowManager().getRowData()[8].hd).toBeUndefined()
 expect(workbookFilterOperations(f.model,f.book as any)).toEqual([]);f.sheet.hideRows(6)
 f.commands.syncExecuteCommand('sheet.command.clear-filter-criteria',{unitId:'visibility',subUnitId:'s'})
 expect(f.sheet.getSheet().getRowVisible(7)).toBe(false);expect(f.sheet.getSheet().getRowVisible(6)).toBe(false);expect(f.sheet.getSheet().getRowVisible(8)).toBe(true)
 expect(workbookFilterOperations(f.model,f.book as any)[0]).toMatchObject({hiddenRows:[6,7]})
 }finally{f.univer.dispose()}
})
it('leaves unsupported source conditions and their hidden rows untouched',()=>{
 const {data,model}=source();model.sheets[0].filter.columns[0].dateGroups=[{year:2026}]
 const before=structuredClone(data);expect(withWorkbookFilters(data,model)).toEqual(before)
})
