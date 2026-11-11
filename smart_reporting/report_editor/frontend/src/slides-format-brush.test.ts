import { expect, it } from 'vitest'
import { captureSlidesBrush, planSlidesBrushApply, type BrushElement } from './slides-format-brush'

const source: BrushElement = {slideIndex:0,id:'source',type:'shape',editable:true,text:'源',brushSource:{supported:true,text:{bold:false,fontSizePt:18},align:'center',shape:{fill:'#123456',stroke:{color:'#222222',widthPt:2}}}}
const target: BrushElement = {...source,slideIndex:1,id:'target',text:'保留正文',brushSource:{supported:true,text:{bold:true,fontSizePt:12},align:'left',shape:{fill:'none'}}}
it('捕获明确字段并叠加待保存格式，不引入UI默认或删除线',()=>{
 const draft={textFormatting:[{slideIndex:0,elementId:'source',italic:false,strike:true}],shapeStyles:[{slideIndex:0,elementId:'source',stroke:null}],paragraphFormatting:[{slideIndex:0,elementId:'source',align:'right' as const}]}
 expect(captureSlidesBrush(source,draft)).toEqual({brush:{text:{bold:false,fontSizePt:18,italic:false},align:'right',shape:{fill:'#123456',stroke:null}},issues:[]})
 expect(captureSlidesBrush({...source,brushSource:{supported:true}},{}).brush).toBeNull()
})
it('三类结果原子合并，保留文字其他页与历史记录，不修改输入',()=>{
 const brush=captureSlidesBrush(source,{}).brush!
 const draft={edits:[{slideIndex:1,elementId:'target',text:'已改正文'}],order:[1,0],textFormatting:[{slideIndex:1,elementId:'target',strike:true}],paragraphFormatting:[{slideIndex:1,elementId:'target',spaceBeforePt:5}],shapeStyles:[{slideIndex:1,elementId:'target',stroke:null}],custom:'保留'}
 const before=JSON.stringify(draft),plan=planSlidesBrushApply(brush,target,draft)
 expect(plan.changed).toBe(true);expect(JSON.stringify(draft)).toBe(before)
 expect(plan.changes.edits).toEqual(draft.edits);expect(plan.changes.order).toEqual([1,0]);expect(plan.changes.custom).toBe('保留')
 expect(plan.changes.textFormatting).toEqual([{slideIndex:1,elementId:'target',strike:true,bold:false,fontSizePt:18}])
 expect(plan.changes.paragraphFormatting).toEqual([...draft.paragraphFormatting,{slideIndex:1,elementId:'target',align:'center'}])
 expect(plan.changes.shapeStyles).toEqual([{slideIndex:1,elementId:'target',stroke:{color:'#222222',widthPt:2},fill:'#123456'}])
 expect(planSlidesBrushApply(brush,target,plan.changes).changed).toBe(false)
})
it('空文字目标只接收形状样式，拒绝图片、删除和组合冲突',()=>{
 const brush=captureSlidesBrush(source,{}).brush!
 expect(planSlidesBrushApply(brush,{...target,text:''},{}).changes).toEqual({shapeStyles:[{slideIndex:1,elementId:'target',...brush.shape}]})
 for(const [element,draft] of [[{...target,type:'picture'},{}],[target,{deletions:[{slideIndex:1,elementId:'target'}]}],[target,{groupEdits:[{slideIndex:1}]}]] as const){
  const plan=planSlidesBrushApply(brush,element,draft);expect(plan.changed).toBe(false);expect(plan.issues.length).toBeGreaterThan(0)
 }
})
it('混合段落对齐不冒充首段，未知来源不从首run或render猜格式',()=>{
 expect(captureSlidesBrush({...source,brushSource:{supported:true},paragraphFormatting:[{align:'left'},{align:'right'}]},{}).brush).toBeNull()
 expect(captureSlidesBrush({...source,brushSource:undefined},{}).brush).toBeNull()
})
it('正文目标以当前草稿为准，删除正文后不再刷文字字段',()=>{
 const brush=captureSlidesBrush(source,{}).brush!
 const added={edits:[{slideIndex:1,elementId:'target',text:'新增正文'}]}
 expect(planSlidesBrushApply(brush,{...target,text:''},added).changes.textFormatting).toBeDefined()
 const removed={edits:[{slideIndex:1,elementId:'target',text:''}]}
 const changes=planSlidesBrushApply(brush,target,removed).changes
 expect(changes.textFormatting).toBeUndefined();expect(changes.paragraphFormatting).toBeUndefined()
})
it('达到段落预算后整批拒绝，不留下形状或文字半批结果',()=>{
 const draft={paragraphFormatting:Array.from({length:500},()=>({slideIndex:0,elementId:'other',align:'left' as const}))}
 const result=planSlidesBrushApply(captureSlidesBrush(source,{}).brush!,target,draft)
 expect(result.changed).toBe(false);expect(result.changes).toBe(draft);expect(result.issues).toHaveLength(1)
})
