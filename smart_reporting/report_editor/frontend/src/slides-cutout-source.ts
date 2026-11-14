/** 去背景只处理render-tree中的原媒体dataURL；先与当前来源图片身份独立核对。 */
export async function verifiedCutoutSource(dataUrl:string,expectedSha256:string,expectedSize:number):Promise<string>{
 const match=/^data:image\/(png|jpeg);base64,([A-Za-z0-9+/]+={0,2})$/.exec(dataUrl)
 if(!match||expectedSize<=0||expectedSize>6*1024*1024)throw Error('图片来源不支持去背景，请选择6 MiB以内的嵌入PNG/JPEG')
 let raw:string
 try{raw=atob(match[2]!)}catch{throw Error('图片来源编码无效')}
 if(btoa(raw)!==match[2]||raw.length!==expectedSize)throw Error('图片来源身份已变化')
 const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0)),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('')
 if(sha!==expectedSha256)throw Error('图片来源身份已变化')
 return dataUrl
}
