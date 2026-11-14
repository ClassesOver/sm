import { expect, it, vi } from 'vitest'
import { createBlankWorkbook, applyCellEdits } from '@sheets-web/xlsx-engine'
import { createPivotDialog } from './workbook-pivot-dialog'
import type { PivotConfig, WorkbookPivot } from './workbook-pivot'
const fixture=async()=>applyCellEdits(await createBlankWorkbook(),[['区域','年份','收入','数量'],['东',2025,10,2],['西',2026,20,4]].flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
const pivot={name:'透视表',sourceSheetName:'Sheet1',sourceRange:'A1:D3',targetSheetName:'Sheet1',targetCell:'H1',rowFields:['区域'],columnFields:[],values:[{field:'收入',agg:'sum'}],tablePath:'xl/pivotTables/pivotTable1.xml',cachePath:'xl/pivotCache/pivotCacheDefinition1.xml',worksheetPath:'xl/worksheets/sheet1.xml',location:{startRow:0,startColumn:7,endRow:4,endColumn:8},fieldNames:['区域','年份','收入','数量']} satisfies WorkbookPivot
const check=(root:HTMLElement,label:string)=>Array.from(root.querySelectorAll<HTMLInputElement>('.pivot-field-list input')).find(input=>input.closest('label')!.textContent===label)!
async function setup(apply:(config:PivotConfig,path?:string)=>Promise<void>,existing=false){const root=document.createElement('div');document.body.append(root);const dialog=createPivotDialog(root,apply);await dialog.open({bytes:await fixture(),sourceSheetName:'Sheet1',sourceRange:'A1:D3',targetCell:'H1',...(existing?{pivots:[pivot]}:{})});return {root,dialog,dispose:()=>{dialog.dispose();root.remove()}}}
it('uses checkbox placement, 2 by 2 areas and cancels without applying',async()=>{
 const apply=vi.fn(async()=>{}),s=await setup(apply)
 check(s.root,'区域').click();await vi.waitFor(()=>expect(s.root.querySelector('[data-pivot-area="rows"]')!.textContent).toContain('区域'))
 check(s.root,'收入').click();await vi.waitFor(()=>expect(s.root.querySelector('[data-pivot-area="values"]')!.textContent).toContain('收入'))
 expect(s.root.querySelector('.pivot-area-grid')!.children).toHaveLength(4)
 s.root.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();await Promise.resolve();expect(apply).not.toHaveBeenCalled();s.dispose()
})
it('submits selected source fields',async()=>{
 const apply=vi.fn(async(_config:PivotConfig)=>{}),s=await setup(apply)
 check(s.root,'区域').click();await vi.waitFor(()=>expect(check(s.root,'区域').checked).toBe(true));check(s.root,'收入').click();await vi.waitFor(()=>expect(check(s.root,'收入').checked).toBe(true))
 s.root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await vi.waitFor(()=>expect(apply).toHaveBeenCalledOnce())
 expect(apply.mock.calls[0]![0]).toMatchObject({rowFields:['区域'],values:[{field:'收入',agg:'sum'}]});s.dispose()
})
it('invalidates queued immediate updates on cancel before the commit microtask',async()=>{
 const apply=vi.fn(async()=>{}),s=await setup(apply,true)
 check(s.root,'数量').click();s.root.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
 await Promise.resolve();await Promise.resolve();expect(apply).not.toHaveBeenCalled();s.dispose()
})
it('freezes controls and preserves pending fields after apply failure',async()=>{
 let reject!:(error:Error)=>void;const apply=vi.fn((_config:PivotConfig)=>new Promise<void>((_resolve,rejectApply)=>{reject=rejectApply})),s=await setup(apply,true)
 check(s.root,'数量').click();await vi.waitFor(()=>expect(apply).toHaveBeenCalledOnce())
 expect(s.root.querySelector<HTMLInputElement>('[aria-label="来源区域"]')!.disabled).toBe(true);expect(s.root.querySelector<HTMLElement>('[data-field-pane]')!.inert).toBe(true)
 expect(apply.mock.calls[0]![0].values).toEqual([{field:'收入',agg:'sum'},{field:'数量',agg:'sum'}])
 reject(new Error('注入提交失败'));await vi.waitFor(()=>expect(s.root.querySelector('[data-pending]')!.textContent).toContain('待更新'))
 expect(s.root.querySelector('[role="alert"]')!.textContent).toContain('注入提交失败');expect(check(s.root,'数量').checked).toBe(true)
 expect(s.root.querySelector<HTMLInputElement>('[aria-label="来源区域"]')!.disabled).toBe(false);s.dispose()
})
it('keeps deferred changes local and opening menus never applies',async()=>{
 const apply=vi.fn(async()=>{}),s=await setup(apply,true)
 s.root.querySelector<HTMLInputElement>('.pivot-fields-pane footer input')!.click();await vi.waitFor(()=>expect(s.root.querySelector<HTMLInputElement>('.pivot-fields-pane footer input')!.checked).toBe(true))
 check(s.root,'数量').click();await vi.waitFor(()=>expect(check(s.root,'数量').checked).toBe(true));expect(apply).not.toHaveBeenCalled()
 s.root.querySelector<HTMLButtonElement>('[aria-label="区域 的字段菜单"]')!.click();await vi.waitFor(()=>expect(s.root.querySelectorAll('[role="menu"]')).toHaveLength(1));expect(apply).not.toHaveBeenCalled()
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await vi.waitFor(()=>expect(s.root.querySelector('[role="menu"]')).toBeNull())
 s.root.querySelector<HTMLButtonElement>('.pivot-fields-pane footer button')!.click();await vi.waitFor(()=>expect(apply).toHaveBeenCalledOnce());s.dispose()
})
it('continues immediate changes with independent snapshots',async()=>{
 const apply=vi.fn(async(_config:PivotConfig)=>{}),s=await setup(apply,true)
 check(s.root,'数量').click();await vi.waitFor(()=>expect(apply).toHaveBeenCalledOnce());await vi.waitFor(()=>expect(s.root.querySelector('[data-pending]')!.textContent).toBe(''))
 check(s.root,'年份').click();await vi.waitFor(()=>expect(apply).toHaveBeenCalledTimes(2))
 expect(apply.mock.calls[0]![0].values).toHaveLength(2);expect(apply.mock.calls[1]![0].values).toHaveLength(3);s.dispose()
})
it('retains its layout and rejects updates when a reread schema loses configured fields',async()=>{
 const apply=vi.fn(async(_config:PivotConfig)=>{}),s=await setup(apply,true)
 const sourceRange=s.root.querySelector<HTMLInputElement>('[aria-label="来源区域"]')!;sourceRange.value='B1:B3';s.root.querySelector<HTMLButtonElement>('[data-action="fields"]')!.click()
 await vi.waitFor(()=>expect(s.root.querySelector('.workbook-ribbon-format-error')!.textContent).toContain('来源缺少已配置字段'))
 expect(s.root.querySelector<HTMLElement>('[data-field-pane]')!.hidden).toBe(true)
 s.root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await Promise.resolve();expect(apply).not.toHaveBeenCalled()
 sourceRange.value='A1:D3';s.root.querySelector<HTMLButtonElement>('[data-action="fields"]')!.click();await vi.waitFor(()=>expect(s.root.querySelector<HTMLElement>('[data-field-pane]')!.hidden).toBe(false))
 expect(check(s.root,'区域').checked).toBe(true);expect(check(s.root,'收入').checked).toBe(true);s.dispose()
})
it('disables pane updates after a source read failure',async()=>{
 const apply=vi.fn(async()=>{}),s=await setup(apply,true)
 s.root.querySelector<HTMLInputElement>('[aria-label="来源区域"]')!.value='A20:B21';s.root.querySelector<HTMLButtonElement>('[data-action="fields"]')!.click()
 await vi.waitFor(()=>expect(s.root.querySelector<HTMLElement>('[data-field-pane]')!.hidden).toBe(true))
 s.root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await Promise.resolve();expect(apply).not.toHaveBeenCalled();s.dispose()
})
async function numericSourceDialog(){
 const bytes=await applyCellEdits(await createBlankWorkbook(),[['Code','Date','Amount'],['001',45292,12]].flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value},...(r===1&&column===1?{style:{numberFormat:'yyyy-mm-dd'}}:{})}))))
 const root=document.createElement('div');document.body.append(root);const dialog=createPivotDialog(root,async()=>{});await dialog.open({bytes,sourceSheetName:'Sheet1',sourceRange:'A1:C2',targetCell:'E1'});return {root,dispose:()=>{dialog.dispose();root.remove()}}
}
it('places numeric text and date-formatted serial fields on Rows like the source',async()=>{
 const s=await numericSourceDialog();check(s.root,'Code').click();await vi.waitFor(()=>expect(s.root.querySelector('[data-pivot-area="rows"]')!.textContent).toContain('Code'));check(s.root,'Date').click();await vi.waitFor(()=>expect(s.root.querySelector('[data-pivot-area="rows"]')!.textContent).toContain('Date'));s.dispose()
})
it('places ordinary numeric fields on Values like the source',async()=>{
 const s=await numericSourceDialog();check(s.root,'Amount').click();await vi.waitFor(()=>expect(s.root.querySelector('[data-pivot-area="values"]')!.textContent).toContain('Amount'));s.dispose()
})
