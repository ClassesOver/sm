import { afterEach, expect, it, vi } from 'vitest'
import { buildWorkbookPrintJob, createPrintPreviewDialog, type WorkbookPrintJob } from './workbook-print-preview'
import type { SheetPrintSetup, SheetPrintSource } from './workbook-print'
const setup: SheetPrintSetup = { orientation:'portrait',paperSize:9,scale:100,fitToPage:false,fitToWidth:0,fitToHeight:0,margins:{left:.7,right:.7,top:.75,bottom:.75},printGridlines:false,printHeadings:false,printArea:null,printTitles:null,rowBreaks:[],colBreaks:[],headerFooter:{oddHeader:'&CO&P/&N',evenHeader:'&CE&P/&N',firstHeader:'&CF&P/&N',differentOddEven:true} }
const source = (name:string): SheetPrintSource => ({name,cells:{A1:{value:name}},merges:[],columnWidths:{},rowHeights:{},hiddenColumns:new Set(),hiddenRows:new Set()})
const job = (): WorkbookPrintJob => buildWorkbookPrintJob([{sheetId:'a',source:source('A'),setup},{sheetId:'b',source:source('B'),setup:{...setup,orientation:'landscape',headerFooter:{...setup.headerFooter,differentFirst:true}}}])!
afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks()})
it('combines per-sheet paper and job numbering, with first-page precedence',()=>{
 const result=job(); expect(result.pageCount).toBe(2);expect(result.pages.map(p=>p.sheetName)).toEqual(['A','B'])
 const parsed=new DOMParser().parseFromString(result.html,'text/html')
 expect([...parsed.querySelectorAll('.hf-header')].map(x=>x.textContent)).toEqual(['O1/2','F2/2'])
 expect(result.pages[1]!.widthIn).toBe(11.69);expect(result.html).toContain('@page sheet1');expect(parsed.querySelectorAll('.page')[1]!.getAttribute('style')).toContain('page:sheet1')
 const even=buildWorkbookPrintJob([{sheetId:'a',source:source('A'),setup},{sheetId:'b',source:source('B'),setup}])!
 expect(new DOMParser().parseFromString(even.html,'text/html').querySelectorAll('.hf-header')[1]!.textContent).toBe('E2/2')
})
it('empty sheets are skipped and text remains escaped',()=>{
 expect(buildWorkbookPrintJob([{sheetId:'empty',source:{...source('empty'),cells:{}},setup}])).toBeNull()
 const result=buildWorkbookPrintJob([{sheetId:'a',source:source('<script>bad</script>'),setup}])!
 expect(new DOMParser().parseFromString(result.html,'text/html').querySelector('script')).toBeNull()
})
const settle=()=>new Promise(resolve=>setTimeout(resolve,0))
it('keeps the static preview outside the Tab order and discards a build after Escape',async()=>{
 const opener=document.createElement('button');document.body.append(opener);opener.focus()
 const root=document.createElement('div');document.body.append(root);let resolve!:(value:WorkbookPrintJob)=>void
 const dialog=createPrintPreviewDialog(root,{buildJob:()=>new Promise(r=>{resolve=r}),print:vi.fn()})
 dialog.open({hasSelection:true,sheetCount:2})
 const frame=root.querySelector('iframe')!
 expect(frame.tabIndex).toBe(-1)
 const pane=root.querySelector<HTMLElement>('[data-print-pane]')!
 expect(pane.tabIndex).toBe(0)
 expect(pane.getAttribute('aria-label')).toBe('打印预览区域')
 window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))
 expect(root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true)
 expect(document.activeElement).toBe(opener)
 resolve(job());await settle();expect(frame.srcdoc).toBe('');dialog.dispose()
})
it('previews active scope, browses pages, rebuilds scope and refreshes before print',async()=>{
 const root=document.createElement('div');document.body.append(root);const buildJob=vi.fn(async()=>job()),print=vi.fn(()=>true)
 const dialog=createPrintPreviewDialog(root,{buildJob,print});dialog.open({hasSelection:true,sheetCount:2});await settle()
 expect(buildJob).toHaveBeenLastCalledWith('active');expect(root.querySelector('iframe')!.getAttribute('sandbox')).toBe('')
 ;(root.querySelector('[data-print-next]') as HTMLButtonElement).click();expect(root.querySelector('[data-print-page]')!.textContent).toContain('2 / 2')
 const scope=root.querySelector('[data-print-scope]') as HTMLSelectElement;scope.value='workbook';scope.dispatchEvent(new Event('change'));await settle();expect(buildJob).toHaveBeenLastCalledWith('workbook')
 ;(root.querySelector('[data-print-submit]') as HTMLButtonElement).click();await settle();expect(buildJob).toHaveBeenCalledTimes(3);expect(print).toHaveBeenCalledWith(job().html);dialog.dispose()
})
it('ignores stale builds after scope change and cancel, and surfaces build/print failures',async()=>{
 const root=document.createElement('div');document.body.append(root);let resolve!:(value:WorkbookPrintJob)=>void
 const buildJob=vi.fn().mockImplementationOnce(()=>new Promise(r=>{resolve=r})).mockResolvedValue(job());const print=vi.fn(()=>false)
 const dialog=createPrintPreviewDialog(root,{buildJob,print});dialog.open({hasSelection:false,sheetCount:1})
 const scope=root.querySelector('[data-print-scope]') as HTMLSelectElement;scope.value='workbook';scope.dispatchEvent(new Event('change'));await settle();resolve({...job(),pageCount:99});await settle();expect(root.querySelector('[data-print-page]')!.textContent).toContain('1 / 2')
 ;(root.querySelector('[data-print-submit]') as HTMLButtonElement).click();await settle();expect(root.querySelector('[data-print-error]')!.textContent).toContain('打印')
 ;(root.querySelector('[data-print-cancel]') as HTMLButtonElement).click();expect(root.querySelector('[role=dialog]')!.hasAttribute('hidden')).toBe(true);dialog.dispose()
})

it('collects visible live sheets in snapshot order and overrides only selected print area',async()=>{
 const {printInputsForScope}=await import('./workbook-print-preview')
 const snapshot={sheetOrder:['b','hidden','a'],sheets:{a:{name:'A',cellData:{0:{0:{v:'live A'}}}},b:{name:'B',cellData:{0:{0:{v:'live B'}}}},hidden:{name:'H',hidden:1}},styles:{}}
 const model={sheets:[{name:'A',printArea:'A1:C3',pageSetup:{orientation:'landscape' as const}},{name:'B',printArea:'A1:B2'}]}
 expect(printInputsForScope(snapshot,model,'workbook','a',null).map(x=>x.sheetId)).toEqual(['b','a'])
 const selected=printInputsForScope(snapshot,model,'selection','a',{startRow:1,endRow:2,startColumn:1,endColumn:2})
 expect(selected).toHaveLength(1);expect(selected[0]!.setup.printArea).toBe('B2:C3');expect(selected[0]!.setup.orientation).toBe('landscape');expect(selected[0]!.source.cells.A1!.value).toBe('live A')
 expect(()=>printInputsForScope(snapshot,model,'selection','a',null)).toThrow('选定')
})
