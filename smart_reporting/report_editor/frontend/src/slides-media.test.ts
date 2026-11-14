import { expect, it } from 'vitest'
import { validateSlideMediaInsertions, prepareSlideMedia, pickSlideMedia } from './slides-media'

const item = { slideIndex: 0, kind: 'audio', extension: 'wav', bytesBase64: btoa('RIFFfixture'), name: '样例.wav' }
it('媒体草稿整批验证原始字节、类型与来源页，拒绝本机路径和迟到目标', () => {
 expect(() => validateSlideMediaInsertions({mediaInsertions:[item]},1,[])).not.toThrow()
 for(const patch of [{kind:'video'},{extension:'exe'},{bytesBase64:'Zh=='},{bytesBase64:''},{path:'/tmp/a.wav'},{slideIndex:1},{name:'bad\nname'}])expect(()=>validateSlideMediaInsertions({mediaInsertions:[{...item,...patch}]},1,[])).toThrow()
 expect(()=>validateSlideMediaInsertions({mediaInsertions:[item]},1,[0])).toThrow()
})
it('媒体和图片共享八 MiB，单媒体不超过六 MiB',()=>{
 const bytesBase64=btoa('x'.repeat(5*1024*1024))
 expect(()=>validateSlideMediaInsertions({mediaInsertions:[{...item,bytesBase64}],images:[{bytesBase64}]},1,[])).toThrow()
 expect(()=>validateSlideMediaInsertions({mediaInsertions:[{...item,bytesBase64:btoa('x'.repeat(6*1024*1024+1))}]},1,[])).toThrow()
})
it('录屏与三维模型海报也共享八 MiB，不能由各类单独绕过总预算',()=>{
 const asset=btoa('x'.repeat(4*1024*1024))
 expect(()=>validateSlideMediaInsertions({mediaInsertions:[item],images:[{bytesBase64:asset}],modelViews:[{posterBase64:asset}]},1,[])).toThrow()
 expect(()=>validateSlideMediaInsertions({mediaInsertions:[{...item,poster:null}]},1,[])).toThrow()
})
it('选择容器后保留实际文件字节，不按不稳定 MIME 拒绝源支持容器',async()=>{
 const result=await prepareSlideMedia(new File(['RIFFfixture'],'样例.wav',{type:'application/octet-stream'}),'audio')
 expect(result).toMatchObject({kind:'audio',extension:'wav',name:'样例.wav',bytesBase64:item.bytesBase64})
 await expect(prepareSlideMedia(new File(['x'],'wrong.mp4'),'audio')).rejects.toThrow()
})

it('销毁信号取消媒体选择并移除临时input，已取消读取不得解析字节',async()=>{
 const controller=new AbortController(),picked=pickSlideMedia('audio',controller.signal)
 expect(document.querySelector('input[type=file]')).not.toBeNull();controller.abort();expect(await picked).toBeNull();expect(document.querySelector('input[type=file]')).toBeNull()
 await expect(prepareSlideMedia(new File(['x'],'a.wav'),'audio',controller.signal)).rejects.toThrow('取消')
})
