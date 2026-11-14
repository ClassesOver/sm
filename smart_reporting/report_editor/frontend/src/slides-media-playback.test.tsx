import React,{act} from 'react'
import {createRoot, type Root} from 'react-dom/client'
import {beforeEach,afterEach,expect,it,vi} from 'vitest'
import type {RenderSlide} from '@genoffice/pptx-render'
import {ShowMediaLayer,runMediaCommand} from './vendor/genoffice/renderer/ShowMediaLayer'
import {openSlideMediaPlayback} from './slides-media-playback'
let root:Root|undefined,editor:ReturnType<typeof openSlideMediaPlayback>|undefined
beforeEach(()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
 vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue();vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});vi.spyOn(HTMLMediaElement.prototype,'load').mockImplementation(()=>{})
 Object.defineProperty(HTMLDialogElement.prototype,'show',{configurable:true,value:function(){this.open=true}})
})
afterEach(async()=>{await act(async()=>root?.unmount());root=undefined;editor?.dispose();editor=undefined;document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})
const source={sourceId:'movie',kind:'video' as const,sha256:'a'.repeat(64),size:3,dataUrl:'data:video/webm;base64,AQID'}
const slide={widthPx:960,heightPx:540,nodes:[{id:'movie',sourceId:'movie',type:'picture',media:'video',box:{x:20,y:30,w:200,h:100}}]} as unknown as RenderSlide
it('播放命令重新从零、暂停切换、停止回零；play拒绝通过错误回执显式返回',async()=>{
 const el=document.createElement('video'),failed=vi.fn();el.currentTime=2
 runMediaCommand(el,'mediaPlay',failed);expect(el.currentTime).toBe(0);expect(el.play).toHaveBeenCalledOnce()
 Object.defineProperty(el,'paused',{configurable:true,value:false});runMediaCommand(el,'mediaPause',failed);expect(el.pause).toHaveBeenCalledOnce()
 el.currentTime=3;runMediaCommand(el,'mediaStop',failed);expect(el.currentTime).toBe(0)
 vi.mocked(el.play).mockRejectedValueOnce(Error('codec'));runMediaCommand(el,'mediaPlay',failed);await Promise.resolve();expect(failed).toHaveBeenCalledOnce()
})
it('源放映层按顺序执行命令，epoch回到已播放状态不重播，销毁释放实际媒体src',async()=>{
 root=createRoot(document.body.appendChild(document.createElement('div')))
 const render=(epoch:number,mediaBase:number)=>root!.render(<ShowMediaLayer slide={slide} sources={[source]} width={480} commands={[{sourceId:'movie',effect:'mediaPlay'}]} epoch={epoch} mediaBase={mediaBase}/>)
 await act(async()=>render(1,0));const player=document.querySelector('video')!;expect(player.play).toHaveBeenCalledOnce()
 await act(async()=>player.dispatchEvent(new Event('play')));expect(player.play).toHaveBeenCalledOnce();expect(player.getAttribute('src')).toBe(source.dataUrl)
 await act(async()=>render(2,1));expect(player.play).toHaveBeenCalledOnce()
 await act(async()=>root!.unmount());root=undefined;expect(player.getAttribute('src')).toBeNull();expect(player.pause).toHaveBeenCalled();expect(player.load).toHaveBeenCalled()
})
it('实际浏览器错误显式显示失败，编辑态拒绝外链且关闭清理播放器',async()=>{
 root=createRoot(document.body.appendChild(document.createElement('div')))
 await act(async()=>root!.render(<ShowMediaLayer slide={slide} sources={[source]} width={480} commands={[]} epoch={1} mediaBase={0}/>))
 await act(async()=>document.querySelector('video')!.dispatchEvent(new Event('error')));expect(document.body.textContent).toContain('浏览器无法播放')
 expect(()=>openSlideMediaPlayback(document.body,{...source,dataUrl:undefined,reason:'未授权'},slide.nodes[0]!.box,960)).toThrow('未授权')
 editor=openSlideMediaPlayback(document.body,source,slide.nodes[0]!.box,960);const player=document.querySelector('.slides-media-playback video')!
 expect(player.getAttribute('src')).toBe(source.dataUrl);editor.dispose();expect(player.getAttribute('src')).toBeNull();expect(document.querySelector('.slides-media-playback')).toBeNull()
})
