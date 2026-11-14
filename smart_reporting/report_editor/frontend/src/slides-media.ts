/** 固定源媒体容器分类的浏览器适配；字节直接进入现有 NativeDraft。 */
import { VIDEO_EXTS, AUDIO_EXTS, fileExt } from '../../../reporting/slides_engine/bridge/source-media/media-kinds'
export type SlideMediaInsertion = { slideIndex:number;kind:'video'|'audio';extension:string;bytesBase64:string;name?:string;center?:{x:number;y:number};poster?:{bytesBase64:string;sha256:string} }
export type SlideMediaSource = { sourceId:string;kind:'video'|'audio';sha256:string|null;size:number|null;dataUrl?:string;warning?:string;reason?:string }
const fail: () => never = () => {throw Error('音视频草稿无效或超过预算；原草稿已保留')}
export function validateSlideMediaInsertions(changes:Record<string,unknown>,slideCount:number,deletedSlides:readonly number[]=[]):void {
 const items=changes.mediaInsertions??[]
 if(!Array.isArray(items)||items.length>50)fail()
 let total=0
 for(const item of items){
  if(!item||typeof item!=='object'||Object.keys(item).some(key=>!['slideIndex','kind','extension','bytesBase64','name','center','poster'].includes(key))||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=slideCount||deletedSlides.includes(item.slideIndex))fail()
  const extensions=item.kind==='video'?VIDEO_EXTS:item.kind==='audio'?AUDIO_EXTS:[]
  if(!(extensions as readonly string[]).includes(item.extension)||typeof item.bytesBase64!=='string'||!item.bytesBase64.length||item.bytesBase64.length>8*1024*1024)fail()
  let bytes:string
  try{bytes=atob(item.bytesBase64)}catch{return fail()}
  if(btoa(bytes)!==item.bytesBase64||!bytes.length||bytes.length>6*1024*1024)fail()
  if(item.name!==undefined&&(typeof item.name!=='string'||item.name.length>500||/[\u0000-\u001f\u007f]/.test(item.name)))fail()
  if(item.center!==undefined&&(!item.center||Object.keys(item.center).sort().join()!=='x,y'||![item.center.x,item.center.y].every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=51206400)))fail()
  if(item.poster!==undefined){
   const poster=item.poster
   if(item.kind!=='video'||!poster||Object.keys(poster).sort().join()!=='bytesBase64,sha256'||typeof poster.bytesBase64!=='string'||poster.bytesBase64.length>5592408||typeof poster.sha256!=='string'||!(/^[a-f0-9]{64}$/).test(poster.sha256))fail()
   let png:string;try{png=atob(poster.bytesBase64)}catch{return fail()}
   if(btoa(png)!==poster.bytesBase64||png.length<24||png.length>4*1024*1024||png.slice(0,8)!=='\x89PNG\r\n\x1a\n')fail()
   const header=new DataView(Uint8Array.from(png.slice(0,24),c=>c.charCodeAt(0)).buffer)
   if(![header.getUint32(16),header.getUint32(20)].every(n=>n>0&&n<=1600))fail()
   total+=png.length
  }
  total+=bytes.length
 }
 for(const key of ['images','pictureReplacements','backgroundImages']){
  const images=changes[key]??[]
  if(!Array.isArray(images))fail()
  for(const item of images){try{total+=atob(item.bytesBase64).length}catch{return fail()}}
 }
 for(const key of ['modelInsertions','modelViews']){
  const models=changes[key]??[];if(!Array.isArray(models))fail()
  for(const item of models){try{total+=atob(item.posterBase64).length;if(item.bytesBase64)total+=atob(item.bytesBase64).length}catch{return fail()}}
 }
 if(total>8*1024*1024)fail()
}
export async function prepareSlideMedia(file:File,kind:'video'|'audio',signal?:AbortSignal):Promise<Omit<SlideMediaInsertion,'slideIndex'>> {
 const extension=fileExt(file.name),extensions=kind==='video'?VIDEO_EXTS:AUDIO_EXTS
 if(!(extensions as readonly string[]).includes(extension)||!file.size||file.size>6*1024*1024)throw Error('请选择源支持的音视频文件，单个文件不超过 6 MiB')
 if(signal?.aborted)throw Error('媒体读取已取消')
 const buffer=await new Promise<ArrayBuffer>((resolve,reject)=>{
  const reader=new FileReader(),abort=()=>reader.abort(),clean=()=>signal?.removeEventListener('abort',abort)
  reader.onload=()=>{clean();resolve(reader.result as ArrayBuffer)};reader.onerror=()=>{clean();reject(Error('读取媒体失败，请重新选择'))};reader.onabort=()=>{clean();reject(Error('媒体读取已取消'))}
  signal?.addEventListener('abort',abort,{once:true});reader.readAsArrayBuffer(file)
 })
 const bytes=new Uint8Array(buffer);let binary=''
 for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000))
 return {kind,extension,bytesBase64:btoa(binary),name:file.name}
}
export function pickSlideMedia(kind:'video'|'audio',signal?:AbortSignal):Promise<File|null>{
 return new Promise(resolve=>{
  const input=document.createElement('input');input.type='file';input.hidden=true;input.accept=(kind==='video'?VIDEO_EXTS:AUDIO_EXTS).map(ext=>'.'+ext).join(',')
  let done=false
  const cancel=()=>finish(null),finish=(file:File|null)=>{if(done)return;done=true;signal?.removeEventListener('abort',cancel);input.remove();resolve(file)}
  input.addEventListener('change',()=>finish(input.files?.[0]??null),{once:true});input.addEventListener('cancel',()=>finish(null),{once:true})
  if(signal?.aborted){finish(null);return}
  signal?.addEventListener('abort',cancel,{once:true});document.body.append(input);input.click()
 })
}
