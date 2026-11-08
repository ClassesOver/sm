import { afterEach, expect, it, vi } from 'vitest'
import { applyWorkbookRibbonCommand, mountWorkbookRibbon, type WorkbookPageSetupState } from './workbook-ribbon'

afterEach(() => { document.body.replaceChildren() })

it('renders the GenOffice ribbon tabs and dispatches supported workbook commands', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand)

  expect([...document.querySelectorAll('[role=tab]')].map(tab => tab.textContent)).toEqual([
    '文件', '开始', '插入', '页面布局', '公式', '数据', '审阅', '视图',
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
  expect(deferred.title).toContain('剪贴板粘贴')
  const rotation = document.querySelector<HTMLButtonElement>('[data-ribbon-command="rotate:45"]')!
  expect(rotation.disabled).toBe(false)
  expect(rotation.title).not.toContain('does not capture text rotation')
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

it('keeps sort and filter source actions visible with an operation-specific unavailable reason', () => {
  document.body.innerHTML = '<main></main>'
  mountWorkbookRibbon(document.querySelector('main')!, vi.fn())
  document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Data"]')!.click()
  // filter-toggle/clear/reapply 走官方 pinned 筛选命令（workbook-main 接线），保持可用；
  // 其余排序/筛选入口仍受不可用原因约束。
  for (const id of ['filter-toggle', 'filter-clear', 'filter-reapply']) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.disabled, id).toBe(false)
  }
  for (const [id, label, reason] of [
    ['sort-custom-open', '自定义排序…', '自定义排序对话框'],
    ['filter-advanced', '高级筛选', '高级筛选条件对话框'],
  ]) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.textContent, id).toBe(label)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
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
  const expected = [
    ['text-to-columns:2', '按逗号拆分', '文本分列操作'],
    ['text-to-columns:4', '按分号拆分', '文本分列操作'],
    ['text-to-columns:8', '按空格拆分', '文本分列操作'],
    ['text-to-columns:1', '按制表符拆分', '文本分列操作'],
    ['flash-fill', '快速填充', '快速填充生成的修改'],
    ['remove-duplicates-open', '删除重复值', '重复值对话框'],
    ['dv-open', '数据验证', '数据验证对话框'],
    ['consolidate-open', '合并计算', '合并计算对话框'],
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
  expect(subtotal?.title).toContain('分组汇总行')
  expect(subtotal?.getAttribute('aria-description')).toContain('分组汇总行')
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
    ['indent-step:increase', '缩进样式'], ['format-cells', '完整单元格格式对话框'],
    ['row-height-open', '行高对话框'], ['col-width-open', '列宽对话框'],
    ['autofit-row-height', '持久化自动行高'], ['autofit-col-width', '持久化自动列宽'],
    ['insert-cells', '插入并移动单元格'], ['delete-cells', '删除并移动单元格'],
  ]) {
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
    expect(button?.disabled, id).toBe(true)
    expect(button?.title, id).toContain(reason)
    expect(button?.getAttribute('aria-description'), id).toContain(reason)
  }
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
    expect(button?.textContent, id).toBe(label)
  }
  expect(document.querySelector<HTMLButtonElement>('[data-ribbon-command="autofn:SUM"]')?.disabled).toBe(false)
  for (const id of [...expected.keys()].filter(id => id.startsWith('insert-function-open'))) {
    const button = [...document.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')]
      .find(candidate => candidate.dataset.ribbonCommand === id)
    expect(button?.disabled, id).toBe(true)
    expect(button?.getAttribute('aria-description'), id).toContain('函数目录对话框')
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
    ['workbook-statistics', '工作簿统计视图'],
    ['translate', '翻译操作'],
    ['sheet-protect', '工作表保护状态'],
    ['workbook-protect', '工作簿保护状态'],
    ['allow-edit-ranges-open', '受保护区域'],
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
    expect(button?.textContent, id).toBe(label)
  }
  expect(buttons.find(button => button.dataset.ribbonCommand === 'toggle-gridlines')?.disabled).toBe(false)
  for (const [id, reason] of [
    ['toggle-page-break-preview', '分页预览渲染'], ['toggle-formula-bar', '编辑栏'],
    ['toggle-headings', '表头尺寸'], ['toggle-right-to-left', '从右到左视图'],
    ['toggle-cross-highlight', '活动行列突出显示'], ['zoom-to-selection', '选区尺寸'],
    ['new-window', '桌面工作簿窗口'], ['arrange-all', '桌面工作簿窗口'],
 ['split-window', '拆分视口'],
    ['hide-window', '桌面工作簿窗口'], ['switch-window', '桌面工作簿窗口'],
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

it('renders Page Layout dropdowns with the source option sets and dispatches their commands', () => {
  document.body.innerHTML = '<main></main>'
  const onCommand = vi.fn()
  const state: WorkbookPageSetupState = {
    margins: 'custom', orientation: undefined, paperSize: undefined,
    fitToWidth: 2, fitToHeight: 0, printGridlines: true, printHeadings: false, printArea: 'A1:B4',
  }
  const ribbon = mountWorkbookRibbon(document.querySelector('main')!, onCommand, {
    rotation: () => undefined, editable: () => true, unavailableReason: () => undefined, pageSetup: () => state,
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
  const scale = document.querySelector<HTMLButtonElement>('[data-ribbon-command="scale"]')!
  expect(scale.disabled).toBe(true)
  expect(scale.title).toContain('打印对话框')
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
