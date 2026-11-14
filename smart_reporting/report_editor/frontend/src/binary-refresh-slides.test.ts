import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createSlidesEditorView} from './slides-main'
import {createEditorShell} from './shell'
import style from './style.css?raw'
import slidesStyle from './slides.css?raw'
import officeStyle from './office-theme.css?raw'
import refreshStyle from './binary-refresh.css?raw'
const sha='a'.repeat(64),digest='b'.repeat(64)
let capability=true,previewFails=false,registered=true
let fetcher: ReturnType<typeof vi.fn>
let view: ReturnType<typeof createSlidesEditorView>|undefined
const task={taskId:'recalc-slides',status:'completed',result:{issueCodes:['code_only']},execution:{status:'completed',runId:'run',issueCodes:[]}}
beforeEach(()=>{
 document.body.innerHTML='<div id="app"></div>';history.replaceState({},'','/reports/v1/slides/report/1');localStorage.clear()
 const css=document.createElement('style');css.textContent=style+slidesStyle+officeStyle+refreshStyle;document.head.append(css)
 document.cookie='report_slides_csrf=slides-token';document.cookie='report_editor_csrf=md-wrong';document.cookie='report_native_csrf=native-wrong'
 capability=true;previewFails=false;registered=true
 fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/context'))return new Response(JSON.stringify({reportId:'report',revision:1,sha256:sha,contextSha256:digest,dataRefresh:{available:capability}}))
  if(url.endsWith('/deck')){if(previewFails)throw Error('deck missing');return new Response(JSON.stringify({revision:1,sha256:sha,size:{cx:9144000,cy:5143500},slides:[{slideIndex:0,animations:[],elements:[{id:'title',type:'text',name:'title',text:'original',editable:true,geometry:{x:1,y:1,width:10,height:10}}]}]}))}
  if(url.endsWith('/save'))return new Response(JSON.stringify({revision:2,revisionRegistered:registered,pptx:{downloadUrl:'/saved.pptx'},editor:{openUrl:'/reports/v1/slides/report/2'},validation:{issues:[]}}))
  if(url.endsWith('/delivery'))return new Response(JSON.stringify({task,delivery:{pptx:{downloadUrl:'/actual.pptx'},pdf:{downloadUrl:'/wrong.pdf'},validation:{ok:false,issues:[{code:'pptx_validation_failed'}]}}}))
  if(url.includes('/recalculations'))return new Response(JSON.stringify(task))
  if(url.endsWith('/charts'))return new Response(JSON.stringify({charts:[]}))
  return new Response(JSON.stringify({slides:[]}))
 });vi.stubGlobal('fetch',fetcher)
})
afterEach(()=>{view?.dispose();view=undefined;window.dispatchEvent(new Event('pagehide'));document.head.querySelectorAll('style').forEach(s=>s.remove());vi.unstubAllGlobals()})
async function open(){const shell=createEditorShell(document.querySelector('#app')!,'full','pptx');view=createSlidesEditorView(shell.editor,{save:shell.save,download:shell.exportPptx});await view.ready;return shell}
const action=()=>document.querySelector<HTMLButtonElement>('[data-action=binary-refresh]')!
it('mounts actual slides main with own CSRF, precise SHA, visible single-target delivery and code-only reasons',async()=>{
 await open();expect(action()).not.toBeNull();expect(action().disabled).toBe(false)
 action().click();await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
 const post=fetcher.mock.calls.find(([url,init])=>String(url).endsWith('/recalculations')&&init?.method==='POST')!
 expect(post[0]).toBe('/reports/v1/slides/report/1/api/recalculations')
 expect(new Headers(post[1]!.headers).get('X-CSRF-Token')).toBe('slides-token')
 expect(JSON.parse(post[1]!.body as string)).toEqual({requestId:expect.any(String),expectedBinarySha256:sha})
 const links=document.querySelectorAll<HTMLAnchorElement>('.binary-refresh-result a');expect(links).toHaveLength(1);expect(links[0].getAttribute('href')).toBe('/actual.pptx')
 for(let element:Element|null=links[0];element;element=element.parentElement)expect(getComputedStyle(element).display).not.toBe('none')
 expect(document.querySelector('.binary-refresh-result')!.textContent).toContain('pptx_validation_failed')
 expect(document.querySelector('.binary-refresh-result')!.textContent).toContain('code_only')
})
it('flushes pending text, saves and stops, and preserves unregistered download without dispatching',async()=>{
 registered=false;await open()
 const field=document.querySelector<HTMLTextAreaElement>('#object-text')!
 field.value='unsaved';field.dispatchEvent(new Event('input',{bubbles:true}))
 action().click();await vi.waitFor(()=>expect(document.body.textContent).toContain('修订未登记'))
 expect(document.querySelector<HTMLAnchorElement>('[data-action=pptx-download]')?.getAttribute('href')).toBe('/saved.pptx')
 expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/recalculations'))).toBe(false)
})
it('restores cached task despite failed deck and unavailable capability, while sourceReusable never authorizes a new task',async()=>{
 await open();action().click();await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
 view!.dispose();view=undefined;window.dispatchEvent(new Event('pagehide'));document.body.innerHTML='<div id="app"></div>'
 capability=false;previewFails=true;await open()
 await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
 expect(action()).toBeNull();expect(document.body.textContent).toContain('deck missing')
})
