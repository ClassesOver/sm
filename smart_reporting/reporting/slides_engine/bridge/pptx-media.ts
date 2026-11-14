/** 固定源 addMedia 的宿主边界与实际包回读；不接收路径，不自动取外链。 */
import { createHash } from 'node:crypto'
import { addMedia, type OpenedPptx, type Slide } from '@genoffice/pptx-engine'
import { VIDEO_EXTS, AUDIO_EXTS } from './source-media/media-kinds'
import { videoFrame, videoSize, audioFrame } from './source-media/video-size'
import { unplayableAudioCodec } from './source-media/mp4-audio-sniff'
export type MediaInsertion = {slideIndex:number;kind:'video'|'audio';extension:string;bytesBase64:string;name?:string;center?:{x:number;y:number};poster?:{bytesBase64:string;sha256:string}}
const MAX=6*1024*1024
export function mediaBytes(item:MediaInsertion):Buffer {
 if(!item||typeof item.bytesBase64!=='string'||!item.bytesBase64.length||item.bytesBase64.length>MAX/3*4)throw Error('media_asset_invalid')
 const extensions=item.kind==='video'?VIDEO_EXTS:item.kind==='audio'?AUDIO_EXTS:[]
 if(!(extensions as readonly string[]).includes(item.extension))throw Error('media_type_invalid')
 const bytes=Buffer.from(item.bytesBase64,'base64')
 if(!bytes.length||bytes.length>MAX||bytes.toString('base64')!==item.bytesBase64)throw Error('media_asset_invalid')
 return bytes
}
export function mediaPlaybackWarning(kind:'video'|'audio',ext:string,bytes:Uint8Array):string|undefined {
 if(kind==='video'&&ext==='avi')return 'AVI 可嵌入并保留，但当前浏览器不支持播放，请在 PowerPoint 中播放或转换容器。'
 if(kind==='video'&&['mp4','m4v','mov'].includes(ext)){
  const codec=unplayableAudioCodec(bytes)
  if(codec)return `媒体包含浏览器不支持的 ${codec} 音轨，播放可能无声；原始文件字节已保留。`
 }
 return undefined
}
export function validateMediaInsertions(opened:OpenedPptx,items:MediaInsertion[],otherAssets:readonly {bytesBase64:string}[]=[]):void {
 if(!Array.isArray(items)||items.length>50)throw Error('media_request_invalid')
 let total=0
 for(const item of items){
  if(!item||Object.keys(item).some(key=>!['slideIndex','kind','extension','bytesBase64','name','center','poster'].includes(key))||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=opened.deck.slides.length)throw Error('media_target_invalid')
  if(item.name!==undefined&&(typeof item.name!=='string'||item.name.length>500||/[\u0000-\u001f\u007f]/.test(item.name)))throw Error('media_name_invalid')
  if(item.center!==undefined&&(!item.center||Object.keys(item.center).sort().join()!=='x,y'||![item.center.x,item.center.y].every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=51206400)))throw Error('media_center_invalid')
  if(item.poster!==undefined){
   if(!item.poster||typeof item.poster!=='object'||typeof item.poster.bytesBase64!=='string')throw Error('media_poster_invalid')
   const poster=item.poster,bytes=Buffer.from(poster.bytesBase64??'','base64')
   if(item.kind!=='video'||Object.keys(poster).sort().join()!=='bytesBase64,sha256'||bytes.length<24||bytes.length>4*1024*1024||bytes.toString('base64')!==poster.bytesBase64||bytes.subarray(0,8).toString('hex')!=='89504e470d0a1a0a'||![bytes.readUInt32BE(16),bytes.readUInt32BE(20)].every(n=>n>0&&n<=1600)||createHash('sha256').update(bytes).digest('hex')!==poster.sha256)throw Error('media_poster_invalid')
   total+=bytes.length
  }
  total+=mediaBytes(item).length
 }
 for(const item of otherAssets)total+=Buffer.from(item.bytesBase64,'base64').length
 if(total>8*1024*1024)throw Error('media_budget_exceeded')
}
export function applyMediaInsertions(opened:OpenedPptx,originalSlides:Slide[],items:MediaInsertion[]):void {
 for(const item of items){
  const index=opened.deck.slides.indexOf(originalSlides[item.slideIndex]!)
  if(index<0)throw Error('media_slide_missing')
  const bytes=mediaBytes(item),size={width:opened.deck.size.cx,height:opened.deck.size.cy}
  const offset=item.kind==='video'?videoFrame(size,videoSize(bytes,item.extension),item.center):audioFrame(size,item.center)
  const added=addMedia(opened,index,{kind:item.kind,bytes,ext:item.extension,offset,name:item.name,...(item.poster?{poster:{bytes:Buffer.from(item.poster.bytesBase64,'base64'),ext:'png'}}:{})})
  if(!added)throw Error('media_insert_failed')
  originalSlides[item.slideIndex]=added.slide
 }
}
const MIME:Record<string,string>={mp4:'video/mp4',m4v:'video/mp4',mov:'video/mp4',webm:'video/webm',avi:'video/x-msvideo',mp3:'audio/mpeg',wav:'audio/wav',m4a:'audio/mp4',aac:'audio/aac',ogg:'audio/ogg'}
export function readSlideMedia(opened:OpenedPptx,slideIndex:number){
 const slide=opened.deck.slides[slideIndex]
 return (slide?.elements??[]).flatMap(element=>{
  if(element.type!=='picture'||!element.media)return []
  const {kind,target,external}=element.media,base={sourceId:element.id,kind,sha256:null as string|null,size:null as number|null}
  if(external)return [{...base,reason:'此媒体使用外部链接，未经授权不会自动加载；源链接仍保留在文件中。'}]
  if(!target||!/^ppt\/media\/[^/]+$/.test(target))return [{...base,reason:'媒体来源路径无法核验。'}]
  const bytes=opened.archive.readBytes(target),ext=target.split('.').pop()?.toLowerCase()??'',mime=MIME[ext]
  if(!bytes?.length)return [{...base,reason:'嵌入媒体缺失，无法播放。'}]
  const identity={...base,sha256:createHash('sha256').update(bytes).digest('hex'),size:bytes.length}
  if(!mime)return [{...identity,reason:'当前浏览器未支持此媒体容器；原始媒体保留在文件中。'}]
  const warning=mediaPlaybackWarning(kind,ext,bytes)
  return [{...identity,dataUrl:`data:${mime};base64,${Buffer.from(bytes).toString('base64')}`,...(warning?{warning}:{})}]
 })
}
