import React, { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PolicyRuleFields } from './rule-fields'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PolicyDefinition } from './editor-contracts'
let root: Root, client: QueryClient
const fetcher=vi.fn()
let current: PolicyDefinition
const original: PolicyDefinition = { id: 'monthly', name: '月度口径', scenario: 'budget_execution', validFrom: '2026-01-01', validTo: null,
 metricVersions: [{ metricId: 'budget', revision: 1 }], evidenceReleaseId: 'rules-1', decisionNotes: '',
 filters: [{ fieldRef: 'warehouse.test.budget.project', operator: 'eq', values: ['A'] }],
 joins: [{ leftKeys: ['warehouse.test.budget.project'], rightKeys: ['warehouse.test.actual.project'], cardinality: 'many_to_one', outputGrain: ['project'] }],
 readinessPolicy: { expectedPeriods: [{ start: '2026-01-01', end: '2027-01-01' }],
 expectedGroups: [[{ dimensionId: 'project', value: 'A' }]], watermarkField: 'warehouse.test.budget.updated', maximumDelaySeconds: 3600, emptyObservation: 'unknown' } }
function Harness({ disabled = false }: { disabled?: boolean }) {
 const [value, setValue] = useState(original); current = value
 return <PolicyRuleFields scope={{database:"warehouse",companyId:"a"}} value={value} disabled={disabled} onChange={patch => setValue(v => ({ ...v, ...patch }))} />
}
beforeEach(() => {
 Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
 vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
 vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
 client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 vi.stubGlobal('fetch',fetcher)
 fetcher.mockImplementation(async(path:string)=>new Response(JSON.stringify(path.includes('/sources?')?{items:[{source_id:'warehouse',name:'仓库',enabled:true,publishedRevision:1}],nextCursor:null}:{sourceVersion:{sourceId:'warehouse',revision:1,contentHash:'source'},catalogVersion:{sourceId:'warehouse',revision:1,contentHash:'catalog'},items:[{fieldRef:'warehouse.test.budget.project_id',database:'test',table:'budget',column:'project_id',dataType:'VARCHAR(20)',nullable:false,description:'项目',tableDescription:''}],nextCursor:null})))
 document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear();fetcher.mockReset();vi.unstubAllGlobals() })
async function mount(disabled = false) { await act(async () => root.render(<QueryClientProvider client={client}><Harness disabled={disabled} /></QueryClientProvider>)) }
async function field(label: string, value: string) {
 const input = document.querySelector<HTMLInputElement>('[aria-label="' + label + '"]')!
 await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })) })
}
async function click(text: string) { await act(async () => [...document.querySelectorAll('button')].find(b => b.textContent?.replaceAll(' ', '') === text)!.click()) }
it('edits filter values without altering the other policy rules', async () => {
 await mount(); await field('筛选 1 值 1', 'B')
 expect(current.filters[0].values).toEqual(['B'])
 expect(current.joins).toEqual(original.joins); expect(current.readinessPolicy).toEqual(original.readinessPolicy)
 expect(original.filters[0].values).toEqual(['A'])
})
it('adds and removes paired join keys together while preserving cardinality', async () => {
 await mount(); await click('添加关联键1')
 await field('关联 1 左键 2', 'warehouse.test.budget.year'); await field('关联 1 右键 2', 'warehouse.test.actual.year')
 expect(current.joins[0].leftKeys).toHaveLength(2); expect(current.joins[0].rightKeys).toHaveLength(2)
 expect(current.joins[0].cardinality).toBe('many_to_one')
 await click('移除关联键1-1')
 expect(current.joins[0].leftKeys).toEqual(['warehouse.test.budget.year'])
 expect(current.joins[0].rightKeys).toEqual(['warehouse.test.actual.year'])
})
it('edits expected periods and groups without replacing watermark settings', async () => {
 await mount(); await field('预期期间 1 结束', '2026-10-01'); await field('预期分组 1 维度 1 值', 'B')
 expect(current.readinessPolicy.expectedPeriods).toEqual([{ start: '2026-01-01', end: '2026-10-01' }])
 expect(current.readinessPolicy.expectedGroups).toEqual([[{ dimensionId: 'project', value: 'B' }]])
 expect(current.readinessPolicy.maximumDelaySeconds).toBe(3600)
 expect(current.readinessPolicy.emptyObservation).toBe('unknown')
})
it('requires explicit removal and prevents edits during a pending write', async () => {
 await mount(true)
 expect([...document.querySelectorAll('input')].every(i => i.disabled)).toBe(true)
 expect([...document.querySelectorAll('button')].every(b => b.disabled)).toBe(true)
 expect(current).toEqual(original)
})
it('keeps filter value types explicit when switching between text, number, boolean and null', async () => {
 await mount()
 async function choose(text: string) {
  const select = document.querySelector('[aria-label="筛选 1 值 1类型"]')!
  await act(async () => select.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)) })
  const option = [...document.querySelectorAll('.ant-select-item-option-content')].find(item => item.textContent === text)!
  await act(async () => option.dispatchEvent(new MouseEvent('click', { bubbles: true })))
 }
 await choose('数字'); expect(current.filters[0].values).toEqual([0])
 await choose('布尔值'); expect(current.filters[0].values).toEqual([false])
 await choose('空值'); expect(current.filters[0].values).toEqual([null])
 await choose('文本'); expect(current.filters[0].values).toEqual([''])
})

async function until(check:()=>void){for(let i=0;i<70;i++){await act(async()=>{await new Promise(r=>setTimeout(r,15))});try{check();return}catch{}}check()}
it('adopts filter join and watermark fields independently without changing values pairs or readiness expectations',async()=>{
 await mount();expect(fetcher).not.toHaveBeenCalled()
 for(const label of ['筛选 1 字段','关联 1 左键 1','关联 1 右键 1','源水位字段']){
  await click(('从已发布目录选择'+label).replaceAll(' ',''))
  const area=document.querySelector('[aria-label="'+label+'目录选择"]')!
  await until(()=>expect([...area.querySelectorAll('button')].find(b=>b.textContent?.includes('浏览 仓库'))).toBeTruthy())
  await act(async()=>[...area.querySelectorAll('button')].find(b=>b.textContent?.includes('浏览 仓库'))!.click())
  await until(()=>expect([...area.querySelectorAll('button')].find(b=>b.textContent?.includes('采用字段 warehouse.test.budget.project_id'))).toBeTruthy())
  await act(async()=>[...area.querySelectorAll('button')].find(b=>b.textContent?.includes('采用字段 warehouse.test.budget.project_id'))!.click())
 }
 expect(current.filters).toEqual([{...original.filters[0],fieldRef:'warehouse.test.budget.project_id'}])
 expect(current.joins).toEqual([{...original.joins[0],leftKeys:['warehouse.test.budget.project_id'],rightKeys:['warehouse.test.budget.project_id']}])
 expect(current.readinessPolicy).toEqual({...original.readinessPolicy,watermarkField:'warehouse.test.budget.project_id'})
 expect(fetcher.mock.calls.every(([path,options])=>path.includes('companyId=a')&&options.method==='GET')).toBe(true)
})
