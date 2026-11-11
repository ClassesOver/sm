import { expect, it, vi } from 'vitest'
import { applyCellEdits, createBlankWorkbook, readWorkbook, createBufferEntrySource } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/index'
import { assemblePackage } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookMergePlan, dedupeMergedSheetName, openWorkbookMergePicker } from './workbook-merge'

async function source(){return applyCellEdits(await createBlankWorkbook(),[{sheetName:'Sheet1',row:0,column:0,writeValue:true,cell:{value:'source'},style:{bold:true,fillColor:'#FFFF00'}},{sheetName:'Sheet1',row:1,column:0,writeValue:true,cell:{value:12},style:{numberFormat:'0.00'}}])}
async function formulaSource(value:string,extra=''){
 const bytes=await source(),zip=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml'
 const workbookXml=await zip.readText('xl/workbook.xml'),calculated=workbookXml.includes('<calcPr')?workbookXml.replace(/<calcPr\b[^>]*\/>/,'<calcPr fullCalcOnLoad="0" calcCompleted="1"/>'):workbookXml.replace('<sheets','<calcPr fullCalcOnLoad="0" calcCompleted="1"/><sheets')
 return (await assemblePackage(bytes,{replaced:new Map([[path,(await zip.readText(path)).replace(/<c\b[^>]*\br="A2"[^>]*>[\s\S]*?<\/c>/,`<c r="A2"${extra}><f>6*2</f>${value}</c>`)],['xl/workbook.xml',calculated]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path,'xl/workbook.xml']})).buffer
}
it('appends every sheet from multiple files, retaining the current draft, formats, merges and dimensions',async()=>{
 const target=await applyCellEdits(await createBlankWorkbook(),[{sheetName:'Sheet1',row:0,column:3,writeValue:true,cell:{value:'manual draft'}}]),first=await applyWorkbookOperations(await source(),[{kind:'applySheetMerges',sheetName:'Sheet1',ranges:['A3:B3']},{kind:'applyColumnWidths',sheetName:'Sheet1',entries:[{index:0,widthChars:22}]},{kind:'applyRowHeights',sheetName:'Sheet1',entries:[{index:1,heightPoints:30}]}]),snapshot=target.slice()
 const plan=await createWorkbookMergePlan(target,[{name:'a.xlsx',bytes:first},{name:'b.xlsx',bytes:await source()}]),result=await applyWorkbookOperations(target,plan.operations),book=await readWorkbook(result)
 expect(plan.sheetNames).toEqual(['Sheet1 (2)','Sheet1 (3)']);expect(target).toEqual(snapshot)
 expect(book.sheets.map(sheet=>sheet.name)).toEqual(['Sheet1','Sheet1 (2)','Sheet1 (3)']);expect(book.sheets[0]!.cells.D1?.value).toBe('manual draft')
 expect(book.sheets[1]!.cells.A1?.value).toBe('source');expect(book.sheets[1]!.merges).toEqual(['A3:B3'])
 expect(book.sheets[1]!.columns[0]!.width).toBe(22);expect(book.sheets[1]!.columns[0]!.start).toBe(1);expect(book.sheets[1]!.rows.find(row=>row.row===2)?.height).toBe(30)
 const xf=book.styles.cellXfs[book.sheets[1]!.cells.A1!.styleIndex!]!;expect(book.styles.fonts[xf.fontId]!.bold).toBe(true)
})
it.each([['<v>12</v>','',12],['<v>cached &amp; text</v>',' t="str"','cached & text'],['<v>1</v>',' t="b"',true]] as const)('imports a formula cached value as a literal without losing it: %s',async(value,extra,expected)=>{
 const target=await createBlankWorkbook(),plan=await createWorkbookMergePlan(target,[{name:'formula.xlsx',bytes:await formulaSource(value,extra)}]),book=await readWorkbook(await applyWorkbookOperations(target,plan.operations))
 expect(book.sheets[1]!.cells.A2?.value).toBe(expected);expect(book.sheets[1]!.cells.A2?.formula).toBeUndefined()
})
it('rejects a missing/invalid cached result, including a failure in a later file, atomically',async()=>{
 const target=await createBlankWorkbook(),snapshot=target.slice()
 for(const value of ['', '<v/>','<v>NaN</v>'])await expect(createWorkbookMergePlan(target,[{name:'ok.xlsx',bytes:await source()},{name:'bad.xlsx',bytes:await formulaSource(value)}])).rejects.toThrow('公式缓存')
 expect(target).toEqual(snapshot)
})
it('rejects a cached formula when workbook calculation is pending',async()=>{
 const target=await createBlankWorkbook(),bytes=await formulaSource('<v>12</v>'),zip=await createBufferEntrySource(bytes),xml=(await zip.readText('xl/workbook.xml')).replace(/<calcPr\b[^>]*\/>/,'<calcPr fullCalcOnLoad="1"/>'),pending=(await assemblePackage(bytes,{replaced:new Map([['xl/workbook.xml',xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:['xl/workbook.xml']})).buffer
 await expect(createWorkbookMergePlan(target,[{name:'pending.xlsx',bytes:pending}])).rejects.toThrow('公式缓存')
})
it('deduplicates names case-insensitively within the 31-character Excel limit',()=>{
 expect(dedupeMergedSheetName('sheet1',new Set(['Sheet1']))).toBe('sheet1 (2)')
 const name='a'.repeat(30);expect(dedupeMergedSheetName(name,new Set([name]))).toBe('a'.repeat(27)+' (2)')
})
it('leaves the workbook untouched on cancel, empty selection, stale draft and async file failure',async()=>{
 const workbook={},onMerge=vi.fn(async()=>{}),setMessage=vi.fn();let draft='before'
 const open=()=>{openWorkbookMergePicker({capture:()=>({workbook,draft}),onMerge,setMessage});return document.querySelector<HTMLInputElement>('input[type=file]')!}
 let input=open();input.dispatchEvent(new Event('cancel'));expect(onMerge).not.toHaveBeenCalled();expect(input.isConnected).toBe(false)
 input=open();Object.defineProperty(input,'files',{value:[]});input.dispatchEvent(new Event('change'));expect(onMerge).not.toHaveBeenCalled()
 let resolve!:(bytes:ArrayBuffer)=>void;input=open();Object.defineProperty(input,'files',{value:[{name:'a.xlsx',size:2,arrayBuffer:()=>new Promise<ArrayBuffer>(done=>{resolve=done})}]});input.dispatchEvent(new Event('change'));draft='changed';resolve(new ArrayBuffer(2));await vi.waitFor(()=>expect(input.isConnected).toBe(false));expect(onMerge).not.toHaveBeenCalled();expect(setMessage).toHaveBeenCalledWith(expect.stringContaining('草稿已变化'))
 input=open();Object.defineProperty(input,'files',{value:[{name:'a.xlsx',size:2,arrayBuffer:async()=>{throw new Error('read failed')}}]});input.dispatchEvent(new Event('change'));await vi.waitFor(()=>expect(input.isConnected).toBe(false));expect(onMerge).not.toHaveBeenCalled()
})
