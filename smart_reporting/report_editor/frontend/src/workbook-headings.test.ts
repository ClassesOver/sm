import {expect,it,vi} from 'vitest'
import {BooleanNumber} from '@univerjs/core'
import {IRenderManagerService,SHEET_VIEWPORT_KEY} from '@univerjs/engine-render'
const implementation='./workbook-headings'
function setup(){
 const config={rowHeader:{hidden:BooleanNumber.FALSE},columnHeader:{hidden:BooleanNumber.FALSE}},core={}
 const sheet={getSheet:()=>({getConfig:()=>config}),getSheetId:()=> 's',getSheetName:()=> 'Data'};const nativeSheet=sheet.getSheet();sheet.getSheet=()=>nativeSheet
 const book={getWorkbook:()=>core,getId:()=> 'book',getActiveSheet:()=>sheet,getSheetBySheetId:()=>sheet},main={left:46},right={left:46,setViewportSize:vi.fn(function(this:any,{left}:any){this.left=left})},skeleton={rowHeaderWidth:46},scene={getViewport:(id:string)=>id===SHEET_VIEWPORT_KEY.VIEW_MAIN?main:right,makeDirty:vi.fn()},render={scene,with:()=>({getCurrentSkeleton:()=>skeleton})}
 let current:any=book
 const executeCommand=vi.fn(async(id:string,params:any)=>{if(id==='sheet.command.set-row-header-width'){const shift=params.size-46;main.left+=shift;right.left+=shift;skeleton.rowHeaderWidth=params.size}return true})
 const runtime={univer:{__getInjector:()=>({get:(token:any)=>{expect(token).toBe(IRenderManagerService);return{getRenderById:()=>render}}})},univerAPI:{getActiveWorkbook:():any=>current,executeCommand}}
 return{runtime,config,main,right,scene,skeleton,executeCommand,sheet,book,replace:()=>{current={...book,getWorkbook:()=>({})}}}
}
it('hides and shows both native headers and repairs the native zero-width fallback viewport shift',async()=>{
 const {toggleWorkbookHeadings}=await import(/* @vite-ignore */implementation),c=setup()
 expect(await toggleWorkbookHeadings(c.runtime)).toEqual({sheetId:'s',sheetName:'Data',showHeadings:false})
 expect(c.config.rowHeader.hidden).toBe(BooleanNumber.TRUE);expect(c.config.columnHeader.hidden).toBe(BooleanNumber.TRUE);expect(c.main.left).toBe(0)
 expect(await toggleWorkbookHeadings(c.runtime)).toEqual({sheetId:'s',sheetName:'Data',showHeadings:true})
 expect(c.main.left).toBe(46);expect(c.right.left).toBe(46);expect(c.scene.makeDirty).toHaveBeenCalledOnce()
 expect(c.executeCommand.mock.calls.map(([id,p])=>[id,p.size])).toEqual([['sheet.command.set-row-header-width',0],['sheet.command.set-col-header-height',0],['sheet.command.set-row-header-width',46],['sheet.command.set-col-header-height',20]])
})
it('does not correct or report a stale workbook after asynchronous native commands',async()=>{
 const {toggleWorkbookHeadings}=await import(/* @vite-ignore */implementation),c=setup()
 c.executeCommand.mockImplementation(async()=>{c.replace();return true})
 await expect(toggleWorkbookHeadings(c.runtime)).rejects.toThrow('已关闭或替换');expect(c.scene.makeDirty).not.toHaveBeenCalled();expect(c.right.setViewportSize).not.toHaveBeenCalled()
})
it('does not correct the new active sheet viewport after a sheet switch',async()=>{
 const {toggleWorkbookHeadings}=await import(/* @vite-ignore */implementation),c=setup()
 c.executeCommand.mockImplementation(async()=>{c.book.getActiveSheet=()=>({...c.sheet,getSheet:()=>({getConfig:()=>c.config})});return true})
 await expect(toggleWorkbookHeadings(c.runtime)).rejects.toThrow('已关闭或替换');expect(c.scene.makeDirty).not.toHaveBeenCalled();expect(c.right.setViewportSize).not.toHaveBeenCalled()
})
it('does not report success when a native header command fails',async()=>{
 const {toggleWorkbookHeadings}=await import(/* @vite-ignore */implementation),c=setup();c.executeCommand.mockResolvedValue(false)
 await expect(toggleWorkbookHeadings(c.runtime)).rejects.toThrow('标题显示未应用');expect(c.scene.makeDirty).not.toHaveBeenCalled()
})
it('keeps a missing workbook a clear no-op error without invoking native commands',async()=>{
 const {toggleWorkbookHeadings}=await import(/* @vite-ignore */implementation),c=setup();c.runtime.univerAPI.getActiveWorkbook=()=>null
 await expect(toggleWorkbookHeadings(c.runtime)).rejects.toThrow('工作簿尚未就绪');expect(c.executeCommand).not.toHaveBeenCalled()
})
