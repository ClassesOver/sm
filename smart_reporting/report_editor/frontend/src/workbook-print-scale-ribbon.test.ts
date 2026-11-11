import {expect,it,vi}from'vitest'
import {mountWorkbookRibbon}from'./workbook-ribbon'
it('binds independent print scale and follows editable and protected page setup guards',()=>{
 let editable=true,protectedSheet=false;const command=vi.fn(),ribbon=mountWorkbookRibbon(document.body,command,{editable:()=>editable,rotation:()=>undefined,hasSelection:()=>true,protection:()=>({sheet:{protected:protectedSheet},workbook:{locked:false}})})
 try{document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Page Layout"]')!.click();const button=document.querySelector<HTMLButtonElement>('[data-ribbon-command="print-scale-open"]')!;expect(button).not.toBeNull();expect(button.textContent).toMatch(/打印缩放/);button.click();expect(command).toHaveBeenCalledWith('print-scale-open');protectedSheet=true;ribbon.refreshState();expect(button.disabled).toBe(true);protectedSheet=false;editable=false;ribbon.refreshState();expect(button.disabled).toBe(true)}finally{ribbon.dispose();document.body.replaceChildren()}
})
