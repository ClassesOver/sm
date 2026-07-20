import type {
  AguiChatProps, AguiClientTool, MenuCatalogEntry, MenuCatalogSnapshot,
  OdooHostSnapshot, ProtocolHandshake
} from '../types'

export const testHostState: OdooHostSnapshot = {
  protocol: 'agui.odoo.v2',
  snapshotId: 'snapshot-test-1',
  hostRevision: 1,
  capturedAt: '2026-07-15T00:00:00.000Z',
  interactive: true,
  surface: 'dock',
  controller: {
    actionId: 1,
    controllerId: 'controller-test-1',
    dataPointId: 'data-test-1',
    viewType: 'form',
    mode: 'edit'
  },
  action: { id: 1, resModel: 'res.partner' },
  menu: false,
  record: {
    model: 'res.partner',
    resId: 7,
    values: { name: 'Acme' },
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

export const testHandshake: ProtocolHandshake = {
  protocol: 'agui.odoo.v2',
  moduleVersion: '12.0.8.8.1',
  bundleVersion: '12.0.8.8.1',
  agentProtocol: 'agui.odoo.v2',
  agentBundleVersion: '12.0.8.8.1',
  commandCatalogHash: 'a'.repeat(64),
  agentCommandCatalogHash: 'a'.repeat(64)
}

export const patchTool: AguiClientTool = {
  name: 'odoo.patch_current_form',
  parameters: { type: 'object' }
}

export function menuCatalog(
  entries: MenuCatalogEntry[] = [],
  overrides: Partial<MenuCatalogSnapshot> = {}
): MenuCatalogSnapshot {
  return {
    catalogId: 'catalog-test-1',
    catalogRevision: 1,
    capturedAt: '2026-07-15T00:00:00.000Z',
    ready: true,
    totalCount: entries.length,
    entries,
    ...overrides
  }
}

export function v2Props(overrides: Partial<AguiChatProps> = {}): AguiChatProps {
  return {
    handshake: testHandshake,
    hostState: testHostState,
    agentState: {},
    tools: [patchTool],
    menuCatalog: menuCatalog(),
    surface: 'dock',
    ...overrides,
    ...(overrides.session
      ? { session: { ...overrides.session, protocol: 'agui.odoo.v2' } }
      : {})
  }
}
