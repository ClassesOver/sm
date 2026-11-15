import type {Schema} from '@tiptap/pm/model'
import type {DocxPmNode} from './docx-operations'
import type {NativeOperation} from './native-draft'
import type {DocxFieldTarget} from './docx-chart-fields'
export const supportedDocxFieldInstruction=(v:unknown):v is string=>typeof v==='string'&&v.length<=1000&&/^\s*(?:DATE|TIME|PAGE|NUMPAGES|FILENAME)(?:\s+\\\*\s+MERGEFORMAT)?\s*$/i.test(v)
export function docxFieldGroups(node:DocxPmNode){
 const groups:{instruction:string;nodes:DocxPmNode[]}[]=[];let previous=false
 for(const n of node.content??[]){const m=n.type==='text'&&n.marks?.find(m=>m.type==='instrField');if(!m){previous=false;continue}const instruction=String(m.attrs?.instr??'');if(previous&&groups.at(-1)?.instruction===instruction)groups.at(-1)!.nodes.push(n);else groups.push({instruction,nodes:[n]});previous=true}
 return groups
}
export function planDocxFieldEdit(doc:DocxPmNode,value:unknown,targets:readonly DocxFieldTarget[],schema:Schema){
 const op=value as NativeOperation
 if(!op||op.kind!=='editField'||Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','fieldIndex','instruction','result','newInstruction','newResult'].includes(k))||!Number.isSafeInteger(op.fieldIndex)||!supportedDocxFieldInstruction(op.instruction)||!supportedDocxFieldInstruction(op.newInstruction)||typeof op.newResult!=='string'||op.newResult.length>1000||/[\x00-\x1f\x7f-\x9f\uFFFE\uFFFF]/u.test(op.newResult)||[...op.newResult].some(c=>{const n=c.codePointAt(0)!;return n>=0xd800&&n<=0xdfff}))throw new Error('域编辑参数无效')
 const target=targets.find(t=>t.blockId===op.blockId&&t.expectedObjectSha256===op.expectedObjectSha256),field=target?.fields.find(f=>f.fieldIndex===op.fieldIndex&&f.instruction===op.instruction&&f.result===op.result),index=doc.content?.findIndex(n=>n.attrs?.docxIndex===target?.docxIndex)??-1
 if(!target||!field||index<0)throw new Error('域编辑来源身份无效')
 const result=structuredClone(doc),node=result.content![index],groups=docxFieldGroups(node).filter(g=>/^(DATE|TIME|PAGE|NUMPAGES|FILENAME)(?:\s|$)/i.test(g.instruction.trim()))
 if(!['docParagraph','docHeading'].includes(node.type)||groups.length!==target.fields.length||groups.some((g,i)=>g.instruction.trim()!==target.fields[i].instruction.trim()||g.nodes.map(n=>n.text??'').join('')!==target.fields[i].result))throw new Error('域来源或段落结构已变化')
 const group=groups[target.fields.indexOf(field)],newText=op.newResult||' ';let at=0
 // Preserve style boundaries when the cache width permits, including styled neighboring runs.
 group.nodes.forEach((n,i)=>{let take=i===group.nodes.length-1?newText.length-at:Math.min((n.text??'').length,newText.length-at);if(take>0&&/[\uD800-\uDBFF]/.test(newText[at+take-1]!)&&/[\uDC00-\uDFFF]/.test(newText[at+take]??''))take--;n.text=newText.slice(at,at+take);at+=take;n.marks=n.marks!.map(m=>m.type==='instrField'?{...m,attrs:{...m.attrs,instr:op.newInstruction,dirty:true}}:m)})
 node.content=node.content!.filter(n=>n.type!=='text'||n.text)
 return {operation:op,node:schema.nodeFromJSON(result)}
}
