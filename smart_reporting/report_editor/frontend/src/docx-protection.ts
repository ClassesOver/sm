/** Fixed source f8c17004 ProtectDialog: editing restrictions + password.
 * Whole-file encryption, modify password and privacy are separate capabilities.
 */
import type { NativeOperation } from './native-draft'
export const DOCX_PROTECTION_MODES=['trackedChanges','comments','readOnly','forms'] as const
export type DocxProtectionMode=typeof DOCX_PROTECTION_MODES[number]
export interface DocxProtectionState {edit:string;enforced:boolean;hash?:string;salt?:string;spinCount?:number;algorithmSid?:number}
export interface DocxProtectionModel {expectedSettingsSha256:string;expectedProtectionSha256:string;protection:DocxProtectionState|null;editable:boolean;contentLocked:boolean;hasPassword:boolean;readOnlyReason:string|null}
const SHA=/^[a-f0-9]{64}$/
export function docxProtectionModel(value:unknown):DocxProtectionModel|null {
 if(!value||typeof value!=='object')return null
 const m=value as DocxProtectionModel
 if(typeof m.expectedSettingsSha256!=='string'||!SHA.test(m.expectedSettingsSha256)||typeof m.expectedProtectionSha256!=='string'||!SHA.test(m.expectedProtectionSha256)||typeof m.editable!=='boolean'||typeof m.contentLocked!=='boolean'||typeof m.hasPassword!=='boolean'||(m.protection!==null&&(!m.protection||typeof m.protection.edit!=='string'||typeof m.protection.enforced!=='boolean')))return null
 return {...m,readOnlyReason:typeof m.readOnlyReason==='string'?m.readOnlyReason:null}
}
export function docxProtectionOperations(operations:NativeOperation[],model:DocxProtectionModel|null):NativeOperation[]{
 const ops=operations.filter(o=>o.kind==='setDocumentProtection')
 if(!ops.length)return []
 if(operations.length!==1||ops.length!==1)throw Error('保护文档必须单独保存，请先保存其他修改')
 if(!model||!model.editable)throw Error(model?.readOnlyReason??'当前来源不支持修改文档保护')
 const op=ops[0]!,keys=op.action==='enable'?'action,expectedProtectionSha256,expectedSettingsSha256,kind,mode,password':'action,expectedProtectionSha256,expectedSettingsSha256,kind,password'
 if(Object.keys(op).sort().join()!==keys||!['enable','disable'].includes(String(op.action))||typeof op.password!=='string'||op.password.length>255)throw Error('保护文档草稿无效')
 if(op.expectedSettingsSha256!==model.expectedSettingsSha256||op.expectedProtectionSha256!==model.expectedProtectionSha256)throw Error('保护文档草稿与当前来源不一致')
 if(model.protection?.enforced?op.action!=='disable':op.action!=='enable')throw Error('请先解除保护并保存，重新打开后再更改限制')
 if(op.action==='enable'&&!DOCX_PROTECTION_MODES.includes(op.mode as DocxProtectionMode))throw Error('保护模式无效')
 return ops.map(o=>({...o}))
}
export function withDocxProtection(operations:NativeOperation[],model:DocxProtectionModel|null,action:'enable'|'disable',mode:DocxProtectionMode,password:string):NativeOperation[]{
 if(!model)throw Error('当前来源未提供文档保护能力')
 const others=operations.filter(o=>o.kind!=='setDocumentProtection')
 if(others.length)throw Error('保护文档必须单独保存，请先保存其他修改')
 const op:NativeOperation={kind:'setDocumentProtection',expectedSettingsSha256:model.expectedSettingsSha256,expectedProtectionSha256:model.expectedProtectionSha256,action,password,...(action==='enable'?{mode}:{})}
 return docxProtectionOperations([op],model)
}
/** The original source remains locked even with a pending disable transition. */
export function docxProtectionContentLocked(model:DocxProtectionModel|null):boolean{return model?.contentLocked??false}
