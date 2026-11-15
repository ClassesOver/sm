/** GenOffice f8c17004 editable ink: source PNG + vector descr, never inline pictures. */
import {createHash} from 'node:crypto'
import type {InkInfo,NewInkImage} from '../packages/docx-engine/src/types'
export interface DocxInkModel { inks:InkInfo[];editable:boolean;readOnlyReason:string|null;expectedInkSha256:string }
export type DocxInkInput=Omit<NewInkImage,'blockIndex'>&{anchorIndex:number}
export interface DocxInkOperation {kind:'setInk';expectedInkSha256:string;inks:DocxInkInput[]}
export function inspectDocxInk(inks:InkInfo[],protectedSource:boolean):DocxInkModel {
 const reason=protectedSource?'文档受保护，墨迹保持原样':inks.some(i=>!i.dataUrl?.startsWith('data:image/png;base64,'))?'来源墨迹图像无法读取，保持原样':null
 return {inks,editable:!reason,readOnlyReason:reason,expectedInkSha256:createHash('sha256').update(JSON.stringify(inks)).digest('hex')}
}
/** Anchor map must come from the final save plan; reject stale/deleted anchors. */
export function validateDocxInkOperations(operations:Record<string,unknown>[],model:DocxInkModel,saveBlockIndexByDocx:Map<number,number>):NewInkImage[]|undefined {
 if(!operations.length)return undefined
 const bad=():never=>{throw new Error('docx_ink_operation_invalid')}
 if(operations.length!==1)throw new Error('docx_ink_batch_conflict')
 const op=operations[0]!
 if(Object.keys(op).sort().join()!=='expectedInkSha256,inks,kind'||op.kind!=='setInk')return bad()
 if(!model.editable)throw new Error('docx_ink_source_unsupported')
 if(op.expectedInkSha256!==model.expectedInkSha256)throw new Error('docx_ink_anchor_invalid')
 if(!Array.isArray(op.inks)||op.inks.length>2000)return bad()
 return op.inks.map((item:unknown)=>{
  if(!item||typeof item!=='object'||Array.isArray(item))return bad()
  const ink=item as Record<string,unknown>
  if(Object.keys(ink).some(k=>!['anchorIndex','base64','widthPx','heightPx','offsetXPx','offsetYPx','payload'].includes(k)))return bad()
  const blockIndex=saveBlockIndexByDocx.get(ink.anchorIndex as number)
  if(!Number.isInteger(ink.anchorIndex)||blockIndex===undefined)throw new Error('docx_ink_anchor_invalid')
  for(const key of ['widthPx','heightPx','offsetXPx','offsetYPx'])if(typeof ink[key]!=='number'||!Number.isFinite(ink[key])||Math.abs(ink[key] as number)>20000)return bad()
  if((ink.widthPx as number)<=0||(ink.heightPx as number)<=0)return bad()
  if(typeof ink.base64!=='string'||ink.base64.length>16000000||!/^[A-Za-z0-9+/]+={0,2}$/.test(ink.base64))return bad()
  const png=Buffer.from(ink.base64,'base64')
  if(png.length<24||png.subarray(0,8).toString('hex')!=='89504e470d0a1a0a'||png.subarray(12,16).toString()!=='IHDR')return bad()
  if(png.readUInt32BE(16)>40000||png.readUInt32BE(20)>40000||!png.readUInt32BE(16)||!png.readUInt32BE(20))return bad()
  if(ink.payload!==undefined){
   if(typeof ink.payload!=='string'||ink.payload.length>2000000)return bad()
   let p:any;try{p=JSON.parse(ink.payload)}catch{return bad()}
   if(p.v!==1||!['pen','pencil','highlighter'].includes(p.tool)||!/^([0-9a-f]{6})$/i.test(p.color)||!Number.isFinite(p.width)||p.width<=0||p.width>100||!Array.isArray(p.points)||!p.points.length||p.points.length>100000)return bad()
   if(p.points.some((q:unknown)=>!Array.isArray(q)||q.length!==2||q.some(v=>typeof v!=='number'||!Number.isFinite(v)||Math.abs(v)>20000)))return bad()
  }
  const {anchorIndex,...image}=ink
  return {...image,blockIndex} as unknown as NewInkImage
 })
}
export function assertDocxInkWritten(parsed:InkInfo[],expected:NewInkImage[]):void {
 if(parsed.length!==expected.length)throw new Error('docx_ink_write_not_applied')
 const remaining=[...parsed]
 for(const b of expected){
  const index=remaining.findIndex(a=>a.anchorIndex===b.blockIndex&&(a.payload??undefined)===b.payload&&a.dataUrl===`data:image/png;base64,${b.base64}`&&['widthPx','heightPx','offsetXPx','offsetYPx'].every(k=>Math.abs((a as any)[k]-(b as any)[k])<=1/9525))
  if(index<0)throw new Error('docx_ink_write_not_applied')
  remaining.splice(index,1)
 }
}
