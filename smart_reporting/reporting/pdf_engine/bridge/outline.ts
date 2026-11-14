import {PDFArray,PDFDict,PDFDocument,PDFHexString,PDFName,PDFNumber,PDFRef,PDFString} from 'pdf-lib'
import type {OutlineEntryInput} from '../src/shared/ipc'

export interface BookmarkNode {title:string;pageId:string;top:number|null;children:BookmarkNode[]}
const failure='来源书签含外部动作、无法解析的目标或异常树，保留原目录且不支持替换'
const pageId=(sha:string,index:number)=>`sha256:${sha}:page:${index}`
const text=(value:unknown)=>value instanceof PDFString||value instanceof PDFHexString?value.decodeText():value instanceof PDFName?value.decodeText():null

/** 与固定源 resolveOutlineForEdit 一样，只编辑能够完整解析为本文件页面的整棵树。 */
export function inspectPdfOutline(document:PDFDocument,sourceSha256:string,protectedSource=false) {
 const outline:BookmarkNode[]=[]
 try {
  if(protectedSource||document.isEncrypted||document.context.trailerInfo.Encrypt||document.catalog.has(PDFName.of('Perms')))throw Error(failure)
  const pages=document.getPages(),indices=new Map(pages.map((page,index)=>[String(page.ref),index]))
  const lookup=(raw:any)=>raw===undefined?undefined:document.context.lookup(raw)
  const destination=(raw:any,depth=0):PDFArray=>{
   if(depth>32)throw Error(failure)
   const value=lookup(raw)
   if(value instanceof PDFArray)return value
   if(value instanceof PDFDict)return destination(value.get(PDFName.of('D')),depth+1)
   const name=text(value);if(name===null)throw Error(failure)
   const old=document.catalog.lookupMaybe(PDFName.of('Dests'),PDFDict)?.get(PDFName.of(name))
   if(old!==undefined)return destination(old,depth+1)
   const names=document.catalog.lookupMaybe(PDFName.of('Names'),PDFDict)?.get(PDFName.of('Dests'))
   const seen=new Set<PDFDict>()
   const find=(node:any,level=0):any=>{
    const tree=lookup(node);if(!(tree instanceof PDFDict)||seen.has(tree)||level>32||seen.size>2000)throw Error(failure)
    seen.add(tree)
    const pairs=tree.lookupMaybe(PDFName.of('Names'),PDFArray)
    if(pairs){if(pairs.size()%2||pairs.size()>4000)throw Error(failure);for(let i=0;i<pairs.size();i+=2)if(text(pairs.lookup(i))===name)return pairs.get(i+1)}
    const kids=tree.lookupMaybe(PDFName.of('Kids'),PDFArray)
    if(kids)for(const child of kids.asArray()){const match=find(child,level+1);if(match!==undefined)return match}
   }
   const target=names===undefined?undefined:find(names)
   if(target===undefined)throw Error(failure)
   return destination(target,depth+1)
  }
  const visited=new Set<PDFDict>()
  const walk=(raw:any,depth:number):BookmarkNode[]=>{
   if(depth>32)throw Error(failure)
   const result:BookmarkNode[]=[]
   while(raw!==undefined){
    const node=lookup(raw)
    if(!(node instanceof PDFDict)||visited.has(node)||visited.size>=2000)throw Error(failure)
    visited.add(node)
    const title=text(node.lookup(PDFName.of('Title')))
    if(title===null||!title.trim()||title.length>4000)throw Error(failure)
    const action=node.lookupMaybe(PDFName.of('A'),PDFDict)
    if(action&&String(action.get(PDFName.of('S')))!=='/GoTo')throw Error(failure)
    const target=destination(node.get(PDFName.of('Dest'))??action?.get(PDFName.of('D')))
    const ref=target.get(0),index=ref instanceof PDFRef?indices.get(String(ref)):ref instanceof PDFNumber?ref.asNumber():undefined
    if(index===undefined||!Number.isInteger(index)||index<0||index>=pages.length)throw Error(failure)
    const kind=String(target.get(1)),offset=kind==='/XYZ'?3:kind==='/FitH'||kind==='/FitBH'?2:-1,value=offset>=0?target.lookup(offset):undefined
    const top=value instanceof PDFNumber?value.asNumber():null
    if(top!==null&&!Number.isFinite(top))throw Error(failure)
    result.push({title,pageId:pageId(sourceSha256,index),top,children:node.has(PDFName.of('First'))?walk(node.get(PDFName.of('First')),depth+1):[]})
    raw=node.get(PDFName.of('Next'))
   }
   return result
  }
  const root=document.catalog.lookupMaybe(PDFName.of('Outlines'),PDFDict)
  if(root)outline.push(...walk(root.get(PDFName.of('First')),0))
  return {outline,outlineEditable:true,outlineReason:null as string|null}
 } catch {return {outline:[] as BookmarkNode[],outlineEditable:false,outlineReason:failure}}
}

export function outlineWriteRequest(tree:unknown[],pages:{pageId:string;index:number}[],blankIndex:Map<string,number>,deleted:Set<string>):OutlineEntryInput[] {
 const indices=new Map([...pages.map(page=>[page.pageId,page.index] as const),...blankIndex.entries()])
 let count=0
 const walk=(items:unknown[],depth:number):OutlineEntryInput[]=>{
  if(depth>32||!Array.isArray(items))throw Error('书签层级无效')
  const result:OutlineEntryInput[]=[]
  for(const raw of items){
   const node=raw as BookmarkNode
   if(++count>2000||!node||typeof node!=='object'||Object.keys(node).some(key=>!['title','pageId','top','children'].includes(key))||typeof node.title!=='string'||!node.title.trim()||node.title.length>4000||typeof node.pageId!=='string'||!indices.has(node.pageId)||node.top!==null&&(typeof node.top!=='number'||!Number.isFinite(node.top))||!Array.isArray(node.children))throw Error('书签标题、页面身份或树无效')
   const children=walk(node.children,depth+1)
   if(!deleted.has(node.pageId))result.push({title:node.title.trim(),pageIndex:indices.get(node.pageId)!,top:node.top,children})
  }
  return result
 }
 // 先按不可变页身份裁掉已删除目标，空结果明确表示无书签，避免遗留悬空 /Dest。
 return walk(tree,0)
}

/** 生成后的读回只产生告警；实际 PDF 必须沿现有链保留并可下载。 */
export async function reviewPdfOutline(bytes:Uint8Array,expected:OutlineEntryInput[],finalOrder:number[],sourceSha256:string,operationIndex:number) {
 try {
  const actual=inspectPdfOutline(await PDFDocument.load(bytes,{updateMetadata:false}),sourceSha256)
  const canonical=(entries:OutlineEntryInput[]):BookmarkNode[]=>entries.map(node=>({title:node.title.trim(),pageId:pageId(sourceSha256,finalOrder.indexOf(node.pageIndex)),top:typeof node.top==='number'?Math.round(node.top*100)/100:null,children:canonical(node.children??[])}))
  if(!actual.outlineEditable||JSON.stringify(actual.outline)!==JSON.stringify(canonical(expected)))throw Error('实际书签树或页面目标与草稿不一致')
  return []
 } catch(error){return [{operationIndex,kind:'setOutline',fieldName:'',code:'pdf_outline_output_review_failed',message:'书签写入后的独立结构复核失败；已保留实际生成文件，请人工核对：'+String(error)}]}
}
