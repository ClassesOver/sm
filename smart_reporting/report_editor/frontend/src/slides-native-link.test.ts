import {afterEach,expect,it,vi} from 'vitest'
import {openSlidesLink,validateSlidesLinkDraft} from './slides-native-link'
const slides=[{elements:[{id:'a',type:'text',linkEditable:true},{id:'r',type:'group',linkEditable:false}]},{elements:[{id:'b',type:'picture',linkEditable:true}]}]
const edit={slideIndex:0,elementId:'a',target:{kind:'url' as const,url:' https://example.com/a?x=1&y=2 '}}
afterEach(()=>document.body.replaceChildren())
it('恢复前严格验证链接并返回独立canonical结果，允许URL/来源页/清除',()=>{
 expect(validateSlidesLinkDraft({linkEdits:[edit]},slides)).toEqual([{...edit,target:{kind:'url',url:edit.target.url.trim()}}])
 expect(edit.target.url.startsWith(' ')).toBe(true)
 for(const target of [{kind:'url',url:'mailto:a@example.com'},{kind:'slide',slideIndex:1},null])expect(validateSlidesLinkDraft({linkEdits:[{...edit,target}]},slides)).toHaveLength(1)
 expect(validateSlidesLinkDraft({},slides)).toEqual([])
})
it('拒绝危险URL、歧义schema、重复/只读/删除目标及来源复制组合冲突',()=>{
 for(const target of [{kind:'url',url:'javascript:alert(1)'},{kind:'url',url:'file:///tmp/x'},{kind:'url',url:'//example.com'},{kind:'url',url:'https://exa\nmple.com'},{kind:'url',url:'https://'},{kind:'url',url:'https://x/'+ 'x'.repeat(2048)},{kind:'url',url:'https://x',tooltip:'额外'},{kind:'slide',slideIndex:true},{kind:'slide',slideIndex:2},{kind:'action',action:'nextslide'},undefined])expect(()=>validateSlidesLinkDraft({linkEdits:[{...edit,target}]},slides)).toThrow()
 for(const changes of [null,{linkEdits:null},{linkEdits:[edit,edit]},{linkEdits:Array(51).fill(edit)},{linkEdits:[{...edit,extra:true}]},{linkEdits:[{...edit,elementId:'r'}]},{linkEdits:[{...edit,elementId:'missing'}]},{linkEdits:[edit],deletedSlides:[0]},{linkEdits:[{...edit,target:{kind:'slide',slideIndex:1}}],deletedSlides:[1]},{linkEdits:[edit],deletions:[{slideIndex:0,elementId:'a'}]},{linkEdits:[edit],groupEdits:[{slideIndex:0}]},{linkEdits:[edit],newSlides:[{duplicateOf:0}]}])expect(()=>validateSlidesLinkDraft(changes,slides)).toThrow()
})
it('拒绝全部C0/C1与反斜杠，合法u/0/7/f及百分号编码不被误伤',()=>{
 for(const code of [...Array.from({length:32},(_,i)=>i),...Array.from({length:33},(_,i)=>127+i),92])expect(()=>validateSlidesLinkDraft({linkEdits:[{...edit,target:{kind:'url',url:'https://example.com/a'+String.fromCharCode(code)+'z'}}]},slides)).toThrow()
 for(const value of ['https://u07f.example/a?u=007f&x=%20','http://example.com/','mailto:u07f@example.com'])expect(validateSlidesLinkDraft({linkEdits:[{...edit,target:{kind:'url',url:value}}]},slides)[0]!.target).toEqual({kind:'url',url:value})
})
it('URL/页面选择与移除使用原生对话框，成功关闭且恢复焦点',()=>{
 const focus=document.createElement('button');document.body.append(focus);focus.focus()
 const apply=vi.fn(),cancel=vi.fn(),editor=openSlidesLink(document.body,{elementLink:{kind:'url',url:'https://old.example/'},slides,onApply:apply,onCancel:cancel})
 document.querySelector<HTMLSelectElement>('[data-link-kind]')!.value='slide';document.querySelector('[data-link-kind]')!.dispatchEvent(new Event('change'))
 document.querySelector<HTMLSelectElement>('[data-link-slide]')!.value='1'
 document.querySelector<HTMLButtonElement>('[data-link-confirm]')!.click()
 expect(apply).toHaveBeenCalledWith({kind:'slide',slideIndex:1});expect(cancel).not.toHaveBeenCalled();expect(document.querySelector('dialog')).toBeNull();expect(document.activeElement).toBe(focus)
 editor.dispose()
 openSlidesLink(document.body,{elementLink:{kind:'url',url:'https://old.example/'},slides,onApply:apply,onCancel:cancel})
 document.querySelector<HTMLButtonElement>('[data-link-remove]')!.click();expect(apply).toHaveBeenLastCalledWith(null)
})
it('非法输入或onApply拒绝保留对话框和原因，取消/逃逸/过期按钮不提交',()=>{
 const apply=vi.fn(()=>{throw Error('来源已变化')}),cancel=vi.fn(),editor=openSlidesLink(document.body,{elementLink:null,slides,onApply:apply,onCancel:cancel})
 const confirm=document.querySelector<HTMLButtonElement>('[data-link-confirm]')!,url=document.querySelector<HTMLInputElement>('[data-link-url]')!
 url.value='javascript:bad';confirm.click();expect(apply).not.toHaveBeenCalled();expect(document.querySelector('[role=alert]')!.textContent).toBeTruthy()
 url.value='https://example.com/';confirm.click();expect(document.querySelector('[role=alert]')!.textContent).toBe('来源已变化');expect(document.querySelector('dialog')).not.toBeNull()
 document.querySelector('dialog')!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(cancel).toHaveBeenCalledOnce();expect(document.querySelector('dialog')).toBeNull()
 const count=apply.mock.calls.length;confirm.click();editor.dispose();expect(apply).toHaveBeenCalledTimes(count);expect(cancel).toHaveBeenCalledOnce()
})
