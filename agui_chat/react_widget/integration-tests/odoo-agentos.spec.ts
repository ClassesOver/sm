import { expect, type Page, test } from '@playwright/test'
import { startSessionTracking, trackedSessionIds } from './session-tracker'

const database = process.env.ODOO_E2E_DB || 'odoo12_agui_e2e'
const login = process.env.ODOO_E2E_LOGIN || 'admin'
const password = process.env.ODOO_E2E_PASSWORD || 'admin'
const workspaceSecret = process.env.AGUI_WORKSPACE_HMAC_SECRET || ''

interface ToolResult {
  result?: Record<string, unknown>
  ok?: boolean
  code?: string
  authorization_id?: string
  needs_confirmation?: boolean
  operation?: string
  preview?: {
    target?: Record<string, unknown>
    changes?: Array<Record<string, unknown>>
    riskReasons?: string[]
  }
  risk_reasons?: string[]
  receipt?: {
    changes?: Array<Record<string, unknown>>
    undo?: {
      available?: boolean
      authorization_id?: string
      status?: string
    }
  }
  snapshot?: Record<string, unknown>
  candidates?: Array<Record<string, unknown>>
  valid?: boolean
  invalidFields?: string[]
  discarded?: boolean
  saved?: boolean
  undone?: boolean
}

function minimalPdf(): Buffer {
  const stream = 'BT /F1 18 Tf 40 80 Td (PDF preview works) Tj ET'
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = objects.map((object, index) => {
    const offset = Buffer.byteLength(pdf)
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
    return offset
  })
  const xrefOffset = Buffer.byteLength(pdf)
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`
  return Buffer.from(pdf, 'ascii')
}

async function loginToOdoo(page: Page) {
  await page.goto(`/web/login?db=${encodeURIComponent(database)}`)
  await page.locator('input[name="login"]').fill(login)
  await page.locator('input[name="password"]').fill(password)
  await Promise.all([
    page.waitForURL(/\/web(?:#|$)/),
    page.locator('button[type="submit"]').click()
  ])
  await expect(page.locator('.o_web_client')).toBeVisible()
  await expect(page.locator('.o_agui_chat_runtime_host')).toHaveCount(1)
  await page.waitForFunction(() => {
    const webClient = (globalThis as any).odoo?.__DEBUG__?.services?.['web.web_client']
    const manager = webClient?.aguiChatSurfaceManager
    return Boolean(
      webClient?.action_manager?.getCurrentController() &&
      manager?.bridge?.catalog?.length
    )
  })
}

async function openAssistant(page: Page) {
  await page.getByRole('button', { name: '打开智能助手' }).click()
  await expect(page.getByRole('button', { name: '新建对话' })).toBeVisible()
}

async function openPartnerList(page: Page) {
  await page.evaluate(async () => {
    const webClient = (globalThis as any).odoo.__DEBUG__.services['web.web_client']
    await Promise.resolve(webClient.do_action({
      type: 'ir.actions.act_window',
      name: '联系人通信测试',
      res_model: 'res.partner',
      views: [[false, 'list'], [false, 'form']],
      target: 'current'
    }))
  })
  await expect(page.locator('.o_list_view')).toBeVisible()
  await expect.poll(() => currentHostState(page).then((state) => state.interactive)).toBe(true)
}

async function openFirstPartner(page: Page, edit = false) {
  await openPartnerList(page)
  const firstRow = page.locator('.o_list_view tbody tr.o_data_row').first()
  await expect(firstRow).toBeVisible()
  await firstRow.click()
  await expect(page.locator('.o_form_view')).toBeVisible()
  await expect.poll(() => currentHostState(page).then((state) => state.viewType)).toBe('form')
  if (edit) {
    const editButton = page.locator('.o_form_button_edit')
    if (await editButton.isVisible()) await editButton.click()
    await expect.poll(() => currentHostState(page).then((state) => state.mode)).toBe('edit')
  }
}

async function openPartner(page: Page, resId: number) {
  await page.evaluate(async (recordId) => {
    const webClient = (globalThis as any).odoo.__DEBUG__.services['web.web_client']
    await Promise.resolve(webClient.do_action({
      type: 'ir.actions.act_window',
      name: '联系人通信测试',
      res_model: 'res.partner',
      res_id: recordId,
      views: [[false, 'form']],
      target: 'current'
    }))
  }, resId)
  await expect(page.locator('.o_form_view')).toBeVisible()
  await expect.poll(() => currentHostState(page).then((state) => state.resId)).toBe(resId)
}

async function rpc<T>(page: Page, model: string, method: string, args: unknown[] = [], kwargs = {}): Promise<T> {
  return page.evaluate(async ({ modelName, methodName, positional, keyword }) => {
    const service = (globalThis as any).odoo.__DEBUG__.services['web.rpc']
    return service.query({
      model: modelName,
      method: methodName,
      args: positional,
      kwargs: keyword
    })
  }, { modelName: model, methodName: method, positional: args, keyword: kwargs })
}

async function sessionIds(page: Page): Promise<number[]> {
  return page.evaluate(async () => {
    const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
    const result = await Promise.resolve(manager.bridge.listSessions())
    return result.sessions.map((session: any) => Number(session.id))
  })
}

async function cleanupE2e(page: Page) {
  const created = await trackedSessionIds(page).catch(() => [])
  await rpc(page, 'agui.chat.test.document', 'cleanup_e2e', [
    'agui_chat_test', [], created
  ]).catch(() => undefined)
}

async function currentHostState(page: Page) {
  return page.evaluate(() => {
    const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
    const state = manager.hostState
    return {
      interactive: state.interactive,
      snapshotId: state.snapshotId,
      hostRevision: state.hostRevision,
      controllerId: state.controller.controllerId,
      dataPointId: state.controller.dataPointId,
      viewType: state.controller.viewType,
      mode: state.controller.mode,
      surface: state.surface,
      model: state.record?.model || state.selection?.model || false,
      resId: state.record?.resId || false,
      values: state.record?.values || {},
      dirty: state.record?.dirty || {},
      dirtyFields: state.record?.dirtyFields || [],
      fields: state.fields || {},
      capabilities: state.capabilities || {}
    }
  })
}

async function executeTool(
  page: Page,
  tool: string,
  args: Record<string, unknown> = {},
  options: {
    id?: string, approve?: boolean, target?: Record<string, unknown>,
    selectedMenu?: { menuId: number, actionId: number },
    runId?: string, threadId?: string
  } = {}
): Promise<{ decision: ToolResult, result: ToolResult, call: Record<string, unknown> }> {
  return page.evaluate(async ({ toolName, argumentsValue, toolOptions }) => {
    const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
    const state = manager.hostState
    const catalog = manager.call('agui_host', 'getMenuCatalog')
    const target = toolOptions.target || (['odoo.search_menu', 'odoo.open_menu'].includes(toolName) ? {
      snapshotId: state.snapshotId,
      hostRevision: state.hostRevision,
      catalogId: catalog.catalogId,
      catalogRevision: catalog.catalogRevision
    } : {
      snapshotId: state.snapshotId,
      hostRevision: state.hostRevision,
      controllerId: state.controller.controllerId,
      dataPointId: state.controller.dataPointId,
      model: state.record?.model || state.selection?.model || false,
      resId: state.record?.resId || false
    })
    const id = toolOptions.id || `e2e-${Date.now()}-${Math.random()}`
    const call = {
      id,
      tool: toolName,
      arguments: toolName.startsWith('odoo.business.')
        ? argumentsValue
        : { target, ...argumentsValue },
      context: {
        requestId: `request-${id}`,
        runId: toolOptions.runId || `run-${id}`,
        threadId: toolOptions.threadId || `thread-${id}`,
        selectedMenu: toolOptions.selectedMenu ? {
          ...toolOptions.selectedMenu,
          catalogId: catalog.catalogId,
          catalogRevision: catalog.catalogRevision
        } : undefined
      }
    }
    const decision = await Promise.resolve(manager.bridge.executeTool(call))
    let result = decision
    if (decision?.needs_confirmation && toolOptions.approve !== undefined) {
      result = await Promise.resolve(manager.bridge.confirmTool(
        call,
        decision.authorization_id,
        toolOptions.approve
      ))
    }
    return { decision, result, call }
  }, { toolName: tool, argumentsValue: args, toolOptions: options })
}

async function confirmTool(
  page: Page,
  call: Record<string, unknown>,
  authorizationId: string,
  approved = true
): Promise<ToolResult> {
  return page.evaluate(async ({ toolCall, token, approve }) => {
    const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
    return Promise.resolve(manager.bridge.confirmTool(toolCall, token, approve))
  }, { toolCall: call, token: authorizationId, approve: approved })
}

async function undoTool(page: Page, authorizationId: string): Promise<ToolResult> {
  return page.evaluate(async (token) => {
    const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
    return Promise.resolve(manager.bridge.undoTool(token))
  }, authorizationId)
}

async function rpcLoadingEvents(page: Page, operation: () => Promise<unknown>) {
  await page.evaluate(() => {
    const core = (globalThis as any).odoo.__DEBUG__.services['web.core']
    const tracker = { request: 0, response: 0, failed: 0 }
    const owner = {}
    core.bus.on('rpc_request', owner, () => { tracker.request += 1 })
    core.bus.on('rpc_response', owner, () => { tracker.response += 1 })
    core.bus.on('rpc_response_failed', owner, () => { tracker.failed += 1 })
    ;(globalThis as any).__aguiE2eRpcTracker = { core, owner, tracker }
  })
  try {
    await operation()
    return await page.evaluate(() => (globalThis as any).__aguiE2eRpcTracker.tracker)
  } finally {
    await page.evaluate(() => {
      const current = (globalThis as any).__aguiE2eRpcTracker
      current.core.bus.off('rpc_request', current.owner)
      current.core.bus.off('rpc_response', current.owner)
      current.core.bus.off('rpc_response_failed', current.owner)
      delete (globalThis as any).__aguiE2eRpcTracker
    })
  }
}

test.describe('@ 前端交互', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/agent/config', async (route) => {
      const declaration = await page.evaluate(() => {
        const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
        return manager.bridge.config
      })
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          protocol: declaration.protocol,
          bundle_version: declaration.bundle_version,
          command_catalog_hash: declaration.command_catalog_hash,
          skills: [{ id: 'audit', name: '合同审计', description: '核对合同字段' }]
        })
      })
    })
    await loginToOdoo(page)
  })

  test.afterEach(async ({ page }) => {
    if (!page.isClosed()) await cleanupE2e(page)
  })

  test('@ 菜单选择器支持真实鼠标点击', async ({ page }) => {
    await openPartnerList(page)
    await openAssistant(page)
    await page.getByRole('button', { name: '新建对话' }).click()
    const input = page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能')
    await input.fill('@')

    const picker = page.getByRole('dialog', { name: '添加到对话' })
    await picker.getByRole('option', { name: /菜单/ }).click()
    await expect(page.getByLabel('搜索菜单')).toBeVisible()

    await picker.getByRole('button', { name: '返回' }).click()
    await expect(picker.getByRole('option', { name: /技能/ })).toBeVisible()

    await picker.getByRole('option', { name: /菜单/ }).click()
    const menu = picker.getByRole('option').first()
    await expect(menu).toBeVisible()
    await menu.click()

    await expect(picker).toBeHidden()
    await expect(input).toHaveValue('')
    await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled()
  })
})

test.describe.serial('Odoo 与 AgentOS 多场景通信', () => {
  test.beforeEach(async ({ page }) => {
    await loginToOdoo(page)
    if (workspaceSecret) {
      await rpc(page, 'ir.config_parameter', 'set_param', [
        'agui_chat.workspace_hmac_secret', workspaceSecret
      ])
    }
    await startSessionTracking(page)
  })

  test.afterEach(async ({ page }) => {
    if (!page.isClosed()) await cleanupE2e(page)
  })

  test('精简目录、幂等重放和过期快照均 fail closed', async ({ page }) => {
    await openFirstPartner(page, true)
    const initial = await currentHostState(page)
    expect(initial).toMatchObject({ interactive: true, viewType: 'form', model: 'res.partner' })
    const catalog = await page.evaluate(() => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      return manager.bridge.catalog.map((tool: any) => tool.name)
    })
    expect(catalog).toEqual(expect.arrayContaining([
      'odoo.search_menu',
      'odoo.open_menu',
      'odoo.apply_filter',
      'odoo.open_record',
      'odoo.open_create',
      'odoo.activate_view_control'
    ]))
    expect(catalog).not.toEqual(expect.arrayContaining([
      'odoo.read_current_view',
      'odoo.open_action',
      'odoo.open_chat_surface',
      'odoo.switch_view'
    ]))

    const id = `validate-${Date.now()}`
    const first = await executeTool(page, 'odoo.validate_current_form', {}, { id })
    expect(first.result).toMatchObject({
      ok: true,
      code: 'ok',
      operation: 'odoo.validate_current_form',
      valid: true
    })

    const replay = await executeTool(page, 'odoo.validate_current_form', {}, { id })
    expect(replay.result).toEqual(first.result)

    const staleTarget = {
      snapshotId: initial.snapshotId,
      hostRevision: initial.hostRevision - 1,
      controllerId: initial.controllerId,
      dataPointId: initial.dataPointId,
      model: initial.model,
      resId: initial.resId
    }
    const stale = await executeTool(page, 'odoo.validate_current_form', {}, { target: staleTarget })
    expect(stale.result).toMatchObject({ ok: false, code: 'stale_snapshot' })
    await expect(page.locator('.o_form_view')).toBeVisible()
  })

  test('菜单经跨模型 Kanban 控件进入目标 action 并打开空白新建表单', async ({ page }) => {
    const documentCount = await rpc<number>(page, 'agui.chat.test.document', 'search_count', [[]])
    const navigationContext = {
      runId: `run-menu-leaf-${Date.now()}`,
      threadId: `thread-menu-leaf-${Date.now()}`
    }
    const searched = await executeTool(page, 'odoo.search_menu', {
      query: '入口看板'
    }, navigationContext)
    expect(searched.result).toMatchObject({
      ok: true,
      matchType: 'exact',
      matchCount: 1,
      candidates: [{
        name: '入口看板',
        fullPath: 'AG-UI 导航测试 / 入口看板',
        menuId: expect.any(Number),
        actionId: expect.any(Number)
      }]
    })
    const selected = searched.result.candidates?.[0] as { menuId: number, actionId: number }

    const openedMenu = await executeTool(page, 'odoo.open_menu', {
      menuId: selected.menuId,
      actionId: selected.actionId
    }, navigationContext)
    expect(openedMenu.result).toMatchObject({
      ok: true,
      operation: 'odoo.open_menu',
      snapshot: {
        interactive: true,
        controller: { viewType: 'kanban' }
      }
    })
    await expect(page.locator('.o_kanban_view')).toBeVisible()
    await expect.poll(() => currentHostState(page).then((state) => state.model)).toBe('agui.chat.test.option')

    const hubState = await currentHostState(page)
    const actionControl = hubState.capabilities.controls.find((control: any) =>
      control.type === 'action' && control.label.includes('打开测试单据')
    )
    expect(actionControl).toMatchObject({ token: expect.any(String), type: 'action' })
    const activated = await executeTool(page, 'odoo.activate_view_control', {
      controlToken: actionControl.token
    })
    expect(activated.result).toMatchObject({ ok: true, operation: 'odoo.activate_view_control' })
    await expect(page.locator('.o_list_view')).toBeVisible()
    await expect.poll(() => currentHostState(page).then((state) => state.model)).toBe('agui.chat.test.document')

    const created = await executeTool(page, 'odoo.open_create')
    expect(created.result).toMatchObject({ ok: true, operation: 'odoo.open_create', opened: true })
    await expect(page.locator('.o_form_view')).toBeVisible()
    await expect.poll(() => currentHostState(page).then((state) => ({
      model: state.model, resId: state.resId, mode: state.mode
    }))).toEqual({ model: 'agui.chat.test.document', resId: false, mode: 'edit' })
    expect(await rpc<number>(page, 'agui.chat.test.document', 'search_count', [[]])).toBe(documentCount)
  })

  test('重复叶子搜索保持歧义且不能授权导航', async ({ page }) => {
    await openPartnerList(page)
    const before = await currentHostState(page)
    const duplicateCount = await page.evaluate(() => {
      const webClient = (globalThis as any).odoo.__DEBUG__.services['web.web_client']
      const source = (() => {
        const pending = [...webClient.menu_data.children]
        while (pending.length) {
          const node = pending.shift()
          if (node?.name === '入口看板') return node
          pending.push(...(node?.children || []))
        }
        return null
      })()
      if (!source) throw new Error('未找到入口看板菜单')
      webClient.menu_data.children.push({
        id: 2147483000,
        name: 'AG-UI 重复菜单',
        action: '',
        children: [{
          id: 2147483001,
          name: source.name,
          action: source.action,
          children: []
        }]
      })
      const manager = webClient.aguiChatSurfaceManager
      return manager.call('agui_host', 'getMenuCatalog').entries.filter(
        (entry: any) => entry.name === '入口看板'
      ).length
    })
    expect(duplicateCount).toBe(2)

    const navigationContext = {
      runId: `run-menu-duplicate-${Date.now()}`,
      threadId: `thread-menu-duplicate-${Date.now()}`
    }
    const searched = await executeTool(page, 'odoo.search_menu', {
      query: '入口看板'
    }, navigationContext)
    expect(searched.result).toMatchObject({
      ok: true,
      matchType: 'exact',
      matchCount: 2,
      candidates: [
        { name: '入口看板', menuId: expect.any(Number), actionId: expect.any(Number) },
        { name: '入口看板', menuId: expect.any(Number), actionId: expect.any(Number) }
      ]
    })

    const candidate = searched.result.candidates?.[0] as { menuId: number, actionId: number }
    const opened = await executeTool(page, 'odoo.open_menu', candidate, navigationContext)
    expect(opened.result).toMatchObject({ ok: false, code: 'menu_search_required' })
    expect((await currentHostState(page)).snapshotId).toBe(before.snapshotId)
  })

  test('搜索后目录变化会拒绝旧目录 target', async ({ page }) => {
    await openPartnerList(page)
    const before = await currentHostState(page)
    const navigationContext = {
      runId: `run-menu-stale-${Date.now()}`,
      threadId: `thread-menu-stale-${Date.now()}`
    }
    const searched = await executeTool(page, 'odoo.search_menu', {
      query: '入口看板'
    }, navigationContext)
    expect(searched.result).toMatchObject({ matchType: 'exact', matchCount: 1 })
    const candidate = searched.result.candidates?.[0] as { menuId: number, actionId: number }

    await page.evaluate((menuId) => {
      const webClient = (globalThis as any).odoo.__DEBUG__.services['web.web_client']
      const pending = [...webClient.menu_data.children]
      while (pending.length) {
        const node = pending.shift()
        if (Number(node?.id) === menuId) {
          node.name = `${node.name}（已变更）`
          break
        }
        pending.push(...(node?.children || []))
      }
      webClient.aguiChatSurfaceManager.call('agui_host', 'getMenuCatalog')
    }, candidate.menuId)

    const opened = await executeTool(page, 'odoo.open_menu', candidate, {
      ...navigationContext,
      target: (searched.call.arguments as Record<string, unknown>).target as Record<string, unknown>
    })
    expect(opened.result).toMatchObject({ ok: false, code: 'stale_menu_catalog' })
    expect((await currentHostState(page)).snapshotId).toBe(before.snapshotId)
  })

  test('动态业务插件经独立确认执行并脱敏结果', async ({ page }) => {
    const command = 'odoo.business.test_document.confirm'
    const catalog = await page.evaluate(() => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      return manager.bridge.catalog.map((tool: any) => tool.name)
    })
    expect(catalog).toContain(command)

    const marker = `AGUI-E2E-业务插件-${Date.now()}`
    const documentId = await rpc<number>(page, 'agui.chat.test.document', 'create', [{
      name: marker,
      required_code: marker,
    }])
    const execution = await executeTool(page, command, {
      model: 'agui.chat.test.document',
      document_id: documentId,
      expected_state: 'draft',
    }, { approve: true })

    expect(execution.decision).toMatchObject({
      needs_confirmation: true,
      code: 'confirmation_required',
      authorization_id: expect.any(String),
    })
    expect(execution.result).toMatchObject({
      ok: true,
      operation: command,
      result: {
        document_id: documentId,
        state: 'confirmed',
        phone_number: '[redacted]',
        configured_secret: '[redacted]',
      },
    })
    const [document] = await rpc<Array<{ state: string }>>(
      page,
      'agui.chat.test.document',
      'read',
      [[documentId], ['state']]
    )
    expect(document.state).toBe('confirmed')
  })

  test('关系查询使用实时 domain/context 且不触发 Odoo 全局加载', async ({ page }) => {
    await openFirstPartner(page, true)
    const state = await currentHostState(page)
    const relation = Object.entries(state.fields).find(([name, field]: [string, any]) =>
      field.type === 'many2one' && !field.readonly && !field.invisible
    )
    expect(relation, '当前联系人表单应存在可编辑的 many2one 字段').toBeTruthy()
    const [fieldName] = relation!
    const query = state.values[fieldName]?.displayName || 'a'
    let toolResult: Awaited<ReturnType<typeof executeTool>> | undefined
    const loading = await rpcLoadingEvents(page, async () => {
      toolResult = await executeTool(page, 'odoo.search_relation', {
        field: fieldName,
        query,
        operation: 'set',
        limit: 8
      })
    })
    expect(loading).toEqual({ request: 0, response: 0, failed: 0 })
    expect(toolResult!.result).toMatchObject({ ok: true, operation: 'odoo.search_relation' })
    expect(toolResult!.result.candidates?.length).toBeGreaterThan(0)
  })

  test('patch 无需确认并通过原生保存写入数据库', async ({ page }) => {
    await openFirstPartner(page, false)
    const before = await currentHostState(page)
    expect(before.mode).toBe('readonly')
    const originalName = String(before.values.name)
    const temporaryName = `AG-UI 通信测试 ${Date.now()}`

    const patch = await executeTool(page, 'odoo.patch_current_form', {
      patch: { name: temporaryName }
    })
    expect(patch.decision).toMatchObject({
      ok: true,
      code: 'ok',
      enteredEditMode: true,
      saved: true
    })
    await expect.poll(() => currentHostState(page).then((state) => state.values.name)).toBe(temporaryName)
    await expect.poll(() => currentHostState(page).then((state) => state.dirtyFields)).toEqual([])

    const persistedName = await page.evaluate(async (resId) => {
      const rpc = (globalThis as any).odoo.__DEBUG__.services['web.rpc']
      const records = await rpc.query({
        model: 'res.partner',
        method: 'read',
        args: [[resId], ['name']],
        kwargs: {}
      })
      return records[0].name
    }, before.resId)
    expect(persistedName).toBe(temporaryName)

    const validation = await executeTool(page, 'odoo.validate_current_form')
    expect(validation.result).toMatchObject({ ok: true, valid: true, invalidFields: [] })

    const restored = await executeTool(page, 'odoo.patch_current_form', {
      patch: JSON.stringify([{ field: 'name', value: originalName }])
    })
    expect(restored.result).toMatchObject({ ok: true, saved: true })
    await expect.poll(() => currentHostState(page).then((state) => state.values.name)).toBe(originalName)
    expect((await currentHostState(page)).dirtyFields).toEqual([])
  })

  test('高风险 patch 经确认后可撤销，存在新修改时拒绝撤销', async ({ page }) => {
    const marker = `AGUI-E2E-闭环-${Date.now()}`
    const partnerId = await rpc<number>(page, 'res.partner', 'create', [{
      name: marker,
      function: '初始岗位'
    }])
    try {
      await openPartner(page, partnerId)
      const initial = await currentHostState(page)
      const sensitive = await executeTool(page, 'odoo.patch_current_form', {
        patch: { phone: '010-11111111' }
      })
      expect(sensitive.result).toMatchObject({ ok: false, code: 'field_sensitive' })

      const changedName = `${marker}-已确认`
      const changedFunction = '确认岗位'
      const prepared = await executeTool(page, 'odoo.patch_current_form', {
        patch: { name: changedName, function: changedFunction }
      })

      expect(prepared.decision).toMatchObject({
        ok: false,
        code: 'confirmation_required',
        needs_confirmation: true,
        risk_reasons: expect.arrayContaining(['multiple_fields']),
        preview: {
          target: {
            model: 'res.partner',
            resId: partnerId,
            hostRevision: initial.hostRevision
          },
          riskReasons: expect.arrayContaining(['multiple_fields']),
          changes: expect.arrayContaining([
            expect.objectContaining({
              field: 'name', label: expect.any(String),
              oldValue: marker, newValue: changedName
            }),
            expect.objectContaining({
              field: 'function', label: expect.any(String),
              oldValue: '初始岗位', newValue: changedFunction
            })
          ])
        }
      })
      expect((await rpc<any[]>(page, 'res.partner', 'read', [
        [partnerId], ['name', 'function']
      ]))[0]).toMatchObject({ name: marker, function: '初始岗位' })

      const applied = await confirmTool(
        page,
        prepared.call,
        String(prepared.decision.authorization_id)
      )
      expect(applied).toMatchObject({
        ok: true,
        saved: true,
        receipt: {
          changes: expect.arrayContaining([
            expect.objectContaining({ field: 'name', newValue: changedName }),
            expect.objectContaining({ field: 'function', newValue: changedFunction })
          ]),
          undo: {
            available: true,
            authorization_id: expect.any(String),
            status: 'available'
          }
        }
      })
      expect(applied).not.toHaveProperty('undo_payload')
      expect((await rpc<any[]>(page, 'res.partner', 'read', [
        [partnerId], ['name', 'function']
      ]))[0]).toMatchObject({ name: changedName, function: changedFunction })

      const undoToken = String(applied.receipt?.undo?.authorization_id)
      const undone = await undoTool(page, undoToken)
      expect(undone).toMatchObject({ ok: true, code: 'ok', saved: true, undone: true })
      expect((await rpc<any[]>(page, 'res.partner', 'read', [
        [partnerId], ['name', 'function']
      ]))[0]).toMatchObject({ name: marker, function: '初始岗位' })
      expect(await undoTool(page, undoToken)).toEqual(undone)

      const secondPatch = await executeTool(page, 'odoo.patch_current_form', {
        patch: { function: changedFunction }
      })
      expect(secondPatch.result).toMatchObject({ ok: true, saved: true })
      const conflictToken = String(secondPatch.result.receipt?.undo?.authorization_id)

      await page.locator('.o_form_button_edit').click()
      await page.locator('.o_form_view input[name="function"]:visible').fill('并发岗位')
      await page.locator('.o_form_view input[name="function"]:visible').blur()
      await expect.poll(() => currentHostState(page).then((state) => state.dirtyFields)).toContain('function')

      expect(await undoTool(page, conflictToken)).toMatchObject({
        ok: false,
        code: 'undo_conflict'
      })
      expect((await rpc<any[]>(page, 'res.partner', 'read', [
        [partnerId], ['function']
      ]))[0].function).toBe(changedFunction)
    } finally {
      await rpc(page, 'res.partner', 'unlink', [[partnerId]]).catch(() => undefined)
    }
  })

  test('保存只读表单时自动进入编辑模式', async ({ page }) => {
    await openFirstPartner(page, false)
    expect((await currentHostState(page)).mode).toBe('readonly')
    const saved = await executeTool(page, 'odoo.save_current_form', {}, { approve: true })
    expect(saved.decision).toMatchObject({ needs_confirmation: true })
    expect(saved.result).toMatchObject({
      ok: true,
      code: 'ok',
      saved: true,
      enteredEditMode: true
    })
  })

  test('host command 更新表单 DOM 后保留聊天草稿焦点和选区', async ({ page }) => {
    await openFirstPartner(page, false)
    await openAssistant(page)
    await page.getByRole('button', { name: '新建对话' }).click()
    const input = page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能')
    const draft = '未发送的聊天草稿'
    await expect(input).toBeEnabled()
    await input.fill(draft)
    await input.evaluate((element: HTMLTextAreaElement) => {
      element.focus()
      element.setSelectionRange(2, 6, 'backward')
    })

    const entered = await executeTool(page, 'odoo.enter_edit_mode')
    expect(entered.result).toMatchObject({ ok: true, editing: true, enteredEditMode: true })
    await expect.poll(() => currentHostState(page).then((state) => state.mode)).toBe('edit')
    await expect(input).toBeFocused()
    await expect(input).toHaveValue(draft)
    expect(await input.evaluate((element: HTMLTextAreaElement) => ({
      start: element.selectionStart,
      end: element.selectionEnd,
      direction: element.selectionDirection
    }))).toEqual({ start: 2, end: 6, direction: 'backward' })

    await page.keyboard.insertText('继续')
    await expect(input).toHaveValue(`${draft.slice(0, 2)}继续${draft.slice(6)}`)
  })

  test('chat 未聚焦时 host command 不主动聚焦 chat', async ({ page }) => {
    await openFirstPartner(page, false)
    await openAssistant(page)
    await page.getByRole('button', { name: '新建对话' }).click()
    const input = page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能')
    await expect(input).toBeEnabled()
    await input.blur()
    await expect(input).not.toBeFocused()

    const entered = await executeTool(page, 'odoo.enter_edit_mode')
    expect(entered.result).toMatchObject({ ok: true, editing: true, enteredEditMode: true })
    await expect.poll(() => currentHostState(page).then((state) => state.mode)).toBe('edit')
    await expect(input).not.toBeFocused()
  })

  test('用户在 host command 期间切到 Odoo 字段后 chat 不抢回焦点', async ({ page }) => {
    await openFirstPartner(page, false)
    await openAssistant(page)
    await page.evaluate(() => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      manager.openSurface('dock')
    })
    await page.getByRole('button', { name: '新建对话' }).click()
    const input = page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能')
    await expect(input).toBeEnabled()
    await input.fill('切换焦点草稿')
    await input.focus()
    await page.evaluate(() => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      const originalCall = manager.call
      manager.call = function (this: any, serviceName: string, methodName: string, ...args: unknown[]) {
        const result = originalCall.call(this, serviceName, methodName, ...args)
        if (serviceName !== 'agui_host' || methodName !== 'executeHostCommand') return result
        return result.then((value: unknown) => {
          const deferred = (globalThis as any).$.Deferred()
          manager.__aguiE2eReleaseHostCommand = () => deferred.resolve(value)
          return deferred.promise()
        })
      }
    })

    const execution = executeTool(page, 'odoo.enter_edit_mode')
    await page.waitForFunction(() => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      return typeof manager.__aguiE2eReleaseHostCommand === 'function'
    })
    const odooInput = page.getByRole('textbox', { name: '名称', exact: true }).first()
    await odooInput.click()
    await expect(odooInput).toBeFocused()
    await page.evaluate(() => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      manager.__aguiE2eReleaseHostCommand()
    })

    const entered = await execution
    expect(entered.result).toMatchObject({ ok: true, editing: true, enteredEditMode: true })
    await expect(odooInput).toBeFocused()
    await expect(input).not.toBeFocused()
    await expect(input).toHaveValue('切换焦点草稿')
  })

  test('AgentOS 客户端工具续跑只保留一次最终回复', async ({ page }) => {
    await openFirstPartner(page, true)
    let agentRequestCount = 0
    await page.route('http://127.0.0.1:7777/agui', async (route) => {
      agentRequestCount += 1
      const request = route.request().postDataJSON() as { state?: { host?: any } }
      const host = request.state?.host
      const event = (value: Record<string, unknown>) => `data: ${JSON.stringify(value)}\n\n`
      const body = agentRequestCount === 1
        ? event({ type: 'TOOL_CALL_START', toolCallId: 'validate-e2e', toolCallName: 'odoo.validate_current_form' }) +
          event({
            type: 'TOOL_CALL_ARGS',
            toolCallId: 'validate-e2e',
            delta: JSON.stringify({
              target: {
                snapshotId: host.snapshotId,
                hostRevision: host.hostRevision,
                controllerId: host.controller.controllerId,
                dataPointId: host.controller.dataPointId,
                model: host.record.model,
                resId: host.record.resId
              }
            })
          }) +
          event({ type: 'TOOL_CALL_END', toolCallId: 'validate-e2e' }) +
          event({ type: 'RUN_FINISHED' })
        : event({ type: 'TEXT_MESSAGE_START', messageId: 'validate-reply' }) +
          event({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'validate-reply', delta: '当前表单校验通过。' }) +
          event({ type: 'TEXT_MESSAGE_END', messageId: 'validate-reply' }) +
          event({ type: 'RUN_FINISHED' })
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Access-Control-Allow-Origin': 'http://127.0.0.1:18069',
          'Access-Control-Allow-Credentials': 'true'
        },
        body
      })
    })
    const sessionsBefore = await page.evaluate(async () => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      const result = await Promise.resolve(manager.bridge.listSessions())
      return result.sessions.map((session: any) => session.id)
    })
    await openAssistant(page)
    await page.getByRole('button', { name: '新建对话' }).click()
    const input = page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能')
    await expect(input).toBeEnabled()
    await input.fill('请调用 odoo.validate_current_form 校验当前表单，并只回复一次最终结论。')
    await page.getByLabel('发送消息', { exact: true }).click()
    await expect(page.getByRole('button', { name: '停止生成' })).toBeVisible()
    await expect(page.getByRole('button', { name: '停止生成' })).toBeHidden({ timeout: 90_000 })
    expect(agentRequestCount).toBe(2)

    await expect.poll(async () => page.evaluate(async (existingIds) => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      const result = await Promise.resolve(manager.bridge.listSessions())
      const created = result.sessions.find((session: any) => !existingIds.includes(session.id))
      if (!created) return 0
      const loaded = await Promise.resolve(manager.bridge.loadSession(created.id))
      return loaded.session.messages.length
    }, sessionsBefore), { timeout: 30_000 }).toBeGreaterThan(2)

    const created = await page.evaluate(async (existingIds) => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      const result = await Promise.resolve(manager.bridge.listSessions())
      const session = result.sessions.find((item: any) => !existingIds.includes(item.id))
      const loaded = await Promise.resolve(manager.bridge.loadSession(session.id))
      return { id: session.id, messages: loaded.session.messages }
    }, sessionsBefore)
    const assistantMessages = created.messages.filter((message: any) => message.role === 'assistant')
    const nonEmptyReplies = assistantMessages.filter((message: any) => String(message.content || '').trim())
    const tools = assistantMessages.flatMap((message: any) => message.tool_calls || [])
    expect(nonEmptyReplies).toHaveLength(1)
    expect(tools).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'odoo.validate_current_form', status: 'ok' })
    ]))
  })

  test('附件上传绑定当前聊天会话', async ({ page }) => {
    await openPartnerList(page)
    await openAssistant(page)
    await page.getByRole('button', { name: '新建对话' }).click()
    await expect(page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能')).toBeEnabled()

    const uploadResponse = page.waitForResponse((response) =>
      response.url().endsWith('/agui_chat/attachment/upload') && response.request().method() === 'POST'
    )
    await page.locator('.o_agui_chat_runtime_host input[type="file"]').setInputFiles({
      name: 'agui-upload-test.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('upload test')
    })
    const response = await uploadResponse
    expect(response.status()).toBe(200)
    expect(await response.json()).toMatchObject({
      attachment: { name: 'agui-upload-test.txt', mimeType: 'text/plain' }
    })
    await expect(page.getByText('agui-upload-test.txt')).toBeVisible()
    await expect(page.getByText(/文本文件\s*·\s*1\s*KB/)).toBeVisible()

    const deleteResponse = page.waitForResponse((candidate) =>
      candidate.url().endsWith('/agui_chat/attachment/delete') && candidate.request().method() === 'POST'
    )
    await page.getByLabel(/移除\s*agui-upload-test\.txt/).click()
    expect((await deleteResponse).status()).toBe(200)
  })

  test('生产文件预览在停靠窗口内完整显示', async ({ page }) => {
    await openPartnerList(page)
    await openAssistant(page)
    await page.getByRole('button', { name: '新建对话' }).click()
    const input = page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能')
    await expect(input).toBeEnabled()

    const uploadResponse = page.waitForResponse((response) =>
      response.url().endsWith('/agui_chat/attachment/upload') && response.request().method() === 'POST'
    )
    await page.locator('.o_agui_chat_runtime_host input[type="file"]').setInputFiles({
      name: '中文预览测试.pdf',
      mimeType: 'application/pdf',
      buffer: minimalPdf()
    })
    expect((await uploadResponse).status()).toBe(200)
    await expect(page.getByText('中文预览测试.pdf')).toBeVisible()

    await page.route('http://127.0.0.1:7777/workspace/upload', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true })
      })
    })
    await page.route('http://127.0.0.1:7777/agui', async (route) => {
      const event = (value: Record<string, unknown>) => `data: ${JSON.stringify(value)}\n\n`
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Access-Control-Allow-Origin': 'http://127.0.0.1:18069',
          'Access-Control-Allow-Credentials': 'true'
        },
        body: event({ type: 'TEXT_MESSAGE_START', messageId: 'preview-reply' }) +
          event({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'preview-reply', delta: '已收到附件' }) +
          event({ type: 'TEXT_MESSAGE_END', messageId: 'preview-reply' }) +
          event({ type: 'RUN_FINISHED' })
      })
    })
    await input.fill('预览附件')
    await page.getByRole('button', { name: '发送消息', exact: true }).click()
    const viewerBundleResponse = page.waitForResponse((response) =>
      response.url().includes('/agui_chat/static/lib/agui-chat-react/agui_file_viewer.')
    )
    const attachmentResponse = page.waitForResponse((response) =>
      /\/agui_chat\/attachment\/\d+$/.test(response.url()) &&
      response.request().method() === 'GET' && response.headers()['content-type'] === 'application/pdf'
    )
    await page.getByRole('button', { name: /文件预览:中文预览测试\.pdf/ }).click()

    const panel = page.getByRole('complementary', { name: '文件预览' })
    await expect(panel).toBeVisible()
    expect((await viewerBundleResponse).status()).toBe(200)
    const pdfResponse = await attachmentResponse
    expect(pdfResponse.status()).toBe(200)
    expect(pdfResponse.headers()['content-disposition']).toMatch(/^inline; filename\*=UTF-8''/)
    expect(Buffer.from(await pdfResponse.body()).subarray(0, 5).toString()).toBe('%PDF-')
    await expect(panel.locator('canvas').first()).toBeVisible()

    const bounds = await page.evaluate(() => {
      const host = document.querySelector('.o_agui_chat_runtime_host') as HTMLElement
      const panel = host.shadowRoot?.querySelector('.agui-file-preview') as HTMLElement
      return {
        host: host.getBoundingClientRect().toJSON(),
        panel: panel.getBoundingClientRect().toJSON(),
        position: getComputedStyle(panel).position
      }
    })
    expect(bounds.position).toBe('absolute')
    expect(bounds.panel.left).toBeGreaterThanOrEqual(bounds.host.left)
    expect(bounds.panel.right).toBeLessThanOrEqual(bounds.host.right)

    await panel.getByRole('button', { name: '关闭文件预览' }).click()
    await expect(panel).toBeHidden()
  })

  test('AgentOS SSE 断网不影响 Odoo，恢复后可继续聊天', async ({ page }) => {
    await openPartnerList(page)
    await openAssistant(page)
    await page.getByRole('button', { name: '新建对话' }).click()
    const input = page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能')
    await expect(input).toBeEnabled()

    await page.route('http://127.0.0.1:7777/agui', (route) => route.abort('failed'))
    await input.fill('故障隔离测试')
    await page.getByRole('button', { name: '发送消息' }).click()
    await expect(page.getByText(/网络|请求|连接|Failed|fetch/i).first()).toBeVisible()
    await expect(page.getByRole('button', { name: '停止生成' })).toBeHidden()
    await expect(input).toBeEnabled()
    await expect(page.locator('.o_list_view')).toBeVisible()

    await page.unroute('http://127.0.0.1:7777/agui')
    await input.fill('只回复：通信恢复成功')
    const send = page.getByRole('button', { name: '发送消息' })
    await expect(send).toBeEnabled()
    await send.click()
    await expect(page.getByText(/通信恢复成功/).last()).toBeVisible({ timeout: 90_000 })
    await expect(page.locator('.o_list_view')).toBeVisible()

  })
})
