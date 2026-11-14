/** 外来粘贴的结构化内容协议；不携带 OOXML、关系或来源对象身份。 */
export interface PasteNode {type:string;attrs?:Record<string,unknown>;text?:string;marks?:{type:string;attrs?:Record<string,unknown>}[];content?:PasteNode[]}
export interface PasteBoundary {docxIndex:number;offset:number}
export interface RichPasteOperation {kind:'pasteRichContent';sourceSha256:string;start:PasteBoundary;end:PasteBoundary;blocks:PasteNode[]}
export const PASTE_PARA_ATTRS=['align','indentLeft','indentRight','indentFirstLine','spaceBefore','spaceAfter','lineSpacing','lineRule','lineRawTwips','shadingFill','bidi']
export const PASTE_RUN_ATTRS=['font','fontAscii','csFont','sizeHalfPoints','color','vertAlign','highlight','charSpacingTwips','charScalePct','caps']
const para=['docParagraph','docHeading','docListItem']
export const pasteParagraph=(n:PasteNode)=>para.includes(n.type)
const attrs:Record<string,string[]>={docParagraph:PASTE_PARA_ATTRS,docHeading:[...PASTE_PARA_ATTRS,'level'],docListItem:[...PASTE_PARA_ATTRS,'kind','ilvl'],docTable:['widthPct','widthTwips'],docTableRow:[],docTableCell:['colspan','rowspan','fill','vAlign'],docTableHeader:['colspan','rowspan','fill','vAlign'],docInlineImage:['dataUrl','widthPx','heightPx','alt'],hardBreak:[]}
const fail=():never=>{throw new Error('粘贴内容结构或格式不受支持，请使用仅保留文本')}
const validText=(v:unknown,max=200000)=>typeof v==='string'&&v.length<=max&&!/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(v)
function validateAttrs(value:Record<string,unknown>,allowed:string[]){
 for(const [k,v] of Object.entries(value)){
  if(!allowed.includes(k)||v===null||v===undefined)fail()
  if(['font','fontAscii','csFont','alt'].includes(k)){if(!validText(v,1000)||/[<>]/u.test(v as string))fail()}
  else if(['color','shadingFill','fill'].includes(k)){if(typeof v!=='string'||! /^(?:[\da-f]{6}|auto)$/i.test(v))fail()}
  else if(k==='align'){if(!['left','center','right','justify'].includes(v as string))fail()}
  else if(k==='kind'){if(!['bullet','ordered'].includes(v as string))fail()}
  else if(k==='lineRule'){if(!['auto','exact','atLeast'].includes(v as string))fail()}
  else if(k==='bidi'){if(typeof v!=='boolean')fail()}
  else if(k==='vertAlign'){if(!['superscript','subscript'].includes(v as string))fail()}
  else if(k==='vAlign'){if(!['top','center','bottom'].includes(v as string))fail()}
  else if(k==='caps'){if(!['all','small','none'].includes(v as string))fail()}
  else if(k==='highlight'){if(typeof v!=='string'||! /^[a-zA-Z]{1,30}$/.test(v))fail()}
  else if(k==='dataUrl'){if(typeof v!=='string'||v.length>12000000||!/^data:image\/(?:png|jpeg);base64,[A-Za-z0-9+/]+={0,2}$/.test(v))fail()}
  else {if(typeof v!=='number')return fail();if(!Number.isFinite(v)||v< -31680||v>31680)fail();if(['colspan','rowspan'].includes(k)&&(!Number.isInteger(v)||v<1||v>100))fail();if(k==='ilvl'&&(!Number.isInteger(v)||v<0||v>8))fail();if(k==='level'&&(!Number.isInteger(v)||v<1||v>9))fail();if(['widthPx','heightPx'].includes(k)&&(v<=0||v>12000))fail()}
 }
}
/** strip=true 仅用于 schema 解析结果；HTTP/草稿必须严格检查，不能默默丢弃恶意字段。 */
export function pasteContent(value:unknown,strip=false):PasteNode[]{
 let count=0,chars=0
 const read=(raw:unknown,depth:number):PasteNode=>{
  if(++count>20000||depth>20||!raw||typeof raw!=='object'||Array.isArray(raw))fail()
  const n=raw as PasteNode;if(!strip&&Object.keys(n).some(k=>!['type','attrs','text','marks','content'].includes(k)))fail()
  if(n.type!=='text'&&!attrs[n.type])fail()
  const result:PasteNode={type:n.type}
  if(n.type==='text'){if(n.attrs||n.content||!validText(n.text)||!n.text)fail();chars+=n.text!.length;result.text=n.text}
  if(n.attrs){const a=Object.fromEntries(Object.entries(n.attrs).filter(([k,v])=>!strip||attrs[n.type]?.includes(k)&&v!=null));validateAttrs(a,attrs[n.type]??[]);if(Object.keys(a).length)result.attrs=a}
  if(n.marks&&!Array.isArray(n.marks))fail();if(n.content&&!Array.isArray(n.content))fail();if(n.attrs&&(typeof n.attrs!=='object'||Array.isArray(n.attrs)))fail();if(n.marks?.length){if(!['text','docInlineImage'].includes(n.type))fail();result.marks=n.marks.map(m=>{if(!m||typeof m!=='object'||Object.keys(m).some(k=>!['type','attrs'].includes(k))||!['bold','italic','underline','strike','docTextStyle','link'].includes(m.type))fail();const a=Object.fromEntries(Object.entries(m.attrs??{}).filter(([k,v])=>!strip||(m.type==='docTextStyle'?PASTE_RUN_ATTRS.includes(k):m.type==='link'?['href','title'].includes(k):false)&&v!=null));if(m.type==='link'){if(Object.keys(a).some(k=>!['href','title'].includes(k))||typeof a.href!=='string'||! /^(?:https?:|mailto:|#)/i.test(a.href)||!validText(a.href,4000)||a.title!==undefined&&!validText(a.title,1000))fail()}else validateAttrs(a,m.type==='docTextStyle'?PASTE_RUN_ATTRS:[]);return{type:m.type,...(Object.keys(a).length?{attrs:a}:{})}})}
  if(n.content)result.content=n.content.map(c=>read(c,depth+1))
  const children=result.content??[]
  if(pasteParagraph(result)&&children.some(c=>!['text','hardBreak','docInlineImage'].includes(c.type))||n.type==='docTable'&&(!children.length||children.some(c=>c.type!=='docTableRow'))||n.type==='docTableRow'&&(!children.length||children.some(c=>!['docTableCell','docTableHeader'].includes(c.type)))||['docTableCell','docTableHeader'].includes(n.type)&&(!children.length||children.some(c=>!pasteParagraph(c)&&c.type!=='docTable'))||['text','hardBreak','docInlineImage'].includes(n.type)&&children.length)fail()
  return result
 }
 if(!Array.isArray(value)||!value.length||value.length>400)return fail()
 const result=value.map(n=>read(n,0));if(chars>200000||result.some(n=>!pasteParagraph(n)&&n.type!=='docTable'))fail();return result
}
export function richPasteOperation(value:unknown,sha:string):RichPasteOperation{
 const op=value as RichPasteOperation
 if(!op||typeof op!=='object'||Object.keys(op).sort().join('|')!=='blocks|end|kind|sourceSha256|start'||op.kind!=='pasteRichContent'||op.sourceSha256!==sha)fail()
 for(const b of [op.start,op.end])if(!b||Object.keys(b).sort().join('|')!=='docxIndex|offset'||!Number.isSafeInteger(b.docxIndex)||b.docxIndex<0||!Number.isSafeInteger(b.offset)||b.offset<0)fail()
 if(op.start.docxIndex>op.end.docxIndex||op.start.docxIndex===op.end.docxIndex&&op.start.offset>op.end.offset)fail()
 return {...op,blocks:pasteContent(op.blocks)}
}

/** 只有可完整重建的普通正文段落可作为替换范围；未知内联容器拒绝重建。 */
export function pasteTargetSupported(b:{type:string;hidden?:boolean;sdtShell?:unknown;originalXml?:string|null}):boolean{
 if(!['paragraph','heading','listItem'].includes(b.type)||b.hidden||b.sdtShell||!b.originalXml||/<(?:w:(?:hyperlink|fldSimple|instrText|fldChar|bookmarkStart|bookmarkEnd|commentRangeStart|commentRangeEnd|ins|del|sdt|drawing|pict|object|sectPr)|m:)/u.test(b.originalXml))return false
 const inline=b.originalXml.replace(/<w:(pPr|rPr)\b[^>]*>[\s\S]*?<\/w:\1>/g,'').replace(/<w:(?:pPr|rPr)\b[^>]*\/>/g,'')
 return [...inline.matchAll(/<\/?([\w:.-]+)\b/g)].every(m=>['w:p','w:r','w:t','w:tab','w:br','w:cr'].includes(m[1]))
}
