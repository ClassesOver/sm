import { describe, expect, it } from 'vitest'
import { getBuiltInToolPresentation } from './builtInToolPresentation'

describe('内置工具展示路由', () => {
  it('识别关系候选结果', () => {
    const tool = {
      name: 'odoo.search_relation',
      result: {
        ok: true,
        operation: 'odoo.search_relation',
        field: 'partner_id',
        fieldLabel: '客户',
        fieldType: 'many2one',
        relation: 'res.partner',
        query: '上海',
        relationOperation: 'set',
        resolution: 'ambiguous',
        snapshotId: 'snapshot-1',
        hostRevision: 1,
        candidates: [{ id: 7, displayName: '上海客户', selected: false }]
      }
    }

    expect(getBuiltInToolPresentation(tool)).toMatchObject({
      kind: 'relation_search',
      result: tool.result
    })
  })

  it('识别筛选记录候选结果', () => {
    const tool = {
      name: 'odoo.apply_filter',
      result: {
        ok: true,
        operation: 'odoo.apply_filter',
        label: '上海客户',
        domain: [],
        count: 1,
        snapshotId: 'snapshot-1',
        hostRevision: 1,
        candidates: [{ token: 'record-1', displayName: '上海客户' }]
      }
    }

    expect(getBuiltInToolPresentation(tool)).toMatchObject({
      kind: 'record_candidates',
      result: tool.result
    })
  })

  it('拒绝字段缺失或候选项畸形的专用结果', () => {
    expect(getBuiltInToolPresentation({
      name: 'odoo.search_relation',
      result: { ok: true, candidates: [{ id: '7', displayName: '客户' }] }
    })).toEqual({ kind: 'default' })
    expect(getBuiltInToolPresentation({
      name: 'odoo.apply_filter',
      result: {
        ok: true,
        operation: 'odoo.apply_filter',
        label: '客户',
        domain: [],
        count: 1,
        snapshotId: 'snapshot-1',
        hostRevision: 1,
        candidates: [{ token: 7, displayName: '客户' }]
      }
    })).toEqual({ kind: 'default' })
    expect(getBuiltInToolPresentation({ name: 'custom.audit', result: {} })).toEqual({ kind: 'default' })
  })
})
