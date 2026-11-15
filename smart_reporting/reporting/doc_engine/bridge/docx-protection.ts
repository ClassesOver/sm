/** Review > Protect Document, fixed GenOffice f8c17004 ProtectDialog.
 * Protection transitions are isolated saves: never authorize content edits in this batch.
 * Passwords are transient request credentials; never persist them in source models.
 */
import { createHash } from 'node:crypto'
import { XMLParser, XMLValidator } from 'fast-xml-parser'
import { hashProtectionPassword, verifyProtectionPassword } from '../packages/docx-engine/src/protection'
import type { DocProtection } from '../packages/docx-engine/src/types.ts'
export const DOCX_PROTECTION_MODES = ['trackedChanges','comments','readOnly','forms'] as const
export interface DocxProtectionModel {
 expectedSettingsSha256: string; expectedProtectionSha256: string
 protection: DocProtection | null; editable: boolean; contentLocked: boolean; hasPassword: boolean; readOnlyReason: string | null
}
const sha = (s:string)=>createHash('sha256').update(s).digest('hex')
const stable = (p:DocProtection|null)=>JSON.stringify(p)
export function inspectDocxProtection(settingsXml:string):DocxProtectionModel {
 const tags=settingsXml.match(/<(?:[\w.-]+:)?documentProtection\b[^>]*(?:\/>|>\s*<\/(?:[\w.-]+:)?documentProtection\s*>)/g)??[]
 let protection:DocProtection|null=null
 let valid=(!settingsXml || XMLValidator.validate(settingsXml)===true) && !/<!DOCTYPE|<!ENTITY/i.test(settingsXml) && (!settingsXml || /^\s*(?:<\?xml[^>]*>\s*)?<w:settings\b[^>]*xmlns:w="http:\/\/schemas.openxmlformats.org\/wordprocessingml\/2006\/main"[^>]*(?:\/>|>[\s\S]*<\/w:settings>)\s*$/.test(settingsXml))
 if((settingsXml.match(/<(?:[\w.-]+:)?documentProtection\b/g)??[]).length!==tags.length || tags.length>1) valid=false
 if(valid&&settingsXml){try{const tree=new XMLParser({preserveOrder:true,ignoreAttributes:false}).parse(settingsXml);const root=tree.find((node:Record<string,unknown>)=>node['w:settings']);const children=root?.['w:settings']??[];if(children.filter((node:Record<string,unknown>)=>'w:documentProtection' in node).length!==tags.length)valid=false}catch{valid=false}}
 if(tags.length===1){
  const tag=tags[0]!, attrs=[...tag.matchAll(/\s([\w:]+)="([^"]*)"/g)], a=Object.fromEntries(attrs.map(x=>[x[1],x[2]]))
  const remaining=tag.replace(/^<w:documentProtection\b/,'').replace(/\/?>\s*(?:<\/w:documentProtection\s*>)?$/,'').replace(/\s[\w:]+="[^"]*"/g,'').trim()
  if(remaining)valid=false
  const allowed=new Set(['w:edit','w:enforcement','w:hash','w:salt','w:cryptSpinCount','w:cryptAlgorithmSid','w:cryptProviderType','w:cryptAlgorithmClass','w:cryptAlgorithmType'])
  if(!tag.startsWith('<w:documentProtection') || attrs.length!==Object.keys(a).length || attrs.some(x=>!allowed.has(x[1]!)) || /[&']/.test(tag) || !DOCX_PROTECTION_MODES.includes(a['w:edit'] as any) || !['0','1','true','false'].includes(a['w:enforcement']??'')) valid=false
  protection={edit:a['w:edit']??'',enforced:['1','true'].includes(a['w:enforcement']??'')}
  if(a['w:hash']){
   protection.hash=a['w:hash'];protection.salt=a['w:salt'];protection.spinCount=Number(a['w:cryptSpinCount']);protection.algorithmSid=Number(a['w:cryptAlgorithmSid'])
   if(!protection.salt || protection.algorithmSid!==14 || !Number.isSafeInteger(protection.spinCount) || protection.spinCount!<0 || protection.spinCount!>1000000 || !/^[A-Za-z0-9+/]{86}==$/.test(protection.hash) || !/^[A-Za-z0-9+/]+={0,2}$/.test(protection.salt)) valid=false
  } else if(a['w:salt'] || a['w:cryptSpinCount'] || a['w:cryptAlgorithmSid']) valid=false
 }
 // Password-to-modify belongs to a separate unlock lifecycle; preserve and lock it.
 if(/<(?:[\w.-]+:)?writeProtection\b/.test(settingsXml)) valid=false
 return {expectedSettingsSha256:sha(settingsXml),expectedProtectionSha256:sha(tags.join('')),protection,editable:valid,contentLocked:!valid||!!protection?.enforced,hasPassword:!!protection?.hash,readOnlyReason:valid?null:'来源保护设置不受支持，保持只读'}
}
export async function validateDocxProtectionOperations(operations:Record<string,unknown>[],model:DocxProtectionModel):Promise<{protection?:DocProtection|null}>{
 if(!operations.length)return {}
 if(operations.length!==1)throw Error('docx_protection_batch_conflict')
 const op=operations[0]!, keys=op.action==='enable'?'action,expectedProtectionSha256,expectedSettingsSha256,kind,mode,password':'action,expectedProtectionSha256,expectedSettingsSha256,kind,password'
 if(op.kind!=='setDocumentProtection'||!['enable','disable'].includes(String(op.action))||Object.keys(op).sort().join()!==keys||typeof op.password!=='string'||op.password.length>255)throw Error('docx_protection_operation_invalid')
 if(!model.editable)throw Error('docx_protection_source_unsupported')
 if(op.expectedSettingsSha256!==model.expectedSettingsSha256||op.expectedProtectionSha256!==model.expectedProtectionSha256)throw Error('docx_protection_anchor_invalid')
 if(model.protection?.enforced){
  // Enabling/changing protection requires a separate disable/save/reload first.
  if(op.action!=='disable')throw Error('docx_protection_disable_first')
  let verified=false;try{verified=await verifyProtectionPassword(op.password,model.protection)}catch{}
  if(!verified)throw Error('docx_protection_password_invalid')
  return {protection:null}
 }
 if(op.action!=='enable'||!DOCX_PROTECTION_MODES.includes(op.mode as any))throw Error('docx_protection_operation_invalid')
 return {protection:{edit:op.mode as string,enforced:true,...(op.password?await hashProtectionPassword(op.password):{})}}
}
export function assertDocxProtectionWritten(settingsXml:string,expected:DocProtection|null):void{
 const actual=inspectDocxProtection(settingsXml)
 if(!actual.editable||stable(actual.protection)!==stable(expected))throw Error('docx_protection_write_not_applied')
}
/** Call before applying ANY content operation; removing protection only unlocks after reload. */
export function assertDocxProtectionBatch(operations:Record<string,unknown>[],model:DocxProtectionModel):void{
 const transitions=operations.filter(o=>o.kind==='setDocumentProtection')
 if(transitions.length && operations.length!==1)throw Error('docx_protection_isolated_save_required')
 if(model.contentLocked&&operations.some(o=>o.kind!=='setDocumentProtection'))throw Error('docx_protection_content_locked')
}
