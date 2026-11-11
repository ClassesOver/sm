import './pdf-ai-dock.css'
import {bindOfficeAssistantFloating} from './office-assistant-floating'
type Mode='read'|'review'|'forms'
/** PDF 共用右侧停靠区；面板保留原任务控制器，切换和关闭均走其取消按钮。 */
export function bindPdfAIDock(layout:HTMLElement,entries:Partial<Record<Mode,{panel:HTMLElement;open():void;close:HTMLButtonElement}>>){
 const workspace=document.createElement('div');workspace.className='pdf-ai-workspace';layout.before(workspace);workspace.append(layout)
 const dock=document.createElement('aside');dock.className='pdf-ai-dock';dock.hidden=true;dock.setAttribute('aria-label','PDF AI 助手侧栏')
 const header=document.createElement('header'),title=document.createElement('strong');title.textContent='PDF AI 助手';header.append(title);dock.append(header)
 const floating=bindOfficeAssistantFloating(dock,header)
 const tabs=document.createElement('nav');tabs.setAttribute('aria-label','AI 助手功能');dock.append(tabs);workspace.append(dock)
 let active:Mode|undefined,changing=false
 const buttons=new Map<Mode,HTMLButtonElement>(),observers:MutationObserver[]=[]
 const activate=(mode:Mode)=>{
  if(changing)return;changing=true
  for(const [key,entry] of Object.entries(entries) as [Mode,NonNullable<typeof entries[Mode]>][]){if(key!==mode&&!entry.panel.hidden)entry.close.click()}
  active=mode;dock.hidden=false;workspace.classList.add('has-ai-dock')
  for(const [key,b] of buttons)b.setAttribute('aria-selected',String(key===mode))
  changing=false
 }
 for(const [key,entry] of Object.entries(entries) as [Mode,NonNullable<typeof entries[Mode]>][]){
  const b=document.createElement('button');b.type='button';b.dataset.pdfAiMode=key;b.textContent={read:'阅读问答',review:'批注审阅',forms:'填写表单'}[key];b.onclick=()=>{activate(key);entry.open()};tabs.append(b);buttons.set(key,b);dock.append(entry.panel)
  const close=()=>{if(changing)return;if(active===key){dock.hidden=true;workspace.classList.remove('has-ai-dock');active=undefined}}
  entry.close.addEventListener('click',close)
  const observer=new MutationObserver(()=>{if(!entry.panel.hidden)activate(key);else if(active===key)close()});observer.observe(entry.panel,{attributes:true,attributeFilter:['hidden']});observers.push(observer)
 }
 return {dispose(){floating.dispose();for(const observer of observers)observer.disconnect();workspace.before(layout);workspace.remove()}}
}

export function mountPdfTaskDock(root:HTMLElement,layout:HTMLElement,controllers:Partial<Record<Mode,{open():void}>>){
 const entries:Parameters<typeof bindPdfAIDock>[1]={}
 for(const [key,name] of [['read','assistant'],['review','review'],['forms','form-ai']] as const){
  const controller=controllers[key],panel=root.querySelector<HTMLElement>('.native-pdf-'+name)
  const close=panel?.querySelector<HTMLButtonElement>('.office-assistant-close')
  if(controller&&panel&&close)entries[key]={panel,close,open:()=>controller.open()}
 }
 return bindPdfAIDock(layout,entries)
}
