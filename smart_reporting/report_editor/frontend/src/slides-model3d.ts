import type {Model3dRotation} from '@genoffice/pptx-engine/model3d'
import {validateLocalGlb} from '@genoffice/pptx-engine/glb-resources'
export type ModelSource={sourceId:string;rot:Model3dRotation;sha256?:string;size?:number;bytesBase64?:string;reason?:string}
export type ModelInsertion={slideIndex:number;key:string;name:string;bytesBase64:string;posterBase64:string;aspect:number;rot:Model3dRotation}
export type ModelViewEdit={slideIndex:number;elementId:string;expectedSha256:string;posterBase64:string;rot:Model3dRotation}
export type ModelChanges={modelInsertions?:ModelInsertion[];modelViews?:ModelViewEdit[]}
export function bytes64(bytes:Uint8Array){let result='';for(let i=0;i<bytes.length;i+=32768)result+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(result)}
export const from64=(value:string)=>Uint8Array.from(atob(value),char=>char.charCodeAt(0))
export function turnModelDraft(changes:ModelChanges,slideIndex:number,source:ModelSource,key:string|undefined,rot:Model3dRotation,posterBase64:string):ModelChanges{
 const result=structuredClone(changes)
 if(key){const item=result.modelInsertions?.find(item=>item.slideIndex===slideIndex&&item.key===key);if(!item)throw Error('模型草稿已变化');item.rot={...rot};item.posterBase64=posterBase64}
 else{if(!source.sha256||!source.bytesBase64)throw Error(source.reason??'模型来源无法核验');result.modelViews=[...(result.modelViews??[]).filter(item=>item.slideIndex!==slideIndex||item.elementId!==source.sourceId),{slideIndex,elementId:source.sourceId,expectedSha256:source.sha256,rot:{...rot},posterBase64}]}
 return result
}
export function validateModelDraft(changes:ModelChanges,count:number,deleted:number[]=[]){
 const keys=new Set<string>();let budget=0
 for(const [kind,items] of [['insert',changes.modelInsertions??[]],['view',changes.modelViews??[]]] as const){
  if(!Array.isArray(items)||items.length>(kind==='insert'?30:100))throw Error('模型草稿无效')
  for(const item of items){
   if(!item||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=count||deleted.includes(item.slideIndex)||!item.rot||Object.keys(item.rot).sort().join()!=='ax,ay,az'||!Object.values(item.rot).every(n=>typeof n==='number'&&Number.isFinite(n)&&Math.abs(n)<=2160000000)||typeof item.posterBase64!=='string'||item.posterBase64.length>5600000)throw Error('模型草稿无效')
   const poster=from64(item.posterBase64);if(poster.length<24||bytes64(poster)!==item.posterBase64||Array.from(poster.subarray(0,8)).join()!=='137,80,78,71,13,10,26,10')throw Error('模型海报无效');budget+=poster.length
   if('key' in item){if(Object.keys(item).sort().join()!=='aspect,bytesBase64,key,name,posterBase64,rot,slideIndex'||typeof item.key!=='string'||!/^[a-zA-Z0-9-]{1,80}$/.test(item.key)||typeof item.name!=='string'||item.name.length>500||/[\x00-\x1f\x7f]/.test(item.name)||!Number.isFinite(item.aspect)||item.aspect<1/3||item.aspect>3||typeof item.bytesBase64!=='string'||item.bytesBase64.length>8388608)throw Error('模型草稿无效');const data=from64(item.bytesBase64);validateLocalGlb(data);budget+=data.length;const key='i:'+item.key;if(keys.has(key))throw Error('模型重复');keys.add(key)}
   else{if(Object.keys(item).sort().join()!=='elementId,expectedSha256,posterBase64,rot,slideIndex'||typeof item.elementId!=='string'||!item.elementId||!(/^[a-f0-9]{64}$/.test(item.expectedSha256)))throw Error('模型来源身份无效');const key=item.slideIndex+':'+item.elementId;if(keys.has(key))throw Error('模型重复');keys.add(key)}
  }
 }
 if(budget>8*1024*1024)throw Error('模型资产超出8MiB预算')
}
