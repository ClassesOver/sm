import {expect,it,vi} from 'vitest'
import {readFileSync} from 'node:fs'
import {bindPdfAIDock,mountPdfTaskDock} from './pdf-ai-dock'
it('PDF画布与右侧助手并排，切换和关闭走原控制器取消而不移除画布',async()=>{
 const root=document.createElement('div'),layout=root.appendChild(document.createElement('main'));layout.className='pdf-layout';const canvas=layout.appendChild(document.createElement('canvas'))
 const make=()=>{const panel=root.appendChild(document.createElement('section'));panel.hidden=true;const close=panel.appendChild(document.createElement('button')),cancel=vi.fn(()=>{panel.hidden=true});close.onclick=cancel;return{panel,close,cancel,open:()=>{panel.hidden=false}}}
 const read=make(),forms=make(),dock=bindPdfAIDock(layout,{read,forms})
 read.open();await vi.waitFor(()=>expect(root.querySelector<HTMLElement>('.pdf-ai-dock')!.hidden).toBe(false))
 root.querySelector<HTMLButtonElement>('[data-pdf-ai-mode=forms]')!.click()
 expect(read.cancel).toHaveBeenCalledOnce();expect(forms.panel.hidden).toBe(false);expect(canvas.parentElement).toBe(layout)
 expect(layout.parentElement?.className).toContain('pdf-ai-workspace');expect(layout.nextElementSibling?.className).toBe('pdf-ai-dock')
 forms.close.click();expect(forms.cancel).toHaveBeenCalledOnce();expect(root.querySelector<HTMLElement>('.pdf-ai-dock')!.hidden).toBe(true)
 dock.dispose();expect(layout.parentElement).toBe(root)
})
it('PDF表单启动使用浏览器document且仅按需加载模块',()=>{
 const source=readFileSync('src/pdf-main.ts','utf8')
 expect(source).toContain("window.document.createTextNode('AI 填写表单')")
 expect(source).not.toContain('window.window.document')
 expect(source).toContain("import type {bindNativePDFFormAI}")
 expect(source).toContain("await import('./native-pdf-form-ai')")
 const css=readFileSync('src/pdf-ai-dock.css','utf8');expect(css).toContain('flex:1;min-width:0;width:auto');expect(css).toContain('@media(max-width:900px)')
})

it('工作区 PDF 默认在左侧打开，换边时保留阅读面板',()=>{
 const root=document.createElement('div')
 const layout=root.appendChild(document.createElement('main'))
 const panel=root.appendChild(document.createElement('section'))
 panel.className='native-pdf-assistant'
 panel.hidden=true
 const close=panel.appendChild(document.createElement('button'))
 close.className='office-assistant-close'
 close.onclick=()=>{panel.hidden=true}
 const open=vi.fn(()=>{panel.hidden=false})
 localStorage.removeItem('native-office-ai-open:PDF AI 助手')
 const dock=mountPdfTaskDock(root,layout,{read:{open}},true)
 expect(layout.previousElementSibling?.classList.contains('office-task-dock-left')).toBe(true)
 expect(panel.hidden).toBe(false)
 expect(open).toHaveBeenCalledOnce()
 layout.previousElementSibling?.querySelector<HTMLButtonElement>('button[aria-label="将 AI 面板移到右侧"]')!.click()
 expect(layout.nextElementSibling?.contains(panel)).toBe(true)
 expect(panel.hidden).toBe(false)
 expect(open).toHaveBeenCalledOnce()
 dock.dispose()
 localStorage.removeItem('genoffice-assistant-preferences')
 localStorage.removeItem('native-office-ai-open:PDF AI 助手')
})
