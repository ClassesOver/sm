import {ICommandService} from '@univerjs/core'
import {createBufferEntrySource} from '@sheets-web/xlsx-engine/zip'
import {readExternalLinks} from '@sheets-web/xlsx-engine/external-links'
import {readExternalSource,type ExternalSourceBinding} from '@sheets-web/xlsx-engine/external-links-source'
import {prepareExternalLinkUpdate,type ExternalUpdateCandidate} from '@sheets-web/xlsx-engine/external-links-update'
import {parseAddress} from '@sheets-web/xlsx-engine/cell-address'
import type {ExternalLinksSnapshot} from './workbook-external-links'
export interface ExternalLinksContext extends ExternalLinksSnapshot{bytes:Uint8Array;operations:Record<string,unknown>[]}
export async function externalLinksContext(bytes:Uint8Array,operations:Record<string,unknown>[],key:string):Promise<ExternalLinksContext>{
 let bindings:ExternalSourceBinding[]=[]
 for(const operation of operations){
  if(operation.kind==='bindExternalLinkSource')bindings=[...bindings.filter(item=>item.index!==operation.index),operation as unknown as ExternalSourceBinding]
  if(operation.kind==='retargetExternalLink')bindings=bindings.filter(item=>item.index!==operation.index)
  if(operation.kind==='breakExternalLink')bindings=bindings.filter(item=>item.index!==operation.index).map(item=>item.index>Number(operation.index)?{...item,index:item.index-1}:item)
 }
 const links=await readExternalLinks(await createBufferEntrySource(bytes))
 return {key,bytes,operations,links,bindings:bindings.filter(binding=>links.some(link=>link.index===binding.index&&link.rawTarget===binding.expectedTarget))}
}
export async function calculateExternalUpdates(context:ExternalLinksContext,evaluate:(candidate:ExternalUpdateCandidate)=>Promise<unknown>,current:()=>boolean){
 const authorized=[]
 for(const raw of context.bindings){const file=await readExternalSource(raw);if(!current())throw new Error('外链来源已变化');authorized.push({index:file.binding.index,expectedTarget:file.binding.expectedTarget,bytes:file.bytes})}
 const prepared=await prepareExternalLinkUpdate(context.bytes,authorized),updates:{sheetName:string;address:string;formula:string;value:string|number|boolean}[]=[],skipped=[...prepared.skipped]
 for(const candidate of prepared.candidates){
  if(!current())throw new Error('工作簿或草稿已变化')
  try{
   const value=await evaluate(candidate)
   if(!current())throw new Error('工作簿或草稿已变化')
   if(typeof value!=='string'&&typeof value!=='number'&&typeof value!=='boolean'||typeof value==='number'&&!Number.isFinite(value)||typeof value==='string'&&/^#(?:REF!|VALUE!|NAME\?|N\/A|ERROR!|DIV\/0!|NUM!|SPILL!)/.test(value))throw new Error('公式引擎未返回可用标量，保留原缓存')
   updates.push({sheetName:candidate.sheetName,address:candidate.address,formula:candidate.formula,value})
  }catch(error){if(!current())throw error;skipped.push({sheetName:candidate.sheetName,address:candidate.address,reason:(error as Error).message})}
 }
 return {operation:updates.length?{kind:'updateExternalLinkCaches',updates}:null,message:'已更新 '+updates.length+' 个值；'+skipped.length+' 个未更新。'+skipped.slice(0,8).map(item=>item.sheetName+'!'+item.address+'：'+item.reason).join('；')}
}
export async function evaluateExternalFormula(runtime:any,candidate:ExternalUpdateCandidate){
 const book=runtime.univerAPI.getActiveWorkbook(),sheet=book?.getSheets().find((item:any)=>item.getSheetName()===candidate.sheetName)
 if(!book||!sheet)throw new Error('外链工作表已变化')
 const point=parseAddress(candidate.address),unitId=book.getId(),sheetId=sheet.getSheetId()
 const result=await runtime.univerAPI.getFormula().executeFormulas({[unitId]:{[sheetId]:{[point.row]:{[point.column]:[candidate.expression]}}}},3000)
 return result[unitId]?.[sheetId]?.[point.row]?.[point.column]?.find((item:any)=>item.formula===candidate.expression)?.value
}

// 外链公式原文仍由 facade 读回；其值保留文件缓存，避免不支持的跨文件计算覆盖为 #REF!。
export async function withExternalFormulaCaches(bytes:Uint8Array,data:{sheets:Record<string,any>}){
 const source=await createBufferEntrySource(bytes),{readWorkbook}=await import('@sheets-web/xlsx-engine/workbook-read'),{readXmlAttribute,decodeXmlText}=await import('@sheets-web/xlsx-engine/xml'),model=await readWorkbook(bytes)
 for(const sheet of model.sheets){
  const target=Object.values(data.sheets).find(item=>item.name===sheet.name);if(!target)continue
  for(const match of (await source.readText(sheet.path)).matchAll(/<c\b([^>]*)>([\s\S]*?)<\/c>/g)){
   const address=readXmlAttribute(match[1]!,'r'),formula=match[2]!.match(/<f\b[^>]*>([\s\S]*?)<\/f>/)?.[1],cached=match[2]!.match(/<v\b[^>]*>([\s\S]*?)<\/v>/)?.[1]
   if(!address||!formula || !/\[[0-9]+\]/.test(formula)||cached===undefined)continue
   const point=parseAddress(address),cell=target.cellData[point.row]?.[point.column];if(!cell)continue
   const kind=readXmlAttribute(match[1]!,'t'),value=kind==='b'?cached==='1':kind==='str'||kind==='e'?decodeXmlText(cached):Number(cached)
   if(typeof value==='number'&&!Number.isFinite(value))continue
   cell.v=value;cell.t=kind==='b'?3:kind==='e'?4:typeof value==='string'?1:2
  }
 }
 return data
}

export function installExternalFormulaCaches(runtime:any){
 const commands=runtime.univer.__getInjector().get(ICommandService)
 const subscription=commands.beforeCommandExecuted((command:any)=>{
  if(command.id!=='formula.mutation.set-formula-calculation-result')return
  const book=runtime.univerAPI.getActiveWorkbook(),data=command.params?.unitData?.[book?.getId()];if(!book||!data)return
  for(const [sheetId,rows] of Object.entries(data)){
   const sheet=book.getSheetBySheetId(sheetId)?.getSheet();if(!sheet||!rows)continue
   for(const [row,columns] of Object.entries(rows as Record<string,any>))for(const [column,value] of Object.entries(columns as Record<string,any>)){
    const cell=sheet.getCell(Number(row),Number(column))
    if(typeof cell?.f === 'string' && /\[[0-9]+\]/.test(cell.f)&&(typeof cell.v==='number'||typeof cell.v==='string'||typeof cell.v==='boolean'))(columns as Record<string,any>)[column]={...(value as object),v:cell.v,t:cell.t}
   }
  }
 })
 return {dispose:()=>subscription.dispose()}
}
