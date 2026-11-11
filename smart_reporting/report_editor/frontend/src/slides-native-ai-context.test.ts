import {expect,it} from 'vitest'
import {slidesAIObjects} from './slides-native-ai-context'
const elements=[{id:'table',name:'经营表',text:'',type:'table',editable:false,tableCells:[['收入','42'],[null,'费用']]},{id:'chart',name:'经营图',text:'',type:'chart',editable:false,chartEditSafe:true,chartKind:'bar' as const,chartCategories:['本期'],chartSeries:[{name:'收入',values:[42]}]},{id:'private',name:'未授权',text:'秘密',type:'shape',editable:true,geometry:{}},{id:'unsafe',name:'只读图',text:'',type:'chart',editable:false,chartEditSafe:false,chartCategories:['秘密类别']}]
const slides=[{slideIndex:0,elements}]
it('当前真实多选只授权表格及安全图表，未选择不回退邻居',()=>{
 const result=slidesAIObjects(slides,[],'object',0,new Set(['table','chart','unsafe']))
 expect(result.map(o=>o.elementId)).toEqual(['table','chart']);expect(JSON.stringify(result)).not.toContain('秘密')
 expect(result[0].tableCells?.[1][0]).toBeNull();expect(slidesAIObjects(slides,[],'object',0,new Set())).toEqual([])
})
it('before预览来自当前单元格和图表草稿，保留真实表格不可写格',()=>{
 const result=slidesAIObjects(slides,[{kind:'editSlides',tableCells:[{slideIndex:0,elementId:'table',row:0,col:1,text:'73'}],chartEdits:[{slideIndex:0,elementId:'chart',categories:['草稿本期'],series:[{name:'收入',values:[73]}]}]}],'object',0,new Set(['table','chart']))
 expect(result[0].tableCells?.[0][1]).toBe('73');expect(result[1].chartCategories).toEqual(['草稿本期']);expect(result[1].text).toContain('73')
 expect(elements[0].tableCells?.[0][1]).toBe('42')
})
it('页与整稿仅包括真实能力对象，结构变化拒绝旧表格投影',()=>{
 expect(slidesAIObjects(slides,[],'slide',0,new Set()).map(o=>o.elementId)).toEqual(['table','chart','private'])
 expect(()=>slidesAIObjects(slides,[{kind:'editSlides',tableStructures:[{slideIndex:0}]}],'object',0,new Set(['table']))).toThrow('结构已变化')
})

it('表格图表版式或组合变化不使用过期对象投影',()=>{
 for(const operation of [{kind:'editSlides',slideLayouts:[{slideIndex:0}]},{kind:'editSlides',groupEdits:[{slideIndex:0}]}])expect(()=>slidesAIObjects(slides,[operation],'object',0,new Set(['chart']))).toThrow('对象结构或版式已变化')
})
