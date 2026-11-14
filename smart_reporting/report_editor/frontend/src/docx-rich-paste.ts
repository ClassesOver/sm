/** 固定源 f8c17004 PasteOptionsChip/paste-options 的原上下文重放语义，保存走结构化原生意图。 */
import {Extension,type Editor} from '@tiptap/core'
import {DOMParser,type Schema} from '@tiptap/pm/model'
import {closeHistory} from '@tiptap/pm/history'
import type {DocxPmNode} from './docx-operations'
import type {NativeOperation} from './native-draft'
import {pasteContent,pasteParagraph,pasteTargetSupported,richPasteOperation,type PasteNode,type RichPasteOperation} from '../../../reporting/doc_engine/bridge/docx-rich-paste-core'
import {pushDownWebInlineStyles,fillMissingRunFonts,caretFontSlots} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/paste-web-html'
import {mergeFormattingFragment,caretStyleMark,caretParaFormat,defaultPasteMode} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/paste-options'
export type RichPasteMode='source'|'merge'|'text'
export interface RichPastePayload {html?:string|null;text?:string|null}
export const NativeDocxRichPaste=Extension.create({name:'nativeDocxRichPaste',addGlobalAttributes:()=>[{types:['doc'],attributes:{nativeRichPasteOperation:{default:null,rendered:false}}}]})
const copy=<T>(x:T):T=>JSON.parse(JSON.stringify(x))
const fail=(message:string):never=>{throw new Error('粘贴：'+message)}
const registry=new WeakMap<Editor,RichPasteControls>()
export const richPasteControls=(editor:Editor)=>registry.get(editor)
export interface RichPasteControls {paste:(payload:RichPastePayload,mode?:RichPasteMode)=>void;switchMode:(mode:RichPasteMode)=>void;mode:()=>RichPasteMode|null;subscribe:(listener:()=>void)=>()=>void;dismiss:()=>void}
function boundary(blocks:DocxPmNode[],index:number){return blocks.findIndex(n=>n.attrs?.docxIndex===index)}
function splitInline(n:DocxPmNode,offset:number,schema:Schema){const node=schema.nodeFromJSON(n);if(!Number.isSafeInteger(offset)||offset<0||offset>node.content.size)fail('选区位置已变化');const text=node.textContent;if(offset>0&&/[\uD800-\uDBFF]/.test(text[offset-1])&&/[\uDC00-\uDFFF]/.test(text[offset]??''))fail('选区不能拆开 Unicode 字符');return {before:node.content.cut(0,offset),after:node.content.cut(offset)}}
function htmlBlocks(editor:Editor,payload:RichPastePayload,mode:RichPasteMode):PasteNode[]{
 const {$from}=editor.state.selection,schema=editor.schema
 if(mode==='text'||!payload.html){let text=payload.text??'';if(!text&&payload.html){const body=new window.DOMParser().parseFromString(payload.html,'text/html').body;body.querySelectorAll('p,div,li,tr,h1,h2,h3,h4,h5,h6,br').forEach(n=>n.after(body.ownerDocument.createTextNode('\n')));text=body.textContent??''}if(!text.trim())fail('剪贴板没有可粘贴的文字');return pasteContent(text.replace(/\r\n?/g,'\n').split('\n').map(line=>({type:'docParagraph',...(line?{content:[{type:'text',text:line}]}:{})})))}
 const html=payload.html.replace(/<!--\[if[\s\S]*?<!\[endif\]-->/g,'').replace(/<o:p>[\s\S]*?<\/o:p>/g,'').replace(/<li([^>]*)>\s*<p[^>]*>([\s\S]*?)<\/p>\s*<\/li>/g,'<li$1>$2</li>')
 const dom=new window.DOMParser().parseFromString(pushDownWebInlineStyles(html),'text/html')
 dom.querySelectorAll('script,style,iframe,object,embed,link,meta').forEach(n=>n.remove())
 for(const image of dom.querySelectorAll('img')){const src=image.getAttribute('src')??'';if(!/^data:image\/(png|jpeg);base64,/i.test(src))fail('HTML 含外部或非 PNG/JPEG 图片；未访问外网，请先复制图片本体或使用仅保留文本');image.setAttribute('data-inline-image','1');image.setAttribute('dataurl',src);image.setAttribute('widthpx',String(Number(image.getAttribute('width'))||Number.parseFloat(image.style.width)||320));image.setAttribute('heightpx',String(Number(image.getAttribute('height'))||Number.parseFloat(image.style.height)||240))}
 // 外来 data-* 只能经固定源格式白名单读取，原生身份永不进入保存意图。
 const parsed=DOMParser.fromSchema(schema).parse(dom.body)
 let fragment=parsed.content
 const marks=editor.state.storedMarks??$from.marks()
 if(mode==='merge')fragment=mergeFormattingFragment(fragment,schema,caretStyleMark(marks,schema),caretParaFormat($from,schema))
 else{const type=schema.marks.docTextStyle,slots=type?caretFontSlots(marks,type):null;if(slots)fragment=fillMissingRunFonts(fragment,slots,schema)}
 return pasteContent(fragment.toJSON(),true)
}
export function createDocxRichPaste(sourceSha256:string,nativeBlocks?:readonly {docxIndex:number|null;type:string;originalXml?:string|null;hidden?:boolean;sdtShell?:unknown}[]){
 const project=(baseline:DocxPmNode,value:unknown,schema:Schema):DocxPmNode=>{
  const op=richPasteOperation(value,sourceSha256),doc=copy(baseline),blocks=doc.content??[],start=boundary(blocks,op.start.docxIndex),end=boundary(blocks,op.end.docxIndex)
  if(start<0||end<start||blocks.slice(start,end+1).some(n=>!pasteParagraph(n)))fail('选区必须位于可核验的正文段落，不能跨表格或保护对象')
  if(nativeBlocks){const selected=nativeBlocks.filter(b=>b.docxIndex!=null&&b.docxIndex>=op.start.docxIndex&&b.docxIndex<=op.end.docxIndex);if(!selected.length||selected.some(b=>!pasteTargetSupported(b)))fail('选区含字段、保护对象或未知原生内容，请选择普通正文段落')}
  const prefix=splitInline(blocks[start],op.start.offset,schema).before,suffix=splitInline(blocks[end],op.end.offset,schema).after
  const inserted=op.blocks.map(n=>schema.nodeFromJSON(n))
  if(prefix.size){if(pasteParagraph(op.blocks[0]))inserted[0]=inserted[0].copy(prefix.append(inserted[0].content));else inserted.unshift(schema.nodeFromJSON({...blocks[start],content:prefix.toJSON()}))}
  if(suffix.size){const last=inserted.length-1;if(pasteParagraph(inserted[last].toJSON() as PasteNode))inserted[last]=inserted[last].copy(inserted[last].content.append(suffix));else inserted.push(schema.nodeFromJSON({...blocks[end],content:suffix.toJSON()}))}
  blocks.splice(start,end-start+1,...inserted.map(n=>n.toJSON() as DocxPmNode));doc.attrs={...doc.attrs,nativeRichPasteOperation:op};return schema.nodeFromJSON(doc).toJSON() as DocxPmNode
 }
 const normalize=(baseline:DocxPmNode,current:DocxPmNode,schema:Schema)=>{const raw=current.attrs?.nativeRichPasteOperation;if(raw==null)return{current,operations:[] as NativeOperation[]};const op=richPasteOperation(raw,sourceSha256);if(JSON.stringify(project(baseline,op,schema))!==JSON.stringify(current))fail('粘贴后结构已变化，请先保存粘贴内容再继续编辑');return{current:baseline,operations:[op as unknown as NativeOperation]}}
 const replay=(baseline:DocxPmNode,ops:readonly NativeOperation[],schema:Schema)=>{const selected=ops.filter(op=>op.kind==='pasteRichContent');if(!selected.length)return baseline;if(selected.length!==1||ops.length!==1)fail('请将富文本粘贴单独保存');return project(baseline,selected[0],schema)}
 const controls=(editor:Editor,pending:()=>readonly NativeOperation[],containerReason:()=>string|null=()=>null):RichPasteControls=>{
  const baseline=editor.getJSON() as DocxPmNode
  let last:{payload:RichPastePayload;mode:RichPasteMode;start:RichPasteOperation['start'];end:RichPasteOperation['end'];selection:{from:number;to:number};storedMarks:typeof editor.state.storedMarks}|null=null,own=false
  const listeners=new Set<()=>void>(),changed=()=>listeners.forEach(fn=>fn())
  const guard=()=>{const reason=containerReason();if(reason)fail(reason);if(!editor.isEditable)fail('当前文档不可编辑');if(pending().some(op=>op.kind!=='pasteRichContent'))fail('请先保存其他修改，再粘贴富文本')}
  const apply=(payload:RichPastePayload,mode:RichPasteMode,start:RichPasteOperation['start'],end:RichPasteOperation['end'])=>{
   guard();const op:RichPasteOperation={kind:'pasteRichContent',sourceSha256,start,end,blocks:htmlBlocks(editor,payload,mode)},next=editor.schema.nodeFromJSON(project(baseline,op,editor.schema));own=true
   try{const tr=closeHistory(editor.state.tr.replaceWith(0,editor.state.doc.content.size,next.content).setDocAttribute('nativeRichPasteOperation',op));editor.view.dispatch(tr);editor.view.dispatch(closeHistory(editor.state.tr));editor.view.focus()}finally{own=false}changed()
  }
  const result:RichPasteControls={paste(payload,mode=defaultPasteMode()){guard();if(editor.state.doc.attrs.nativeRichPasteOperation)fail('请先保存上一次粘贴或撤销后再粘贴');const {$from,$to,from,to}=editor.state.selection;if($from.depth!==1||$to.depth!==1)fail('请将光标放在正文段落中');const start={docxIndex:Number($from.parent.attrs.docxIndex),offset:$from.parentOffset},end={docxIndex:Number($to.parent.attrs.docxIndex),offset:$to.parentOffset};if($from.parent.attrs.docxIndex==null||$to.parent.attrs.docxIndex==null)fail('选区没有原生来源身份');const captured={payload:copy(payload),mode,start,end,selection:{from,to},storedMarks:editor.state.storedMarks};apply(payload,mode,start,end);last=captured;changed()},switchMode(mode){if(!last)fail('当前没有可切换的粘贴');guard();const current=editor.state,original=editor.schema.nodeFromJSON(baseline),{selection,storedMarks}=last!;own=true
   // 只把原上下文借给解析器；不发出中间文档事务，不制造额外 Undo 步骤。
   try{const restored=current.reconfigure({plugins:[]});const tr=restored.tr.replaceWith(0,restored.doc.content.size,original.content);const temporary=restored.apply(tr);const resolved=temporary.doc.resolve(selection.from);const fake={...editor,state:{...temporary,selection:{$from:resolved},storedMarks},schema:editor.schema} as unknown as Editor;const blocks=htmlBlocks(fake,last!.payload,mode);const op:RichPasteOperation={kind:'pasteRichContent',sourceSha256,start:last!.start,end:last!.end,blocks};const next=editor.schema.nodeFromJSON(project(baseline,op,editor.schema));editor.view.dispatch(closeHistory(current.tr.replaceWith(0,current.doc.content.size,next.content).setDocAttribute('nativeRichPasteOperation',op)));editor.view.dispatch(closeHistory(editor.state.tr));last!.mode=mode}finally{own=false}changed()},mode:()=>last?.mode??null,subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn)},dismiss(){last=null;changed()}}
  editor.on('transaction',({transaction})=>{if(!own&&transaction.docChanged&&last){last=null;changed()}});registry.set(editor,result);editor.on('destroy',()=>registry.delete(editor));return result
 }
 return {project,normalize,replay,controls}
}
