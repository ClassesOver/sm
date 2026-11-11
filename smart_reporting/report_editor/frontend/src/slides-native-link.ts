/** 固定源LinkDialog的对象级适配；本地静态放映暂不执行链接。 */
export type SlidesLinkTarget={kind:'url';url:string}|{kind:'slide';slideIndex:number}
export type SlidesLinkEdit={slideIndex:number;elementId:string;target:SlidesLinkTarget|null}
export type SlidesLinkSourceSlide={elements:readonly {id:string;type?:string;linkEditable?:boolean}[]}
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
function fail(reason:string):never{throw Error(reason)}
function fields(v:unknown,keys:string[]):asserts v is Record<string,unknown>{if(!record(v)||Object.keys(v).sort().join()!==[...keys].sort().join())fail('链接草稿字段结构无效；原草稿已保留')}
function canonicalUrl(value:unknown):string{
 if(typeof value!=='string'||!value.trim()||value.trim().length>2048||/[\u0000-\u001f\u007f-\u009f\\]/.test(value))fail('网址无效或超过2048字符')
 const text=value.trim();if(/\s/.test(text))fail('网址不能包含空白字符')
 let parsed:URL;try{parsed=new URL(text)}catch{return fail('请输入完整的HTTP、HTTPS或mailto地址')}
 if(!['http:','https:','mailto:'].includes(parsed.protocol)||(['http:','https:'].includes(parsed.protocol)&&!/^https?:\/\//i.test(text))||(parsed.protocol==='mailto:'&&!parsed.pathname))fail('仅支持HTTP、HTTPS或mailto链接')
 return text
}
function target(value:unknown,count:number):SlidesLinkTarget|null{
 if(value===null)return null
 if(!record(value))fail('链接目标结构无效')
 if(value.kind==='url'){fields(value,['kind','url']);return {kind:'url',url:canonicalUrl(value.url)}}
 if(value.kind==='slide'){
  fields(value,['kind','slideIndex'])
  if(typeof value.slideIndex!=='number'||!Number.isInteger(value.slideIndex)||value.slideIndex<0||value.slideIndex>=count)fail('链接目标幻灯片不存在')
  return {kind:'slide',slideIndex:value.slideIndex}
 }
 return fail('链接仅支持网址、来源幻灯片或移除')
}
function array(value:unknown):unknown[]{if(value===undefined)return [];if(!Array.isArray(value))fail('链接草稿冲突信息无效；原草稿已保留');return value}
export function validateSlidesLinkDraft(changes:unknown,slides:readonly SlidesLinkSourceSlide[]):SlidesLinkEdit[]{
 if(!record(changes))fail('链接草稿结构无效；原草稿已保留')
 const items=array(changes.linkEdits),deleted=array(changes.deletedSlides),deletions=array(changes.deletions),groups=array(changes.groupEdits),newSlides=array(changes.newSlides),seen=new Set<string>(),result:SlidesLinkEdit[]=[]
 if(items.length>50)fail('链接草稿最多50项；原草稿已保留')
 for(const item of items){
  fields(item,['slideIndex','elementId','target'])
  if(typeof item.slideIndex!=='number'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=slides.length||typeof item.elementId!=='string'||!item.elementId.length||item.elementId.length>200)fail('链接来源对象无效；原草稿已保留')
  const index=item.slideIndex,key=index+':'+item.elementId,source=slides[index]!.elements.filter(e=>e.id===item.elementId)
  if(seen.has(key)||deleted.includes(index)||source.length!==1||source[0]!.linkEditable!==true||!['text','shape','picture'].includes(source[0]!.type??'')||deletions.some(d=>record(d)&&d.slideIndex===index&&d.elementId===item.elementId)||groups.some(g=>record(g)&&g.slideIndex===index)||newSlides.some(s=>record(s)&&s.duplicateOf===index))fail('链接来源重复、只读、删除或存在组合/复制冲突；原草稿已保留')
  const link=target(item.target,slides.length)
  if(link?.kind==='slide'&&(deleted.includes(link.slideIndex)||newSlides.some(s=>record(s)&&s.duplicateOf===link.slideIndex)))fail('链接目标幻灯片已删除或存在复制冲突；原草稿已保留')
  seen.add(key);result.push({slideIndex:index,elementId:item.elementId,target:link})
 }
 return result
}
export type SlidesLinkOptions={elementLink:SlidesLinkTarget|null;slides:readonly unknown[];onApply:(target:SlidesLinkTarget|null)=>void;onCancel:()=>void}
export function openSlidesLink(host:HTMLElement,options:SlidesLinkOptions):{dispose():void}{
 const previous=document.activeElement instanceof HTMLElement?document.activeElement:undefined,dialog=document.createElement('dialog')
 dialog.className='slides-native-link-dialog';dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.setAttribute('aria-label','对象超链接')
 Object.assign(dialog.style,{maxWidth:'90vw',width:'440px',padding:'24px',border:'1px solid #cad4df',borderRadius:'12px'})
 const heading=document.createElement('h2');heading.textContent='对象超链接'
 const mode=document.createElement('select');mode.dataset.linkKind='';mode.setAttribute('aria-label','链接类型')
 for(const [value,label] of [['url','网址或邮箱'],['slide','本文档幻灯片']]){const option=document.createElement('option');option.value=value!;option.textContent=label!;mode.append(option)}
 const url=document.createElement('input');url.type='text';url.dataset.linkUrl='';url.setAttribute('aria-label','链接网址');url.placeholder='https://example.com';url.value=options.elementLink?.kind==='url'?options.elementLink.url:'https://'
 const slide=document.createElement('select');slide.dataset.linkSlide='';slide.setAttribute('aria-label','目标幻灯片')
 options.slides.forEach((item,index)=>{const option=document.createElement('option'),source=record(item)?item:{},value=typeof source.slideIndex==='number'&&Number.isInteger(source.slideIndex)?source.slideIndex:index;option.value=String(value);option.textContent=typeof source.label==='string'?source.label:'第 '+String(value+1)+' 页';option.disabled=source.deleted===true;slide.append(option)})
 mode.value=options.elementLink?.kind==='slide'?'slide':'url';if(options.elementLink?.kind==='slide')slide.value=String(options.elementLink.slideIndex)
 const update=()=>{url.hidden=mode.value!=='url';slide.hidden=mode.value!=='slide'};mode.addEventListener('change',update);update()
 const note=document.createElement('p');note.textContent='修改将保存到PPTX；当前本地静态放映暂不执行链接。'
 const error=document.createElement('p');error.setAttribute('role','alert')
 const actions=document.createElement('div');Object.assign(actions.style,{display:'flex',justifyContent:'flex-end',gap:'12px',marginTop:'16px'})
 let active=true
 const dispose=()=>{if(!active)return;active=false;dialog.remove();if(previous?.isConnected)previous.focus()}
 const cancel=()=>{if(!active)return;dispose();options.onCancel()}
 const apply=(remove=false)=>{
  if(!active)return
  try{
   let link:SlidesLinkTarget|null=null
   if(!remove){if(mode.value==='url')link={kind:'url',url:canonicalUrl(url.value)};else{const selected=slide.selectedOptions[0];if(!selected||selected.disabled)fail('请选择有效的目标幻灯片');link={kind:'slide',slideIndex:Number(selected.value)}}}
   options.onApply(link)
  }catch(cause){error.textContent=cause instanceof Error?cause.message:'链接修改未能应用，请重新选择后重试。';return}
  dispose()
 }
 const button=(label:string,click:()=>void)=>{const node=document.createElement('button');node.type='button';node.textContent=label;node.addEventListener('click',click);return node}
 if(options.elementLink){const remove=button('移除链接',()=>apply(true));remove.dataset.linkRemove='';actions.append(remove)}
 const ok=button('确定',()=>apply());ok.dataset.linkConfirm='';actions.append(button('取消',cancel),ok)
 dialog.append(heading,mode,url,slide,note,error,actions);host.append(dialog)
 dialog.addEventListener('cancel',event=>{event.preventDefault();cancel()});dialog.addEventListener('close',cancel);dialog.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();cancel()}else if(event.key==='Enter'&&event.target===url){event.preventDefault();apply()}})
 if(typeof dialog.showModal==='function')dialog.showModal();else dialog.setAttribute('open','')
 ;(mode.value==='url'?url:slide).focus()
 return {dispose}
}
