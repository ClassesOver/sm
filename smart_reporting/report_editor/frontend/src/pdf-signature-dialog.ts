import {createPdfSignatureStore,type PdfSignatureData} from './pdf-signature-store'
import type {NativeDraftIdentity} from './native-draft'
/** 完整签名输入仅在来源、权限及草稿仍有效时回传原生放置链路。 */
export function bindPdfSignatureDialog(options:{owner:Document;scope:NativeDraftIdentity['scope'];snapshot:()=>string;unavailable:()=>string|null;color:()=>[number,number,number];onConfirm:(data:PdfSignatureData)=>void;status:(message:string)=>void}){
 let disposed=false,generation=0,opening=false,dialog:{dispose():void}|undefined
 const close=()=>{generation++;opening=false;dialog?.dispose();dialog=undefined}
 return {async open(){
  if(disposed||opening||dialog)return
  const blocked=options.unavailable();if(blocked){options.status(blocked);return}
  const epoch=++generation,snapshot=options.snapshot(),active=()=>!disposed&&epoch===generation
  opening=true
  try{const {showPdfSignatureDialog}=await import('./pdf-signature-dialog-source');if(!active())return
   const validate=()=>{const reason=options.unavailable();if(reason)throw Error(reason);if(options.snapshot()!==snapshot)throw Error('草稿或页面来源已变化，请重新打开签名')}
   validate();const storage={getItem:(key:string)=>options.owner.defaultView!.localStorage.getItem(key),setItem:(key:string,value:string)=>options.owner.defaultView!.localStorage.setItem(key,value)}
   dialog=showPdfSignatureDialog({owner:options.owner,color:options.color(),store:createPdfSignatureStore(options.scope,storage),onCancel:close,onConfirm(data){if(!active())return;validate();options.onConfirm(data);close()}})
  }catch(error){if(active())options.status(error instanceof Error?error.message:String(error))}finally{if(active())opening=false}
 },cancel:close,incompleteReason:()=>opening||dialog?'请先完成或取消签名设置':null,dispose(){disposed=true;close()}}
}
