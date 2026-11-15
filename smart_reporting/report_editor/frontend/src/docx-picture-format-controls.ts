import type {Editor} from '@tiptap/core'
import {NodeSelection} from '@tiptap/pm/state'
import {closeHistory} from '@tiptap/pm/history'
import {projectDocxPictureFormat,pictureSizeForSide,resetPictureDimensions,type PictureFormatAnchor,type PictureFormatPatch} from './docx-picture-format'
import {zh} from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/app/zh'
import {twipsToPx} from './vendor/genoffice-docs/apps/docs/src/renderer/units'
export type DocxPictureFormatAction='rotateRight'|'rotateLeft'|'flipH'|'flipV'|'wrap'|'alignLeft'|'alignCenter'|'alignRight'|'resetSize'|'position'
// GenOffice ContextMenu.tsx WRAP_OPTIONS, shared by the Layout and Picture Format ribbons.
const wrapOptions=[
 [null,zh.appWrapInline],['square-left',zh.appWrapSquareLeft],['square-right',zh.appWrapSquareRight],
 ['topBottom',zh.appWrapTopBottom],['behind',zh.appWrapBehind],['front',zh.appWrapFront],
] as const
/** Host provides actual section content width, in CSS px, for GenOffice Reset Size. */
export function createDocxPictureFormatControls(editor:Editor,anchors:PictureFormatAnchor[],locked:()=>string|null,reportError:(error:unknown)=>void,contentWidth:()=>number=()=>624){
 let active=true,generation=0
 let arrangeMenu: { trigger: HTMLButtonElement; dispose: () => void } | undefined
 const selected=()=>{
  const s=editor.state.selection
  if(!(s instanceof NodeSelection)||s.node.type.name!=='docProtected'||s.node.attrs.blockType!=='image')return null
  const anchor=anchors.find(a=>a.docxIndex===s.node.attrs.docxIndex)
  return anchor?{node:s.node,pos:s.from,anchor}:null
 }
 const reason=()=>locked()??(!editor.isEditable?'当前文档不可编辑':null)??(selected()?.node.attrs.imageReplace?'图片替换与格式修改需分别保存':null)??(selected()?.anchor.imageFormatEditable?null:'请选择支持原生格式保存的整块图片')
 const alignment=():PictureFormatPatch['align']=>{
  const picture=selected()
  return picture?picture.node.attrs.imageAlign??'left':null
 }
 const flipped=(action:'flipH'|'flipV')=>Boolean(selected()?.node.attrs[action==='flipH'?'imageFlipH':'imageFlipV'])
 const closeArrangeMenu=()=>{
  const menu=arrangeMenu
  if(!menu)return
  arrangeMenu=undefined
  menu.dispose()
 }
 const close=()=>{generation++;closeArrangeMenu()}
 const writePatch=(target:NonNullable<ReturnType<typeof selected>>,patch:PictureFormatPatch,focusEditor:boolean)=>{
  const pending:PictureFormatPatch={...target.node.attrs.imageFormat,...patch}
  if(patch.wrap===null){delete pending.posH;delete pending.posV}
  const {imagePosH,imagePosV,imageRelH,imageRelV}=target.node.attrs
  if(patch.wrap&&!pending.posH&&imageRelH==='margin'&&imageRelV==='margin'&&imagePosH&&imagePosV){
   pending.posH=imagePosH
   pending.posV=imagePosV
  }
  // The two square choices move the object to the named side. Keep the vertical preset.
  if(pending.posH&&patch.wrap==='square-left'&&pending.posH==='right')pending.posH='left'
  if(pending.posH&&patch.wrap==='square-right')pending.posH='right'
  const op={kind:'formatImage',blockId:target.anchor.blockId,expectedObjectSha256:target.anchor.expectedObjectSha256,expectedImageSha256:target.anchor.imageSha256,...pending}
  const projected=projectDocxPictureFormat(target.node.toJSON(),target.anchor,op)
  const tr=closeHistory(editor.state.tr).setNodeMarkup(target.pos,undefined,projected.attrs)
  close()
  editor.view.dispatch(tr.setSelection(NodeSelection.create(tr.doc,target.pos)))
  if(focusEditor)editor.view.focus()
 }
 const size=()=>{
  const target=selected()
  if(!target)return null
  const width=Number(target.node.attrs.imageWidthPx),height=Number(target.node.attrs.imageHeightPx)
  if(![width,height].every(value=>Number.isFinite(value)&&value>0))return null
  const snapshot=editor.state.doc
  return {
   key:target.anchor.blockId,width,height,
   resize(side:'w'|'h',twips:number,lockAspect:boolean){
    const current=selected()
    if(!active||editor.isDestroyed||reason()||editor.state.doc!==snapshot||current?.node!==target.node||current.pos!==target.pos)return
    try{writePatch(target,pictureSizeForSide(width,height,side,twipsToPx(twips),lockAspect),false)}catch(error){reportError(error)}
   },
  }
 }
 const open=(action:DocxPictureFormatAction,trigger?:HTMLButtonElement)=>{
  try{
   const arrange=action==='position'||action==='wrap'
   if(arrange&&arrangeMenu&&arrangeMenu.trigger===trigger){close();return}
   const unavailable=reason();if(unavailable)throw new Error(unavailable)
   close();const target=selected()!,snapshot=editor.state.doc,ticket=generation
   const current=()=>active&&ticket===generation&&!editor.isDestroyed&&!reason()&&editor.state.doc===snapshot&&selected()?.node===target.node&&selected()?.pos===target.pos
   const apply=(patch:PictureFormatPatch)=>{
    if(!current())throw new Error('文档或图片选择已变化，请重新打开图片格式工具')
    writePatch(target,patch,true)
   }
   if(arrange){
    const wrapper=trigger?.parentElement
    if(!trigger||!wrapper)return
    const panel=document.createElement('div'),grid=document.createElement('div')
    panel.className='layout-menu'
    panel.dataset.rbPanel=''
    panel.setAttribute('role','group')
    panel.setAttribute('aria-label',action==='position'?'位置':'环绕文字')
    grid.className='pos-grid'
    const button=(label:string,pressed:boolean,patch:PictureFormatPatch)=>{
     const item=document.createElement('button')
     item.type='button'
     item.classList.toggle('active',pressed)
     item.setAttribute('aria-label',label)
     item.setAttribute('aria-pressed',String(pressed))
     item.title=label
     item.onclick=()=>{try{apply(patch)}catch(error){close();reportError(error)}}
     return item
    }
    const {imageWrap,imagePosH,imagePosV}=target.node.attrs
    const wrapButton=(wrap:typeof wrapOptions[number][0],label:string)=>{
     const item=button(label,(imageWrap??null)===wrap,{wrap})
     const caption=document.createElement('b')
     caption.textContent=label
     item.append(caption)
     return item
    }
    if(action==='position'){
     const inline=wrapButton(null,zh.appWrapInline)
     inline.dataset.position='inline'
     panel.append(inline,grid)
     for(const [v,vertical] of [['top','顶部'],['center','中部'],['bottom','底部']] as const){
      for(const [h,horizontal] of [['left','左侧'],['center','居中'],['right','右侧']] as const){
       const item=button(vertical+horizontal,!!imageWrap&&imagePosH===h&&imagePosV===v,{posH:h,posV:v,wrap:h==='right'?'square-right':'square-left'})
       item.classList.add('pos-cell',`ph-${h}`,`pv-${v}`)
       const dot=document.createElement('span')
       dot.className='pos-dot'
       item.append(dot);grid.append(item)
      }
     }
    }else{
     for(const [wrap,label] of wrapOptions){
      const item=wrapButton(wrap,label)
      item.dataset.wrap=wrap??'inline'
      panel.append(item)
     }
    }
    const doc=trigger.ownerDocument
    const onOutside=(event:Event)=>{if(!wrapper.contains(event.target as Node))closeArrangeMenu()}
    const onTransaction=()=>{if(!current())closeArrangeMenu()}
    arrangeMenu={trigger,dispose:()=>{
     doc.removeEventListener('pointerdown',onOutside,true)
     doc.removeEventListener('focusin',onOutside)
     editor.off('transaction',onTransaction)
     trigger.setAttribute('aria-expanded','false')
     panel.remove()
    }}
    panel.onkeydown=event=>{
     if(event.key!=='Escape')return
     event.preventDefault()
     event.stopPropagation()
     closeArrangeMenu()
     trigger.focus()
    }
    trigger.setAttribute('aria-expanded','true')
    wrapper.append(panel)
    doc.addEventListener('pointerdown',onOutside,true)
    doc.addEventListener('focusin',onOutside)
    editor.on('transaction',onTransaction)
    const selectedItem=panel.querySelector<HTMLButtonElement>('[aria-pressed="true"]')??panel.querySelector<HTMLButtonElement>('button')
    selectedItem?.focus({preventScroll:true})
    return
   }
   if(action==='rotateRight'||action==='rotateLeft'){apply({rotDeg:((Number(target.node.attrs.imageRotDeg)||0)+(action==='rotateRight'?90:270))%360});return}
   if(action==='flipH'||action==='flipV'){apply({[action]:!target.node.attrs[action==='flipH'?'imageFlipH':'imageFlipV']});return}
   if(action==='alignLeft'||action==='alignCenter'||action==='alignRight'){
    apply({align:action==='alignLeft'?null:action==='alignCenter'?'center':'right'})
    return
   }
   if(action==='resetSize'){
    const image=new Image();image.onload=()=>{try{apply(resetPictureDimensions(image.naturalWidth,image.naturalHeight,contentWidth()))}catch(error){reportError(error)}};image.onerror=()=>reportError(new Error('图片自然尺寸无法读取'));image.src=String(target.node.attrs.imageDataUrl);return
   }
  }catch(error){reportError(error)}
 }
 return {reason,alignment,flipped,size,open,closeArrangeMenu,dispose(){active=false;close()}}
}
