import type {NativeOperation} from './native-draft'
import {encodeStyle,decodeStyle,patchStyle,spliceCharColors,colorsToRuns,runsToColors} from './pdf-selection-style-source'
export interface PdfSelectionStyleRun{start:number;end:number;font?:'arial'|'times'|'courier';size?:number;color?:[number,number,number];bold?:boolean;italic?:boolean}
const fields=['font','size','color','bold','italic'] as const
const scalarBoundary=(text:string,index:number)=>!(index>0&&index<text.length&&/[\uD800-\uDBFF]/.test(text[index-1]!)&&/[\uDC00-\uDFFF]/.test(text[index]!))
export function validatePdfSelectionStyleRuns(text:string,runs:unknown):asserts runs is PdfSelectionStyleRun[]|undefined{
 if(runs===undefined)return
 if(!Array.isArray(runs)||runs.length>4000)throw Error('选区样式范围无效')
 let end=0
 for(const run of runs){
  if(!run||typeof run!=='object'||Array.isArray(run)||Object.keys(run).some(key=>!['start','end',...fields].includes(key)))throw Error('选区样式字段无效')
  if(!Number.isInteger(run.start)||!Number.isInteger(run.end)||run.start<end||run.start<0||run.end<=run.start||run.end>text.length||!scalarBoundary(text,run.start)||!scalarBoundary(text,run.end))throw Error('选区须为升序不重叠的完整 UTF-16 字符范围')
  if(!fields.some(key=>run[key]!==undefined))throw Error('选区样式不得为空')
  if(run.font!==undefined&&!['arial','times','courier'].includes(run.font))throw Error('选区字体无效')
  if(run.size!==undefined&&(!Number.isFinite(run.size)||run.size<6||run.size>72))throw Error('选区字号须为6–72')
  if(run.color!==undefined&&(!Array.isArray(run.color)||run.color.length!==3||run.color.some((value:unknown)=>typeof value!=='number'||!Number.isFinite(value)||value<0||value>1)))throw Error('选区颜色无效')
  if(run.bold!==undefined&&typeof run.bold!=='boolean'||run.italic!==undefined&&typeof run.italic!=='boolean')throw Error('选区粗斜体无效')
  end=run.end
 }
}
const hex=(color:number[])=>'#'+color.map(value=>Math.round(value*255).toString(16).padStart(2,'0')).join('')
function keysFromRuns(text:string,runs:PdfSelectionStyleRun[]|undefined){return runsToColors(text.length,(runs??[]).map(run=>({start:run.start,end:run.end,color:encodeStyle({...run,color:run.color?hex(run.color):undefined})})))}
function runsFromKeys(keys:string[]):PdfSelectionStyleRun[]{return colorsToRuns(keys).map(run=>{const style=decodeStyle(run.color),out:PdfSelectionStyleRun={start:run.start,end:run.end};if(style.color)out.color=[1,3,5].map(start=>parseInt(style.color!.slice(start,start+2),16)/255) as [number,number,number];if(style.font)out.font=style.font as PdfSelectionStyleRun['font'];if(style.size!==undefined)out.size=style.size;if(style.bold!==undefined)out.bold=style.bold;if(style.italic!==undefined)out.italic=style.italic;return out})}
export function canonicalPdfSelectionStyleRuns(text:string,runs:unknown){validatePdfSelectionStyleRuns(text,runs);return runsFromKeys(keysFromRuns(text,runs))}
/** Selection semantics reuse the pinned UTF-16 char-key splice and patch helpers. */
export function bindPdfTextSelectionStyles(root:HTMLElement){
 const owner=root.ownerDocument,section=owner.createElement('fieldset'),legend=owner.createElement('legend');legend.textContent='选区文字样式';section.className='pdf-text-selection-style';section.append(legend)
 const hint=owner.createElement('p');hint.textContent='选中替换文字中的字符后应用或清除选区样式。选区保持不变；最终字体与混排位置请核对实际 PDF 预览。';section.append(hint)
 function label(name:string,input:HTMLElement){const row=owner.createElement('label');row.textContent=name;input.setAttribute('aria-label','选区'+name);row.append(input);section.append(row);return input}
 function select(name:string,options:[string,string][]){const input=label(name,owner.createElement('select')) as HTMLSelectElement;for(const [value,title]of options){const option=owner.createElement('option');option.value=value;option.textContent=title;input.append(option)}return input}
 const font=select('字体',[['','不修改字体'],['arial','Arial / Liberation Sans'],['times','Times / Liberation Serif'],['courier','Courier / Liberation Mono']])
 const size=label('字号',owner.createElement('input')) as HTMLInputElement;size.type='number';size.min='6';size.max='72';size.step='any';size.placeholder='不修改字号'
 const bold=select('粗体',[['','不修改粗体'],['true','粗体'],['false','常规字重']]),italic=select('斜体',[['','不修改斜体'],['true','斜体'],['false','正体']])
 const useColor=label('指定颜色',owner.createElement('input')) as HTMLInputElement;useColor.type='checkbox'
 const color=label('颜色',owner.createElement('input')) as HTMLInputElement;color.type='color';color.value='#cc2222'
 const apply=owner.createElement('button');apply.type='button';apply.textContent='对选区应用样式';apply.dataset.pdfSelectionStyleApply=''
 const clear=owner.createElement('button');clear.type='button';clear.textContent='清除选区样式';clear.dataset.pdfSelectionStyleClear=''
 const status=owner.createElement('p');status.setAttribute('role','status');const current=owner.createElement('p');current.dataset.pdfSelectionStyleCurrent='';current.setAttribute('aria-live','polite');const error=owner.createElement('p');error.setAttribute('role','alert');section.append(apply,clear,status,current,error);root.append(section)
 let textarea:HTMLTextAreaElement|undefined,value='',keys:string[]=[],disabled=false,range:[number,number,'forward'|'backward'|'none']=[0,0,'none']
 function sync(){if(textarea&&textarea.value!==value){keys=spliceCharColors(value,keys,textarea.value);value=textarea.value}status.textContent=colorsToRuns(keys).length?'已配置 '+colorsToRuns(keys).length+' 段选区样式；UTF-16 范围 '+colorsToRuns(keys).map(run=>'['+run.start+','+run.end+')').join('、'):'尚未配置选区样式'}
 function renderSelection(){const[start,end]=range;const valid=!!textarea&&end>start&&scalarBoundary(value,start)&&scalarBoundary(value,end);const labels={font:'字体',size:'字号',color:'颜色',bold:'粗体',italic:'斜体'},parts=[];for(const field of fields){const selected=valid?keys.slice(start,end).map(key=>decodeStyle(key)[field]):[];const first=selected[0];const state=!valid?'none':selected.some(value=>value!==first)?'mixed':first===undefined?'inherit':String(first);current.dataset[field]=state;parts.push(labels[field]+'：'+(state==='mixed'?'混合':state==='inherit'?'继承整对象':state==='none'?'—':field==='bold'||field==='italic'?state==='true'?'开启':'关闭':state))}current.textContent=valid?'当前选区 ['+start+','+end+')：'+parts.join('；'):'当前选区：未选择字符';updateDisabled()}
 function capture(){if(textarea){sync();range=[textarea.selectionStart,textarea.selectionEnd,textarea.selectionDirection]}renderSelection()}
 const selectionChanged=()=>{if(owner.activeElement===textarea)capture()};owner.addEventListener('selectionchange',selectionChanged)
 const events=['select','keyup','pointerup','mouseup','input']
 function bindTextarea(next:HTMLTextAreaElement){if(textarea===next)return;for(const event of events)textarea?.removeEventListener(event,capture);textarea=next;value=next.value;keys=[];for(const event of events)next.addEventListener(event,capture);capture();updateDisabled()}
 function updateDisabled(){for(const control of section.querySelectorAll('input,select,button'))(control as HTMLInputElement).disabled=disabled||!textarea;color.disabled=disabled||!textarea||!useColor.checked;const[start,end]=range,valid=!!textarea&&end>start&&scalarBoundary(value,start)&&scalarBoundary(value,end);apply.disabled=disabled||!valid;clear.disabled=disabled||!valid||!keys.slice(start,end).some(Boolean)}
 function act(reset:boolean){if(disabled||!textarea)return;capture();try{const[start,end,direction]=range;if(end<=start)throw Error('请先在替换后的文字中选择字符');if(!scalarBoundary(value,start)||!scalarBoundary(value,end))throw Error('选区不能拆分 UTF-16 代理对');const patch:Parameters<typeof patchStyle>[1]=reset?{font:null,size:null,color:null,bold:null,italic:null}:{};if(!reset){if(font.value)patch.font=font.value;if(size.value)patch.size=Number(size.value);if(bold.value)patch.bold=bold.value==='true';if(italic.value)patch.italic=italic.value==='true';if(useColor.checked)patch.color=color.value;if(!Object.keys(patch).length)throw Error('请选择需要应用的选区样式');const candidate={start,end,...patch,color:typeof patch.color==='string'?[1,3,5].map(at=>parseInt(patch.color!.slice(at,at+2),16)/255):undefined};validatePdfSelectionStyleRuns(value,[candidate])}for(let i=start;i<end;i++)keys[i]=patchStyle(keys[i]??'',patch);error.textContent='';sync();renderSelection();textarea.focus();textarea.setSelectionRange(start,end,direction)}catch(cause){error.textContent=cause instanceof Error?cause.message:String(cause)}}
 const applyClick=()=>act(false),clearClick=()=>act(true);apply.addEventListener('click',applyClick);clear.addEventListener('click',clearClick);useColor.addEventListener('change',updateDisabled);section.addEventListener('pointerdown',capture)
 const existing=root.querySelector<HTMLTextAreaElement>('textarea[aria-label="替换后的文字"]');if(existing)bindTextarea(existing);updateDisabled()
 return {bindTextarea,clearFields(touched:readonly (typeof fields)[number][]){sync();const patch:Parameters<typeof patchStyle>[1]={};for(const field of touched)patch[field]=null;keys=keys.map(key=>patchStyle(key,patch));sync();renderSelection();error.textContent=''},read(){sync();const runs=runsFromKeys(keys);validatePdfSelectionStyleRuns(value,runs);return runs},fill(operation?:NativeOperation){value=textarea?.value??(typeof operation?.newText==='string'?operation.newText:'');validatePdfSelectionStyleRuns(value,operation?.styleRuns);keys=keysFromRuns(value,operation?.styleRuns);sync();error.textContent='';capture()},setDisabled(value:boolean){disabled=value;updateDisabled()},dispose(){for(const event of events)textarea?.removeEventListener(event,capture);section.removeEventListener('pointerdown',capture);owner.removeEventListener('selectionchange',selectionChanged);section.remove()}}
}
