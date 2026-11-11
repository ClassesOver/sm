import {expect,it,vi} from 'vitest'
import {mountWorkbookRibbon} from './workbook-ribbon'
it('binds readonly protected error checking and tracks availability and pending state',()=>{
 let available=true,pending=false;const command=vi.fn(),ribbon=mountWorkbookRibbon(document.body,command,{editable:()=>false,rotation:()=>undefined,protection:()=>({sheet:{protected:true},workbook:{locked:true}}),errorChecking:()=>({available,pending})})
 try{
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Formulas"]')!.click()
  const button=document.querySelector<HTMLButtonElement>('[data-ribbon-command="error-checking"]')!
  expect(button).not.toBeNull();expect(button.disabled).toBe(false);button.click();expect(command).toHaveBeenCalledWith('error-checking')
  pending=true;ribbon.refreshState();expect(button.disabled).toBe(true);expect(button.getAttribute('aria-busy')).toBe('true')
  pending=false;available=false;ribbon.refreshState();expect(button.disabled).toBe(true);expect(button.title).toMatch(/尚未就绪/)
 }finally{ribbon.dispose();document.body.replaceChildren()}
})
