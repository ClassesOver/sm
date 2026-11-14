import type {createNativeApi} from './native-api'

export type MailMergeRecord=Record<string,string>
export interface MailMergeSource {name:string;path:string;sourceSha256:string;sourceBase64:string;fields:string[];records:MailMergeRecord[];recordCount:number}
export async function uploadDocxMailMergeSource(api:Pick<ReturnType<typeof createNativeApi>,'mailMergeSource'>,file:File):Promise<MailMergeSource>{
  if(file.size<1||file.size>4*1024*1024)throw new Error('收件人 CSV 必须为 1 字节至 4 MiB')
  const bytes=new Uint8Array(await file.arrayBuffer())
  let binary=''
  for(let index=0;index<bytes.length;index+=8192)binary+=String.fromCharCode(...bytes.subarray(index,index+8192))
  const base64=btoa(binary)
  const result=await api.mailMergeSource({requestId:crypto.randomUUID(),filename:file.name,bytesBase64:base64})
  return {...result.source,sourceBase64:base64}
}
export function mailMergeOperation(source:MailMergeSource,documentSha256:string){ return {kind:'mailMergeSingle' as const,documentSha256,sourceSha256:source.sourceSha256,sourceBase64:source.sourceBase64} }
