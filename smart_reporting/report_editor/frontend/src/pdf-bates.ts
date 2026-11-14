import './pdf-bates.css'
import {buildBatesInserts,formatBates,type BatesConfig} from '../../../reporting/pdf_engine/vendor/bates/bates'
import {BATES_COLORS,BATES_POSITIONS,validateBatesConfig,validateBatesOperation,type BatesOperation} from '../../../reporting/pdf_engine/vendor/bates/protocol'
import type {NativeDraft,NativeOperation} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
import {installFocusTrap} from './focus-trap'
export type {BatesOperation}
export function buildPdfBatesOperation(sourceSha256:string,pages:PdfPageIdentity[],config:BatesConfig,measure:(text:string,size:number)=>number):BatesOperation{
 validateBatesConfig(config)
 const inputs=buildBatesInserts(pages.map(page=>({width:page.cropBox.width*(page.userUnit??1),height:page.cropBox.height*(page.userUnit??1),rotate:page.rotation,x0:page.cropBox.x,y0:page.cropBox.y,userUnit:page.userUnit??1})),config,measure)
 const operation:BatesOperation={kind:'addBates',sourceSha256,config:structuredClone(config),entries:inputs.map((input,ordinal)=>({pageId:pages[input.pageIndex]!.pageId,ordinal,origin:input.origin,rotate:((input.rotate??0)%360+360)%360,lineXOffsets:[input.lineXOffsets![0]!]}))}
 validateBatesOperation(operation,new Set(pages.map(page=>page.pageId)),sourceSha256);return operation
}
export function validatePdfBates(pages:PdfPageIdentity[],operations:NativeOperation[]){
 const known=new Set([...pages.map(page=>page.pageId),...operations.filter(op=>op.kind==='insertBlankPage').map(op=>String(op.pageId))])
 for(const op of operations.filter(op=>op.kind==='addBates')){
  const source=pages[0]?.pageId.match(/^sha256:([a-f0-9]{64}):page:/)?.[1]??''
  validateBatesOperation(op as unknown as BatesOperation,known,source)
 }
}
export function appendPdfBatesPreview(layer:HTMLElement,page:PdfPageIdentity,operations:NativeOperation[],viewport:{width:number;height:number;transform:number[]}){
 const entries=operations.filter(op=>op.kind==='addBates').flatMap(raw=>{const op=raw as BatesOperation;return op.entries.filter(entry=>entry.pageId===page.pageId).map(entry=>({entry,config:op.config}))})
 if(!entries.length)return
 const ns='http://www.w3.org/2000/svg',svg=layer.ownerDocument.createElementNS(ns,'svg'),group=layer.ownerDocument.createElementNS(ns,'g')
 svg.setAttribute('class','pdf-pending-drawings pdf-pending-bates');svg.setAttribute('width',String(viewport.width));svg.setAttribute('height',String(viewport.height));group.setAttribute('transform',`matrix(${viewport.transform.join(' ')})`)
 for(const {entry,config}of entries){const text=layer.ownerDocument.createElementNS(ns,'text'),angle=entry.rotate*Math.PI/180,c=Math.round(Math.cos(angle)),s=Math.round(Math.sin(angle));text.dataset.pdfBatesPreview='';text.setAttribute('transform',`matrix(${c} ${s} ${s} ${-c} ${entry.origin.join(' ')})`);text.setAttribute('x',String(entry.lineXOffsets[0]));text.setAttribute('y','0');text.setAttribute('font-size',String(config.fontSize));text.setAttribute('fill',`rgb(${config.color.map(v=>Math.round(v*255)).join(',')})`);text.textContent=formatBates(config.prefix,config.start+entry.ordinal,config.digits);group.append(text)}
 svg.append(group);layer.append(svg)
}
/** 源 BatesDialog 的配置；原位内容在应用时固定，不使用水印位图或最终页码替代。 */
export function bindPdfBates(options:{root:HTMLElement;draft:NativeDraft;pages:()=>PdfPageIdentity[];unavailable:()=>string|null;changed:()=>void;status:(message:string)=>void;measure?:(text:string,size:number)=>number}){
 const owner=options.root.ownerDocument,dialog=owner.createElement('dialog');dialog.className='pdf-layout-dialog pdf-bates-dialog';dialog.setAttribute('aria-label','Bates 编号')
 const title=owner.createElement('h3');title.textContent='Bates 编号'
 const hint=owner.createElement('p');hint.textContent='按当前可见页序为所选范围插入可搜索编号。应用后内容固定；重排不重编号，后插入页不自动编号，删页不补号。'
 const fields=owner.createElement('div');fields.className='pdf-bates-fields';dialog.append(title,hint,fields)
 function field(name:string,type:string,value:string){const label=owner.createElement('label');label.textContent=name;const input=owner.createElement('input');input.type=type;input.value=value;input.setAttribute('aria-label','Bates '+name);label.append(input);fields.append(label);return input}
 const prefix=field('前缀','text','');prefix.placeholder='ACME-';prefix.maxLength=200
 const start=field('起始编号','number','1');start.min='0';start.step='1'
 const digits=field('编号位数','number','6');digits.min='1';digits.max='15';digits.step='1'
 const size=field('字号','number','10');size.min='6';size.max='36';size.step='any'
 const first=field('起始页','number','1');first.min='1';first.step='1'
 const last=field('结束页','number','');last.placeholder='留空至末页';last.min='1';last.step='1'
 const colorLabel=owner.createElement('label');colorLabel.textContent='颜色';const color=owner.createElement('select');color.setAttribute('aria-label','Bates 颜色');for(const [index,label]of ['黑色','红色','蓝色','绿色'].entries()){const option=owner.createElement('option');option.value=String(index);option.textContent=label;color.append(option)}colorLabel.append(color);fields.append(colorLabel)
 const positionLabel=owner.createElement('label');positionLabel.textContent='位置';const position=owner.createElement('select');position.setAttribute('aria-label','Bates 位置');for(const [index,value]of BATES_POSITIONS.entries()){const option=owner.createElement('option');option.value=value;option.textContent=['左上','上方居中','右上','左下','下方居中','右下'][index]!;position.append(option)}position.value='bottom-right';positionLabel.append(position);fields.append(positionLabel)
 const preview=owner.createElement('output');preview.className='pdf-bates-preview';preview.setAttribute('aria-label','Bates 编号预览');dialog.append(preview)
 const error=owner.createElement('p');error.setAttribute('role','alert');dialog.append(error)
 const actions=owner.createElement('div');actions.className='pdf-layout-actions';const cancel=owner.createElement('button');cancel.type='button';cancel.textContent='取消';const apply=owner.createElement('button');apply.type='button';apply.textContent='应用 Bates 编号';apply.dataset.batesApply='';actions.append(cancel,apply);dialog.append(actions);options.root.append(dialog)
 let disposed=false,snapshot='',returnFocus:HTMLElement|null=null
 const config=():BatesConfig=>({prefix:prefix.value,start:Number(start.value),digits:Number(digits.value),fontSize:Number(size.value),color:BATES_COLORS[Number(color.value)]!,position:position.value as BatesConfig['position'],firstPage:Number(first.value),lastPage:last.value.trim()===''?null:Number(last.value)})
 const sample=()=>{const cfg=config();try{validateBatesConfig(cfg);const count=Math.max(0,Math.min(cfg.lastPage??options.pages().length,options.pages().length)-cfg.firstPage+1);preview.textContent=count?`${formatBates(cfg.prefix,cfg.start,cfg.digits)}${count>1?' … '+formatBates(cfg.prefix,cfg.start+count-1,cfg.digits):''}`:'该范围没有页面';preview.style.textAlign=cfg.position.endsWith('right')?'right':cfg.position.endsWith('center')?'center':'left';preview.style.color=`rgb(${cfg.color.map(v=>Math.round(v*255)).join(',')})`}catch{preview.textContent='请填写有效编号配置'}}
 fields.addEventListener('input',sample);fields.addEventListener('change',sample)
 cancel.addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>returnFocus?.focus())
 const trap=installFocusTrap(dialog)
 apply.addEventListener('click',()=>{if(disposed||!dialog.open)return;try{
  const blocked=options.unavailable();if(blocked)throw Error(blocked)
  if(snapshot!==JSON.stringify(options.draft.operations))throw Error('草稿已变化，请关闭后重新配置 Bates 编号')
  const cfg=config();validateBatesConfig(cfg)
  if(cfg.firstPage>options.pages().length){dialog.close();options.status('所选范围没有页面，未添加 Bates 编号');return}
  const canvas=owner.createElement('canvas'),context=options.measure?null:canvas.getContext('2d')
  const measure=options.measure??((text:string,fontSize:number)=>{if(!context)throw Error('浏览器无法测量编号文字');context.font=`${fontSize}px ${getComputedStyle(owner.body).fontFamily}`;return context.measureText(text).width})
  const operation=buildPdfBatesOperation(options.draft.identity.sourceSha256,options.pages(),cfg,measure)
  options.draft.setOperations([...options.draft.operations,operation]);dialog.close();options.changed()
 }catch(cause){error.textContent=cause instanceof Error?cause.message:String(cause)}})
 return {open(){if(disposed)return;const reason=options.unavailable();if(reason){options.status(reason);return}returnFocus=owner.activeElement as HTMLElement;snapshot=JSON.stringify(options.draft.operations);error.textContent='';first.value='1';last.value='';sample();dialog.showModal();prefix.focus()},incompleteReason:()=>dialog.open?'请先应用或取消 Bates 编号配置':null,dispose(){disposed=true;trap();dialog.remove()}}
}
