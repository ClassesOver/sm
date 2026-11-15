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

it('Office 工作区默认从左侧打开并记住用户主动关闭',()=>{
 const f=fixture(); f.dock.dispose()
 const create=()=>mountOfficeTaskDock(f.main,[f.read,f.edit],{label:'测试助手',officeWorkspace:true})
 const first=create(); first.openInitially()
 const aside=f.host.querySelector<HTMLElement>('aside')!
 expect(aside.nextElementSibling).toBe(f.main)
 expect(aside.hidden).toBe(false)
 aside.querySelector<HTMLButtonElement>('[aria-label="收起 AI 助手"]')!.click()
 first.dispose()
 const next=create(); next.openInitially()
 expect(f.host.querySelector<HTMLElement>('aside')!.hidden).toBe(true)
 next.dispose()
})

it('右侧助手关闭自动打开后仍可手动打开，且保留先前的打开记录',()=>{
 const f=fixture();f.dock.dispose()
 const preferences='genoffice-assistant-preferences'
 const remembered='native-office-ai-open:测试助手'
 localStorage.setItem(remembered,'1')
 localStorage.setItem(preferences,JSON.stringify({side:'right',openInNewDocs:false}))
 const dock=mountOfficeTaskDock(f.main,[f.read],{label:'测试助手',officeWorkspace:true})
 dock.openInitially()
 const aside=f.host.querySelector<HTMLElement>('aside')!
 expect(f.main.nextElementSibling).toBe(aside)
 expect(aside.hidden).toBe(true)
 dock.open('read')
 expect(aside.hidden).toBe(false)
 aside.querySelector<HTMLButtonElement>('[aria-label="收起 AI 助手"]')!.click()
 expect(localStorage.getItem(remembered)).toBe('1')
 dock.dispose()
})
it('在助手内换边时保留当前面板和草稿，并保存位置',()=>{
 const f=fixture();f.dock.dispose()
 localStorage.setItem('genoffice-assistant-preferences',JSON.stringify({side:'left',fontSize:18,spellcheck:false}))
 const dock=mountOfficeTaskDock(f.main,[f.read],{label:'测试助手',officeWorkspace:true})
 dock.open('read')
 const input=f.read.panel.querySelector('textarea')!
 input.value='未发送'
 const aside=f.host.querySelector('aside')!
 aside.querySelector<HTMLButtonElement>('button[aria-label="将 AI 面板移到右侧"]')!.click()
 expect(f.main.nextElementSibling).toBe(aside)
 expect(aside.classList.contains('office-task-dock-left')).toBe(false)
 expect(f.read.panel.hidden).toBe(false)
 expect(f.read.close).not.toHaveBeenCalled()
 expect(input.value).toBe('未发送')
 expect(aside.querySelector('button[aria-label="将 AI 面板移到左侧"]')).not.toBeNull()
 expect(JSON.parse(localStorage.getItem('genoffice-assistant-preferences')!)).toMatchObject({side:'right',fontSize:18,spellcheck:false})
 dock.dispose()
})
it('其他文档保存位置后，已打开的助手同步换边并保留当前面板',()=>{
 const f=fixture();f.dock.dispose()
 const dock=mountOfficeTaskDock(f.main,[f.read],{label:'PDF AI 助手',officeWorkspace:true})
 dock.open('read')
 const aside=f.host.querySelector('aside')!
 const key='genoffice-assistant-preferences'
 const newValue=JSON.stringify({side:'right'})
 localStorage.setItem(key,newValue)
 window.dispatchEvent(new StorageEvent('storage',{key,newValue,storageArea:localStorage}))
 expect(f.main.nextElementSibling).toBe(aside)
 expect(aside.hidden).toBe(false)
 expect(f.read.close).not.toHaveBeenCalled()
 dock.dispose()
})
