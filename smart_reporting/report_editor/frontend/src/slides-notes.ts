export type NotesEdit={slideIndex:number;text:string}
export type NotesSource={notesText?:string;notesEditable?:boolean;notesReason?:string|null}
export type NotesPaneState={slideIndex:number;text:string;editable:boolean;reason?:string|null;visible:boolean}
export type NotesPaneOptions={onChange:(slideIndex:number,text:string)=>void;onError?:(message:string)=>void;onVisibleChange?:(visible:boolean)=>void}
let notesPaneSequence=0
const record=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)
export function slidesNotesReadOnlyReason(reason?:string|null):string{
 if(reason?.startsWith('notes_edit_master_'))return '备注母版结构暂不支持编辑；可查看或复制现有备注。'
 if(reason?.startsWith('notes_edit_'))return '此文件的备注结构暂不支持编辑；可查看或复制现有备注。'
 return reason||'当前页面备注仅可读'
}
function normalize(value:unknown):string{
 if(typeof value!=='string'||value.length>20000)throw Error('每页演讲者备注最多20000个UTF16字符')
 for(let index=0;index<value.length;index++){
  const code=value.charCodeAt(index)
  if((code<32&&![9,10,13].includes(code))||code===65534||code===65535)throw Error('演讲者备注包含不支持的控制字符或非字符')
  if(code>=55296&&code<=56319){const next=value.charCodeAt(++index);if(!(next>=56320&&next<=57343))throw Error('演讲者备注包含孤立代理字符')}
  else if(code>=56320&&code<=57343)throw Error('演讲者备注包含孤立代理字符')
 }
 return value.replace(/\r\n?/g,'\n').replace(/\n+$/,'')
}
function array(value:unknown):unknown[]{if(value===undefined)return [];if(!Array.isArray(value))throw Error('备注草稿冲突信息无效；原草稿已保留');return value}
/** 只返回独立的规范化备注记录，其他草稿保持原样。 */
export function validateSlidesNotesDraft(changes:unknown,slides:readonly NotesSource[]):NotesEdit[]{
 if(!record(changes))throw Error('备注草稿结构无效；原草稿已保留')
 const edits=array(changes.notesEdits),deleted=array(changes.deletedSlides),created=array(changes.newSlides),seen=new Set<number>(),result:NotesEdit[]=[]
 if(edits.length>200)throw Error('每批最多修改200页演讲者备注')
 let total=0
 for(const item of edits){
  if(!record(item)||Object.keys(item).sort().join()!=='slideIndex,text'||typeof item.slideIndex!=='number'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=slides.length)throw Error('演讲者备注来源或字段无效；原草稿已保留')
  const index=item.slideIndex
  if(seen.has(index)||slides[index]?.notesEditable!==true||deleted.includes(index)||created.some(value=>record(value)&&value.duplicateOf===index))throw Error(slides[index]?.notesReason?slidesNotesReadOnlyReason(slides[index]?.notesReason):'演讲者备注来源重复、只读、删除或存在复制冲突；原草稿已保留')
  const text=normalize(item.text);total+=(item.text as string).length
  if(total>200000)throw Error('每批演讲者备注原始文本合计最多200000个UTF16字符')
  seen.add(index);result.push({slideIndex:index,text})
 }
 return result
}
/** textarea只创建一次；输入回调同步，调用方在保存/换页/历史前检查flush结果。 */
export function createSlidesNotesPane(host:HTMLElement,options:NotesPaneOptions):{update(state:NotesPaneState):boolean;flush():boolean;setVisible(visible:boolean):boolean;dispose():void}{
 const pane=document.createElement('section'),heading=document.createElement('div'),title=document.createElement('span'),toggle=document.createElement('button'),textarea=document.createElement('textarea'),reason=document.createElement('p'),error=document.createElement('p')
 pane.className='slides-notes-pane';pane.dataset.notesPanel='';pane.setAttribute('aria-label','演讲者备注面板')
 heading.className='slides-notes-heading';title.textContent='演讲者备注';toggle.type='button'
 textarea.dataset.notesText='';textarea.setAttribute('aria-label','演讲者备注');textarea.placeholder='单击添加演讲者备注';textarea.rows=3;textarea.readOnly=true;textarea.spellcheck=false
 reason.className='slides-notes-reason';reason.id='slides-notes-reason-'+(++notesPaneSequence);textarea.setAttribute('aria-describedby',reason.id);error.className='slides-notes-error';error.setAttribute('role','alert')
 heading.append(title,toggle);pane.append(heading,textarea,reason,error);host.append(pane)
 let current:NotesPaneState|undefined,committed='',composing=false,submitting=false,disposed=false,visible=true
 const report=(message:string)=>{error.textContent=message;options.onError?.(message)}
 const show=(value:boolean)=>{const changed=visible!==value;visible=value;textarea.hidden=!value;reason.hidden=!value;error.hidden=!value;toggle.textContent=value?'收起备注':'展开备注';toggle.setAttribute('aria-expanded',String(value));pane.classList.toggle('is-collapsed',!value);if(changed&&!disposed)options.onVisibleChange?.(value)}
 const submit=(finish:boolean):boolean=>{
  if(disposed||!current||!current.editable)return true
  if(submitting)return false
  if(composing){report('请先完成输入法输入，再切页或保存备注');return false}
  try{
   const text=normalize(textarea.value)
   if(text!==committed){submitting=true;try{options.onChange(current.slideIndex,text)}finally{submitting=false};committed=text}
   error.textContent=''
   if(finish&&textarea.value!==text)textarea.value=text
   return true
  }catch(cause){report(cause instanceof Error?cause.message:'演讲者备注未能提交，请修正后重试');return false}
 }
 const flush=()=>submit(true)
 const setVisible=(value:boolean)=>{if(disposed)return true;if(!value&&!flush())return false;show(value);return true}
 const update=(state:NotesPaneState):boolean=>{
  if(disposed)return false
  const switching=current!==undefined&&current.slideIndex!==state.slideIndex
  if(submitting&&(switching||(current?.editable&&!state.editable)))return false
  if(switching&&!flush())return false
  if(!switching&&current?.editable&&!state.editable&&!flush())return false
  const preserve=!switching&&!!current&&(composing||submitting||(current.editable&&(textarea.value!==committed||!!error.textContent)))
  if(!preserve){
   let baseline=state.text
   if(state.editable)try{baseline=normalize(state.text)}catch(cause){report(cause instanceof Error?cause.message:'演讲者备注来源无效');return false}
   textarea.value=state.text;committed=baseline;error.textContent=''
  }
  current={...state};textarea.readOnly=!state.editable;reason.textContent=state.editable?'':slidesNotesReadOnlyReason(state.reason)
  if(state.visible!==visible&&!setVisible(state.visible))return false
  show(state.visible);return true
 }
 textarea.addEventListener('input',event=>{if(disposed||!current?.editable)return;if(event instanceof InputEvent&&event.isComposing)composing=true;if(!composing)submit(false)})
 textarea.addEventListener('compositionstart',()=>{if(!disposed&&current?.editable)composing=true})
 textarea.addEventListener('compositionend',()=>{if(disposed)return;composing=false;submit(false)})
 textarea.addEventListener('blur',()=>{if(!disposed)flush()})
 toggle.addEventListener('click',()=>{if(!disposed)setVisible(!visible)})
 show(true)
 return {update,flush,setVisible,dispose(){if(disposed)return;disposed=true;current=undefined;composing=false;pane.remove()}}
}
