// @vitest-environment jsdom
import {expect,it,vi} from 'vitest'
import {createNotePictures} from './workbook-note-pictures'
const item={sheetName:'数据',sheetIndex:0,row:0,column:0,author:'作者',text:'保留文字',sourceIdentity:'a'.repeat(64),mediaPath:'xl/media/p.png',relationshipId:'img',mediaType:'image/png',sha256:'b'.repeat(64),size:3,bytes:new Uint8Array([1,2,3])}
it('shows actual picture metadata supports jump remove close and empty state',async()=>{
 const root=document.createElement('div');document.body.append(root);const jump=vi.fn(),remove=vi.fn(),ui=createNotePictures(root,{capture:async()=>({key:'x',pictures:[item],issues:[]}),current:()=>true,editable:()=>true,jump,remove,insert:vi.fn()})
 await ui.open();expect(root.textContent).toContain('作者');expect(root.textContent).toContain('保留文字');expect(root.querySelector('img')).not.toBeNull()
 ;(root.querySelector('[data-note-picture-jump]') as HTMLButtonElement).click();expect(jump).toHaveBeenCalledWith(item)
 ;(root.querySelector('[data-note-picture-remove]') as HTMLButtonElement).click();await vi.waitFor(()=>expect(remove).toHaveBeenCalledWith(item,'x'))
 ;(root.querySelector('[data-note-pictures-close]') as HTMLButtonElement).click();expect(root.querySelector('.note-pictures-pane')).toBeNull();ui.dispose()
})
it('keeps text on image failure and holds hover when pointer enters then constrains tooltip placement',async()=>{
 const root=document.createElement('div');document.body.append(root);const ui=createNotePictures(root,{capture:async()=>({key:'x',pictures:[],issues:[]}),current:()=>true,editable:()=>true,jump:vi.fn(),remove:vi.fn(),insert:vi.fn()})
 ui.hover({...item,bytes:null,unavailable:'图片缺失'},'x');expect(root.querySelector('[role=tooltip]')?.textContent).toContain('图片缺失')
 root.querySelector('[role=tooltip]')!.dispatchEvent(new Event('pointerenter'));ui.hover(null,'x');expect(root.querySelector('[role=tooltip]')).not.toBeNull()
 root.querySelector('[role=tooltip]')!.dispatchEvent(new Event('pointerleave'));expect(root.querySelector('[role=tooltip]')).toBeNull()
 await ui.open();expect(root.textContent).toContain('没有包含图片的批注');ui.dispose()
})
