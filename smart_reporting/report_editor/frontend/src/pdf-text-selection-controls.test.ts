import {expect,it} from 'vitest'
import {bindPdfReplacementStyle} from './pdf-replace-text-style'
function fixture(){const root=document.createElement('section'),text=document.createElement('textarea');text.setAttribute('aria-label','替换后的文字');text.value='AABBCC';root.append(text);document.body.append(root);const panel=bindPdfReplacementStyle(root);return {root,text,panel,dispose(){panel.dispose();root.remove()}}}
const run={start:2,end:4,font:'times',size:18,color:[1,0,0],bold:false,italic:true}
it('whole draft field changes clear only corresponding selection overrides and preserve selection',()=>{
 const f=fixture(),{root,text,panel}=f
 try{for(const [label,value,event,field]of [['字体','courier','change','font'],['字号','24','input','size'],['粗体',true,'change','bold'],['斜体',true,'change','italic'],['颜色','#00ff00','input','color'],['指定颜色',false,'change','color']] as const){
  panel.fill({kind:'replaceText',newText:text.value,styleRuns:[run]});text.focus();text.setSelectionRange(2,4,'backward');text.dispatchEvent(new Event('select'))
  const control=root.querySelector<HTMLInputElement>('[aria-label="替换文字'+label+'"]')!;if(typeof value==='boolean')control.checked=value;else control.value=value;control.dispatchEvent(new Event(event,{bubbles:true}))
  const expected:Record<string,unknown>={...run};delete expected[field];expect(panel.read().styleRuns).toEqual([expected]);expect([text.selectionStart,text.selectionEnd,text.selectionDirection]).toEqual([2,4,'backward'])
 }
 panel.fill({kind:'replaceText',newText:text.value,styleRuns:[run]});for(const label of ['对齐','行距']){const control=root.querySelector<HTMLInputElement>('[aria-label="替换文字'+label+'"]')!;control.value=label==='对齐'?'right':'30';control.dispatchEvent(new Event('change',{bubbles:true}))}expect(panel.read().styleRuns).toEqual([run])
 }finally{f.dispose()}
})
it('keyboard and selectionchange report uniform mixed and inherited fields without mutating runs',()=>{
 const f=fixture(),{root,text,panel}=f
 try{panel.fill({kind:'replaceText',newText:text.value,styleRuns:[run]});text.focus();text.setSelectionRange(2,4,'backward');text.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowRight',shiftKey:true}))
  const current=root.querySelector<HTMLElement>('[data-pdf-selection-style-current]')!;expect(current).not.toBeNull();expect(current.dataset.font).toBe('times');expect(current.dataset.size).toBe('18');expect(current.dataset.bold).toBe('false');expect(current.dataset.italic).toBe('true');expect(current.dataset.color).toBe('#ff0000')
  text.setSelectionRange(1,5);document.dispatchEvent(new Event('selectionchange'));expect(current.dataset.font).toBe('mixed');expect(current.textContent).toContain('混合');expect(panel.read().styleRuns).toEqual([run])
  text.setSelectionRange(0,2);text.dispatchEvent(new Event('select'));expect(current.dataset.font).toBe('inherit');expect(current.textContent).toContain('继承整对象')
  text.setSelectionRange(1,1);text.dispatchEvent(new Event('select'));expect(current.textContent).toContain('未选择字符');expect(root.querySelector<HTMLButtonElement>('[data-pdf-selection-style-apply]')!.disabled).toBe(true)
 }finally{f.dispose()}
})
it('clearing a keyboard selection removes only that range and restores focus and direction',()=>{
 const f=fixture(),{root,text,panel}=f
 try{panel.fill({kind:'replaceText',newText:text.value,styleRuns:[{...run,start:0,end:6}]});text.focus();text.setSelectionRange(2,4,'backward');text.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowLeft',shiftKey:true}));root.querySelector<HTMLButtonElement>('[data-pdf-selection-style-clear]')!.click()
  expect(panel.read().styleRuns).toEqual([{...run,start:0,end:2},{...run,start:4,end:6}]);expect([text.selectionStart,text.selectionEnd,text.selectionDirection,document.activeElement===text]).toEqual([2,4,'backward',true]);expect(root.querySelector<HTMLElement>('[data-pdf-selection-style-current]')!.dataset.font).toBe('inherit')
 }finally{f.dispose()}
})
it('whole draft changes clear that field across every range and drop empty runs',()=>{
 const f=fixture(),{root,text,panel}=f
 try{panel.fill({kind:'replaceText',newText:text.value,styleRuns:[{start:0,end:2,font:'times'},{start:4,end:6,font:'arial'}]});text.focus();text.setSelectionRange(2,2);text.dispatchEvent(new Event('select'));const font=root.querySelector<HTMLSelectElement>('[aria-label="替换文字字体"]')!;font.value='courier';font.dispatchEvent(new Event('change',{bubbles:true}));expect(panel.read()).toEqual({font:'courier'});expect(root.querySelector<HTMLElement>('[data-pdf-selection-style-current]')!.textContent).toContain('未选择字符')
 }finally{f.dispose()}
})
