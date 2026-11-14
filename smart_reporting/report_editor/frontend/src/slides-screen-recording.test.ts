import {afterEach,expect,it,vi} from 'vitest'
import {startSlideScreenRecording} from './slides-screen-recording'
afterEach(()=>vi.unstubAllGlobals())
it('授权期间取消后到达的流必须立即释放且不开始录制',async()=>{
 let grant!:(stream:MediaStream)=>void
 const stop=vi.fn(),track={stop,addEventListener:vi.fn()}
 const getDisplayMedia=vi.fn(()=>new Promise<MediaStream>(resolve=>grant=resolve))
 vi.stubGlobal('navigator',{mediaDevices:{getDisplayMedia}})
 vi.stubGlobal('MediaRecorder',class{static isTypeSupported(){return true}})
 const controller=new AbortController(),result=startSlideScreenRecording(controller.signal)
 controller.abort();grant({getTracks:()=>[track],getVideoTracks:()=>[track]} as unknown as MediaStream)
 await expect(result).rejects.toThrow(/取消/);expect(stop).toHaveBeenCalledOnce()
 expect(getDisplayMedia).toHaveBeenCalledWith({video:true,audio:false})
})
it('明确说明浏览器缺少屏幕捕获能力，不尝试伪造录制',async()=>{
 vi.stubGlobal('navigator',{mediaDevices:{}})
 await expect(startSlideScreenRecording(new AbortController().signal)).rejects.toThrow(/浏览器/)
})
