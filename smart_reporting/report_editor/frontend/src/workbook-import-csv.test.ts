import { afterEach, expect, it, vi } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService, IUndoRedoService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
const implementation = './workbook-import-csv'
const product = () => import(/* @vite-ignore */ implementation)
const instances: Univer[] = []
afterEach(() => { vi.restoreAllMocks(); instances.splice(0).forEach(instance => instance.dispose()); document.body.replaceChildren() })
function fixture() {
 const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } }); instances.push(univer); univer.registerPlugin(UniverSheetsPlugin)
 const api = FUniver.newAPI(univer), book = api.createWorkbook({ id: 'csv', name: 'CSV', sheetOrder: ['s','other'], sheets: { s: { id:'s',name:'Data',rowCount:30,columnCount:20,cellData:{0:{0:{v:'manual draft'}},4:{2:{v:'before',s:{bl:1}}}} }, other:{id:'other',name:'Other',rowCount:30,columnCount:20} } })
 univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId()); const sheet=book.getActiveSheet()!; sheet.getRange('C5').activate()
 return { univer,api,book,sheet }
}
it('imports literal text and source numeric semantics at selection with one real undo/redo', async () => {
 const f=fixture(), { importCsvIntoSelection }=await product()
 expect(importCsvIntoSelection(f.book,'name;value;code;formula\r\n中文;12.5;007;=1+1\r\nTRUE;1234567890123456;+86;@SUM(A1)')).toEqual({rows:3,columns:4,address:'C5'})
 expect(f.sheet.getRange('C5:F7').getValues()).toEqual([['name','value','code','formula'],['中文',12.5,'007','=1+1'],['TRUE','1234567890123456','+86','@SUM(A1)']])
 expect(f.sheet.getRange('F6').getFormula()).toBe(''); expect(f.sheet.getRange('A1').getValue()).toBe('manual draft')
 expect(f.sheet.getSheet().getCell(4,2)?.s).toEqual({bl:1})
 await f.api.undo(); expect(f.sheet.getRange('C5').getValue()).toBe('before'); expect(f.sheet.getRange('D6').getValue()).toBeNull(); expect(f.sheet.getRange('A1').getValue()).toBe('manual draft')
 await f.api.redo(); expect(f.sheet.getRange('D6').getValue()).toBe(12.5)
})
it('parses BOM, sep declaration, multiline escaped quotes, CR-only and ragged rows as source',async()=>{
 const f=fixture(),{importCsvIntoSelection}=await product()
 importCsvIntoSelection(f.book,'\uFEFFsep=;\r\n"a;field";"a""b\r\nc"\rshort\r\r')
 expect(f.sheet.getRange('C5:D6').getValues()).toEqual([['a;field','a"b\nc'],['short','']])
})
it('replaces existing formulas with literal CSV text and restores formulas on undo',async()=>{
 const f=fixture(),{importCsvIntoSelection}=await product()
 f.sheet.getRange('C5').setValue({f:'=1+1'});importCsvIntoSelection(f.book,'=2+2')
 expect(f.sheet.getRange('C5').getFormula()).toBe('');expect(f.sheet.getRange('C5').getValue()).toBe('=2+2')
 await f.api.undo();expect(f.sheet.getRange('C5').getFormula()).toBe('=1+1')
})
it('reports a real native command cancellation without success, draft changes or undo history',async()=>{
 const f=fixture(),{openWorkbookCsvImport}=await product(),before=structuredClone(f.book.save()),history=f.univer.__getInjector().get(IUndoRedoService),undo=history.pitchTopUndoElement(),done=vi.fn(),setMessage=vi.fn()
 const guard=f.api.addEvent(f.api.Event.BeforeCommandExecute,(command:any)=>{if(command.id==='sheet.command.set-range-values')command.cancel=true})
 try {
  openWorkbookCsvImport({getWorkbook:()=>f.book,setMessage,onImported:done})
  const input=document.querySelector<HTMLInputElement>('input[type=file]')!;fileChange(input,{size:3,arrayBuffer:async()=>new TextEncoder().encode('x,y').buffer})
  await vi.waitFor(()=>expect(input.isConnected).toBe(false));expect(done).not.toHaveBeenCalled();expect(setMessage).toHaveBeenLastCalledWith(expect.stringMatching(/未应用|拒绝/));expect(f.book.save()).toEqual(before);expect(history.pitchTopUndoElement()).toBe(undo)
 } finally {guard.dispose()}
})
it('rejects empty, rectangle limit and out-of-grid data before mutation',async()=>{
 const f=fixture(),{importCsvIntoSelection}=await product(),before=structuredClone(f.book.save()),history=f.univer.__getInjector().get(IUndoRedoService),undo=history.pitchTopUndoElement()
 for(const text of ['', '\n\n',Array.from({length:251},()=>Array(200).fill('x').join(',')).join('\n')])expect(()=>importCsvIntoSelection(f.book,text)).toThrow()
 f.sheet.getRange('T30').activate();expect(()=>importCsvIntoSelection(f.book,'a,b')).toThrow()
 expect(f.book.save()).toEqual(before);expect(history.pitchTopUndoElement()).toBe(undo)
})
function fileChange(input:HTMLInputElement,file:unknown){Object.defineProperty(input,'files',{configurable:true,value:file?[file]:[]});input.dispatchEvent(new Event('change'))}
it('file picker decodes UTF16/GB18030 and removes itself after success',async()=>{
 const f=fixture(),{openWorkbookCsvImport}=await product(),messages:string[]=[],done=vi.fn()
 for(const bytes of [new Uint8Array([255,254,45,78,44,0,49,0]),new Uint8Array([0xd6,0xd0,44,49])]){
  openWorkbookCsvImport({getWorkbook:()=>f.book,setMessage:(message:string)=>messages.push(message),onImported:done})
  const input=document.querySelector<HTMLInputElement>('input[type=file]')!;expect(input.accept).toContain('.tsv');fileChange(input,{size:bytes.length,arrayBuffer:async()=>bytes.buffer})
  await vi.waitFor(()=>expect(input.isConnected).toBe(false));expect(f.sheet.getRange('C5:D5').getValues()).toEqual([['中',1]])
 }
 expect(done).toHaveBeenCalledTimes(2);expect(messages.at(-1)).toContain('C5')
})
it.each(['selection','sheet','blocked','disposed','draft'])('rejects asynchronous stale %s without changing target',async mode=>{
 const f=fixture(),{openWorkbookCsvImport}=await product(),messages:string[]=[];let blocked=false,resolve!:(value:ArrayBuffer)=>void
 const dispose=openWorkbookCsvImport({getWorkbook:()=>f.book,isBlocked:()=>blocked,setMessage:(message:string)=>messages.push(message)})
 const input=document.querySelector<HTMLInputElement>('input[type=file]')!;fileChange(input,{size:3,arrayBuffer:()=>new Promise<ArrayBuffer>(r=>{resolve=r})})
 if(mode==='selection')f.sheet.getRange('D6').activate()
 if(mode==='sheet')f.book.setActiveSheet(f.book.getSheetBySheetId('other')!)
 if(mode==='blocked')blocked=true
 if(mode==='disposed')dispose()
 if(mode==='draft')f.sheet.getRange('A1').setValue('new manual draft')
 resolve(new TextEncoder().encode('x,y').buffer as ArrayBuffer)
 await vi.waitFor(()=>expect(input.isConnected).toBe(false));await Promise.resolve()
 expect(f.sheet.getRange('C5').getValue()).toBe('before');if(mode!=='disposed')expect(messages.at(-1)).toMatch(/变化|不能|锁定/)
})
it.each(['cancel','oversize','read-failure','invalid-encoding'])('file %s leaves cells and undo unchanged',async mode=>{
 const f=fixture(),{openWorkbookCsvImport}=await product(),before=structuredClone(f.book.save()),history=f.univer.__getInjector().get(IUndoRedoService),undo=history.pitchTopUndoElement(),setMessage=vi.fn()
 openWorkbookCsvImport({getWorkbook:()=>f.book,setMessage})
 const input=document.querySelector<HTMLInputElement>('input[type=file]')!
 if(mode==='cancel')fileChange(input,null)
 else fileChange(input,{size:mode==='oversize'?32*1024*1024+1:4,arrayBuffer:async()=>{if(mode==='read-failure')throw Error('read failed');return new Uint8Array([255,254,0]).buffer}})
 await vi.waitFor(()=>expect(input.isConnected).toBe(false));expect(f.book.save()).toEqual(before);expect(history.pitchTopUndoElement()).toBe(undo)
 if(mode!=='cancel')expect(setMessage).toHaveBeenCalled()
})
