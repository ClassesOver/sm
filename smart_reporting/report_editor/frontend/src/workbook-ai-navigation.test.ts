import {afterEach,expect,it,vi} from 'vitest'
import {Univer,IUniverInstanceService} from '@univerjs/core'
import {FUniver} from '@univerjs/core/lib/facade'
import {UniverSheetsPlugin} from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import {navigateWorkbookReadTarget} from './workbook-ai-navigation'
const live: Univer[]=[]
afterEach(()=>{for(const item of live)item.dispose();live.length=0})
function fixture(){
 const univer=new Univer();live.push(univer);univer.registerPlugin(UniverSheetsPlugin)
 const api=FUniver.newAPI(univer),book=api.createWorkbook({id:'ai-nav',name:'Navigation',sheetOrder:['a','b'],sheets:{a:{id:'a',name:'First',rowCount:100,columnCount:20,cellData:{0:{0:{v:42}}}},b:{id:'b',name:'Target',rowCount:100,columnCount:20,cellData:{2:{2:{v:84}}}}}})
 univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId())
 const reveal=vi.fn().mockResolvedValue(true)
 return {book,runtime:{univer,univerAPI:api},options:{current:()=>true,closed:()=>false,cancel:vi.fn(),reveal}}
}
const target={sheetName:'Target',range:'C3:D5',startRow:2,endRow:4,startColumn:2,endColumn:3}
it('selects actual sheet/range and verifies visibility without changing stored cells',async()=>{
 const f=fixture(),before=JSON.stringify(f.book.save().sheets)
 await navigateWorkbookReadTarget(f.runtime,target,f.options)
 expect(f.book.getActiveSheet()!.getSheetName()).toBe('Target')
 expect(f.book.getActiveRange()!.getRange()).toMatchObject({startRow:2,endRow:4,startColumn:2,endColumn:3})
 expect(f.options.reveal).toHaveBeenCalledWith(expect.anything(),2,2,expect.any(Function))
 expect(JSON.stringify(f.book.save().sheets)).toBe(before)
})
it.each([{...target,range:'C3'}, {...target,startRow:-1}, {...target,endColumn:16384},{...target,sheetName:'Unknown'}])('rejects invalid target before mutation',async value=>{
 const f=fixture();await expect(navigateWorkbookReadTarget(f.runtime,value,f.options)).rejects.toThrow()
 expect(f.book.getActiveSheet()!.getSheetName()).toBe('First');expect(f.options.reveal).not.toHaveBeenCalled()
})
it('does not claim visibility when reveal fails or user moves selection',async()=>{
 const f=fixture();f.options.reveal.mockResolvedValue(false)
 await expect(navigateWorkbookReadTarget(f.runtime,target,f.options)).rejects.toThrow('显示')
 f.options.reveal.mockImplementation(async()=>{f.book.setActiveRange(f.book.getActiveSheet()!.getRange('A1'));return true})
 await expect(navigateWorkbookReadTarget(f.runtime,target,f.options)).rejects.toThrow()
})
it('never moves closed or cancelled tasks',async()=>{
 const f=fixture();await expect(navigateWorkbookReadTarget(f.runtime,target,{...f.options,current:()=>false})).rejects.toThrow()
 await expect(navigateWorkbookReadTarget(f.runtime,target,{...f.options,closed:()=>true})).rejects.toThrow()
 expect(f.book.getActiveSheet()!.getSheetName()).toBe('First')
})
