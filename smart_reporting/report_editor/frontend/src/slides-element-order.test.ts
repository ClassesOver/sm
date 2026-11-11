import {expect,it} from 'vitest'
import {planSlidesElementOrder,validateSlidesElementOrders} from './slides-element-order'
const elements=['a','b','c','d','e','f'].map(id=>({id,type:'shape',orderEditable:true}))
it.each([
 ['front',['b','c','e'],['a','d','f','b','c','e']],
 ['back',['e','c','b'],['b','c','e','a','d','f']],
 ['forward',['b','c','e'],['a','d','b','c','f','e']],
 ['backward',['b','c','e'],['b','c','a','e','d','f']],
] as const)('多选%s保持来源次序且连续块只跨过一个未选对象',(direction,selected,want)=>{
 expect(planSlidesElementOrder(elements,selected,undefined,direction)).toEqual({elementIds:[...want],changed:true})
})
it('连续选中端点块保持不动，无变化不新增历史；从当前草稿顺序计算',()=>{
 expect(planSlidesElementOrder(elements,['e','f'],undefined,'forward')).toEqual({elementIds:['a','b','c','d','e','f'],changed:false})
 expect(planSlidesElementOrder(elements,['a','b'],undefined,'backward').changed).toBe(false)
 expect(planSlidesElementOrder(elements,['a','b'],undefined,'back').changed).toBe(false)
 expect(planSlidesElementOrder(elements,['a'],['f','e','d','c','b','a'],'backward').elementIds).toEqual(['f','e','d','c','a','b'])
})
it('只读对象可被安全对象跨过但互相次序必须保留，未知及重复目标拒绝',()=>{
 const mixed=[elements[0]!,{id:'readonly',type:'chart'},elements[1]!,{id:'readonly2',type:'group'}]
 expect(planSlidesElementOrder(mixed,['a','b'],undefined,'front').elementIds).toEqual(['readonly','readonly2','a','b'])
 for(const selected of [[],['a','a'],['missing'],['readonly']])expect(()=>planSlidesElementOrder(mixed,selected,undefined,'front')).toThrow()
 expect(()=>planSlidesElementOrder(mixed,['a'],['a','readonly2','b','readonly'],'front')).toThrow()
 expect(()=>planSlidesElementOrder([{id:'a',type:'chart',orderEditable:true}],['a'],undefined,'front')).toThrow()
})
it('恢复严格验证完整全排列及外部schema，不修改输入',()=>{
 const slides=[{elements},{elements:[{id:'x'}]}],value=[{slideIndex:0,elementIds:['f','e','d','c','b','a']}]
 expect(validateSlidesElementOrders(value,slides)).toEqual(value)
 expect(validateSlidesElementOrders(undefined,slides)).toEqual([])
 for(const bad of [null,{},[...value,...value],[{...value[0],extra:true}],[{slideIndex:0,elementIds:['a']}],[{slideIndex:0,elementIds:['a','a','c','d','e','f']}],[{slideIndex:0,elementIds:['a','b','c','d','e','unknown']}],[{slideIndex:true,elementIds:[]}],[{slideIndex:2,elementIds:[]}]] )expect(()=>validateSlidesElementOrders(bad,slides)).toThrow()
 expect(()=>validateSlidesElementOrders(value,slides,[0])).toThrow()
 expect(value[0]!.elementIds).toEqual(['f','e','d','c','b','a'])
})
it('恢复不能交换只读对象相对顺序，安全对象可跨过只读对象',()=>{
 const slides=[{elements:[{id:'a',type:'text',orderEditable:true},{id:'r1',type:'chart'},{id:'r2',type:'group'}]}]
 expect(()=>validateSlidesElementOrders([{slideIndex:0,elementIds:['a','r2','r1']}],slides)).toThrow()
 expect(validateSlidesElementOrders([{slideIndex:0,elementIds:['r1','r2','a']}],slides)[0]!.elementIds).toEqual(['r1','r2','a'])
})
it('每页最多500对象且ID最多200字符，空页顺序允许为空',()=>{
 const source=Array.from({length:500},(_,i)=>({id:String(i),type:'shape',orderEditable:true})),ids=source.map(e=>e.id)
 expect(validateSlidesElementOrders([{slideIndex:0,elementIds:ids}],[{elements:source}])).toHaveLength(1)
 expect(planSlidesElementOrder(source,[ids[0]!],undefined,'front').changed).toBe(true)
 const tooMany=[...source,{id:'500',type:'shape',orderEditable:true}]
 expect(()=>validateSlidesElementOrders([{slideIndex:0,elementIds:tooMany.map(e=>e.id)}],[{elements:tooMany}])).toThrow()
 expect(()=>planSlidesElementOrder(tooMany,['0'],undefined,'front')).toThrow()
 for(const length of [200,201]){
  const id='x'.repeat(length),one=[{id,type:'shape',orderEditable:true}],validate=()=>validateSlidesElementOrders([{slideIndex:0,elementIds:[id]}],[{elements:one}]),plan=()=>planSlidesElementOrder(one,[id],undefined,'front')
  if(length===200){expect(validate()).toHaveLength(1);expect(plan().changed).toBe(false)}else{expect(validate).toThrow();expect(plan).toThrow()}
 }
 expect(validateSlidesElementOrders([{slideIndex:0,elementIds:[]}],[{elements:[]}])).toEqual([{slideIndex:0,elementIds:[]}])
})
