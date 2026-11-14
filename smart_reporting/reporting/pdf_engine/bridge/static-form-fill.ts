/** Static Fill Form: fixed source metadata + image-edit.ts content insertion (never AcroForm or Stamp). */
import {z} from 'zod'
import {createHash} from 'node:crypto'
import {PDFDict,PDFDocument,PDFName,PDFNumber,PDFSignature} from 'pdf-lib'
import {readStaticFormFills} from '../src/main/save-pdf'
import type {StaticFormFillRecord} from '../src/shared/ipc'
import {chainPdfium,loadPdfium,saveDoc,withDocument} from '../src/main/text-edit'
import {decodePngBgra,listExistingEngineImages,type ExistingEngineImage} from './existing-image-engine'
import {prepareMixedPng} from './mixed-png'
const rect=z.tuple([z.number().finite(),z.number().finite(),z.number().finite(),z.number().finite()])
const identity={sourceSha256:z.string().regex(/^[a-f0-9]{64}$/),pageId:z.string(),id:z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/),expectedImageSha256:z.string().regex(/^[a-f0-9]{64}$/).optional()}
export const setStaticFillSchema=z.object({kind:z.literal('setStaticFill'),...identity,fillKind:z.enum(['text','check','cross']),rect,image:z.string().max(6_000_000),text:z.string().trim().min(1).max(1000).optional(),fontSize:z.number().finite().min(6).max(72).optional(),color:z.string().regex(/^#[a-f0-9]{6}$/i).optional(),align:z.enum(['left','center','right']).optional()}).strict()
export const removeStaticFillSchema=z.object({kind:z.literal('removeStaticFill'),...identity,expectedImageSha256:z.string().regex(/^[a-f0-9]{64}$/)}).strict()
const near=(a:readonly number[],b:readonly number[])=>a.every((v,i)=>Math.abs(v-b[i]!)<.05)
export function staticFillAvailability(document:PDFDocument){
 const acro=document.catalog.lookupMaybe(PDFName.of('AcroForm'),PDFDict)
 const safe=!document.isEncrypted&&!document.context.trailerInfo.Encrypt&&!document.catalog.has(PDFName.of('Perms'))&&!acro?.has(PDFName.of('XFA'))&&!document.getForm().getFields().some(field=>field instanceof PDFSignature)&&document.getPages().every(page=>{const unit=page.node.get(PDFName.of('UserUnit'));return (!unit||unit instanceof PDFNumber&&unit.asNumber()===1)&&page.getRotation().angle%90===0})
 return {staticFill:safe,staticFillReason:safe?null:'来源含保护、签名、动态表单或非默认页面单位，暂不能安全添加静态填写'}
}
export async function inspectStaticFills(bytes:Uint8Array,images?:ExistingEngineImage[]){
 const records=await readStaticFormFills(bytes),document=await PDFDocument.load(bytes,{updateMetadata:false}),capabilities=staticFillAvailability(document)
 const targets=records.length?(images??await listExistingEngineImages(bytes)):[]
 const staticFormFills=records.map(record=>{
  const matching=targets.filter(image=>image.pageIndex===record.pageIndex&&near(image.rect,record.rect))
  const unique=records.filter(other=>other.id===record.id||other.pageIndex===record.pageIndex&&near(other.rect,record.rect)).length===1
  const editable=capabilities.staticFill&&unique&&matching.length===1&&matching[0]!.exclusive
  return {...record,editable,...(editable?{expectedImageSha256:matching[0]!.fingerprint}:{reason:'静态填写元数据与图像不能唯一匹配，仅保留显示，请核对原件'})}
 })
 return {staticFormFills,capabilities}
}
// GenOffice f8c17004 main/image-edit.ts imageMatrix, unchanged geometry.
function imageMatrix(rect:readonly number[],rotate:number):number[]{
 const [x1,y1,x2,y2]=rect as [number,number,number,number],w=x2-x1,h=y2-y1
 switch(((rotate%360)+360)%360){case 90:return [0,h,-w,0,x2,y1];case 180:return [-w,0,0,-h,x2,y2];case 270:return [0,-h,w,0,x1,y2];default:return [w,0,0,h,x1,y1]}
}
/** Only page-owned, uniquely fingerprinted fills are removed. Source images never use a rect-only match. */
export async function prepareStaticFills(bytes:Uint8Array,operations:Record<string,unknown>[],sourceSha256:string,rotations:{pageIndex:number;delta:number}[]){
 const model=await inspectStaticFills(bytes),document=await PDFDocument.load(bytes,{updateMetadata:false})
 const ops=operations.filter(op=>['setStaticFill','removeStaticFill'].includes(String(op.kind))).map(op=>op.kind==='setStaticFill'?setStaticFillSchema.parse(op):removeStaticFillSchema.parse(op))
 if(ops.length&&!model.capabilities.staticFill)throw Error(model.capabilities.staticFillReason!)
 const records:StaticFormFillRecord[]=model.staticFormFills.map(({editable,expectedImageSha256,reason,...record})=>record)
 const seen=new Set<string>(),budget={pixels:0,bytes:0}
 const plans=ops.map(op=>{
  if(op.sourceSha256!==sourceSha256||seen.has(op.id))throw Error('静态填写来源或重复身份无效')
  seen.add(op.id)
  const index=Number(op.pageId.match(new RegExp('^sha256:'+sourceSha256+':page:(\\d+)$'))?.[1])
  const page=document.getPages()[index];if(!page)throw Error('静态填写页面身份已过期')
  const saved=model.staticFormFills.find(record=>record.id===op.id)
  if(saved?(!saved.editable||saved.pageIndex!==index||saved.expectedImageSha256!==op.expectedImageSha256):op.expectedImageSha256!==undefined||op.kind==='removeStaticFill')throw Error('静态填写图像身份已变化，请重新打开修订')
  if(op.kind==='setStaticFill'){
   if(op.fillKind==='text'&&(!op.text||op.fontSize===undefined||!op.color||!op.align)||op.fillKind!=='text'&&[op.text,op.fontSize,op.align].some(v=>v!==undefined)||op.text&&/[\p{Cc}\p{Cf}\u2028\u2029]/u.test(op.text.replace(/\n/g,'')))throw Error('静态填写文字配置无效')
   const [x1,y1,x2,y2]=op.rect,box=page.getCropBox()
   if(x2-x1<3||y2-y1<3||x1<box.x||y1<box.y||x2>box.x+box.width||y2>box.y+box.height)throw Error('静态填写超出页面范围')
   prepareMixedPng(op.image,budget)
  }
  const position=records.findIndex(record=>record.id===op.id);if(position>=0)records.splice(position,1)
  if(op.kind==='setStaticFill')records.push({id:op.id,kind:op.fillKind,pageIndex:index,rect:op.rect,...(op.fillKind==='text'?{text:op.text,fontSize:op.fontSize,color:op.color,align:op.align}:{})})
  return {op,index,saved,rotation:page.getRotation().angle+rotations.filter(r=>r.pageIndex===index).reduce((sum,r)=>sum+r.delta,0)}
 })
 if(!plans.length)return {bytes,records}
 const output=await chainPdfium(async()=>{const m=await loadPdfium();return withDocument(m,bytes,doc=>{
  for(const plan of plans){
   const page=m._FPDF_LoadPage(doc,plan.index);if(!page)throw Error('静态填写页面无法读取')
   try{
    if(plan.saved){
     const pointers=[m._malloc(4),m._malloc(4),m._malloc(4),m._malloc(4)];let target=0
     try{for(let i=0;i<m._FPDFPage_CountObjects(page);i++){const obj=m._FPDFPage_GetObject(page,i);if(m._FPDFPageObj_GetType(obj)!==3||!m._FPDFPageObj_GetBounds(obj,...pointers as [number,number,number,number]))continue;const bounds=pointers.map(p=>m.HEAPF32[p>>2]!);if(near(bounds,plan.saved.rect)){if(target)throw Error('静态填写图像定位不唯一');target=obj}}}finally{for(const p of pointers)m._free(p)}
     if(!target||!m._FPDFPage_RemoveObject(page,target))throw Error('静态填写图像无法移除')
     m._FPDFPageObj_Destroy(target)
    }
    if(plan.op.kind==='setStaticFill'){
     const {width,height,bgra}=decodePngBgra(plan.op.image),buffer=m._malloc(bgra.length);m.HEAPU8.set(bgra,buffer)
     let bitmap=0,image=0
     try{bitmap=m._FPDFBitmap_CreateEx(width,height,4,buffer,width*4);image=m._FPDFPageObj_NewImageObj(doc);if(!bitmap||!image||!m._FPDFImageObj_SetBitmap(0,0,image,bitmap))throw Error('静态填写位图无法写入');const matrix=m._malloc(24);try{m.HEAPF32.set(imageMatrix(plan.op.rect,plan.rotation),matrix>>2);m._FPDFPageObj_SetMatrix(image,matrix)}finally{m._free(matrix)}m._FPDFPage_InsertObject(page,image);image=0}finally{if(image)m._FPDFPageObj_Destroy(image);if(bitmap)m._FPDFBitmap_Destroy(bitmap);m._free(buffer)}
    }
    if(!m._FPDFPage_GenerateContent(page))throw Error('静态填写页面内容无法生成')
   }finally{m._FPDF_ClosePage(page)}
  }
  return saveDoc(m,doc)
 })})
 return {bytes:output,records}
}
/** Review is advisory once bytes exist; fixed writer owns metadata remapping. */
export async function reviewStaticFills(bytes:Uint8Array,expected:StaticFormFillRecord[],operations:Record<string,unknown>[]=[]){
 try{
  const actual=await readStaticFormFills(bytes),images=await listExistingEngineImages(bytes)
  if(JSON.stringify(actual)!==JSON.stringify(expected))throw Error('静态填写元数据复读不一致')
  for(const record of actual){
   const matching=images.filter(image=>image.pageIndex===record.pageIndex&&near(image.rect,record.rect))
   if(matching.length!==1)throw Error('静态填写内容图像范围复读不一致')
   const op=operations.find(op=>op.kind==='setStaticFill'&&op.id===record.id)
   if(op){
    const {width,height,bgra}=decodePngBgra(String(op.image)),rgb=new Uint8Array(width*height*3)
    for(let i=0;i<width*height;i++){rgb[i*3]=bgra[i*4+2]!;rgb[i*3+1]=bgra[i*4+1]!;rgb[i*3+2]=bgra[i*4]!}
    const expectedPixels=createHash('sha256').update(JSON.stringify([width,height])).update(rgb).digest('hex')
    if(matching[0]!.width!==width||matching[0]!.height!==height||matching[0]!.pixelsSha256!==expectedPixels)throw Error('静态填写图像像素或尺寸复读不一致')
   }
  }
  return []
 }catch(error){return [{operationIndex:0,kind:'setStaticFill',fieldName:'',code:'pdf_static_fill_output_review_failed',message:'静态填写输出复核失败；实际生成 PDF 已保留，请人工核对：'+String(error)}]}
}
