import {expect,it} from 'vitest'
const implementation='./workbook-formula-bar-view'
it('defaults visible and scopes the source hide class to its own workbook host',async()=>{
 const {createFormulaBarView}=await import(/* @vite-ignore */implementation)
 const host=document.createElement('div'),other=document.createElement('div');host.innerHTML='<div data-u-comp="formula-bar"><input value="=SUM(A1:A2)"></div>';other.innerHTML=host.innerHTML
 const control=createFormulaBarView(host)
 expect(control.visible()).toBe(true);expect(control.toggle()).toBe(false);expect(control.visible()).toBe(false)
 expect(host.classList.contains('workbook-formula-bar-hidden')).toBe(true);expect(other.className).toBe('');expect(host.querySelector('input')!.value).toBe('=SUM(A1:A2)')
 expect(control.toggle()).toBe(true);expect(host.className).toBe('');control.dispose()
})
it('keeps a late native formula bar hidden and releases view state without replacing its editor',async()=>{
 const {createFormulaBarView}=await import(/* @vite-ignore */implementation)
 const host=document.createElement('div'),control=createFormulaBarView(host);control.toggle()
 const bar=document.createElement('div');bar.dataset.uComp='formula-bar';bar.innerHTML='<div contenteditable="true">draft</div>';host.append(bar)
 expect(host.classList.contains('workbook-formula-bar-hidden')).toBe(true);expect(host.firstChild).toBe(bar)
 control.dispose();control.dispose();expect(host.className).toBe('');expect(host.firstChild).toBe(bar);expect(bar.textContent).toBe('draft')
 expect(control.toggle()).toBe(true);expect(host.className).toBe('')
})
it('preserves unrelated host classes and independent workbook controls',async()=>{
 const {createFormulaBarView}=await import(/* @vite-ignore */implementation)
 const first=document.createElement('div'),second=document.createElement('div');first.className='workbook-grid existing'
 const a=createFormulaBarView(first),b=createFormulaBarView(second);a.toggle();b.toggle();a.dispose()
 expect(first.className).toBe('workbook-grid existing');expect(b.visible()).toBe(false);expect(second.classList.contains('workbook-formula-bar-hidden')).toBe(true);b.dispose()
})
