import { expect, it } from 'vitest'
import { validateSlidesGroupDraft } from './slides-groups'
const slides=[{elements:[{id:'a',type:'text',groupEditable:true},{id:'b',type:'picture',groupEditable:true},{id:'c',type:'shape',groupEditable:true},{id:'g',type:'group',ungroupEditable:true}]},{elements:[{id:'other',type:'shape',groupEditable:true}]}]
const group={slideIndex:0,kind:'group',elementIds:['b','a']}
it('组合规范化来源顺序但不修改请求，允许另页修改和页面重排',()=>{
 const input={groupEdits:[group],edits:[{slideIndex:1,elementId:'other',text:'保留'}],order:[1,0]}
 expect(validateSlidesGroupDraft(input,slides)).toEqual([{slideIndex:0,kind:'group',elementIds:['a','b']}])
 expect(input.groupEdits[0]?.elementIds).toEqual(['b','a'])
})
it('恢复前拒绝未知重复非连续对象和同页重复组合',()=>{
 for(const records of [[{...group,elementIds:['a','unknown']}],[{...group,elementIds:['a','a']}],[{...group,elementIds:['a','c']}],[group,group]])
  expect(()=>validateSlidesGroupDraft({groupEdits:records},slides)).toThrow('组合')
})
it('同页其他编辑全批拒绝而不覆盖组合草稿',()=>{
 for(const change of [{edits:[{slideIndex:0,elementId:'a',text:'字'}]},{elementOrders:[{slideIndex:0,elementIds:['b','a','c','g']}]},{deletedSlides:[0]},{resetLayouts:[0]},{newSlides:[{duplicateOf:0}]},{slideSize:{cx:9144000,cy:5143500}},{theme:'executive'},{headerFooter:{footer:'页脚'}},{hiddenSlides:[{slideIndex:0,hidden:true}]}])
  expect(()=>validateSlidesGroupDraft({groupEdits:[group],...change},slides)).toThrow('组合')
})
it('取消组合只允许可安全拆解的单一来源组且字段严格',()=>{
 expect(validateSlidesGroupDraft({groupEdits:[{slideIndex:0,kind:'ungroup',elementId:'g'}]},slides)).toEqual([{slideIndex:0,kind:'ungroup',elementId:'g'}])
 expect(()=>validateSlidesGroupDraft({groupEdits:[{slideIndex:0,kind:'ungroup',elementId:'a'}]},slides)).toThrow('组合')
 expect(()=>validateSlidesGroupDraft({groupEdits:[{slideIndex:0,kind:'ungroup',elementId:'g',extra:true}]},slides)).toThrow('组合')
 expect(validateSlidesGroupDraft({},slides)).toEqual([])
})
