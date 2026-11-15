/** Strict source-bound insertion through the pinned searchable-text writer. */
import {createHash} from 'node:crypto'
import {PDFArray,PDFDocument,PDFName,PDFNumber} from 'pdf-lib'
import {applySaveRequest} from '../src/main/save-pdf'
import {inspectTextObjects} from '../src/main/text-edit'
import {replacementMetrics} from './replace-text-layout'
import {insertedLineWidths} from './static-text-layout'
import {replyReferences} from './note-replies'

const hash=(bytes:Uint8Array|string)=>createHash('sha256').update(bytes).digest('hex')
export interface StaticTextOperation {
 kind:'insertText';sourceSha256:string;pageId:string;origin:[number,number]
 text:string;fontSize:number;color:[number,number,number];align:'left'|'center'|'right'
 font?:'arial'|'times'|'courier';bold?:boolean;italic?:boolean;lineLeading?:number
}
export function staticTextAvailability(document:PDFDocument) {
 try{
  if(document.isEncrypted||document.context.trailerInfo.Encrypt||document.catalog.has(PDFName.of('Perms'))||document.catalog.has(PDFName.of('AcroForm'))||replyReferences(document,false)===null)return {insertText:false,insertTextReason:'来源含保护、签名或表单，暂不支持插入静态文字'}
  for(const page of document.getPages()){
   const unit=page.node.getInheritableAttribute(PDFName.of('UserUnit'))
   if(unit!==undefined&&(!(unit instanceof PDFNumber)||unit.asNumber()!==1))return {insertText:false,insertTextReason:'来源含非默认页面单位，暂不支持插入静态文字'}
   if(![0,90,180,270].includes(page.getRotation().angle))return {insertText:false,insertTextReason:'来源页面旋转角度暂不支持插入静态文字'}
   const annotations=page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)
   if(annotations&&annotations.size()>0)return {insertText:false,insertTextReason:'来源含批注，暂不支持插入静态文字'}
   const box=page.getCropBox()
   if(![box.x,box.y,box.width,box.height].every(Number.isFinite)||box.width<=0||box.height<=0)return {insertText:false,insertTextReason:'来源页面裁切范围无效，暂不支持插入静态文字'}
  }
  return {insertText:true,insertTextReason:null}
 }catch{return {insertText:false,insertTextReason:'来源结构尚不能安全插入静态文字'}}
}
type InspectedText=Awaited<ReturnType<typeof inspectTextObjects>>
function addedText(before:InspectedText,output:InspectedText,pageIndex:number){
 const remaining=[...output[pageIndex]!]
 for(const old of before[pageIndex]!){const found=remaining.findIndex(item=>item.text.trimEnd()===old.text.trimEnd()&&Math.abs(item.fontSize-old.fontSize)<.05&&item.rect.every((value,i)=>Math.abs(value-old.rect[i]!)<.05));if(found>=0)remaining.splice(found,1)}
 return remaining
}
export function verifyStaticTextOutput(before:InspectedText,output:InspectedText,operation:Pick<StaticTextOperation,'text'|'origin'|'fontSize'|'lineLeading'|'font'|'bold'|'italic'>,pageIndex:number,geometry:{rotation:number;cropBox:{x:number;y:number;width:number;height:number};lineXOffsets?:number[];syntheticBold?:boolean[]}):string|null{
 if(output.length!==before.length)return 'pdf_insert_text_original_pages_changed'
 const near=(a:number,b:number)=>Math.abs(a-b)<.05
 for(const [index,originals]of before.entries()){
  const remaining=[...output[index]!]
  for(const old of originals){const found=remaining.findIndex(item=>item.text.trimEnd()===old.text.trimEnd()&&near(item.fontSize,old.fontSize)&&item.rect.every((value,i)=>near(value,old.rect[i]!)));if(found<0)return 'pdf_insert_text_original_text_or_geometry_changed';remaining.splice(found,1)}
  if(index!==pageIndex&&remaining.length)return 'pdf_insert_text_original_other_page_changed'
 }
 const added=addedText(before,output,pageIndex),lines=operation.text.split('\n').map((text,index)=>({text,index})).filter(line=>line.text.length)
 if(added.length!==lines.length||added.some((item,i)=>item.text.trimEnd()!==lines[i]!.text.trimEnd()))return 'pdf_insert_text_output_not_extractable'
 const size=operation.fontSize,leading=operation.lineLeading??size*1.2,axes=geometry.rotation===0?[1,0,0,1]:geometry.rotation===90?[0,1,-1,0]:geometry.rotation===180?[-1,0,0,-1]:[0,-1,1,0]
 for(const [index,inserted]of added.entries()){
  if(!near(inserted.fontSize,size))return 'pdf_insert_text_font_size_changed'
  const line=lines[index]!,offset=geometry.lineXOffsets?.[line.index]??0,drop=line.index*leading
  const x=operation.origin[0]+axes[0]!*offset-axes[2]!*drop,y=operation.origin[1]+axes[1]!*offset-axes[3]!*drop,[x1,y1,x2,y2]=inserted.rect
  const bounds=geometry.rotation===0?[x1-x,y1-y,x2-x,y2-y]:geometry.rotation===90?[y1-y,x-x2,y2-y,x-x1]:geometry.rotation===180?[x-x2,y-y2,x-x1,y-y1]:[y-y2,x1-x,y-y1,x2-x]
  const[a,b,c,d]=bounds
  if(a! < -size*.5||a!>size||c!<=a!||b! < -size||d!>size*1.5||d!<b!||Math.min(Math.abs(b!),Math.abs(d!))>size*.5)return 'pdf_insert_text_geometry_or_rotation_changed'
  const box=geometry.cropBox
  if(x1<box.x||y1<box.y||x2>box.x+box.width||y2>box.y+box.height)return 'pdf_insert_text_overflow_generated_bytes_retained'
  const face=inserted.fontName.replace(/^[A-Z]{6}\+/,'')
  if(operation.font&&!({arial:/Arial|LiberationSans/i,times:/Times|LiberationSerif/i,courier:/Courier|LiberationMono/i}[operation.font]).test(face))return 'pdf_insert_text_requested_font_fallback_generated_bytes_retained'
  if(operation.bold&&!/bold/i.test(face)&&!geometry.syntheticBold?.[index]||operation.italic&&!/italic|oblique/i.test(face))return 'pdf_insert_text_requested_style_fallback_generated_bytes_retained'
 }
 return null
}
function staticTextTarget(document:PDFDocument,operation:StaticTextOperation,sourceSha256:string){
 if(operation.sourceSha256!==sourceSha256)throw Error('PDF 来源摘要不匹配')
 const pageIndex=document.getPages().findIndex((_,index)=>operation.pageId===`sha256:${sourceSha256}:page:${index}`)
 if(pageIndex<0)throw Error('PDF 页面身份无效')
 const page=document.getPage(pageIndex),box=page.getCropBox(),[x,y]=operation.origin
 if(x<box.x||x>box.x+box.width||y<box.y||y>box.y+box.height)throw Error('插入文字基线起点超出来源裁切范围')
 return pageIndex
}

export async function insertStaticText(content:Uint8Array,operation:StaticTextOperation,expectedSha256:string){
 const sourceSha256=hash(content)
 if(expectedSha256!==sourceSha256||operation.sourceSha256!==sourceSha256)throw Error('PDF 来源摘要不匹配')
 const document=await PDFDocument.load(content,{updateMetadata:false})
 const availability=staticTextAvailability(document)
 if(!availability.insertText)throw Error(availability.insertTextReason!)
 const pageIndex=staticTextTarget(document,operation,sourceSha256)
 const page=document.getPage(pageIndex),box=page.getCropBox()
 const skip=(reason:string)=>({operationIndex:0,kind:'insertText' as const,pageId:operation.pageId,reason})
 let bytes=content,skippedOperations:ReturnType<typeof skip>[]=[]
 try{
  const before=await inspectTextObjects(content)
  const input={pageIndex,origin:operation.origin,text:operation.text,fontSize:operation.fontSize,color:operation.color.map(value=>Math.round(value*255)) as [number,number,number],font:operation.font,bold:operation.bold,italic:operation.italic,lineLeading:operation.lineLeading,align:operation.align,rotate:page.getRotation().angle}
  const write=(lineXOffsets?:number[])=>applySaveRequest(content,{path:'',markups:[],drawings:[],formValues:[],stamps:[],textInserts:[{...input,lineXOffsets}]})
  let result=await write()
  if(result.skippedTextInserts.length){
   skippedOperations=result.skippedTextInserts.map(item=>skip(item.reason))
  }else{
   bytes=result.bytes
   // A failed measurement or post-write review retains the generated actual bytes.
   try{
    let output=await inspectTextObjects(bytes),lineXOffsets:number[]|undefined
    if(operation.align!=='left'){
     const added=addedText(before,output,pageIndex),lines=operation.text.split('\n')
     if(added.map(item=>item.text.trimEnd()).join('\n')!==lines.filter(Boolean).map(line=>line.trimEnd()).join('\n'))throw Error('pdf_insert_text_measure_lines_changed')
     const logical=lines.filter(Boolean),widths=await insertedLineWidths(bytes,pageIndex,added.map((item,i)=>({...item,measureText:logical[i]!})));let index=0
     lineXOffsets=lines.map(line=>line?widths[index++]!*(operation.align==='center'?-.5:-1):0)
     result=await write(lineXOffsets)
     if(result.skippedTextInserts.length)throw Error(result.skippedTextInserts.map(item=>item.reason).join('; '))
     bytes=result.bytes;output=await inspectTextObjects(bytes)
    }
    const syntheticBold=operation.bold?(await replacementMetrics(bytes,pageIndex,addedText(before,output,pageIndex).map(item=>({...item,measureText:''})))).map(item=>item.boldPainted):undefined
    const reason=verifyStaticTextOutput(before,output,operation,pageIndex,{rotation:page.getRotation().angle,cropBox:box,lineXOffsets,syntheticBold})
    if(reason)skippedOperations=[skip(reason)]
   }catch(error){skippedOperations=[skip('pdf_insert_text_output_review_failed: '+(error instanceof Error?error.message:String(error)))]}
  }
 }catch(error){
  // A writer/resource failure leaves a readable original available to publication.
  skippedOperations=[skip(`pdf_insert_text_failed: ${error instanceof Error?error.message:String(error)}`)]
 }
 const outputSha256=hash(bytes),appliedOperationIndices=skippedOperations.length?[]:[0]
 return {bytes,sourceSha256,sha256:outputSha256,size:bytes.length,appliedOperationIndices,skippedOperations,previewDigest:hash(JSON.stringify({sourceSha256,operation,outputSha256,appliedOperationIndices,skippedOperations}))}
}

/** Read-only preflight against the immutable original, shared by mixed text batches. */
export async function staticTextTargets(content:Uint8Array,operations:StaticTextOperation[],expectedSha256:string){
 const sourceSha256=hash(content)
 if(expectedSha256!==sourceSha256)throw Error('PDF 来源摘要不匹配')
 const document=await PDFDocument.load(content,{updateMetadata:false}),availability=staticTextAvailability(document)
 if(!availability.insertText)throw Error(availability.insertTextReason!)
 return operations.map(operation=>staticTextTarget(document,operation,sourceSha256))
}

/** Validate every original identity before writing; only the server rebinds intermediate bytes. */
export async function insertStaticTexts(content:Uint8Array,operations:StaticTextOperation[],expectedSha256:string){
 if(operations.length===1)return insertStaticText(content,operations[0]!,expectedSha256)
 const sourceSha256=hash(content)
 if(expectedSha256!==sourceSha256)throw Error('PDF 来源摘要不匹配')
 const document=await PDFDocument.load(content,{updateMetadata:false}),availability=staticTextAvailability(document)
 if(!availability.insertText)throw Error(availability.insertTextReason!)
 const targets=operations.map(operation=>staticTextTarget(document,operation,sourceSha256))
 let bytes=content
 const appliedOperationIndices:number[]=[],skippedOperations:{operationIndex:number;kind:'insertText';pageId:string;reason:string}[]=[]
 for(const [index,operation]of operations.entries()){
  const intermediateSha256=hash(bytes),pageId=`sha256:${intermediateSha256}:page:${targets[index]}`
  try{
   const result=await insertStaticText(bytes,{...operation,sourceSha256:intermediateSha256,pageId},intermediateSha256)
   bytes=result.bytes
   if(result.appliedOperationIndices.includes(0))appliedOperationIndices.push(index)
   skippedOperations.push(...result.skippedOperations.map(skip=>({...skip,operationIndex:index,pageId:operation.pageId})))
  }catch(error){
   // Original input failures were rejected before writing. An intermediate
   // resource/load failure must not discard earlier generated text.
   skippedOperations.push({operationIndex:index,kind:'insertText',pageId:operation.pageId,reason:`pdf_insert_text_failed: ${error instanceof Error?error.message:String(error)}`})
  }
 }
 const outputSha256=hash(bytes)
 return {bytes,sourceSha256,sha256:outputSha256,size:bytes.length,appliedOperationIndices,skippedOperations,previewDigest:hash(JSON.stringify({sourceSha256,operations,outputSha256,appliedOperationIndices,skippedOperations}))}
}
