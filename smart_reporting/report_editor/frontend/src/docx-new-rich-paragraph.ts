import {docxInsertionAnchor} from './docx-insertion-anchor'
import {Extension} from '@tiptap/core'
import {serializeMarks} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/caret-marks'
import type {Schema} from '@tiptap/pm/model'
import type {Run} from '../../../reporting/doc_engine/packages/docx-engine/src/types'
import {NEW_RICH_PARA_KEYS,NEW_RICH_RUN_KEYS,normalizeNewRichParagraph,validateNewRichParagraphOperation,type NewRichParagraphBindings,type NewRichParagraphOperation,type NewRichParagraphSpec,type NewRichParagraphRun,resolveNewRichParagraphSourceRun} from '../../../reporting/doc_engine/bridge/docx-new-rich-paragraph'
import type {DocxAnchor,DocxPmNode} from './docx-operations'
export type {NewRichParagraphBindings,NewRichParagraphOperation}
export type NewRichParagraphFrontendAnchor=DocxAnchor&{insertParagraphAdjacentEditable?:boolean}
/** A split creates a new native object. It must never duplicate the source anchor. */
export const NativeNewRichParagraph = Extension.create({name:'nativeNewRichParagraph',addGlobalAttributes:()=>[{types:['docParagraph','docHeading','docListItem'],attributes:{docxIndex:{default:null,keepOnSplit:false,rendered:false}}}]})
function fail():never{throw new Error('新增段落包含尚不能安全保存的属性、来源身份或内联对象')}
const equal=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b)
/** Schema defaults are not authored fields. Unknown attributes are always rejected,
 * including attributes ProseMirror would otherwise silently discard. */
function authored(attrs:Record<string,unknown>|undefined,defaults:Record<string,{default?:unknown}>,allowed:readonly string[]){
 const out:Record<string,unknown>={}
 for(const [key,value] of Object.entries(attrs??{})){
  if(!(key in defaults))fail()
  if(value==null||equal(value,defaults[key]?.default))continue
  if(!allowed.includes(key))throw new Error(`新增段落属性暂不支持：${key}`)
  out[key]=value
 }
 return out
}
function typedRun(child:DocxPmNode,schema:Schema,bindings:NewRichParagraphBindings={},source=false):Record<string,unknown>{
  if(!['text','hardBreak'].includes(child.type)||Object.keys(child).some(k=>!['type','text','attrs','marks'].includes(k)))fail()
  if(child.type==='hardBreak'){if(Object.keys(authored(child.attrs,schema.nodes.hardBreak?.spec.attrs??{},[])).length)fail()}
  else if(child.attrs||typeof child.text!=='string')fail()
  const run:Record<string,unknown>={text:child.type==='hardBreak'?'\n':child.text}
  const seen=new Set<string>()
  for(const mark of child.marks??[]){
   if(!mark||Object.keys(mark).some(k=>!['type','attrs'].includes(k)))fail()
   if(seen.has(mark.type))fail();seen.add(mark.type)
   if(['bold','italic','underline','strike'].includes(mark.type)){authored(mark.attrs,schema.marks[mark.type]?.spec.attrs??{},[]);run[mark.type]=true}
   else if(mark.type==='docTextStyle'){
    const attrs={...mark.attrs},raw=attrs.rawRPr
    if(raw!=null){
     if(typeof raw!=='string')fail()
     if(source){run.rawRPr=raw}
     else{
      let matched:Record<string,unknown>|undefined
      for(const [blockId,entry] of bindings.sourceRuns??[]){let from=0;for(const candidate of entry.runs){if(candidate.rawRPr===raw){const ref={blockId,expectedObjectSha256:entry.expectedObjectSha256,from};try{resolveNewRichParagraphSourceRun(ref,bindings);matched=ref;break}catch{ /* a source run with unknown raw formatting is not eligible */ }}from+=candidate.text.length}if(matched)break}
      if(!matched)fail();run.sourceFormat=matched
     }
     attrs.rawRPr=null
    }
    Object.assign(run,authored(attrs,schema.marks.docTextStyle?.spec.attrs??{},NEW_RICH_RUN_KEYS.filter(k=>!['text','bold','italic','underline','strike','sourceFormat'].includes(k))))
   }
   else fail()
  }
  return run
 }
/** Trusted baseline-only metadata map. Unsupported source leaves retain their
 * text width but supply no reusable raw metadata, preserving source offsets. */
export function newRichParagraphSourceRuns(original:DocxPmNode,anchors:readonly DocxAnchor[],schema:Schema):Map<string,{expectedObjectSha256:string;runs:Run[]}>{
 const sources=new Map<string,{expectedObjectSha256:string;runs:Run[]}>()
 for(const node of original.content??[]){
  const matches=anchors.filter(a=>a.docxIndex===node.attrs?.docxIndex&&a.editable)
  if(matches.length!==1||!['docParagraph','docHeading','docListItem'].includes(node.type)||(node.content??[]).some(c=>!['text','hardBreak'].includes(c.type)))continue
  const runs:Run[]=(node.content??[]).map(child=>{try{return typedRun(child,schema,{},true) as unknown as Run}catch{return {text:child.type==='hardBreak'?'\n':child.text??''}}})
  sources.set(matches[0]!.blockId,{expectedObjectSha256:matches[0]!.expectedObjectSha256,runs})
 }
 return sources
}
export function newRichParagraphSpec(node:DocxPmNode,schema:Schema,bindings:NewRichParagraphBindings={}):NewRichParagraphSpec{
 if(!['docParagraph','docHeading','docListItem'].includes(node.type)||node.attrs?.docxIndex!=null||Object.keys(node).some(k=>!['type','attrs','content'].includes(k)))fail()
 const type=schema.nodes[node.type];if(!type)fail()
 const a=authored(node.attrs,type.spec.attrs??{},[...NEW_RICH_PARA_KEYS,'styleId','level','outlineOnly','kind','numId','ilvl','caretMarks'])
 const result:Record<string,unknown>={type:node.type==='docHeading'?'heading':node.type==='docListItem'?'listItem':'paragraph',runs:[]}
 if(node.type==='docHeading'){result.level=node.attrs?.level??1;if(node.attrs?.outlineOnly===true)result.outlineOnly=true}
 if(a.styleId!==undefined)result.styleId=a.styleId
 if(node.type==='docListItem')result.list={kind:node.attrs?.kind,numId:node.attrs?.numId,ilvl:node.attrs?.ilvl??0}
 const format=Object.fromEntries(Object.entries(a).filter(([k])=>(NEW_RICH_PARA_KEYS as readonly string[]).includes(k)));if(Object.keys(format).length)result.format=format

 for(const child of node.content??[]){if(child.type==='text'&&!child.text)fail();(result.runs as unknown[]).push(typedRun(child,schema,bindings))}
 if(a.caretMarks!==undefined){if(typeof a.caretMarks!=='string')fail();let marks:unknown;try{marks=JSON.parse(a.caretMarks)}catch{fail()}if(!Array.isArray(marks))fail();result.caretFormat=typedRun({type:'text',text:'',marks:marks as {type:string;attrs?:Record<string,unknown>}[]},schema,bindings)}
 return normalizeNewRichParagraph(result,bindings)
}
/** A newline within a run means Shift+Enter (w:br). Separate inserted nodes mean
 * Enter/new paragraphs; this helper never flattens one into the other. */
export function projectNewRichParagraph(value:unknown,schema:Schema,bindings:NewRichParagraphBindings={}):DocxPmNode{
 const spec=normalizeNewRichParagraph(value,bindings),attrs:Record<string,unknown>={...spec.format,docxIndex:null,...(spec.styleId?{styleId:spec.styleId}:{})}
 if(spec.type==='heading'){attrs.level=spec.level;attrs.outlineOnly=spec.outlineOnly??false}
 if(spec.list)Object.assign(attrs,spec.list)
 const content:DocxPmNode[]=[]
 const runMarks=(run:NewRichParagraphRun)=>{
  const marks:{type:string;attrs?:Record<string,unknown>}[]=[]
  for(const key of ['bold','italic','underline','strike'] as const)if(run[key]===true)marks.push({type:key})
  const style=Object.fromEntries(Object.entries(run).filter(([k])=>!['text','bold','italic','underline','strike','sourceFormat'].includes(k)))
  if(run.sourceFormat)style.rawRPr=resolveNewRichParagraphSourceRun(run.sourceFormat,bindings).rawRPr
  if(Object.keys(style).length)marks.push({type:'docTextStyle',attrs:style})
  return marks
 }
 if(spec.caretFormat)attrs.caretMarks=serializeMarks(runMarks(spec.caretFormat).map(m=>schema.marks[m.type]!.create(m.attrs)))
 for(const run of spec.runs){
  const marks=runMarks(run)
  const parts=run.text.split('\n');parts.forEach((part,i)=>{if(i)content.push({type:'hardBreak',...(marks.length?{marks}:{})});if(part)content.push({type:'text',text:part,...(marks.length?{marks}:{})})})
 }
 return schema.nodeFromJSON({type:spec.type==='heading'?'docHeading':spec.type==='listItem'?'docListItem':'docParagraph',attrs,...(content.length?{content}:{})}).toJSON() as DocxPmNode
}
function anchorType(node:DocxPmNode){return node.type==='docTable'?'table':node.type==='docHeading'?'heading':node.type==='docListItem'?'listItem':node.type==='docParagraph'?'paragraph':''}
/** Ordered insertion-loop hook; compiler has no dispatch/history side effects. */
export function docxNewRichParagraphOperation(original:DocxPmNode,current:DocxPmNode,index:number,anchors:readonly NewRichParagraphFrontendAnchor[],schema:Schema,bindings:NewRichParagraphBindings={}):NewRichParagraphOperation|undefined{
 const node=current.content?.[index];if(!node||node.attrs?.docxIndex!=null||!['docParagraph','docHeading','docListItem'].includes(node.type))return undefined
 bindings={...bindings,sourceRuns:bindings.sourceRuns??newRichParagraphSourceRuns(original,anchors,schema)}
 const paragraph=newRichParagraphSpec(node,schema,bindings)
 if(!schema.nodeFromJSON(node).eq(schema.nodeFromJSON(projectNewRichParagraph(paragraph,schema,bindings))))fail()
 const before=original.content??[],after=current.content??[],id=(n:DocxPmNode)=>n.attrs?.docxIndex
 const valid=(n:DocxPmNode)=>id(n)!=null&&!!anchorType(n)&&anchors.some(a=>a.docxIndex===id(n)&&(n.type==='docTable'?a.insertParagraphAdjacentEditable===true:a.editable)&&a.blockId&&a.expectedObjectSha256)&&before.filter(b=>id(b)===id(n)).length===1
 const insertion=docxInsertionAnchor(before,after,index,valid),target=insertion?.target
 if(!target)fail()
 const matches=anchors.filter(a=>a.docxIndex===id(target));if(matches.length!==1)fail();const a=matches[0]!
 return validateNewRichParagraphOperation({kind:'insertRichParagraph',blockId:a.blockId,expectedObjectSha256:a.expectedObjectSha256,position:insertion!.position,paragraph},{...a,type:anchorType(target)},bindings)
}
/** Uses the caller's common afterCounts so multiple/mixed inserted objects retain order. */
export function replayDocxNewRichParagraph(result:DocxPmNode,operation:unknown,anchors:readonly NewRichParagraphFrontendAnchor[],schema:Schema,afterCounts:Map<string,number>,bindings:NewRichParagraphBindings={}):void{
 bindings={...bindings,sourceRuns:bindings.sourceRuns??newRichParagraphSourceRuns(result,anchors,schema)}
 const raw=operation as NewRichParagraphOperation,a=anchors.find(item=>item.blockId===raw?.blockId&&item.expectedObjectSha256===raw?.expectedObjectSha256)
 if(!a)fail();const index=result.content?.findIndex(n=>n.attrs?.docxIndex===a.docxIndex)??-1;if(index<0)fail()
 const op=validateNewRichParagraphOperation(operation,{...a,type:anchorType(result.content![index]!)},bindings),offset=op.position==='after'?(afterCounts.get(a.blockId)??0)+1:0
 result.content!.splice(index+offset,0,projectNewRichParagraph(op.paragraph,schema,bindings));if(op.position==='after')afterCounts.set(a.blockId,offset)
}
