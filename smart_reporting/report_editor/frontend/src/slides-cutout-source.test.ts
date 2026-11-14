import {expect,it} from 'vitest'
import {verifiedCutoutSource} from './slides-cutout-source'
it('只读取已核验PNG/JPEG原图字节并匹配sha/size，不获取外链',async()=>{
 const bytes=Uint8Array.from([137,80,78,71,13,10,26,10,0]),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join(''),dataUrl='data:image/png;base64,'+btoa(String.fromCharCode(...bytes))
 expect(await verifiedCutoutSource(dataUrl,sha,bytes.length)).toBe(dataUrl)
 await expect(verifiedCutoutSource(dataUrl,'0'.repeat(64),bytes.length)).rejects.toThrow('身份')
 await expect(verifiedCutoutSource('https://external/x.png',sha,bytes.length)).rejects.toThrow('来源')
 await expect(verifiedCutoutSource(dataUrl,sha,bytes.length+1)).rejects.toThrow('身份')
})
