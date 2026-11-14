import { z } from 'zod'
import { sha256Hex } from './sha256'
import { createBufferEntrySource } from './zip'
import { readExternalLinks } from './external-links'
import { readWorkbook } from './workbook-read'
export const EXTERNAL_SOURCE_MAX_BYTES=6*1024*1024
export const externalSourceSchema=z.object({kind:z.literal('bindExternalLinkSource'),index:z.number().int().positive().max(64),expectedTarget:z.string().max(2048),name:z.string().min(1).max(255).refine(value=>value.toLowerCase().endsWith('.xlsx')&&!value.includes('/')&&!value.includes(String.fromCharCode(92))&&[...value].every(char=>char.charCodeAt(0)>=32)),mediaType:z.literal('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),size:z.number().int().positive().max(EXTERNAL_SOURCE_MAX_BYTES),sha256:z.string().regex(/^[a-f0-9]{64}$/),bytesBase64:z.string().min(8).max(8*1024*1024).regex(/^[A-Za-z0-9+/]*={0,2}$/)}).strict()
export type ExternalSourceBinding=z.infer<typeof externalSourceSchema>
export async function readExternalSource(raw:unknown){
 const binding=externalSourceSchema.parse(raw),bytes=Uint8Array.from(atob(binding.bytesBase64),char=>char.charCodeAt(0))
 if(bytes.length!==binding.size||await sha256Hex(bytes)!==binding.sha256)throw new Error('授权来源文件身份摘要不匹配')
 await readWorkbook(bytes)
 return {binding,bytes}
}
export async function validateExternalSourceBinding(bytes:Uint8Array,raw:unknown){
 const file=await readExternalSource(raw),link=(await readExternalLinks(await createBufferEntrySource(bytes))).find(item=>item.index===file.binding.index)
 if(!link||link.rawTarget!==file.binding.expectedTarget)throw new Error('授权外链来源已变化')
 return bytes
}
