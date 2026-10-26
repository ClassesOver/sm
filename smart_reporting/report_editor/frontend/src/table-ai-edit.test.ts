import { describe, expect, it, vi } from 'vitest'
import { Schema } from '@milkdown/kit/prose/model'
import { EditorState } from '@milkdown/kit/prose/state'
import { createTableAIEdit, replaceTableProtocolBlock } from './table-ai-edit'
import type { ReportEditorClient } from './api'

const schema = new Schema({ nodes: {
  doc: { content: 'block+' },
  paragraph: { content: 'text*', group: 'block' },
  table: { content: 'table_row+', group: 'block' },
  table_row: { content: 'table_cell+' },
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
  it('渲染逐格审阅并支持点击数据格查看来源', async () => {
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
    } as unknown as ReportEditorClient
    const doc = schema.node('doc', null, [
      paragraph('[[table:tbl-1]]'), table('old'), paragraph('[[/table:tbl-1]]'),
    ])
    const state = EditorState.create({ schema, doc })
    const view = { state, dispatch: vi.fn() } as never
    const controller = createTableAIEdit({ view, client, pollIntervalMs: 1 })
    controller.open('tbl-1', '')
    await vi.waitFor(() => {
      expect(document.querySelector<HTMLButtonElement>('.table-ai-template')?.disabled).toBe(true)
    })
    const area = document.querySelector<HTMLTextAreaElement>('#table-ai-input')!
    area.value = '改成期间明细'
    ;(document.querySelector<HTMLButtonElement>('.ui-button--primary') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(document.querySelector('.table-ai-review')).not.toBeNull()
    })
    const cell = document.querySelector<HTMLButtonElement>('.table-ai-cell-added .table-ai-cell, td.table-ai-cell-added .table-ai-cell')
    expect(cell).not.toBeNull()
    cell!.click()
    const detail = document.querySelector<HTMLElement>('.table-ai-source-detail')!
    expect(detail.textContent).toContain('analysis_001')
    expect(detail.textContent).toContain('periodValues.0')
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
    expect(next.doc.textContent).toContain('tbl-new')
    expect(next.doc.textContent).toContain('old 2')
    expect(transaction.getMeta('SMART_REPORT_TABLE_PROTOCOL_EDIT')).toEqual({ tableId: 'tbl-new' })
  })

  it('does not replace an unknown table marker', () => {
    const doc = schema.node('doc', null, [paragraph('[[table:tbl-1]]'), table('old'), paragraph('[[/table:tbl-1]]')])
    const { view } = viewFor(doc)
    expect(replaceTableProtocolBlock(view as never, 'missing', '[[table:new]]\n[[/table:new]]')).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
  })
})
