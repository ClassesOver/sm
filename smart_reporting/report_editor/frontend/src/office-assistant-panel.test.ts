import {afterEach,expect,it,vi} from 'vitest'
import {bindOfficeAssistantPanel} from './office-assistant-panel'
afterEach(()=>document.body.replaceChildren())
function fixture(){
 const panel=document.body.appendChild(document.createElement('section'));panel.className='native-ai native-ai-panel'
 const title=document.createElement('h3'),help=document.createElement('p'),form=document.createElement('form'),input=document.createElement('textarea'),start=document.createElement('button'),cancel=document.createElement('button'),close=document.createElement('button'),answer=document.createElement('div'),controls=document.createElement('div'),scope=document.createElement('select')
 title.textContent='AI 助手';start.type='submit';cancel.type=close.type='button';form.append(input,start,cancel);panel.append(title,help,controls,scope,form,answer,close)
 const submit=vi.fn((e:Event)=>e.preventDefault());form.addEventListener('submit',submit);const onClose=vi.fn();const view=bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close,controls,scope,onClose})
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
