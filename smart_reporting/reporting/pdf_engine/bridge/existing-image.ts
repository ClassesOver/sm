/** Source-bound existing content image geometry; this never inserts a stamp. */
import {createHash} from 'node:crypto'
import {PDFDocument} from 'pdf-lib'
import {z} from 'zod'
import {inspectTextObjects} from '../src/main/text-edit'
import {staticTextAvailability} from './static-text'
import {applyExistingImageReplace,applyExistingImageReplaceBgra,applyExistingImageTransform,decodePngBgra,listExistingEngineImages,renderExistingImageBgra,type ExistingEngineImage} from './existing-image-engine'
import {cropRect,flipPixels,multiplyAlpha} from '../src/renderer/image-bake'
const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
const rectSchema=z.tuple([z.number().finite(),z.number().finite(),z.number().finite(),z.number().finite()])
const operationSchema=z.object({kind:z.literal('transformExistingImage'),sourceSha256:z.string().regex(/^[a-f0-9]{64}$/),pageId:z.string(),imageId:z.string().regex(/^[a-f0-9]{64}$/),expectedImageSha256:z.string().regex(/^[a-f0-9]{64}$/),rect:rectSchema,image:z.string().min(8).max(6_000_000).optional(),bake:z.discriminatedUnion('kind',[
 z.object({kind:z.literal('flip'),axis:z.enum(['h','v'])}).strict(),
 z.object({kind:z.literal('opacity'),alpha:z.number().min(0).max(.99).refine(value=>Math.abs(Math.round(value*100)-value*100)<1e-9)}).strict(),
 z.object({kind:z.literal('crop'),crop:z.object({l:z.number().min(0).max(1),t:z.number().min(0).max(1),r:z.number().min(0).max(1),b:z.number().min(0).max(1)}).strict().refine(c=>c.r-c.l>=.01&&c.b-c.t>=.01&&(c.r-c.l<1||c.b-c.t<1))}).strict(),
]).optional()}).strict().refine(op=>op.image===undefined||op.bake===undefined)
/** 固定源 App.tsx BAKE_SCALE：烘焙像素按页面尺寸 3 倍取样，结果保持印刷清晰度。 */
const BAKE_SCALE=3
export type ExistingImageOperation=z.infer<typeof operationSchema>
export interface ExistingImageRef {pageId:string;pageIndex:number;rect:[number,number,number,number];aboveText:boolean;imageId:string;expectedImageSha256:string;editable:boolean;reason?:string;replaceable:boolean;replaceReason?:string;bakeable:boolean;bakeReason?:string}
const near=(a:readonly number[],b:readonly number[],tol=2)=>a.every((v,i)=>Math.abs(v-b[i])<=tol)
function references(sourceSha256:string,images:ExistingEngineImage[],allowed:boolean):ExistingImageRef[]{
 return images.map((image,index)=>{
  const ambiguous=images.some((other,otherIndex)=>index!==otherIndex&&image.pageIndex===other.pageIndex&&near(image.rect,other.rect))
  const editable=allowed&&image.exclusive&&!ambiguous
  // PDFium 的 SetBitmap 改写图像流本身：同一像素流被其他位置引用（含其他页）时替换会连带改变它们，必须拒绝。
  const shared=images.some((other,otherIndex)=>index!==otherIndex&&other.pixelsSha256===image.pixelsSha256)
  const replaceable=editable&&!shared
  // 固定源烘焙（裁剪/翻转/透明度）取显示方向像素后经 replaceImage 写回且不动矩阵：只对页面直属、无旋转无镜像的图像结果方向一致。
  const bakeable=replaceable&&image.axisAligned
  return {pageId:'sha256:'+sourceSha256+':page:'+image.pageIndex,pageIndex:image.pageIndex,rect:image.rect,aboveText:image.aboveText,imageId:hash(JSON.stringify({sourceSha256,index,pageIndex:image.pageIndex,rect:image.rect,fingerprint:image.fingerprint})),expectedImageSha256:image.fingerprint,editable,...(!editable?{reason:ambiguous?'图像位置重叠，不能唯一定位原对象':!image.exclusive?'图像位于共享模板，暂不能单独编辑':'来源结构暂不支持编辑已有图像'}:{}),replaceable,...(!replaceable?{replaceReason:!editable?'此图像不能编辑':'同一图像数据被多处引用，替换会改变其他位置，暂不支持替换'}:{}),bakeable,...(!bakeable?{bakeReason:!replaceable?(!editable?'此图像不能编辑':'同一图像数据被多处引用，裁剪或翻转会改变其他位置'):'图像带旋转、镜像或位于模板内，暂不支持裁剪、翻转与透明度'}:{})}
 })
}
export async function inspectExistingImages(content:Uint8Array){
 const document=await PDFDocument.load(content,{updateMetadata:false}),availability=staticTextAvailability(document)
 const allowed=availability.insertText,sourceSha256=hash(content)
 let images:ExistingEngineImage[]
 try{images=await listExistingEngineImages(content)}catch{return {existingImages:[],capabilities:{editExistingImage:false,editExistingImageReason:'来源图像对象暂不能安全识别，暂不支持编辑已有图像'}}}
 const existingImages=references(sourceSha256,images,allowed)
 const editExistingImage=allowed&&existingImages.some(image=>image.editable)
 const reason=!allowed?availability.insertTextReason?.replace('插入静态文字','编辑已有图像'):!images.length?'来源没有可编辑的已有图像':!editExistingImage?existingImages[0]?.reason:null
 return {existingImages,capabilities:{editExistingImage,editExistingImageReason:reason??null}}
}
export async function transformExistingImage(content:Uint8Array,input:unknown,expectedSha256:string){
 const operation=operationSchema.parse(input),sourceSha256=hash(content)
 if(expectedSha256!==sourceSha256||operation.sourceSha256!==sourceSha256)throw Error('PDF 来源摘要不匹配')
 const model=await inspectExistingImages(content)
 const target=model.existingImages.find(image=>image.imageId===operation.imageId&&image.pageId===operation.pageId)
 if(!target||target.expectedImageSha256!==operation.expectedImageSha256)throw Error('PDF 已有图像身份无效或已过期')
 if(!target.editable)throw Error(target.reason??'来源不能编辑已有图像')
 if(operation.image!==undefined&&!target.replaceable)throw Error(target.replaceReason??'此图像暂不支持替换')
 if(operation.bake&&!target.bakeable)throw Error(target.bakeReason??'此图像暂不支持裁剪、翻转与透明度')
 // 烘焙不与移动同批：翻转/透明度保持原范围，裁剪的新范围必须正是固定源 cropRect(原范围, 保留比例)。
 if(operation.bake&&!near(operation.rect,operation.bake.kind==='crop'?cropRect(target.rect,operation.bake.crop):target.rect,.05))throw Error(operation.bake.kind==='crop'?'裁剪后的范围须由保留比例计算，不能同时移动':'翻转或透明度不能同时移动或缩放图像')
 const document=await PDFDocument.load(content,{updateMetadata:false}),page=document.getPage(target.pageIndex),box=page.getCropBox(),[x1,y1,x2,y2]=operation.rect
 if(x2-x1<3||y2-y1<3||x1<box.x||y1<box.y||x2>box.x+box.width||y2>box.y+box.height)throw Error('图像范围超出来源裁切范围或尺寸过小')
 const skip=(reason:string)=>({operationIndex:0,kind:operation.kind,pageId:operation.pageId,reason})
 // 固定源 replaceImage：替换像素（PNG），足迹与层级保留，随后同一几何变换；替换图先解码校验，失败整批拒绝。
 const replacement=operation.image===undefined?undefined:(()=>{try{const decoded=decodePngBgra(operation.image!);return {width:decoded.width,height:decoded.height}}catch(error){throw Error('替换图像须为可解码的 PNG：'+(error instanceof Error?error.message:String(error)))}})()
 let bytes=content,skippedOperations:ReturnType<typeof skip>[]=[],baked:{width:number;height:number}|undefined
 try{
  if(operation.bake){
   // 固定源 bakeSourcePng → transformPngPixels/cropImagePng → replaceImage：取图像自身的显示像素，在像素上烘焙后写回。
   const source=await renderExistingImageBgra(content,target.pageIndex,target.rect,BAKE_SCALE),bake=operation.bake
   const image={data:new Uint8ClampedArray(source.bgra.buffer,source.bgra.byteOffset,source.bgra.length),width:source.width,height:source.height}
   let pixels:{width:number;height:number;bgra:Uint8Array}
   if(bake.kind==='flip')pixels={width:image.width,height:image.height,bgra:new Uint8Array(flipPixels(image,bake.axis).buffer)}
   else if(bake.kind==='opacity')pixels={width:image.width,height:image.height,bgra:new Uint8Array(multiplyAlpha(image,bake.alpha).buffer)}
   else{
    // 与固定源 cropImagePng 相同的取整：sx/sy 四舍五入，宽高至少 1 像素
    const {l,t,r,b}=bake.crop,sx=Math.round(l*image.width),sy=Math.round(t*image.height),sw=Math.max(1,Math.min(image.width-sx,Math.round((r-l)*image.width))),sh=Math.max(1,Math.min(image.height-sy,Math.round((b-t)*image.height)))
    const out=new Uint8Array(sw*sh*4);for(let row=0;row<sh;row++)out.set(source.bgra.subarray(((sy+row)*image.width+sx)*4,((sy+row)*image.width+sx+sw)*4),row*sw*4)
    pixels={width:sw,height:sh,bgra:out}
   }
   baked={width:pixels.width,height:pixels.height}
   bytes=await applyExistingImageReplaceBgra(content,target.pageIndex,target.rect,operation.rect,pixels)
  }else bytes=replacement?await applyExistingImageReplace(content,target.pageIndex,target.rect,operation.rect,operation.image!):await applyExistingImageTransform(content,target.pageIndex,target.rect,operation.rect)}catch(error){skippedOperations=[skip('pdf_existing_image_failed: '+(error instanceof Error?error.message:String(error)))]}
 if(!skippedOperations.length){
  // Once the writer returns, review failure must retain these actual generated bytes.
  try{
   const output=await listExistingEngineImages(bytes),before=await listExistingEngineImages(content)
   const targetIndex=model.existingImages.indexOf(target)
   const remaining=[...output],expected=before.map((image,index)=>({...image,rect:index===targetIndex?operation.rect:image.rect}))
   // 替换的目标按新像素尺寸与位置复核（PDFium 会把 alpha 拆成 SMask 并重新编码，不能比较原始字节）；其他图像逐像素不变。
   for(const [index,image] of expected.entries()){const i=remaining.findIndex(item=>item.pageIndex===image.pageIndex&&near(item.rect,image.rect,.05)&&((replacement??baked)&&index===targetIndex?item.width===(replacement??baked)!.width&&item.height===(replacement??baked)!.height:item.pixelsSha256===image.pixelsSha256));if(i<0)throw Error((replacement??baked)&&index===targetIndex?'替换图像像素尺寸或范围复核不一致':'图像对象范围复核不一致');remaining.splice(i,1)}
   if(remaining.length)throw Error('图像对象数量复核不一致')
   const oldText=await inspectTextObjects(content),newText=await inspectTextObjects(bytes)
   if(oldText.length!==newText.length||oldText.some((runs,i)=>runs.length!==newText[i].length||runs.some((run,j)=>run.text!==newText[i][j].text||!near(run.rect,newText[i][j].rect,.05))))throw Error('原始正文复核不一致')
   const saved=await PDFDocument.load(bytes,{updateMetadata:false})
   if(saved.getPageCount()!==document.getPageCount()||saved.getPages().some((p,i)=>p.getRotation().angle!==document.getPage(i).getRotation().angle||JSON.stringify(p.getCropBox())!==JSON.stringify(document.getPage(i).getCropBox())||JSON.stringify(p.getMediaBox())!==JSON.stringify(document.getPage(i).getMediaBox())))throw Error('页面结构复核不一致')
  }catch(error){skippedOperations=[skip('pdf_existing_image_output_review_failed: '+(error instanceof Error?error.message:String(error)))]}
 }
 const outputSha256=hash(bytes),appliedOperationIndices=skippedOperations.length?[]:[0]
 return {bytes,sourceSha256,sha256:outputSha256,size:bytes.length,appliedOperationIndices,skippedOperations,previewDigest:hash(JSON.stringify({sourceSha256,operation,outputSha256,appliedOperationIndices,skippedOperations}))}
}
