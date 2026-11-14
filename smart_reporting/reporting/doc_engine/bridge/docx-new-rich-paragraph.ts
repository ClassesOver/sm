/** New paragraphs use the source GeneratedBlock writer, never client XML or relationships.
 * This module is pure and can also validate browser draft/replay payloads. */
import {generateParagraphXml,mergeRPrModel} from '../packages/docx-engine/src/generate'
import type {GeneratedBlock, ParaFormat, Run} from '../packages/docx-engine/src/types'
export interface NewRichSourceFormat {blockId:string;expectedObjectSha256:string;from:number}
export interface NewRichParagraphRun extends Run {sourceFormat?:NewRichSourceFormat}
export interface NewRichParagraphSource {expectedObjectSha256:string;runs:readonly Run[]}
export interface NewRichParagraphBindings {
 sourceRuns?:ReadonlyMap<string,NewRichParagraphSource>
 styles?: ReadonlyMap<string,{type:string;headingLevel?:number|null}>
 numbering?: ReadonlyMap<string,{levels:Record<number,{numFmt?:string;picBulletId?:unknown}>}>
}
export interface NewRichParagraphSpec extends GeneratedBlock {runs:NewRichParagraphRun[];caretFormat?:NewRichParagraphRun}
export interface NewRichParagraphOperation {[key:string]:unknown;kind:'insertRichParagraph';blockId:string;expectedObjectSha256:string;position:'before'|'after';paragraph:NewRichParagraphSpec}
export interface NewRichParagraphAnchor {blockId:string;expectedObjectSha256:string;type:string;editable:boolean;insertParagraphAdjacentEditable?:boolean;protectedDocument?:boolean;hidden?:boolean;sdtShell?:unknown}
function fail():never{throw new Error('新增富文本段落字段、格式或来源身份无效')}
const record=(v:unknown):Record<string,unknown>=>{if(!v||typeof v!=='object'||Array.isArray(v))fail();return v as Record<string,unknown>}
const keys=(v:Record<string,unknown>,allowed:readonly string[])=>{if(Object.keys(v).some(k=>!allowed.includes(k)))fail()}
const text=(v:unknown,max=20000)=>{if(typeof v!=='string'||v.length>max||/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff]/u.test(v)||!v.isWellFormed())fail();return v as string}
const integer=(v:unknown,min:number,max:number)=>{if(typeof v!=='number'||!Number.isSafeInteger(v)||v<min||v>max)fail();return v as number}
const name=(v:unknown)=>{const s=text(v,255);if(!s.trim()||/[<>]/.test(s))fail();return s}
export const NEW_RICH_RUN_KEYS=['text','bold','italic','underline','strike','color','sizeHalfPoints','font','fontAscii','eastAsiaFont','fontCs','rtl','charSpacingTwips','kernHalfPoints','caps','vanishOwn','charScalePct','highlight','dstrike','positionHalfPoints','vertAlign','styleId','sourceFormat'] as const
export const NEW_RICH_PARA_KEYS=['align','lineSpacing','lineRule','lineRawTwips','indentLeft','indentRight','indentFirstLine','spaceBefore','spaceAfter','spaceBeforeAuto','spaceAfterAuto','pageBreakBefore','keepNext','keepLines','suppressLineNumbers','widowControl','contextualSpacing','bidi','shadingFill','snapToGrid'] as const
const flags=['bold','italic','underline','strike','rtl','vanishOwn','dstrike','spaceBeforeAuto','spaceAfterAuto','pageBreakBefore','keepNext','keepLines','suppressLineNumbers','widowControl','contextualSpacing','bidi','snapToGrid']
const highlights=['black','blue','cyan','green','magenta','red','yellow','white','darkBlue','darkCyan','darkGreen','darkMagenta','darkRed','darkYellow','darkGray','lightGray','none']
function properties(raw:unknown,allowed:readonly string[],bindings:NewRichParagraphBindings,run=false){
 const v=record(raw);keys(v,allowed);const out:Record<string,unknown>={}
 for(const [k,x] of Object.entries(v)){
  if(k==='text'){out[k]=text(x);continue}
  if(k==='sourceFormat'){out[k]=newRichSourceFormat(x,bindings);continue}
  if(flags.includes(k)){if(typeof x!=='boolean')fail();out[k]=x}
  else if(['font','fontAscii','eastAsiaFont','fontCs'].includes(k))out[k]=name(x)
  else if(k==='styleId'){const id=name(x);if(bindings.styles?.get(id)?.type!==(run?'character':'paragraph'))fail();out[k]=id}
  else if(['color','shadingFill'].includes(k)){if(typeof x!=='string'||!/^(?:[a-f\d]{6}|auto)$/i.test(x))fail();out[k]=x}
  else if(k==='align'){if(!['left','center','right','justify'].includes(x as string))fail();out[k]=x}
  else if(k==='lineRule'){if(!['auto','exact','atLeast'].includes(x as string))fail();out[k]=x}
  else if(k==='caps'){if(!['all','small','none'].includes(x as string))fail();out[k]=x}
  else if(k==='vertAlign'){if(!['superscript','subscript'].includes(x as string))fail();out[k]=x}
  else if(k==='highlight'){if(!highlights.includes(x as string))fail();out[k]=x}
  else if(k==='lineSpacing'){if(typeof x!=='number'||!Number.isFinite(x)||x<=0||x>100)fail();out[k]=x}
  else {const [min,max]=k==='sizeHalfPoints'?[2,3276]:k==='charScalePct'?[1,600]:k==='kernHalfPoints'?[0,3276]:['spaceBefore','spaceAfter','lineRawTwips'].includes(k)?[0,31680]:[-31680,31680];out[k]=integer(x,min,max)}
 }
 if(!run){
  if(['exact','atLeast'].includes(out.lineRule as string)){if(!(Number(out.lineRawTwips)>0)||out.lineSpacing!==undefined)fail()}
  else if(out.lineRawTwips!==undefined){
   const raw=Number(out.lineRawTwips),exact=raw/240,rounded=Math.round(exact*100)/100,multiple=out.lineSpacing
   // Source parsing retains raw twips alongside either an exact style-derived
   // multiplier or a paragraph multiplier rounded to two decimal places.
   if(raw<=0||exact>100||multiple!==undefined&&Math.abs(Number(multiple)-exact)>1e-9&&Math.abs(Number(multiple)-rounded)>1e-9)fail()
   if(multiple===undefined)out.lineSpacing=exact
  }
 }

 return out
}
/** Resolve metadata only from an identified original run. The accepted raw rPr
 * must be exactly redundant with supported typed source properties; unknown
 * elements, theme references, relationships and unmodeled effects fail closed. */
function newRichSourceFormat(value:unknown,bindings:NewRichParagraphBindings):NewRichSourceFormat{
 const ref=record(value);keys(ref,['blockId','expectedObjectSha256','from'])
 const blockId=name(ref.blockId),expectedObjectSha256=name(ref.expectedObjectSha256),from=integer(ref.from,0,Number.MAX_SAFE_INTEGER)
 const source=bindings.sourceRuns?.get(blockId);if(!source||source.expectedObjectSha256!==expectedObjectSha256)fail()
 let offset=0,found:Run|undefined
 for(const run of source.runs){const end=offset+run.text.length;if(from===offset){const at=from-offset;if(at>0&&/[\uD800-\uDBFF]/.test(run.text[at-1])&&/[\uDC00-\uDFFF]/.test(run.text[at]??''))fail();found=run;break}offset=end}
 if(!found||typeof found.rawRPr!=='string'||found.rawRPr.length>10000)fail()
 const supported=Object.fromEntries(Object.entries(found).filter(([key,v])=>(NEW_RICH_RUN_KEYS as readonly string[]).includes(key)&&key!=='sourceFormat'&&v!=null))
 const safe=properties({...supported,text:''},NEW_RICH_RUN_KEYS,bindings,true) as unknown as Run
 let modeled=mergeRPrModel('',safe,false)
 // The source builder emits bCs/iCs twins for ordinary Latin b/i; their
 // absence in original non-CS rPr is semantically redundant, not unknown XML.
 for(const twin of ['bCs','iCs'])if(!new RegExp('<w:'+twin+'[\\s/>]').test(found.rawRPr))modeled=modeled.replace(new RegExp('<w:'+twin+'(?: [^>]*)?/>' ,'g'),'')
 if(modeled!==found.rawRPr)fail()
 return {blockId,expectedObjectSha256,from}
}
export function resolveNewRichParagraphSourceRun(value:unknown,bindings:NewRichParagraphBindings):Run{
 const ref=newRichSourceFormat(value,bindings),source=bindings.sourceRuns!.get(ref.blockId)!;let offset=0
 for(const run of source.runs){const end=offset+run.text.length;if(ref.from===offset)return run;offset=end}
 return fail()
}
export function normalizeNewRichParagraph(value:unknown,bindings:NewRichParagraphBindings={}):NewRichParagraphSpec{
 const v=record(value);keys(v,['type','level','outlineOnly','styleId','list','format','runs','caretFormat'])
 if(!['paragraph','heading','listItem'].includes(v.type as string)||!Array.isArray(v.runs)||v.runs.length>1000)fail()
 const out:NewRichParagraphSpec={type:v.type as GeneratedBlock['type'],runs:v.runs.map(r=>{const p=properties(r,NEW_RICH_RUN_KEYS,bindings,true);if(!('text'in p))fail();return p as unknown as NewRichParagraphRun})}
 if(v.caretFormat!==undefined){const pending=properties(v.caretFormat,NEW_RICH_RUN_KEYS,bindings,true);if(pending.text!=='')fail();out.caretFormat=pending as unknown as NewRichParagraphRun}
 if(out.runs.reduce((n,r)=>n+r.text.length,0)>20000)fail()
 if(v.format!==undefined)out.format=properties(v.format,NEW_RICH_PARA_KEYS,bindings) as ParaFormat
 if(v.styleId!==undefined){const id=name(v.styleId);if(bindings.styles?.get(id)?.type!=='paragraph')fail();out.styleId=id}
 if(v.type==='heading'){out.level=integer(v.level,1,9);if(v.outlineOnly!==undefined&&typeof v.outlineOnly!=='boolean')fail();if(v.outlineOnly!==undefined)out.outlineOnly=v.outlineOnly as boolean;if(!out.styleId&&out.outlineOnly!==true)fail();const bound=out.styleId&&bindings.styles?.get(out.styleId);if(bound&&bound.headingLevel!==out.level)fail()}
 else if(v.level!==undefined||v.outlineOnly!==undefined)fail()
 if(v.type==='listItem'){
  const list=record(v.list);keys(list,['kind','numId','ilvl']);if(!['ordered','bullet'].includes(list.kind as string))fail();const numId=name(list.numId),ilvl=integer(list.ilvl,0,8),level=bindings.numbering?.get(numId)?.levels[ilvl]
  if(!level||level.picBulletId!=null||(level.numFmt==='bullet'?'bullet':'ordered')!==list.kind)fail()
  out.list={kind:list.kind as 'ordered'|'bullet',numId,ilvl}
 }else if(v.list!==undefined)fail()
 return out
}
export function validateNewRichParagraphOperation(value:unknown,anchor:NewRichParagraphAnchor,bindings:NewRichParagraphBindings={}):NewRichParagraphOperation{
 const v=record(value);keys(v,['kind','blockId','expectedObjectSha256','position','paragraph'])
 if(v.kind!=='insertRichParagraph'||v.blockId!==anchor.blockId||v.expectedObjectSha256!==anchor.expectedObjectSha256||!anchor.blockId||!anchor.expectedObjectSha256||!(anchor.type==='table'?anchor.insertParagraphAdjacentEditable===true:anchor.editable)||anchor.protectedDocument===true||anchor.hidden||anchor.sdtShell||!['paragraph','heading','listItem','table'].includes(anchor.type)||!['before','after'].includes(v.position as string))fail()
 return {kind:'insertRichParagraph',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,position:v.position as 'before'|'after',paragraph:normalizeNewRichParagraph(v.paragraph,bindings)}
}
export function buildNewRichParagraph(value:unknown,bindings:NewRichParagraphBindings={}):GeneratedBlock{
 const {caretFormat:pending,...block}=normalizeNewRichParagraph(value,bindings)
 const clean=(run:NewRichParagraphRun):Run=>{const {sourceFormat,...typed}=run;return typed}
 const caretFormat=pending?clean(pending):undefined
 block.runs=block.runs.map(clean)
 // The source generator writes auto spacing from lineSpacing, not raw twips.
 // Use the validated exact ratio here so a rounded display multiplier (e.g.
 // 241 twips shown as 1.00) does not shift the saved line height by a twip.
 if(block.format?.lineRawTwips!==undefined&&!['exact','atLeast'].includes(block.format.lineRule??'auto'))block.format={...block.format,lineSpacing:block.format.lineRawTwips/240}
 if(!block.runs.length&&caretFormat){
  // Source writer omits empty text runs. Put the validated pending formatting
  // on the paragraph mark so saving an empty line does not erase its font.
  const xml=generateParagraphXml(block,{headingStyleIds:new Map(),allocateHyperlinkRel:()=>fail()}),ppr=xml.match(/<w:pPr>[\s\S]*?<\/w:pPr>/)?.[0]??'<w:pPr></w:pPr>'
  return {...block,runs:[caretFormat],rawPPr:ppr.replace('</w:pPr>',mergeRPrModel('',caretFormat,false)+'</w:pPr>')}
 }
 return block
}
