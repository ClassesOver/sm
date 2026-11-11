import {createElement,PanelRightClose} from 'lucide'
import {AI_PANEL_WIDTH_DEFAULT,AI_PANEL_WIDTH_MIN,clampAiPanelWidth,loadAiPanelWidth,saveAiPanelWidth,maxAiPanelWidth} from './vendor/genoffice-ai-panel/ai-panel-width'
import './office-task-dock.css'
import {bindOfficeAssistantFloating} from './office-assistant-floating'
export interface OfficeTaskEntry {id:string;label:string;panel:HTMLElement;open():void;close():void}
/** 只统一停靠和模式切换，任务身份、取消、采纳仍属于各格式原控制器。 */
export function mountOfficeTaskDock(main:HTMLElement,entries:OfficeTaskEntry[],options:{label:string}){
 const workspace=document.createElement('div');workspace.className='office-task-workspace';main.before(workspace);workspace.append(main);main.classList.add('office-task-main')
 const dock=document.createElement('aside');dock.className='office-task-dock';dock.hidden=true;dock.setAttribute('aria-label',options.label)
 const header=document.createElement('header'),title=document.createElement('strong');title.textContent=options.label
 const close=document.createElement('button');close.type='button';close.setAttribute('aria-label','收起 AI 助手');close.append(createElement(PanelRightClose,{width:18,height:18,'aria-hidden':'true'}));header.append(title,close)
 const floating=bindOfficeAssistantFloating(dock,header)
 const nav=document.createElement('nav');nav.setAttribute('aria-label','AI 助手功能');dock.append(header,nav);workspace.append(dock)
 const divider=document.createElement('div');divider.className='office-task-divider';divider.tabIndex=0;divider.setAttribute('role','separator');divider.setAttribute('aria-orientation','vertical');divider.setAttribute('aria-label','调整 AI 助手宽度');dock.prepend(divider)
 const storageKey='native-office-ai-width:'+options.label
 let width=AI_PANEL_WIDTH_DEFAULT
 try{width=loadAiPanelWidth(storageKey)??width}catch{}
 const resize=(requested:number,save=false)=>{width=clampAiPanelWidth(requested);dock.style.setProperty('--office-task-width',width+'px');divider.setAttribute('aria-valuenow',String(width));divider.setAttribute('aria-valuemin',String(AI_PANEL_WIDTH_MIN));divider.setAttribute('aria-valuemax',String(maxAiPanelWidth()));if(save)try{saveAiPanelWidth(storageKey,width)}catch{}}
 resize(width)
 let active:string|undefined,changing=false,disposed=false,trigger:HTMLElement|null=null,drag:number|undefined
 const buttons=new Map<string,HTMLButtonElement>(),observers:MutationObserver[]=[],origins=entries.map(entry=>({entry,parent:entry.panel.parentNode,next:entry.panel.nextSibling}))
 function activate(id:string){if(changing||disposed)return;changing=true;for(const entry of entries)if(entry.id!==id&&!entry.panel.hidden)entry.close();active=id;dock.hidden=false;workspace.classList.add('has-office-task-dock');for(const [key,b]of buttons)b.setAttribute('aria-pressed',String(key===id));changing=false}
 function hide(){dock.hidden=true;workspace.classList.remove('has-office-task-dock');active=undefined}
 function open(id:string){const entry=entries.find(entry=>entry.id===id);if(!entry||disposed)return;if(active===id&&!entry.panel.hidden){entry.panel.querySelector('textarea')?.focus();return}const focus=document.activeElement;if(focus instanceof HTMLElement&&!dock.contains(focus))trigger=focus;activate(id);entry.open()}
 function collapse(){for(const entry of entries)if(!entry.panel.hidden)entry.close();hide();if(trigger?.isConnected)trigger.focus({preventScroll:true})}
 for(const entry of entries){const b=document.createElement('button');b.type='button';b.textContent=entry.label;b.dataset.officeAiMode=entry.id;b.onclick=()=>open(entry.id);buttons.set(entry.id,b);nav.append(b);dock.append(entry.panel);const observer=new MutationObserver(()=>{if(!entry.panel.hidden)activate(entry.id);else if(active===entry.id)hide()});observer.observe(entry.panel,{attributes:true,attributeFilter:['hidden']});observers.push(observer);if(!entry.panel.hidden)activate(entry.id)}
 close.onclick=collapse
 const key=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!event.isComposing&&!event.defaultPrevented){event.preventDefault();collapse()}}
 dock.addEventListener('keydown',key)
 const move=(event:PointerEvent)=>{if(drag===event.pointerId)resize(workspace.getBoundingClientRect().right-event.clientX)}
 const end=(event:PointerEvent)=>{if(drag!==event.pointerId)return;drag=undefined;resize(width,true);if(divider.hasPointerCapture(event.pointerId))divider.releasePointerCapture(event.pointerId)}
 const start=(event:PointerEvent)=>{if(event.button!==0)return;event.preventDefault();drag=event.pointerId;divider.setPointerCapture(event.pointerId)}
 const resizeKey=(event:KeyboardEvent)=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();resize(event.key==='Home'?AI_PANEL_WIDTH_MIN:event.key==='End'?maxAiPanelWidth():width+(event.key==='ArrowLeft'?20:-20),true)}
 const viewport=()=>resize(width)
 divider.addEventListener('pointerdown',start);divider.addEventListener('pointermove',move);divider.addEventListener('pointerup',end);divider.addEventListener('pointercancel',end);divider.addEventListener('keydown',resizeKey);window.addEventListener('resize',viewport)
 return{open,dispose(){if(disposed)return;collapse();disposed=true;floating.dispose();observers.forEach(observer=>observer.disconnect());window.removeEventListener('resize',viewport);for(const {entry,parent,next}of origins)if(parent?.isConnected)parent.insertBefore(entry.panel,next?.parentNode===parent?next:null);workspace.before(main);main.classList.remove('office-task-main');workspace.remove()}}
}
