import { afterEach, expect, it, vi } from 'vitest'
import { Editor, Node, Extension } from '@tiptap/core'
import { measureDocxRowHeight } from './docx-table-row-height-measure'
const Doc=Node.create({name:'doc',topNode:true,content:'docTable+'})
const Table=Node.create({name:'docTable',content:'docTableRow+',renderHTML:()=>['table',['tbody',0]]})
const Row=Node.create({name:'docTableRow',content:'docTableCell+',renderHTML:()=>['tr',0]})
const Cell=Node.create({name:'docTableCell',content:'docParagraph+',renderHTML:()=>['td',0]})
const Paragraph=Node.create({name:'docParagraph',content:'inline*',renderHTML:()=>['p',0]})
const Image=Node.create({name:'image',inline:true,group:'inline',atom:true,renderHTML:()=>['img']})
const Text=Node.create({name:'text',group:'inline'})
const editors:Editor[]=[]
afterEach(()=>{editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren();vi.restoreAllMocks()})
function setup(){
 const wrapper=document.createElement('div');wrapper.className='doc-zoom';document.body.append(wrapper)
 const editor=new Editor({element:wrapper,extensions:[Doc,Table,Row,Cell,Paragraph,Text,Image],content:{type:'doc',content:[{type:'docTable',content:[0,1,2].map(i=>({type:'docTableRow',content:[{type:'docTableCell',content:[{type:'docParagraph',content:[{type:'text',text:String(i)}]}]}]}))}]}});editors.push(editor)
 const rows=[...editor.view.dom.querySelectorAll('tr')]
 for(const node of [editor.view.dom,wrapper]){const values=new Map<string,string>(),priorities=new Map<string,string>();const get=node.style.getPropertyValue.bind(node.style),set=node.style.setProperty.bind(node.style),remove=node.style.removeProperty.bind(node.style),priority=node.style.getPropertyPriority.bind(node.style);vi.spyOn(node.style,'getPropertyValue').mockImplementation(key=>key==='zoom'?values.get(key)??'':get(key));vi.spyOn(node.style,'getPropertyPriority').mockImplementation(key=>key==='zoom'?priorities.get(key)??'':priority(key));vi.spyOn(node.style,'setProperty').mockImplementation((key,value,p)=>{if(key==='zoom'){values.set(key,value??'');priorities.set(key,p??'')}else set(key,value,p)});vi.spyOn(node.style,'removeProperty').mockImplementation(key=>{if(key==='zoom'){const old=values.get(key)??'';values.delete(key);priorities.delete(key);return old}return remove(key)})}
 rows.forEach((row,index)=>vi.spyOn(row,'getBoundingClientRect').mockImplementation(()=>({height:[27,67,47][index],width:120} as DOMRect)))
 return{editor,wrapper,rows,measure:(top=0,bottom=3,current=()=>true)=>measureDocxRowHeight(editor.view,editor.state.doc.child(0),1,top,bottom,current)}
}
it('全量真实TR测量，root/wrapper临时100%并恢复zoom原值及priority',async()=>{
 const f=setup();f.editor.view.dom.style.setProperty('zoom','1.5','important');f.wrapper.style.setProperty('zoom','.75')
 for(const row of f.rows)vi.spyOn(row,'getBoundingClientRect').mockImplementation(()=>{expect(f.editor.view.dom.style.getPropertyValue('zoom')).toBe('1');expect(f.wrapper.style.getPropertyValue('zoom')).toBe('1');return {height:47} as DOMRect})
 expect(await f.measure()).toBe(705)
 expect(f.editor.view.dom.style.getPropertyValue('zoom')).toBe('1.5');expect(f.editor.view.dom.style.getPropertyPriority('zoom')).toBe('important');expect(f.wrapper.style.getPropertyValue('zoom')).toBe('.75')
 expect(await f.measure(0,2)).toBe(705)
})
it('按实际内容高度求均值并拒绝任何缺失/零高/异表行',async()=>{
 const f=setup();expect(await f.measure()).toBe(705);expect(await f.measure(0,2)).toBe(705)
 vi.spyOn(f.rows[1],'getBoundingClientRect').mockReturnValue({height:0} as DOMRect)
 await expect(f.measure()).rejects.toThrow(/行|测量/)
 vi.spyOn(f.editor.view,'nodeDOM').mockReturnValue(null);await expect(f.measure()).rejects.toThrow(/行|测量/)
})
it('测量异常必须恢复zoom；准备期间文档或zoom变化拒绝',async()=>{
 const f=setup();f.editor.view.dom.style.setProperty('zoom','1.5')
 vi.spyOn(f.rows[1],'getBoundingClientRect').mockImplementation(()=>{throw new Error('measure failure')})
 await expect(f.measure()).rejects.toThrow('measure failure');expect(f.editor.view.dom.style.getPropertyValue('zoom')).toBe('1.5');expect(f.wrapper.style.getPropertyValue('zoom')).toBe('')
 await expect(f.measure(0,3,()=>false)).rejects.toThrow(/文档|选区|改变/)
 const pending=f.measure();f.editor.view.dom.style.setProperty('zoom','.75');await expect(pending).rejects.toThrow(/缩放|改变/)
})
it('图片失败或字体准备失败拒绝，不能部分提交',async()=>{
 const f=setup();f.editor.commands.insertContentAt(4,{type:'image'});const image=f.editor.view.dom.querySelector('img')!
 Object.defineProperty(image,'complete',{value:true});Object.defineProperty(image,'naturalWidth',{value:0})
 await expect(f.measure()).rejects.toThrow(/图片/)
})
it('准备超时和等待中失效立即结束并清理图片事件监听',async()=>{
 vi.useFakeTimers();const f=setup();f.editor.commands.insertContentAt(4,{type:'image'});const image=f.editor.view.dom.querySelector('img')!
 Object.defineProperty(image,'complete',{value:false});Object.defineProperty(image,'decode',{value:undefined})
 const remove=vi.spyOn(image,'removeEventListener');let active=true
 const pending=expect(f.measure(0,3,()=>active)).rejects.toThrow(/改变/)
 await vi.advanceTimersByTimeAsync(1);active=false;await vi.advanceTimersByTimeAsync(100);await pending
 expect(remove.mock.calls.map(([name])=>name)).toEqual(expect.arrayContaining(['load','error']))
 const timeout=expect(f.measure()).rejects.toThrow(/超时/);await vi.advanceTimersByTimeAsync(15000);await timeout
 expect(vi.getTimerCount()).toBe(0);vi.useRealTimers()
})
