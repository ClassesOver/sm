/** 本地草稿身份契约；四个业务字段来自固定源 shared/ipc.ts::MetadataInput。 */
export const metadataFields=['title','author','subject','keywords'] as const
export type MetadataValues=Record<(typeof metadataFields)[number],string>
export interface MetadataOperation {kind:'setMetadata';sourceSha256:string;modifiedMs:number;metadata:MetadataValues}
export function validateMetadataOperation(value:unknown,sourceSha256:string):asserts value is MetadataOperation{
 const op=value as MetadataOperation
 if(!op||typeof op!=='object'||Array.isArray(op)||Object.keys(op).some(k=>!['kind','sourceSha256','modifiedMs','metadata'].includes(k))||op.kind!=='setMetadata'||!/^[a-f0-9]{64}$/.test(op.sourceSha256)||op.sourceSha256!==sourceSha256||!Number.isSafeInteger(op.modifiedMs)||op.modifiedMs<0||op.modifiedMs>8640000000000000)throw Error('文档属性身份或修改时间无效')
 if(!op.metadata||typeof op.metadata!=='object'||Array.isArray(op.metadata)||Object.keys(op.metadata).some(k=>!metadataFields.includes(k as typeof metadataFields[number]))||metadataFields.some(k=>typeof op.metadata[k]!=='string'||op.metadata[k].length>4096||/[\p{Cc}\p{Cf}\u2028\u2029]/u.test(op.metadata[k])))throw Error('文档属性仅支持标题、作者、主题和关键词，每项最多4096字符且不可含控制字符')
}
export const normalizedKeywords=(value:string)=>value.split(/[,，;；]/).map(k=>k.trim()).filter(Boolean).join(' ')
