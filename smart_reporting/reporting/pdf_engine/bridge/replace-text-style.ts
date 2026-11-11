/** Whole-object styling/multiline through the pinned GenOffice paragraph rebuild path. */
import {createHash} from 'node:crypto'
import {PDFDocument} from 'pdf-lib'
import {applyTextEdits,inspectTextObjects,validateTextEdits} from '../src/main/text-edit'
import type {TextEditInput} from '../src/shared/ipc'
import {inspectNativeText} from './text-operations'
import {validateTextStyleRuns,nativeTextStyleRuns,expectedTextSegments,type PdfTextStyleRun} from './replace-text-runs'
import {replacementMetrics} from './replace-text-layout'
const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
export interface StyledReplaceTextOperation{
 kind:'replaceText';sourceSha256:string;pageId:string;objectId:string;expectedTextSha256:string;newText:string
 font?:'arial'|'times'|'courier';fontSize?:number;color?:[number,number,number];bold?:boolean;italic?:boolean
 align?:'left'|'center'|'right';lineLeading?:number;styleRuns?:PdfTextStyleRun[]
}
type Objects=Awaited<ReturnType<typeof inspectTextObjects>>
type Plan={index:number;operation:StyledReplaceTextOperation;pageIndex:number;targetIndex:number;edit:TextEditInput;origin:[number,number];size:number;leading:number;offsets?:number[]}
const near=(a:number,b:number)=>Math.abs(a-b)<.05
function validOptions(operation:StyledReplaceTextOperation){
 validateTextStyleRuns(operation.newText,operation.styleRuns)
 if(typeof operation.newText!=='string'||operation.newText.length>4000||/[\p{Cc}\p{Cf}\u2028\u2029]/u.test(operation.newText.replace(/\n/g,'')))throw Error('PDF 替换文字含不支持的字符')
 if(operation.font!==undefined&&!['arial','times','courier'].includes(operation.font))throw Error('PDF 替换字体无效')
 if(operation.fontSize!==undefined&&(!Number.isFinite(operation.fontSize)||operation.fontSize<6||operation.fontSize>72))throw Error('PDF 替换字号须为6–72')
 if(operation.color!==undefined&&(!Array.isArray(operation.color)||operation.color.length!==3||operation.color.some(value=>!Number.isFinite(value)||value<0||value>1)))throw Error('PDF 替换颜色无效')
 if(operation.bold!==undefined&&typeof operation.bold!=='boolean'||operation.italic!==undefined&&typeof operation.italic!=='boolean')throw Error('PDF 替换样式无效')
 if(operation.align!==undefined&&!['left','center','right'].includes(operation.align))throw Error('PDF 替换对齐无效')
 if(operation.lineLeading!==undefined&&(!Number.isFinite(operation.lineLeading)||operation.lineLeading<=0))throw Error('PDF 替换行距须为正数')
}
function addedObjects(before:Objects,after:Objects,plans:Plan[]){
 if(before.length!==after.length)throw Error('pdf_text_style_original_pages_changed')
 return before.map((objects,pageIndex)=>{
  const remaining=[...after[pageIndex]!]
  for(const [index,old]of objects.entries()){
   if(plans.some(plan=>plan.pageIndex===pageIndex&&plan.targetIndex===index))continue
   const found=remaining.findIndex(item=>item.text.trimEnd()===old.text.trimEnd()&&near(item.fontSize,old.fontSize)&&item.fontName===old.fontName&&item.fontSha256===old.fontSha256&&item.rect.every((value,i)=>near(value,old.rect[i]!)))
   if(found<0)throw Error('pdf_text_style_original_text_or_geometry_changed')
   remaining.splice(found,1)
  }
  return remaining
 })
}
async function groupedOutput(bytes:Uint8Array,before:Objects,plans:Plan[]){
 const after=await inspectTextObjects(bytes),added=addedObjects(before,after,plans),groups=new Map<number,{object:Objects[number][number];metric:Awaited<ReturnType<typeof replacementMetrics>>[number];lineIndex:number;style:ReturnType<typeof expectedTextSegments>[number][number]['style']}[]>()
 for(const [pageIndex,objects]of added.entries()){
  if(!objects.length)continue
  const metrics=await replacementMetrics(bytes,pageIndex,objects.map(object=>({...object,measureText:''}))),used=new Set<number>()
  for(const plan of plans.filter(item=>item.pageIndex===pageIndex)){
   const group=[]
   for(const [lineIndex,segments]of expectedTextSegments(plan.edit).entries()){
    if(!segments.some(segment=>segment.text.trim()))continue
    let cursor=plan.origin[0]+(plan.offsets?.[lineIndex]??0)
    for(const segment of segments){
     const found=objects.findIndex((item,i)=>!used.has(i)&&item.text.trimEnd()===segment.text.trimEnd()&&near(metrics[i]!.matrix[4],cursor)&&near(metrics[i]!.matrix[5],plan.origin[1]-lineIndex*plan.leading))
     if(found<0)throw Error('pdf_text_style_output_segments_or_baselines_changed')
     used.add(found)
     // Never measure page-extraction synthesized spaces: only the requested logical segment.
     const [metric]=await replacementMetrics(bytes,pageIndex,[{...objects[found]!,measureText:segment.text}])
     group.push({object:objects[found]!,metric:metric!,lineIndex,style:segment.style});cursor+=metric!.width
    }
   }
   groups.set(plan.index,group)
  }
  if(used.size!==objects.length)throw Error('pdf_text_style_unexpected_output_objects')
 }
 for(const plan of plans)if(!groups.has(plan.index)&&plan.operation.newText.trim())throw Error('pdf_text_style_output_not_extractable')
 return {after,groups}
}
export async function replaceStyledText(content:Uint8Array,operations:StyledReplaceTextOperation[],expectedSha256:string){
 const sourceSha256=hash(content)
 if(expectedSha256!==sourceSha256||operations.some(operation=>operation.sourceSha256!==sourceSha256))throw Error('PDF 来源摘要不匹配')
 if(!operations.length||operations.some(operation=>operation.kind!=='replaceText'))throw Error('样式替换须与其他类型修改分别保存')
 operations.forEach(validOptions)
 const document=await PDFDocument.load(content,{updateMetadata:false}),before=await inspectTextObjects(content),source=await inspectNativeText(content,sourceSha256),plans:Plan[]=[],reasons=new Map<number,string[]>(),used=new Set<string>()
 const warn=(index:number,reason:string)=>reasons.set(index,[...(reasons.get(index)??[]),reason])
 let bytes=content
 for(const [index,operation]of operations.entries()){
  const pageIndex=document.getPages().findIndex((_,i)=>operation.pageId==='sha256:'+sourceSha256+':page:'+i),objects=source[pageIndex]??[],targetIndex=objects.findIndex(item=>item.objectId===operation.objectId&&item.expectedTextSha256===operation.expectedTextSha256),target=objects[targetIndex]
  if(!target||!target.text.trim()||used.has(operation.objectId)){warn(index,'pdf_text_style_identity_invalid_or_repeated');continue}
  used.add(operation.objectId)
  const [x1,y1,x2,y2]=target.rect
  if(objects.filter(other=>Math.max(0,Math.min(x2,other.rect[2])-Math.max(x1,other.rect[0]))*Math.max(0,Math.min(y2,other.rect[3])-Math.max(y1,other.rect[1]))>(x2-x1)*(y2-y1)*.5).length!==1){warn(index,'pdf_text_style_identity_ambiguous');continue}
  try{
   const [metric]=await replacementMetrics(content,pageIndex,[{...before[pageIndex]![targetIndex]!,measureText:''}]),matrix=metric!.matrix
   if(Math.abs(matrix[1])>.0001||Math.abs(matrix[2])>.0001||matrix[0]<=0||matrix[3]<=0){warn(index,'pdf_text_style_unsupported_source_baseline_geometry');continue}
   const size=operation.fontSize??metric!.fontSize,origin:[number,number]=[matrix[4],matrix[5]],leading=operation.lineLeading??size*1.2
   const edit:TextEditInput={pageIndex,rect:[...target.rect],oldText:target.text,newText:operation.newText,fontSize:size,newFontSize:size,origin,newFont:operation.font,newBold:operation.bold,newItalic:operation.italic,newColor:operation.color?.map(value=>Math.round(value*255)) as [number,number,number]|undefined,lineLeading:leading,align:operation.align??'left',styleRuns:nativeTextStyleRuns(operation.styleRuns)}
   const [validation]=await validateTextEdits(content,[edit])
   if(validation!.reason){warn(index,validation!.reason);continue}
   plans.push({index,operation,pageIndex,targetIndex,edit,origin,size,leading})
  }catch(error){warn(index,'pdf_text_style_prepare_failed: '+(error instanceof Error?error.message:String(error)))}
 }
 if(plans.length)try{
  let active=[...plans]
  const write=async()=>{
   const submitted=active,result=await applyTextEdits(content,submitted.map(plan=>({...plan.edit,lineXOffsets:plan.offsets})));bytes=result.bytes
   const failed=new Set<Plan>()
   for(const skipped of result.skipped){
    // The pinned replacement API identifies failures by page + oldText, not editIndex.
    const matches=submitted.filter(plan=>plan.pageIndex===skipped.pageIndex&&plan.edit.oldText===skipped.oldText)
    if(!matches.length)throw Error('pdf_text_style_writer_failure_identity_unmapped')
    for(const plan of matches){warn(plan.index,skipped.reason);failed.add(plan)}
   }
   active=submitted.filter(plan=>!failed.has(plan))
  }
  await write()
  if(active.length)try{
   let output=await groupedOutput(bytes,before,active)
   if(active.some(plan=>plan.operation.align&&plan.operation.align!=='left')){
    for(const plan of active){
     if(!plan.operation.align||plan.operation.align==='left')continue
     plan.offsets=plan.operation.newText.split('\n').map(()=>0)
     for(const line of output.groups.get(plan.index)??[])plan.offsets[line.lineIndex]!+=line.metric.width*(plan.operation.align==='center'?-.5:-1)
    }
    await write()
    output=await groupedOutput(bytes,before,active)
   }
   for(const plan of active){
    const operation=plan.operation,box=document.getPage(plan.pageIndex).getCropBox(),group=output.groups.get(plan.index)??[]
    for(const {object,metric,style,lineIndex}of group){
     const requested={font:style?.font??operation.font,size:style?.size??plan.size,bold:style?.bold??operation.bold,italic:style?.italic??operation.italic,color:style?.color??operation.color?.map(value=>Math.round(value*255))}
     if(!near(metric.fontSize,requested.size))warn(plan.index,'pdf_text_style_font_size_changed_generated_bytes_retained')
     const face=object.fontName.replace(/^[A-Z]{6}\+/,'')
     if(requested.font&&!({arial:/Arial|LiberationSans/i,times:/Times|LiberationSerif/i,courier:/Courier|LiberationMono/i}[requested.font as 'arial'|'times'|'courier']).test(face))warn(plan.index,'pdf_text_style_requested_font_fallback_generated_bytes_retained')
     if(requested.bold&&!/bold/i.test(face)&&!metric.boldPainted||requested.italic&&!/italic|oblique/i.test(face)||style?.bold===false&&(/bold/i.test(face)||metric.boldPainted)||style?.italic===false&&/italic|oblique/i.test(face))warn(plan.index,'pdf_text_style_requested_style_fallback_generated_bytes_retained')
     if(requested.color&&requested.color.some((value,i)=>Math.abs(value-metric.color[i]!)>1))warn(plan.index,'pdf_text_style_color_changed_generated_bytes_retained')
     const [x1,y1,x2,y2]=object.rect
     const outside=x1<box.x||y1<box.y||x2>box.x+box.width||y2>box.y+box.height
     const collision=output.after[plan.pageIndex]!.some(other=>other!==object&&!group.some(line=>line.object===other&&line.lineIndex===lineIndex)&&Math.min(x2,other.rect[2])-Math.max(x1,other.rect[0])>.1&&Math.min(y2,other.rect[3])-Math.max(y1,other.rect[1])>.1)
     if(outside||collision)warn(plan.index,'pdf_text_style_overflow_page_or_neighbor_generated_bytes_retained')
    }
   }
  }catch(error){for(const plan of plans)warn(plan.index,'pdf_text_style_output_review_failed: '+(error instanceof Error?error.message:String(error)))}
 }catch(error){for(const plan of plans)warn(plan.index,'pdf_text_style_writer_failed: '+(error instanceof Error?error.message:String(error)))}
 const skippedOperations=[...reasons].map(([operationIndex,issues])=>({operationIndex,kind:'replaceText' as const,pageId:operations[operationIndex]!.pageId,reason:[...new Set(issues)].join('; ')})).sort((a,b)=>a.operationIndex-b.operationIndex),appliedOperationIndices=plans.filter(plan=>!reasons.has(plan.index)).map(plan=>plan.index),outputSha256=hash(bytes)
 return {bytes,sourceSha256,sha256:outputSha256,size:bytes.length,appliedOperationIndices,skippedOperations,previewDigest:hash(JSON.stringify({sourceSha256,operations,outputSha256,appliedOperationIndices,skippedOperations}))}
}
