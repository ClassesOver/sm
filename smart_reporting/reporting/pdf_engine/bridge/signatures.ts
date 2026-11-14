import {readPdfSignatures} from '../src/main/pdf-signatures'

/** 仅基本完整性核验；服务端根证书不能代表报告接收人的信任政策。 */
export async function inspectDigitalSignatures(bytes:Uint8Array){
 const signatureVerification={scope:'basic-integrity-only' as const,trustPolicy:'none' as const,revocationChecked:false,timestampsVerified:false,readable:true,issues:[] as string[]}
 try{
  const digitalSignatures=await readPdfSignatures(bytes)
  for(const sig of digitalSignatures){
   sig.trusted=false
   if(sig.status==='valid'){sig.status='untrusted';sig.problems.push('untrusted-issuer')}
  }
  return {digitalSignatures,signatureVerification}
 }catch{
  signatureVerification.readable=false;signatureVerification.issues.push('数字签名结构无法完整读取，不能据此判断文件未签名或签名有效')
  return {digitalSignatures:[],signatureVerification}
 }
}
