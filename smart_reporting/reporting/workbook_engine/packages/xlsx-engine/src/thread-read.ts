import { SaxesParser } from 'saxes'
import { sha256Hex } from './sha256'
import { decodeXmlText, readXmlAttribute } from './xml'
import { decodeXlsxEscapes } from './xlsx-escapes'
import type { EntrySource } from './zip'
import type { SheetThread } from './thread-write-source'

export interface CellThread extends SheetThread { row: number; column: number; text: string }
export interface SheetThreadsModel { threads: CellThread[]; sourceIdentity: string; readOnlyReason?: string }
export const THREAD_REL = 'http://schemas.microsoft.com/office/2017/10/relationships/threadedComment'
export const PERSON_REL = 'http://schemas.microsoft.com/office/2017/10/relationships/person'
export function threadTargetPath(from: string, target: string): string {
  if (target.includes('\\') || /[?#:%]/.test(target)) throw new Error('线程批注关系路径无效')
  const parts = target.startsWith('/') ? [] : from.split('/').slice(0, -1)
  for (const p of target.split('/')) {
    if (p === '..') { if (!parts.pop()) throw new Error('线程批注关系越界') }
    else if (p && p !== '.') parts.push(p)
  }
  const path = parts.join('/')
  if (!path.startsWith('xl/')) throw new Error('线程批注关系越界')
  return path
}
export function threadAddress(row: number, column: number): string {
  let label = ''
  for (let n = column; n >= 0; n = Math.floor(n / 26) - 1) label = String.fromCharCode(65 + n % 26) + label
  return `${label}${row + 1}`
}
function position(ref: string): {row: number; column: number} {
  const m = ref.match(/^([A-Z]{1,3})([1-9]\d{0,6})$/)
  if (!m) throw new Error('线程批注坐标无效')
  let column = 0; for (const c of m[1]!) column = column * 26 + c.charCodeAt(0) - 64
  const row = Number(m[2]) - 1; column--
  if (row > 1048575 || column > 16383) throw new Error('线程批注坐标越界')
  return {row,column}
}
const THREAD_NS = 'http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments'
function assertThreadXml(xml: string, root: 'ThreadedComments'|'personList'): void {
  if(/(?:^|\s)[\w:]+='/.test(xml))throw new Error('线程批注属性序列化形式仅可保留')
  const parser = new SaxesParser({xmlns:true}), stack:string[] = []
  const child = root === 'personList' ? 'person' : 'threadedComment'
  const attrs:Record<string,string[]> = {ThreadedComments:[],personList:[],person:['displayName','id','userId','providerId'],threadedComment:['ref','dT','personId','id','parentId','done'],text:['space']}
  parser.on('doctype',()=>{throw new Error('线程批注不支持DOCTYPE')})
  parser.on('opentag',t=>{
    const parent=stack.at(-1)
    if(t.prefix || t.uri!==THREAD_NS || (!parent ? t.local!==root : parent===root ? t.local!==child : parent==='threadedComment' ? t.local!=='text' : true))throw new Error('线程批注命名空间或扩展结构无法保真编辑')
    for(const a of Object.values(t.attributes))if(a.uri!=='http://www.w3.org/2000/xmlns/' && (!(attrs[t.local]??[]).includes(a.local) || (a.prefix && !(t.local==='text'&&a.local==='space'&&a.uri==='http://www.w3.org/XML/1998/namespace'))))throw new Error('线程批注扩展属性无法保真编辑')
    stack.push(t.local)
  })
  parser.on('closetag',()=>{stack.pop()})
  parser.write(xml).close()
}
export async function assertSheetThreadsStationary(bytes:Uint8Array,sheetName:string):Promise<void> {
  const {createBufferEntrySource}=await import('./zip'), {parseSheetElements,resolveWorksheetPath}=await import('./workbook-read')
  const source=await createBufferEntrySource(bytes), sheet=parseSheetElements(await source.readText('xl/workbook.xml')).find(s=>s.name===sheetName)
  if(!sheet?.relationshipId)return
  const rel=await threadRelationship(source,await resolveWorksheetPath(source,sheet.relationshipId),THREAD_REL)
  if(rel.path)throw new Error('含线程批注的工作表暂不支持排序或移动行列及单元格，请保留批注位置')
}
export async function threadRelationship(source: EntrySource, from: string, type: string): Promise<{rels: string; relsPath: string; path?: string}> {
  const relsPath = from.replace(/\/([^/]+)$/, '/_rels/$1.rels')
  const rels = await source.has(relsPath) ? await source.readText(relsPath) : ''
  if(rels){
    const parser=new SaxesParser({xmlns:true});let depth=0
    parser.on('doctype',()=>{throw new Error('线程批注关系不支持DOCTYPE')})
    parser.on('opentag',t=>{depth++;if(t.prefix||t.uri!=='http://schemas.openxmlformats.org/package/2006/relationships'||(depth===1?t.local!=='Relationships':depth!==2||t.local!=='Relationship'))throw new Error('线程批注关系命名空间无效')})
    parser.on('closetag',()=>{depth--});parser.write(rels).close()
    if(/(?:^|\s)[\w:]+='/.test(rels))throw new Error('线程批注关系属性序列化形式仅可保留')
  }
  const matches = [...rels.matchAll(/<Relationship\b[^>]*\/?\s*>/g)].map(m => m[0]).filter(r => readXmlAttribute(r,'Type') === type)
  if (matches.length > 1) throw new Error('线程批注关系重复')
  const rel = matches[0]
  if (!rel) return {rels,relsPath}
  const target = readXmlAttribute(rel,'Target')
  if (!target || readXmlAttribute(rel,'TargetMode')) throw new Error('线程批注外部关系不支持编辑')
  return {rels,relsPath,path:threadTargetPath(from,decodeXmlText(target))}
}
export async function readSheetThreads(source: EntrySource, path: string): Promise<SheetThreadsModel> {
  const result: SheetThreadsModel = {threads:[],sourceIdentity:''}
  try {
    const sheet = await source.readText(path)
    const rel = await threadRelationship(source,path,THREAD_REL)
    const people = await threadRelationship(source,'xl/workbook.xml',PERSON_REL)
    const xml = rel.path ? await source.readText(rel.path) : ''
    const persons = people.path ? await source.readText(people.path) : ''
    result.sourceIdentity = sha256Hex(JSON.stringify([path,sheet,rel.rels,xml,people.rels,persons]))
    if (/<sheetProtection\b/.test(sheet)) throw new Error('受保护工作表暂不支持线程批注编辑')
    if (xml.length + persons.length > 2 * 1024 * 1024) throw new Error('线程批注超过预算')
    if (xml) assertThreadXml(xml,'ThreadedComments')
    if (persons) assertThreadXml(persons,'personList')
    if (/<(?:mentions|mention|extLst)\b/.test(xml + persons)) throw new Error('带提及或扩展的线程批注仅可保留')
    const authors = new Map<string,string>()
    for (const m of persons.matchAll(/<person\b[^>]*\/?\s*>/g)) {
      const id = readXmlAttribute(m[0],'id'), author = readXmlAttribute(m[0],'displayName')
      if (!id || author === undefined || authors.has(id)) throw new Error('线程批注人物身份无效')
      authors.set(id,decodeXmlText(author))
    }
    const entries = new Map<string,{id:string;personId:string;author:string;dT:string;text:string;parentId?:string|undefined;done:boolean;ref:string}>()
    let total = 0
    for (const m of xml.matchAll(/<threadedComment\b([^>]*)(?:\/>|>([\s\S]*?)<\/threadedComment>)/g)) {
      const a = m[1]!, body = m[2] ?? ''
      const id = readXmlAttribute(a,'id'), personId = readXmlAttribute(a,'personId'), dT = readXmlAttribute(a,'dT'), ref = readXmlAttribute(a,'ref')
      const textXml = body.match(/^\s*<text(?:\s+xml:space="preserve")?>([\s\S]*?)<\/text>\s*$/)?.[1]
      if (!id || !personId || !authors.has(personId) || !dT || !ref || entries.has(id) || textXml === undefined || /</.test(textXml)) throw new Error('线程批注结构或作者无法保真编辑')
      position(ref)
      const text = decodeXlsxEscapes(decodeXmlText(textXml)); total += text.length
      if (text.length > 32767 || total > 1024 * 1024 || entries.size >= 1000) throw new Error('线程批注超出文本或数量预算')
      entries.set(id,{id,personId,author:authors.get(personId)!,dT,ref,text,parentId:readXmlAttribute(a,'parentId'),done:['1','true'].includes(readXmlAttribute(a,'done')??'0')})
    }
    const roots = new Map<string,CellThread>()
    for (const e of entries.values()) if (!e.parentId) {
      if (roots.has(e.ref)) throw new Error('同一单元格有重复线程')
      const {ref,parentId,...root} = e
      const thread = {...root,...position(ref),replies:[]}; roots.set(ref,thread); result.threads.push(thread)
    }
    for (const e of entries.values()) if (e.parentId) {
      const root = roots.get(e.ref)
      if (!root || root.id !== e.parentId) throw new Error('线程回复父身份不匹配')
      const {ref,parentId,done,...reply} = e
      ;(root.replies as typeof reply[]).push(reply)
    }
  } catch(error) { result.readOnlyReason = (error as Error).message }
  return result
}
