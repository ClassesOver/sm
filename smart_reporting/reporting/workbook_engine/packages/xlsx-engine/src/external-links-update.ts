// 只展开用户明确授权的工作簿值；计算交给现有 Univer 引擎。
import { z } from 'zod'
import { createBufferEntrySource, assemblePackage, assertOnlyTouchedEntriesChanged } from './zip'
import { readExternalLinks } from './external-links'
import { readWorkbook } from './workbook-read'
import { decodeXmlText, escapeXmlText, readXmlAttribute } from './xml'
import { parseAddress, formatAddress } from './cell-address'

export interface ExternalUpdateCandidate { sheetName:string; address:string; formula:string; expression:string }
export async function prepareExternalLinkUpdate(bytes:Uint8Array, authorized:readonly {index:number;expectedTarget:string;bytes:Uint8Array}[]) {
 const source=await createBufferEntrySource(bytes), links=await readExternalLinks(source), models=new Map<number,Awaited<ReturnType<typeof readWorkbook>>>()
 for(const file of authorized){if(!links.some(link=>link.index===file.index&&link.rawTarget===file.expectedTarget))throw new Error('外链来源已变化');models.set(file.index,await readWorkbook(file.bytes))}
 const model=await readWorkbook(bytes),candidates:ExternalUpdateCandidate[]=[],skipped:{sheetName:string;address:string;reason:string}[]=[]
 for(const sheet of model.sheets){
  const xml=await source.readText(sheet.path)
  for(const cell of xml.matchAll(/<c\b([^>]*)>([\s\S]*?)<\/c>/g)){
   const address=readXmlAttribute(cell[1]!, 'r'),body=cell[2]!,f=body.match(/<f\b([^>]*)>([\s\S]*?)<\/f>/)
   if(!address||!f||!f[2]?.includes('['))continue
   const formula=decodeXmlText(f[2]),base={sheetName:sheet.name,address};let reason=''
   if(/\bt="(?:shared|array|dataTable)"/.test(f[1]!))reason='共享或数组外链公式保留缓存'
   // 引号字符串不能被当成外链引用替换。
   const segments=formula.split(/("(?:[^"]|"")*")/g)
   if (!segments.some((segment, index) => index % 2 === 0 && /\[[0-9]+\]/.test(segment))) continue
   const rewritten=segments.map((segment,position)=>position%2?segment:segment.replace(/(?:'\[(\d+)\]((?:[^']|'')+)'|\[(\d+)\]([^\s!(),;"'^&*<>=+\-*/[\]]+))!([$]?[A-Z]{1,3}[$]?[1-9][0-9]*(?::[$]?[A-Z]{1,3}[$]?[1-9][0-9]*)?)/g,(_all,a:string,quoted:string,b:string,bare:string,ref:string)=>{
    const sourceModel=models.get(Number(a??b));if(!sourceModel){reason='来源未授权选择，保留缓存';return _all}
    const target=sourceModel.sheets.find(item=>item.name.toLowerCase()===(quoted?.replaceAll("''", "'")??bare).toLowerCase());if(!target){reason='授权来源缺少工作表，保留缓存';return _all}
    const [start,end=start]=ref.replaceAll('$','').split(':'),first=parseAddress(start!),last=parseAddress(end!),count=(last.row-first.row+1)*(last.column-first.column+1)
    if(count<1||count>10000){reason='外链范围超出更新上限';return _all}
    const rows:string[]=[]
    for(let row=first.row;row<=last.row;row++){
     const values:string[]=[]
     for(let column=first.column;column<=last.column;column++){
      const value=target.cells[formatAddress(row,column)]
      if(value?.formula){reason='来源单元格含未受控重算的公式，保留缓存';return _all}
      values.push(value?.value===null||value===undefined?'0':typeof value.value==='number'?String(value.value):typeof value.value==='boolean'?(value.value?'TRUE':'FALSE'):'"'+String(value.value).replaceAll('"','""')+'"')
     }
     rows.push(values.join(','))
    }
    return count===1?rows[0]!:'{'+rows.join(';')+'}'
   })).join('')
   if(rewritten.includes('['))reason=reason||'外部名称或不支持的外链引用，保留缓存'
   if(/\b(?:OFFSET|INDIRECT|ROW|COLUMN|CELL|INFO|WEBSERVICE|HYPERLINK)\s*\(/i.test(rewritten))reason='引用形状或外部访问函数不支持安全更新，保留缓存'
   if(reason)skipped.push({...base,reason});else if(rewritten!==formula)candidates.push({...base,formula,expression:'='+rewritten})
  }
 }
 return {candidates,skipped}
}
const updateSchema=z.object({kind:z.literal('updateExternalLinkCaches'),updates:z.array(z.object({sheetName:z.string().min(1).max(31),address:z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}$/),formula:z.string().min(1).max(8192),value:z.union([z.number().finite(),z.string().max(32767),z.boolean()])}).strict()).min(1).max(10000)}).strict()
export async function applyExternalLinkCaches(bytes:Uint8Array,raw:unknown){
 const {updates}=updateSchema.parse(raw),source=await createBufferEntrySource(bytes),model=await readWorkbook(bytes),replaced=new Map<string,string>(),seen=new Set<string>()
 for(const update of updates){
  const sheet=model.sheets.find(item=>item.name===update.sheetName),key=update.sheetName+'!'+update.address
  if (sheet?.protection?.protected) throw new Error('外链公式所在工作表受保护')
  if(!sheet||seen.has(key)||!update.formula.includes('['))throw new Error('外链公式目标身份无效');seen.add(key)
  let matched=false
  const xml=(replaced.get(sheet.path)??await source.readText(sheet.path)).replace(/<c\b([^>]*)>([\s\S]*?)<\/c>/g,(all,attributes:string,body:string)=>{
   if(readXmlAttribute(attributes,'r')!==update.address)return all
   const f=body.match(/<f\b[^>]*>([\s\S]*?)<\/f>/)
   if(!f||decodeXmlText(f[1]!)!==update.formula)throw new Error('外链公式已变化，缓存未写入')
   matched=true
   const type=typeof update.value==='string'?'str':typeof update.value==='boolean'?'b':null
   const attrs=attributes.replace(/\s+t="[^"]*"/g,'')+(type?' t="'+type+'"':'')
   const value=typeof update.value==='boolean'?(update.value?'1':'0'):escapeXmlText(String(update.value))
   return '<c'+attrs+'>'+body.replace(/<v\b[^>]*>[\s\S]*?<\/v>/g,'')+'<v>'+value+'</v></c>'
  })
  if(!matched)throw new Error('外链公式目标已变化');replaced.set(sheet.path,xml)
 }
 const mutation=await assemblePackage(bytes,{replaced,added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[...replaced.keys()]});assertOnlyTouchedEntriesChanged(mutation);return mutation.buffer
}
