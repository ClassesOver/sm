/** Full fixed-source PasteSpecialDialog + ExcelShell host, using the existing modal and save journal. */
import {CommandType,ICommandService,LocaleService} from '@univerjs/core'
import {ContextMenuGroup,ContextMenuPosition,IMenuManagerService,MenuItemType} from '@univerjs/ui'
import {BehaviorSubject} from 'rxjs'
import {createModal} from './modal'
import {hasWorkbookModal,isWorkbookGridKeyTarget} from './workbook-shortcut-target'
import {applyPasteSpecial,readPasteSpecialSource,pasteSpecialAvailability,PASTE_SPECIAL_TYPES,PASTE_SPECIAL_OPERATIONS,type PasteSpecialOptions,type PasteSpecialSource} from './workbook-vendor/grid/paste-special'
import type {UniverRuntime} from './workbook-vendor/grid/create-univer'
import './workbook-paste-special.css'
const typeLabels=['全部','公式','数值','格式','批注和注释','验证','所有使用源主题的单元','边框除外','列宽','公式和数字格式','值和数字格式','所有合并条件格式']
const operationLabels=['无','加','减','乘','除']
export function createWorkbookPasteSpecial(root:HTMLElement,options:{runtime:UniverRuntime;editable():boolean;onMessage(text:string):void;onChange():void}){
 const {runtime}=options;let disposed=false,epoch=0,busy=false,reading=false,target='',source:PasteSpecialSource={kind:'none'}
 const selection=()=>{
  const book=runtime.univerAPI.getActiveWorkbook(),sheet=book?.getActiveSheet(),range=book?.getActiveRange()
  return book&&sheet&&range?JSON.stringify([book.getId(),sheet.getSheetId(),range.getRange()]):''
 }
 const current=()=>!disposed&&options.editable()&&target!==''&&selection()===target
 const close=()=>{if(busy)return;++epoch;reading=false;modal.close()}
 const modal=createModal({root,label:'选择性粘贴',closeLabel:'关闭选择性粘贴',overlayClass:'workbook-paste-special-overlay',cardClass:'workbook-paste-special-dialog',content:'<h2>选择性粘贴</h2><section class="workbook-paste-special-body"></section><p role="alert"></p><footer class="workbook-paste-special-actions"></footer>',onRequestClose:close})
 const body=modal.card.querySelector('section')!,alert=modal.card.querySelector('[role=alert]')!,footer=modal.card.querySelector('footer')!
 async function open(){
  if(disposed||busy||!options.editable()||runtime.univerAPI.getActiveWorkbook()?.isCellEditing?.())return
  const captured=selection();if(!captured){options.onMessage('请先选择目标单元格。');return}
  const token=++epoch;reading=true;target=captured
  try{const incoming=await readPasteSpecialSource(runtime);if(token!==epoch||!current())return;source=incoming;render();modal.open(body.querySelector<HTMLInputElement>('input:not([disabled])'));}
  catch(error){if(token===epoch&&!disposed)options.onMessage((error as Error).message)}finally{if(token===epoch)reading=false}
 }
 function render(){
  body.replaceChildren();footer.replaceChildren();alert.textContent='';const availability=pasteSpecialAvailability(source)
  let state:PasteSpecialOptions={type:'all',operation:'none',skipBlanks:false,transpose:false,link:false}
  const group=(legend:string)=>{const field=document.createElement('fieldset'),title=document.createElement('legend');title.textContent=legend;field.append(title);body.append(field);return field}
  const types=group('粘贴'),operations=group('运算')
  const radio=(field:HTMLElement,name:string,value:string,label:string,checked:boolean,enabled:boolean,pick:()=>void)=>{const row=document.createElement('label'),input=document.createElement('input');input.type='radio';input.name=name;input.value=value;input.checked=checked;input.disabled=!enabled;input.onchange=pick;row.append(input,label);if(!enabled)row.title=name==='paste-special-type'&&['comments','validation'].includes(value)?'当前粘贴引擎不支持此项':'当前复制内容不支持此项';field.append(row)}
  PASTE_SPECIAL_TYPES.forEach((type,i)=>radio(types,'paste-special-type',type,typeLabels[i]!,type==='all',availability.types.has(type),()=>{state={...state,type}}))
  PASTE_SPECIAL_OPERATIONS.forEach((operation,i)=>radio(operations,'paste-special-operation',operation,operationLabels[i]!,operation==='none',operation==='none'||availability.operation,()=>{state={...state,operation}}))
  const flags=document.createElement('div');flags.className='workbook-paste-special-flags';body.append(flags)
  for(const [key,label]of [['skipBlanks','跳过空单元'],['transpose','转置']] as const){const row=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.disabled=!availability[key];input.onchange=()=>{state={...state,[key]:input.checked}};row.append(input,label);flags.append(row)}
  const note=source.kind==='none'?'没有可粘贴的内容：请先复制一个区域。':source.kind==='text'?'复制内容来自其他应用：只能粘贴数值或转置。':source.cut?'剪切后只能整体粘贴。':null
  if(note){const p=document.createElement('p');p.className='workbook-paste-special-note';p.textContent=note;body.append(p)}
  const button=(text:string,enabled:boolean,action:()=>void)=>{const b=document.createElement('button');b.type='button';b.textContent=text;b.disabled=!enabled;b.onclick=action;footer.append(b);return b}
  async function apply(link:boolean){
   if(busy)return
   if(!current()){alert.textContent='目标区域或工作簿状态已变化，请重新打开选择性粘贴';return}
   busy=true;modal.overlay.setAttribute('aria-busy','true');const controls=[...modal.card.querySelectorAll<HTMLInputElement|HTMLButtonElement>('input,button')],disabled=controls.map(c=>c.disabled);controls.forEach(c=>c.disabled=true)
   try{const result=await applyPasteSpecial(runtime,source,{...state,link},current);if(!result.ok){alert.textContent=result.reason==='out-of-bounds'?'粘贴区域会超出工作表边界。':result.reason==='no-selection'?'请先选择目标单元格。':result.reason==='not-applied'?'所选粘贴未应用；请检查目标权限或重新复制。':'没有可粘贴的内容：请先复制一个区域。';return}options.onChange();options.onMessage('已选择性粘贴，修改尚未保存。');busy=false;close()}
   catch(error){alert.textContent=(error as Error).message}finally{busy=false;modal.overlay.removeAttribute('aria-busy');controls.forEach((c,i)=>c.disabled=disabled[i]!)}
  }
  button('粘贴链接',availability.link,()=>{void apply(true)});button('取消',true,close);const confirm=button('确定',availability.types.has(state.type),()=>{void apply(false)});confirm.dataset.pasteSpecialApply=''
  modal.card.onkeydown=event=>{if(event.isComposing||event.keyCode===229||event.defaultPrevented)return;if(event.key==='Enter'&&!(event.target instanceof HTMLButtonElement)){event.preventDefault();if(!confirm.disabled)void apply(false)}}
 }
 const key=(event:KeyboardEvent)=>{
  if(event.defaultPrevented||event.isComposing||event.keyCode===229)return
  if(event.key==='Escape'&&reading){event.preventDefault();close();return}
  if(event.key.toLowerCase()!=='v'||!event.ctrlKey||!event.altKey||event.metaKey||event.shiftKey||!options.editable()||!isWorkbookGridKeyTarget(event.target)||hasWorkbookModal(root.ownerDocument))return
  event.preventDefault();event.stopImmediatePropagation();void open()
 }
 root.addEventListener('keydown',key,true)
 let menu:{dispose():void}|undefined
 const injector=runtime.univer?.__getInjector?.()
 if(injector?.has?.(IMenuManagerService)&&injector.has(ICommandService)){
  const id='sheets.paste-special.open',hidden=new BehaviorSubject(false),commands=injector.get(ICommandService),menus=injector.get(IMenuManagerService)
  const registered=commands.registerCommand({id,type:CommandType.COMMAND,handler:()=>{if(!options.editable())return false;void open();return true}})
  if(injector.has(LocaleService)){const locale=injector.get(LocaleService);locale.load({[locale.getCurrentLocale()]:{smartReportingPasteSpecial:'选择性粘贴…'}})}
  menus.mergeMenu({[ContextMenuPosition.MAIN_AREA]:{[ContextMenuGroup.FORMAT]:{[id]:{order:1.5,menuItemFactory:()=>({id,commandId:id,type:MenuItemType.BUTTON,title:'smartReportingPasteSpecial',hidden$ :hidden})}}}})
  menu={dispose(){hidden.next(true);registered.dispose();hidden.complete()}}
 }
 return {open,dispose(){if(disposed)return;disposed=true;++epoch;reading=false;root.removeEventListener('keydown',key,true);menu?.dispose();modal.remove()}}
}
