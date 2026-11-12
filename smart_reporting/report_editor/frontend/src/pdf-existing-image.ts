import type {NativeDraft,NativeOperation} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
import {cropRect,type CropFractions} from './vendor/genoffice-pdf/renderer/image-bake'
export const PDF_EXISTING_IMAGE_ALONE_REASON='已有图像编辑须单独保存，请先保存或撤销其他修改'
export interface PdfExistingImage {pageId:string;pageIndex:number;rect:[number,number,number,number];imageId:string;expectedImageSha256:string;aboveText:boolean;editable:boolean;reason?:string;replaceable?:boolean;replaceReason?:string;bakeable?:boolean;bakeReason?:string}
/** 固定源 image-bake 的三种像素编辑：由桥接取图像自身显示像素后烘焙并经 replaceImage 写回。 */
export type PdfImageBake={kind:'flip';axis:'h'|'v'}|{kind:'opacity';alpha:number}|{kind:'crop';crop:CropFractions}
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
/** 裁剪/翻转/透明度：不与移动或替换同批；裁剪的新范围由固定源 cropRect 计算。 */
export function existingImageBake(sourceSha256:string,image:PdfExistingImage,bake:PdfImageBake):NativeOperation {
 if(image.bakeable!==true)throw Error(image.bakeReason??'此图像暂不支持裁剪、翻转与透明度')
 validateBake(bake)
 const rect=bake.kind==='crop'?cropRect(image.rect,bake.crop).map(value=>Math.round(value*1000)/1000):[...image.rect]
 return {kind:'transformExistingImage',sourceSha256,pageId:image.pageId,imageId:image.imageId,expectedImageSha256:image.expectedImageSha256,rect,bake}
}
function validateBake(bake:unknown):asserts bake is PdfImageBake {
 const value=bake as Record<string,unknown>
 const fraction=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=1
 if(!value||typeof value!=='object')throw Error('像素编辑参数无效')
 if(value.kind==='flip'){if(Object.keys(value).sort().join()!=='axis,kind'||!['h','v'].includes(String(value.axis)))throw Error('翻转方向无效');return}
 if(value.kind==='opacity'){const alpha=value.alpha;if(Object.keys(value).sort().join()!=='alpha,kind'||typeof alpha!=='number'||alpha<0||alpha>.99||Math.abs(Math.round(alpha*100)-alpha*100)>1e-9)throw Error('不透明度须为 0–99% 的整数百分比');return}
 if(value.kind==='crop'){const c=value.crop as Record<string,number>|undefined;if(Object.keys(value).sort().join()!=='crop,kind'||!c||Object.keys(c).sort().join()!=='b,l,r,t'||![c.l,c.t,c.r,c.b].every(fraction)||c.r!-c.l!<.01||c.b!-c.t!<.01||(c.r!-c.l!>=1&&c.b!-c.t!>=1))throw Error('裁剪范围无效：每边保留比例须在 0–100% 内，且至少裁去一部分');return}
 throw Error('像素编辑类型无效')
}
export function validatePdfExistingImage(pages:PdfPageIdentity[],operations:NativeOperation[],images?:PdfExistingImage[]){
 const edits=operations.filter(operation=>operation.kind==='transformExistingImage');if(!edits.length)return
 if(operations.length!==1)throw Error(PDF_EXISTING_IMAGE_ALONE_REASON)
 const operation=edits[0]!
 if(Object.keys(operation).some(key=>!['kind','sourceSha256','pageId','imageId','expectedImageSha256','rect','image','bake'].includes(key))||(operation.image!==undefined&&!pngBase64(operation.image))||(operation.image!==undefined&&operation.bake!==undefined))throw Error('已有图像编辑参数无效')
 if(operation.bake!==undefined)validateBake(operation.bake)
 const page=pages.find(page=>page.pageId===operation.pageId)
 if(!page||page.blank||!digest(operation.sourceSha256)||!page.pageId.startsWith('sha256:'+operation.sourceSha256+':page:')||!digest(operation.imageId)||!digest(operation.expectedImageSha256))throw Error('已有图像来源或页面身份已变化')
 const rect=operation.rect
 if(!Array.isArray(rect)||rect.length!==4||rect.some(value=>typeof value!=='number'||!Number.isFinite(value)))throw Error('图像范围无效')
 const [x1,y1,x2,y2]=rect as number[],box=page.cropBox
 if(x2-x1<3||y2-y1<3||x1<box.x||y1<box.y||x2>box.x+box.width||y2>box.y+box.height)throw Error('图像范围超出当前页面或尺寸过小')
 if(images){const target=images.find(image=>image.imageId===operation.imageId&&image.pageId===operation.pageId&&image.expectedImageSha256===operation.expectedImageSha256);if(!target?.editable)throw Error(target?.reason??'已有图像身份已变化');if(operation.image!==undefined&&target.replaceable!==true)throw Error(target.replaceReason??'此图像暂不支持替换');if(operation.bake!==undefined){if(target.bakeable!==true)throw Error(target.bakeReason??'此图像暂不支持裁剪、翻转与透明度');const bake=operation.bake as PdfImageBake,expected=bake.kind==='crop'?cropRect(target.rect,bake.crop):target.rect;if((rect as number[]).some((value,i)=>Math.abs(value-expected[i]!)>.05))throw Error('裁剪、翻转或透明度不能同时移动图像')}}
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
 const hint=owner.createElement('p');hint.textContent='选择原 PDF 的图像对象，移动或调整尺寸，或替换为新图像（保留位置与层级，可同时调整范围）。坐标为原始 PDF 单位，原点在左下角；页面旋转不改变这里的坐标。也可水平/垂直翻转、按比例裁剪或调整透明度（像素编辑不能与移动或替换同批）。保存前请核对实际 PDF 预览。'
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
 // 固定源图像浮动工具条：水平/垂直翻转、裁剪、透明度（像素烘焙后经 replaceImage 写回）
 const bakeKind=field('像素编辑',owner.createElement('select')) as HTMLSelectElement
 for(const [value,label] of [['','无'],['flip-h','水平翻转'],['flip-v','垂直翻转'],['crop','裁剪'],['opacity','透明度']])bakeKind.append(new Option(label,value))
 const cropRow=owner.createElement('div');cropRow.className='pdf-existing-image-crop'
 const cropInputs=['左','上','右','下'].map(name=>{const label=owner.createElement('label');label.textContent='裁去'+name+' %';const input=owner.createElement('input');input.type='number';input.min='0';input.max='99';input.step='1';input.value='0';input.setAttribute('aria-label','裁去'+name+'侧百分比');label.append(input);cropRow.append(label);return input})
 const opacityLabel=owner.createElement('label');opacityLabel.textContent='透明度 %';const opacityInput=owner.createElement('input');opacityInput.type='number';opacityInput.min='1';opacityInput.max='100';opacityInput.step='1';opacityInput.value='50';opacityInput.setAttribute('aria-label','图像透明度百分比');opacityLabel.append(opacityInput)
 const bakeInfo=owner.createElement('p');bakeInfo.className='pdf-existing-image-replace-info'
 dialog.append(cropRow,opacityLabel,bakeInfo)
 const alert=owner.createElement('p');alert.setAttribute('role','alert')
 const confirm=owner.createElement('button');confirm.type='button';confirm.textContent='应用';confirm.dataset.pdfExistingImageConfirm=''
 const dismiss=owner.createElement('button');dismiss.type='button';dismiss.textContent='取消'
 dialog.append(alert,confirm,dismiss);options.root.append(dialog)
 let disposed=false,snapshot='',imageSnapshot='',choices:PdfExistingImage[]=[],replacement:string|undefined
 function setReplacement(value?:{png:string;width:number;height:number;name:string}){replacement=value?.png;replaceClear.hidden=!value;replaceInfo.textContent=value?`将替换为 ${value.name}（${value.width}×${value.height}）`:'不替换像素';syncBake()}
 function syncReplace(){const image=choices[Number(select.value)];const reason=image&&image.replaceable!==true?image.replaceReason??'此图像暂不支持替换':null;replacePick.disabled=!!reason||!!bakeKind.value;replacePick.title=bakeKind.value?'像素编辑与替换不能同批':reason??'选择 PNG 或 JPEG 替换此图像的像素';if(reason&&replacement)setReplacement();syncBake()}
 /** 像素编辑与移动/替换互斥：选中时锁定坐标并隐藏替换。 */
 function syncBake(){const image=choices[Number(select.value)],reason=image&&image.bakeable!==true?image.bakeReason??'此图像暂不支持裁剪、翻转与透明度':null
  if(reason&&bakeKind.value)bakeKind.value=''
  bakeKind.disabled=!!reason||replacement!==undefined;bakeKind.title=replacement!==undefined?'替换与像素编辑不能同批':reason??''
  cropRow.hidden=bakeKind.value!=='crop';opacityLabel.hidden=bakeKind.value!=='opacity'
  for(const input of inputs)input.disabled=!!bakeKind.value
  if(bakeKind.value)fill()
  bakeInfo.textContent=reason?reason:bakeKind.value?'像素编辑保持原位置与层级（裁剪会按保留比例缩小范围），不能同时移动；保存前请核对实际 PDF 预览。':''}
 function currentBake():PdfImageBake|undefined{
  if(bakeKind.value==='flip-h'||bakeKind.value==='flip-v')return {kind:'flip',axis:bakeKind.value==='flip-h'?'h':'v'}
  if(bakeKind.value==='opacity'){const percent=Number(opacityInput.value);if(!Number.isInteger(percent)||percent<1||percent>100)throw Error('透明度须为 1–100 的整数百分比');return {kind:'opacity',alpha:(100-percent)/100}}
  if(bakeKind.value==='crop'){const [l,t,r,b]=cropInputs.map(input=>Number(input.value));if(![l,t,r,b].every(value=>Number.isInteger(value)&&value>=0&&value<=99))throw Error('每侧裁去比例须为 0–99 的整数');return {kind:'crop',crop:{l:l!/100,t:t!/100,r:1-r!/100,b:1-b!/100}}}
  return undefined
 }
 function cancel(){if(dialog.open)dialog.close()}
 function reason(){return options.unavailable()??(snapshot!==JSON.stringify(options.draft.operations)||imageSnapshot!==JSON.stringify(options.images())?'草稿或图像来源已变化，请重新打开编辑':null)}
 function fill(){const image=choices[Number(select.value)];if(!image)return;const [x1,y1,x2,y2]=image.rect;[x1,y1,x2-x1,y2-y1].forEach((value,i)=>inputs[i]!.value=String(value))}
 select.addEventListener('change',()=>{fill();syncReplace()});dismiss.addEventListener('click',cancel);bakeKind.addEventListener('change',()=>{alert.textContent='';syncReplace()})
 replacePick.addEventListener('click',()=>{replaceFile.value='';replaceFile.click()})
 replaceClear.addEventListener('click',()=>setReplacement())
 replaceFile.addEventListener('change',()=>{const file=replaceFile.files?.[0];if(!file)return;void pngFromImageFile(owner,file).then(result=>{if(!dialog.open)return;setReplacement({...result,name:file.name});alert.textContent=''}).catch(error=>{alert.textContent=error instanceof Error?error.message:String(error)})})
 confirm.addEventListener('click',async()=>{
  if(disposed||!dialog.open)return
  try{const blocked=reason();if(blocked)throw Error(blocked);const image=choices[Number(select.value)];if(!image)throw Error('请选择已有图像');const bake=currentBake();if(bake){const operation=existingImageBake(options.draft.identity.sourceSha256,image,bake);validatePdfExistingImage(options.pages(),[operation],options.images());options.draft.setOperations([operation]);cancel();await options.refresh();options.status('已暂存已有图像'+(bake.kind==='crop'?'裁剪':bake.kind==='flip'?(bake.axis==='h'?'水平翻转':'垂直翻转'):'透明度')+'，请核对实际 PDF 预览后保存');return}
  const [x,y,width,height]=inputs.map(input=>input.value.trim()===''?NaN:Number(input.value));const replaced=replacement!==undefined,operation=existingImageTransform(options.draft.identity.sourceSha256,image,{x:x!,y:y!,width:width!,height:height!},replacement);validatePdfExistingImage(options.pages(),[operation],options.images());options.draft.setOperations([operation]);cancel();await options.refresh();options.status(replaced?'已暂存已有图像替换，请核对实际 PDF 预览后保存':'已暂存已有图像移动或尺寸调整，请核对实际 PDF 预览后保存')}
  catch(error){alert.textContent=error instanceof Error?error.message:String(error)}
 })
 return {open(){if(disposed)return;const blocked=options.unavailable();if(blocked){options.status(blocked);return}if(options.draft.operations.length){options.status(PDF_EXISTING_IMAGE_ALONE_REASON);return}choices=options.images().filter(image=>image.editable);if(!choices.length){options.status('来源没有可编辑的已有图像');return}snapshot=JSON.stringify(options.draft.operations);imageSnapshot=JSON.stringify(options.images());select.replaceChildren();choices.forEach((image,i)=>{const option=owner.createElement('option');option.value=String(i);option.textContent='第 '+(image.pageIndex+1)+' 页 · 图像 '+(i+1);select.append(option)});select.value='0';bakeKind.value='';for(const input of cropInputs)input.value='0';opacityInput.value='50';fill();setReplacement();syncReplace();alert.textContent='';dialog.showModal()},cancel,incompleteReason(){return dialog.open?'请先完成或取消已有图像编辑':null},refresh(){if(dialog.open&&reason())cancel()},dispose(){if(disposed)return;disposed=true;dialog.remove()}}
}
