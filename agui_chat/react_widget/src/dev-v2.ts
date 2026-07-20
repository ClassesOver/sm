import type { OdooHostSnapshot, ProtocolHandshake } from './types'

export const devHandshake: ProtocolHandshake = {
  protocol: 'agui.odoo.v2',
  moduleVersion: '12.0.8.8.1',
  bundleVersion: '12.0.8.8.1',
  agentProtocol: 'agui.odoo.v2',
  agentBundleVersion: '12.0.8.8.1',
  commandCatalogHash: 'a'.repeat(64),
  agentCommandCatalogHash: 'a'.repeat(64)
}

export const devHostState: OdooHostSnapshot = {
  protocol: 'agui.odoo.v2',
  snapshotId: 'dev-snapshot-1',
  hostRevision: 1,
  capturedAt: '2026-07-15T00:00:00.000Z',
  interactive: true,
  surface: 'dock',
  controller: {
    actionId: 1,
    controllerId: 'dev-controller-1',
    dataPointId: 'dev-record-1',
    viewType: 'form',
    mode: 'edit'
  },
  action: { id: 1, name: '销售商机', resModel: 'crm.lead' },
  menu: false,
  record: {
    model: 'crm.lead',
    resId: 42,
    values: { name: '年度续约', expected_revenue: 126000 },
    dirty: {},
    dirtyFields: []
  },
  selection: false,
  fields: {},
  capabilities: {
    create: true,
    open: true,
    edit: true,
    filter: false,
    totalCount: 1,
    filterFields: {},
    records: [],
    controls: [],
    x2many: []
  }
}
