import type {PDFPageProxy} from 'pdfjs-dist'
import type {NativeDraft,NativeOperation} from './native-draft'
import type {PdfModel,PdfPageIdentity,PdfRect} from './pdf-operations'
import {renderStaticFormText,renderStaticFormMark} from './vendor/genoffice-pdf/renderer/static-form-fill'
import {checkboxWidgetAt,printedBoxAt,markRectForBox} from './vendor/genoffice-pdf/renderer/form-mark-target'
import {collectDetectInput} from './vendor/genoffice-pdf/renderer/form-detect'
import {showPdfObjectDialog} from './pdf-object-dialog'
export interface PdfStaticFill {id:string;kind:'text'|'check'|'cross';pageIndex:number;rect:PdfRect;text?:string;fontSize?:number;color?:string;align?:'left'|'center'|'right';editable?:boolean;expectedImageSha256?:string;reason?:string}
export function validatePdfStaticFill(pages:PdfPageIdentity[],operations:NativeOperation[]){
 const ids=new Set<string>()
 for(const op of operations.filter(op=>['setStaticFill','removeStaticFill'].includes(op.kind))){
  const page=pages.find(page=>page.pageId===op.pageId)
  const allowed=['kind','sourceSha256','pageId','id','expectedImageSha256',...(op.kind==='setStaticFill'?['fillKind','rect','image','text','fontSize','color','align']:[])]
  if(!page||page.blank||op.sourceSha256!==page.pageId.match(/^sha256:([a-f0-9]{64}):page:/)?.[1]||typeof op.id!=='string'||!/^[a-zA-Z0-9_-]{1,80}$/.test(op.id)||ids.has(op.id)||Object.keys(op).some(key=>!allowed.includes(key)))throw Error('静态填写来源或身份无效')
  ids.add(op.id)
  if(op.expectedImageSha256!==undefined&&(typeof op.expectedImageSha256!=='string'||!/^[a-f0-9]{64}$/.test(op.expectedImageSha256)))throw Error('静态填写图像身份无效')
  if(op.kind==='removeStaticFill'){if(!op.expectedImageSha256)throw Error('静态填写图像身份无效');continue}
  const rect=op.rect as number[],b=page.cropBox
  if(!Array.isArray(rect)||rect.length!==4||!rect.every(Number.isFinite)||rect[2]!-rect[0]!<3||rect[3]!-rect[1]!<3||rect[0]!<b.x||rect[1]!<b.y||rect[2]!>b.x+b.width||rect[3]!>b.y+b.height)throw Error('静态填写超出页面范围')
  if(!['text','check','cross'].includes(String(op.fillKind))||typeof op.image!=='string'||!op.image.startsWith('iVBORw0KGgo')||op.image.length>6_000_000)throw Error('静态填写位图无效')
  if(op.fillKind==='text'){
   if(typeof op.text!=='string'||!op.text.trim()||op.text.length>1000||/[\p{Cc}\p{Cf}\u2028\u2029]/u.test(op.text.replace(/\n/g,''))||typeof op.fontSize!=='number'||!Number.isFinite(op.fontSize)||op.fontSize<6||op.fontSize>72||typeof op.color!=='string'||!/^#[a-f0-9]{6}$/i.test(op.color)||!['left','center','right'].includes(String(op.align)))throw Error('静态填写文字配置无效')
  }else if(op.text!==undefined||op.fontSize!==undefined||op.align!==undefined)throw Error('勾叉不能包含文字配置')
 }
 if(ids.size&&operations.some(op=>['replaceText','insertText','setPageSize','mergePages','splitPages','createFormField','transformExistingImage','redact','cropPage'].includes(op.kind)))throw Error('静态填写与正文、裁切、设计或涂黑请分别保存')
}
export function staticFillsForDraft(model:Pick<PdfModel,'staticFormFills'|'pages'>,operations:NativeOperation[]):PdfStaticFill[]{
 const result=(model.staticFormFills??[]).map(record=>({...record}))
 for(const op of operations){
  if(!['setStaticFill','removeStaticFill'].includes(op.kind))continue
  const index=result.findIndex(record=>record.id===op.id);if(index>=0)result.splice(index,1)
  if(op.kind==='setStaticFill')result.push({id:String(op.id),kind:op.fillKind as PdfStaticFill['kind'],pageIndex:model.pages.find(page=>page.pageId===op.pageId)?.index??-1,rect:op.rect as PdfRect,...(op.fillKind==='text'?{text:String(op.text),fontSize:Number(op.fontSize),color:String(op.color),align:op.align as PdfStaticFill['align']}:{color:'#111111'}),editable:true,...(typeof op.expectedImageSha256==='string'?{expectedImageSha256:op.expectedImageSha256}:{})})
 }
 return result.filter(record=>!operations.some(op=>op.kind==='deletePage'&&op.pageId===model.pages.find(page=>page.index===record.pageIndex)?.pageId))
}
export function missingRequiredFormFields(model:PdfModel,operations:NativeOperation[]){
 const names=new Set((model.formDesignWidgets??[]).filter(widget=>widget.required).map(widget=>widget.fieldName))
 return (model.formFields??[]).filter(field=>{if(!names.has(field.name))return false;const op=operations.find(op=>op.kind==='setFormValue'&&op.name===field.name);const value=op?(field.kind==='checkbox'?op.checked:op.value):field.value;return field.kind==='checkbox'?!value:!String(value??'').trim()}).map(field=>field.name)
}
export function bindPdfStaticFill(options:{root:HTMLElement;draft:NativeDraft;model:()=>PdfModel;pages:()=>PdfPageIdentity[];getPage:(index:number)=>Promise<PDFPageProxy>;unavailable:()=>string|null;start:()=>void;stop:()=>void;refresh:()=>Promise<void>;status:(text:string)=>void;focusField:(name:string)=>void}){
 const owner=options.root.ownerDocument
 let disposed=false,dialog:HTMLDialogElement|undefined,pending:{kind:PdfStaticFill['kind'];image:string;width:number;height:number;text?:string;fontSize?:number;color?:string;align?:PdfStaticFill['align'];target?:PdfStaticFill}|undefined,snapshot='',epoch=0
 const same=()=>!disposed&&!options.unavailable()&&snapshot===JSON.stringify(options.draft.operations)
 function close(){const view=dialog;dialog=undefined;if(view?.open)view.close();view?.remove()}
 function cancel(){epoch++;pending=undefined;close();options.stop()}
 function error(error:unknown){options.status(error instanceof Error?error.message:String(error))}
 function stage(pageId:string,rect:PdfRect,config:NonNullable<typeof pending>){
  if(!same())throw Error('来源或草稿已变化，请重新开始静态填写')
  if(config.target&&options.model().pages.find(page=>page.pageId===pageId)?.index!==config.target.pageIndex)throw Error('已保存的静态填写请在原来源页重新放置')
  const id=config.target?.id??crypto.randomUUID(),target=options.model().staticFormFills?.find(record=>record.id===id)
  const operation:NativeOperation={kind:'setStaticFill',sourceSha256:options.model().sourceSha256,pageId,id,fillKind:config.kind,rect,image:config.image,...(target?.expectedImageSha256?{expectedImageSha256:target.expectedImageSha256}:{}),...(config.kind==='text'?{text:config.text!,fontSize:config.fontSize!,color:config.color!,align:config.align!}:{})}
  const operations=[...options.draft.operations.filter(op=>!(['setStaticFill','removeStaticFill'].includes(op.kind)&&op.id===id)),operation]
  validatePdfStaticFill(options.model().pages,operations);options.draft.setOperations(operations);cancel();void options.refresh().catch(cause=>options.status('静态填写草稿已保留，刷新失败：'+String(cause)))
 }
 function openText(target?:PdfStaticFill){
  if(disposed||options.unavailable())return
  cancel();snapshot=JSON.stringify(options.draft.operations)
  const view=owner.createElement('dialog');dialog=view;view.className='pdf-layout-dialog pdf-static-text-dialog pdf-static-fill-dialog';view.setAttribute('aria-label',target?'编辑静态填写':'添加静态填写文字')
  const hint=owner.createElement('p');hint.textContent='文字和标记会直接加入页面，保存后可在本编辑器中继续修改；不会创建可交互的表单字段。';view.append(hint)
  function label(name:string,control:HTMLElement){const row=owner.createElement('label');row.textContent=name;control.setAttribute('aria-label','静态填写'+name);row.append(control);view.append(row)}
  const text=owner.createElement('textarea');text.rows=4;text.maxLength=1000;text.value=target?.text??'';label('文字',text)
  const size=owner.createElement('input');size.type='number';size.min='6';size.max='72';size.value=String(target?.fontSize??14);label('字号',size)
  const color=owner.createElement('input');color.type='color';color.value=target?.color??'#111111';label('颜色',color)
  const align=owner.createElement('select');for(const [value,name]of [['left','左对齐'],['center','居中'],['right','右对齐']]){const item=owner.createElement('option');item.value=value!;item.textContent=name!;align.append(item)}align.value=target?.align??'left';label('对齐',align)
  const alert=owner.createElement('p');alert.setAttribute('role','alert');const actions=owner.createElement('div');actions.className='pdf-layout-actions'
  const dismiss=owner.createElement('button');dismiss.type='button';dismiss.textContent='取消';dismiss.onclick=cancel;actions.append(dismiss)
  function config(){if(!same())throw Error('来源或草稿已变化，请关闭后重试');const value=Number(size.value);if(!text.value.trim()||text.value.length>1000||!Number.isFinite(value)||value<6||value>72)throw Error('请填写文字并选择 6–72 的字号');const rendered=renderStaticFormText(text.value,value,color.value,align.value as CanvasTextAlign);if(!rendered||rendered.width*4>2000||rendered.height*4>2000)throw Error('静态文字过大，请缩短文字或减小字号');return {kind:'text' as const,image:rendered.image,width:rendered.width,height:rendered.height,text:text.value.trim(),fontSize:value,color:color.value,align:align.value as PdfStaticFill['align'],...(target?{target}:{})}}
  if(target){const keep=owner.createElement('button');keep.type='button';keep.textContent='更新原位置';keep.onclick=()=>{try{const page=options.model().pages.find(page=>page.index===target.pageIndex)!;stage(page.pageId,target.rect,config())}catch(cause){alert.textContent=String(cause)}};actions.append(keep)}
  const apply=owner.createElement('button');apply.type='button';apply.textContent=target?'重新放置':'确定并选择落点';apply.dataset.pdfStaticFillConfirm='';apply.onclick=()=>{try{pending=config();close();options.start();options.status('请点击页面放置静态文字，Escape 取消')}catch(cause){alert.textContent=cause instanceof Error?cause.message:String(cause)}};actions.append(apply)
  view.append(alert,actions);options.root.append(view);view.addEventListener('close',()=>{if(dialog===view){dialog=undefined;view.remove()}});showPdfObjectDialog(view,text)
 }
 async function place(page:PdfPageIdentity,point:number[]){
  if(!pending||!same())return
  const token=++epoch,config=pending
  try{
   if(config.kind!=='text'){
    const widget=checkboxWidgetAt((options.model().formDesignWidgets??[]).filter(widget=>widget.pageIndex===page.index).map(widget=>({...widget,kind:widget.fieldKind??'',readOnly:!options.model().formFields?.some(field=>field.name===widget.fieldName&&field.editable)})),point[0]!,point[1]!)
    if(widget){
     const field=options.model().formFields!.find(field=>field.name===widget.fieldName)!,operation={kind:'setFormValue',fieldId:field.fieldId,expectedFieldSha256:field.expectedFieldSha256,name:field.name,fieldKind:'checkbox',checked:true}
     options.draft.setOperations([...options.draft.operations.filter(op=>!(op.kind==='setFormValue'&&op.name===field.name)),operation]);cancel();await options.refresh();return
    }
    const shapes=(await collectDetectInput(await options.getPage(page.index))).shapes
    if(token!==epoch||pending!==config||!same())return
    const box=printedBoxAt(shapes,point[0]!,point[1]!);if(box){const rect=markRectForBox(box),image=renderStaticFormMark(config.kind,rect[2]-rect[0]);if(!image)throw Error('勾叉位图无法绘制');stage(page.pageId,rect,{...config,image:image.image,width:image.width,height:image.height});return}
   }
   const rotation=((page.rotation%360)+360)%360,width=rotation%180?config.height:config.width,height=rotation%180?config.width:config.height,b=page.cropBox
   if(width>b.width||height>b.height)throw Error('静态填写大于页面，请减小字号')
   const x=Math.min(Math.max(b.x,point[0]!-width/2),b.x+b.width-width),y=Math.min(Math.max(b.y,point[1]!-height/2),b.y+b.height-height)
   stage(page.pageId,[x,y,x+width,y+height],config)
  }catch(cause){error(cause)}
 }
 function openManager(){
  if(disposed||options.unavailable())return;cancel();snapshot=JSON.stringify(options.draft.operations)
  const view=owner.createElement('dialog');dialog=view;view.className='pdf-layout-dialog pdf-extract-dialog pdf-static-fill-dialog';view.setAttribute('aria-label','管理静态填写')
  const body=owner.createElement('div');body.className='pdf-extract-body';const hint=owner.createElement('p');hint.textContent='仅管理静态文字、勾号和叉号。原生表单字段使用“填写可填写域”。重新放置限原来源页；更新或删除后请校验当前修改查看实际 PDF。删除不是安全擦除。';body.append(hint)
  for(const fill of staticFillsForDraft(options.model(),options.draft.operations)){
   const row=owner.createElement('p');row.dataset.pdfStaticFillKind=fill.kind;row.dataset.pdfStaticFillId=fill.id;row.textContent=`第 ${options.pages().findIndex(page=>page.index===fill.pageIndex)+1} 页 · ${fill.kind==='text'?fill.text:fill.kind==='check'?'勾号':'叉号'} `
   const page=options.model().pages.find(page=>page.index===fill.pageIndex)!
   const edit=owner.createElement('button');edit.type='button';edit.textContent=fill.kind==='text'?'编辑文字/位置':'重新放置';edit.disabled=fill.editable===false;edit.onclick=()=>{if(!same())return;if(fill.kind==='text'){close();openText(fill)}else{const image=renderStaticFormMark(fill.kind);if(image){pending={kind:fill.kind,image:image.image,width:image.width,height:image.height,target:fill};close();options.start();options.status('请点击页面重新放置勾号或叉号，Escape 取消')}}}
   const remove=owner.createElement('button');remove.type='button';remove.textContent='删除';remove.disabled=fill.editable===false;remove.onclick=()=>{if(!same())return;const original=options.model().staticFormFills?.find(record=>record.id===fill.id);const operations=options.draft.operations.filter(op=>!(['setStaticFill','removeStaticFill'].includes(op.kind)&&op.id===fill.id));if(original?.expectedImageSha256)operations.push({kind:'removeStaticFill',sourceSha256:options.model().sourceSha256,pageId:page.pageId,id:fill.id,expectedImageSha256:original.expectedImageSha256});options.draft.setOperations(operations);cancel();void options.refresh().catch(error)}
   const geometry=owner.createElement('button');geometry.type='button';geometry.textContent='调整位置/大小';geometry.disabled=fill.editable===false
   geometry.onclick=()=>{
    if(!same())return;close()
    const view=owner.createElement('dialog');dialog=view;view.className='pdf-layout-dialog pdf-static-text-dialog pdf-static-fill-dialog';view.setAttribute('aria-label','静态填写位置与大小')
    const inputs=[fill.rect[0],fill.rect[1],fill.rect[2]-fill.rect[0],fill.rect[3]-fill.rect[1]].map((value,index)=>{const row=owner.createElement('label'),input=owner.createElement('input');row.textContent=['左边 X','底边 Y','宽度','高度'][index]!;input.type='number';input.step='any';input.value=String(value);input.setAttribute('aria-label','静态填写'+row.textContent);row.append(input);view.append(row);return input})
    const hint=owner.createElement('p');hint.textContent='坐标和尺寸为来源 PDF 单位（左下角原点）。保存后重新编辑会保留此尺寸；请核对实际 PDF 预览。';const alert=owner.createElement('p');alert.setAttribute('role','alert')
    const apply=owner.createElement('button');apply.type='button';apply.textContent='暂存位置与大小';apply.onclick=()=>{try{const [x,y,w,h]=inputs.map(input=>Number(input.value)),image=fill.kind==='text'?renderStaticFormText(fill.text??'',fill.fontSize,fill.color,fill.align):renderStaticFormMark(fill.kind);if(!image)throw Error('静态填写位图无法重建');stage(page.pageId,[x!,y!,x!+w!,y!+h!],{kind:fill.kind,image:image.image,width:image.width,height:image.height,target:fill,...(fill.kind==='text'?{text:fill.text!,fontSize:fill.fontSize!,color:fill.color!,align:fill.align!}:{})})}catch(cause){alert.textContent=cause instanceof Error?cause.message:String(cause)}}
    const dismiss=owner.createElement('button');dismiss.type='button';dismiss.textContent='取消';dismiss.onclick=cancel;view.append(hint,alert,dismiss,apply);options.root.append(view);showPdfObjectDialog(view,inputs[0]!)
   }
   row.append(edit,geometry,remove);body.append(row)
  }
  if(!body.querySelector('button')){const empty=owner.createElement('p');empty.textContent='尚无静态填写';body.append(empty)}
  const dismiss=owner.createElement('button');dismiss.type='button';dismiss.textContent='关闭';dismiss.onclick=cancel;view.append(body,dismiss);options.root.append(view);view.addEventListener('close',()=>{if(dialog===view){dialog=undefined;view.remove()}});showPdfObjectDialog(view,dismiss)
 }
 const key=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!event.isComposing&&event.keyCode!==229&&!event.defaultPrevented&&pending){event.preventDefault();cancel();options.status('已取消静态填写')}}
 options.root.addEventListener('keydown',key)
 return {openText,openManager,place,cancel,mark(kind:'check'|'cross'){if(disposed||options.unavailable())return;cancel();snapshot=JSON.stringify(options.draft.operations);const image=renderStaticFormMark(kind);if(image){pending={kind,image:image.image,width:image.width,height:image.height};options.start();options.status('请点击页面放置'+(kind==='check'?'勾号':'叉号')+'，Escape 取消')}},complete(){cancel();const missing=missingRequiredFormFields(options.model(),options.draft.operations);options.status(missing.length?'填写完成提示：以下原生必填域尚未填写（仍可保存/下载）：'+missing.join('、'):'填写已完成，请保存新修订并核对实际 PDF');if(missing.length)options.focusField(missing[0]!)},incompleteReason(){return dialog?.open?'请完成或取消静态填写对话框':pending?'请放置或取消静态填写':null},update(){if((pending||dialog?.open)&&!same())cancel()},dispose(){if(disposed)return;cancel();disposed=true;options.root.removeEventListener('keydown',key)}}
}
