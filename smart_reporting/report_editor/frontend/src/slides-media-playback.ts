/** 固定源编辑态 DOM 播放层；只消费实际 PPTX 快照的已授权媒体。 */
import type {SlideMediaSource} from './slides-media'
export function openSlideMediaPlayback(host:HTMLElement,source:SlideMediaSource,box:{x:number;y:number;w:number;h:number},slideWidth:number):{dispose():void}{
 if(!source.dataUrl)throw Error(source.reason??'嵌入媒体不可读取')
 const surface=host.querySelector<HTMLElement>('.konvajs-content')??host,rect=surface.getBoundingClientRect(),k=(rect.width||slideWidth)/slideWidth
 const width=Math.max(1,Math.min(window.innerWidth-20,Math.max(source.kind==='audio'?260:100,box.w*k))),height=source.kind==='video'?width*box.h/box.w:54
 const left=Math.max(10,Math.min(rect.left+box.x*k,window.innerWidth-width-10)),top=Math.max(10,Math.min(rect.top+box.y*k,window.innerHeight-height-80))
 const opener=document.activeElement instanceof HTMLElement?document.activeElement:undefined
 const dialog=document.createElement('dialog');dialog.className='slides-media-playback';dialog.setAttribute('aria-label',source.kind==='video'?'视频播放':'音频播放')
 Object.assign(dialog.style,{position:'fixed',margin:'0',padding:'0',left:`${left}px`,top:`${top}px`,width:`${width}px`,maxWidth:'calc(100vw - 20px)',border:'1px solid #666',zIndex:'1000',background:'#111',color:'#fff'})
 const player=document.createElement(source.kind==='video'?'video':'audio');player.controls=true;player.preload='metadata';player.src=source.dataUrl;player.dataset.mediaId=source.sourceId;player.setAttribute('aria-label',source.kind==='video'?'编辑视频':'编辑音频')
 if(player instanceof HTMLVideoElement){player.playsInline=true;player.style.height=`${height}px`}
 player.style.width='100%'
 const status=document.createElement('p');status.setAttribute('role','status');status.style.margin='4px';status.textContent=source.warning??''
 const failed=()=>{if(!disposed)status.textContent='浏览器无法播放此媒体容器或编码；原始文件已保留，可下载后在 PowerPoint 中播放。'}
 player.addEventListener('error',failed)
 const close=document.createElement('button');close.type='button';close.textContent='关闭播放';close.setAttribute('aria-label','关闭媒体播放')
 let disposed=false
 const dispose=()=>{if(disposed)return;disposed=true;player.pause();player.removeAttribute('src');player.load();dialog.remove();if(opener?.isConnected)opener.focus({preventScroll:true});window.removeEventListener('resize',dispose);window.removeEventListener('keydown',escape)}
 const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();dispose()}}
 close.addEventListener('click',dispose);dialog.addEventListener('cancel',event=>{event.preventDefault();dispose()})
 dialog.append(player,close,status);document.body.append(dialog);dialog.show();window.addEventListener('resize',dispose);window.addEventListener('keydown',escape)
 void player.play().catch(failed)
 return {dispose}
}
