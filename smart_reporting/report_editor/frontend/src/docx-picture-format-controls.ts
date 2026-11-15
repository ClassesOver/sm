import type {Editor} from '@tiptap/core'
import {NodeSelection} from '@tiptap/pm/state'
import {closeHistory} from '@tiptap/pm/history'
import {PICTURE_WRAPS,projectDocxPictureFormat,pictureSizeForSide,resetPictureDimensions,type PictureFormatAnchor,type PictureFormatPatch} from './docx-picture-format'
export type DocxPictureFormatAction='rotateRight'|'rotateLeft'|'flipH'|'flipV'|'size'|'wrap'|'align'|'resetSize'|'position'
/** Host provides actual section content width, in CSS px, for GenOffice Reset Size. */
export function createDocxPictureFormatControls(editor:Editor,anchors:PictureFormatAnchor[],host:HTMLElement,locked:()=>string|null,reportError:(error:unknown)=>void,contentWidth:()=>number=()=>624){
 let active=true,generation=0,modal:HTMLElement|undefined
 const selected=()=>{
  const s=editor.state.selection
  if(!(s instanceof NodeSelection)||s.node.type.name!=='docProtected'||s.node.attrs.blockType!=='image')return null
  const anchor=anchors.find(a=>a.docxIndex===s.node.attrs.docxIndex)
  return anchor?{node:s.node,pos:s.from,anchor}:null
 }
 const reason=()=>locked()??(!editor.isEditable?'当前文档不可编辑':null)??(selected()?.node.attrs.imageReplace?'图片替换与格式修改需分别保存':null)??(selected()?.anchor.imageFormatEditable?null:'请选择支持原生格式保存的整块图片')
 const close=()=>{generation++;modal?.remove();modal=undefined}
 const open=(action:DocxPictureFormatAction)=>{
  try{
   const unavailable=reason();if(unavailable)throw new Error(unavailable)
   close();const target=selected()!,snapshot=editor.state.doc,ticket=generation
   const current=()=>active&&ticket===generation&&!editor.isDestroyed&&!reason()&&editor.state.doc===snapshot&&selected()?.node===target.node&&selected()?.pos===target.pos
   const apply=(patch:PictureFormatPatch)=>{
    if(!current())throw new Error('文档或图片选择已变化，请重新打开图片格式工具')
    const op={kind:'formatImage',blockId:target.anchor.blockId,expectedObjectSha256:target.anchor.expectedObjectSha256,expectedImageSha256:target.anchor.imageSha256,...target.node.attrs.imageFormat,...patch}
    const projected=projectDocxPictureFormat(target.node.toJSON(),target.anchor,op)
    const tr=closeHistory(editor.state.tr).setNodeMarkup(target.pos,undefined,projected.attrs)
    editor.view.dispatch(tr.setSelection(NodeSelection.create(tr.doc,target.pos)));close();editor.view.focus()
   }
   if(action==='rotateRight'||action==='rotateLeft'){apply({rotDeg:((Number(target.node.attrs.imageRotDeg)||0)+(action==='rotateRight'?90:270))%360});return}
   if(action==='flipH'||action==='flipV'){apply({[action]:!target.node.attrs[action==='flipH'?'imageFlipH':'imageFlipV']});return}
   if(action==='resetSize'){
    const image=new Image();image.onload=()=>{try{apply(resetPictureDimensions(image.naturalWidth,image.naturalHeight,contentWidth()))}catch(error){reportError(error)}};image.onerror=()=>reportError(new Error('图片自然尺寸无法读取'));image.src=String(target.node.attrs.imageDataUrl);return
   }
   modal=document.createElement('div');modal.className='docx-picture-format-dialog';modal.setAttribute('role','dialog');modal.setAttribute('aria-label','图片格式');modal.setAttribute('aria-modal','true');Object.assign(modal.style,{position:'fixed',left:'50%',top:'25%',transform:'translateX(-50%)',zIndex:'1000',background:'white',color:'#242424',padding:'20px',border:'1px solid #d0d0d0',borderRadius:'8px',boxShadow:'0 8px 32px #0003',minWidth:'280px',maxHeight:'70vh',overflow:'auto'});modal.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();close();editor.view.focus()}}
   const form=document.createElement('form'),title=document.createElement('h3');title.textContent='图片格式';Object.assign(form.style,{display:'grid',gap:'12px'});form.append(title)
   const input=(label:string,value:number)=>{const row=document.createElement('label'),field=document.createElement('input');row.textContent=label;field.type='number';field.min='1';field.max='10000';field.value=String(value);row.append(field);form.append(row);return field}
   const width=input('宽度（px）',Number(target.node.attrs.imageWidthPx)),height=input('高度（px）',Number(target.node.attrs.imageHeightPx))
   const lock=document.createElement('input');lock.type='checkbox';lock.checked=true;const lockLabel=document.createElement('label');lockLabel.textContent='锁定纵横比';lockLabel.append(lock);form.append(lockLabel)
   const ratio=Number(target.node.attrs.imageWidthPx)/Number(target.node.attrs.imageHeightPx)
   width.onchange=()=>{if(lock.checked)height.value=String(Math.max(1,Math.round(Number(width.value)/ratio)))}
   height.onchange=()=>{if(lock.checked)width.value=String(Math.max(1,Math.round(Number(height.value)*ratio)))}
   const select=(label:string,options:readonly (readonly [string,string])[],value:string)=>{const row=document.createElement('label'),field=document.createElement('select');row.textContent=label;for(const [key,name] of options){const option=document.createElement('option');option.value=key;option.textContent=name;field.append(option)}field.value=value;row.append(field);form.append(row);return field}
   const wrap=select('文字环绕',[['','嵌入型'],...PICTURE_WRAPS.map((v,i)=>[v,['四周型（左）','四周型（右）','紧密型（左）','紧密型（右）','穿越型（左）','穿越型（右）','上下型','衬于文字下方','浮于文字上方'][i]!] as const)],String(target.node.attrs.imageWrap??''))
   const align=select('对齐',[['left','左对齐'],['center','居中'],['right','右对齐']],String(target.node.attrs.imageAlign??'left'))
   const posH=select('水平位置',[['left','左'],['center','中'],['right','右']],String(target.node.attrs.imagePosH??'left'))
   const posV=select('垂直位置',[['top','上'],['center','中'],['bottom','下']],String(target.node.attrs.imagePosV??'top'))
   const submit=document.createElement('button');submit.type='submit';submit.textContent='应用';const cancel=document.createElement('button');cancel.type='button';cancel.textContent='取消';cancel.onclick=close;form.append(submit,cancel)
   // Only the requested group is written: size and alignment changes preserve source anchor geometry.
   form.onsubmit=e=>{e.preventDefault();try{if(action==='size')apply(pictureSizeForSide(Number(width.value),Number(height.value),'w',Number(width.value),false));else if(action==='wrap')apply({wrap:(wrap.value||null) as PictureFormatPatch['wrap']});else if(action==='position')apply({posH:posH.value as PictureFormatPatch['posH'],posV:posV.value as PictureFormatPatch['posV'],wrap:posH.value==='right'?'square-right':'square-left'});else apply({align:align.value as PictureFormatPatch['align']})}catch(error){reportError(error)}}
   const visible:(HTMLInputElement|HTMLSelectElement)[]=action==='size'?[width,height,lock]:action==='wrap'?[wrap]:action==='position'?[posH,posV]:[align]
   for(const field of [width,height,lock,wrap,align,posH,posV])field.closest('label')!.hidden=!visible.includes(field)
   modal.append(form);host.append(modal);(action==='size'?width:action==='wrap'?wrap:action==='position'?posH:align).focus()
  }catch(error){reportError(error)}
 }
 return {reason,open,dispose(){active=false;close()}}
}
