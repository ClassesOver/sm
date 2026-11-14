import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import type {RenderSlide} from '@genoffice/pptx-render'
import {renderSlidesPrintImages} from './slides-print-render'

const stage=vi.hoisted(()=>({draw:vi.fn(),toDataURL:vi.fn(()=> 'data:image/png;base64,QQ==')}))
vi.mock('react-dom/client',()=>({createRoot:()=>({render(element:{props:{stageRef:(stage:unknown)=>void}}){element.props.stageRef(stage)},unmount:vi.fn()})}))
vi.mock('./vendor/genoffice/renderer/SlideThumb',()=>({SlideThumb:()=>null}))
const images:HTMLImageElement[]=[]
beforeEach(()=>{
 vi.stubGlobal('Image',function(){const image=document.createElement('img');images.push(image);return image})
 vi.stubGlobal('requestAnimationFrame',(callback:FrameRequestCallback)=>{queueMicrotask(()=>callback(0));return 1})
})
afterEach(()=>{images.length=0;document.body.replaceChildren();vi.clearAllMocks();vi.unstubAllGlobals()})
const slides=():RenderSlide[]=>[{widthPx:960,heightPx:540,scale:1,nodes:[],background:{kind:'image',mode:'stretch',dataUrl:'data:image/png;base64,Qg=='}}]

it('releases pending image handlers and its source when rasterization is cancelled',async()=>{
 const abort=new AbortController(),work=renderSlidesPrintImages(slides(),abort.signal),rejected=expect(work).rejects.toMatchObject({name:'AbortError'})
 expect(images).toHaveLength(1);expect(images[0]!.onload).toBeTypeOf('function')
 abort.abort();await rejected
 expect(images[0]!.onload).toBeNull();expect(images[0]!.onerror).toBeNull();expect(images[0]!.getAttribute('src')).toBeNull();expect(stage.draw).not.toHaveBeenCalled();expect(document.body.children).toHaveLength(0)
})

it('cleans completed images and the offscreen stage after rendering',async()=>{
 const abort=new AbortController(),work=renderSlidesPrintImages(slides(),abort.signal)
 images[0]!.onload!(new Event('load'))
 await expect(work).resolves.toEqual(['data:image/png;base64,QQ=='])
 expect(images[0]!.onload).toBeNull();expect(images[0]!.onerror).toBeNull();expect(stage.draw).toHaveBeenCalledOnce();expect(document.body.children).toHaveLength(0)
})

it('cancels the remaining image loads after one embedded image fails',async()=>{
 const input=slides();input.push({...input[0]!,background:{kind:'image',mode:'stretch',dataUrl:'data:image/png;base64,Qw=='}})
 const work=renderSlidesPrintImages(input,new AbortController().signal),rejected=expect(work).rejects.toThrow('幻灯片内嵌图片读取失败')
 expect(images).toHaveLength(2);images[0]!.onerror!(new Event('error'));await rejected
 for(const image of images){expect(image.onload).toBeNull();expect(image.onerror).toBeNull()}
 expect(images[1]!.getAttribute('src')).toBeNull();expect(document.body.children).toHaveLength(0)
})
