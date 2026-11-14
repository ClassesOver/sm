import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {openSlidesPrintDialog,type SlidesPrintSnapshot} from './slides-print-dialog'
const snapshot:SlidesPrintSnapshot={ratio:16/9,current:1,slides:[{src:'data:image/png;base64,QQ==',notes:'one',hidden:false},{src:'data:image/png;base64,Qg==',notes:'<script>two</script>',hidden:true},{src:'data:image/png;base64,Qw==',notes:'three',hidden:false}]}
beforeEach(()=>{HTMLDialogElement.prototype.showModal=function(){this.open=true};HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new Event('close'))}})
afterEach(()=>{document.querySelectorAll<HTMLDialogElement>('dialog').forEach(dialog=>dialog.close());document.body.replaceChildren();vi.restoreAllMocks()})
async function fixture(load:(_:AbortSignal)=>Promise<SlidesPrintSnapshot>=async()=>snapshot){const root=document.body.appendChild(document.createElement('div')),opener=root.appendChild(document.createElement('button'));opener.focus();let current=true;const control=openSlidesPrintDialog(root,{load,isCurrent:()=>current});await vi.waitFor(()=>expect(root.querySelector('[role=status]')?.textContent).not.toContain('读取'));const dialog=root.querySelector<HTMLDialogElement>('dialog')!,frame=dialog.querySelector<HTMLIFrameElement>('iframe')!;return {root,opener,control,dialog,frame,stale:()=>{current=false}}}
function choose(dialog:HTMLElement,label:string,value:string){const select=dialog.querySelector<HTMLSelectElement>(`select[aria-label="${label}"]`)!;select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}))}
function checked(dialog:HTMLElement,label:string){const input=dialog.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;input.checked=!input.checked;input.dispatchEvent(new Event('change',{bubbles:true}))}
function preview(frame:HTMLIFrameElement){return new DOMParser().parseFromString(frame.srcdoc,'text/html')}
it('prints selected visible draft slides and uses source handout/notes layouts with escaped notes',async()=>{
 const f=await fixture();expect([...preview(f.frame).images].map(image=>image.getAttribute('src'))).toEqual(['data:image/png;base64,QQ==','data:image/png;base64,Qw=='])
 choose(f.dialog,'打印范围','current');expect(f.dialog.querySelector('[role=alert]')?.textContent).toContain('没有')
 checked(f.dialog,'打印隐藏幻灯片');choose(f.dialog,'打印布局','notes')
 expect(preview(f.frame).querySelectorAll('.page.notes')).toHaveLength(1);expect(preview(f.frame).querySelector('.note')?.textContent).toBe('<script>two</script>');expect(preview(f.frame).querySelector('script')).toBeNull()
 choose(f.dialog,'打印范围','custom');const range=f.dialog.querySelector<HTMLInputElement>('[aria-label="打印页码"]')!;range.value='3,1-2,2';range.dispatchEvent(new Event('input',{bubbles:true}));choose(f.dialog,'打印布局','handout2')
 expect(preview(f.frame).querySelectorAll('.page.handout')).toHaveLength(2);expect([...preview(f.frame).images].map(image=>image.getAttribute('src'))).toEqual(snapshot.slides.map(slide=>slide.src))
 choose(f.dialog,'纸张方向','landscape');expect(f.frame.srcdoc).toContain('size: 11.69in 8.27in');expect(f.dialog.querySelector('[role=status]')?.textContent).toContain('2')
})
it('rejects invalid/empty ranges and stale snapshots before calling system print',async()=>{
 const f=await fixture();const button=f.dialog.querySelector<HTMLButtonElement>('[data-slides-print-confirm]')!
 choose(f.dialog,'打印范围','custom');const range=f.dialog.querySelector<HTMLInputElement>('[aria-label="打印页码"]')!;range.value='3-1';range.dispatchEvent(new Event('input',{bubbles:true}));button.click();expect(f.dialog.querySelector('[data-slides-print-job]')).toBeNull();expect(f.dialog.querySelector('[role=alert]')?.textContent).toContain('页码')
 range.value='1';range.dispatchEvent(new Event('input',{bubbles:true}));expect(button.disabled).toBe(false);button.click();const job=f.dialog.querySelector<HTMLIFrameElement>('[data-slides-print-job]')!,print=vi.spyOn(job.contentWindow!,'print').mockImplementation(()=>{});vi.spyOn(job.contentWindow!,'focus').mockImplementation(()=>{});expect(job.srcdoc).not.toContain('counter-reset: pg');job.dispatchEvent(new Event('load'));await vi.waitFor(()=>expect(print).toHaveBeenCalledOnce())
 f.stale();button.click();await vi.waitFor(()=>expect(f.dialog.querySelector('[role=alert]')?.textContent).toContain('变化'));expect(print).toHaveBeenCalledOnce()
 f.control.dispose();expect(document.activeElement).toBe(f.opener)
})
it('aborts loading on close and never attaches late content after disposal',async()=>{
 let signal:AbortSignal|undefined,resolve!:(value:SlidesPrintSnapshot)=>void;const root=document.body.appendChild(document.createElement('div'));const ctl=openSlidesPrintDialog(root,{isCurrent:()=>true,load:current=>{signal=current;return new Promise(done=>{resolve=done})}});ctl.dispose();expect(signal?.aborted).toBe(true);resolve(snapshot);await Promise.resolve();expect(root.querySelector('dialog')).toBeNull()
})
it('releases image cancellation listeners after load and aborts an unfinished print job on close',async()=>{
 const f=await fixture(),add=vi.spyOn(AbortSignal.prototype,'addEventListener'),remove=vi.spyOn(AbortSignal.prototype,'removeEventListener');f.dialog.querySelector<HTMLButtonElement>('[data-slides-print-confirm]')!.click()
 const job=f.dialog.querySelector<HTMLIFrameElement>('[data-slides-print-job]')!,image=job.contentDocument!.createElement('img');Object.defineProperty(image,'complete',{value:false});job.contentDocument!.body.append(image)
 const print=vi.spyOn(job.contentWindow!,'print').mockImplementation(()=>{});vi.spyOn(job.contentWindow!,'focus').mockImplementation(()=>{});job.dispatchEvent(new Event('load'))
 const registration=add.mock.calls.find(call=>call[0]==='abort')!;expect(registration).toBeDefined();image.dispatchEvent(new Event('load'));await vi.waitFor(()=>expect(print).toHaveBeenCalledOnce());expect(remove).toHaveBeenCalledWith('abort',registration[1])
 f.dialog.querySelector<HTMLButtonElement>('[data-slides-print-confirm]')!.click();const unfinished=f.dialog.querySelector<HTMLIFrameElement>('[data-slides-print-job]')!,pending=unfinished.contentDocument!.createElement('img');Object.defineProperty(pending,'complete',{value:false});unfinished.contentDocument!.body.append(pending);unfinished.dispatchEvent(new Event('load'));f.control.dispose();await Promise.resolve();expect(document.querySelector('[data-slides-print-job]')).toBeNull()
})
it('fits the preview page to the available pane width',async()=>{
 const f=await fixture();Object.defineProperty(f.frame,'clientWidth',{value:400});const page=f.frame.contentDocument!.createElement('div');page.className='page';page.getBoundingClientRect=()=>new DOMRect(0,0,1000,600);f.frame.contentDocument!.body.append(page);f.frame.dispatchEvent(new Event('load'));expect(Number(f.frame.contentDocument!.body.style.zoom)).toBeCloseTo(.356)
})
