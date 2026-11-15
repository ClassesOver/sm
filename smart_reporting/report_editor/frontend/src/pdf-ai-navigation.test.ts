import {afterEach,expect,it,vi} from 'vitest'
import {navigatePDFReadTarget} from './pdf-ai-navigation'
afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks()})
function fixture() {
 let pages=[{pageId:'p1'},{pageId:'p2'}],active='p1',current=true,available=true,visible=true
 const viewport=document.createElement('div'),node=document.createElement('section')
 node.dataset.pageId='p2';viewport.append(node);document.body.append(viewport)
 vi.spyOn(viewport,'getBoundingClientRect').mockImplementation(()=>({left:0,right:500,top:0,bottom:400,width:500,height:400} as DOMRect))
 vi.spyOn(node,'getBoundingClientRect').mockImplementation(()=>({left:10,right:410,top:visible?0:500,bottom:visible?300:800,width:400,height:300} as DOMRect))
 vi.spyOn(window,'requestAnimationFrame').mockImplementation(callback=>{queueMicrotask(()=>callback(0));return 1})
 const navigate=vi.fn((id:string)=>{active=id;node.classList.add('is-active')})
 const options={viewport,pages:()=>pages,currentPage:()=>active,pageNode:(id:string)=>id==='p2'?node:undefined,current:()=>current,available:()=>available,navigate}
 return {options,navigate,hide:()=>{visible=false},cancel:()=>{current=false},lock:()=>{available=false},move:()=>{active='p1'},reorder:()=>{pages.reverse()}}
}
const target={page:2,pageId:'p2'}
it('verifies matching page identity and active visible DOM after navigation',async()=>{
 const f=fixture();await navigatePDFReadTarget(target,f.options);expect(f.navigate).toHaveBeenCalledExactlyOnceWith('p2')
})
it.each([{page:0,pageId:'p2'},{page:true,pageId:'p2'},{page:1,pageId:'p2'},{page:2,pageId:'foreign'}])('rejects invalid or mismatched targets before moving: %j',async invalid=>{
 const f=fixture();await expect(navigatePDFReadTarget(invalid as never,f.options)).rejects.toThrow();expect(f.navigate).not.toHaveBeenCalled()
})
it.each(['hide','cancel','lock','move','reorder'] as const)('does not confirm after %s while waiting for layout',async mutation=>{
 const f=fixture();const result=navigatePDFReadTarget(target,f.options);f[mutation]();await expect(result).rejects.toThrow()
})
