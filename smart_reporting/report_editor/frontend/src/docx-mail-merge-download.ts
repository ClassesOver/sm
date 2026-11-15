export async function verifyDocxMailMergeDownload(result:{content:ArrayBuffer;size:number;sha256:string;sourceSha256:string;filename:string},expectedSource:string){
 const bytes=new Uint8Array(result.content),digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',result.content)),b=>b.toString(16).padStart(2,'0')).join('')
 if(result.sourceSha256!==expectedSource||!Number.isSafeInteger(result.size)||bytes.length!==result.size||bytes.length<4||bytes.length>64*1024*1024||bytes[0]!==80||bytes[1]!==75||bytes[2]!==3||bytes[3]!==4||digest!==result.sha256)throw new Error('邮件合并下载身份校验失败，请重新导出')
 return bytes
}
