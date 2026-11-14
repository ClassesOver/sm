// 固定源 f8c17004 ExternalLinksPanel；浏览器文件授权取代桌面 OS picker/reveal。
import './workbook-watch-window.css'
import './workbook-external-links.css'
import type {ExternalWorkbookLink} from '@sheets-web/xlsx-engine/external-links'
import {EXTERNAL_SOURCE_MAX_BYTES,type ExternalSourceBinding} from '@sheets-web/xlsx-engine/external-links-source'
import {sha256Hex} from '@sheets-web/xlsx-engine/sha256'
export interface ExternalLinksSnapshot{key:string;links:readonly ExternalWorkbookLink[];bindings:readonly ExternalSourceBinding[]}
export interface ExternalLinksHost{
 capture():Promise<ExternalLinksSnapshot>
 current(key:string):boolean
 editable():boolean
 apply(snapshot:ExternalLinksSnapshot,operations:Record<string,unknown>[]):Promise<void>
 update(snapshot:ExternalLinksSnapshot):Promise<{message:string}>
 locate(index:number,snapshot:ExternalLinksSnapshot):Promise<string>
 pick?(index:number):Promise<File|null>
}
export function createWorkbookExternalLinks(host:HTMLElement,deps:ExternalLinksHost){
 let panel:HTMLElement|undefined,snapshot:ExternalLinksSnapshot|undefined,busy=false,disposed=false,generation=0,confirming:number|undefined,notice='',updated=false
 const pick=(index:number):Promise<File|null>=>deps.pick?deps.pick(index):new Promise(resolve=>{
  const input=document.createElement('input');input.type='file';input.accept='.xlsx';input.hidden=true;panel!.append(input)
  const finish=(file:File|null)=>{input.remove();resolve(file)}
  input.addEventListener('change',()=>finish(input.files?.[0]??null),{once:true});input.addEventListener('cancel',()=>finish(null),{once:true});input.click()
 })
 const check=(captured:ExternalLinksSnapshot,token:number)=>{if(disposed||!panel||token!==generation||!deps.current(captured.key))throw new Error('工作簿或草稿已变化，请重新打开外部链接');if(!deps.editable())throw new Error('当前工作簿不可编辑或正在保存')}
 const action=(work:(captured:ExternalLinksSnapshot,token:number)=>Promise<void>)=>{
  if(busy||!snapshot)return
  const captured=snapshot,token=generation;busy=true;render()
  void(async()=>{try{check(captured,token);await work(captured,token)}catch(error){if(token===generation)notice=(error as Error).message}finally{if(token===generation&&!disposed){busy=false;render()}}})()
 }
 const button=(label:string,attribute:string,callback:()=>void)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.setAttribute(attribute,'');b.disabled=busy;b.addEventListener('click',callback);return b}
 const render=()=>{
  if(!panel||!snapshot)return
  panel.replaceChildren();const header=document.createElement('header'),title=document.createElement('strong');title.textContent='外部链接'
  header.append(title,button('更新值','data-external-update',()=>action(async(captured,token)=>{const result=await deps.update(captured);if(token!==generation)return;notice=result.message;updated=true;snapshot=await deps.capture()})),button('×','data-external-close',close));panel.append(header)
  const info=document.createElement('p');info.textContent='仅显式选择的 XLSX 文件可读取；不会探测原路径或访问链接 URL。选择来源后保存草稿；新打开的修订须重新授权来源。';panel.append(info)
  const status=document.createElement('p');status.setAttribute('role','status');status.textContent=notice||(!snapshot.links.length?'此工作簿没有外部链接。':'修改保留在当前草稿，保存后写入文件。');panel.append(status)
  if(!snapshot.links.length)return
  const scroll=document.createElement('div');scroll.className='watch-scroll';scroll.tabIndex=0;const table=document.createElement('table');table.innerHTML='<thead><tr><th>来源</th><th>状态</th><th>工作表</th><th>操作</th></tr></thead>';const body=document.createElement('tbody')
  for(const link of snapshot.links){
   const row=document.createElement('tr'),source=document.createElement('td'),state=document.createElement('td'),sheets=document.createElement('td'),actions=document.createElement('td'),binding=[...snapshot.bindings].reverse().find(item=>item.index===link.index&&item.expectedTarget===link.rawTarget)
   source.textContent=link.rawTarget;if(binding)source.append(document.createElement('br'),document.createTextNode('→ 已授权：'+binding.name));state.dataset.externalStatus='';state.textContent=binding?(updated?'可读取，已检查':'已授权，待更新'):(updated?'未授权，保留缓存':'未检查');sheets.textContent=link.sheetNames.join(', ')
   actions.append(button('定位来源','data-external-locate',()=>action(async(captured,token)=>{const message=await deps.locate(link.index,captured);if(token===generation)notice=message})),button('更改来源','data-external-change',()=>action(async(captured,token)=>{
    const file=await pick(link.index);if(!file)return;check(captured,token)
    if(file.size<1||file.size>EXTERNAL_SOURCE_MAX_BYTES||!file.name.toLowerCase().endsWith('.xlsx'))throw new Error('请选择不超过 6 MiB 的 XLSX 文件')
    const bytes=new Uint8Array(await file.arrayBuffer());check(captured,token);let binary='';for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000))
    const binding:ExternalSourceBinding={kind:'bindExternalLinkSource',index:link.index,expectedTarget:file.name,name:file.name,mediaType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',size:bytes.length,sha256:await sha256Hex(bytes),bytesBase64:btoa(binary)}
    check(captured,token);await deps.apply(captured,[{kind:'retargetExternalLink',index:link.index,expectedTarget:link.rawTarget,target:file.name},binding]);if(token!==generation)return;snapshot=await deps.capture();updated=false;notice='来源已更改；公式和缓存保持原值。点击更新值后读取授权文件。'
   })))
   if(confirming===link.index)actions.append(button('确认断开','data-external-break-confirm',()=>action(async(captured,token)=>{check(captured,token);await deps.apply(captured,[{kind:'breakExternalLink',index:link.index,expectedTarget:link.rawTarget}]);if(token!==generation)return;confirming=undefined;snapshot=await deps.capture();notice='链接已断开，引用公式按当前文件缓存冻结为值；修改尚未保存。'})),button('取消','data-external-break-cancel',()=>{confirming=undefined;render()}))
   else actions.append(button('断开链接','data-external-break',()=>{confirming=link.index;render()}))
   row.append(source,state,sheets,actions);body.append(row)
  }
  table.append(body);scroll.append(table);panel.append(scroll)
 }
 function close(){generation++;panel?.remove();panel=undefined;snapshot=undefined;busy=false;confirming=undefined}
 return{async open(){if(disposed)return;close();const token=generation;const captured=await deps.capture();if(disposed||token!==generation)return;snapshot=captured;notice='';updated=false;panel=document.createElement('section');panel.className='workbook-watch-window workbook-external-links';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','外部链接');panel.addEventListener('keydown',event=>{if(event.key==='Escape'&&!busy)close()});host.append(panel);render()},close,dispose(){disposed=true;close()}}
}
