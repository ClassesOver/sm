import type {NotePicture} from '@sheets-web/xlsx-engine/note-pictures'
import {formatAddress} from '@sheets-web/xlsx-engine/cell-address'
import './workbook-note-pictures.css'
export interface NotePictureSnapshot {key:string;pictures:NotePicture[];issues:{sheetName:string;message:string}[];sheets?:{sheetName:string;sourceIdentity:string;notes:{row:number;column:number;author:string;text:string}[]}[]}
interface Options {capture():Promise<NotePictureSnapshot>;current(key:string):boolean;editable():boolean;jump(picture:NotePicture):unknown;remove(picture:NotePicture,key:string):Promise<unknown>|unknown;insert():Promise<unknown>|unknown}
export function createNotePictures(root:HTMLElement,options:Options){
 let pane:HTMLElement|undefined,tooltip:HTMLElement|undefined,snapshot:NotePictureSnapshot|undefined,held:NotePicture|null=null,inside=false,busy=false,disposed=false,generation=0,hoverKey='',hoverActive=false
 const urls=new Map<HTMLImageElement,string>()
 const clear=(element:HTMLElement|undefined)=>{if(!element)return;for(const image of element.querySelectorAll('img')){const url=urls.get(image);if(url)URL.revokeObjectURL?.(url);urls.delete(image)}element.remove()}
 const button=(label:string,attribute:string,click:()=>unknown)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.setAttribute(attribute,'');b.addEventListener('click',()=>void click());return b}
 const message=(value:string)=>{const el=pane?.querySelector<HTMLElement>('[role=status]');if(el)el.textContent=value}
 const image=(picture:NotePicture)=>{const box=document.createElement('div');if(!picture.bytes){box.textContent='此图片无法显示：'+(picture.unavailable??'媒体文件不可用');box.className='np-image-missing';return box}const img=document.createElement('img');img.alt='批注图片';img.className='np-image'
  const data=picture.bytes.slice();const blob=new Blob([data.buffer as ArrayBuffer],{type:picture.mediaType})
  if(URL.createObjectURL){const url=URL.createObjectURL(blob);img.src=url;urls.set(img,url)}else{let binary='';for(const byte of data)binary+=String.fromCharCode(byte);img.src='data:'+picture.mediaType+';base64,'+btoa(binary)}
  img.addEventListener('error',()=>{box.textContent='此图片无法显示；批注文字保留';const url=urls.get(img);if(url)URL.revokeObjectURL?.(url);urls.delete(img)})
  box.append(img);return box
 }
 const remove=async(picture:NotePicture,key:string)=>{if(busy||!options.editable()||!options.current(key)){message('草稿已变化或当前不可编辑，请重新打开图片批注');return}busy=true;try{await options.remove(picture,key);if(disposed)return;hideHover();await open()}catch(error){message((error as Error).message)}finally{busy=false;refresh()}}
 const card=(picture:NotePicture,key:string,hover=false)=>{const article=document.createElement(hover?'div':'article');article.className=hover?'note-hover-card':'np-card';const header=document.createElement('header')
  if(!hover)header.append(button(picture.sheetName+'!'+formatAddress(picture.row,picture.column),'data-note-picture-jump',()=>options.jump(picture)))
  if(picture.author){const author=document.createElement('span');author.className='np-author';author.textContent=picture.author;header.append(author)}
  const rm=button('移除图片','data-note-picture-remove',()=>remove(picture,key));rm.disabled=!options.editable();header.append(rm);article.append(header,image(picture))
  if(picture.text){const text=document.createElement('p');text.className='np-text';text.textContent=picture.text;article.append(text)}
  article.title=picture.sha256?'SHA-256 '+picture.sha256+'；'+picture.size+' 字节':picture.unavailable??'';return article
 }
 function refresh(){for(const b of root.querySelectorAll<HTMLButtonElement>('[data-note-picture-remove],[data-note-picture-insert]'))b.disabled=busy||!options.editable()}
 function close(){generation++;clear(pane);pane=undefined;snapshot=undefined}
 async function open(){const token=++generation;const data=await options.capture();if(disposed||token!==generation)return;clear(pane);snapshot=data;pane=document.createElement('aside');pane.className='note-pictures-pane';pane.setAttribute('aria-label','图片批注');const header=document.createElement('header');header.append(document.createTextNode('图片批注'),button('关闭','data-note-pictures-close',close));pane.append(header)
  const insert=button('在当前单元格插入图片','data-note-picture-insert',async()=>{try{await options.insert()}catch(error){message((error as Error).message)}});pane.append(insert)
  const status=document.createElement('p');status.setAttribute('role','status');status.textContent=data.issues.map(i=>i.sheetName+'：'+i.message).join('；')||'仅移除图片会保留批注作者和文字；修改尚未保存。';pane.append(status)
  const list=document.createElement('div');list.className='np-list';if(!data.pictures.length){const empty=document.createElement('p');empty.textContent='此工作簿没有包含图片的批注';list.append(empty)}else for(const picture of data.pictures)list.append(card(picture,data.key))
  pane.append(list);root.append(pane);refresh()
 }
 function hideHover(){clear(tooltip);tooltip=undefined;held=null;inside=false;hoverActive=false}
 function place(){if(!tooltip)return;const popups=root.querySelectorAll('[data-u-comp="cell-popup"]'),popup=popups[popups.length-1]??document.querySelector('[data-u-comp="cell-popup"]'),rect=popup?.getBoundingClientRect();if(!rect){tooltip.style.left='12px';tooltip.style.top='220px';return}const width=tooltip.offsetWidth||260;tooltip.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-width-8))+'px';tooltip.style.top=Math.min(rect.bottom+6,Math.max(8,window.innerHeight-120))+'px';if(tooltip.getBoundingClientRect().bottom>window.innerHeight-8)tooltip.style.top=Math.max(8,rect.top-tooltip.offsetHeight-6)+'px'}
 function hover(picture:NotePicture|null,key:string){hoverActive=!!picture;if(!picture){if(!inside)hideHover();return}held=picture;hoverKey=key;clear(tooltip);tooltip=card(picture,key,true);tooltip.setAttribute('role','tooltip');tooltip.addEventListener('pointerenter',()=>{inside=true});tooltip.addEventListener('pointerleave',()=>{inside=false;if(!hoverActive)hideHover()});root.append(tooltip);place();tooltip.querySelector('img')?.addEventListener('load',place,{once:true});requestAnimationFrame(place)}
 window.addEventListener('resize',place)
 return {open,close,toggle:()=>pane?close():open(),hover,refresh,isOpen:()=>!!pane,dispose(){disposed=true;close();hideHover();window.removeEventListener('resize',place)}}
}
