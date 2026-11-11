/** 固定 GenOffice merge-workbooks：追加值/格式/几何，公式只导入可用缓存。 */
import { SaxesParser } from 'saxes'
import { readWorkbook, createBufferEntrySource, parseAddress, type CellEdit } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/index'
import { logicalStyleOf, styleDelta } from './workbook-vendor/core/style-map'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import type { WorkbookOperation } from './workbook-draft'

export interface MergeWorkbookSource { name:string; bytes:Uint8Array }
export interface WorkbookMergeSnapshot { workbook:object|null; draft:string }
export interface WorkbookMergePickerOptions {
 capture:()=>WorkbookMergeSnapshot|undefined
 isBlocked?:()=>boolean
 setMessage:(message:string)=>void
 onMerge:(sources:MergeWorkbookSource[],validate:()=>void)=>Promise<void>
}
export interface WorkbookMergeActionOptions extends Omit<WorkbookMergePickerOptions,'onMerge'> {
 wait:()=>Promise<void>
 original:()=>Uint8Array
 currentOperations:()=>Promise<WorkbookOperation[]>
 loadOperations:(operations:WorkbookOperation[])=>Promise<void>
 locked:(operation:()=>Promise<void>)=>Promise<void>
 onApplied:(files:number,sheets:number)=>void
}
/** 文件读取前后复核同一份草稿；提交方在事务锁内再次调用 validate。 */
export function openWorkbookMergePicker(options:WorkbookMergePickerOptions):()=>void{
 const captured=options.capture(),input=document.createElement('input')
 let disposed=false,reading=false
 const dispose=()=>{disposed=true;input.remove();input.onchange=null;input.oncancel=null}
 const fail=(error:unknown)=>{if(!disposed)options.setMessage(error instanceof Error?error.message:'合并工作簿失败');dispose()}
 const validate=()=>{
  if(disposed)throw new Error('合并工作簿已取消')
  if(options.isBlocked?.())throw new Error('当前工作簿已锁定，不能合并')
  const current=options.capture()
  if(!captured||current?.workbook!==captured.workbook||current.draft!==captured.draft)throw new Error('当前工作簿或草稿已变化，请重新选择合并文件')
 }
 try{validate()}catch(error){fail(error);return dispose}
 input.type='file';input.multiple=true;input.accept='.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';input.hidden=true
 input.oncancel=dispose
 input.onchange=()=>{
  if(disposed||reading)return
  const files=Array.from(input.files??[])
  if(!files.length){dispose();return}
  reading=true
  void(async()=>{
   validate()
   if(files.length>20||files.some(file=>file.size>32*1024*1024)||files.reduce((sum,file)=>sum+file.size,0)>64*1024*1024)throw new Error('一次最多合并20个文件，每个最多32 MiB，合计最多64 MiB')
   const sources:MergeWorkbookSource[]=[]
   for(const file of files){const bytes=new Uint8Array(await file.arrayBuffer());validate();sources.push({name:file.name,bytes})}
   validate();await options.onMerge(sources,validate);dispose()
  })().catch(fail)
 }
 document.body.append(input);input.click();return dispose
}
export function openWorkbookMergeAction(options:WorkbookMergeActionOptions):void{
 openWorkbookMergePicker({...options,onMerge:async(sources,validate)=>{
  await options.locked(async()=>{
   await options.wait();validate()
   const before=await options.currentOperations(),target=await applyWorkbookOperations(options.original(),before),plan=await createWorkbookMergePlan(target,sources)
   validate()
   try{await options.loadOperations([...before,...plan.operations])}catch(error){await options.loadOperations(before);throw error}
   options.onApplied(plan.files,plan.importedSheets)
  })
 }})
}
export function dedupeMergedSheetName(name:string,taken:ReadonlySet<string>):string{
 const names=new Set([...taken].map(item=>item.toLowerCase()))
 if(!names.has(name.toLowerCase()))return name
 for(let index=2;;index++){const suffix=` (${index})`,candidate=name.slice(0,31-suffix.length).replace(/[\s']+$/,'')+suffix;if(!names.has(candidate.toLowerCase()))return candidate}
}
const MAIN='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
function formulaCaches(xml:string,file:string,cacheTrusted=true):Map<string,string|number|boolean>{
 const values=new Map<string,string|number|boolean>(),parser=new SaxesParser({xmlns:true})
 let address='',type='',formula=false,cached=false,value='',inValue=false
 parser.on('opentag',tag=>{
  if(tag.uri!==MAIN)return
  const attr=(key:string)=>Object.values(tag.attributes).find(item=>item.local===key)?.value??''
  if(tag.local==='c'){address=attr('r');type=attr('t');formula=false;cached=false;value=''}
  if(tag.local==='f')formula=true
  if(tag.local==='v'){cached=true;inValue=true}
 })
 parser.on('text',text=>{if(inValue)value+=text})
 parser.on('closetag',tag=>{
  if(tag.uri!==MAIN)return
  if(tag.local==='v')inValue=false
  if(tag.local!=='c'||!formula)return
  const fail=()=>{throw new Error(`${file} 的 ${address} 公式缓存缺失或无法确认，请先在电子表格软件中计算并保存`)}
  if(!cacheTrusted)fail()
  if(!cached)fail()
  let result:string|number|boolean
  if(type==='str')result=value
  else if(type==='b'){if(!['0','1'].includes(value))fail();result=value==='1'}
  else if(!type||type==='n'){if(!value.trim()||!Number.isFinite(Number(value)))fail();result=Number(value)}
  else {fail();return}
  values.set(address,result)
 })
 parser.write(xml).close();return values
}

export async function createWorkbookMergePlan(targetBytes:Uint8Array,sources:readonly MergeWorkbookSource[]){
 if(!sources.length)throw new Error('请选择需要合并的工作簿')
 if(sources.length>20||sources.some(source=>source.bytes.length>32*1024*1024))throw new Error('一次最多合并20个文件，每个文件最多32 MiB')
 const target=await readWorkbook(targetBytes),taken=new Set(target.sheets.map(sheet=>sheet.name)),sheetNames:string[]=[],content:WorkbookOperation[]=[]
 let count=0
 for(const source of sources){
  const book=await readWorkbook(source.bytes),entries=await createBufferEntrySource(source.bytes)
  for(const sheet of book.sheets){
   const name=dedupeMergedSheetName(sheet.name,taken);taken.add(name);sheetNames.push(name)
   const sheetXml=await entries.readText(sheet.path),workbookXml=await entries.readText('xl/workbook.xml'),calcPr=workbookXml.match(/<calcPr\b[^>]*>/)?.[0]??'',cacheTrusted=calcPr!==''&&!/\bfullCalcOnLoad="(?:1|true)"|\bcalcMode="manual"|\bcalcCompleted="(?:0|false)"/.test(calcPr),caches=formulaCaches(sheetXml,source.name,cacheTrusted),edits:CellEdit[]=[]
   for(const [address,cell] of Object.entries(sheet.cells)){
    if(++count>100000)throw new Error('合并工作簿最多导入100000个单元格')
    const position=parseAddress(address),logical=logicalStyleOf(book.styles,book.styles.cellXfs[cell.styleIndex??0],book.themePalette)
    const style={...styleDelta(undefined,logical),...(logical?.vAlign==='middle'?{verticalAlignment:'center' as const}:{})}
    edits.push({sheetName:name,...position,writeValue:true,cell:{value:caches.has(address)?caches.get(address)!:cell.value},...(Object.keys(style).length?{style}:{})})
   }
   // 自闭合共享公式 follower 也可能仅出现在原始 XML 中。
   for(const [address,value] of caches)if(!sheet.cells[address])edits.push({sheetName:name,...parseAddress(address),writeValue:true,cell:{value}})
   content.push({kind:'applyCellEdits',edits})
   const widths=sheet.columns.filter(column=>column.width!==undefined&&!column.hidden).flatMap(column=>Array.from({length:column.end-column.start+1},(_,offset)=>({index:column.start+offset-1,widthChars:column.width!})))
   if(widths.length)content.push({kind:'applyColumnWidths',sheetName:name,entries:widths})
   const heights=sheet.rows.filter(row=>row.height!==undefined).map(row=>({index:row.row-1,heightPoints:row.height!}))
   if(heights.length)content.push({kind:'applyRowHeights',sheetName:name,entries:heights})
   if(sheet.merges.length)content.push({kind:'applySheetMerges',sheetName:name,ranges:sheet.merges})
  }
 }
 const operations:WorkbookOperation[]=[{kind:'applySheetEdits',plan:{renames:[],additions:sheetNames.map(name=>({name})),removals:[],order:[...target.sheets.map(sheet=>sheet.name),...sheetNames]}},...content]
 await applyWorkbookOperations(targetBytes,operations)
 return {operations,sheetNames,files:sources.length,importedSheets:sheetNames.length}
}
