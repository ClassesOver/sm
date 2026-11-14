/** 复用原生3D writer；宿主只接有界GLB和真实PNG，不接路径。 */
import {createHash} from 'node:crypto'
import {addModel3d,setModel3dView,type OpenedPptx,type Slide} from '@genoffice/pptx-engine'
import {validateLocalGlb} from '../packages/pptx-engine/src/glb-resources.ts'
import type {Model3dRotation} from '../packages/pptx-engine/src/model3d.ts'
export type ModelInsertion={slideIndex:number;key:string;bytesBase64:string;posterBase64:string;name:string;aspect:number;rot:Model3dRotation}
export type ModelViewEdit={slideIndex:number;elementId:string;expectedSha256:string;rot:Model3dRotation;posterBase64:string}
function decode(value:string,max:number):Buffer {
 if(typeof value!=='string'||value.length>Math.ceil(max/3)*4)throw Error('model3d_asset_invalid')
 const bytes=Buffer.from(value,'base64')
 if(!bytes.length||bytes.length>max||bytes.toString('base64')!==value)throw Error('model3d_asset_invalid')
 return bytes
}
function png(value:string){const b=decode(value,4*1024*1024);if(b.length<24||b.subarray(0,8).toString('hex')!=='89504e470d0a1a0a'||b.readUInt32BE(16)>1600||b.readUInt32BE(20)>1600||!b.readUInt32BE(16)||!b.readUInt32BE(20))throw Error('model3d_poster_invalid');return b}
function rotation(rot:Model3dRotation){if(!rot||Object.keys(rot).sort().join()!=='ax,ay,az'||![rot.ax,rot.ay,rot.az].every(n=>typeof n==='number'&&Number.isFinite(n)&&Math.abs(n)<=2160000000))throw Error('model3d_rotation_invalid')}
export function readModelSources(opened:OpenedPptx,index:number){return (opened.deck.slides[index]?.elements??[]).flatMap(el=>{
 if(el.type!=='picture'||!el.model3d)return []
 const target=el.model3d.target,base={sourceId:el.id,rot:el.model3d.rot}
 if(!target||!/^ppt\/media\/[^/]+\.glb$/i.test(target))return [{...base,reason:'模型来源无法核验'}]
 const bytes=opened.archive.readBytes(target)
 if(!bytes)return [{...base,reason:'嵌入GLB缺失'}]
 const identity={...base,sha256:createHash('sha256').update(bytes).digest('hex'),size:bytes.length}
 try{validateLocalGlb(bytes);return [{...identity,bytesBase64:Buffer.from(bytes).toString('base64')}]}catch(error){return [{...identity,reason:error instanceof Error?error.message:'模型无法读取'}]}
})}
export function validateModels(opened:OpenedPptx,insertions:ModelInsertion[],views:ModelViewEdit[],otherBytes=0){
 if(!Array.isArray(insertions)||!Array.isArray(views)||insertions.length>30||views.length>100)throw Error('model3d_request_invalid')
 const keys=new Set<string>(),targets=new Set<string>();let total=otherBytes
 for(const item of insertions){
  if(!item||Object.keys(item).sort().join()!=='aspect,bytesBase64,key,name,posterBase64,rot,slideIndex'||!opened.deck.slides[item.slideIndex]||!Number.isInteger(item.slideIndex)||typeof item.key!=='string'||!/^[a-zA-Z0-9-]{1,80}$/.test(item.key)||keys.has(item.key)||typeof item.name!=='string'||item.name.length>500||/[\x00-\x1f\x7f]/.test(item.name)||typeof item.aspect!=='number'||!Number.isFinite(item.aspect)||item.aspect<1/3||item.aspect>3)throw Error('model3d_insertion_invalid')
  keys.add(item.key);rotation(item.rot);const b=decode(item.bytesBase64,6*1024*1024);validateLocalGlb(b);total+=b.length+png(item.posterBase64).length
 }
 for(const item of views){
  if(!item||Object.keys(item).sort().join()!=='elementId,expectedSha256,posterBase64,rot,slideIndex'||!Number.isInteger(item.slideIndex)||!opened.deck.slides[item.slideIndex]||typeof item.elementId!=='string'||typeof item.expectedSha256!=='string')throw Error('model3d_view_invalid')
  const key=item.slideIndex+':'+item.elementId,source=readModelSources(opened,item.slideIndex).find(s=>s.sourceId===item.elementId)
  if(targets.has(key)||!source||!('bytesBase64' in source)||source.sha256!==item.expectedSha256)throw Error('model3d_source_changed')
  targets.add(key);rotation(item.rot);total+=png(item.posterBase64).length
 }
 if(total>8*1024*1024)throw Error('model3d_budget_exceeded')
}
export function applyModels(opened:OpenedPptx,slides:Slide[],insertions:ModelInsertion[],views:ModelViewEdit[]){
 for(const item of views){const slide=slides[item.slideIndex]!;if(!setModel3dView(opened,slide,item.elementId,{rot:item.rot,poster:{bytes:png(item.posterBase64),ext:'png'}}))throw Error('model3d_view_failed')}
 for(const item of insertions){const slide=slides[item.slideIndex]!,index=opened.deck.slides.indexOf(slide),cy=Math.round(opened.deck.size.cy*.5),cx=Math.round(cy*item.aspect)
 const result=addModel3d(opened,index,{bytes:decode(item.bytesBase64,6*1024*1024),ext:'glb',poster:{bytes:png(item.posterBase64),ext:'png'},rot:item.rot,name:item.name,offset:{x:Math.round((opened.deck.size.cx-cx)/2),y:Math.round((opened.deck.size.cy-cy)/2),cx,cy}})
 if(!result)throw Error('model3d_insert_failed');slides[item.slideIndex]=result.slide
 }
}
