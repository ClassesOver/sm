import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {webcrypto} from 'node:crypto'
import {compareDocuments,type PageText} from './vendor/genoffice-pdf/renderer/compare-text'

const parser=vi.hoisted(()=>({pages:['same\nnew','extra'],failure:null as Error|null,pending:null as Promise<unknown>|null,destroyed:0,started:0,holdCalculation:false}))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs',()=>({getDocument:()=>{parser.started++;return{promise:parser.failure?Promise.reject(parser.failure):parser.pending??Promise.resolve({numPages:parser.pages.length,getPage:async(n:number)=>({getTextContent:async()=>({items:parser.pages[n-1].split('\n').map(str=>({str,hasEOL:true}))})})}),destroy:async()=>{parser.destroyed++}}}}))
let dirty=false,disposed:(()=>void)|undefined
beforeEach(()=>{dirty=false;parser.pages=['same\nnew','extra'];parser.failure=null;parser.pending=null;parser.destroyed=0;parser.started=0;parser.holdCalculation=false;vi.stubGlobal('crypto',webcrypto)
 vi.stubGlobal('Worker',class{onmessage:((event:{data:unknown})=>void)|null=null;onerror:unknown;canceled=false;postMessage(value:{left:PageText[];right:PageText[]}){if(!parser.holdCalculation)queueMicrotask(()=>{if(!this.canceled)this.onmessage?.({data:compareDocuments(value.left,value.right)})})}terminate(){this.canceled=true}})
})
afterEach(()=>{disposed?.();disposed=undefined;document.body.replaceChildren();vi.unstubAllGlobals()})
async function fixture(){
 const path='./pdf-compare'
 const module=await import(/* @vite-ignore */path).catch(()=>null)
 expect(module,'read-only comparison adapter is available').not.toBeNull()
 if(!module)throw Error('comparison not implemented')
 const container=document.body.appendChild(document.createElement('aside')),navigated:string[]=[]
 const pdf={numPages:1,getPage:async()=>({getTextContent:async()=>({items:[{str:'same',hasEOL:true},{str:'old',hasEOL:true}]})})}
 const compare=module.bindPdfCompare({container,source:()=>({document:pdf,sha256:'a'.repeat(64),size:12,name:'source.pdf',pages:[{index:0,pageId:'source-page-0'}]}),unavailable:()=>dirty?'对比前请先保存文档':null,navigate:(id:string)=>navigated.push(id)})
 disposed=()=>compare.dispose()
 const input=container.querySelector<HTMLInputElement>('input[type=file]')!
 const pick=(name='other.pdf')=>{const file=new File(['%PDF-fixture'],name,{type:'application/pdf'});Object.defineProperty(file,'arrayBuffer',{value:async()=>new TextEncoder().encode('%PDF-fixture').buffer});Object.defineProperty(input,'files',{configurable:true,value:[file]});input.dispatchEvent(new Event('change'))}
 return{container,compare,navigated,pick}
}
it('uses the complete source component, swaps counts and never navigates a non-source extra page',async()=>{
 const f=await fixture();f.pick();await vi.waitFor(()=>expect(f.container.querySelectorAll('.pdf-compare-row')).toHaveLength(2))
 const rows=f.container.querySelectorAll<HTMLButtonElement>('.pdf-compare-row');rows[0].click();expect(f.navigated).toEqual(['source-page-0']);expect(rows[1].disabled).toBe(true)
 expect(rows[0].textContent).toContain('+1 行');expect(rows[0].textContent).toContain('−1 行')
 f.container.querySelector<HTMLButtonElement>('.pdf-compare-swap')!.click()
 await vi.waitFor(()=>expect(f.container.querySelectorAll('.pdf-compare-row')[1].textContent).toContain('−1 行'))
 const identity=f.container.querySelector<HTMLElement>('[data-pdf-compare-identity]')!
 expect(identity.dataset.sha256).toMatch(/^[a-f0-9]{64}$/);expect(identity.dataset.size).toBe('12');expect(identity.textContent).toContain('other.pdf')
})
it('refuses pending edits and does not read a picked PDF',async()=>{
 const f=await fixture();dirty=true;f.pick();await Promise.resolve();expect(f.container.textContent).toContain('先保存');expect(f.container.querySelector('.pdf-compare-row')).toBeNull();expect(parser.destroyed).toBe(0)
})
it('reports scan or blank text as a limited text comparison',async()=>{
 const f=await fixture();parser.pages=[''];f.pick();await vi.waitFor(()=>expect(f.container.textContent).toContain('无可提取文本'));expect(f.container.textContent).toContain('无法判断视觉内容')
})
it('retains the previous result when native picking is canceled and allows selecting the same file again',async()=>{
 const f=await fixture();f.pick();await vi.waitFor(()=>expect(f.container.querySelectorAll('.pdf-compare-row')).toHaveLength(2));f.container.querySelector('input')!.dispatchEvent(new Event('cancel'));expect(f.container.querySelectorAll('.pdf-compare-row')).toHaveLength(2)
 parser.pages=['same\nold'];f.pick();await vi.waitFor(()=>expect(f.container.textContent).toContain('两个文档的文本一致'));expect(f.container.querySelector('.pdf-compare-row')).toBeNull()
})
it('reports password failures without producing an identical result',async()=>{
 const f=await fixture();parser.failure=Object.assign(new Error('Password required'),{name:'PasswordException'});f.pick();await vi.waitFor(()=>expect(f.container.textContent).toContain('密码'));expect(f.container.textContent).not.toContain('文本一致');expect(parser.destroyed).toBe(1)
})
it('cancels a pending parser and ignores its late result',async()=>{
 const f=await fixture();let release:(value:unknown)=>void=()=>{};parser.pending=new Promise(resolve=>release=resolve);f.pick();await vi.waitFor(()=>expect(parser.started).toBe(1));f.compare.cancel();release({numPages:1,getPage:async()=>({getTextContent:async()=>({items:[]})})});await Promise.resolve();await Promise.resolve();expect(f.container.querySelector('.pdf-compare-row')).toBeNull();expect(f.container.getAttribute('aria-busy')).toBe('false');expect(parser.destroyed).toBe(1)
})
it('disposal cannot repopulate the panel with a late parser result',async()=>{
 const f=await fixture();let release:(value:unknown)=>void=()=>{};parser.pending=new Promise(resolve=>release=resolve);f.pick();await vi.waitFor(()=>expect(parser.started).toBe(1));f.compare.dispose();disposed=undefined;release({numPages:1,getPage:async()=>({getTextContent:async()=>({items:[]})})});await Promise.resolve();await Promise.resolve();expect(f.container.childElementCount).toBe(0);expect(parser.destroyed).toBe(1)
})
it('canceling a pending swap retains the displayed old/new orientation on the next comparison',async()=>{
 const f=await fixture();f.pick();await vi.waitFor(()=>expect(f.container.querySelectorAll('.pdf-compare-row')).toHaveLength(2))
 parser.holdCalculation=true;f.container.querySelector<HTMLButtonElement>('.pdf-compare-swap')!.click();expect(f.container.getAttribute('aria-busy')).toBe('true');f.compare.cancel()
 parser.holdCalculation=false;f.pick();await vi.waitFor(()=>expect(f.container.getAttribute('aria-busy')).toBe('false'))
 expect(f.container.querySelectorAll('.pdf-compare-row')[1].textContent).toContain('+1 行')
})
