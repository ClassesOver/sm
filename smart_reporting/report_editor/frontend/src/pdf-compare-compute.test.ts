import {afterEach,expect,it,vi} from 'vitest'
import {compareDocuments} from './vendor/genoffice-pdf/renderer/compare-text'

afterEach(()=>vi.unstubAllGlobals())
async function module(){const path='./pdf-compare-compute';const result=await import(/* @vite-ignore */path).catch(()=>null);expect(result,'comparison must execute outside the UI thread').not.toBeNull();if(!result)throw Error('worker adapter missing');return result}
it('sends both complete page sides to the module worker and returns the unchanged source result',async()=>{
 vi.stubGlobal('Worker',class{onmessage:((event:{data:unknown})=>void)|null=null;onerror:unknown;postMessage(value:{left:Parameters<typeof compareDocuments>[0];right:Parameters<typeof compareDocuments>[1]}){queueMicrotask(()=>this.onmessage?.({data:compareDocuments(value.left,value.right)}))}terminate(){}})
 const {createPdfComparison}=await module(),task=createPdfComparison([{pageIndex:0,text:'first\nold'}],[{pageIndex:0,text:'first\nnew'},{pageIndex:1,text:'extra'}])
 await expect(task.promise).resolves.toMatchObject({equal:false,pages:[{pageIndex:0,addedCount:1,removedCount:1},{pageIndex:1,addedCount:1,removedCount:0}]})
})
it('terminates work and rejects cancellation instead of delivering a late result',async()=>{
 let terminated=false
 vi.stubGlobal('Worker',class{onmessage:unknown;onerror:unknown;postMessage(){}terminate(){terminated=true}})
 const {createPdfComparison}=await module(),task=createPdfComparison([{pageIndex:0,text:'old'}],[{pageIndex:0,text:'new'}]),rejected=expect(task.promise).rejects.toThrow('已取消')
 task.cancel();await rejected;expect(terminated).toBe(true)
})
