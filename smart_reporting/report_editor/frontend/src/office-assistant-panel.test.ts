import {afterEach,expect,it,vi} from 'vitest'
import {bindOfficeAssistantPanel} from './office-assistant-panel'
afterEach(()=>document.body.replaceChildren())
function fixture(headerAction?: HTMLButtonElement){
 const panel=document.body.appendChild(document.createElement('section'));panel.className='native-ai native-ai-panel'
 const title=document.createElement('h3'),help=document.createElement('p'),form=document.createElement('form'),input=document.createElement('textarea'),start=document.createElement('button'),cancel=document.createElement('button'),close=document.createElement('button'),answer=document.createElement('div'),controls=document.createElement('div'),scope=document.createElement('select')
 title.textContent='AI 助手';start.type='submit';cancel.disabled=true;cancel.type=close.type='button';form.append(input,start,cancel);panel.append(title,help,controls,scope,form,answer,close)
 const submit=vi.fn((e:Event)=>e.preventDefault());form.addEventListener('submit',submit);const onClose=vi.fn();const view=bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close,controls,scope,onClose,headerAction})
 return{panel,form,input,start,cancel,close,answer,controls,scope,view,submit,onClose}
}
it('固定源侧栏顺序：标题和范围在上，结果工具区可滚动，输入框与发送固定底部',async()=>{
 const f=fixture();expect([...f.panel.children].map(n=>n.className)).toEqual(['office-assistant-header','office-assistant-toolbar','office-assistant-body','office-assistant-composer'])
 expect(f.panel.querySelector('.office-assistant-body')!.contains(f.answer)).toBe(true)
 expect(f.panel.querySelector('.office-assistant-composer')!.contains(f.input)).toBe(true)
 const progress=document.createElement('section');f.panel.append(progress);await Promise.resolve();expect(progress.parentElement?.className).toBe('office-assistant-body')
 expect(f.panel.querySelector('.office-assistant-toolbar')!.contains(f.scope)).toBe(true);f.view.dispose()
})
it('底部按钮仍关联原form提交且保留原监听器',()=>{const f=fixture();expect(f.start.form).toBe(f.form);f.start.click();expect(f.submit).toHaveBeenCalledOnce();f.view.dispose()})
it('助手结果区可直接键盘聚焦阅读，保留原回答节点',()=>{
 const f=fixture(),body=f.panel.querySelector<HTMLElement>('.office-assistant-body')!
 expect(body.tabIndex).toBe(0);expect(body.getAttribute('role')).toBe('region');expect(body.getAttribute('aria-label')).toBe('助手结果与工具进度')
 body.focus();expect(document.activeElement).toBe(body);expect(body.contains(f.answer)).toBe(true);expect(f.submit).not.toHaveBeenCalled();f.view.dispose()
})
it('结果区自身的Home/End直接滚动首尾，不接管组合键或内部输入控件',()=>{
 const f=fixture(),body=f.panel.querySelector<HTMLElement>('.office-assistant-body')!
 Object.defineProperty(body,'scrollHeight',{value:500});Object.defineProperty(body,'clientHeight',{value:100})
 const key=(target:HTMLElement,value:string,options:KeyboardEventInit={})=>{const event=new KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true,...options});target.dispatchEvent(event);return event}
 expect(key(body,'End').defaultPrevented).toBe(true);expect(body.scrollTop).toBe(500)
 expect(key(body,'Home',{ctrlKey:true}).defaultPrevented).toBe(false);expect(body.scrollTop).toBe(500)
 expect(key(body,'Home',{isComposing:true}).defaultPrevented).toBe(false);expect(body.scrollTop).toBe(500)
 const nested=body.appendChild(document.createElement('textarea'))
 expect(key(nested,'Home').defaultPrevented).toBe(false);expect(body.scrollTop).toBe(500)
 expect(key(body,'Home').defaultPrevented).toBe(true);expect(body.scrollTop).toBe(0);f.view.dispose()
 expect(key(body,'End').defaultPrevented).toBe(false);expect(body.scrollTop).toBe(0)
})
it('Esc在输入法组合期间不关闭，普通Esc走原控制器并隐藏',()=>{const f=fixture();f.input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true}));expect(f.onClose).not.toHaveBeenCalled();f.input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(f.onClose).toHaveBeenCalledOnce();expect(f.panel.hidden).toBe(true);f.view.dispose()})

it('Enter 发送，Shift+Enter 和输入法确认保留，忙碌时 Esc 只停止任务',()=>{
 const f=fixture()
 const key=(value:string, options:KeyboardEventInit={})=>{
  const event=new KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true,...options})
  f.input.dispatchEvent(event)
  return event
 }
 expect(key('Enter',{isComposing:true}).defaultPrevented).toBe(false)
 expect(key('Enter',{shiftKey:true}).defaultPrevented).toBe(false)
 expect(f.submit).not.toHaveBeenCalled()
 expect(key('Enter').defaultPrevented).toBe(true)
 expect(f.submit).toHaveBeenCalledOnce()
 f.start.disabled=true
 f.cancel.disabled=false
 const stop=vi.fn()
 f.cancel.addEventListener('click',stop)
 key('Enter')
 expect(f.submit).toHaveBeenCalledOnce()
 expect(key('Escape').defaultPrevented).toBe(true)
 expect(stop).toHaveBeenCalledOnce()
 expect(f.onClose).not.toHaveBeenCalled()
 f.view.dispose()
})

it('按源聊天视图在底部跟随新回答，向上阅读时保留位置，回到底部后恢复跟随',async()=>{
 const f=fixture(),body=f.panel.querySelector<HTMLElement>('.office-assistant-body')!
 let height=400
 Object.defineProperty(body,'scrollHeight',{get:()=>height});Object.defineProperty(body,'clientHeight',{value:100})
 f.answer.textContent='第一个回答';await Promise.resolve()
 expect(body.scrollTop).toBe(400)
 body.scrollTop=80;body.dispatchEvent(new Event('scroll'))
 height=600;f.answer.append(document.createTextNode('工具进度'))
 await Promise.resolve();expect(body.scrollTop).toBe(80)
 body.scrollTop=460;body.dispatchEvent(new Event('scroll'))
 height=800;f.answer.append(document.createTextNode('后续回答'))
 await Promise.resolve();expect(body.scrollTop).toBe(800)
 f.view.dispose();body.scrollTop=10;height=900;f.answer.append(document.createTextNode('已卸载'))
 await Promise.resolve();expect(body.scrollTop).toBe(10)
})
it('共用输入区没有模型选择入口，保留授权范围选择及原控制器',()=>{
 const f=fixture(),composer=f.panel.querySelector('.office-assistant-composer')!
 expect(composer.querySelector('select,[role=combobox],[data-model-picker],.ai-model-picker')).toBeNull()
 expect(f.panel.querySelectorAll('select')).toHaveLength(1)
 expect(f.panel.querySelector('select')).toBe(f.scope)
 expect(f.submit).not.toHaveBeenCalled();f.view.dispose()
})

it('新对话沿用源行为恢复跟随新回答，不增加模型选择',async()=>{
 const reset=document.createElement('button'),f=fixture(reset),body=f.panel.querySelector<HTMLElement>('.office-assistant-body')!
 let height=400
 Object.defineProperty(body,'scrollHeight',{get:()=>height});Object.defineProperty(body,'clientHeight',{value:100})
 body.scrollTop=50;body.dispatchEvent(new Event('scroll'))
 reset.click();height=700;f.answer.textContent='新对话回答';await Promise.resolve()
 expect(body.scrollTop).toBe(700);expect(f.submit).not.toHaveBeenCalled();f.view.dispose()
})

it('每次接受新任务时恢复源跟随行为，即使此前正在向上阅读',async()=>{
 const f=fixture(),body=f.panel.querySelector<HTMLElement>('.office-assistant-body')!
 let height=400
 Object.defineProperty(body,'scrollHeight',{get:()=>height});Object.defineProperty(body,'clientHeight',{value:100})
 body.scrollTop=40;body.dispatchEvent(new Event('scroll'))
 f.view.beforeTask();height=700;f.answer.textContent='新任务回答';await Promise.resolve()
 expect(body.scrollTop).toBe(700);expect(f.submit).not.toHaveBeenCalled();f.view.dispose()
})

it('任务在隐藏期间完成后，展开仍在跟随的面板显示最新内容',async()=>{
 const f=fixture(),body=f.panel.querySelector<HTMLElement>('.office-assistant-body')!
 const dock=document.body.appendChild(document.createElement('aside'));dock.hidden=true;dock.append(f.panel)
 let height=300
 Object.defineProperty(body,'scrollHeight',{get:()=>height});Object.defineProperty(body,'clientHeight',{get:()=>f.panel.hidden||dock.hidden?0:100})
 Object.defineProperty(body,'scrollTop',{get:()=>position,set:(value:number)=>{position=f.panel.hidden||dock.hidden?0:value},configurable:true})
 let position=0
 f.panel.hidden=true;height=800;f.answer.textContent='任务在隐藏期间完成'
 await Promise.resolve();expect(position).toBe(0)
 f.view.beforeOpen();f.panel.hidden=false
 queueMicrotask(()=>{dock.hidden=false})
 await vi.waitFor(()=>expect(position).toBe(800))
 f.view.dispose()
})
