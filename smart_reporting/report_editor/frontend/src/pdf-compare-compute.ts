import type {CompareResult,PageText} from './vendor/genoffice-pdf/renderer/compare-text'

/** Keep the pinned quadratic LCS off the UI thread; cancellation releases its memory. */
export function createPdfComparison(left:PageText[],right:PageText[]){
 let worker:Worker|undefined,finished=false,rejectTask:(error:Error)=>void=()=>{}
 const stop=()=>{worker?.terminate();worker=undefined}
 const promise=new Promise<CompareResult>((resolve,reject)=>{
  rejectTask=reject
  try{
   worker=new Worker(new URL('./pdf-compare-worker.ts',import.meta.url),{type:'module'})
   worker.onmessage=(event:MessageEvent<CompareResult>)=>{if(finished)return;finished=true;stop();resolve(event.data)}
   worker.onerror=event=>{if(finished)return;finished=true;stop();reject(Error(event.message||'PDF 文本比较线程失败'))}
   worker.postMessage({left,right})
  }catch(error){finished=true;stop();reject(error)}
 })
 return{promise,cancel(){if(finished)return;finished=true;stop();rejectTask(Error('已取消 PDF 文本比较'))}}
}
