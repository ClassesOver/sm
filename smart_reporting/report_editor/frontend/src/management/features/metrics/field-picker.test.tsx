import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MetricFieldPicker } from './field-picker'
let root:Root,client:QueryClient
const fetcher=vi.fn(),changed=vi.fn(),scope={database:'warehouse',companyId:'a'}
const field={fieldRef:'warehouse.test.budget.amount',database:'test',table:'budget',column:'amount',dataType:'DECIMAL(18,2)',nullable:false,description:'预算额',tableDescription:'预算表'}
const response=(body:unknown)=>new Response(JSON.stringify(body))
beforeEach(()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('fetch',fetcher)
 vi.stubGlobal('matchMedia',()=>({matches:false,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}))
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}})
 fetcher.mockImplementation(async(path:string)=>path.includes('/sources?')?response({items:[{source_id:'warehouse',name:'已发布仓库',enabled:true,publishedRevision:2}],nextCursor:null}):response({sourceVersion:{sourceId:'warehouse',revision:2,contentHash:'source-hash'},catalogVersion:{sourceId:'warehouse',revision:1,contentHash:'catalog-hash'},items:[{...field,fieldRef:path.includes('after=')?'warehouse.test.budget.period':field.fieldRef,column:path.includes('after=')?'period':'amount'}],nextCursor:path.includes('after=')?null:field.fieldRef}))
 client=new QueryClient({defaultOptions:{queries:{retry:false}}});document.body.innerHTML='<div id="root"></div>';root=createRoot(document.getElementById('root')!)
})
afterEach(async()=>{await act(async()=>root.unmount());client.clear();vi.unstubAllGlobals();fetcher.mockReset();changed.mockReset()})
async function until(check:()=>void){for(let i=0;i<70;i++){await act(async()=>{await new Promise(r=>setTimeout(r,15))});try{check();return}catch{}}check()}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.replaceAll(' ','')===name)!
async function click(name:string){await act(async()=>button(name).click())}
async function mount(){await act(async()=>root.render(<QueryClientProvider client={client}><MetricFieldPicker scope={scope} label="取数字段" value="manual.db.table.field" disabled={false} onChange={changed}/></QueryClientProvider>))}
it('reads only on explicit open and chooses an exact published source and field without automatic changes',async()=>{
 await mount();expect(fetcher).not.toHaveBeenCalled();await click('从已发布目录选择取数字段')
 await until(()=>expect(button('浏览已发布仓库·warehouse版本2')).toBeTruthy());await click('浏览已发布仓库·warehouse版本2')
 await until(()=>expect(button('采用字段warehouse.test.budget.amount')).toBeTruthy());expect(changed).not.toHaveBeenCalled()
 expect(document.body.textContent).toContain('目录版本 1');expect(document.body.textContent).toContain('DECIMAL(18,2)')
 await click('加载更多字段');await until(()=>expect(button('采用字段warehouse.test.budget.period')).toBeTruthy())
 await click('采用字段warehouse.test.budget.period');expect(changed).toHaveBeenCalledWith('warehouse.test.budget.period')
 expect(fetcher.mock.calls.filter(([p])=>p.includes('/metric-field-catalog?')).every(([p,o])=>p.includes('sourceId=warehouse')&&p.includes('sourceRevision=2')&&p.includes('companyId=a')&&o.method==='GET')).toBe(true)
})
it('rejects another source revision before displaying or selecting its fields',async()=>{
 const original=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(path:string)=>path.includes('/sources?')?original(path):response({sourceVersion:{sourceId:'warehouse',revision:3,contentHash:'x'},catalogVersion:{sourceId:'warehouse',revision:1,contentHash:'y'},items:[field],nextCursor:null}))
 await mount();await click('从已发布目录选择取数字段');await until(()=>expect(button('浏览已发布仓库·warehouse版本2')).toBeTruthy());await click('浏览已发布仓库·warehouse版本2')
 await until(()=>expect(document.body.textContent).toContain('字段目录身份与所选发布版本不一致'))
 expect(button('采用字段warehouse.test.budget.amount')).toBeUndefined();expect(changed).not.toHaveBeenCalled()
})
it('keeps the manual reference when no published sources are available',async()=>{
 fetcher.mockImplementation(async()=>response({items:[],nextCursor:null}))
 await mount();await click('从已发布目录选择取数字段');await until(()=>expect(document.body.textContent).toContain('当前页没有可用的已发布数据源'))
 expect(document.body.textContent).toContain('manual.db.table.field');expect(changed).not.toHaveBeenCalled()
})
