/** Fixed GenOffice f8c17004 App.tsx insertField + ribbon-insert-tab field menu. */
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {parseDocx} from '../packages/docx-engine/src/parse'
import {generateParagraphXml} from '../packages/docx-engine/src/generate'
import {docxTocSource} from './docx-toc-core'
import {insertDocxInlineField,readDocxInlineFields,updateDocxInlineFields,editDocxInlineField} from './docx-field-core'
import {assertZipIdentity} from './docx-comment-source'
export const docxInsertionHash=(v:string|Uint8Array)=>createHash('sha256').update(v).digest('hex')
export function readDocxInsertionAnchor(op:any,keys:string[],family:string){
 if(!op||typeof op!=='object'||!/^[a-f0-9]{64}$/.test(op.blockId??'')||!/^[a-f0-9]{64}$/.test(op.expectedObjectSha256??'')||!['before','after'].includes(op.position)||Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','position',...keys].includes(k)))throw new Error('docx_'+family+'_operation')
}
export async function docxInsertionAnchor(bytes:Uint8Array,op:any,family:string,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 assertZipIdentity(bytes);parsed??=await parseDocx(bytes)
 const source=docxTocSource(parsed),hash=docxInsertionHash(bytes)
 const block=parsed.blocks.find(b=>b.docxIndex!=null&&docxInsertionHash(hash+':block:'+b.docxIndex)===op.blockId)
 if(!block?.originalXml||block.docxIndex==null||docxInsertionHash(block.originalXml)!==op.expectedObjectSha256)throw new Error('docx_'+family+'_anchor')
 const p=source.paragraphs.get(block.docxIndex)
 if(!source.safe||!p||!['paragraph','heading','listItem'].includes(block.type)||(op.position==='after'&&/<w:sectPr\b/.test(block.originalXml)))throw new Error('docx_'+family+'_anchor_unsupported')
 return {parsed,source,at:op.position==='before'?p.start:p.end}
}
export const validDocxInsertText=(v:unknown,max=1000):v is string=>typeof v==='string'&&v.length<=max&&!/[\x00-\x1f\x7f-\x9f\uFFFE\uFFFF]/u.test(v)&&![...v].some(c=>{const n=c.codePointAt(0)!;return n>=0xd800&&n<=0xdfff})
export const isDocxFieldOperation=(v:{kind?:unknown})=>v.kind==='insertField'||v.kind==='updateFields'||v.kind==='editField'
export function readDocxFieldOperation(v:unknown){
 const op=v as any;readDocxInsertionAnchor(op,['instruction','result','fieldOffset'],'field')
 if(!isDocxFieldOperation(op)||!['DATE','TIME','PAGE','NUMPAGES','FILENAME'].includes(op.instruction)||!validDocxInsertText(op.result)||(op.fieldOffset!==undefined&&(!Number.isSafeInteger(op.fieldOffset)||op.fieldOffset<0)))throw new Error('docx_field_operation')
 return op as {kind:'insertField';blockId:string;expectedObjectSha256:string;position:'before'|'after';instruction:string;result:string;fieldOffset?:number}
}
export async function patchDocxField(bytes:Uint8Array,value:unknown,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 if((value as {kind?:unknown})?.kind==='editField')return patchDocxFieldEdit(bytes,value,parsed)
 if((value as {kind?:unknown})?.kind==='updateFields')return patchDocxFieldUpdates(bytes,value,parsed)
 const op=readDocxFieldOperation(value),{source,at}=await docxInsertionAnchor(bytes,op,'field',parsed)
 // Reuse actual generic-field writer, including begin/separate/end and escaped cache.
 const fragment=generateParagraphXml({type:'paragraph',runs:[{text:op.result||' ',instrField:op.instruction}]},{headingStyleIds:new Map(),allocateHyperlinkRel:()=>{throw new Error('docx_field_relationship')}})
 const zip=await JSZip.loadAsync(bytes);let xml=source.xml.slice(0,at)+fragment+source.xml.slice(at);if(op.fieldOffset!==undefined){const hash=docxInsertionHash(bytes),doc=parsed??await parseDocx(bytes),b=doc.blocks.find(b=>b.docxIndex!=null&&docxInsertionHash(hash+':block:'+b.docxIndex)===op.blockId)!,range=source.paragraphs.get(b.docxIndex!)!;const replacement=insertDocxInlineField(b.originalXml!,op.fieldOffset,fragment.slice(5,-6));xml=source.xml.slice(0,range.start)+replacement+source.xml.slice(range.end)}zip.file('word/document.xml',xml,{createFolders:false})
 return zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
}

export type DocxFieldUpdate={blockId:string;expectedObjectSha256:string;fields:{fieldIndex:number;instruction:string;result:string}[]}
export function readDocxFieldUpdates(v:unknown){const op=v as {kind?:unknown;updates?:DocxFieldUpdate[]};if(!op||op.kind!=='updateFields'||Object.keys(op).some(k=>!['kind','updates'].includes(k))||!Array.isArray(op.updates)||!op.updates.length||op.updates.length>20000||!op.updates.every(u=>u&&Object.keys(u).every(k=>['blockId','expectedObjectSha256','fields'].includes(k))&&/^[a-f0-9]{64}$/.test(u.blockId)&&/^[a-f0-9]{64}$/.test(u.expectedObjectSha256)&&Array.isArray(u.fields)&&u.fields.length>0&&u.fields.length<=1000&&u.fields.every(f=>f&&Object.keys(f).every(k=>['fieldIndex','instruction','result'].includes(k))&&Number.isSafeInteger(f.fieldIndex)&&f.fieldIndex>=0&&validDocxInsertText(f.instruction)&&validDocxInsertText(f.result))))throw new Error('docx_field_update_operation');return {kind:'updateFields' as const,updates:op.updates}}
export async function inspectDocxFields(bytes:Uint8Array,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 parsed??=await parseDocx(bytes);const source=docxTocSource(parsed),hash=docxInsertionHash(bytes),seen=new Set<number>(),result=[]
 if(!source.safe)return []
 for(const b of parsed.blocks){if(b.docxIndex==null||!b.originalXml||!source.paragraphs.has(b.docxIndex)||seen.has(b.docxIndex))continue;seen.add(b.docxIndex)
 const fields=readDocxInlineFields(b.originalXml);if(fields.length)result.push({docxIndex:b.docxIndex,blockId:docxInsertionHash(hash+':block:'+b.docxIndex),expectedObjectSha256:docxInsertionHash(b.originalXml),fields:fields.map(({fieldIndex,instruction,result})=>({fieldIndex,instruction,result}))})}
 return result
}
async function patchDocxFieldUpdates(bytes:Uint8Array,value:unknown,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 const op=readDocxFieldUpdates(value);assertZipIdentity(bytes);parsed??=await parseDocx(bytes)
 const source=docxTocSource(parsed);if(!source.safe)throw new Error('docx_field_update_source_unsupported')
 const targets=await inspectDocxFields(bytes,parsed),seen=new Set<string>(),changes=[]
 for(const u of op.updates){if(seen.has(u.blockId))throw new Error('docx_field_update_duplicate');seen.add(u.blockId);const t=targets.find(t=>t.blockId===u.blockId&&t.expectedObjectSha256===u.expectedObjectSha256),b=t&&parsed.blocks.find(b=>b.docxIndex===t.docxIndex),range=t&&source.paragraphs.get(t.docxIndex);if(!t||!b?.originalXml||!range)throw new Error('docx_field_update_anchor');changes.push({...range,xml:updateDocxInlineFields(b.originalXml,u.fields)})}
 let xml=source.xml;for(const c of changes.sort((a,b)=>b.start-a.start))xml=xml.slice(0,c.start)+c.xml+xml.slice(c.end)
 const zip=await JSZip.loadAsync(bytes);zip.file('word/document.xml',xml,{createFolders:false});return zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
}

export async function patchDocxFieldEdit(bytes:Uint8Array,value:unknown,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 const op=value as any
 if(!op||op.kind!=='editField'||Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','fieldIndex','instruction','result','newInstruction','newResult'].includes(k))||!Number.isSafeInteger(op.fieldIndex)||op.fieldIndex<0||!['instruction','result','newInstruction','newResult'].every(k=>validDocxInsertText(op[k])))throw new Error('docx_field_edit_operation')
 assertZipIdentity(bytes);parsed??=await parseDocx(bytes)
 const source=docxTocSource(parsed),targets=await inspectDocxFields(bytes,parsed),target=targets.find(t=>t.blockId===op.blockId&&t.expectedObjectSha256===op.expectedObjectSha256),block=target&&parsed.blocks.find(b=>b.docxIndex===target.docxIndex),range=target&&source.paragraphs.get(target.docxIndex)
 if(!source.safe||!block?.originalXml||!range)throw new Error('docx_field_edit_anchor')
 const replacement=editDocxInlineField(block.originalXml,op),zip=await JSZip.loadAsync(bytes)
 zip.file('word/document.xml',source.xml.slice(0,range.start)+replacement+source.xml.slice(range.end),{createFolders:false})
 return zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
}
