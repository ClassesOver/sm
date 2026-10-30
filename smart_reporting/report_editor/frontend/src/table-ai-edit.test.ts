import { describe, expect, it, vi } from 'vitest'
import { Schema } from '@milkdown/kit/prose/model'
import { EditorState } from '@milkdown/kit/prose/state'
import { EditorView } from '@milkdown/kit/prose/view'
import { history, undo } from '@milkdown/kit/prose/history'
import { createTableAIEdit, replaceTableProtocolBlock, tableBodyMarkdown } from './table-ai-edit'
import type { ReportEditorClient } from './api'

const schema = new Schema({ nodes: {
  doc: { content: 'block+' },
  paragraph: { content: 'text*', group: 'block', toDOM: () => ['p', 0] },
  table: { content: 'table_row+', group: 'block', toDOM: () => ['table', ['tbody', 0]] },
  table_row: { content: 'table_cell+', toDOM: () => ['tr', 0] },
  table_cell: { content: 'paragraph+', toDOM: () => ['td', 0] },
  text: {},
} })

function paragraph(value: string) { return schema.node('paragraph', null, value ? schema.text(value) : undefined) }
function table(value: string) {
  return schema.node('table', null, schema.node('table_row', null,
    schema.node('table_cell', null, paragraph(value)),
  ))
}

function viewFor(doc: ReturnType<typeof schema.node>) {
  const state = EditorState.create({ schema, doc })
  const view = { state, dispatch: vi.fn() }
  return { state, view }
}

describe('createTableAIEdit review', () => {
  it('shows the complete current table as a readable preview', async () => {
    document.body.innerHTML = ''
    const client = {
      tableEditRecordByTableId: vi.fn(async () => { throw new Error('not edited') }),
      tableTemplates: vi.fn(async () => ({ templates: [] })),
    } as unknown as ReportEditorClient
    const { view } = viewFor(schema.node('doc', null, paragraph('正文')))
    const controller = createTableAIEdit({ view: view as never, client })
    const currentBody = [
      '| 科室 | 门诊量 |', '| --- | ---: |',
      ...Array.from({ length: 7 }, (_, index) => `| 科室 ${index + 1} | ${100 + index} |`),
    ].join('\n')

    controller.open('tbl-preview', currentBody)
    await vi.waitFor(() => expect(document.querySelector('#table-ai-input')).not.toBeNull())

    const preview = document.querySelector<HTMLTableElement>('.table-ai-current-preview')!
    expect(preview.getAttribute('aria-label')).toBe('当前表格预览')
    expect(preview.querySelectorAll('thead th')).toHaveLength(2)
    expect(preview.querySelectorAll('tbody tr')).toHaveLength(7)
    expect(preview.textContent).toContain('科室 7')
    expect(document.querySelector('.table-ai-context pre')).toBeNull()
    controller.dispose()
  })

  it.each([false, true])('采用后的改表回执只定位仍存在的新版本（撤销=%s）', async reverted => {
    document.body.innerHTML = ''
    const markdown = '[[table:tbl-new]]\n| 项目 |\n| --- |\n| 新值 |\n\n[[/table:tbl-new]]'
    const client = {
      tableEditRecordByTableId: vi.fn(async () => { throw new Error('no record') }),
      tableTemplates: vi.fn(async () => ({ templates: [] })),
      startTableAiEdit: vi.fn(async () => ({ editId: 'tedit-next', status: 'queued' })),
      tableAiEditStatus: vi.fn(async () => ({ editId: 'tedit-next', status: 'succeeded', markdown, warnings: [], skipped: [], review: { columns: [], rows: [] } })),
      cancelTableAiEdit: vi.fn(async () => undefined),
    } as unknown as ReportEditorClient
    const host = document.createElement('div'); document.body.append(host)
    const view = new EditorView(host, { state: EditorState.create({ schema, doc: schema.node('doc', null, [paragraph('[[table:tbl-old]]'), table('旧值'), paragraph('[[/table:tbl-old]]')]), plugins: [history()] }) })
    const controller = createTableAIEdit({ view, client, pollIntervalMs: 1 })
    controller.open('tbl-old', '| 项目 |\n| --- |\n| 旧值 |')
    await vi.waitFor(() => expect(document.querySelector('#table-ai-input')).not.toBeNull())
    const input = document.querySelector<HTMLTextAreaElement>('#table-ai-input')!
    input.value = '改表'; input.dispatchEvent(new Event('input'))
    document.querySelector<HTMLButtonElement>('.ask-ai-composers .ui-button--primary')!.click()
    await vi.waitFor(() => expect(document.querySelector('.table-ai-review')).not.toBeNull())
    const adopt = document.querySelector<HTMLButtonElement>('.ask-ai-review-dock:not([hidden]) .ui-button--primary')!
    expect(adopt.textContent).toBe('采用到正文'); adopt.click()
    const receipt = document.querySelector<HTMLElement>('.ask-ai-receipt')!
    expect(receipt).not.toBeNull()
    expect(document.querySelector<HTMLElement>('.ask-ai-panel')!.hidden).toBe(false)
    if (reverted) {
      undo(view.state, view.dispatch)
      receipt.querySelector<HTMLButtonElement>('[data-action="continue-editing"]')!.click()
      expect(receipt.textContent).toContain('已变化或无法唯一定位')
      expect(view.state.doc.textContent).toContain('旧值')
    } else {
      receipt.querySelector<HTMLButtonElement>('[data-action="continue-editing"]')!.click()
      await vi.waitFor(() => expect(document.querySelector('#table-ai-input')).not.toBeNull())
      const next = document.querySelector<HTMLTextAreaElement>('#table-ai-input')!
      next.value = '再次调整'; next.dispatchEvent(new Event('input'))
      document.querySelector<HTMLButtonElement>('.ask-ai-composers .ui-button--primary')!.click()
      await vi.waitFor(() => expect(client.startTableAiEdit).toHaveBeenLastCalledWith('tbl-old', expect.objectContaining({ previousEditId: 'tedit-next', baseBody: '| 项目 |\n| --- |\n| 新值 |' })))
    }
    controller.dispose(); view.destroy()
  })
  it('打开不可用的表格时先展示原因卡，不挂载输入区', async () => {
    document.body.innerHTML = ''
    const client = {
      tableEditRecordByTableId: vi.fn(async () => { throw new Error('not edited') }),
      tableAiAvailability: vi.fn(async () => ({ available: false, reason: 'table_unbound' })),
      tableTemplates: vi.fn(async () => ({ templates: [] })),
    } as unknown as ReportEditorClient
    const host = document.createElement('div'); document.body.append(host)
    const view = new EditorView(host, { state: EditorState.create({ schema, doc: schema.node('doc', null, [paragraph('[[table:tbl-old]]'), table('旧值'), paragraph('[[/table:tbl-old]]')]), plugins: [history()] }) })
    const controller = createTableAIEdit({ view, client, pollIntervalMs: 1 })
    controller.open('tbl-old', '| 项目 |\n| --- |\n| 旧值 |')
    await vi.waitFor(() => expect(document.querySelector('.chart-ai-unavailable')).not.toBeNull())
    expect(document.querySelector('.chart-ai-unavailable')!.textContent).toContain('无法改表')
    expect(document.querySelector('#table-ai-input')).toBeNull()
    expect(client.tableAiAvailability).toHaveBeenCalledWith('tbl-old')
    controller.dispose(); view.destroy()
  })

  it('可用性预检请求失败时照常打开输入区', async () => {
    document.body.innerHTML = ''
    const client = {
      tableEditRecordByTableId: vi.fn(async () => { throw new Error('not edited') }),
      tableAiAvailability: vi.fn(async () => { throw new Error('network') }),
      tableTemplates: vi.fn(async () => ({ templates: [] })),
    } as unknown as ReportEditorClient
    const host = document.createElement('div'); document.body.append(host)
    const view = new EditorView(host, { state: EditorState.create({ schema, doc: schema.node('doc', null, [paragraph('[[table:tbl-old]]'), table('旧值'), paragraph('[[/table:tbl-old]]')]), plugins: [history()] }) })
    const controller = createTableAIEdit({ view, client, pollIntervalMs: 1 })
    controller.open('tbl-old', '| 项目 |\n| --- |\n| 旧值 |')
    await vi.waitFor(() => expect(document.querySelector('#table-ai-input')).not.toBeNull())
    controller.dispose(); view.destroy()
  })

  it('同一表格正文改变后重开，保留要求并使用新表体提交', async () => {
    document.body.innerHTML = ''
    const client = {
      tableEditRecordByTableId: vi.fn(async () => { throw new Error('not edited') }),
      tableTemplates: vi.fn(async () => ({ templates: [] })),
      startTableAiEdit: vi.fn(async () => ({ editId: 'tedit-test' })),
      tableAiEditStatus: vi.fn(async () => ({ status: 'failed', error: { message: '测试结束' } })),
    } as unknown as ReportEditorClient
    const { view } = viewFor(schema.node('doc', null, paragraph('正文')))
    const controller = createTableAIEdit({ view: view as never, client, pollIntervalMs: 1 })
    controller.open('tbl-1', '| 项目 |\n| --- |\n| 旧内容 |')
    await vi.waitFor(() => expect(document.querySelector('#table-ai-input')).not.toBeNull())
    const area = document.querySelector<HTMLTextAreaElement>('#table-ai-input')!
    area.value = '按收入降序'; area.dispatchEvent(new Event('input'))
    expect(document.querySelector('.ask-ai-composers #table-ai-input')).not.toBeNull()
    expect(document.querySelector('.ask-ai-content textarea')).toBeNull()
    const updated = '| 项目 |\n| --- |\n| 新内容 |'
    controller.open('tbl-1', updated)
    expect(document.querySelector<HTMLTextAreaElement>('#table-ai-input')!.value).toBe('按收入降序')
    document.querySelector<HTMLButtonElement>('.ui-button--primary')!.click()
    await vi.waitFor(() => expect(client.startTableAiEdit).toHaveBeenCalledWith('tbl-1', expect.objectContaining({ baseBody: updated })))
    controller.dispose()
  })

  it('预制表格模板保持无自由要求的确定性执行路径', async () => {
    document.body.innerHTML = ''
    const client = {
      tableEditRecordByTableId: vi.fn(async () => { throw new Error('not edited') }),
      tableTemplates: vi.fn(async () => ({ templates: [{ templateId: 'budget-execution', name: '预算执行', available: true }] })),
      startTableTemplateEdit: vi.fn(async () => ({ editId: 'tedit-template' })),
      tableAiEditStatus: vi.fn(async () => ({ editId: 'tedit-template', status: 'failed', error: { message: '测试终止' } })),
    } as unknown as ReportEditorClient
    const { view } = viewFor(schema.node('doc', null, paragraph('正文')))
    const controller = createTableAIEdit({ view: view as never, client, pollIntervalMs: 1 })
    controller.open('tbl-1')
    await vi.waitFor(() => expect(document.querySelector('.table-ai-template')).not.toBeNull())
    document.querySelector<HTMLButtonElement>('.table-ai-template')!.click()
    await vi.waitFor(() => expect(client.startTableTemplateEdit).toHaveBeenCalled())
    expect(client.startTableTemplateEdit).toHaveBeenCalledWith('tbl-1', expect.not.objectContaining({ instruction: expect.anything() }))
    controller.dispose()
  })

  it('失败后保留输入，收起再打开不重复启动任务', async () => {
    document.body.innerHTML = ''
    let complete: (value: unknown) => void = () => undefined
    const client = {
      tableTemplates: vi.fn(async () => ({ templates: [] })),
      tableEditRecordByTableId: vi.fn(async () => { throw new Error('not edited') }),
      startTableAiEdit: vi.fn(async () => ({ editId: 'tedit-test', status: 'queued' })),
      tableAiEditStatus: vi.fn(() => new Promise(resolve => { complete = resolve })),
      cancelTableAiEdit: vi.fn(async () => undefined),
    } as unknown as ReportEditorClient
    const { view } = viewFor(schema.node('doc', null, paragraph('正文')))
    const controller = createTableAIEdit({ view: view as never, client, pollIntervalMs: 1 })
    controller.open('tbl-1', '| 项目 |\n| --- |\n| 收入 |')
    await vi.waitFor(() => expect(document.querySelector('#table-ai-input')).not.toBeNull())
    const area = document.querySelector<HTMLTextAreaElement>('#table-ai-input')!
    area.value = '按收入降序'
    area.dispatchEvent(new Event('input'))
    document.querySelector("#table-ai-input")?.dispatchEvent(new Event("input"))
    document.querySelector<HTMLButtonElement>('.ui-button--primary')!.click()
    await vi.waitFor(() => expect(client.tableAiEditStatus).toHaveBeenCalled())
    document.querySelector<HTMLButtonElement>('.table-ai-edit-close')!.click()
    controller.open('tbl-1')
    expect(document.querySelector('.ask-ai-progress')).not.toBeNull()
    expect(client.startTableAiEdit).toHaveBeenCalledTimes(1)
    const search = document.createElement('input'); document.body.append(search); search.focus()
    complete({ editId: 'tedit-test', status: 'failed', error: { message: '数据不足' } })
    await vi.waitFor(() => expect(document.querySelector('.ask-ai-session')!.textContent).toContain('数据不足'))
    await vi.waitFor(() => expect(document.querySelector<HTMLTextAreaElement>('#table-ai-input')?.value).toBe('按收入降序'))
    expect(document.querySelector('.ask-ai-session')!.textContent).toContain('数据不足')
    expect(document.activeElement).toBe(search)
    controller.dispose()
  })

  it.each([false, true])('逐格核验来源，替换时保护正文的新改动（正文已改：%s）', async changed => {
    document.body.innerHTML = '<div id="root"></div>'
    const client = {
      tableTemplates: vi.fn(async () => ({
        tableId: 'tbl-1',
        templates: [
          { templateId: 'composition', name: '构成表', available: false, reason: '缺少维度分组' },
        ],
      })),
      startTableAiEdit: vi.fn(async () => ({ editId: 'tedit-00000001', status: 'queued' })),
      tableAiEditStatus: vi.fn(async () => ({
        editId: 'tedit-00000001',
        tableId: 'tbl-1',
        status: 'succeeded',
        markdown: '[[table:tbl-1-e0000001]]\n| | 收入（万元） |\n| --- | ---: |\n| 2025年9月 | 3,600 |\n\n[[/table:tbl-1-e0000001]]',
        review: {
          columns: ['收入（万元）'],
          rows: [{
            label: '2025年9月',
            cells: [
              { text: '2025年9月', status: 'unchanged', column: '' },
              { text: '3,600', status: 'added', column: '收入（万元）', source: { analysisId: 'analysis_001', factIds: ['fact-aaaaaaaaaaaaaaaa'], selector: 'periodValues.0' } },
            ],
          }],
          flagged: [],
        },
        warnings: [],
        skipped: [],
      })),
      cancelTableAiEdit: vi.fn(async () => undefined),
      tableEditRecordByTableId: vi.fn(async () => { throw new Error('not edited') }),
    } as unknown as ReportEditorClient
    const doc = schema.node('doc', null, [
      paragraph('[[table:tbl-1]]'), table('old'), paragraph('[[/table:tbl-1]]'),
    ])
    const state = EditorState.create({ schema, doc })
    const dispatch = vi.fn()
    const view = { state, dispatch } as never
    let currentBody = ''
    const controller = createTableAIEdit({ view, client, pollIntervalMs: 1, currentBody: () => currentBody })
    controller.open('tbl-1', '')
    await vi.waitFor(() => {
      expect(document.querySelector<HTMLButtonElement>('.table-ai-template')?.disabled).toBe(true)
    })
    const area = document.querySelector<HTMLTextAreaElement>('#table-ai-input')!
    area.value = '改成期间明细'
    document.querySelector("#table-ai-input")?.dispatchEvent(new Event("input"))
    ;(document.querySelector<HTMLButtonElement>('.ui-button--primary') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(document.querySelector('.table-ai-review')).not.toBeNull()
    })
    const cell = document.querySelector<HTMLButtonElement>('.table-ai-cell-added .table-ai-cell, td.table-ai-cell-added .table-ai-cell')
    const unavailable = document.querySelector<HTMLButtonElement>('.table-ai-template:disabled')!
    expect(unavailable.querySelector('.ask-ai-template-reason')?.textContent).toContain('缺少维度分组')
    expect(cell).not.toBeNull()
    cell!.click()
    const detail = document.querySelector<HTMLElement>('.table-ai-source-detail')!
    expect(detail.textContent).toContain('analysis_001')
    expect(detail.textContent).toContain('periodValues.0')
    const followUp = document.querySelector<HTMLTextAreaElement>('.ask-ai-composers textarea')!
    followUp.value = '标注最高收入'; followUp.dispatchEvent(new Event('input'))
    document.querySelector<HTMLButtonElement>('.ask-ai-composers .ui-button--primary')!.click()
    await vi.waitFor(() => expect(client.startTableAiEdit).toHaveBeenCalledTimes(2))
    expect(client.startTableAiEdit).toHaveBeenLastCalledWith('tbl-1', expect.objectContaining({
      instruction: '标注最高收入', previousEditId: 'tedit-00000001', baseBody: '',
    }))
    await vi.waitFor(() => expect(document.querySelector('.table-ai-review')).not.toBeNull())
    if (changed) currentBody = '| 项目 |\n| --- |\n| 用户的新内容 |'
    document.querySelector<HTMLButtonElement>('.ask-ai-review-dock:not([hidden]) .ui-button--primary')!.click()
    if (changed) {
      expect(dispatch).not.toHaveBeenCalled()
      expect(document.querySelector('.chart-ai-note')!.textContent).toContain('未覆盖新内容')
    } else {
      expect(dispatch).toHaveBeenCalledTimes(1)
      expect(document.querySelector('.ask-ai-receipt')?.textContent).toContain('已替换到正文')
      expect(document.querySelector<HTMLElement>('.ask-ai-panel')!.hidden).toBe(false)
      expect(document.querySelector('.table-ai-review')).toBeNull()
    }
    controller.dispose()
  })

  it('reopens an edited table through its original table id and previous edit id', async () => {
    document.body.innerHTML = '<div id="root"></div>'
    const client = {
      tableEditRecordByTableId: vi.fn(async () => ({
        editId: 'tedit-12345678abcdef00', tableId: 'tbl-original',
        newTableId: 'tbl-original-e12345678', markdown: '',
      })),
      tableTemplates: vi.fn(async () => ({ tableId: 'tbl-original', templates: [] })),
      startTableAiEdit: vi.fn(async () => ({ editId: 'tedit-00000002', status: 'queued' })),
      tableAiEditStatus: vi.fn(async () => ({
        editId: 'tedit-00000002', tableId: 'tbl-original', status: 'failed',
        error: { code: 'failed', message: 'stop' },
      })),
    } as unknown as ReportEditorClient
    const doc = schema.node('doc', null, [
      paragraph('[[table:tbl-original-e12345678]]'), table('old'), paragraph('[[/table:tbl-original-e12345678]]'),
    ])
    const state = EditorState.create({ schema, doc })
    const controller = createTableAIEdit({ view: { state, dispatch: vi.fn() } as never, client, pollIntervalMs: 1 })
    const baseBody = '| 项目 |\n| --- |\n| 当前值 |'
    controller.open('tbl-original-e12345678', baseBody)
    await vi.waitFor(() => expect(document.querySelector('#table-ai-input')).not.toBeNull())
    const area = document.querySelector<HTMLTextAreaElement>('#table-ai-input')!
    area.value = '继续调整'
    document.querySelector("#table-ai-input")?.dispatchEvent(new Event("input"))
    document.querySelector<HTMLButtonElement>('.ui-button--primary')!.click()
    await vi.waitFor(() => expect(client.startTableAiEdit).toHaveBeenCalled())
    expect(client.tableTemplates).toHaveBeenCalledWith('tbl-original-e12345678')
    expect(client.startTableAiEdit).toHaveBeenCalledWith('tbl-original-e12345678', expect.objectContaining({
      baseBody,
      previousEditId: 'tedit-12345678abcdef00',
      expectedSha256: expect.stringMatching(/^[0-9a-f]{64}$/),
    }))
    controller.dispose()
  })
})

describe('replaceTableProtocolBlock', () => {
  it('replaces only the selected table block in one transaction', () => {
    const doc = schema.node('doc', null, [
      paragraph('[[table:tbl-1]]'), table('old 1'), paragraph('[[/table:tbl-1]]'),
      paragraph('正文'),
      paragraph('[[table:tbl-2]]'), table('old 2'), paragraph('[[/table:tbl-2]]'),
    ])
    const { state, view } = viewFor(doc)
    expect(replaceTableProtocolBlock(view as never, 'tbl-1', '[[table:tbl-new]]\n| 项目 |\n| --- |\n| 新值 |\n\n[[/table:tbl-new]]')).toBe(true)
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    const transaction = view.dispatch.mock.calls[0][0]
    const next = state.apply(transaction)
    next.doc.check()
    expect(next.doc.textContent).toContain('tbl-new')
    expect(next.doc.textContent).toContain('old 2')
    expect(transaction.getMeta('SMART_REPORT_TABLE_PROTOCOL_EDIT')).toEqual({ tableId: 'tbl-new' })
  })

  it('wraps every header and data cell in a paragraph node', () => {
    const doc = schema.node('doc', null, [paragraph('[[table:tbl-1]]'), table('old'), paragraph('[[/table:tbl-1]]')])
    const { state, view } = viewFor(doc)
    expect(replaceTableProtocolBlock(view as never, 'tbl-1', '[[table:tbl-new]]\n| 项目 | 值 |\n| --- | ---: |\n| 新值 | 1 |\n\n[[/table:tbl-new]]')).toBe(true)
    const next = state.apply(view.dispatch.mock.calls[0][0])
    expect(() => next.doc.check()).not.toThrow()
    next.doc.descendants(node => {
      if (node.type.name === 'table_cell') expect(node.firstChild?.type.name).toBe('paragraph')
    })
  })

  it('replaces the old caption together with the table block', () => {
    const doc = schema.node('doc', null, [
      paragraph('旧表题'), paragraph('[[table:tbl-1]]'), table('old'), paragraph('[[/table:tbl-1]]'),
    ])
    const { state, view } = viewFor(doc)
    expect(replaceTableProtocolBlock(view as never, 'tbl-1', '新表题\n\n[[table:tbl-new]]\n| 项目 |\n| --- |\n| 新值 |\n\n[[/table:tbl-new]]', '旧表题')).toBe(true)
    const next = state.apply(view.dispatch.mock.calls[0][0])
    expect(next.doc.textContent).toContain('新表题')
    expect(next.doc.textContent).not.toContain('旧表题')
  })

  it('keeps unrelated prose when the original table had no caption', () => {
    const doc = schema.node('doc', null, [
      paragraph('需要保留的正文'), paragraph('[[table:tbl-1]]'), table('old'), paragraph('[[/table:tbl-1]]'),
    ])
    const { state, view } = viewFor(doc)
    expect(replaceTableProtocolBlock(view as never, 'tbl-1', '新表题\n\n[[table:tbl-new]]\n| 项目 |\n| --- |\n| 新值 |\n\n[[/table:tbl-new]]')).toBe(true)
    const next = state.apply(view.dispatch.mock.calls[0][0])
    expect(next.doc.textContent).toContain('需要保留的正文')
    expect(next.doc.textContent).toContain('新表题')
  })

  it('does not replace an unknown table marker', () => {
    const doc = schema.node('doc', null, [paragraph('[[table:tbl-1]]'), table('old'), paragraph('[[/table:tbl-1]]')])
    const { view } = viewFor(doc)
    expect(replaceTableProtocolBlock(view as never, 'missing', '[[table:new]]\n[[/table:new]]')).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
  })
})

describe('tableBodyMarkdown', () => {
  it('returns Markdown table rows rather than rendered HTML', () => {
    const markdown = '表题\n\n[[table:tbl-1]]\n| 项目 | 值 |\n| --- | ---: |\n| 收入 | 3,600 |\n\n[[/table:tbl-1]]\n\n正文'
    expect(tableBodyMarkdown(markdown, 'tbl-1')).toBe('| 项目 | 值 |\n| --- | ---: |\n| 收入 | 3,600 |')
  })
})
