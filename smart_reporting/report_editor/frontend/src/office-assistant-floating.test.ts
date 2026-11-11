import {afterEach,expect,it,vi} from 'vitest'
import {bindOfficeAssistantFloating} from './office-assistant-floating'
afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks()})
it('浮动与停靠保留面板身份和输入，键盘移动受视口限制',()=>{
 const dock=document.body.appendChild(document.createElement('aside'));dock.className='office-task-dock'
 const header=dock.appendChild(document.createElement('header')),input=dock.appendChild(document.createElement('textarea'));input.value='待处理指令'
 vi.spyOn(dock,'getBoundingClientRect').mockReturnValue({left:600,top:100,width:360,height:600,right:960,bottom:700,x:600,y:100,toJSON(){}})
 const binding=bindOfficeAssistantFloating(dock,header)
 header.querySelector<HTMLButtonElement>('[aria-label="浮动 AI 助手"]')!.click()
 expect(dock.classList.contains('is-office-assistant-floating')).toBe(true)
 const handle=header.querySelector<HTMLElement>('[role=button]')!
 for(let i=0;i<60;i++)handle.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))
 expect(dock.style.left).toBe('8px');expect(input.value).toBe('待处理指令')
 header.querySelector<HTMLButtonElement>('[aria-label="停靠 AI 助手"]')!.click()
 expect(dock.classList.contains('is-office-assistant-floating')).toBe(false);expect(dock.style.left).toBe('');expect(dock.contains(input)).toBe(true)
 binding.dispose();expect(header.querySelector('button')).toBeNull()
})
it('拖动浮窗后视口缩小仍保持标题栏可达，释放指针和销毁移除监听',()=>{
 const dock=document.body.appendChild(document.createElement('aside'));dock.className='pdf-ai-dock';const header=dock.appendChild(document.createElement('header'))
 vi.spyOn(dock,'getBoundingClientRect').mockReturnValue({left:500,top:80,width:360,height:500,right:860,bottom:580,x:500,y:80,toJSON(){}})
 header.setPointerCapture=vi.fn();header.hasPointerCapture=()=>true;header.releasePointerCapture=vi.fn()
 const binding=bindOfficeAssistantFloating(dock,header);header.querySelector('button')!.click()
 function pointer(type:string,x:number,y:number){const event=new MouseEvent(type,{clientX:x,clientY:y,button:0,bubbles:true});Object.defineProperty(event,'pointerId',{value:1});header.dispatchEvent(event)}
 pointer('pointerdown',510,90);pointer('pointermove',-400,-300);expect(dock.style.left).toBe('8px');expect(dock.style.top).toBe('8px');pointer('pointerup',-400,-300);expect(header.releasePointerCapture).toHaveBeenCalledWith(1)
 binding.dispose()
})
