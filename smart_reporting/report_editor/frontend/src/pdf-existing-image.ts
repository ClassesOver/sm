import type {NativeDraft,NativeOperation} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
import {cropRect,DEFAULT_CUTOUT_TOLERANCE,type CropFractions} from './vendor/genoffice-pdf/renderer/image-bake'
import {installFocusTrap} from './focus-trap'
export const PDF_EXISTING_IMAGE_ALONE_REASON='已有图像编辑须单独保存，请先保存或撤销其他修改'
export type PdfImagePixelTarget={sourceSha256:string;pageId:string;imageId:string;expectedImageSha256:string}
export type PdfImagePixels=PdfImagePixelTarget&{image:string;width:number;height:number;sha256:string}
export interface PdfExistingImage {pageId:string;pageIndex:number;rect:[number,number,number,number];imageId:string;expectedImageSha256:string;aboveText:boolean;editable:boolean;reason?:string;replaceable?:boolean;replaceReason?:string;bakeable?:boolean;bakeReason?:string}
/** 固定源 ImageBakeOp 的像素编辑：由桥接取图像自身显示像素后烘焙并经 replaceImage 写回。 */
export type PdfImageBake={kind:'flip';axis:'h'|'v'}|{kind:'opacity';alpha:number}|{kind:'crop';crop:CropFractions}|{kind:'cutout';tolerance:number}|{kind:'rotate';quarterTurns:1|3}
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
 if(image.bakeable!==true)throw Error(image.bakeReason??'此图像暂不支持裁剪、翻转、旋转与透明度')
 validateBake(bake)
 const rect=bake.kind==='crop'?cropRect(image.rect,bake.crop).map(value=>Math.round(value*1000)/1000)
  :bake.kind==='rotate'?rotatedImageRect(image.rect):[...image.rect]
 return {kind:'transformExistingImage',sourceSha256,pageId:image.pageId,imageId:image.imageId,expectedImageSha256:image.expectedImageSha256,rect,bake}
}
/** Quarter-turn around the center in PDF user space; odd turns swap the footprint. */
export function rotatedImageRect(rect:readonly [number,number,number,number]):[number,number,number,number] {
 const cx=(rect[0]+rect[2])/2,cy=(rect[1]+rect[3])/2,w=rect[2]-rect[0],h=rect[3]-rect[1]
 return [cx-h/2,cy-w/2,cx+h/2,cy+w/2].map(value=>Math.round(value*1000)/1000) as [number,number,number,number]
}
function validateBake(bake:unknown):asserts bake is PdfImageBake {
 const value=bake as Record<string,unknown>
 const fraction=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=1
 if(!value||typeof value!=='object')throw Error('像素编辑参数无效')
 if(value.kind==='flip'){if(Object.keys(value).sort().join()!=='axis,kind'||!['h','v'].includes(String(value.axis)))throw Error('翻转方向无效');return}
 if(value.kind==='opacity'){const alpha=value.alpha;if(Object.keys(value).sort().join()!=='alpha,kind'||typeof alpha!=='number'||!Number.isFinite(alpha)||alpha<0||alpha>.99||Math.abs(Math.round(alpha*100)-alpha*100)>1e-9)throw Error('不透明度须为 0–99% 的整数百分比');return}
 if(value.kind==='cutout'){const tolerance=value.tolerance;if(Object.keys(value).sort().join()!=='kind,tolerance'||!Number.isInteger(tolerance)||(tolerance as number)<0||(tolerance as number)>100)throw Error('去除背景的容差须为 0–100 的整数');return}
 if(value.kind==='crop'){const c=value.crop as Record<string,number>|undefined;if(Object.keys(value).sort().join()!=='crop,kind'||!c||Object.keys(c).sort().join()!=='b,l,r,t'||![c.l,c.t,c.r,c.b].every(fraction)||c.r!-c.l!<.01||c.b!-c.t!<.01||(c.r!-c.l!>=1&&c.b!-c.t!>=1))throw Error('裁剪范围无效：每边保留比例须在 0–100% 内，且至少裁去一部分');return}
 if(value.kind==='rotate'){if(Object.keys(value).sort().join()!=='kind,quarterTurns'||![1,3].includes(Number(value.quarterTurns)))throw Error('旋转角度无效');return}
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
 if(images){const target=images.find(image=>image.imageId===operation.imageId&&image.pageId===operation.pageId&&image.expectedImageSha256===operation.expectedImageSha256);if(!target?.editable)throw Error(target?.reason??'已有图像身份已变化');if(operation.image!==undefined&&target.replaceable!==true)throw Error(target.replaceReason??'此图像暂不支持替换');if(operation.bake!==undefined){if(target.bakeable!==true)throw Error(target.bakeReason??'此图像暂不支持裁剪、翻转、旋转与透明度');const bake=operation.bake as PdfImageBake,expected=bake.kind==='crop'?cropRect(target.rect,bake.crop):bake.kind==='rotate'?rotatedImageRect(target.rect):target.rect;if((rect as number[]).some((value,i)=>Math.abs(value-expected[i]!)>.05))throw Error('裁剪、翻转、旋转或透明度不能同时移动图像')}}
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
export function bindPdfExistingImagePanel(options:{root:HTMLElement;draft:NativeDraft;pages:()=>PdfPageIdentity[];images:()=>PdfExistingImage[];unavailable:()=>string|null;refresh:()=>Promise<void>;status:(message:string)=>void;readPixels?:(target:PdfImagePixelTarget)=>Promise<PdfImagePixels>}){
 const owner=options.root.ownerDocument,dialog=owner.createElement('dialog');dialog.className='pdf-layout-dialog pdf-existing-image-dialog';dialog.setAttribute('aria-label','编辑已有图像')
 const title=owner.createElement('h3');title.textContent='编辑已有图像'
 const header=owner.createElement('header'),close=owner.createElement('button');close.type='button';close.textContent='×';close.setAttribute('aria-label','关闭编辑已有图像');header.append(title,close)
 const body=owner.createElement('div');body.className='pdf-existing-image-body'
 const hint=owner.createElement('p');hint.textContent='选择原 PDF 的图像对象，移动或调整尺寸，或替换为新图像（保留位置与层级，可同时调整范围）。坐标为原始 PDF 单位，原点在左下角；页面旋转不改变这里的坐标。也可水平/垂直翻转、按比例裁剪或调整透明度（像素编辑不能与移动或替换同批）。保存前请核对实际 PDF 预览。'
 hint.setAttribute('role','region');hint.setAttribute('aria-label','已有图像编辑说明');hint.tabIndex=0;body.append(hint)
 function field(name:string,input:HTMLElement,parent:HTMLElement=body){const label=owner.createElement('label');label.textContent=name;input.setAttribute('aria-label','已有图像'+name);label.append(input);parent.append(label);return input}
 const select=field('选择',owner.createElement('select')) as HTMLSelectElement
 const geometry=owner.createElement('fieldset'),geometryTitle=owner.createElement('legend');geometry.className='pdf-existing-image-geometry';geometryTitle.textContent='位置与尺寸';geometry.append(geometryTitle);body.append(geometry)
 const inputs=['X','Y','宽度','高度'].map(name=>{const input=field(name,owner.createElement('input'),geometry) as HTMLInputElement;input.type='number';input.step='any';return input})
 // 固定源 Picture ▸ 替换图片（replaceExisting）：选择新图像替换像素
 const replaceGroup=owner.createElement('fieldset'),replaceTitle=owner.createElement('legend');replaceTitle.textContent='替换图像';replaceGroup.append(replaceTitle)
 const replaceRow=owner.createElement('div');replaceRow.className='pdf-existing-image-replace'
 const replaceFile=owner.createElement('input');replaceFile.type='file';replaceFile.accept='image/png,image/jpeg';replaceFile.hidden=true;replaceFile.setAttribute('aria-label','选择替换图像')
 const replacePick=owner.createElement('button');replacePick.type='button';replacePick.textContent='替换为新图像…';replacePick.dataset.pdfExistingImageReplace=''
 const replaceClear=owner.createElement('button');replaceClear.type='button';replaceClear.textContent='不替换';replaceClear.hidden=true
 const replaceInfo=owner.createElement('span');replaceInfo.className='pdf-existing-image-replace-info';replaceInfo.textContent='不替换像素'
 replaceInfo.setAttribute('role','status');replaceInfo.setAttribute('aria-label','图像替换状态');replaceInfo.tabIndex=0
 replaceRow.append(replacePick,replaceClear,replaceInfo,replaceFile);replaceGroup.append(replaceRow);body.append(replaceGroup)
 // Fixed-source pixel edits are baked and written back through replaceImage.
 const bakeGroup=owner.createElement('fieldset'),bakeTitle=owner.createElement('legend');bakeTitle.textContent='像素编辑';bakeGroup.append(bakeTitle);body.append(bakeGroup)
 const bakeKind=field('操作',owner.createElement('select'),bakeGroup) as HTMLSelectElement;bakeKind.setAttribute('aria-label','已有图像像素编辑')
 for(const [value,label] of [['','无'],['flip-h','水平翻转'],['flip-v','垂直翻转'],['rotate-cw','顺时针旋转 90°'],['rotate-ccw','逆时针旋转 90°'],['crop','裁剪'],['opacity','透明度'],['cutout','去除背景']])bakeKind.append(new Option(label,value))
 const cropRow=owner.createElement('div');cropRow.className='pdf-existing-image-crop'
 const cropInputs=['左','上','右','下'].map(name=>{const label=owner.createElement('label');label.textContent='裁去'+name+' %';const input=owner.createElement('input');input.type='number';input.min='0';input.max='99';input.step='1';input.value='0';input.setAttribute('aria-label','裁去'+name+'侧百分比');label.append(input);cropRow.append(label);return input})
 const opacityLabel=owner.createElement('label');opacityLabel.textContent='透明度 %';const opacityInput=owner.createElement('input');opacityInput.type='number';opacityInput.min='1';opacityInput.max='100';opacityInput.step='1';opacityInput.value='50';opacityInput.setAttribute('aria-label','图像透明度百分比');opacityLabel.append(opacityInput)
 // 固定源 CutoutDialog：容差 0–100（默认 DEFAULT_CUTOUT_TOLERANCE），与边缘相连、接近边缘颜色的背景变为透明
 const cutoutLabel=owner.createElement('label');cutoutLabel.textContent='去除背景容差';const cutoutInput=owner.createElement('input');cutoutInput.type='number';cutoutInput.min='0';cutoutInput.max='100';cutoutInput.step='1';cutoutInput.value=String(DEFAULT_CUTOUT_TOLERANCE);cutoutInput.setAttribute('aria-label','去除背景容差');cutoutLabel.append(cutoutInput)
 const bakeInfo=owner.createElement('p');bakeInfo.className='pdf-existing-image-replace-info';bakeInfo.setAttribute('role','status');bakeInfo.setAttribute('aria-label','图像像素编辑状态');bakeInfo.tabIndex=0
 bakeGroup.append(cropRow,opacityLabel,cutoutLabel,bakeInfo)
 const visualRow=owner.createElement('div');visualRow.className='pdf-existing-image-visual'
 const visualButtons=(['crop','cutout'] as const).map(kind=>{const button=owner.createElement('button');button.type='button';button.textContent=kind==='crop'?'可视裁剪…':'去除背景…';button.dataset.pdfImageVisual=kind;visualRow.append(button);button.addEventListener('click',()=>{void openVisual(kind)});return button});bakeGroup.append(visualRow)
 const alert=owner.createElement('p');alert.setAttribute('role','alert');alert.setAttribute('aria-label','已有图像校验提示');alert.tabIndex=0;body.append(alert)
 const confirm=owner.createElement('button');confirm.type='button';confirm.textContent='应用';confirm.dataset.pdfExistingImageConfirm=''
 const dismiss=owner.createElement('button');dismiss.type='button';dismiss.textContent='取消'
 const actions=owner.createElement('div');actions.className='pdf-layout-actions';actions.append(dismiss,confirm)
 const footer=owner.createElement('footer');footer.append(actions);dialog.append(header,body,footer);options.root.append(dialog)
 let disposed=false,snapshot='',imageSnapshot='',choices:PdfExistingImage[]=[],replacement:string|undefined
 let fileGeneration=0,loading=false
 let visualDialog:{dispose:()=>void}|undefined
 let opener:HTMLElement|null=null,releaseFocus:(()=>void)|undefined
 function setReplacement(value?:{png:string;width:number;height:number;name:string}){replacement=value?.png;replaceClear.hidden=!value;replaceInfo.textContent=value?`将替换为 ${value.name}（${value.width}×${value.height}）`:'不替换像素';syncBake()}
 function syncReplace(){const image=choices[Number(select.value)];const reason=image&&image.replaceable!==true?image.replaceReason??'此图像暂不支持替换':null;replacePick.disabled=loading||!!reason||!!bakeKind.value;replacePick.title=bakeKind.value?'像素编辑与替换不能同批':reason??'选择 PNG 或 JPEG 替换此图像的像素';if(reason){if(replacement)setReplacement();replaceInfo.textContent=reason}else if(!replacement)replaceInfo.textContent='不替换像素';if(loading)replaceInfo.textContent='正在转换图像，请稍候…';confirm.disabled=loading;dialog.setAttribute('aria-busy',String(loading));syncBake()}
 /** 像素编辑与移动/替换互斥：选中时锁定坐标并隐藏替换。 */
 function syncBake(){const image=choices[Number(select.value)],reason=image&&image.bakeable!==true?image.bakeReason??'此图像暂不支持裁剪、翻转、旋转与透明度':null
  if(reason&&bakeKind.value)bakeKind.value=''
  for(const button of visualButtons)button.disabled=loading||!!reason||replacement!==undefined||!options.readPixels||!!bakeKind.value
  bakeKind.disabled=loading||!!reason||replacement!==undefined;bakeKind.title=replacement!==undefined?'替换与像素编辑不能同批':reason??''
  cropRow.hidden=bakeKind.value!=='crop';opacityLabel.hidden=bakeKind.value!=='opacity';cutoutLabel.hidden=bakeKind.value!=='cutout'
  for(const input of inputs)input.disabled=!!bakeKind.value
  if(bakeKind.value)fill()
  bakeInfo.textContent=reason?reason:bakeKind.value==='cutout'?'去除背景：与图像边缘相连、颜色接近边缘的区域变为透明；容差越大移除越多。保持原位置与层级，保存前请核对实际 PDF 预览。':bakeKind.value?'像素编辑保持原位置与层级（裁剪会按保留比例缩小范围），不能同时移动；保存前请核对实际 PDF 预览。':''}
 function currentBake():PdfImageBake|undefined{
  if(bakeKind.value==='flip-h'||bakeKind.value==='flip-v')return {kind:'flip',axis:bakeKind.value==='flip-h'?'h':'v'}
  if(bakeKind.value==='rotate-cw'||bakeKind.value==='rotate-ccw')return {kind:'rotate',quarterTurns:bakeKind.value==='rotate-cw'?1:3}
  if(bakeKind.value==='opacity'){const percent=Number(opacityInput.value);if(!Number.isInteger(percent)||percent<1||percent>100)throw Error('透明度须为 1–100 的整数百分比');return {kind:'opacity',alpha:(100-percent)/100}}
  if(bakeKind.value==='cutout'){const tolerance=cutoutInput.value.trim()===''?NaN:Number(cutoutInput.value);if(!Number.isInteger(tolerance)||tolerance<0||tolerance>100)throw Error('去除背景的容差须为 0–100 的整数');return {kind:'cutout',tolerance}}
  if(bakeKind.value==='crop'){const [l,t,r,b]=cropInputs.map(input=>input.value.trim()===''?NaN:Number(input.value));if(![l,t,r,b].every(value=>Number.isInteger(value)&&value>=0&&value<=99))throw Error('每侧裁去比例须为 0–99 的整数');return {kind:'crop',crop:{l:l!/100,t:t!/100,r:1-r!/100,b:1-b!/100}}}
  return undefined
 }
 function invalidateLoad(){visualDialog?.dispose();visualDialog=undefined;fileGeneration++;loading=false;confirm.disabled=false;dialog.setAttribute('aria-busy','false')}
 function showError(error:unknown){alert.textContent=error instanceof Error?error.message:String(error);if(dialog.open)alert.focus()}
 function closed(){if(dialog.open)return;invalidateLoad();releaseFocus?.();releaseFocus=undefined;if(opener?.isConnected&&!owner.querySelector('dialog[open]'))opener.focus({preventScroll:true});opener=null}
 function cancel(){if(dialog.open)dialog.close();closed()}
 close.addEventListener('click',cancel);dialog.addEventListener('close',closed);dialog.addEventListener('cancel',event=>{event.preventDefault();cancel()})
 function reason(){return options.unavailable()??(snapshot!==JSON.stringify(options.draft.operations)||imageSnapshot!==JSON.stringify(options.images())?'草稿或图像来源已变化，请重新打开编辑':null)}
 async function openVisual(kind:'crop'|'cutout'){
  if(disposed||!dialog.open||loading||!options.readPixels)return
  const image=choices[Number(select.value)],blocked=reason()
  if(blocked||!image?.bakeable||replacement!==undefined||bakeKind.value){showError(blocked??'当前图像不能进行可视像素编辑');return}
  const generation=++fileGeneration,selected=select.value
  const active=()=>!disposed&&dialog.open&&fileGeneration===generation&&select.value===selected
  const target={sourceSha256:options.draft.identity.sourceSha256,pageId:image.pageId,imageId:image.imageId,expectedImageSha256:image.expectedImageSha256}
  loading=true;syncReplace();alert.textContent='正在读取原图像素…'
  try{
   const [pixels,{showPdfImageDialog}]=await Promise.all([options.readPixels(target),import('./pdf-image-dialogs')])
   if(!active())return
   const changed=reason();if(changed)throw Error(changed)
   if(Object.entries(target).some(([key,value])=>pixels[key as keyof PdfImagePixelTarget]!==value)||!pngBase64(pixels.image)||!digest(pixels.sha256)||!Number.isInteger(pixels.width)||!Number.isInteger(pixels.height)||pixels.width<1||pixels.height<1)throw Error('原图像素回执身份无效')
   loading=false;syncReplace();alert.textContent='';visualButtons[kind==='crop'?0:1]!.focus()
   visualDialog=showPdfImageDialog({owner,kind,image:pixels.image,onCancel(){if(!active())return;fileGeneration++;visualDialog=undefined;syncReplace()},onApply(png,crop){
    if(!active())return
    let staged=false
    try{const changed=reason();if(changed)throw Error(changed);const rect=crop?cropRect(image.rect,crop):image.rect
     const operation=existingImageTransform(target.sourceSha256,image,{x:rect[0],y:rect[1],width:rect[2]-rect[0],height:rect[3]-rect[1]},png)
     validatePdfExistingImage(options.pages(),[operation],options.images());options.draft.setOperations([operation]);staged=true;cancel()
     void options.refresh().then(()=>options.status('已暂存'+(kind==='crop'?'可视裁剪':'去除背景')+'，请核对实际 PDF 预览后保存')).catch(error=>options.status('像素编辑已暂存，但预览刷新失败：'+String(error)))
    }catch(error){if(!staged)showError(error)}
   }})
  }catch(error){if(!active())return;loading=false;syncReplace();showError(error)}
 }
 function fill(){const image=choices[Number(select.value)];if(!image)return;const [x1,y1,x2,y2]=image.rect;[x1,y1,x2-x1,y2-y1].forEach((value,i)=>inputs[i]!.value=String(value))}
 select.addEventListener('change',()=>{invalidateLoad();setReplacement();fill();syncReplace();alert.textContent=''});dismiss.addEventListener('click',cancel);bakeKind.addEventListener('change',()=>{alert.textContent='';syncReplace()})
 replacePick.addEventListener('click',()=>{replaceFile.value='';replaceFile.click()})
 replaceClear.addEventListener('click',()=>{invalidateLoad();setReplacement();syncReplace()})
 replaceFile.addEventListener('change',()=>{
  const file=replaceFile.files?.[0];if(!file||disposed||!dialog.open)return
  const image=choices[Number(select.value)],blocked=reason()
  if(blocked||image?.replaceable!==true||bakeKind.value){showError(blocked??image?.replaceReason??'当前图像不可替换');return}
  const generation=++fileGeneration,selected=select.value
  const active=()=>!disposed&&dialog.open&&fileGeneration===generation&&select.value===selected
  loading=true;alert.textContent='';syncReplace()
  void pngFromImageFile(owner,file).then(result=>{
   if(!active())return
   const changed=reason();if(changed)throw Error(changed)
   loading=false;setReplacement({...result,name:file.name});syncReplace();alert.textContent=''
  }).catch(error=>{if(!active())return;loading=false;syncReplace();showError(error)})
 })
 confirm.addEventListener('click',async()=>{
  if(disposed||!dialog.open)return
  let staged=false
  try{if(loading)throw Error('替换图像正在转换，请稍候');const blocked=reason();if(blocked)throw Error(blocked);const image=choices[Number(select.value)];if(!image)throw Error('请选择已有图像');const bake=currentBake();if(bake){const operation=existingImageBake(options.draft.identity.sourceSha256,image,bake);validatePdfExistingImage(options.pages(),[operation],options.images());options.draft.setOperations([operation]);staged=true;cancel();await options.refresh();options.status('已暂存已有图像'+(bake.kind==='crop'?'裁剪':bake.kind==='flip'?(bake.axis==='h'?'水平翻转':'垂直翻转'):bake.kind==='rotate'?'旋转':bake.kind==='cutout'?'去除背景':'透明度')+'，请核对实际 PDF 预览后保存');return}
  const [x,y,width,height]=inputs.map(input=>input.value.trim()===''?NaN:Number(input.value));const replaced=replacement!==undefined,operation=existingImageTransform(options.draft.identity.sourceSha256,image,{x:x!,y:y!,width:width!,height:height!},replacement);validatePdfExistingImage(options.pages(),[operation],options.images());options.draft.setOperations([operation]);staged=true;cancel();await options.refresh();options.status(replaced?'已暂存已有图像替换，请核对实际 PDF 预览后保存':'已暂存已有图像移动或尺寸调整，请核对实际 PDF 预览后保存')}
  catch(error){if(staged)options.status('图像编辑已暂存，但预览刷新失败：'+(error instanceof Error?error.message:String(error))+'；请重试预览后核对');else showError(error)}
 })
 return {open(){if(disposed||dialog.open)return;invalidateLoad();const blocked=options.unavailable();if(blocked){options.status(blocked);return}if(options.draft.operations.length){options.status(PDF_EXISTING_IMAGE_ALONE_REASON);return}choices=options.images().filter(image=>image.editable);if(!choices.length){options.status('来源没有可编辑的已有图像');return}snapshot=JSON.stringify(options.draft.operations);imageSnapshot=JSON.stringify(options.images());select.replaceChildren();choices.forEach((image,i)=>{const option=owner.createElement('option');option.value=String(i);option.textContent='第 '+(image.pageIndex+1)+' 页 · 图像 '+(i+1);select.append(option)});select.value='0';bakeKind.value='';for(const input of cropInputs)input.value='0';opacityInput.value='50';fill();setReplacement();syncReplace();alert.textContent='';opener=owner.activeElement instanceof HTMLElement?owner.activeElement:null;releaseFocus=installFocusTrap(dialog);dialog.showModal();select.focus()},cancel,incompleteReason(){return dialog.open?'请先完成或取消已有图像编辑':null},refresh(){if(dialog.open&&reason())cancel()},dispose(){if(disposed)return;disposed=true;cancel();dialog.remove()}}
}
