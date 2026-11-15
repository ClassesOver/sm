import {it,expect}from 'vitest'
import {verifyDocxMailMergeDownload}from './docx-mail-merge-download'
it('refuses an export whose actual bytes differ from its issued identity',async()=>{
 const bytes=new Uint8Array([80,75,3,4,5]);await expect(verifyDocxMailMergeDownload({content:bytes.buffer,size:5,sha256:'0'.repeat(64),sourceSha256:'a'.repeat(64),filename:'mail-merge.zip'},'a'.repeat(64))).rejects.toThrow('身份')
})
it('accepts the actual ZIP bytes only for the expected source',async()=>{
 const bytes=new Uint8Array([80,75,3,4,5]),digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join(''),result={content:bytes.buffer,size:5,sha256:digest,sourceSha256:'a'.repeat(64),filename:'mail-merge.zip'}
 await expect(verifyDocxMailMergeDownload(result,'b'.repeat(64))).rejects.toThrow('身份')
 expect(await verifyDocxMailMergeDownload(result,'a'.repeat(64))).toEqual(bytes)
})
