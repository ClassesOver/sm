import { expect, it, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { act, createElement } from 'react'
import { installWorkbookZoomDialogLauncher } from './workbook-zoom-launcher'
it('uses official component/menu registration and disposes commands and stale callbacks',async()=>{
 const registrations:any[]=[],schemas:any[]=[],subscription={dispose:vi.fn()};let onCommand=()=>{},zoom=1
 const components={register:vi.fn((id,component)=>{registrations.push({id,component});return{dispose:vi.fn()}})}
 const commandService={registerCommand:vi.fn(()=>({dispose:vi.fn()}))}
 const menus={mergeMenu:vi.fn(value=>schemas.push(value))},command=vi.fn(),host=document.createElement('div');document.body.append(host)
 let index=0;const runtime={univer:{__getInjector:()=>({has:()=>true,get:()=>{const i=index++;return i===0?components:i===1?menus:commandService}})},univerAPI:{getActiveWorkbook:()=>({getActiveSheet:()=>({getZoom:()=>zoom})}),onCommandExecuted:(callback:()=>void)=>{onCommand=callback;return subscription}}}
 const handle=installWorkbookZoomDialogLauncher(runtime,host,command)
 const root=createRoot(host)
 try{
  expect(schemas).toHaveLength(1);await act(async()=>root.render(createElement(registrations[0].component)))
  const buttons=host.querySelectorAll('button');expect([...buttons].map(b=>b.textContent)).toEqual(['−','+','100%'])
  buttons[2].click();buttons[1].click();expect(command).toHaveBeenCalledWith('zoom-open');expect(command).toHaveBeenCalledWith('zoom-in')
  zoom=4;await act(async()=>onCommand());expect(host.querySelectorAll('button')[1].disabled).toBe(true)
  handle.dispose();buttons[2].click();expect(command).toHaveBeenCalledTimes(2)
 }finally{await act(async()=>root.unmount());host.remove();handle.dispose()}
 expect(subscription.dispose).toHaveBeenCalledTimes(1)
})
it('leaves headless runtimes unchanged without resolving absent UI services',()=>{
 const get=vi.fn();const handle=installWorkbookZoomDialogLauncher({univer:{__getInjector:()=>({has:()=>false,get})}},document.createElement('div'),vi.fn())
 handle.dispose();expect(get).not.toHaveBeenCalled()
})

it('supports hosts without an injector method and individually missing official UI services',()=>{
 for(const has of [undefined,()=>false,(()=>{let calls=0;return()=>++calls===1})()]) {
  const get=vi.fn();const r=has?{univer:{__getInjector:()=>({has,get})}}:{}
  const handle=installWorkbookZoomDialogLauncher(r,document.createElement('div'),vi.fn());handle.refresh();handle.dispose()
  expect(get).not.toHaveBeenCalled()
 }
})
