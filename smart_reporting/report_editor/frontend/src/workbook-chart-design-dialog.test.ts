import { afterEach, expect, it, vi } from 'vitest'
import { createChartDesignDialog } from './workbook-chart-design-dialog'

afterEach(() => document.body.replaceChildren())

it('prefills the chart title and submits the user text instead of a fixed title', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'title', initialTitle: '原始标题' })
  const input = document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
  expect(input.value).toBe('原始标题')
  input.value = '季度销售 & 订单'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: 'xl/charts/chart1.xml', title: '季度销售 & 订单' }, expect.objectContaining({ property: 'title' }))
  dialog.dispose()
})

it.each(['none', 'left', 'right', 'top', 'bottom'])('submits legend position %s', legend => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'legend' })
  document.querySelector<HTMLSelectElement>('[aria-label="图例位置"]')!.value = legend
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: 'xl/charts/chart1.xml', legend }, expect.objectContaining({ property: 'legend' }))
  dialog.dispose()
})

it('requires a legend choice and rejects an oversized title without applying', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  const target = { chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1' }
  dialog.open({ ...target, property: 'legend' })
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alert"]')!.textContent).toContain('请选择图例位置')
  dialog.open({ ...target, property: 'title' })
  document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!.value = '长'.repeat(201)
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alert"]')!.textContent).toContain('200')
  dialog.dispose()
})

it('submits the selected axis title and preserves the captured chart identity', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart4.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'categoryTitle' })
  const input = document.querySelector<HTMLInputElement>('[aria-label="分类轴标题"]')!
  input.value = '月份'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: 'xl/charts/chart4.xml', axisTitles: { category: '月份' } }, expect.objectContaining({ property: 'categoryTitle' }))
  dialog.dispose()
})

it('clears a blank axis title and allows choosing no data labels', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart2.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'valueTitle' })
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenLastCalledWith({ chartPath: 'xl/charts/chart2.xml', axisTitles: { value: null } }, expect.objectContaining({ property: 'valueTitle' }))
  dialog.open({ chartPath: 'xl/charts/chart2.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'labels' })
  document.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')!.value = 'none'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenLastCalledWith({ chartPath: 'xl/charts/chart2.xml', dataLabels: 'none' }, expect.objectContaining({ property: 'labels' }))
  dialog.dispose()
})

it('cancels without applying a chart edit', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'categoryTitle' })
  document.querySelector<HTMLButtonElement>('[data-chart-design-cancel]')!.click()
  expect(apply).not.toHaveBeenCalled()
  dialog.dispose()
})

it('submits grouped chart format and gridline settings', () => {
  const apply = vi.fn(), dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart3.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'format' })
  document.querySelector<HTMLSelectElement>('[aria-label="图表分组"]')!.value = 'stacked'
  document.querySelector<HTMLInputElement>('[aria-label="显示主网格线"]')!.checked = true
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({ chartPath: 'xl/charts/chart3.xml', grouping: 'stacked', gridlines: true }, expect.objectContaining({ property: 'format' }))
  dialog.dispose()
})

it('keeps the edited title until the asynchronous chart commit succeeds', async () => {
  let finish!: () => void
  const apply = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
  const dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'title', initialTitle: '原始标题' })
  const input = document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
  input.value = '尚未成功写回的标题'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(document.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(false)
  expect(input.value).toBe('尚未成功写回的标题')
  finish()
  await vi.waitFor(() => expect(document.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(true))
  dialog.dispose()
})

it('retains the failed title and error, then allows a successful retry', async () => {
  let reject!: (reason: Error) => void
  const pending = new Promise<void>((_, fail) => { reject = fail })
  void pending.catch(() => undefined)
  const apply = vi.fn().mockReturnValueOnce(pending).mockResolvedValueOnce(undefined)
  const dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart2.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'title', initialTitle: '原始标题' })
  const input = document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
  input.value = '保留我的修改'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  reject(new Error('图表来源已变化，请重试'))
  await vi.waitFor(() => expect(document.querySelector('[role="alert"]')!.textContent).toContain('图表来源已变化，请重试'))
  expect(document.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(false)
  expect(input.value).toBe('保留我的修改')
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  await vi.waitFor(() => expect(document.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(true))
  expect(apply).toHaveBeenCalledTimes(2)
  dialog.dispose()
})

it('prevents duplicate submission and user cancellation while a commit is pending', async () => {
  let finish!: () => void
  const apply = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
  const dialog = createChartDesignDialog(document.body, apply)
  dialog.open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'title' })
  const overlay = document.querySelector<HTMLElement>('[role="dialog"]')!, form = overlay.querySelector('form')!
  form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  overlay.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  overlay.click()
  overlay.querySelector<HTMLButtonElement>('[data-chart-design-cancel]')!.click()
  expect(apply).toHaveBeenCalledOnce()
  expect(overlay.hidden).toBe(false)
  expect(overlay.querySelector('section')!.getAttribute('aria-busy')).toBe('true')
  expect([...form.querySelectorAll<HTMLInputElement>('input,select,button')].every(control => control.disabled)).toBe(true)
  expect(dialog.isApplying()).toBe(true)
  const progress = overlay.querySelector<HTMLElement>('[role="status"]')!
  expect(document.activeElement).toBe(progress)
  for (const shiftKey of [false, true]) {
    const event = new KeyboardEvent('keydown', { key: 'Tab', shiftKey, bubbles: true, cancelable: true })
    progress.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(progress)
  }
  document.body.focus()
  const outsideTab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
  window.dispatchEvent(outsideTab)
  expect(outsideTab.defaultPrevented).toBe(true)
  expect(document.activeElement).toBe(progress)
  finish()
  await vi.waitFor(() => expect(overlay.hidden).toBe(true))
  expect(dialog.isApplying()).toBe(false)
  dialog.dispose()
})

it.each(['resolve', 'reject', 'dispose'] as const)('ignores a stale %s receipt after an external lifecycle change', async mode => {
  let finish!: () => void, fail!: (reason: Error) => void
  const pending = new Promise<void>((resolve, reject) => { finish = resolve; fail = reject })
  const dialog = createChartDesignDialog(document.body, () => pending)
  dialog.open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'title' })
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  if (mode === 'dispose') dialog.dispose()
  else {
    dialog.close()
    dialog.open({ chartPath: 'xl/charts/chart2.xml', sheetId: 'sheet-1', sheetName: 'Sheet1', property: 'title', initialTitle: '第二张图' })
  }
  if (mode === 'reject') fail(new Error('过期失败'))
  else finish()
  await pending.catch(() => undefined)
  if (mode === 'dispose') expect(document.querySelector('[role="dialog"]')).toBeNull()
  else {
    expect(document.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(false)
    expect(document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!.value).toBe('第二张图')
    expect(document.querySelector('[role="alert"]')!.textContent).toBe('')
    dialog.dispose()
  }
})

it('blocks only ineffective scatter off requests and resets the restriction on reopen',()=>{
 const apply=vi.fn(),dialog=createChartDesignDialog(document.body,apply)
 const target={chartPath:'xl/charts/chart1.xml',sheetId:'sheet-1',sheetName:'Sheet1',property:'labels' as const}
 try{
  dialog.open({...target,initial:{dataLabels:'value',dataLabelsOffUnavailable:true}})
  const labels=document.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')!
  expect(labels.querySelector<HTMLOptionElement>('option[value="none"]')!.disabled).toBe(true)
  expect(document.body.textContent).toContain('首个系列')
  labels.value='none';document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alert"]')!.textContent).toContain('首个系列')
  dialog.open({...target,initial:{dataLabels:'value'}})
  expect(labels.querySelector<HTMLOptionElement>('option[value="none"]')!.disabled).toBe(false)
  labels.value='none';document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  expect(apply).toHaveBeenCalledWith({chartPath:target.chartPath,dataLabels:'none'},expect.anything())
 }finally{dialog.dispose()}
})
