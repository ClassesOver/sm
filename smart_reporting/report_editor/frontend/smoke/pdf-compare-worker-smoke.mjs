import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {createServer} from 'vite'

const frontend=fileURLToPath(new URL('../',import.meta.url)),directory='/dev/shm/office-pdf-compare-source-20261113'
const server=await createServer({root:frontend,configFile:resolve(frontend,'vite.config.ts'),cacheDir:resolve(directory,'worker-vite-cache'),server:{host:'127.0.0.1',port:4467,strictPort:true,watch:{ignored:['**/*']}}})
await server.listen()
const browser=await chromium.launch({headless:true})
try{
 const page=await browser.newPage(),errors=[]
 page.on('pageerror',error=>errors.push(error.message))
 await page.goto('http://127.0.0.1:4467/reports/v1/editor/assets/favicon.svg')
 const results=await page.evaluate(async()=>{
  const {createPdfComparison}=await import('/reports/v1/editor/assets/src/pdf-compare-compute.ts')
  const left=Array.from({length:10},(_,pageIndex)=>({pageIndex,text:Array.from({length:4000},(_,index)=>`old ${index}`).join('\n')})),right=Array.from({length:10},(_,pageIndex)=>({pageIndex,text:Array.from({length:4000},(_,index)=>`new ${index}`).join('\n')}))
  const started=performance.now(),task=createPdfComparison(left,right),caught=task.promise.then(()=>({canceled:false}),error=>({canceled:true,message:error.message}))
  const eventDelay=await new Promise(resolve=>setTimeout(()=>resolve(performance.now()-started),20))
  task.cancel();const cancellation=await caught
  const small=createPdfComparison(left.slice(0,1),right.slice(0,1)),result=await small.promise
  const swap=createPdfComparison(right.slice(0,1),left.slice(0,1)),swapped=await swap.promise
  return{eventDelay,cancellation,result:{equal:result.equal,pages:result.pages.length,added:result.pages[0].addedCount,removed:result.pages[0].removedCount,firstAdded:result.pages[0].added[0].line},swapped:{firstAdded:swapped.pages[0].added[0].line},sourceLines:4000,canceledPages:10}
 })
 assert.ok(results.eventDelay<150,JSON.stringify(results));assert.equal(results.cancellation.canceled,true)
 assert.deepEqual(results.result,{equal:false,pages:1,added:4000,removed:4000,firstAdded:'new 0'});assert.equal(results.swapped.firstAdded,'old 0');assert.deepEqual(errors,[])
 await writeFile(resolve(directory,'worker-browser.json'),JSON.stringify({results,errors},null,2));console.log(JSON.stringify({results,errors},null,2))
}finally{await browser.close();await server.close()}
