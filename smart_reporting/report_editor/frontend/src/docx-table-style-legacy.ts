import type {Schema} from '@tiptap/pm/model'
import type {DocxPmNode} from './docx-operations'
import {DEFAULT_TABLE_LOOK,normalizeTableStylePatch,tablePresetCell,type TableStylePatch,type TableStyleSource,type TableStyleOption} from './docx-table-style-core'
export interface DocxTableStyleAnchor {docxIndex?:number;blockId?:string;expectedObjectSha256?:string;tableStyleEditable?:boolean;tableStyleReadOnlyReason?:string|null;tableStyleSource?:TableStyleSource;tableStyleOptions?:TableStyleOption[]}
export interface DocxTableStyleOperation extends TableStylePatch {[key:string]:unknown;kind:'setTableStyle';blockId:string;expectedObjectSha256:string}
const canonical=(v:unknown):unknown=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b)).map(([k,x])=>[k,canonical(x)])):v
const same=(a:unknown,b:unknown)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b))
function fail():never{throw Error('docx_table_style_draft_invalid')}
function currentStyle(source:TableStyleSource,patch:TableStylePatch){return patch.style?patch.style.kind==='document'?patch.style.styleId:null:source.styleId}
function lookOf(value:unknown){return value??DEFAULT_TABLE_LOOK}
/** Final portable intent also retains the most recent preset's direct formatting. */
export function projectDocxTableStyle(source:DocxPmNode,anchor:DocxTableStyleAnchor,input:unknown,schema?:Schema):DocxPmNode {
 if(!schema||source.type!=='docTable'||!anchor.tableStyleEditable||!anchor.tableStyleSource)throw Error(anchor.tableStyleReadOnlyReason??'docx_table_style_unavailable')
 if(Object.entries(source.attrs??{}).some(([k,v])=>k.startsWith('nativeTable')&&k!=='nativeTableStyle'&&v))fail()
 const attrs=source.attrs??{},previous=attrs.nativeTableStyle?normalizeTableStylePatch(attrs.nativeTableStyle):{},base=anchor.tableStyleSource
 if((attrs.tblStyleId??null)!==currentStyle(base,previous)||!same(lookOf(attrs.tblLook),previous.look??base.look))fail()
 const next=normalizeTableStylePatch(input),patch:TableStylePatch={...previous,...next}
 if(next.style?.kind==='preset')patch.preset=next.style.id
 if(next.style?.kind==='document'&&!anchor.tableStyleOptions?.some(s=>s.styleId===(next.style as {styleId:string}).styleId))fail()
 const json=structuredClone(source),a=json.attrs??={}
 if(next.style)a.tblStyleId=next.style.kind==='document'?next.style.styleId:null
 if(next.look){a.tblLook=next.look;a.tblLookEdited=true}
 const preset=next.style?.kind==='preset'?next.style.id:next.preset
 if(preset)for(const [r,row] of (json.content??[]).entries())for(const cell of row.content??[])cell.attrs={...cell.attrs,...tablePresetCell(preset,r)}
 a.nativeTableStyle=patch
 const result=schema.nodeFromJSON(json).toJSON() as DocxPmNode
 if(!same(result.attrs?.nativeTableStyle,patch))fail()
 return result
}
function tableOf(doc:DocxPmNode,index:number){return doc.content?.find(n=>n.type==='docTable'&&n.attrs?.docxIndex===index)}
export function normalizeDocxTableStyle(baseline:DocxPmNode,live:DocxPmNode,anchors:readonly DocxTableStyleAnchor[],schema?:Schema){
 const current=structuredClone(live),operations:DocxTableStyleOperation[]=[]
 for(const anchor of anchors){const original=tableOf(baseline,anchor.docxIndex!),table=tableOf(current,anchor.docxIndex!);if(!original||!table||!table.attrs?.nativeTableStyle)continue
  if(!anchor.blockId||!anchor.expectedObjectSha256||original.attrs?.nativeTableStyle)fail()
  const patch=normalizeTableStylePatch(table.attrs.nativeTableStyle),expected=projectDocxTableStyle(original,anchor,patch,schema)
  if(!same(expected,table))fail()
  const at=current.content!.indexOf(table);current.content![at]=structuredClone(original)
  operations.push({kind:'setTableStyle',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,...patch})
 }
 return{baseline,current,operations}
}
export function replayDocxTableStyle(baseline:DocxPmNode,operations:readonly Record<string,unknown>[],anchors:readonly DocxTableStyleAnchor[],schema?:Schema):DocxPmNode {
 const current=structuredClone(baseline),seen=new Set<string>()
 for(const op of operations){if(op.kind!=='setTableStyle')continue
  if(Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','style','look','preset'].includes(k)))fail()
  const anchor=anchors.find(a=>a.blockId===op.blockId),table=anchor&&tableOf(current,anchor.docxIndex!)
  if(!anchor||!table||anchor.expectedObjectSha256!==op.expectedObjectSha256||seen.has(anchor.blockId!))fail()
  const patch=normalizeTableStylePatch({...('style'in op?{style:op.style}:{}),...('look'in op?{look:op.look}:{}),...('preset'in op?{preset:op.preset}:{})})
  current.content![current.content!.indexOf(table)]=projectDocxTableStyle(table,anchor,patch,schema);seen.add(anchor.blockId!)
 }
 return current
}
