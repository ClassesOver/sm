import type {Editor} from '@tiptap/core'
import {annotationsFromParsed,buildInkImages,type InkAnnotation} from './docx-ink'
import type {DocxInkModel,DocxInkOperation} from '../../../reporting/doc_engine/bridge/docx-ink'
export type {DocxInkModel,DocxInkOperation}
/** Journal callback must commit via the document's NativeDocxHistory transaction.
 * Reading it on every action keeps undo/redo and restored draft JSON authoritative. */
export function createDocxInkController(options:{editor:()=>Editor|null;model:()=>DocxInkModel|undefined;operations:()=>{kind:string;[key:string]:unknown}[];commit:(operation:DocxInkOperation)=>boolean;canEdit:()=>boolean}) {
 const annotations=():InkAnnotation[]=>{
  const op=options.operations().find(o=>o.kind==='setInk') as unknown as DocxInkOperation|undefined
  const restored=annotationsFromParsed(op?op.inks.map(i=>({...i,dataUrl:`data:image/png;base64,${i.base64}`,payload:i.payload??null})):options.model()?.inks??[])
  return restored.map((a,i)=>{const key=JSON.stringify([a.anchorIndex,a.stroke,a.image]);let h=2166136261;for(let j=0;j<key.length;j++)h=Math.imul(h^key.charCodeAt(j),16777619);return {...a,id:`native-ink-${h>>>0}-${restored.slice(0,i).filter(b=>JSON.stringify([b.anchorIndex,b.stroke,b.image])===key).length}`}})
 }
 const replace=(values:InkAnnotation[]):boolean=>{
  const model=options.model()
  if(!options.canEdit()||!options.editor()?.isEditable||!model?.editable)return false
  const anchors=new Map(values.map(a=>[a.anchorIndex,a.anchorIndex]))
  const inks=buildInkImages(values,anchors).map(({blockIndex,...image})=>({...image,anchorIndex:blockIndex}))
  return options.commit({kind:'setInk',expectedInkSha256:model.expectedInkSha256,inks})
 }
 return {annotations,replace,add:(value:InkAnnotation)=>replace([...annotations(),value]),remove:(ids:string[])=>replace(annotations().filter(a=>!ids.includes(a.id))),clear:()=>replace([])}
}
