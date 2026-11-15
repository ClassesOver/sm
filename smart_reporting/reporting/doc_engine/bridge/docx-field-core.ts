import {splitXmlChildren} from '../packages/docx-engine/src/generate'
import {decodeXmlText} from '../packages/docx-engine/src/zotero-doc-props'
import {escapeXmlText} from '../packages/docx-engine/src/xml-utils'
/** Raw paragraph surgery: inherited run attributes/rPr stay exact; existing fields are opaque. */
export function insertDocxInlineField(xml:string,offset:number,fragment:string){
 const open=/^<w:p\b[^>]*>/.exec(xml)?.[0];if(!open||!xml.endsWith('</w:p>')||!Number.isSafeInteger(offset)||offset<0)throw new Error('docx_field_offset')
 const inner=xml.slice(open.length,-6),children=splitXmlChildren(inner);let at=open.length,total=0,depth=0,candidate:number|undefined
 for(const child of children){const raw=child.xml,start=xml.indexOf(raw,at);if(start<0)throw new Error('docx_field_offset');at=start+raw.length
 if(child.name==='w:pPr')continue
 if(child.name!=='w:r')throw new Error('docx_field_inline_unsupported')
 const begin=/<w:fldChar\b[^>]*w:fldCharType=["']begin["']/.test(raw),end=/<w:fldChar\b[^>]*w:fldCharType=["']end["']/.test(raw)
 if(depth===0&&total===offset&&candidate===undefined)candidate=start
 if(begin)depth++
 if(/<w:(?:tab|br|cr|drawing|pict|object|sym|footnoteReference|endnoteReference)\b/.test(raw))throw new Error('docx_field_inline_unsupported')
 const texts=[...raw.matchAll(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>/g)],text=texts.map(m=>decodeXmlText(m[1]!)).join(''),next=total+text.length
 if(offset>total&&offset<next){
 if(depth||texts.length!==1)throw new Error('docx_field_offset_inside_field')
 const run=/^(<w:r\b[^>]*>)(<w:rPr\b[^>]*>[\s\S]*?<\/w:rPr>|<w:rPr\b[^>]*\/>|)(<w:t\b[^>]*>)[\s\S]*?<\/w:t><\/w:r>$/.exec(raw)
 if(!run)throw new Error('docx_field_inline_unsupported')
 const cut=offset-total;if(/[\uD800-\uDBFF]/.test(text[cut-1]!)&&/[\uDC00-\uDFFF]/.test(text[cut]!))throw new Error('docx_field_offset_surrogate')
 const part=(s:string)=>run[1]+run[2]+'<w:t xml:space="preserve">'+escapeXmlText(s)+'</w:t></w:r>'
 return xml.slice(0,start)+part(text.slice(0,cut))+fragment+part(text.slice(cut))+xml.slice(at)
 }
 total=next;if(end){depth--;if(depth<0)throw new Error('docx_field_inline_unsupported')}
 }
 if(depth||offset>total)throw new Error('docx_field_offset')
 if(candidate===undefined&&offset===total)candidate=xml.length-6
 if(candidate===undefined)throw new Error('docx_field_offset_inside_field')
 return xml.slice(0,candidate)+fragment+xml.slice(candidate)
}
export type DocxInlineField={fieldIndex:number;instruction:string;result:string;spans:{start:number;end:number;text:string}[];instructionSpans:{start:number;end:number;text:string}[]}
export function readDocxInlineFields(xml:string):DocxInlineField[]{
 if(/<!--|<!\[CDATA|<\?|<w:(?:del|ins|moveFrom|moveTo|hyperlink|sdt|fldSimple|drawing|pict|object|txbxContent)\b|w:fldLock\s*=/.test(xml))return []
 const opening=/^<w:p\b[^>]*>/.exec(xml)?.[0];if(!opening||!xml.endsWith('</w:p>')||splitXmlChildren(xml.slice(opening.length,-6)).some(c=>!['w:r','w:pPr'].includes(c.name)))return []
 const fields:DocxInlineField[]=[],stack:{field:DocxInlineField;separated:boolean;nested:boolean}[]=[];let index=0
 const token=/<w:fldChar\b[^>]*\/>|<w:(instrText|t)\b[^>]*>([\s\S]*?)<\/w:\1>/g
 for(const m of xml.matchAll(token)){
 if(m[0].startsWith('<w:fldChar')){const kind=/w:fldCharType=["']([^"']+)["']/.exec(m[0])?.[1]
 if(kind==='begin'){if(stack.length)stack.forEach(s=>s.nested=true);stack.push({field:{fieldIndex:index++,instruction:'',result:'',spans:[],instructionSpans:[]},separated:false,nested:stack.length>0})}
 else if(kind==='separate'){const top=stack.at(-1);if(top){if(top.separated)top.nested=true;top.separated=true}}
 else if(kind==='end'){const top=stack.pop();if(top&&!top.nested&&top.separated&&/^(DATE|TIME|PAGE|NUMPAGES|FILENAME)(?:\s|$)/i.test(top.field.instruction.trim()))fields.push(top.field)}
 continue}
 const top=stack.at(-1);if(!top)continue;const value=decodeXmlText(m[2]??'')
 if(m[1]==='instrText'&&!top.separated){top.field.instruction+=value;top.field.instructionSpans.push({start:m.index!+m[0].indexOf('>')+1,end:m.index!+m[0].lastIndexOf('</'),text:value})}
 if(m[1]==='t'&&top.separated){const start=m.index!+m[0].indexOf('>')+1,end=m.index!+m[0].lastIndexOf('</');top.field.result+=value;top.field.spans.push({start,end,text:value})}
 }
 return fields.filter(f=>f.spans.length)
}
export function updateDocxInlineFields(xml:string,updates:{fieldIndex:number;instruction:string;result:string}[]){
 const fields=readDocxInlineFields(xml),changes:{start:number;end:number;text:string}[]=[],seen=new Set<number>()
 for(const u of updates){const field=fields.find(f=>f.fieldIndex===u.fieldIndex&&f.instruction===u.instruction);if(!field||seen.has(u.fieldIndex))throw new Error('docx_field_update_anchor');seen.add(u.fieldIndex);field.spans.forEach((s,i)=>changes.push({...s,text:i===0?escapeXmlText(u.result||' '):''}))}
 for(const c of changes.sort((a,b)=>b.start-a.start))xml=xml.slice(0,c.start)+c.text+xml.slice(c.end)
 return xml
}

/** Only literal menu fields and the nonsemantic MERGEFORMAT switch are editable. */
export const supportedDocxFieldInstruction=(v:unknown):v is string=>typeof v==='string'&&v.length<=1000&&/^\s*(?:DATE|TIME|PAGE|NUMPAGES|FILENAME)(?:\s+\\\*\s+MERGEFORMAT)?\s*$/i.test(v)
export function editDocxInlineField(xml:string,op:{fieldIndex:number;instruction:string;result:string;newInstruction:string;newResult:string}){
 if(!supportedDocxFieldInstruction(op.instruction)||!supportedDocxFieldInstruction(op.newInstruction))throw new Error('docx_field_edit_instruction')
 const field=readDocxInlineFields(xml).find(f=>f.fieldIndex===op.fieldIndex&&f.instruction===op.instruction&&f.result===op.result)
 if(!field||!field.instructionSpans.length)throw new Error('docx_field_edit_anchor')
 const value=op.newResult||' ';let at=0
 const resultChanges=field.spans.map((s,i)=>{let take=i===field.spans.length-1?value.length-at:Math.min(s.text.length,value.length-at);if(take>0&&/[\uD800-\uDBFF]/.test(value[at+take-1]!)&&/[\uDC00-\uDFFF]/.test(value[at+take]??''))take--;const text=escapeXmlText(value.slice(at,at+take));at+=take;return {...s,text}})
 const changes=[...field.instructionSpans.map((s,i)=>({...s,text:i===0?escapeXmlText(op.newInstruction):''})),...resultChanges]
 for(const c of changes.sort((a,b)=>b.start-a.start))xml=xml.slice(0,c.start)+c.text+xml.slice(c.end)
 return xml
}
