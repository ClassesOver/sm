import {expect,it} from 'vitest'
import {readSlideMedia,mediaPlaybackWarning,validateMediaInsertions} from './pptx-media'

it('媒体回读拒绝外链、本机路径、缺失和未知容器，保留可核验的文件身份',()=>{
 const elements=[['external',{kind:'video',target:'https://example.invalid/private.mp4',external:true}],['path',{kind:'audio',target:'/etc/passwd'}],['missing',{kind:'audio',target:'ppt/media/missing.wav'}],['unknown',{kind:'video',target:'ppt/media/original.mkv'}],['mov',{kind:'video',target:'ppt/media/original.mov'}]].map(([id,media])=>({id,type:'picture',media}))
 const opened={deck:{slides:[{elements}]},archive:{readBytes:(path:string)=>path.includes('missing')?undefined:new Uint8Array([1,2,3])}} as any
 const result=readSlideMedia(opened,0)
 expect(result.slice(0,4).every(item=>!('dataUrl' in item))).toBe(true)
 expect(JSON.stringify(result)).not.toContain('https://example.invalid');expect(result[3]!.sha256).toHaveLength(64);expect(result[3]!.size).toBe(3)
 expect((result[4] as any).dataUrl).toBe('data:video/mp4;base64,AQID')
 expect(mediaPlaybackWarning('video','avi',new Uint8Array([1]))).toContain('浏览器不支持')
})
it('桥接整批媒体和图片共用八 MiB，拒绝路径、页越界和非规范编码',()=>{
 const opened={deck:{slides:[{}]}} as any,item={slideIndex:0,kind:'audio' as const,extension:'wav',bytesBase64:'UklGRg=='}
 validateMediaInsertions(opened,[item])
 for(const patch of [{path:'/tmp/a'},{slideIndex:1},{bytesBase64:'Zh=='},{kind:'video'}])expect(()=>validateMediaInsertions(opened,[{...item,...patch} as any])).toThrow()
 const bytesBase64=Buffer.alloc(5*1024*1024).toString('base64')
 expect(()=>validateMediaInsertions(opened,[{...item,bytesBase64}],[{bytesBase64}])).toThrow('budget')
})
