import type {NativeDraft,NativeOperation} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
export const PDF_EXISTING_IMAGE_ALONE_REASON='已有图像编辑须单独保存，请先保存或撤销其他修改'
export interface PdfExistingImage {pageId:string;pageIndex:number;rect:[number,number,number,number];imageId:string;expectedImageSha256:string;aboveText:boolean;editable:boolean;reason?:string;replaceable?:boolean;replaceReason?:string}
/** 替换像素的上限与固定源插入图像一致：浏览器转 PNG、最长边 ≤2000px、编码 ≤6MB。 */
export const PDF_REPLACEMENT_IMAGE_MAX_BASE64=6_000_000
const pngBase64=(value:unknown):value is string=>typeof value==='string'&&value.startsWith('iVBORw0KGgo')&&value.length<=PDF_REPLACEMENT_IMAGE_MAX_BASE64&&/^[A-Za-z0-9+/]+={0,2}$/.test(value)
const digest=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value)
/** 移动/缩放已有图像；传入 replacement（PNG base64）时同时替换像素（固定源 replaceImage）。 */
export function existingImageTransform(sourceSha256:string,image:PdfExistingImage,geometry:{x:number;y:number;width:number;height:number},replacement?:string):NativeOperation {
 const {x,y,width,height}=geometry
 if(![x,y,width,height].every(Number.isFinite)||width<3||height<3)throw Error('图像坐标须为有限数值，宽高至少为 3')
 if(replacement!==undefined&&!pngBase64(replacement))throw Error('替换图像须为不超过限额的 PNG')
 if(replacement!==undefined&&image.replaceable!==true)throw Error(image.replaceReason??'此图像暂不支持替换')
 return {kind:'transformExistingImage',sourceSha256,pageId:image.pageId,imageId:image.imageId,expectedImageSha256:image.expectedImageSha256,rect:[x,y,x+width,y+height],...(replacement!==undefined?{image:replacement}:{})}
}
export function validatePdfExistingImage(pages:PdfPageIdentity[],operations:NativeOperation[],images?:PdfExistingImage[]){
 const edits=operations.filter(operation=>operation.kind==='transformExistingImage');if(!edits.length)return
 if(operations.length!==1)throw Error(PDF_EXISTING_IMAGE_ALONE_REASON)
 const operation=edits[0]!
 if(Object.keys(operation).some(key=>!['kind','sourceSha256','pageId','imageId','expectedImageSha256','rect','image'].includes(key))||(operation.image!==undefined&&!pngBase64(operation.image)))throw Error('已有图像编辑参数无效')
 const page=pages.find(page=>page.pageId===operation.pageId)
 if(!page||page.blank||!digest(operation.sourceSha256)||!page.pageId.startsWith('sha256:'+operation.sourceSha256+':page:')||!digest(operation.imageId)||!digest(operation.expectedImageSha256))throw Error('已有图像来源或页面身份已变化')
 const rect=operation.rect
 if(!Array.isArray(rect)||rect.length!==4||rect.some(value=>typeof value!=='number'||!Number.isFinite(value)))throw Error('图像范围无效')
 const [x1,y1,x2,y2]=rect as number[],box=page.cropBox
 if(x2-x1<3||y2-y1<3||x1<box.x||y1<box.y||x2>box.x+box.width||y2>box.y+box.height)throw Error('图像范围超出当前页面或尺寸过小')
 if(images){const target=images.find(image=>image.imageId===operation.imageId&&image.pageId===operation.pageId&&image.expectedImageSha256===operation.expectedImageSha256);if(!target?.editable)throw Error(target?.reason??'已有图像身份已变化');if(operation.image!==undefined&&target.replaceable!==true)throw Error(target.replaceReason??'此图像暂不支持替换')}
}
/** 与“插入图像”相同：PNG/JPEG ≤10MB，浏览器按最长边 ≤2000px 转为 PNG。 */
export async function pngFromImageFile(owner:Document,file:File):Promise<{png:string;width:number;height:number}>{
 if(!['image/png','image/jpeg'].includes(file.type)||file.size>10*1024*1024)throw Error('请选择不超过 10MB 的 PNG 或 JPEG 图像')
 const bitmap=await createImageBitmap(file),ratio=Math.min(1,2000/Math.max(bitmap.width,bitmap.height))
 const canvas=owner.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*ratio));canvas.height=Math.max(1,Math.round(bitmap.height*ratio))
 canvas.getContext('2d')!.drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close()
 const png=canvas.toDataURL('image/png').split(',')[1]??''
 if(!pngBase64(png))throw Error('图像转换后过大，请换一张较小的图像')
 return {png,width:canvas.width,height:canvas.height}
}
export function bindPdfExistingImagePanel(options:{root:HTMLElement;draft:NativeDraft;pages:()=>PdfPageIdentity[];images:()=>PdfExistingImage[];unavailable:()=>string|null;refresh:()=>Promise<void>;status:(message:string)=>void}){
 const owner=options.root.ownerDocument,dialog=owner.createElement('dialog');dialog.className='pdf-layout-dialog pdf-existing-image-dialog';dialog.setAttribute('aria-label','编辑已有图像')
 const title=owner.createElement('h3');title.textContent='编辑已有图像'
 const hint=owner.createElement('p');hint.textContent='选择原 PDF 的图像对象，移动或调整尺寸，或替换为新图像（保留位置与层级，可同时调整范围）。坐标为原始 PDF 单位，原点在左下角；页面旋转不改变这里的坐标。暂不支持像素裁剪。保存前请核对实际 PDF 预览。'
 dialog.append(title,hint)
 function field(name:string,input:HTMLElement){const label=owner.createElement('label');label.textContent=name;input.setAttribute('aria-label','已有图像'+name);label.append(input);dialog.append(label);return input}
 const select=field('选择',owner.createElement('select')) as HTMLSelectElement
 const inputs=['X','Y','宽度','高度'].map(name=>{const input=field(name,owner.createElement('input')) as HTMLInputElement;input.type='number';input.step='any';return input})
 // 固定源 Picture ▸ 替换图片（replaceExisting）：选择新图像替换像素
 const replaceRow=owner.createElement('div');replaceRow.className='pdf-existing-image-replace'
 const replaceFile=owner.createElement('input');replaceFile.type='file';replaceFile.accept='image/png,image/jpeg';replaceFile.hidden=true;replaceFile.setAttribute('aria-label','选择替换图像')
 const replacePick=owner.createElement('button');replacePick.type='button';replacePick.textContent='替换为新图像…';replacePick.dataset.pdfExistingImageReplace=''
 const replaceClear=owner.createElement('button');replaceClear.type='button';replaceClear.textContent='不替换';replaceClear.hidden=true
 const replaceInfo=owner.createElement('span');replaceInfo.className='pdf-existing-image-replace-info';replaceInfo.textContent='不替换像素'
 replaceRow.append(replacePick,replaceClear,replaceInfo,replaceFile);dialog.append(replaceRow)
 const alert=owner.createElement('p');alert.setAttribute('role','alert')
 const confirm=owner.createElement('button');confirm.type='button';confirm.textContent='应用';confirm.dataset.pdfExistingImageConfirm=''
 const dismiss=owner.createElement('button');dismiss.type='button';dismiss.textContent='取消'
 dialog.append(alert,confirm,dismiss);options.root.append(dialog)
 let disposed=false,snapshot='',imageSnapshot='',choices:PdfExistingImage[]=[],replacement:string|undefined
 function setReplacement(value?:{png:string;width:number;height:number;name:string}){replacement=value?.png;replaceClear.hidden=!value;replaceInfo.textContent=value?`将替换为 ${value.name}（${value.width}×${value.height}）`:'不替换像素'}
 function syncReplace(){const image=choices[Number(select.value)];const reason=image&&image.replaceable!==true?image.replaceReason??'此图像暂不支持替换':null;replacePick.disabled=!!reason;replacePick.title=reason??'选择 PNG 或 JPEG 替换此图像的像素';if(reason&&replacement)setReplacement()}
 function cancel(){if(dialog.open)dialog.close()}
 function reason(){return options.unavailable()??(snapshot!==JSON.stringify(options.draft.operations)||imageSnapshot!==JSON.stringify(options.images())?'草稿或图像来源已变化，请重新打开编辑':null)}
 function fill(){const image=choices[Number(select.value)];if(!image)return;const [x1,y1,x2,y2]=image.rect;[x1,y1,x2-x1,y2-y1].forEach((value,i)=>inputs[i]!.value=String(value))}
 select.addEventListener('change',()=>{fill();syncReplace()});dismiss.addEventListener('click',cancel)
 replacePick.addEventListener('click',()=>{replaceFile.value='';replaceFile.click()})
 replaceClear.addEventListener('click',()=>setReplacement())
 replaceFile.addEventListener('change',()=>{const file=replaceFile.files?.[0];if(!file)return;void pngFromImageFile(owner,file).then(result=>{if(!dialog.open)return;setReplacement({...result,name:file.name});alert.textContent=''}).catch(error=>{alert.textContent=error instanceof Error?error.message:String(error)})})
 confirm.addEventListener('click',async()=>{
  if(disposed||!dialog.open)return
  try{const blocked=reason();if(blocked)throw Error(blocked);const image=choices[Number(select.value)];if(!image)throw Error('请选择已有图像');const [x,y,width,height]=inputs.map(input=>input.value.trim()===''?NaN:Number(input.value));const replaced=replacement!==undefined,operation=existingImageTransform(options.draft.identity.sourceSha256,image,{x:x!,y:y!,width:width!,height:height!},replacement);validatePdfExistingImage(options.pages(),[operation],options.images());options.draft.setOperations([operation]);cancel();await options.refresh();options.status(replaced?'已暂存已有图像替换，请核对实际 PDF 预览后保存':'已暂存已有图像移动或尺寸调整，请核对实际 PDF 预览后保存')}
  catch(error){alert.textContent=error instanceof Error?error.message:String(error)}
 })
 return {open(){if(disposed)return;const blocked=options.unavailable();if(blocked){options.status(blocked);return}if(options.draft.operations.length){options.status(PDF_EXISTING_IMAGE_ALONE_REASON);return}choices=options.images().filter(image=>image.editable);if(!choices.length){options.status('来源没有可编辑的已有图像');return}snapshot=JSON.stringify(options.draft.operations);imageSnapshot=JSON.stringify(options.images());select.replaceChildren();choices.forEach((image,i)=>{const option=owner.createElement('option');option.value=String(i);option.textContent='第 '+(image.pageIndex+1)+' 页 · 图像 '+(i+1);select.append(option)});select.value='0';fill();setReplacement();syncReplace();alert.textContent='';dialog.showModal()},cancel,incompleteReason(){return dialog.open?'请先完成或取消已有图像编辑':null},refresh(){if(dialog.open&&reason())cancel()},dispose(){if(disposed)return;disposed=true;dialog.remove()}}
}
