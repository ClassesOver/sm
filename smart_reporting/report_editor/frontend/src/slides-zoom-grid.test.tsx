import {afterEach,expect,it,vi} from 'vitest'
import {mountZoomGrid} from './slides-zoom-grid'
vi.mock('./vendor/genoffice/renderer/SlideThumb',()=>({SlideThumb:()=>null}))
let controller:AbortController
afterEach(()=>{controller?.abort();document.body.replaceChildren()})
it('保留缩略图单选、Ctrl/Command多选及取消选中语义',async()=>{
 const host=document.body.appendChild(document.createElement('div')),changed=vi.fn()
 controller=new AbortController()
 await mountZoomGrid(host,[0,1].map(index=>({index,caption:`第 ${index+1} 页`,slide:{nodes:[]} as never})),changed,controller.signal)
 await vi.waitFor(()=>expect(host.querySelectorAll('button')).toHaveLength(2))
 const [first,second]=host.querySelectorAll('button')
 first!.click();await vi.waitFor(()=>expect(first!.getAttribute('aria-pressed')).toBe('true'))
 second!.dispatchEvent(new MouseEvent('click',{bubbles:true,ctrlKey:true}));await vi.waitFor(()=>expect(second!.getAttribute('aria-pressed')).toBe('true'));expect(changed).toHaveBeenLastCalledWith([0,1])
 first!.dispatchEvent(new MouseEvent('click',{bubbles:true,metaKey:true}));await vi.waitFor(()=>expect(first!.getAttribute('aria-pressed')).toBe('false'));expect(changed).toHaveBeenLastCalledWith([1])
 second!.dispatchEvent(new MouseEvent('click',{bubbles:true,ctrlKey:true}));await vi.waitFor(()=>expect(second!.getAttribute('aria-pressed')).toBe('false'));expect(changed).toHaveBeenLastCalledWith([])
})
