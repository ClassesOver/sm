import {afterEach,expect,it,vi} from 'vitest'
import {createSlidesNotesPane,validateSlidesNotesDraft} from './slides-notes'
const slides=[{notesText:'旧备注',notesEditable:true},{notesText:'',notesEditable:true},{notesEditable:false,notesReason:'复杂备注'}]
afterEach(()=>document.body.replaceChildren())
const view=(extra={})=>({slideIndex:0,text:'旧备注',editable:true,visible:true,...extra})
function input(node:HTMLTextAreaElement,text:string){node.value=text;node.dispatchEvent(new Event('input',{bubbles:true}))}
it('来源协议精确校验且规范化换行，保留空格与内部空行，不修改原草稿',()=>{
 const draft={notesEdits:[{slideIndex:0,text:' a\r\n\r\nb \r\n'}],edits:[{text:'保留'}]},before=structuredClone(draft)
 expect(validateSlidesNotesDraft(draft,slides)).toEqual([{slideIndex:0,text:' a\n\nb '}]);expect(draft).toEqual(before)
 expect(validateSlidesNotesDraft({},slides)).toEqual([])
 expect(validateSlidesNotesDraft({notesEdits:[{slideIndex:0,text:''}]},slides)).toEqual([{slideIndex:0,text:''}])
 for(const draft of [null,{notesEdits:null},{notesEdits:[{slideIndex:0,text:'a',extra:true}]},{notesEdits:[{slideIndex:true,text:'a'}]},{notesEdits:[{slideIndex:3,text:'a'}]},{notesEdits:[{slideIndex:2,text:'a'}]},{notesEdits:[{slideIndex:0,text:'a'},{slideIndex:0,text:'b'}]},{notesEdits:[{slideIndex:0,text:'a'}],deletedSlides:[0]},{notesEdits:[{slideIndex:0,text:'a'}],newSlides:[{duplicateOf:0}]}])expect(()=>validateSlidesNotesDraft(draft,slides)).toThrow()
})
it('限额按原始UTF16检查，拒绝非法控制字符、孤立代理与非字符',()=>{
 const edit=(text:string)=>({notesEdits:[{slideIndex:0,text}]})
 expect(validateSlidesNotesDraft(edit('😀'.repeat(10000)),slides)[0]!.text.length).toBe(20000)
 for(const text of ['x'.repeat(20001),'\n'.repeat(20001),String.fromCharCode(0),String.fromCharCode(11),String.fromCharCode(0xd800),String.fromCharCode(0xdc00),String.fromCharCode(0xfffe),String.fromCharCode(0xffff)])expect(()=>validateSlidesNotesDraft(edit(text),slides)).toThrow()
 const many=Array.from({length:201},(_,slideIndex)=>({slideIndex,text:''})),sources=many.map(()=>({notesEditable:true}))
 expect(()=>validateSlidesNotesDraft({notesEdits:many},sources)).toThrow()
 expect(()=>validateSlidesNotesDraft({notesEdits:many.slice(0,11).map(item=>({...item,text:'x'.repeat(20000)}))},sources)).toThrow()
 expect(validateSlidesNotesDraft(edit(' a\t\r\nb\r'),slides)[0]!.text).toBe(' a\t\nb')
})
it('普通输入同步提交且无op不回调，blur规范化不重建textarea',()=>{
 const onChange=vi.fn(),pane=createSlidesNotesPane(document.body,{onChange});pane.update(view())
 const node=document.querySelector<HTMLTextAreaElement>('.slides-notes-pane textarea')!
 expect(node.getAttribute('aria-label')).toBe('演讲者备注')
 input(node,'新备注\n\n');expect(onChange).toHaveBeenLastCalledWith(0,'新备注')
 node.setSelectionRange(1,1);pane.update(view({text:'新备注'}));expect(document.querySelector('textarea')).toBe(node);expect(node.value).toBe('新备注\n\n');expect(node.selectionStart).toBe(1)
 input(node,'新备注\n');expect(onChange).toHaveBeenCalledOnce()
 node.dispatchEvent(new Event('blur'));expect(node.value).toBe('新备注');expect(onChange).toHaveBeenCalledOnce();expect(pane.flush()).toBe(true)
})
it('IME只在结束提交，进行中flush和切页失败且保留输入',()=>{
 const onChange=vi.fn(),pane=createSlidesNotesPane(document.body,{onChange});pane.update(view())
 const node=document.querySelector<HTMLTextAreaElement>('textarea')!
 node.dispatchEvent(new CompositionEvent('compositionstart'));input(node,'输入中');expect(onChange).not.toHaveBeenCalled()
 expect(pane.flush()).toBe(false);expect(pane.update(view({slideIndex:1,text:'下一页'}))).toBe(false);expect(node.value).toBe('输入中')
 node.dispatchEvent(new CompositionEvent('compositionend'));expect(onChange).toHaveBeenCalledExactlyOnceWith(0,'输入中')
 expect(pane.update(view({slideIndex:1,text:'下一页'}))).toBe(true);expect(node.value).toBe('下一页')
})
it('提交失败保留内容与原因，阻止换页及折叠，修正后flush继续',()=>{
 let reject=true;const onChange=vi.fn(()=>{if(reject)throw Error('来源已变化')}),onError=vi.fn(),pane=createSlidesNotesPane(document.body,{onChange,onError});pane.update(view())
 const node=document.querySelector<HTMLTextAreaElement>('textarea')!;input(node,'待保留')
 expect(document.querySelector('[role=alert]')!.textContent).toBe('来源已变化');expect(onError).toHaveBeenCalledWith('来源已变化')
 expect(pane.update(view({slideIndex:1,text:'下一页'}))).toBe(false);expect(pane.setVisible(false)).toBe(false);expect(node.value).toBe('待保留')
 pane.update(view());expect(node.value).toBe('待保留');reject=false;expect(pane.flush()).toBe(true)
 expect(pane.update(view({slideIndex:1,text:'下一页'}))).toBe(true);expect(onChange).toHaveBeenLastCalledWith(0,'待保留')
})
it('flush补齐未收到input的内容，切页前提交绑定来源，外部undo可更新已提交基线',()=>{
 const onChange=vi.fn(),pane=createSlidesNotesPane(document.body,{onChange});pane.update(view())
 const node=document.querySelector<HTMLTextAreaElement>('textarea')!;node.value='最后输入'
 expect(pane.update(view({slideIndex:1,text:'页二'}))).toBe(true);expect(onChange).toHaveBeenLastCalledWith(0,'最后输入')
 pane.update(view({slideIndex:1,text:'撤销后的备注'}));expect(node.value).toBe('撤销后的备注')
})
it('只读来源纯文本展示原因，折叠可切换，销毁取消输入且旧事件无效',()=>{
 const onChange=vi.fn(),pane=createSlidesNotesPane(document.body,{onChange});pane.update(view({text:'<img src=x>',editable:false,reason:'复杂备注'}))
 const node=document.querySelector<HTMLTextAreaElement>('textarea')!;expect(node.readOnly).toBe(true);expect(node.value).toBe('<img src=x>');expect(document.querySelector('img')).toBeNull()
 input(node,'不写入');expect(onChange).not.toHaveBeenCalled();expect(document.querySelector('.slides-notes-pane')!.textContent).toContain('复杂备注')
 expect(pane.setVisible(false)).toBe(true);expect(node.hidden).toBe(true);expect(pane.setVisible(true)).toBe(true)
 pane.update(view());node.dispatchEvent(new CompositionEvent('compositionstart'));input(node,'未完成输入');pane.dispose();node.dispatchEvent(new CompositionEvent('compositionend'));input(node,'旧事件')
 expect(onChange).not.toHaveBeenCalled();expect(document.querySelector('.slides-notes-pane')).toBeNull();expect(pane.flush()).toBe(true)
})
it.each([
 ['notes_edit_master_registration_invalid','备注母版结构暂不支持编辑；可查看或复制现有备注。'],
 ['notes_edit_master_relationships_invalid','备注母版结构暂不支持编辑；可查看或复制现有备注。'],
 ['notes_edit_future_source_reason','此文件的备注结构暂不支持编辑；可查看或复制现有备注。'],
 ['复杂备注','复杂备注'],
 [null,'当前页面备注仅可读'],
])('只读原因%s展示可理解的提示且不改变备注或编辑能力',(reason,message)=>{
 const onChange=vi.fn(),pane=createSlidesNotesPane(document.body,{onChange})
 pane.update(view({text:'来源备注',editable:false,reason}))
 const node=document.querySelector<HTMLTextAreaElement>('textarea')!
 expect(document.querySelector('.slides-notes-reason')?.textContent).toBe(message)
 expect(node.readOnly).toBe(true);expect(node.value).toBe('来源备注');expect(onChange).not.toHaveBeenCalled()
 if(reason?.startsWith('notes_edit_'))expect(()=>validateSlidesNotesDraft({notesEdits:[{slideIndex:0,text:'不能覆盖'}]},[{notesEditable:false,notesReason:reason}])).toThrow(message!)
 pane.dispose()
})
it('备注只读提示关联输入框，多实例描述身份不混用',()=>{
 const panes=[0,1].map(slideIndex=>{
  const pane=createSlidesNotesPane(document.body,{onChange(){}})
  pane.update(view({slideIndex,editable:false,reason:'notes_edit_master_registration_invalid'}))
  return pane
 })
 const descriptions=[...document.querySelectorAll('textarea')].map(node=>{
  const id=node.getAttribute('aria-describedby')
  expect(id).toBeTruthy()
  const reason=document.getElementById(id!)
  expect(reason?.closest('.slides-notes-pane')).toBe(node.closest('.slides-notes-pane'))
  expect(reason?.textContent).toContain('备注母版')
  return id
 })
 expect(new Set(descriptions).size).toBe(2)
 panes.forEach(pane=>pane.dispose())
})
it('同步回调内旧视图刷新不覆盖输入，失败时不能切到只读状态',()=>{
 let reject=false
 const onChange=vi.fn(()=>{pane.update(view());if(reject)throw Error('拒绝写入')}),pane=createSlidesNotesPane(document.body,{onChange})
 pane.update(view());const node=document.querySelector<HTMLTextAreaElement>('textarea')!
 input(node,'同步文字');expect(node.value).toBe('同步文字');expect(onChange).toHaveBeenCalledOnce()
 reject=true;input(node,'保留错误输入')
 expect(pane.update(view({editable:false,reason:'锁定'}))).toBe(false)
 expect(node.readOnly).toBe(false);expect(node.value).toBe('保留错误输入');expect(pane.flush()).toBe(false)
})
it('已保存备注含原始换行时仅收尾显示不制造无变化回调',()=>{
 const onChange=vi.fn(),pane=createSlidesNotesPane(document.body,{onChange});pane.update(view({text:' a\r\n\r\nb \r\n'}))
 expect(pane.flush()).toBe(true);expect(onChange).not.toHaveBeenCalled();expect(document.querySelector('textarea')!.value).toBe(' a\n\nb ')
})
it('本地折叠实际变化才通知可见状态，提交失败和销毁后不通知',()=>{
 const onVisibleChange=vi.fn(),onChange=vi.fn(()=>{throw Error('备注不可提交')}),pane=createSlidesNotesPane(document.body,{onChange,onVisibleChange})
 pane.update(view());const toggle=document.querySelector<HTMLButtonElement>('.slides-notes-heading button')!,node=document.querySelector<HTMLTextAreaElement>('textarea')!
 expect(onVisibleChange).not.toHaveBeenCalled();toggle.click();expect(onVisibleChange).toHaveBeenCalledExactlyOnceWith(false)
 pane.update(view({visible:false}));expect(onVisibleChange).toHaveBeenCalledOnce();expect(node.hidden).toBe(true)
 pane.setVisible(true);expect(onVisibleChange).toHaveBeenLastCalledWith(true);onVisibleChange.mockClear()
 input(node,'不可提交');toggle.click();expect(onVisibleChange).not.toHaveBeenCalled();expect(node.hidden).toBe(false)
 pane.dispose();toggle.click();pane.setVisible(false);expect(onVisibleChange).not.toHaveBeenCalled()
})
it('提交回调重入只读或换页后抛错不会提交成功，失败输入仍可修正',()=>{
 for(const next of [view({editable:false}),view({slideIndex:1,text:'页二'})]){
  let reject=true
  const updates:boolean[]=[],recursive:boolean[]=[],onChange=vi.fn(()=>{
   updates.push(pane.update(next));recursive.push(pane.flush());if(reject)throw Error('存储失败')
  }),pane=createSlidesNotesPane(document.body,{onChange})
  pane.update(view());const node=document.querySelector<HTMLTextAreaElement>('[data-notes-text]')!
  input(node,'保留失败文字')
  expect(updates).toEqual([false]);expect(recursive).toEqual([false]);expect(node.readOnly).toBe(false);expect(node.value).toBe('保留失败文字')
  expect(document.querySelector('[role=alert]')!.textContent).toBe('存储失败');expect(pane.flush()).toBe(false)
  reject=false;input(node,'已修正');expect(onChange).toHaveBeenLastCalledWith(0,'已修正');expect(node.readOnly).toBe(false);expect(node.value).toBe('已修正');expect(pane.flush()).toBe(true)
  pane.dispose()
 }
})
