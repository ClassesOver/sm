import {expect,it,vi} from 'vitest'
const modulePath='./workbook-external-links'
const row={index:1,rawTarget:'file:///private/source.xlsx',source:'file:///private/source.xlsx',sheetNames:['Data'],part:'xl/externalLinks/externalLink1.xml',relsPart:'xl/externalLinks/_rels/externalLink1.xml.rels'}
async function setup(){
 document.body.innerHTML='<main></main>';const host=document.querySelector('main')!,apply=vi.fn(),locate=vi.fn(),update=vi.fn(async()=>({message:'更新 1 个值；1 个未更新：未授权'}));let writable=true,current='one'
 const {createWorkbookExternalLinks}=await import(/* @vite-ignore */modulePath)
 const panel=createWorkbookExternalLinks(host,{capture:async()=>({key:current,links:[row],bindings:[]}),current:(key:string)=>key===current,editable:()=>writable,apply,locate,update,pick:async()=>null})
 await panel.open();return{host,panel,apply,locate,update,readonly:()=>{writable=false},stale:()=>{current='two'}}
}
it('lists without probing and exposes update locate source change and two-stage break',async()=>{
 const c=await setup();try{
 expect(c.host.textContent).toContain('file:///private/source.xlsx');expect(c.host.querySelector('[data-external-status]')?.textContent).toBe('未检查')
 expect(c.locate).not.toHaveBeenCalled();(c.host.querySelector('[data-external-break]') as HTMLButtonElement).click();expect(c.apply).not.toHaveBeenCalled()
 expect(c.host.querySelector('[data-external-break-confirm]')).not.toBeNull();(c.host.querySelector('[data-external-break-cancel]') as HTMLButtonElement).click();expect(c.apply).not.toHaveBeenCalled()
 expect(c.host.querySelector('[data-external-change]')).not.toBeNull();expect(c.host.querySelector('[data-external-locate]')).not.toBeNull()
 }finally{c.panel.dispose()}
})
it.each(['readonly','stale'] as const)('rejects late destructive callback after %s',async fault=>{
 const c=await setup();try{(c.host.querySelector('[data-external-break]') as HTMLButtonElement).click();c[fault]();(c.host.querySelector('[data-external-break-confirm]') as HTMLButtonElement).click();await vi.waitFor(()=>expect(c.host.textContent).toMatch(/变化|编辑/));expect(c.apply).not.toHaveBeenCalled()}finally{c.panel.dispose()}
})
it('reports actual update warnings and treats cancelled file selection as no edit',async()=>{
 const c=await setup();try{(c.host.querySelector('[data-external-change]') as HTMLButtonElement).click();await vi.waitFor(()=>expect((c.host.querySelector('[data-external-update]') as HTMLButtonElement).disabled).toBe(false));expect(c.apply).not.toHaveBeenCalled();(c.host.querySelector('[data-external-update]') as HTMLButtonElement).click();await vi.waitFor(()=>expect(c.host.textContent).toContain('1 个未更新'));expect(c.update).toHaveBeenCalledTimes(1)}finally{c.panel.dispose()}
})
it('does not apply a selected file after the panel is closed while reading it',async()=>{
 document.body.innerHTML='<main></main>';const {createWorkbookExternalLinks}=await import(/* @vite-ignore */modulePath),apply=vi.fn();let resolve!:(value:ArrayBuffer)=>void
 const file={name:'source.xlsx',size:4,arrayBuffer:()=>new Promise<ArrayBuffer>(done=>{resolve=done})} as File
 const panel=createWorkbookExternalLinks(document.querySelector('main')!,{capture:async()=>({key:'one',links:[row],bindings:[]}),current:()=>true,editable:()=>true,apply,locate:async()=>'',update:async()=>({message:''}),pick:async()=>file})
 await panel.open();(document.querySelector('[data-external-change]') as HTMLButtonElement).click();await vi.waitFor(()=>expect(resolve).toBeTypeOf('function'));panel.close();resolve(new Uint8Array([1,2,3,4]).buffer);await new Promise(done=>setTimeout(done,0));expect(apply).not.toHaveBeenCalled();panel.dispose()
})
it('dispatches the full external links panel from the actual Formula ribbon command',async()=>{
 const {mountWorkbookRibbon}=await import('./workbook-ribbon'),onCommand=vi.fn(),ribbon=mountWorkbookRibbon(document.body,onCommand,{editable:()=>true,rotation:()=>0})
 try{(document.querySelector('[data-ribbon-tab="Formulas"]') as HTMLButtonElement).click();const button=document.querySelector('[data-ribbon-command="external-links-panel"]') as HTMLButtonElement;expect(button).not.toBeNull();expect(button.disabled).toBe(false);button.click();expect(onCommand).toHaveBeenCalledWith('external-links-panel')}finally{ribbon.dispose()}
},15000)
