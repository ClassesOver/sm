import {createElement} from 'react'
import {createRoot} from 'react-dom/client'
import {SignaturesDialog} from './vendor/genoffice-pdf/renderer/SignaturesDialog'
import {installFocusTrap} from './focus-trap'
import type {PdfDigitalSignatureModel} from './pdf-digital-signatures'
import './pdf-signature-dialog.css'
import './pdf-digital-signatures.css'
const strings:Record<string,string>={
 certSign:'证书签名',
 sigPanelTitle:'数字签名',sigStatusValid:'基本完整性检查通过',sigStatusWarning:'需要留意',sigStatusUntrusted:'完整，信任未建立',sigStatusInvalid:'无效',sigKindTimestamp:'文档时间戳（未验证）',sigSignedBy:'签名人：{name}',sigSignedAt:'签名内的时间（非可信时间戳）',sigClaimedAt:'声明的时间（未验证）',sigOnPage:'第 {page} 页',sigGoToPage:'跳转到该页',sigReason:'原因',sigLocation:'地点',sigContact:'联系方式',sigHash:'哈希算法',sigCertified:'声明的认证级别：{level}',sigCovers:'签名范围',sigCoversAll:'整个已保存文档',sigCoversPart:'未覆盖当前文件全部字节',sigChain:'证书链',sigChainTrusted:'本服务不判断证书信任',sigChainUntrusted:'信任未建立',sigSubject:'主体',sigIssuedBy:'颁发者',sigValidFrom:'生效时间',sigValidTo:'失效时间',sigSerial:'序列号',sigFingerprint:'SHA-256 指纹',sigKey:'公钥',sigSelfSigned:'自签名',
 sigTrustRoots:'仅检查基本字节完整性与受支持的分离 CMS 签名；未建立组织或用户的证书信任策略，未验证证书用途、完整 PKI 路径或可信时间戳。',sigNoRevocation:'未检查证书吊销状态（CRL / OCSP）。',sigProblemDigestMismatch:'文档与签名中的摘要不一致',sigProblemSignatureInvalid:'签名本身无效',sigProblemMalformed:'签名数据已损坏或格式错误',sigProblemUnsupported:'此处无法检查这种类型或算法的签名',sigProblemNoSignerCert:'签名中缺少匹配的签名人证书',sigProblemChanged:'此签名之后又添加了内容；已签名的部分未改变',sigProblemSelfSigned:'自签名证书：没有第三方为签名人的身份担保',sigProblemUntrusted:'未建立签名人的证书信任',sigProblemExpired:'证书在声明的签署时间已过期',sigProblemNotYetValid:'证书在声明的签署时间尚未生效',certLevel1:'不允许修改',certLevel2:'填写表单与签名',certLevel3:'填写表单、签名与批注',ok:'关闭',
}
export function showPdfDigitalSignatures(options:{owner:Document;model:PdfDigitalSignatureModel;onClose:()=>void;onGoToPage:(index:number)=>void}){
 const dialog=options.owner.createElement('dialog');dialog.className='pdf-signature-source-dialog pdf-digital-signatures-dialog';dialog.setAttribute('aria-label','数字签名');const opener=options.owner.activeElement as HTMLElement|null
 options.owner.body.append(dialog);const root=createRoot(dialog),release=installFocusTrap(dialog);let active=true
 function dispose(){if(!active)return;active=false;release();root.unmount();if(dialog.open)dialog.close();dialog.remove();if(opener?.isConnected)opener.focus({preventScroll:true})}
 function close(){if(active){dispose();options.onClose()}}
 const model=options.model,verification=model.signatureVerification!
 const notice=verification.readable?(model.digitalSignatures!.length?'':'没有已赋值的数字签名；空签名字段和可视手写签名不属于数字签名。'):verification.issues.join('；')||'无法完整读取数字签名，不能判断文件未签名。'
 const t=(key:string,args?:Record<string,string|number>)=>(strings[key]??key).replace(/\{(\w+)\}/g,(_all,key:string)=>String(args?.[key]??''))
 root.render(createElement('div',{},
  createElement('p',{className:'pdf-signature-source-notice'},'仅核对已保存来源；未保存修改未参与核验。来源 SHA-256：'+model.sourceSha256),
  notice?createElement('p',{className:'pdf-signature-source-notice',role:'status'},notice):null,
  createElement(SignaturesDialog,{t,signatures:verification.readable?model.digitalSignatures!:[],onClose:close,onGoToPage:options.onGoToPage})))
 dialog.addEventListener('cancel',event=>{event.preventDefault();close()});dialog.showModal()
 return {dispose}
}
