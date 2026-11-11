import {expect,it,vi} from 'vitest'
import {Univer,LocaleType,IUniverInstanceService,ICommandService,IUndoRedoService} from '@univerjs/core'
import {FUniver} from '@univerjs/core/lib/facade'
import {UniverSheetsPlugin} from '@univerjs/sheets'
import {UniverSheetsFilterPlugin,SheetsFilterService} from '@univerjs/sheets-filter'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-filter/facade'
const path='./workbook-advanced-filter'
const range={startRow:4,endRow:9,startColumn:2,endColumn:4}
async function fixture(options:any={}){
 const univer=new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}});univer.registerPlugin(UniverSheetsPlugin);univer.registerPlugin(UniverSheetsFilterPlugin)
 const api=FUniver.newAPI(univer),book=api.createWorkbook({id:'advanced',name:'Book',sheetOrder:['s'],sheets:{s:{id:'s',name:'Data',rowCount:30,columnCount:10,cellData:Object.fromEntries([['Group','Value','Keep'],['A',5,'yes'],['B',10,'yes'],['A',20,'yes'],['B',30,'no'],['A',40,'yes']].map((row,r)=>[r+4,Object.fromEntries(row.map((v,c)=>[c+2,{v}]))]))}}})
 univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId());const sheet=book.getActiveSheet()!;sheet.getRange('C5:E10').activate()
 let metadata:any={journal:['old']}
 const control=(await import(path)).installAdvancedFilter({univer,univerAPI:api},{preflight:()=>{},captureMetadata:()=>structuredClone(metadata),restoreMetadata:(value:any)=>{metadata=structuredClone(value)},...options})
 const commands=univer.__getInjector().get(ICommandService),history=univer.__getInjector().get(IUndoRedoService),filters=univer.__getInjector().get(SheetsFilterService)
 return {univer,api,book,sheet,control,commands,history,model:()=>filters.getFilterModel('advanced','s'),close:()=>{control.dispose();univer.dispose()}}
}
it('no-filter capture is read-only and confirm creates range and criteria in one undo/redo',async()=>{
 const f=await fixture();try{
 const target=f.control.capture();expect(target.range).toEqual(range);expect(f.model()).toBeNull();expect(f.history.pitchTopUndoElement()).toBeNull()
 await f.control.apply(target,{colId:1,operator1:'greaterThanOrEqual',value1:'10',operator2:'lessThan',value2:'30',and:true})
 expect([...f.model()!.filteredOutRows].sort((a,b)=>a-b)).toEqual([5,8,9]);expect(f.model()!.getFilterColumn(3)!.serialize().customFilters?.and).toBe(1)
 await f.api.undo();expect(f.model()).toBeNull();await f.api.redo();expect([...f.model()!.filteredOutRows].sort((a,b)=>a-b)).toEqual([5,8,9])
 }finally{f.close()}
})
it('preserves offset neighbouring column criteria, equal omits operator and OR stays native',async()=>{
 const f=await fixture();try{
 f.commands.syncExecuteCommand('sheet.command.set-filter-range',{unitId:'advanced',subUnitId:'s',range})
 f.commands.syncExecuteCommand('sheet.command.set-filter-criteria',{unitId:'advanced',subUnitId:'s',col:4,criteria:{colId:4,filters:{filters:['yes']}}})
 await f.control.apply(f.control.capture(),{colId:0,operator1:'equal',value1:'A'})
 expect(f.model()!.getFilterColumn(2)!.serialize().customFilters?.customFilters).toEqual([{val:'A'}]);expect([...f.model()!.filteredOutRows].sort((a,b)=>a-b)).toEqual([6,8])
 expect(f.model()!.getFilterColumn(4)!.serialize().filters?.filters).toEqual(['yes'])
 await f.control.apply(f.control.capture(),{colId:1,operator1:'lessThan',value1:'10',operator2:'greaterThan',value2:'30',and:false})
 expect([...f.model()!.filteredOutRows].sort((a,b)=>a-b)).toEqual([6,7,8])
 }finally{f.close()}
})
it.each(['sheet.command.set-filter-range','sheet.command.set-filter-criteria','sheet.mutation.set-filter-range','sheet.mutation.set-filter-criteria','history-before','history-after'])('atomic failure restores old state and redo (%s)',async fault=>{
 const f=await fixture();try{
 f.sheet.getRange('A1').setValue('old');f.sheet.getRange('A2').setValue('redo');await f.api.undo();f.sheet.getRange('C5:E10').activate()
 const undo=f.history.pitchTopUndoElement(),redo=f.history.pitchTopRedoElement(),target=f.control.capture();let once=true
 const execute=f.commands.syncExecuteCommand.bind(f.commands),push=f.history.pushUndoRedo.bind(f.history)
 const spy=fault.startsWith('sheet.command')?vi.spyOn(f.commands,'syncExecuteCommand').mockImplementation(((id:string,p:any,o:any)=>{if(id===fault&&once){once=false;return false}return execute(id,p,o)}) as any):undefined
 const hook=f.commands.onCommandExecuted((command:any)=>{if(command.id===fault&&once){once=false;throw new Error('post mutation')}})
 const hspy=fault.startsWith('history')?vi.spyOn(f.history,'pushUndoRedo').mockImplementation((item:any)=>{if(fault==='history-after')push(item);throw new Error('history failure')}):undefined
 await expect(f.control.apply(target,{colId:0,operator1:'equal',value1:'A'})).rejects.toThrow()
 spy?.mockRestore();hook.dispose();hspy?.mockRestore()
 expect(f.model()).toBeNull();expect(f.history.pitchTopUndoElement()).toBe(undo);expect(f.history.pitchTopRedoElement()).toBe(redo)
 await f.api.redo();expect(f.sheet.getRange('A2').getValue()).toBe('redo')
 }finally{f.close()}
})
it('uses native single-cell expansion without mutation and rejects stale/preflight/protection',async()=>{
 let release!:()=>void;const f=await fixture({preflight:()=>new Promise<void>(r=>{release=r})});try{
 f.sheet.getRange('D7').activate();const target=f.control.capture();expect(target.range).toEqual(range);expect(f.model()).toBeNull()
 const applying=f.control.apply(target,{colId:0,operator1:'equal',value1:'A'});f.sheet.getRange('A1').setValue('concurrent');release();await expect(applying).rejects.toThrow('变化');expect(f.model()).toBeNull()
 }finally{f.close()}
 const p=await fixture({protectedSheet:()=>true});try{expect(()=>p.control.capture()).toThrow('受保护')}finally{p.close()}
})
it.each([false,true])('existing filter rollback preserves all criteria, visibility and foreign history (fail=%s)',async fail=>{
 const f=await fixture();try{
 f.commands.syncExecuteCommand('sheet.command.set-filter-range',{unitId:'advanced',subUnitId:'s',range})
 f.commands.syncExecuteCommand('sheet.command.set-filter-criteria',{unitId:'advanced',subUnitId:'s',col:4,criteria:{colId:4,filters:{filters:['yes']}}})
 const foreign=f.api.createWorkbook({id:'foreign',name:'Foreign',sheetOrder:['x'],sheets:{x:{id:'x',name:'X',rowCount:10,columnCount:10}}}),other=foreign.getActiveSheet()!
 f.univer.__getInjector().get(IUniverInstanceService).focusUnit('advanced');f.sheet.getRange('C5:E10').activate()
 const before=f.model()!.serialize(),undo=f.history.pitchTopUndoElement();let once=true
 const hook=f.commands.onCommandExecuted((command:any)=>{if(command.id==='sheet.mutation.set-filter-criteria'&&once){once=false;other.getRange('A1').setValue('foreign');if(fail)throw new Error('after native mutation')}})
 const applying=f.control.apply(f.control.capture(),{colId:0,operator1:'equal',value1:'A'})
 if(fail){await expect(applying).rejects.toThrow();expect(f.model()!.serialize()).toEqual(before);expect(f.history.pitchTopUndoElement()).toBe(undo)}else await applying
 hook.dispose();f.univer.__getInjector().get(IUniverInstanceService).focusUnit('foreign');await f.api.undo();expect(other.getRange('A1').getValue()).toBeNull();await f.api.redo();expect(other.getRange('A1').getValue()).toBe('foreign')
 }finally{f.close()}
})
it('rejects changed protection, same-id replacement, tampered range and invalid conditions before mutation',async()=>{
 let protectedSheet=false;const f=await fixture({protectedSheet:()=>protectedSheet});try{
 const target=f.control.capture();protectedSheet=true;await expect(f.control.apply(target,{colId:0,operator1:'equal',value1:'A'})).rejects.toThrow('受保护');protectedSheet=false
 await expect(f.control.apply({...target,range:{...target.range,endRow:8}},{colId:0,operator1:'equal',value1:'A'})).rejects.toThrow('变化')
 for(const input of [{colId:9,operator1:'equal',value1:'A'},{colId:0,operator1:'bogus',value1:'A'},{colId:0,operator1:'equal',value1:''},{colId:0,operator1:'equal',value1:'A',value2:null},{colId:0,operator1:'equal',value1:'A',and:'bad'}])await expect(f.control.apply(target,input)).rejects.toThrow()
 expect(f.model()).toBeNull();f.api.disposeUnit('advanced');f.api.createWorkbook({id:'advanced',sheetOrder:['s'],sheets:{s:{id:'s',name:'Replacement',rowCount:30,columnCount:10}}});f.univer.__getInjector().get(IUniverInstanceService).focusUnit('advanced')
 await expect(f.control.apply(target,{colId:0,operator1:'equal',value1:'A'})).rejects.toThrow('变化')
 }finally{f.close()}
})
it('preserves numeric/boolean headers and manual hides and rolls metadata failure back',async()=>{
 let captures=0;const f=await fixture({captureMetadata:()=>{if(++captures===2)throw new Error('metadata finalization');return {old:true}}});try{
 f.sheet.getRange('C5').setValue(0);f.sheet.getRange('D5').setValue(false)
 const manager=f.sheet.getSheet().getRowManager();manager.getRowOrCreate(7);manager.getRowData()[7].hd=1
 const target=f.control.capture();expect(target.fields.slice(0,2).map((field:any)=>field.label)).toEqual(['0','0'])
 await expect(f.control.apply(target,{colId:0,operator1:'notEqual',value1:'B'})).rejects.toThrow('metadata finalization')
 expect(f.model()).toBeNull();expect(manager.getRowData()[7].hd).toBe(1);expect(f.history.pitchTopUndoElement()?.redoMutations[0].id).not.toBe('sheet.mutation.set-filter-range')
 }finally{f.close()}
})
