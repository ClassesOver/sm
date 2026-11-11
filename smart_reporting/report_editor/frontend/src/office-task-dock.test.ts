import {afterEach,expect,it,vi} from 'vitest'
import {mountOfficeTaskDock} from './office-task-dock'
afterEach(()=>{document.body.replaceChildren();localStorage.clear()})
function fixture(){const host=document.body.appendChild(document.createElement('div')),main=host.appendChild(document.createElement('main'));const make=(id:string)=>{const panel=host.appendChild(document.createElement('section'));panel.hidden=true;panel.appendChild(document.createElement('textarea'));const close=vi.fn(()=>{panel.hidden=true});return{id,label:id,panel,close,open:()=>{panel.hidden=false}}};const read=make('read'),edit=make('edit'),dock=mountOfficeTaskDock(main,[read,edit],{label:'测试助手'});return{host,main,read,edit,dock}}
it('现有入口打开后停靠，切换取消旧任务，再点同模式不重启，关闭恢复画布',async()=>{
 const f=fixture();f.read.open();await vi.waitFor(()=>expect(f.host.querySelector<HTMLElement>('aside')!.hidden).toBe(false))
 f.dock.open('edit');expect(f.read.close).toHaveBeenCalledOnce();expect(f.edit.panel.hidden).toBe(false)
 f.dock.open('edit');expect(f.edit.close).not.toHaveBeenCalled();expect(document.activeElement).toBe(f.edit.panel.querySelector('textarea'))
 f.host.querySelector<HTMLButtonElement>('[aria-label="收起 AI 助手"]')!.click();expect(f.edit.close).toHaveBeenCalledOnce();expect(f.host.querySelector<HTMLElement>('aside')!.hidden).toBe(true)
 f.dock.dispose();expect(f.main.parentElement).toBe(f.host);expect(f.edit.panel.parentElement).toBe(f.host)
})
it('固定源宽度边界及键盘调整，Esc取消且输入法Esc保留',()=>{
 const f=fixture();f.dock.open('edit');const resize=f.host.querySelector<HTMLElement>('[role=separator]')!
 resize.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));expect(resize.getAttribute('aria-valuenow')).toBe('380')
 resize.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));expect(resize.getAttribute('aria-valuenow')).toBe('280')
 f.edit.panel.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true}));expect(f.edit.close).not.toHaveBeenCalled()
 f.edit.panel.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(f.edit.close).toHaveBeenCalledOnce();f.dock.dispose()
})
