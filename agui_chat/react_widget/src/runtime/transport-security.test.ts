import { describe, expect, it } from 'vitest'
import { buildRunInput, endpoint, transportError, validateRunInput } from './transport'
import { menuCatalog, testHostState, v2Props } from '../test/fixtures'

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
    expect(() => endpoint({})).toThrow(/尚未配置/)
    expect(() => endpoint({ runtimeUrl: '//evil.example/agui' })).toThrow(/不允许/)
    expect(() => endpoint({ runtimeUrl: 'https://evil.example/agui' })).toThrow(/不允许/)
  })

  it('enforces message and encoded request limits', () => {
    const input = buildRunInput([
      { id: '1', role: 'tool', toolCallId: 'call-1', content: 'one' },
      { id: '2', role: 'tool', toolCallId: 'call-2', content: 'two' }
    ], v2Props(), 'thread-1', null, {})
    expect(() => validateRunInput(input, v2Props({ limits: { messages: 1 } }))).toThrow(/消息数量超过限制/)
    expect(() => validateRunInput(input, v2Props({ limits: { requestBytes: 10 } }))).toThrow(/请求大小超过配置限制/)
  })

  it('sends only the latest user message while preserving its attachments and current context', () => {
    const input = buildRunInput([
      { id: 'old-user', role: 'user', content: '第一轮' },
      { id: 'old-assistant', role: 'assistant', content: '旧回答' },
      {
        id: 'latest-user', role: 'user', content: '第三轮',
        attachments: [{
          id: '12', name: '数据.csv', mimeType: 'text/csv', size: 10,
          modality: 'document', workspacePath: 'attachments/latest-user/数据.csv'
        }],
        skills: [{ id: 'review', name: '审查', description: '检查数据', valid: true }]
      },
      { id: 'pending', role: 'assistant', content: '' }
    ], v2Props(), 'thread-1', 'pending', {})

    expect(input.messages).toEqual([{
      id: 'latest-user', role: 'user', content: '第三轮',
      attachments: [{
        id: '12', name: '数据.csv', mimeType: 'text/csv', size: 10,
        modality: 'document', workspacePath: 'attachments/latest-user/数据.csv'
      }]
    }])
    expect(input.context).toContainEqual({
      description: '已选智能体技能',
      value: JSON.stringify([{ id: 'review', name: '审查', description: '检查数据' }])
    })
    expect(input.context.some((item) => item.description === 'HRP 宿主快照')).toBe(true)
  })

  it('sends every consecutive trailing tool result in order', () => {
    const input = buildRunInput([
      { id: 'user', role: 'user', content: '处理页面' },
      { id: 'assistant', role: 'assistant', content: '', tool_calls: [] },
      { id: 'tool-1', role: 'tool', toolCallId: 'call-1', content: '{"ok":true}' },
      { id: 'tool-2', role: 'tool', toolCallId: 'call-2', content: '{"ok":false}' },
      { id: 'pending', role: 'assistant', content: '' }
    ], v2Props(), 'thread-1', 'pending', {})

    expect(input.messages).toEqual([
      { id: 'tool-1', role: 'tool', toolCallId: 'call-1', content: '{"ok":true}' },
      { id: 'tool-2', role: 'tool', toolCallId: 'call-2', content: '{"ok":false}' }
    ])
  })

  it('only forwards the controlled branch fields and accepts a stable run ID', () => {
    const input = buildRunInput(
      [{ id: 'user', role: 'user', content: '重新回答' }],
      v2Props(), 'target-thread', null, {}, {
        runId: 'stable-run',
        branch: {
          sourceThreadId: 'source-thread',
          sourceRunId: 'source-run',
          targetMessageId: 'assistant-1'
        }
      }
    )

    expect(input.runId).toBe('stable-run')
    expect(input.forwardedProps).toEqual({ branch: {
      sourceThreadId: 'source-thread',
      sourceRunId: 'source-run',
      targetMessageId: 'assistant-1'
    } })
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
        description: 'HRP 宿主快照',
        value: JSON.stringify({
          protocol: 'agui.odoo.v2',
          snapshotId: 'snapshot-test-1',
          hostRevision: 1,
          interactive: true,
          surface: 'dock',
          pageTarget: {
            snapshotId: 'snapshot-test-1',
            hostRevision: 1
          },
          menuTarget: {
            snapshotId: 'snapshot-test-1',
            hostRevision: 1,
            catalogId: 'catalog-test-1',
            catalogRevision: 1
          },
          viewTarget: {
            snapshotId: 'snapshot-test-1',
            hostRevision: 1,
            controllerId: 'controller-test-1',
            dataPointId: 'data-test-1',
            model: 'res.partner',
            resId: 7
          },
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
      { description: 'HRP 用户', value: '{"id":2,"name":"Administrator"}' },
      { description: '智能体 ID', value: 'odoo-assistant' }
    ])
    expect(input.forwardedProps).toEqual({})
  })

  it('binds the form target to the record instead of the window action', () => {
    const input = buildRunInput(
      [{ id: '1', role: 'user', content: 'update the current record' }],
      v2Props({
        hostState: {
          ...testHostState,
          action: { id: 1, resModel: 'res.partner', resId: false }
        }
      }),
      'thread-1',
      null,
      {}
    )
    const hostContext = input.context.find(
      (item) => item.description === 'HRP 宿主快照'
    )
    const snapshot = JSON.parse(hostContext?.value || '{}')

    expect(snapshot.action.resId).toBe(false)
    expect(snapshot.viewTarget).toEqual({
      snapshotId: testHostState.snapshotId,
      hostRevision: testHostState.hostRevision,
      controllerId: testHostState.controller.controllerId,
      dataPointId: testHostState.controller.dataPointId,
      model: 'res.partner',
      resId: 7
    })
  })

  it('keeps list query details in the browser and only sends the report scope', () => {
    const listHost = {
      ...testHostState,
      controller: {
        ...testHostState.controller,
        viewType: 'list' as const,
        mode: false as const
      },
      action: {
        id: 1,
        resModel: 'res.partner',
        domain: [['company_id', '=', 3]],
        context: { search_default_customer: 1 }
      },
      record: false as const,
      selection: {
        model: 'res.partner',
        ids: [7, 9],
        domain: [['name', 'ilike', '机密筛选值']],
        context: { allowed_company_ids: [3] }
      },
      capabilities: {
        ...testHostState.capabilities,
        records: [{ token: 'record-token', displayName: '机密客户名称' }],
        controls: [{
          token: 'control-token', type: 'open' as const, label: '机密客户名称',
          recordLabel: '机密客户名称'
        }]
      }
    }
    const input = buildRunInput(
      [{ id: 'report', role: 'user', content: '生成当前列表报表' }],
      v2Props({ hostState: listHost }),
      'thread-1',
      null,
      {}
    )
    const hostContext = JSON.parse(input.context.find(
      (item) => item.description === 'HRP 宿主快照'
    )?.value || '{}')

    expect(hostContext.selection).toEqual({
      model: 'res.partner', scope: 'selected', selectedCount: 2
    })
    expect(hostContext.action).not.toHaveProperty('domain')
    expect(hostContext.action).not.toHaveProperty('context')
    expect(input.state.host.selection).toEqual({
      model: 'res.partner', scope: 'selected', selectedCount: 2
    })
    expect(input.state.host.action).not.toHaveProperty('domain')
    expect(input.state.host.action).not.toHaveProperty('context')
    expect(hostContext.capabilities.records).toEqual([])
    expect(hostContext.capabilities.controls).toEqual([])
    expect((input.state.host.capabilities as { records: unknown[] }).records).toEqual([])
    expect(JSON.stringify(input)).not.toContain('机密筛选值')
    expect(JSON.stringify(input)).not.toContain('allowed_company_ids')
    expect(JSON.stringify(input)).not.toContain('机密客户名称')
  })

  it('keeps explicit selections without sending the menu catalog on the first run', () => {
    const menuMention = {
      menuId: 8, actionId: 42, name: '客户', path: ['销售', '客户'],
      fullPath: '销售 / 客户', catalogId: 'catalog-test-1', catalogRevision: 1, valid: true
    }
    const recordSelection = {
      token: 'record-token', displayName: '上海某公司',
      snapshotId: testHostState.snapshotId, hostRevision: testHostState.hostRevision
    }
    const input = buildRunInput([{
      id: 'selected', role: 'user', content: '打开它', menuMention, recordSelection
    }], v2Props({
      tools: [
        { name: 'odoo.search_menu', parameters: { type: 'object' } },
        { name: 'odoo.open_menu', parameters: { type: 'object' } }
      ],
      menuCatalog: menuCatalog([
        { ...menuMention },
        { menuId: 9, actionId: 43, name: '机密菜单', path: ['机密菜单'], fullPath: '机密菜单' }
      ])
    }), 'thread-1', null, {})

    expect(input.messages).toEqual([{ id: 'selected', role: 'user', content: '打开它' }])
    expect(input.context).toContainEqual({
      description: '已选 HRP 菜单',
      value: JSON.stringify({
        menuId: 8, actionId: 42, catalogId: 'catalog-test-1', catalogRevision: 1,
        name: '客户', path: ['销售', '客户'], fullPath: '销售 / 客户',
        navigationRequired: true, requiredFirstTool: 'odoo.open_menu'
      })
    })
    expect(input.context).toContainEqual({
      description: '已选 HRP 记录候选项', value: JSON.stringify(recordSelection)
    })
    expect(input.context.some((item) => item.description === '当前用户可见 HRP 菜单')).toBe(false)
  })

  it('adds the complete semantic menu catalog only after a same-version miss', () => {
    const entries = [
      { menuId: 8, actionId: 42, name: '报销单', path: ['费用', '报销单'], fullPath: '费用 / 报销单' },
      { menuId: 9, actionId: 43, name: '申请单', path: ['采购', '申请单'], fullPath: '采购 / 申请单' }
    ]
    const props = v2Props({
      tools: [
        { name: 'odoo.search_menu', parameters: { type: 'object' } },
        { name: 'odoo.open_menu', parameters: { type: 'object' } }
      ],
      menuCatalog: menuCatalog(entries)
    })
    const first = buildRunInput(
      [{ id: 'menu-user', role: 'user', content: '打开差旅入口' }],
      props, 'thread-1', null, {}
    )
    expect(first.context.some((item) => item.description === '当前用户可见 HRP 菜单')).toBe(false)

    const input = buildRunInput([
      { id: 'menu-user', role: 'user', content: '打开差旅入口' },
      {
        id: 'menu-result', role: 'tool', name: 'odoo.search_menu', toolCallId: 'search-1',
        content: JSON.stringify({
          matchType: 'none', candidates: [], catalogId: 'catalog-test-1', catalogRevision: 1
        })
      }
    ], props, 'thread-1', null, {})
    const menuContext = input.context.find((item) => item.description === '当前用户可见 HRP 菜单')
    const catalog = JSON.parse(menuContext?.value || '{}')

    expect(catalog).toEqual({
      catalogId: 'catalog-test-1', catalogRevision: 1,
      totalCount: 2, includedCount: 2, complete: true,
      navigationAuthorized: false, requiredTool: 'odoo.search_menu',
      paths: ['费用 / 报销单', '采购 / 申请单']
    })
    expect(menuContext?.value).not.toContain('menuId')
    expect(menuContext?.value).not.toContain('actionId')
  })

  it('marks exact menu navigation for required search and unique-result open stages', () => {
    const entry = {
      menuId: 9,
      actionId: 42,
      name: '报销单查询',
      path: ['费用报销', '单据查询', '报销单查询'],
      fullPath: '费用报销 / 单据查询 / 报销单查询'
    }
    const props = v2Props({
      tools: [
        { name: 'odoo.search_menu', parameters: { type: 'object' } },
        { name: 'odoo.open_menu', parameters: { type: 'object' } },
        { name: 'odoo.apply_filter', parameters: { type: 'object' } }
      ],
      menuCatalog: menuCatalog([entry])
    })
    const user = { id: 'menu-user', role: 'user' as const, content: '打开报销单查询' }

    const initial = buildRunInput([user], props, 'thread-1', null, {})
    expect(initial.context).toContainEqual({
      description: 'HRP 菜单导航请求',
      value: JSON.stringify({
        phase: 'search',
        query: '报销单查询',
        requiredFirstTool: 'odoo.search_menu',
        catalogId: 'catalog-test-1',
        catalogRevision: 1
      })
    })

    const wrongQuery = buildRunInput([
      user,
      {
        id: 'menu-search', role: 'tool' as const, name: 'odoo.search_menu',
        toolCallId: 'search-1', content: JSON.stringify({
          query: '付款单查询', matchType: 'exact', matchCount: 1, truncated: false,
          candidates: [entry], catalogId: 'catalog-test-1', catalogRevision: 1
        })
      }
    ], props, 'thread-1', null, {})
    expect(wrongQuery.context).toContainEqual({
      description: 'HRP 菜单导航请求',
      value: JSON.stringify({
        phase: 'search',
        query: '报销单查询',
        requiredFirstTool: 'odoo.search_menu',
        catalogId: 'catalog-test-1',
        catalogRevision: 1
      })
    })

    const searched = buildRunInput([
      user,
      {
        id: 'menu-search', role: 'tool' as const, name: 'odoo.search_menu',
        toolCallId: 'search-1', content: JSON.stringify({
          query: '报销单查询', matchType: 'exact', matchCount: 1, truncated: false,
          candidates: [entry],
          catalogId: 'catalog-test-1', catalogRevision: 1
        })
      }
    ], props, 'thread-1', null, {})
    expect(searched.context).toContainEqual({
      description: 'HRP 菜单导航请求',
      value: JSON.stringify({
        phase: 'open',
        query: '报销单查询',
        requiredFirstTool: 'odoo.open_menu',
        catalogId: 'catalog-test-1',
        catalogRevision: 1
      })
    })
    const navigationContext = searched.context.find(
      (item) => item.description === 'HRP 菜单导航请求'
    )
    expect(navigationContext?.value).not.toContain('menuId')
    expect(navigationContext?.value).not.toContain('actionId')

    const opened = buildRunInput([
      user,
      {
        id: 'menu-search', role: 'tool' as const, name: 'odoo.search_menu',
        toolCallId: 'search-1', content: JSON.stringify({
          query: '报销单查询', matchType: 'exact', matchCount: 1, truncated: false,
          candidates: [entry],
          catalogId: 'catalog-test-1', catalogRevision: 1
        })
      },
      {
        id: 'menu-open', role: 'tool' as const, name: 'odoo.open_menu',
        toolCallId: 'open-1', content: JSON.stringify({ ok: true, navigated: true })
      }
    ], props, 'thread-1', null, {})
    expect(opened.context.some((item) => item.description === 'HRP 菜单导航请求')).toBe(false)
  })

  it('does not force navigation for questions, unknown targets, or ambiguous results', () => {
    const entry = {
      menuId: 9,
      actionId: 42,
      name: '报销单查询',
      path: ['费用报销', '报销单查询'],
      fullPath: '费用报销 / 报销单查询'
    }
    const props = v2Props({
      tools: [
        { name: 'odoo.search_menu', parameters: { type: 'object' } },
        { name: 'odoo.open_menu', parameters: { type: 'object' } }
      ],
      menuCatalog: menuCatalog([entry])
    })

    for (const content of ['如何打开报销单查询', '打开不存在的菜单']) {
      const input = buildRunInput([
        { id: content, role: 'user', content }
      ], props, 'thread-1', null, {})
      expect(input.context.some((item) => item.description === 'HRP 菜单导航请求')).toBe(false)
    }

    const ambiguous = buildRunInput([
      { id: 'menu-user', role: 'user', content: '打开报销单查询' },
      {
        id: 'menu-search', role: 'tool', name: 'odoo.search_menu', toolCallId: 'search-1',
        content: JSON.stringify({
          query: '报销单查询', matchType: 'exact', matchCount: 2, truncated: false,
          candidates: [entry, { ...entry, menuId: 10, actionId: 43 }],
          catalogId: 'catalog-test-1', catalogRevision: 1
        })
      }
    ], props, 'thread-1', null, {})
    expect(ambiguous.context.some((item) => item.description === 'HRP 菜单导航请求')).toBe(false)
  })

  it('does not add semantic menu context unless both menu tools are enabled', () => {
    const messages = [
      { id: 'menu-user', role: 'user' as const, content: '打开差旅入口' },
      {
        id: 'menu-result', role: 'tool' as const, name: 'odoo.search_menu',
        toolCallId: 'search-1', content: JSON.stringify({
          matchType: 'none', candidates: [], catalogId: 'catalog-test-1', catalogRevision: 1
        })
      }
    ]

    for (const toolName of ['odoo.search_menu', 'odoo.open_menu']) {
      const input = buildRunInput(messages, v2Props({
        tools: [{ name: toolName, parameters: { type: 'object' } }],
        menuCatalog: menuCatalog([{
          menuId: 8, actionId: 42, name: '报销单',
          path: ['费用', '报销单'], fullPath: '费用 / 报销单'
        }])
      }), 'thread-1', null, {})

      expect(input.context.some(
        (item) => item.description === '当前用户可见 HRP 菜单'
      )).toBe(false)
    }
  })

  it('does not add semantic menu context for a stale catalog miss', () => {
    const props = v2Props({
      tools: [
        { name: 'odoo.search_menu', parameters: { type: 'object' } },
        { name: 'odoo.open_menu', parameters: { type: 'object' } }
      ],
      menuCatalog: menuCatalog([{
        menuId: 8, actionId: 42, name: '报销单',
        path: ['费用', '报销单'], fullPath: '费用 / 报销单'
      }])
    })

    for (const staleResult of [
      { catalogId: 'catalog-stale', catalogRevision: 1 },
      { catalogId: 'catalog-test-1', catalogRevision: 0 }
    ]) {
      const input = buildRunInput([
        { id: 'menu-user', role: 'user', content: '打开差旅入口' },
        {
          id: 'menu-result', role: 'tool', name: 'odoo.search_menu', toolCallId: 'search-1',
          content: JSON.stringify({ matchType: 'none', candidates: [], ...staleResult })
        }
      ], props, 'thread-1', null, {})

      expect(input.context.some(
        (item) => item.description === '当前用户可见 HRP 菜单'
      )).toBe(false)
    }
  })

  it('bounds semantic menu context by UTF-8 bytes without truncating paths', () => {
    const entries = Array.from({ length: 300 }, (_, index) => ({
      menuId: index + 1,
      actionId: index + 1000,
      name: `菜单${index}`,
      path: ['模块', `菜单${index}`],
      fullPath: `模块 / 菜单${index}${'路径'.repeat(300)}`
    }))
    const input = buildRunInput([
      { id: 'menu-context', role: 'user', content: '打开相关菜单' },
      {
        id: 'menu-miss', role: 'tool', name: 'odoo.search_menu', toolCallId: 'search-1',
        content: JSON.stringify({
          matchType: 'none', candidates: [], catalogId: 'catalog-test-1', catalogRevision: 1
        })
      }
    ], v2Props({
      tools: [
        { name: 'odoo.search_menu', parameters: { type: 'object' } },
        { name: 'odoo.open_menu', parameters: { type: 'object' } }
      ],
      menuCatalog: menuCatalog(entries)
    }), 'thread-1', null, {})
    const menuContext = input.context.find(
      (item) => item.description === '当前用户可见 HRP 菜单'
    )
    const catalog = JSON.parse(menuContext?.value || '{}')

    expect(catalog).toMatchObject({
      totalCount: 300,
      complete: false,
      navigationAuthorized: false,
      requiredTool: 'odoo.search_menu'
    })
    expect(new TextEncoder().encode(menuContext?.value || '').byteLength).toBeLessThanOrEqual(128 * 1024)
    expect(catalog.paths.length).toBeGreaterThan(0)
    expect(catalog.paths.length).toBeLessThan(entries.length)
    expect(catalog.paths.every((path: string) => entries.some((entry) => entry.fullPath === path))).toBe(true)
    expect(menuContext?.value).not.toContain('menuId')
    expect(menuContext?.value).not.toContain('actionId')
  })

  it('only exposes menu navigation until the selected menu opens successfully', () => {
    const menuMention = {
      menuId: 1448, actionId: 42, name: '费用申请单创建',
      path: ['费用', '费用申请单创建'], fullPath: '费用 / 费用申请单创建', valid: true
    }
    const tools = [
      { name: 'odoo.open_menu', parameters: { type: 'object' } },
      { name: 'odoo.open_create', parameters: { type: 'object' } }
    ]
    const userMessage = {
      id: 'selected-menu', role: 'user' as const, content: '', menuMention
    }
    const initial = buildRunInput(
      [userMessage], v2Props({ menuCatalog: menuCatalog([menuMention]), tools }),
      'thread-1', null, {}
    )

    expect(initial.tools.map((tool) => tool.name)).toEqual(['odoo.open_menu'])

    const navigationMessages = [
      userMessage,
      {
        id: 'assistant-menu', role: 'assistant' as const, content: '', tool_calls: [{
          id: 'menu-call', name: 'odoo.open_menu', args: { menuId: 1448, actionId: 42 }
        }]
      },
      {
        id: 'tool-menu', role: 'tool' as const, name: 'odoo.open_menu',
        toolCallId: 'menu-call', content: JSON.stringify({
          ok: true, operation: 'odoo.open_menu', navigated: true
        })
      }
    ]
    const wrongMenu = buildRunInput([
      navigationMessages[0],
      {
        ...navigationMessages[1],
        tool_calls: [{ id: 'menu-call', name: 'odoo.open_menu', args: { menuId: 1447, actionId: 42 } }]
      },
      navigationMessages[2]
    ], v2Props({ menuCatalog: menuCatalog([menuMention]), tools }), 'thread-1', null, {})
    expect(wrongMenu.tools.map((tool) => tool.name)).toEqual(['odoo.open_menu'])

    const afterNavigation = buildRunInput(
      navigationMessages, v2Props({ menuCatalog: menuCatalog([menuMention]), tools }),
      'thread-1', null, {}
    )

    expect(afterNavigation.tools.map((tool) => tool.name)).toEqual([
      'odoo.open_menu', 'odoo.open_create'
    ])
    const selectedMenu = afterNavigation.context.find(
      (item) => item.description === '已选 HRP 菜单'
    )
    expect(JSON.parse(selectedMenu?.value || '{}')).toMatchObject({
      navigationRequired: false,
      requiredFirstTool: false
    })
  })

  it('adds exact workspace paths and tools to Agent context', () => {
    const input = buildRunInput([{
      id: 'workspace', role: 'user', content: '检查这些内容', workspaceReferences: [
        { id: 'file', path: '合同/甲.txt', name: '甲.txt', isDirectory: false },
        { id: 'dir', path: '报表', name: '报表', isDirectory: true }
      ]
    }], v2Props(), 'thread-1', null, {})
    expect(input.context).toContainEqual({
      description: '已选工作区引用',
      value: JSON.stringify([
        { path: '合同/甲.txt', type: 'file', tool: 'workspace_read_file' },
        { path: '报表', type: 'directory', tool: 'workspace_list_files' }
      ])
    })
    expect(input.messages[0]).not.toHaveProperty('workspaceReferences')
  })

  it('maps authentication, permission, and rate-limit failures', () => {
    expect(transportError(401).message).toMatch(/登录状态已过期/)
    expect(transportError(403).message).toMatch(/没有.*权限/)
    expect(transportError(429).message).toMatch(/请求过于频繁/)
  })
})
