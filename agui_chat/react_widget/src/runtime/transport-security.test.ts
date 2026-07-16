import { describe, expect, it } from 'vitest'
import { buildRunInput, endpoint, transportError, validateRunInput } from './transport'
import { testHostState, v2Props } from '../test/fixtures'

describe('production transport contract', () => {
  it('uses the configured runtime while attachments are enabled', () => {
    expect(endpoint({ runtimeUrl: '/external/agui' })).toBe('/external/agui')
  })

  it('accepts same-origin paths and explicitly enabled development origins', () => {
    expect(endpoint({ runtimeUrl: '/contract-review/agui' })).toBe('/contract-review/agui')
    expect(endpoint({
      runtimeUrl: 'http://localhost:8000/agui',
      allowCrossOriginDev: true
    })).toBe('http://localhost:8000/agui')
  })

  it('rejects missing, protocol-relative, and unapproved absolute URLs', () => {
    expect(() => endpoint({})).toThrow(/not configured/)
    expect(() => endpoint({ runtimeUrl: '//evil.example/agui' })).toThrow(/not allowed/)
    expect(() => endpoint({ runtimeUrl: 'https://evil.example/agui' })).toThrow(/not allowed/)
  })

  it('enforces message and encoded request limits', () => {
    const input = buildRunInput([
      { id: '1', role: 'user', content: 'one' },
      { id: '2', role: 'user', content: 'two' }
    ], v2Props(), 'thread-1', null, {})
    expect(() => validateRunInput(input, v2Props({ limits: { messages: 1 } }))).toThrow(/Message limit/)
    expect(() => validateRunInput(input, v2Props({ limits: { requestBytes: 10 } }))).toThrow(/larger/)
  })

  it('emits the AgentOS RunAgentInput context contract', () => {
    const input = buildRunInput(
      [{ id: '1', role: 'user', content: 'hello' }],
      v2Props({
        user: { id: 2, name: 'Administrator' },
        agentId: 'odoo-assistant',
        context: { company: { id: 1, name: 'Main' } }
      }),
      'thread-1',
      null,
      {}
    )
    expect(input.context).toEqual([
      {
        description: 'Odoo host snapshot',
        value: JSON.stringify({
          protocol: 'agui.odoo.v2',
          snapshotId: 'snapshot-test-1',
          hostRevision: 1,
          interactive: true,
          surface: 'dock',
          controller: testHostState.controller,
          action: {
            id: 1,
            resModel: 'res.partner'
          },
          menu: false,
          record: testHostState.record,
          selection: false,
          fields: {},
          capabilities: testHostState.capabilities
        })
      },
      { description: 'company', value: '{"id":1,"name":"Main"}' },
      { description: 'Odoo user', value: '{"id":2,"name":"Administrator"}' },
      { description: 'Agent ID', value: 'odoo-assistant' }
    ])
    expect(input.forwardedProps).toEqual({})
  })

  it('sends only the selected menu and record candidate as structured context', () => {
    const menuMention = {
      menuId: 8, actionId: 42, name: '客户', path: ['销售', '客户'],
      fullPath: '销售 / 客户', valid: true
    }
    const recordSelection = {
      token: 'record-token', displayName: '上海某公司',
      snapshotId: testHostState.snapshotId, hostRevision: testHostState.hostRevision
    }
    const input = buildRunInput([{
      id: 'selected', role: 'user', content: '打开它', menuMention, recordSelection
    }], v2Props({
      menuOptions: [
        { ...menuMention },
        { menuId: 9, actionId: 43, name: '机密菜单', path: ['机密菜单'], fullPath: '机密菜单' }
      ]
    }), 'thread-1', null, {})

    expect(input.messages).toEqual([{ id: 'selected', role: 'user', content: '打开它' }])
    expect(input.context).toContainEqual({
      description: 'Selected Odoo menu',
      value: JSON.stringify({
        menuId: 8, actionId: 42, name: '客户', path: ['销售', '客户'], fullPath: '销售 / 客户'
      })
    })
    expect(input.context).toContainEqual({
      description: 'Selected Odoo record candidate', value: JSON.stringify(recordSelection)
    })
    expect(JSON.stringify(input)).not.toContain('机密菜单')
  })

  it('maps authentication, permission, and rate-limit failures', () => {
    expect(transportError(401).message).toMatch(/Authentication/)
    expect(transportError(403).message).toMatch(/permission/)
    expect(transportError(429).message).toMatch(/Too many/)
  })
})
