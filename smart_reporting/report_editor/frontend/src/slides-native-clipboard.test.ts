import {expect,it} from 'vitest'
import {captureSlidesClipboard,planSlidesClipboardPaste,validateSlidesClipboardDraft} from './slides-native-clipboard'
const sha='a'.repeat(64),slides=[{elements:['a','b','c'].map(id=>({id,type:'text',clipboardEditable:true}))},{elements:[{id:'x',type:'picture',clipboardEditable:true}]}]
const record={sourceSlideIndex:0,elementIds:['c','a'],slideIndex:1,dx:20,dy:20}
it('来源集合canonical化且不改输入，剪切删除允许恢复，copy buffer不携带XML',()=>{
 const before=structuredClone(record)
 expect(validateSlidesClipboardDraft({clipboardPastes:[record],deletions:[{slideIndex:0,elementId:'a'}]},slides)[0]!.elementIds).toEqual(['a','c'])
 const buffer=captureSlidesClipboard(sha,0,['c','a'],{},slides)
 expect(buffer).toEqual({sourceSha256:sha,sourceSlideIndex:0,elementIds:['a','c']})
 expect(planSlidesClipboardPaste(buffer,sha,1,20,20,{deletions:[{slideIndex:0,elementId:'a'}]},slides)).toEqual([{...record,elementIds:['a','c']}])
 expect(record).toEqual(before)
})
it('copy只接受无待保存内容的来源页，paste拒绝过期SHA但允许其他页内容',()=>{
 for(const changes of [{edits:[{slideIndex:0,elementId:'a',text:'变更'}]},{deletions:[{slideIndex:0,elementId:'a'}]},{clipboardPastes:[{...record,slideIndex:0}]}])expect(()=>captureSlidesClipboard(sha,0,['a'],changes,slides)).toThrow()
 const buffer=captureSlidesClipboard(sha,0,['a'],{edits:[{slideIndex:1,elementId:'x',text:'另页'}]},slides)
 expect(()=>planSlidesClipboardPaste(buffer,'b'.repeat(64),1,20,20,{},slides)).toThrow()
 expect(planSlidesClipboardPaste(buffer,sha,1,20,20,{edits:[{slideIndex:1,elementId:'x',text:'另页'}]},slides)).toHaveLength(1)
})
it('draft拒绝外部schema、无效/重复/只读目标、数量和位移，涉及页结构修改互斥',()=>{
 expect(validateSlidesClipboardDraft({},slides)).toEqual([])
 for(const value of [null,{},[null],[{...record,xml:'bad'}],[{...record,elementIds:[]}],[{...record,elementIds:['a','a']}],[{...record,elementIds:['a','unknown']}],[{...record,sourceSlideIndex:true}],[{...record,slideIndex:99}],[{...record,dx:Infinity}],Array(51).fill(record)])expect(()=>validateSlidesClipboardDraft({clipboardPastes:value},slides)).toThrow()
 for(const changes of [{theme:'modern'},{slideSize:{}},{headerFooter:{}},{deletedSlides:[0]},{resetLayouts:[1]},{slideLayouts:[{slideIndex:0}]},{groupEdits:[{slideIndex:1}]},{newSlides:[{duplicateOf:0}]}])expect(()=>validateSlidesClipboardDraft({...changes,clipboardPastes:[record]},slides)).toThrow()
 expect(()=>validateSlidesClipboardDraft({clipboardPastes:[record]},[{elements:[{id:'a',type:'text',clipboardEditable:false}]},slides[1]!])).toThrow()
})
it('连续粘贴只追加引用操作，buffer与既有draft不变；总对象上限500',()=>{
 const buffer=captureSlidesClipboard(sha,0,['a'],{},slides),changes={clipboardPastes:[record]},before=structuredClone(changes)
 expect(planSlidesClipboardPaste(buffer,sha,0,40,40,changes,slides)).toHaveLength(2)
 expect(changes).toEqual(before)
 const many=Array.from({length:50},()=>({...record,elementIds:Array.from({length:11},(_,i)=>String(i))}))
 expect(()=>validateSlidesClipboardDraft({clipboardPastes:many},slides)).toThrow()
})
it('跨页可用母版或主题metadata不一致时提前拒绝，缺失metadata交后端核验',()=>{
 const mismatched=slides.map((slide,i)=>({...slide,masterPath:i?'m2':'m1',themePath:'t1'}))
 expect(()=>validateSlidesClipboardDraft({clipboardPastes:[record]},mismatched)).toThrow()
 const differentTheme=slides.map((slide,i)=>({...slide,masterPath:'m1',themePath:i?'t2':'t1'}))
 expect(()=>validateSlidesClipboardDraft({clipboardPastes:[record]},differentTheme)).toThrow()
 expect(validateSlidesClipboardDraft({clipboardPastes:[record]},slides)).toHaveLength(1)
})
