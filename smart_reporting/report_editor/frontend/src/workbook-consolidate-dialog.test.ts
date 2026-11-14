import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => document.body.replaceChildren())

it('keeps source references, counts pending input, limits label functions and retries with the captured target', async () => {
  const path = './workbook-consolidate-dialog'
  const { createConsolidateDialog } = await import(path)
  const apply = vi.fn().mockImplementationOnce(() => { throw new Error('目标与来源重叠') })
  const dialog = createConsolidateDialog(document.body, apply)
  const target = { workbookId: 'book', sheetId: 'sheet-1', row: 5, column: 0, defaultReference: "'O''Brien'!A1:B3", targetLabel: 'Summary!A6' }
  dialog.open(target); target.sheetId = 'sheet-2'
  const overlay = document.querySelector<HTMLElement>('[aria-label="合并计算"]')!
  const reference = overlay.querySelector<HTMLInputElement>('[aria-label="引用位置"]')!
  const add = overlay.querySelector<HTMLButtonElement>('[data-action="add"]')!
  const fn = overlay.querySelector<HTMLSelectElement>('[aria-label="函数"]')!
  const labels = overlay.querySelector<HTMLInputElement>('[aria-label="使用左列标签"]')!
  expect(reference.value).toBe("'O''Brien'!A1:B3")
  add.click(); reference.value = "'O''Brien'!A1:B3"; add.click()
  expect(overlay.querySelectorAll('[data-reference]')).toHaveLength(1)
  fn.value = 'max'; labels.checked = true; labels.dispatchEvent(new Event('change'))
  expect(fn.value).toBe('sum')
  expect([...fn.options].map(option => option.value)).toEqual(['sum', 'count', 'average'])
  reference.value = 'Other!A1:B2'
  overlay.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply).toHaveBeenCalledWith({ workbookId: 'book', sheetId: 'sheet-1', row: 5, column: 0 }, { fn: 'sum', leftLabels: true, references: ["'O''Brien'!A1:B3", 'Other!A1:B2'] })
  expect(overlay.hidden).toBe(false)
  expect(overlay.querySelector('[role="alert"]')!.textContent).toBe('目标与来源重叠')
  overlay.querySelector<HTMLButtonElement>('[data-reference] button')!.click()
  expect(overlay.querySelectorAll('[data-reference]')).toHaveLength(0)
  overlay.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(apply.mock.calls[1][1].references).toEqual(['Other!A1:B2'])
  expect(overlay.hidden).toBe(true)
  dialog.dispose()
})

async function setup(apply=vi.fn()) {
  const {createConsolidateDialog}=await import('./workbook-consolidate-dialog')
  const dialog=createConsolidateDialog(document.body,apply)
  dialog.open({workbookId:'book',sheetId:'sheet',row:0,column:4,defaultReference:'',targetLabel:'Summary!E1'})
  const overlay=document.querySelector<HTMLElement>('[role="dialog"]')!
  return {dialog,overlay,reference:overlay.querySelector<HTMLInputElement>('[aria-label="引用位置"]')!,add:overlay.querySelector<HTMLButtonElement>('[data-action="add"]')!}
}

it('provides named reading regions while keeping actions separate from the scrolling references', async()=>{
  const {dialog,overlay}=await setup(),card=overlay.querySelector('.modal-card')!
  expect(card.querySelector(':scope > header h2')?.textContent).toBe('合并计算')
  expect(card.querySelector(':scope > form > footer button[type="submit"]')).not.toBeNull()
  for(const label of ['所有引用位置','合并计算说明','合并计算范围','合并计算引用状态','合并计算错误']){
    const region=overlay.querySelector<HTMLElement>(`[aria-label="${label}"]`)
    expect(region,`${label}可聚焦阅读`).not.toBeNull();expect(region?.tabIndex).toBe(0)
  }
  dialog.dispose()
})

it('keeps keyboard focus on the next or previous reference after removal, then returns to input', async()=>{
  const {dialog,overlay,reference,add}=await setup()
  for(const value of ['Source!A1','Source!A2','Source!A3']){reference.value=value;add.click()}
  const middle=overlay.querySelector<HTMLButtonElement>('[aria-label="删除引用 Source!A2"]')!;middle.focus();middle.click()
  expect(document.activeElement?.getAttribute('aria-label')).toBe('删除引用 Source!A3')
  expect(overlay.querySelector('[role="status"]')?.textContent).toContain('2')
  overlay.querySelector<HTMLButtonElement>('[aria-label="删除引用 Source!A3"]')!.click()
  expect(document.activeElement?.getAttribute('aria-label')).toBe('删除引用 Source!A1')
  overlay.querySelector<HTMLButtonElement>('[aria-label="删除引用 Source!A1"]')!.click()
  expect(document.activeElement).toBe(reference)
  expect(overlay.querySelectorAll('[data-reference]')).toHaveLength(0)
  expect(overlay.querySelector('[role="status"]')?.textContent).toContain('0')
  dialog.dispose()
})

it('reveals add and submit errors without losing the reference or stealing input focus', async()=>{
  const {dialog,overlay,reference,add}=await setup(vi.fn(()=>{throw new Error('目标与来源重叠')}))
  const error=overlay.querySelector<HTMLElement>('[role="alert"]')!,reveal=vi.fn();error.scrollIntoView=reveal
  reference.value='bad reference';reference.focus();add.click()
  expect(error.textContent).toContain('引用位置无效');expect(reveal).toHaveBeenCalledWith({block:'nearest'});expect(document.activeElement).toBe(reference);expect(reference.value).toBe('bad reference')
  reference.value='Source!A1';overlay.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true}))
  expect(error.textContent).toBe('目标与来源重叠');expect(reference.value).toBe('Source!A1');expect(document.activeElement).toBe(reference);expect(reveal).toHaveBeenCalledTimes(2)
  dialog.dispose()
})

it.each(['composition','legacy','handled'])('受保护Enter保留合并计算的未添加引用：%s', async protection=>{
 const apply=vi.fn(),{dialog,overlay,reference}=await setup(apply)
 try{
  reference.value='Source!A1:B3';reference.focus()
  const event=new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0})
  if(protection==='handled')event.preventDefault()
  reference.dispatchEvent(event)
  expect(reference.value).toBe('Source!A1:B3');expect(overlay.querySelectorAll('[data-reference]')).toHaveLength(0);expect(document.activeElement).toBe(reference);expect(apply).not.toHaveBeenCalled()
  reference.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))
  expect(reference.value).toBe('');expect(overlay.querySelectorAll('[data-reference]')).toHaveLength(1);expect(apply).not.toHaveBeenCalled()
 }finally{dialog.dispose()}
})
