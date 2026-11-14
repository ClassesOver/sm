import type {PdfSignatureInfo} from './vendor/genoffice-pdf/shared/ipc'
export interface PdfDigitalSignatureModel{
 sourceSha256:string;digitalSignatures?:PdfSignatureInfo[]
 signatureVerification?:{scope:'basic-integrity-only';trustPolicy:'none';readable:boolean;issues:string[];revocationChecked:boolean;timestampsVerified:boolean}
}
/** 只展示当前已保存来源；不把草稿预览、空签名域或服务端根证书冒充已核验签名。 */
export function bindPdfDigitalSignatures(options:{owner:Document;sourceSha256:string;model:()=>PdfDigitalSignatureModel;load?:()=>Promise<PdfDigitalSignatureModel>;unavailable:()=>string|null;onGoToPage:(pageIndex:number)=>void;status:(message:string)=>void}){
 let disposed=false,opening=false,generation=0,panel:{dispose():void}|undefined
 let loaded:PdfDigitalSignatureModel|undefined
 const close=()=>{generation++;opening=false;panel?.dispose();panel=undefined}
 function snapshot(required=true){
  const reason=options.unavailable();if(reason)throw Error(reason)
  const current=options.model();if(current.sourceSha256!==options.sourceSha256)throw Error('数字签名来源已变化，请重新打开文档')
  const model=current.signatureVerification?current:loaded??current
  if(required&&(!model.signatureVerification||!model.digitalSignatures))throw Error('数字签名尚未从原生来源读取，不能判断文件未签名')
  return model
 }
 return {async open(){
  if(disposed||opening||panel)return
  const epoch=++generation;opening=true
  try{
   const current=snapshot(false)
   if(!current.signatureVerification&&options.load){
    const result=await options.load();if(disposed||epoch!==generation)return
    if(result.sourceSha256!==options.sourceSha256)throw Error('数字签名只读来源身份不匹配')
    loaded=result
   }
   snapshot();const {showPdfDigitalSignatures}=await import('./pdf-digital-signatures-source')
   if(disposed||epoch!==generation)return
   const model=snapshot()
   panel=showPdfDigitalSignatures({owner:options.owner,model:structuredClone(model),onClose:close,onGoToPage:index=>{if(!disposed&&epoch===generation){try{snapshot();options.onGoToPage(index)}catch(error){options.status(error instanceof Error?error.message:String(error))}}}})
  }catch(error){if(!disposed&&epoch===generation)options.status(error instanceof Error?error.message:String(error))}
  finally{if(epoch===generation)opening=false}
 },close,dispose(){disposed=true;close()}}
}
