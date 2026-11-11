import { afterEach, expect, it, vi } from 'vitest'
import { applyWorkbookRibbonCommand, mountWorkbookRibbon, type WorkbookPageSetupState } from './workbook-ribbon'

afterEach(() => { document.body.replaceChildren() })

it('opens pivot filters and editable-range management only on editable unprotected sheets', () => {
  const command = vi.fn(); let protectedSheet = false, editable = true
  const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => editable, rotation: () => 0,
    protection: () => ({ sheet: { protected: protectedSheet }, workbook: { locked: false } }) })
  for (const [tab, ids] of [['Insert', ['slicer-open', 'timeline-open']], ['Review', ['allow-edit-ranges-open']]] as const) {
    document.querySelector<HTMLButtonElement>(`[data-ribbon-tab="${tab}"]`)!.click()
    for (const id of ids) {
      const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
      expect(button.disabled, id).toBe(false)
      button.click(); expect(command).toHaveBeenLastCalledWith(id)
      protectedSheet = true; ribbon.refreshState(); expect(button.disabled, id).toBe(true)
      protectedSheet = false; editable = false; ribbon.refreshState(); expect(button.disabled, id).toBe(true)
      editable = true; ribbon.refreshState()
    }
  }
  ribbon.dispose()
})

it('toggles cell superscript and subscript through Univer style patches', () => {
  let current = 1
  const setValues = vi.fn((values: Array<Array<{ s: { va: number } }>>) => { current = values[0]![0]!.s.va })
  const range: any = { getHeight: () => 1, getWidth: () => 1, getCellStyleData: () => ({ va: current }), setValues }
  const workbook: any = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => range }) }) }
  expect(applyWorkbookRibbonCommand('superscript', workbook)).toBe(true)
  expect(current).toBe(3)
  expect(applyWorkbookRibbonCommand('superscript', workbook)).toBe(true)
  expect(current).toBe(1)
  expect(applyWorkbookRibbonCommand('subscript', workbook)).toBe(true)
  expect(current).toBe(2)
  expect(setValues).toHaveBeenCalledTimes(3)
})

it('opens header/footer editing and disables it on protected sheets', () => {
  const command = vi.fn(); let protectedSheet = false
  const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => true, rotation: () => 0,
    protection: () => ({ sheet: { protected: protectedSheet }, workbook: { locked: false } }) })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Insert"]')!.click()
  const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="header-footer-open"]')!
  expect(button).not.toBeNull(); expect(button.disabled).toBe(false)
  button.click(); expect(command).toHaveBeenCalledWith('header-footer-open')
  protectedSheet = true; ribbon.refreshState(); expect(button.disabled).toBe(true)
  ribbon.dispose()
})

it('opens the read-only queries panel on protected or saved sheets and disables it while unavailable', () => {
  const command = vi.fn(); let available = true
  const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => false, rotation: () => 0,
    queries: () => ({ available }), protection: () => ({ sheet: { protected: true }, workbook: { locked: false } }) })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="queries-open"]')!
  expect(button).not.toBeNull(); expect(button.disabled).toBe(false)
  expect(button.querySelector('svg')).not.toBeNull()
  button.click(); expect(command).toHaveBeenCalledWith('queries-open')
  available = false; ribbon.refreshState(); expect(button.disabled).toBe(true)
  button.click(); expect(command).toHaveBeenCalledTimes(1)
  ribbon.dispose()
})

it('opens CSV import with a source icon and disables it for read-only or protected sheets', () => {
  const command = vi.fn()
  let editable = true, protectedSheet = false
  const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => editable, rotation: () => 0,
    protection: () => ({ sheet: { protected: protectedSheet }, workbook: { locked: false } }) })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="import-csv"]')!
  expect(button.disabled).toBe(false)
  expect(button.textContent).toContain('导入 CSV')
  expect(button.querySelector('svg')).not.toBeNull()
  button.click(); expect(command).toHaveBeenCalledWith('import-csv')
  editable = false; ribbon.refreshState(); expect(button.disabled).toBe(true)
  editable = true; protectedSheet = true; ribbon.refreshState(); expect(button.disabled).toBe(true)
  button.click(); expect(command).toHaveBeenCalledTimes(1)
  ribbon.dispose()
})

it('opens the native conditional formatting manager and prevents protected edits', () => {
  const command = vi.fn()
  let protectedSheet = false
  const ribbon = mountWorkbookRibbon(document.body, command, {
    editable: () => true, rotation: () => 0,
    protection: () => ({ sheet: { protected: protectedSheet }, workbook: { locked: false } }),
  })
  const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="cf-open"]')!
  expect(button.disabled).toBe(false)
  button.click(); expect(command).toHaveBeenLastCalledWith('cf-open')
  protectedSheet = true; ribbon.refreshState()
  expect(button.disabled).toBe(true)
  button.click(); expect(command).toHaveBeenCalledTimes(1)
  ribbon.dispose()
})

it('exposes the native right-to-left view action with current direction', () => {
  const command = vi.fn()
  const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => true, rotation: () => 0,
    rightToLeft: () => ({ active: true, available: true }) })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
  const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="toggle-right-to-left"]')!
  expect(button.disabled).toBe(false)
  expect(button.getAttribute('aria-pressed')).toBe('true')
  button.click(); expect(command).toHaveBeenCalledWith('toggle-right-to-left')
  ribbon.dispose()
})

it('toggles headings as a view action and reflects the current state', () => {
  const command = vi.fn()
  let visible = true
  const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => false, rotation: () => 0,
    headings: () => ({ visible, available: true }) })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
  const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="toggle-headings"]')!
  expect(button.disabled).toBe(false)
  expect(button.getAttribute('aria-pressed')).toBe('true')
  button.click(); expect(command).toHaveBeenCalledWith('toggle-headings')
  visible = false; ribbon.refreshState()
  expect(button.getAttribute('aria-pressed')).toBe('false')
  ribbon.dispose()
})

it('dispatches source cell style presets and prevents edits on a protected sheet', () => {
  const command = vi.fn()
  let protectedSheet = false
  const ribbon = mountWorkbookRibbon(document.body, command, {
    editable: () => true, rotation: () => 0,
    protection: () => ({ sheet: { protected: protectedSheet }, workbook: { locked: false } }),
  })
  const select = document.querySelector<HTMLSelectElement>('[data-ribbon-control="cell-style"]')
  expect(select).not.toBeNull()
  expect(select!.options).toHaveLength(15)
  select!.value = 'input'; select!.dispatchEvent(new Event('change'))
  expect(command).toHaveBeenCalledWith('cell-style:input')
  expect(select!.value).toBe('')
  protectedSheet = true; ribbon.refreshState()
  expect(select!.disabled).toBe(true)
  ribbon.dispose()
})

it('opens the data table command from Data and respects read-only state', () => {
  const command = vi.fn()
  let editable = true
  const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => editable, rotation: () => 0 })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="data-table-open"]')!
  expect(button).not.toBeNull()
  button.click()
  expect(command).toHaveBeenCalledWith('data-table-open')
  editable = false; ribbon.refreshState()
  expect(button.disabled).toBe(true)
  ribbon.dispose()
})

it('dispatches outline grouping and detail commands and disables them in read-only mode', () => {
  const command = vi.fn()
  let editable = true
  const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => editable, rotation: () => 0 })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  const ids = ['outline-group:rows', 'outline-group:cols', 'outline-ungroup:rows', 'outline-ungroup:cols', 'outline-hide-detail', 'outline-show-detail']
  for (const id of ids) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
    expect(button.disabled).toBe(false)
    button.click()
    expect(command).toHaveBeenLastCalledWith(id)
  }
  editable = false; ribbon.refreshState()
  for (const id of ids) expect(document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!.disabled).toBe(true)
  ribbon.dispose()
})

it('dispatches explicit outline detail, clear and summary controls with current summary state', () => {
  const command = vi.fn()
  let below = true, right = false
  const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => true, rotation: () => 0,
    outlineSummary: () => ({ below, right }) })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  for (const id of ['outline-hide-detail:rows', 'outline-hide-detail:cols', 'outline-show-detail:rows', 'outline-show-detail:cols', 'outline-clear', 'outline-summary-below', 'outline-summary-right']) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button, id).not.toBeNull()
    expect(button!.disabled).toBe(false); button!.click()
    expect(command).toHaveBeenLastCalledWith(id)
  }
  const summary = (axis: string) => document.querySelector<HTMLButtonElement>(`[data-ribbon-command="outline-summary-${axis}"]`)!
  expect(summary('below').getAttribute('aria-pressed')).toBe('true')
  expect(summary('right').getAttribute('aria-pressed')).toBe('false')
  below = false; right = true; ribbon.refreshState()
  expect(summary('below').getAttribute('aria-pressed')).toBe('false')
  expect(summary('right').getAttribute('aria-pressed')).toBe('true')
  ribbon.dispose()
})

it('shows contextual table properties and commits the captured table identity without losing an in-progress name', () => {
  document.body.innerHTML = '<main></main>'
  let table: { id: string; name: string; range: string; reason?: string } | undefined
  const renameTable = vi.fn(), resizeTable = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), {
    rotation: () => 0, editable: () => true, table: () => table, renameTable, resizeTable,
  })
  expect(document.querySelector('[data-ribbon-tab="Table Design"]')).toBeNull()
  table = { id: 'file-table-sheet-1', name: 'Staff', range: 'A1:B3' }
  ribbon.refreshState()
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Table Design"]')!.click()
  const input = document.querySelector<HTMLInputElement>('[aria-label="表格名称"]')!
  expect(input.value).toBe('Staff')
  expect(document.querySelector('[data-ribbon-control="table-range"]')!.textContent).toBe('A1:B3')
  document.querySelector<HTMLButtonElement>('[data-ribbon-control="table-resize"]')!.click()
  expect(resizeTable).toHaveBeenCalledWith('file-table-sheet-1', 'A1:B3')
  input.focus(); input.value = 'Employees'; ribbon.refreshState()
  expect(input.value).toBe('Employees')
  input.dispatchEvent(new Event('change', { bubbles: true }))
  expect(renameTable).toHaveBeenCalledWith('file-table-sheet-1', 'Employees')
  table = { ...table, name: 'Employees', reason: '工作表受保护' }
  ribbon.refreshState()
  expect(input.disabled).toBe(true)
  expect(input.title).toBe('工作表受保护')
  expect(document.querySelector<HTMLButtonElement>('[data-ribbon-control="table-resize"]')!.disabled).toBe(true)
  table = undefined; ribbon.refreshState()
  expect(document.querySelector('[data-ribbon-tab="Table Design"]')).toBeNull()
  expect(document.querySelector('[data-ribbon-tab="Home"]')!.getAttribute('aria-selected')).toBe('true')
  ribbon.dispose()
})

it('renders the GenOffice ribbon tabs and dispatches supported workbook commands', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand)

  expect([...document.querySelectorAll('[role=tab]')].map(tab => tab.textContent)).toEqual([
    '文件', '开始', '插入', '页面布局', '公式', '数据', '审阅', '视图', '图表设计',
  ])
  document.querySelector<HTMLButtonElement>('[data-ribbon-command="bold"]')!.click()
  const font = document.querySelector<HTMLSelectElement>('[data-ribbon-control="font-family"]')!
  font.value = 'Calibri'
  font.dispatchEvent(new Event('change', { bubbles: true }))
  const increaseDecimal = document.querySelector<HTMLButtonElement>('[data-ribbon-command="decimal-inc"]')!
  expect(increaseDecimal.disabled).toBe(false)
  increaseDecimal.click()
  document.querySelector<HTMLButtonElement>('[data-ribbon-command="autofn:SUM"]')!.click()
  expect([...document.querySelectorAll('[data-ribbon-command^="autofn:"]')].map(button => button.textContent)).toEqual([
    '自动求和', '平均值', '计数值', '最大值', '最小值',
  ])
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Insert"]')!.click()

  expect(onCommand.mock.calls).toEqual([['bold'], ['font-family:Calibri'], ['decimal-inc'], ['autofn:SUM']])
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Home"]')!.click()
  // 剪贴板与格式刷已接入官方命令；上标仍缺引擎字段，保留以原因禁用。
  for (const id of ['paste', 'format-painter']) expect(document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!.dataset.unavailableReason, id).toBeUndefined()
  const deferred = document.querySelector<HTMLButtonElement>('[data-ribbon-command="superscript"]')!
  expect(deferred.disabled).toBe(true)
  expect(deferred.title).toContain('上标')
  const rotation = document.querySelector<HTMLButtonElement>('[data-ribbon-command="rotate:45"]')!
  expect(rotation.disabled).toBe(false)
  expect(rotation.title).not.toContain('does not capture text rotation')
  ribbon.dispose()
})

it('dispatches table totals and style changes with the current table identity and reflects protection', () => {
  document.body.innerHTML = '<main></main>'
  let table = { id: 'staff', name: 'Staff', range: 'A1:B3', totals: false, style: 'TableStyleMedium4', reason: undefined as string | undefined }
  const setTableTotals = vi.fn(), setTableStyle = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), {
    rotation: () => 0, editable: () => true, table: () => table, setTableTotals, setTableStyle,
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Table Design"]')!.click()
  const totals = document.querySelector<HTMLInputElement>('[aria-label="汇总行"]')!
  totals.click()
  expect(setTableTotals).toHaveBeenCalledWith('staff', true)
  const style = document.querySelector<HTMLSelectElement>('[aria-label="表格样式"]')!
  expect(style.value).toBe('TableStyleMedium4')
  expect(style.options).toHaveLength(61)
  style.value = 'TableStyleDark3'; style.dispatchEvent(new Event('change'))
  expect(setTableStyle).toHaveBeenCalledWith('staff', 'TableStyleDark3')
  table = { ...table, id: 'other', totals: true, style: '', reason: '工作表受保护' }; ribbon.refreshState()
  expect(totals.checked).toBe(true); expect(totals.disabled).toBe(true)
  expect(style.value).toBe(''); expect(style.disabled).toBe(true)
  ribbon.dispose()
})

it('reflects and changes the header row of the current table and respects read-only state', () => {
  document.body.innerHTML = '<main></main>'
  let table = { id: 'staff', name: 'Staff', range: 'A1:B3', header: true, reason: undefined as string | undefined }
  const setTableHeaderRow = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), {
    rotation: () => 0, editable: () => true, table: () => table, setTableHeaderRow,
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Table Design"]')!.click()
  const header = document.querySelector<HTMLInputElement>('[aria-label="标题行"]')!
  expect(header.checked).toBe(true)
  header.click()
  expect(setTableHeaderRow).toHaveBeenCalledWith('staff', false)
  table = { ...table, id: 'other', header: false }; ribbon.refreshState()
  expect(header.checked).toBe(false)
  header.click()
  expect(setTableHeaderRow).toHaveBeenLastCalledWith('other', true)
  table = { ...table, reason: '工作表受保护' }; ribbon.refreshState()
  expect(header.disabled).toBe(true)
  expect(header.title).toBe('工作表受保护')
  ribbon.dispose()
})

it('reflects filter buttons for the selected table and disables them without headers or edit permission', () => {
  document.body.innerHTML = '<main></main>'
  let table = { id: 'staff', name: 'Staff', range: 'A1:B3', header: true, filterButton: true, reason: undefined as string | undefined }
  const setTableFilterButton = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), {
    rotation: () => 0, editable: () => true, table: () => table, setTableFilterButton,
  } as any)
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Table Design"]')!.click()
  const filter = document.querySelector<HTMLInputElement>('[aria-label="筛选按钮"]')!
  expect(filter).not.toBeNull()
  expect(filter.checked).toBe(true)
  filter.click()
  expect(setTableFilterButton).toHaveBeenCalledWith('staff', false)
  table = { ...table, id: 'other', filterButton: false }; ribbon.refreshState()
  expect(filter.checked).toBe(false)
  filter.click()
  expect(setTableFilterButton).toHaveBeenLastCalledWith('other', true)
  table = { ...table, header: false }; ribbon.refreshState()
  expect(filter.disabled).toBe(true)
  table = { ...table, header: true, reason: '工作表受保护' }; ribbon.refreshState()
  expect(filter.disabled).toBe(true)
  expect(filter.title).toBe('工作表受保护')
  ribbon.dispose()
})

it('writes formatting through the selected Univer range and inserts a worksheet through the workbook', () => {
  const calls: unknown[][] = []
  const style = { bl: 0, it: 0, ul: { s: 0 } }
  let wrap = false
  const range = {
    getCellStyleData: () => style,
    getRow: () => 2,
    getColumn: () => 3,
    getHeight: () => 1, getWidth: () => 1,
    getWrap: () => wrap,
    setFontWeight: (value: 'bold' | 'normal' | null) => { calls.push(['bold', value]); style.bl = value === 'bold' ? 1 : 0 },
    setFontStyle: (value: 'italic' | 'normal' | null) => { calls.push(['italic', value]); style.it = value === 'italic' ? 1 : 0 },
    setValue: (patch: { s: { ul?: { s: number } } }) => { if (patch.s.ul) { calls.push(['underline', patch.s.ul.s === 1 ? 'underline' : 'none']); style.ul.s = patch.s.ul.s } },
    setFontLine: (value: 'underline' | 'line-through' | 'none' | null) => { calls.push(['underline', value]); style.ul.s = value === 'underline' ? 1 : 0 },
    setWrap: (value: boolean) => { calls.push(['wrap', value]); wrap = value },
    setFontFamily: (value: string) => calls.push(['font-family', value]),
    setFontSize: (value: number) => calls.push(['font-size', value]),
    setFontColor: (value: string) => calls.push(['font-color', value]),
    setBackgroundColor: (value: string) => calls.push(['fill', value]),
    setBorder: (...args: unknown[]) => calls.push(['border', ...args]),
    setNumberFormat: (value: string) => calls.push(['number-format', value]),
    setHorizontalAlignment: (...args: unknown[]) => calls.push(['align', ...args]),
    setVerticalAlignment: (...args: unknown[]) => calls.push(['valign', ...args]),
    merge: () => calls.push(['merge']),
    mergeAcross: () => calls.push(['merge-across']),
    breakApart: () => calls.push(['unmerge']),
    clearContent: () => calls.push(['clear-content']),
  }
  const workbook = {
    getActiveSheet: () => ({
      getSelection: () => ({ getActiveRange: () => range }),
      getRange: () => ({ setFormula: () => undefined, getCellStyleData: () => style }),
      insertRowsBefore: (...args: unknown[]) => calls.push(['insert-row', ...args]),
      deleteRows: (...args: unknown[]) => calls.push(['delete-row', ...args]),
      insertColumnsBefore: (...args: unknown[]) => calls.push(['insert-col', ...args]),
      deleteColumns: (...args: unknown[]) => calls.push(['delete-col', ...args]),
    }),
    insertSheet: () => calls.push(['insert-sheet']),
  } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  for (const command of [
    'bold', 'italic', 'underline', 'wrap', 'bold', 'italic', 'underline', 'wrap',
    'font-family:Arial', 'font-size:12', 'font-size:14', 'font-color:#000000', 'fill:#fff2cc', 'border:all',
    'format:0.00', 'format:0%', 'format:#,##0.00',
    'align:center', 'merge:cells', 'merge:unmerge', 'merge:across', 'clear-contents',
    'insert-row-here', 'delete-row-here', 'insert-col-here', 'delete-col-here',
  ] as const) {
    expect(applyWorkbookRibbonCommand(command, workbook)).toBe(true)
  }
  expect(applyWorkbookRibbonCommand('insert-sheet', workbook)).toBe(true)
  expect(calls).toEqual([
    ['bold', 'bold'], ['italic', 'italic'], ['underline', 'underline'], ['wrap', true],
    ['bold', 'normal'], ['italic', 'normal'], ['underline', 'none'], ['wrap', false],
    ['font-family', 'Arial'], ['font-size', 12], ['font-size', 14], ['font-color', '#000000'], ['fill', '#fff2cc'],
    ['border', 'all', 1, '#000000'],
    ['number-format', '0.00'], ['number-format', '0%'], ['number-format', '#,##0.00'],
    ['align', 'center'], ['merge'], ['unmerge'], ['merge-across'], ['clear-content'],
    ['insert-row', 2, 1], ['delete-row', 2, 1], ['insert-col', 3, 1], ['delete-col', 3, 1],
    ['insert-sheet'],
  ])
  expect(() => applyWorkbookRibbonCommand('rotate:45', workbook)).toThrow('当前工作簿未接入')
  const step = vi.fn()
  expect(applyWorkbookRibbonCommand('decimal-inc', workbook, step)).toBe(true)
  expect(applyWorkbookRibbonCommand('decimal-dec', workbook, step)).toBe(true)
  expect(step.mock.calls).toEqual([[1], [-1]])
  expect(() => applyWorkbookRibbonCommand('decimal-inc', workbook)).toThrow('当前工作簿未接入')
})

it('writes upstream AutoSum function formulas below every selected column', () => {
  const formulas: unknown[][] = []
  const range = { getRow: () => 2, getColumn: () => 1, getHeight: () => 3, getWidth: () => 2 }
  const workbook = {
    getActiveSheet: () => ({
      getSelection: () => ({ getActiveRange: () => range }),
      getRange: (...args: number[]) => ({ setFormula: (formula: string) => formulas.push([...args, formula]) }),
      insertRowsBefore: () => undefined, deleteRows: () => undefined,
      insertColumnsBefore: () => undefined, deleteColumns: () => undefined,
    }),
    insertSheet: () => undefined,
  } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  for (const [fn, expected] of [
    ['SUM', '=SUM(B3:B5)'], ['AVERAGE', '=AVERAGE(B3:B5)'], ['COUNT', '=COUNT(B3:B5)'],
    ['MAX', '=MAX(B3:B5)'], ['MIN', '=MIN(B3:B5)'],
  ] as const) {
    expect(applyWorkbookRibbonCommand(`autofn:${fn}`, workbook)).toBe(true)
    expect(formulas.at(-2)?.[2]).toBe(expected)
    expect(formulas.at(-1)?.[2]).toBe(expected.replaceAll('B', 'C'))
  }
  expect(formulas.map(([row, column]) => [row, column])).toEqual(Array.from({ length: 10 }, (_, index) => [5, index % 2 === 0 ? 1 : 2]))
})

it('rejects AutoSum for a single-row selection', () => {
  const workbook = {
    getActiveSheet: () => ({
      getSelection: () => ({ getActiveRange: () => ({ getRow: () => 0, getColumn: () => 0, getHeight: () => 1, getWidth: () => 1 }) }),
      getRange: () => { throw new Error('must not write') },
      insertRowsBefore: () => undefined, deleteRows: () => undefined,
      insertColumnsBefore: () => undefined, deleteColumns: () => undefined,
    }),
    insertSheet: () => undefined,
  } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  expect(() => applyWorkbookRibbonCommand('autofn:SUM', workbook)).toThrow('请至少选择两行')
})

it('renders source-localized sort actions and dispatches their upstream command ids', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  mountWorkbookRibbon(document.querySelector('main')!, onCommand)
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  const ascending = document.querySelector<HTMLButtonElement>('[data-ribbon-command="sort:asc"]')!
  const descending = document.querySelector<HTMLButtonElement>('[data-ribbon-command="sort:desc"]')!
  expect(ascending.textContent).toBe('升序')
  expect(descending.textContent).toBe('降序')
  expect(ascending.disabled).toBe(false)
  expect(descending.disabled).toBe(false)
  ascending.click()
  descending.click()
  expect(onCommand.mock.calls).toEqual([['sort:asc'], ['sort:desc']])
})

it('dispatches the source sort and filter actions including advanced filter', () => {
  document.body.innerHTML = '<main></main>'
  const command = vi.fn()
  mountWorkbookRibbon(document.querySelector('main')!, command)
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  for (const id of ['filter-toggle', 'filter-clear', 'filter-reapply', 'sort-custom-open', 'filter-advanced']) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.disabled, id).toBe(false)
    button!.click()
    expect(command).toHaveBeenLastCalledWith(id)
  }
})

it('dispatches clear formats/all through the official selection commands and refuses without the wiring', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  mountWorkbookRibbon(document.querySelector('main')!, onCommand)
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Home"]')!.click()
  const clearAll = document.querySelector<HTMLButtonElement>('[data-ribbon-command="clear-all"]')!
  const clearFormats = document.querySelector<HTMLButtonElement>('[data-ribbon-command="clear-formats"]')!
  expect(clearAll.textContent).toBe('全部清除')
  expect(clearFormats.textContent).toBe('清除格式')
  expect(clearAll.disabled).toBe(false)
  expect(clearFormats.disabled).toBe(false)
  clearFormats.click(); clearAll.click()
  expect(onCommand.mock.calls.map(([command]) => command)).toEqual(['clear-formats', 'clear-all'])

  const range = { getRow: () => 0, getColumn: () => 0, getHeight: () => 2, getWidth: () => 1 }
  const workbook = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => range }) }) } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  const kinds: ('all' | 'formats')[] = []
  const clearSelection = vi.fn((kind: 'all' | 'formats') => { kinds.push(kind); return true })
  expect(applyWorkbookRibbonCommand('clear-formats', workbook, undefined, undefined, undefined, clearSelection)).toBe(true)
  expect(applyWorkbookRibbonCommand('clear-all', workbook, undefined, undefined, undefined, clearSelection)).toBe(true)
  expect(clearSelection.mock.calls).toEqual([['formats'], ['all']])
  clearSelection.mockReturnValueOnce(false)
  expect(() => applyWorkbookRibbonCommand('clear-formats', workbook, undefined, undefined, undefined, clearSelection)).toThrow('清除未应用')
  expect(() => applyWorkbookRibbonCommand('clear-formats', workbook)).toThrow('未接入清除命令')
})

it('renders GenOffice Data Tools in source order with explicit native writeback limits', () => {
  document.body.innerHTML = '<main></main>'
  mountWorkbookRibbon(document.querySelector('main')!, vi.fn())
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  const groups = [...document.querySelectorAll<HTMLElement>('.workbook-ribbon-group')]
  const groupFor = (title: string) => groups.find(group => group.querySelector('h3')?.textContent === title)
  const dataTools = groupFor('数据工具')!
  const ids = [...dataTools.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
    .map(button => button.dataset.ribbonCommand)
  expect(ids).toEqual([
    'text-to-columns:2', 'text-to-columns:4', 'text-to-columns:8', 'text-to-columns:1',
    'flash-fill', 'remove-duplicates-open', 'dv-open', 'consolidate-open',
  ])
  const flash = dataTools.querySelector<HTMLButtonElement>('[data-ribbon-command="flash-fill"]')!
  for (const id of [1, 2, 4, 8]) expect(dataTools.querySelector<HTMLButtonElement>(`[data-ribbon-command="text-to-columns:${id}"]`)!.disabled).toBe(false)
  expect(dataTools.querySelector<HTMLButtonElement>('[data-ribbon-command="remove-duplicates-open"]')!.disabled).toBe(false)
  expect(flash.disabled).toBe(false)
  const validation = dataTools.querySelector<HTMLButtonElement>('[data-ribbon-command="dv-open"]')!
  expect(validation.disabled).toBe(false)
  expect(flash.textContent).toBe('快速填充')
  const consolidate = dataTools.querySelector<HTMLButtonElement>('[data-ribbon-command="consolidate-open"]')!
  expect(consolidate.textContent).toBe('合并计算')
  expect(consolidate.disabled).toBe(false)
  expect(consolidate.dataset.unavailableReason).toBeUndefined()
  const outline = groupFor('分级显示')!
  const outlineIds = [...outline.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
    .map(button => button.dataset.ribbonCommand)
  expect(outlineIds.at(-1)).toBe('subtotal-open')
  const subtotal = outline.querySelector<HTMLButtonElement>('[data-ribbon-command="subtotal-open"]')
  expect(subtotal?.textContent).toBe('分类汇总')
  expect(subtotal?.disabled).toBe(false)
  expect(subtotal?.dataset.unavailableReason).toBeUndefined()
})

it('dispatches the official sort-range command with absolute bounds for asc and desc', () => {
  const calls: unknown[][] = []
  const range = { getRow: () => 1, getColumn: () => 2, getHeight: () => 3, getWidth: () => 2 }
  const sheet = {
    getSelection: () => ({ getActiveRange: () => range }),
    getRange: () => { throw new Error('must not write cells directly') },
    insertRowsBefore: () => undefined, deleteRows: () => undefined,
    insertColumnsBefore: () => undefined, deleteColumns: () => undefined,
  }
  const workbook = { getActiveSheet: () => sheet, insertSheet: () => undefined } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  const sortRange = (bounds: { startRow: number; endRow: number; startColumn: number; endColumn: number; colIndex: number }, ascending: boolean) => {
    calls.push([{ ...bounds }, ascending]); return true
  }
  expect(applyWorkbookRibbonCommand('sort:asc', workbook, undefined, undefined, sortRange)).toBe(true)
  expect(applyWorkbookRibbonCommand('sort:desc', workbook, undefined, undefined, sortRange)).toBe(true)
  expect(calls).toEqual([
    [{ startRow: 1, endRow: 3, startColumn: 2, endColumn: 3, colIndex: 2 }, true],
    [{ startRow: 1, endRow: 3, startColumn: 2, endColumn: 3, colIndex: 2 }, false],
  ])
})

it('surfaces official sort failures and keeps the single-row guard', () => {
  const range = { getRow: () => 0, getColumn: () => 0, getHeight: () => 2, getWidth: () => 1 }
  const workbook = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => range }) }), insertSheet: () => undefined } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  expect(() => applyWorkbookRibbonCommand('sort:asc', workbook, undefined, undefined, () => false)).toThrow('排序未应用')
  expect(() => applyWorkbookRibbonCommand('sort:asc', workbook)).toThrow('未接入官方排序命令')
  const single = { getRow: () => 0, getColumn: () => 0, getHeight: () => 1, getWidth: () => 1 }
  const singleWorkbook = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => single }) }), insertSheet: () => undefined } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  expect(() => applyWorkbookRibbonCommand('sort:asc', singleWorkbook, undefined, undefined, () => true)).toThrow('请至少选择两行')
})

it('renders source-localized Home Alignment and Cells actions with their fixed command ids', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  mountWorkbookRibbon(document.querySelector('main')!, onCommand)
  const getLabel = (id: string) => document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)?.textContent
  const labels = new Map([...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
    .map(button => [button.dataset.ribbonCommand!, button.textContent ?? '']))
  expect(labels.get('valign:top')).toBe('顶端对齐')
  expect(labels.get('valign:middle')).toBe('垂直居中')
  expect(labels.get('valign:bottom')).toBe('底端对齐')
  expect(labels.get('align:left')).toBe('左对齐')
  expect(labels.get('align:center')).toBe('居中')
  expect(labels.get('align:right')).toBe('右对齐')
  expect(labels.get('merge:center')).toBe('合并后居中')
  expect(labels.get('merge:across')).toBe('跨越合并')
  expect(labels.get('merge:cells')).toBe('合并单元格')
  expect(labels.get('merge:unmerge')).toBe('取消单元格合并')
  expect(labels.get('insert-row-here')).toBe('插入行')
  expect(labels.get('delete-row-here')).toBe('删除行')
  expect(labels.get('insert-col-here')).toBe('插入列')
  expect(labels.get('delete-col-here')).toBe('删除列')
  expect(labels.get('clear-contents')).toBe('清除内容')
  for (const id of ['valign:top', 'align:center', 'merge:cells', 'merge:center', 'merge:across', 'merge:unmerge', 'insert-row-here', 'delete-row-here', 'insert-col-here', 'delete-col-here', 'clear-contents', 'insert-cells', 'delete-cells', 'format-cells']) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
    expect(button.disabled, id).toBe(false)
    button.click()
  }
  expect(onCommand.mock.calls.map(([command]) => command)).toEqual([
    'valign:top', 'align:center', 'merge:cells', 'merge:center', 'merge:across', 'merge:unmerge',
    'insert-row-here', 'delete-row-here', 'insert-col-here', 'delete-col-here', 'clear-contents', 'insert-cells', 'delete-cells', 'format-cells',
  ])
  expect(getLabel('clear-contents')).toBe('清除内容')
})

it('wires Find and Replace to the registered Univer dialogs', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  mountWorkbookRibbon(document.querySelector('main')!, onCommand)
  for (const [id, label] of [['find', '查找'], ['replace', '替换']]) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.textContent).toBe(label)
    expect(button?.disabled).toBe(false)
    button?.click()
    expect(onCommand).toHaveBeenLastCalledWith(id)
  }
})

it('renders the GenOffice Formulas Function Library with localized categories and safe states', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  mountWorkbookRibbon(document.querySelector('main')!, onCommand)
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Formulas"]')!.click()
  const expected = new Map([
    ['insert-function-open', '插入函数'], ['insert-function-open:All', '最近使用的函数'],
    ['insert-function-open:Financial', '财务'], ['insert-function-open:Logical', '逻辑'],
    ['insert-function-open:Text', '文本'], ['insert-function-open:Date & Time', '日期和时间'],
    ['insert-function-open:Lookup', '查找与引用'], ['insert-function-open:Math', '数学和三角函数'],
    ['autofn:SUM', '自动求和'], ['autofn:AVERAGE', '平均值'], ['autofn:COUNT', '计数'],
    ['autofn:MAX', '最大值'], ['autofn:MIN', '最小值'],
  ])
  for (const [id, label] of expected) {
    const button = [...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
      .find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.querySelector('span:not(.workbook-ribbon-icon)')?.textContent ?? button?.textContent, id).toBe(label)
  }
  expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="autofn:SUM"]')?.disabled).toBe(false)
  for (const id of [...expected.keys()].filter(id => id.startsWith('insert-function-open'))) {
    const button = [...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
      .find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.disabled, id).toBe(false)
    button?.click()
    expect(onCommand).toHaveBeenLastCalledWith(id)
  }
})

it('renders the GenOffice Review Comments and Notes commands with note-specific unavailable reasons', () => {
  document.body.innerHTML = '<main></main>'
  const reasons: Record<string, string> = {
    'note-open': '批注状态不可用', 'note-delete': '批注状态不可用',
    'note-prev': '批注集合不可用', 'note-next': '批注集合不可用', 'note-show-toggle': '批注可见状态不可用',
  }
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), {
    rotation: () => undefined, editable: () => true, hasSelection: () => true,
    noteReason: id => reasons[id],
  })
  ribbon.refreshState?.()
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Review"]')!.click()
  const expected = [
    ['note-open', '新建/编辑批注', '批注状态不可用'], ['note-delete', '删除', '批注状态不可用'],
    ['note-prev', '上一条', '批注集合不可用'], ['note-next', '下一条', '批注集合不可用'],
    ['note-show-toggle', '显示批注', '批注可见状态不可用'],
  ]
  const buttons = [...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
  for (const [id, label, reason] of expected) {
    const button = buttons.find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.querySelector('span:not(.workbook-ribbon-icon)')?.textContent ?? button?.textContent, id).toBe(label)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
  }
  expect(buttons.filter(button => button.dataset.ribbonCommand === 'note-open')).toHaveLength(2)
})

it('matches the GenOffice Review source groups, command ids, and safe disabled states', () => {
  document.body.innerHTML = '<main></main>'
  mountWorkbookRibbon(document.querySelector('main')!, vi.fn())
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Review"]')!.click()
  const groups = [...document.querySelectorAll<HTMLElement>('.workbook-ribbon-group')]
  expect(groups.map(group => group.querySelector('h3')?.textContent)).toEqual([
    '校对', '语言', '批注', '注释', '保护',
  ])
  const idsByGroup = groups.map(group => [...group.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
    .map(button => button.dataset.ribbonCommand))
  expect(idsByGroup).toEqual([
    ['workbook-statistics'], ['translate'],
    ['note-open', 'note-delete', 'note-prev', 'note-next', 'note-show-toggle'],
    ['note-open'], ['sheet-protect', 'workbook-protect', 'allow-edit-ranges-open'],
  ])
  const labels = new Map([...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
    .map(button => [button.dataset.ribbonCommand!, button.textContent ?? '']))
  expect(labels.get('workbook-statistics')).toBe('工作簿统计信息')
  expect(document.querySelector('[data-ribbon-command=translate] > span:not(.workbook-ribbon-icon)')?.textContent).toBe('翻译')
  expect(labels.get('sheet-protect')).toBe('保护工作表')
  expect(labels.get('workbook-protect')).toBe('保护工作簿')
  expect(labels.get('allow-edit-ranges-open')).toBe('允许编辑区域')
  for (const [id, reason] of [
    ['translate', '翻译操作'],
  ]) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
  }
  expect(document.querySelector('[data-ribbon-command="spell-check"]')).toBeNull()
  expect(document.querySelector('[data-ribbon-command="spellcheck-toggle"]')).toBeNull()
  expect(document.querySelector('[data-ribbon-command="workbook-change-password"]')).toBeNull()
  expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="workbook-statistics"]')!.disabled).toBe(false)
})

it('renders GenOffice View controls with a live gridline toggle and explicit unavailable states', () => {
  document.body.innerHTML = '<main></main>'
  mountWorkbookRibbon(document.querySelector('main')!, vi.fn())
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
  const buttons = [...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
  const expected = new Map([
    ['toggle-page-break-preview', '分页预览'], ['toggle-gridlines', '显示网格线'],
    ['toggle-formula-bar', '编辑栏'], ['toggle-headings', '显示标题'],
    ['toggle-right-to-left', '从右到左'], ['toggle-cross-highlight', '突出显示活动行和列'],
    ['zoom-reset', '重置缩放'], ['zoom-to-selection', '缩放到选定区域'],
    ['zoom-in', '放大'], ['zoom-out', '缩小'],
    ['new-window', '新建窗口'], ['arrange-all', '全部重排'], ['freeze-panes', '冻结窗格'],
    ['split-window', '拆分窗口'], ['hide-window', '隐藏窗口'], ['switch-window', '切换窗口'],
  ])
  for (const [id, label] of expected) {
    const button = buttons.find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.querySelector('span:not(.workbook-ribbon-icon)')?.textContent ?? button?.textContent, id).toBe(label)
  }
  expect(buttons.find(button => button.dataset.ribbonCommand === 'toggle-gridlines')?.disabled).toBe(false)
  for (const [id, reason] of [
    ['new-window', '桌面工作簿窗口'], ['arrange-all', '桌面工作簿窗口'],
 ['split-window', '拆分视口'],
    ['hide-window', '桌面工作簿窗口'], ['switch-window', '桌面工作簿窗口'],
  ]) {
    const button = buttons.find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
  }
  const fit = buttons.find(button => button.dataset.ribbonCommand === 'zoom-to-selection')!
  expect(fit.disabled).toBe(false)
})

it('keeps selection zoom available on protected and read-only sheets', () => {
  document.body.innerHTML = '<main></main>'
  const command = vi.fn()
  let ready = true
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, command, {
    editable: () => false, rotation: () => 0,
    zoomSelectionAvailable: () => ready,
    protection: () => ({ sheet: { protected: true }, workbook: { locked: false } }),
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
  const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="zoom-to-selection"]')!
  expect(button.disabled).toBe(false)
  button.click()
  expect(command).toHaveBeenCalledWith('zoom-to-selection')
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Review"]')!.click()
  const statistics = document.querySelector<HTMLButtonElement>('[data-ribbon-command="workbook-statistics"]')!
  expect(statistics.disabled).toBe(false)
  statistics.click()
  expect(command).toHaveBeenCalledWith('workbook-statistics')
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
  ready = false; ribbon.refreshState()
  expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="zoom-to-selection"]')!.disabled).toBe(true)
})

it('offers all source zoom presets and the full dialog while respecting view readiness', () => {
  document.body.innerHTML = '<main></main>'
  const command = vi.fn()
  let ready = true
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, command, {
    editable: () => false, rotation: () => 0, zoomSelectionAvailable: () => ready,
    protection: () => ({ sheet: { protected: true }, workbook: { locked: false } }),
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
  const dialog = document.querySelector<HTMLButtonElement>('[data-ribbon-command="zoom-open"]')!
  expect(dialog.disabled).toBe(false)
  dialog.click(); expect(command).toHaveBeenLastCalledWith('zoom-open')
  const presets = document.querySelector<HTMLSelectElement>('[data-ribbon-menu="zoom"]')!
  expect([...presets.options].map(option => option.value)).toEqual(['', '50', '75', '100', '125', '150', '200'])
  expect(presets.disabled).toBe(false)
  presets.value = '125'; presets.dispatchEvent(new Event('change'))
  expect(command).toHaveBeenLastCalledWith('zoom:125')
  expect(presets.value).toBe('')
  ready = false; ribbon.refreshState()
  expect(dialog.disabled).toBe(true); expect(presets.disabled).toBe(true)
})

it('toggles the active Univer worksheet gridlines without changing cell data', () => {
  const calls: boolean[] = []
  let hidden = false
  const workbook = { getActiveSheet: () => ({
    getSelection: () => ({ getActiveRange: () => null }),
    hasHiddenGridLines: () => hidden,
    setHiddenGridlines: (value: boolean) => { hidden = value; calls.push(value) },
    insertRowsBefore: vi.fn(), deleteRows: vi.fn(), insertColumnsBefore: vi.fn(), deleteColumns: vi.fn(),
  }), insertSheet: vi.fn() } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  expect(applyWorkbookRibbonCommand('toggle-gridlines', workbook)).toBe(true)
  expect(applyWorkbookRibbonCommand('toggle-gridlines', workbook)).toBe(true)
  expect(calls).toEqual([true, false])
})

it('renders Page Layout dropdowns with the source option sets and dispatches their commands', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  const state: WorkbookPageSetupState = {
    margins: 'custom', orientation: undefined, paperSize: undefined,
    fitToWidth: 2, fitToHeight: 0, printGridlines: true, printHeadings: false, printArea: 'A1:B4',
  }
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand, {
    rotation: () => undefined, editable: () => true, hasSelection: () => true, unavailableReason: () => undefined, pageSetup: () => state,
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Page Layout"]')!.click()
  const margins = document.querySelector<HTMLSelectElement>('[data-ribbon-control="page-margins"]')!
  expect([...margins.options].map(option => option.textContent)).toEqual(['自定义（保留文件边距）', '常规', '宽', '窄'])
  expect(margins.value).toBe('custom')
  const orientation = document.querySelector<HTMLSelectElement>('[data-ribbon-control="page-orientation"]')!
  expect([...orientation.options].map(option => option.value)).toEqual(['', 'portrait', 'landscape'])
  const paper = document.querySelector<HTMLSelectElement>('[data-ribbon-control="page-paper"]')!
  expect([...paper.options].map(option => option.textContent)).toEqual(['按文件保存', 'Letter', 'Legal', 'Tabloid', 'Executive', 'A3', 'A4', 'A5'])
  const fitWidth = document.querySelector<HTMLSelectElement>('[data-ribbon-control="page-fit:width"]')!
  expect([...fitWidth.options].map(option => option.value)).toEqual(['0', '1', '2', '3', '4', '5'])
  expect(fitWidth.value).toBe('2')
  expect(document.querySelector<HTMLSelectElement>('[data-ribbon-control="page-fit:height"]')!.value).toBe('0')
  expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="print-gridlines"]')!.getAttribute('aria-pressed')).toBe('true')
  const breaks = document.querySelector<HTMLSelectElement>('[data-ribbon-menu="page-breaks"]')!
  breaks.value = 'page-breaks:reset'
  breaks.dispatchEvent(new Event('change', { bubbles: true }))
  expect(breaks.value).toBe('')
  orientation.value = 'landscape'
  orientation.dispatchEvent(new Event('change', { bubbles: true }))
  fitWidth.value = '3'
  fitWidth.dispatchEvent(new Event('change', { bubbles: true }))
  document.querySelector<HTMLButtonElement>('[data-ribbon-command="print-headings"]')!.click()
  expect(onCommand.mock.calls).toEqual([
    ['page-breaks:reset'], ['page-orientation:landscape'], ['page-fit:width:3'], ['print-headings'],
  ])
  const scale = document.querySelector<HTMLButtonElement>('[data-ribbon-command="print-scale-open"]')!
  expect(scale.disabled).toBe(false)
  scale.click()
  expect(onCommand).toHaveBeenLastCalledWith('print-scale-open')
  ribbon.dispose()
})

it('keeps Page Layout controls non-editable without page-setup state', () => {
  document.body.innerHTML = '<main></main>'
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), { rotation: () => undefined, editable: () => true, unavailableReason: () => undefined })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Page Layout"]')!.click()
  expect(document.querySelector<HTMLSelectElement>('[data-ribbon-control="page-margins"]')!.disabled).toBe(true)
  expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="print-gridlines"]')!.disabled).toBe(true)
  ribbon.dispose()
})

it('mirrors protection state on Review ▸ Protection and locks editing buttons on a protected sheet', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  let protection = { sheet: { protected: true, reason: undefined as string | undefined }, workbook: { locked: false, reason: '工作簿结构受密码保护' as string | undefined } }
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand, {
    rotation: () => undefined, editable: () => true, hasSelection: () => true, protection: () => protection,
  })
  ribbon.refreshState?.()
  const button = (id: string) => document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
  expect(button('bold').disabled).toBe(true)
  expect(button('bold').title).toContain('工作表受保护')
  expect(button('copy').disabled).toBe(false)
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Review"]')!.click()
  expect(button('sheet-protect').textContent).toBe('撤销工作表保护')
  expect(button('sheet-protect').getAttribute('aria-pressed')).toBe('true')
  expect(button('sheet-protect').disabled).toBe(false)
  expect(button('workbook-protect').textContent).toBe('保护工作簿')
  expect(button('workbook-protect').disabled).toBe(true)
  expect(button('workbook-protect').title).toBe('工作簿结构受密码保护')
  button('sheet-protect').click()
  expect(onCommand).toHaveBeenCalledWith('sheet-protect')
  protection = { sheet: { protected: false, reason: undefined }, workbook: { locked: true, reason: undefined } }
  ribbon.refreshState?.()
  expect(button('sheet-protect').textContent).toBe('保护工作表')
  expect(button('workbook-protect').textContent).toBe('撤销工作簿保护')
})

it('wires Formulas ▸ Show Formulas, Calculate Now/Sheet and the Calculation Options menu, usable read-only', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  let calculation = { formulaView: true, manual: false }
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand, {
    rotation: () => undefined, editable: () => false, hasSelection: () => true, calculation: () => calculation,
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Formulas"]')!.click()
  ribbon.refreshState?.()
  const button = (id: string) => document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
  for (const id of ['toggle-show-formulas', 'calculate-now', 'calculate-sheet']) { expect(button(id).disabled, id).toBe(false); button(id).click() }
  expect(button('toggle-show-formulas').getAttribute('aria-pressed')).toBe('true')
  const mode = document.querySelector<HTMLSelectElement>('[data-ribbon-control="calc-mode"]')!
  expect([...mode.options].map(option => option.value)).toEqual(['auto', 'manual'])
  expect(mode.value).toBe('auto')
  mode.value = 'manual'; mode.dispatchEvent(new Event('change'))
  expect(onCommand.mock.calls.map(([command]) => command)).toEqual(['toggle-show-formulas', 'calculate-now', 'calculate-sheet', 'calc-mode:manual'])
  calculation = { formulaView: false, manual: true }
  ribbon.refreshState?.()
  expect(mode.value).toBe('manual')
  expect(button('toggle-show-formulas').getAttribute('aria-pressed')).toBe('false')
  expect(document.querySelector('[data-ribbon-command="calculation-options"]')).toBeNull()
})

it('reflects and dispatches the four style options for the currently selected table', () => {
  document.body.innerHTML = '<main></main>'
  let table = { id: 'staff', name: 'Staff', range: 'A1:B3', reason: undefined as string | undefined,
    styleOptions: { showFirstColumn: true, showLastColumn: false, showRowStripes: true, showColumnStripes: false } }
  const setTableStyleOption = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), {
    rotation: () => 0, editable: () => true, table: () => table, setTableStyleOption,
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Table Design"]')!.click()
  for (const [label, option] of [['首列', 'showFirstColumn'], ['末列', 'showLastColumn'], ['行条纹', 'showRowStripes'], ['列条纹', 'showColumnStripes']] as const) {
    const control = document.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!
    expect(control.checked).toBe(table.styleOptions[option])
    control.click()
    expect(setTableStyleOption).toHaveBeenLastCalledWith('staff', option, !table.styleOptions[option])
  }
  table = { ...table, id: 'other', reason: '工作表受保护', styleOptions: { showFirstColumn: false, showLastColumn: true, showRowStripes: false, showColumnStripes: true } }
  ribbon.refreshState()
  for (const [label, option] of [['首列', 'showFirstColumn'], ['末列', 'showLastColumn'], ['行条纹', 'showRowStripes'], ['列条纹', 'showColumnStripes']] as const) {
    const control = document.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!
    expect(control.checked).toBe(table.styleOptions[option]); expect(control.disabled).toBe(true)
    expect(control.title).toBe('工作表受保护')
  }
  ribbon.dispose()
})

it('converts the selected table through its captured identity and disables conversion for protection', () => {
  document.body.innerHTML = '<main></main>'
  let table = { id: 'staff', name: 'Staff', range: 'A1:B3', reason: undefined as string | undefined }
  const convertTable = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), {
    rotation: () => 0, editable: () => true, table: () => table, convertTable,
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Table Design"]')!.click()
  const control = document.querySelector<HTMLButtonElement>('[aria-label="转换为区域"]')!
  control.click()
  expect(convertTable).toHaveBeenCalledWith('staff')
  table = { ...table, reason: '工作表受保护' }; ribbon.refreshState()
  expect(control.disabled).toBe(true); expect(control.title).toBe('工作表受保护')
  ribbon.dispose()
})

it('opens native table creation from Home and Insert and respects protected selections', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  let protectedSheet = false
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand, {
    rotation: () => 0, editable: () => true,
    protection: () => ({ sheet: { protected: protectedSheet }, workbook: { locked: false } }),
  })
  const control = () => document.querySelector<HTMLButtonElement>('[data-ribbon-command="format-as-table"]')!
  expect(control().disabled).toBe(false)
  control().click(); expect(onCommand).toHaveBeenLastCalledWith('format-as-table')
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Insert"]')!.click()
  expect(control().disabled).toBe(false); control().click()
  expect(onCommand).toHaveBeenCalledTimes(2)
  protectedSheet = true; ribbon.refreshState(); expect(control().disabled).toBe(true)
  ribbon.dispose()
})

it('exposes the source checkbox action only for an editable unprotected sheet', () => {
  document.body.innerHTML = '<main></main>'
  let editable = true, protection = false
  const onCommand = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand, {
    rotation: () => 0, editable: () => editable, protection: () => ({ sheet: { protected: protection }, workbook: { locked: false } }),
  } as any)
  try {
    document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Insert"]')!.click()
    const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="insert-checkbox"]')!
    expect(button.disabled).toBe(false)
    expect(button.dataset.unavailableReason).toBeUndefined()
    button.click()
    expect(onCommand).toHaveBeenLastCalledWith('insert-checkbox')
    protection = true; ribbon.refreshState()
    expect(button.disabled).toBe(true)
    protection = false; editable = false; ribbon.refreshState()
    expect(button.disabled).toBe(true)
  } finally { ribbon.dispose() }
})

it('toggles the session formula bar on readonly and protected sheets while reflecting availability and pressed state', () => {
  document.body.innerHTML = '<main></main>'
  let visible = true, available = true
  const onCommand = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand, {
    rotation: () => undefined, editable: () => false, hasSelection: () => false,
    protection: () => ({ sheet: { protected: true }, workbook: { locked: true } }),
    formulaBar: () => ({ visible, available }),
  } as any)
  try {
    document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
    const button = document.querySelector<HTMLButtonElement>('[data-ribbon-command="toggle-formula-bar"]')!
    expect(button.disabled).toBe(false); expect(button.getAttribute('aria-pressed')).toBe('true')
    button.click(); expect(onCommand).toHaveBeenLastCalledWith('toggle-formula-bar')
    visible = false; ribbon.refreshState()
    expect(button.getAttribute('aria-pressed')).toBe('false')
    available = false; ribbon.refreshState(); expect(button.disabled).toBe(true)
    button.click(); expect(onCommand).toHaveBeenCalledTimes(1)
  } finally { ribbon.dispose() }
})

it('offers built-in CJK families separately from system fonts and dispatches actual font names', () => {
  const onCommand = vi.fn(), ribbon = mountWorkbookRibbon(document.body, onCommand)
  try {
    const select = document.querySelector<HTMLSelectElement>('[data-ribbon-control="font-family"]')!
    const options = new Map([...select.options].map(option => [option.value, option.textContent]))
    for (const [family, label] of [
      ['Noto Sans CJK SC', '思源黑体（内置）'], ['Noto Serif CJK SC', '思源宋体（内置）'],
      ['LXGW WenKai', '霞鹜文楷（内置）'], ['Ma Shan Zheng', '马善政毛笔楷书（内置）'], ['ZCOOL XiaoWei', '站酷小薇（内置）'],
      ['SimSun', '宋体（系统字体）'], ['SimHei', '黑体（系统字体）'], ['Microsoft YaHei', '微软雅黑（系统字体）'], ['KaiTi', '楷体（系统字体）'], ['FangSong', '仿宋（系统字体）'],
    ]) {
      expect(options.get(family!)).toBe(label)
      select.value = family!;select.dispatchEvent(new Event('change'))
      expect(onCommand).toHaveBeenLastCalledWith(`font-family:${family}`)
    }
    expect(options.get('Calibri')).toBe('Calibri')
  } finally { ribbon.dispose() }
})

it('persists actual CJK font-family menu values through a real Univer range and XLSX save', async () => {
  const { Univer, LocaleType, IUniverInstanceService } = await import('@univerjs/core')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  await import('@univerjs/sheets/facade')
  const { createBlankWorkbook, readWorkbook, applyCellEdits } = await import('@sheets-web/xlsx-engine')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { loadWorkbookData, readBackSnapshot } = await import('./workbook-vendor/grid/sync')
  const source = await createBlankWorkbook(), model = await readWorkbook(source)
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  let ribbon: ReturnType<typeof mountWorkbookRibbon> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    const api = FUniver.newAPI(univer)
    loadWorkbookData({ univer, univerAPI: api } as any, buildWorkbookData(model, 'cjk-menu', 'cjk-menu'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('cjk-menu')
    const book = api.getActiveWorkbook()!, sheet = book.getSheets()[0]!
    const families = ['Noto Sans CJK SC', 'Noto Serif CJK SC', 'LXGW WenKai', 'Ma Shan Zheng', 'ZCOOL XiaoWei', 'SimSun', 'SimHei', 'Microsoft YaHei', 'KaiTi', 'FangSong']
    let row = 0
    ribbon = mountWorkbookRibbon(document.body, command => applyWorkbookRibbonCommand(command, { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => sheet.getRange(row, 0) }) }) } as any))
    const select = document.querySelector<HTMLSelectElement>('[data-ribbon-control="font-family"]')!
    families.forEach((family, index) => { row = index;sheet.getRange(row, 0).setValue('中文字体');select.value = family;select.dispatchEvent(new Event('change')) })
    const cells = readBackSnapshot(book.getSnapshot()).sheets[0]!.cells
    const edits = families.map((family, index) => {
      const cell = cells[`A${index + 1}`]!
      expect(cell.style?.fontFamily).toBe(family)
      return { sheetName: model.sheets[0]!.name, row: index, column: 0, writeValue: true, cell: { value: cell.value }, style: { fontFamily: cell.style!.fontFamily! } }
    })
    const saved = await readWorkbook(await applyCellEdits(source, edits))
    families.forEach((family, index) => {
      const styleIndex = saved.sheets[0]!.cells[`A${index + 1}`]!.styleIndex!
      expect(saved.styles.fonts[saved.styles.cellXfs[styleIndex]!.fontId]?.family).toBe(family)
    })
  } finally { ribbon?.dispose();univer.dispose() }
})

it('reflects cross-highlight reading preference and allows it on protected readonly sheets',()=>{
 document.body.innerHTML='<main></main>';let active=false,available=true
 const run=vi.fn(()=>{active=!active;controller.refreshState()})
 const controller=mountWorkbookRibbon(document.querySelector('main')!,run,{rotation:()=>undefined,editable:()=>false,crossHighlight:()=>({active,available}),protection:()=>({sheet:{protected:true},workbook:{locked:true}})})
 document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
 const button=document.querySelector<HTMLButtonElement>('[data-ribbon-command="toggle-cross-highlight"]')!
 expect(button.disabled).toBe(false);expect(button.getAttribute('aria-pressed')).toBe('false')
 button.click();expect(run).toHaveBeenCalledWith('toggle-cross-highlight');expect(button.getAttribute('aria-pressed')).toBe('true')
 available=false;controller.refreshState();expect(button.disabled).toBe(true)
 controller.dispose()
})

it('keeps normal and page-break preview mutually exclusive and readable on protected sheets', () => {
  document.body.innerHTML = '<main></main>'
  let active = false
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, vi.fn(), {
    editable: () => false, rotation: () => 0,
    protection: () => ({ sheet: { protected: true }, workbook: { locked: false } }),
    pageBreakPreview: () => ({ active, available: true }),
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
  const normal = document.querySelector<HTMLButtonElement>('[data-ribbon-command="normal-view"]')!
  const preview = document.querySelector<HTMLButtonElement>('[data-ribbon-command="toggle-page-break-preview"]')!
  expect(normal.disabled).toBe(false); expect(preview.disabled).toBe(false)
  expect(normal.getAttribute('aria-pressed')).toBe('true'); expect(preview.getAttribute('aria-pressed')).toBe('false')
  active = true; ribbon.refreshState()
  expect(normal.getAttribute('aria-pressed')).toBe('false'); expect(preview.getAttribute('aria-pressed')).toBe('true')
})

it('enables formula trace controls for protected readonly worksheets and exposes remove state', () => {
  document.body.innerHTML = '<main></main>'
  let active = false
  const command = vi.fn(), ribbon = mountWorkbookRibbon(document.querySelector('main')!, command, {
    editable: () => false, rotation: () => 0, protection: () => ({ sheet: { protected: true }, workbook: { locked: false } }),
    formulaTrace: () => ({ available: true, active }),
  })
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Formulas"]')!.click()
  for (const id of ['trace-precedents', 'trace-dependents']) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
    expect(button.disabled).toBe(false); button.click(); expect(command).toHaveBeenCalledWith(id)
  }
  const remove = document.querySelector<HTMLButtonElement>('[data-ribbon-command="remove-arrows"]')!
  expect(remove.disabled).toBe(true); active = true; ribbon.refreshState(); expect(remove.disabled).toBe(false)
})

it('uses decorative command icons with visible labels for Home actions', () => {
  const host = document.body.appendChild(document.createElement('div'))
  const ribbon = mountWorkbookRibbon(host, vi.fn())
  const buttons = [...host.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
  expect(buttons.filter(button => !button.querySelector('svg')).map(button => button.dataset.ribbonCommand)).toEqual([])
  for (const button of buttons) {
    expect(button.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    expect(button.textContent?.trim()).not.toBe('')
  }
  ribbon.dispose()
})
it('audits icon coverage across workbook command tabs', () => {
  const host = document.body.appendChild(document.createElement('div'))
  const ribbon = mountWorkbookRibbon(host, vi.fn())
  const missing = new Set<string>()
  const tabs = [...host.querySelectorAll<HTMLElement>('[data-ribbon-tab]')].map(tab => tab.dataset.ribbonTab!)
  for (const tab of tabs) {
    host.querySelectorAll<HTMLButtonElement>('[data-ribbon-tab]').forEach(button => { if (button.dataset.ribbonTab === tab) button.click() })
    host.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]').forEach(button => { if (!button.querySelector('svg')) missing.add(button.dataset.ribbonCommand!) })
  }
  expect([...missing]).toEqual([])
  ribbon.dispose()
})

it('retains protection icons and updates accessible labels when state refreshes', () => {
  const host = document.body.appendChild(document.createElement('div'));let protectedSheet=false
  const ribbon=mountWorkbookRibbon(host,vi.fn(),{editable:()=>true,rotation:()=>0,protection:()=>({sheet:{protected:protectedSheet},workbook:{locked:false}})})
  host.querySelector<HTMLButtonElement>('[data-ribbon-tab=Review]')!.click()
  const button=host.querySelector<HTMLButtonElement>('[data-ribbon-command=sheet-protect]')!
  expect(button.querySelectorAll('svg')).toHaveLength(1)
  protectedSheet=true;ribbon.refreshState()
  expect(button.querySelectorAll('svg')).toHaveLength(1)
  expect(button.getAttribute('aria-label')).toBe('撤销工作表保护')
  expect(button.getAttribute('aria-pressed')).toBe('true')
  ribbon.dispose()
})
