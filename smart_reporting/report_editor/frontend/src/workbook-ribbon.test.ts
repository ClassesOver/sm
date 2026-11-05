import { afterEach, expect, it, vi } from 'vitest'
import { applyWorkbookRibbonCommand, mountWorkbookRibbon } from './workbook-ribbon'

afterEach(() => { document.body.replaceChildren() })

it('renders the GenOffice ribbon tabs and dispatches supported workbook commands', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand)

  expect([...document.querySelectorAll('[role=tab]')].map(tab => tab.textContent)).toEqual([
    'Home', 'Insert', 'Page Layout', 'Formulas', 'Data', 'Review', 'View',
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
  const deferred = document.querySelector<HTMLButtonElement>('[data-ribbon-command="paste"]')!
  expect(deferred.disabled).toBe(true)
  expect(deferred.title).toContain('native workbook editor')
  const rotation = document.querySelector<HTMLButtonElement>('[data-ribbon-command="rotate:45"]')!
  expect(rotation.disabled).toBe(true)
  expect(rotation.title).toContain('does not capture text rotation')
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
    getWrap: () => wrap,
    setFontWeight: (value: 'bold' | 'normal' | null) => { calls.push(['bold', value]); style.bl = value === 'bold' ? 1 : 0 },
    setFontStyle: (value: 'italic' | 'normal' | null) => { calls.push(['italic', value]); style.it = value === 'italic' ? 1 : 0 },
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
      getRange: () => ({ setFormula: () => undefined }),
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
  expect(() => applyWorkbookRibbonCommand('rotate:45', workbook)).toThrow('does not capture text rotation')
  const step = vi.fn()
  expect(applyWorkbookRibbonCommand('decimal-inc', workbook, step)).toBe(true)
  expect(applyWorkbookRibbonCommand('decimal-dec', workbook, step)).toBe(true)
  expect(step.mock.calls).toEqual([[1], [-1]])
  expect(() => applyWorkbookRibbonCommand('decimal-inc', workbook)).toThrow('not wired to the workbook runtime')
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
  expect(() => applyWorkbookRibbonCommand('autofn:SUM', workbook)).toThrow('Select at least two rows')
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

it('keeps sort and filter source actions visible with an operation-specific unavailable reason', () => {
  document.body.innerHTML = '<main></main>'
  mountWorkbookRibbon(document.querySelector('main')!, vi.fn())
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  for (const [id, label, reason] of [
    ['sort-custom-open', '自定义排序…', 'custom-sort dialog'],
    ['filter-toggle', '筛选', 'no autoFilter readback/writeback contract'],
    ['filter-clear', '清除筛选条件', 'no filter criteria readback'],
    ['filter-reapply', '重新应用筛选', 'no persisted autoFilter criteria model'],
    ['filter-advanced', '高级筛选', 'no advanced criteria dialog'],
  ]) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.textContent, id).toBe(label)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
  }
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
  const expected = [
    ['text-to-columns:2', '按逗号拆分', 'no text-to-columns command'],
    ['text-to-columns:4', '按分号拆分', 'no text-to-columns command'],
    ['text-to-columns:8', '按空格拆分', 'no text-to-columns command'],
    ['text-to-columns:1', '按制表符拆分', 'no text-to-columns command'],
    ['flash-fill', '快速填充', 'derived cell edits'],
    ['remove-duplicates-open', '删除重复值', 'selection-driven duplicate dialog'],
    ['dv-open', '数据验证', 'data-validation dialog'],
    ['consolidate-open', '合并计算', 'consolidate dialog'],
  ]
  for (const [id, label, reason] of expected) {
    const button = dataTools.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.textContent, id).toBe(label)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
  }
  const outline = groupFor('分级显示')!
  const outlineIds = [...outline.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
    .map(button => button.dataset.ribbonCommand)
  expect(outlineIds.at(-1)).toBe('subtotal-open')
  const subtotal = outline.querySelector<HTMLButtonElement>('[data-ribbon-command="subtotal-open"]')
  expect(subtotal?.textContent).toBe('分类汇总')
  expect(subtotal?.disabled).toBe(true)
  expect(subtotal?.title).toContain('no subtotal operation')
  expect(subtotal?.getAttribute('aria-description')).toContain('no subtotal operation')
})

it('sorts the selected Univer range with the shared stable XLSX engine semantics', () => {
  const calls: unknown[][] = []
  const rows = [
    ['z', 20],
    ['a', 10],
    ['m', 15],
  ]
  const formulas = [['', ''], ['', ''], ['', '']]
  const range = {
    getRow: () => 1, getColumn: () => 1, getHeight: () => 3, getWidth: () => 2,
    getValues: () => rows,
    getFormulas: () => formulas,
  }
  const sheet = {
    getSelection: () => ({ getActiveRange: () => range }),
    getRange: (row: number, column: number) => ({ setValue: (value: unknown) => calls.push([row, column, value]) }),
    insertRowsBefore: () => undefined, deleteRows: () => undefined,
    insertColumnsBefore: () => undefined, deleteColumns: () => undefined,
  }
  const workbook = { getActiveSheet: () => sheet, insertSheet: () => undefined } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  expect(applyWorkbookRibbonCommand('sort:asc', workbook)).toBe(true)
  expect(calls).toEqual([[1, 1, 'a'], [1, 2, 10], [2, 1, 'm'], [2, 2, 15], [3, 1, 'z'], [3, 2, 20]])
  calls.length = 0
  expect(applyWorkbookRibbonCommand('sort:desc', workbook)).toBe(true)
  expect(calls).toEqual([[2, 1, 'm'], [2, 2, 15], [3, 1, 'a'], [3, 2, 10]])
})

it('rejects sorting a selected range containing formulas without changing the grid', () => {
  const setValue = vi.fn()
  const range = { getRow: () => 0, getColumn: () => 0, getHeight: () => 2, getWidth: () => 1,
    getValues: () => [[2], [1]], getFormulas: () => [['=1+1'], ['']] }
  const workbook = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => range }),
    getRange: () => ({ setValue }), insertRowsBefore: vi.fn(), deleteRows: vi.fn(), insertColumnsBefore: vi.fn(), deleteColumns: vi.fn() }),
    insertSheet: vi.fn() } as unknown as Parameters<typeof applyWorkbookRibbonCommand>[1]
  expect(() => applyWorkbookRibbonCommand('sort:asc', workbook)).toThrow('contains a formula at A1')
  expect(setValue).not.toHaveBeenCalled()
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
  for (const id of ['valign:top', 'align:center', 'merge:cells', 'merge:center', 'merge:across', 'merge:unmerge', 'insert-row-here', 'delete-row-here', 'insert-col-here', 'delete-col-here', 'clear-contents']) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)!
    expect(button.disabled, id).toBe(false)
    button.click()
  }
  expect(onCommand.mock.calls.map(([command]) => command)).toEqual([
    'valign:top', 'align:center', 'merge:cells', 'merge:center', 'merge:across', 'merge:unmerge',
    'insert-row-here', 'delete-row-here', 'insert-col-here', 'delete-col-here', 'clear-contents',
  ])
  expect(getLabel('clear-contents')).toBe('清除内容')
  for (const [id, reason] of [
    ['rotate:-45', 'does not capture text rotation'], ['rotate:vertical', 'does not capture text rotation'],
    ['indent-step:increase', 'does not roundtrip OOXML indent styles'], ['format-cells', 'no Format Cells dialog'],
    ['row-height-open', 'no row-height dialog'], ['col-width-open', 'no column-width dialog'],
    ['autofit-row-height', 'does not persist Univer auto-height'], ['autofit-col-width', 'does not persist Univer auto-width'],
    ['clear-all', 'only supports clearing cell contents'], ['clear-formats', 'does not distinguish every cleared inherited/style component'],
    ['insert-cells', 'no insert-shifted-cells operation'], ['delete-cells', 'no delete-shifted-cells operation'],
  ]) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
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
    expect(button?.textContent, id).toBe(label)
  }
  expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="autofn:SUM"]')?.disabled).toBe(false)
  for (const id of [...expected.keys()].filter(id => id.startsWith('insert-function-open'))) {
    const button = [...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
      .find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.disabled, id).toBe(true)
    expect(button?.getAttribute('aria-description'), id).toContain('function catalog')
  }
})

it('renders the GenOffice Review Comments and Notes commands with note-specific unavailable reasons', () => {
  document.body.innerHTML = '<main></main>'
  mountWorkbookRibbon(document.querySelector('main')!, vi.fn())
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Review"]')!.click()
  const expected = [
    ['note-open', '新建批注', 'note state/readback'], ['note-delete', '删除', 'note state/readback'],
    ['note-prev', '上一条', 'note collection'], ['note-next', '下一条', 'note collection'],
    ['note-show-toggle', '显示批注', 'Note preset'],
  ]
  const buttons = [...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
  for (const [id, label, reason] of expected) {
    const button = buttons.find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.textContent, id).toBe(label)
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
  expect(labels.get('translate')).toBe('翻译')
  expect(labels.get('sheet-protect')).toBe('保护工作表')
  expect(labels.get('workbook-protect')).toBe('保护工作簿')
  expect(labels.get('allow-edit-ranges-open')).toBe('允许编辑区域')
  for (const [id, reason] of [
    ['workbook-statistics', 'workbook-statistics view'],
    ['translate', 'workbook AI translation'],
    ['sheet-protect', 'does not expose sheet protection state'],
    ['workbook-protect', 'does not expose workbook protection state'],
    ['allow-edit-ranges-open', 'protected-range readback'],
  ]) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
  }
  expect(document.querySelector('[data-ribbon-command="spell-check"]')).toBeNull()
  expect(document.querySelector('[data-ribbon-command="spellcheck-toggle"]')).toBeNull()
  expect(document.querySelector('[data-ribbon-command="workbook-change-password"]')).toBeNull()
})

it('renders GenOffice View controls with a live gridline toggle and explicit unavailable states', () => {
  document.body.innerHTML = '<main></main>'
  mountWorkbookRibbon(document.querySelector('main')!, vi.fn())
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="View"]')!.click()
  const buttons = [...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
  const expected = new Map([
    ['toggle-page-break-preview', '分页预览'], ['toggle-gridlines', '网格线'],
    ['toggle-formula-bar', '编辑栏'], ['toggle-headings', '标题'],
    ['toggle-right-to-left', '从右到左'], ['toggle-cross-highlight', '突出显示活动行和列'],
    ['zoom-reset', '重置缩放'], ['zoom-to-selection', '缩放到选定区域'],
    ['zoom-in', '放大'], ['zoom-out', '缩小'],
    ['new-window', '新建窗口'], ['arrange-all', '全部重排'], ['freeze-panes', '冻结窗格'],
    ['split-window', '拆分窗口'], ['hide-window', '隐藏窗口'], ['switch-window', '切换窗口'],
  ])
  for (const [id, label] of expected) {
    const button = buttons.find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.textContent, id).toBe(label)
  }
  expect(buttons.find(button => button.dataset.ribbonCommand === 'toggle-gridlines')?.disabled).toBe(false)
  for (const [id, reason] of [
    ['toggle-page-break-preview', 'page-break preview renderer'], ['toggle-formula-bar', 'Formula bar visibility'],
    ['toggle-headings', 'Row and column heading visibility'], ['toggle-right-to-left', 'Right-to-left view'],
    ['toggle-cross-highlight', 'Cross-highlight is transient UI state'], ['zoom-reset', 'no zoom getter/setter'],
    ['zoom-to-selection', 'render skeleton dimensions'], ['zoom-in', 'no zoom getter/setter'], ['zoom-out', 'no zoom getter/setter'],
    ['new-window', 'desktop workbook windows'], ['arrange-all', 'desktop window manager'],
    ['freeze-panes', 'Freeze panes requires'], ['split-window', 'split-window viewport state'],
    ['hide-window', 'desktop workbook windows'], ['switch-window', 'desktop workbook windows'],
  ]) {
    const button = buttons.find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
  }
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
