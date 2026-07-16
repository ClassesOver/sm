import { expect, type Page, test } from '@playwright/test'
import { startSessionTracking, trackedSessionIds } from './session-tracker'


const database = process.env.ODOO_E2E_DB || 'odoo12_agui_e2e'
const login = process.env.ODOO_E2E_LOGIN || 'admin'
const password = process.env.ODOO_E2E_PASSWORD || 'admin'


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
}

async function openDocuments(page: Page, resId?: number) {
  await page.evaluate(async (recordId) => {
    const webClient = (globalThis as any).odoo.__DEBUG__.services['web.web_client']
    await Promise.resolve(webClient.do_action({
      type: 'ir.actions.act_window',
      name: 'AG-UI 通用测试单据',
      res_model: 'agui.chat.test.document',
      res_id: recordId || false,
      views: recordId ? [[false, 'form']] : [[false, 'list'], [false, 'form']],
      target: 'current'
    }))
  }, resId || false)
  await expect(page.locator(resId ? '.o_form_view' : '.o_list_view')).toBeVisible()
  await expect.poll(() => hostState(page).then((state) => state.interactive)).toBe(true)
}

async function hostState(page: Page) {
  return page.evaluate(() => {
    const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
    const state = manager.hostState
    return {
      interactive: state.interactive,
      model: state.record?.model || false,
      resId: state.record?.resId || false,
      mode: state.controller?.mode || false,
      values: state.record?.values || {},
      dirtyFields: state.record?.dirtyFields || []
    }
  })
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

async function startAgentSession(page: Page) {
  const before = await sessionIds(page)
  await page.getByRole('button', { name: '打开智能助手' }).click()
  await page.getByRole('button', { name: '新建对话' }).click()
  await expect(page.getByPlaceholder('输入消息，开始提问')).toBeEnabled()
  return before
}

async function sendChineseMessage(page: Page, message: string) {
  const input = page.getByPlaceholder('输入消息，开始提问')
  await input.fill(message)
  await page.getByLabel('发送消息', { exact: true }).click()
  await expect(page.getByRole('button', { name: '停止生成' })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('button', { name: '停止生成' })).toBeHidden({ timeout: 120_000 })
}

async function createdSession(page: Page, before: number[]) {
  return expect.poll(async () => {
    return page.evaluate(async (existing) => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      const result = await Promise.resolve(manager.bridge.listSessions())
      const session = result.sessions.find((item: any) => !existing.includes(Number(item.id)))
      if (!session) return null
      const loaded = await Promise.resolve(manager.bridge.loadSession(session.id))
      return { id: Number(session.id), messages: loaded.session.messages }
    }, before)
  }, { timeout: 30_000 }).not.toBeNull().then(async () => {
    return page.evaluate(async (existing) => {
      const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
      const result = await Promise.resolve(manager.bridge.listSessions())
      const session = result.sessions.find((item: any) => !existing.includes(Number(item.id)))
      const loaded = await Promise.resolve(manager.bridge.loadSession(session.id))
      return { id: Number(session.id), messages: loaded.session.messages }
    }, before)
  })
}

function tools(messages: any[]) {
  return messages.flatMap((message) => message.tool_calls || [])
}

async function cleanup(page: Page, documentIds: number[]) {
  const created = await trackedSessionIds(page).catch(() => [])
  await rpc(page, 'agui.chat.test.document', 'cleanup_e2e', [
    'agui_chat_test', documentIds.filter(Boolean), created
  ]).catch(() => undefined)
}


test.describe.serial('真实 AgentOS 通用单据业务场景', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    testInfo.setTimeout(150_000)
    await loginToOdoo(page)
    await rpc(page, 'agui.chat.config', 'configure_test_environment')
    await startSessionTracking(page)
  })

  test('表单 modal 打开时聊天输入仍保持焦点', async ({ page }) => {
    const documentId = await rpc<number>(page, 'agui.chat.test.document', 'create', [{
      name: `AGUI-E2E-MODAL-${Date.now()}`,
      required_code: 'MODAL-001'
    }])
    try {
      await openDocuments(page, documentId)
      await page.getByRole('button', { name: '打开智能助手' }).click()
      await page.evaluate(() => {
        const modal = document.createElement('div')
        modal.className = 'modal'
        modal.tabIndex = -1
        modal.setAttribute('role', 'dialog')
        modal.setAttribute('data-agui-focus-test', 'true')
        modal.innerHTML = '<div class="modal-dialog"><div class="modal-content">' +
          '<input aria-label="明细弹窗输入" /></div></div>'
        document.body.appendChild(modal)
        ;(globalThis as any).$(modal).modal({ backdrop: false, keyboard: false, show: true })
      })
      await expect(page.locator('[data-agui-focus-test].in')).toBeVisible()

      const input = page.getByPlaceholder('输入消息，开始提问')
      await input.click()
      await expect(input).toBeFocused()
      await page.keyboard.type('modal 输入回归')
      await expect(input).toHaveValue('modal 输入回归')
    } finally {
      await page.evaluate(() => {
        const modal = document.querySelector('[data-agui-focus-test]')
        if (!modal) return
        ;(globalThis as any).$(modal).modal('hide')
        modal.remove()
      }).catch(() => undefined)
      await cleanup(page, [documentId])
    }
  })

  test('中文指令从空白表单新建并持久化单据', async ({ page }) => {
    const marker = `AGUI-E2E-新建-${Date.now()}`
    let documentId = 0
    let beforeSessions = await sessionIds(page)
    try {
      await openDocuments(page)
      await page.locator('.o_list_button_add').click()
      await expect(page.locator('.o_form_view')).toBeVisible()
      await expect.poll(() => hostState(page).then((state) => state.mode)).toBe('edit')
      beforeSessions = await startAgentSession(page)

      await sendChineseMessage(page,
        `请立即调用 odoo.patch_current_form 在当前空白通用测试单据填写并保存：` +
        `单据名称为“${marker}”，必填编码为“CREATE-001”，数量为3，金额为12.5，` +
        `优先级使用 high，单据类型使用 standard。不要只解释，必须实际调用工具。`
      )

      const state = await hostState(page)
      documentId = Number(state.resId)
      expect(state).toMatchObject({ model: 'agui.chat.test.document' })
      expect(documentId).toBeGreaterThan(0)
      const records = await rpc<any[]>(page, 'agui.chat.test.document', 'read', [
        [documentId], ['name', 'required_code', 'quantity', 'amount', 'priority', 'document_type']
      ])
      expect(records[0]).toMatchObject({
        name: marker,
        required_code: 'CREATE-001',
        quantity: 3,
        amount: 12.5,
        priority: 'high',
        document_type: 'standard'
      })
      const session = await createdSession(page, beforeSessions)
      expect(tools(session.messages)).toEqual(expect.arrayContaining([
        expect.objectContaining({ name: 'odoo.patch_current_form', status: 'ok' })
      ]))
    } finally {
      await cleanup(page, [documentId])
    }
  })

  test('中文多轮指令刷新隐藏 domain 并写入新候选', async ({ page }) => {
    const marker = `AGUI-E2E-DOMAIN-${Date.now()}`
    const special = await rpc<any[]>(page, 'agui.chat.test.option', 'search_read', [], {
      domain: [['name', '=', '特殊唯一候选']], fields: ['id'], limit: 1
    })
    const documentId = await rpc<number>(page, 'agui.chat.test.document', 'create', [{
      name: marker,
      required_code: 'DOMAIN-001',
      document_type: 'standard',
      domain_key: 'standard'
    }])
    let beforeSessions = await sessionIds(page)
    try {
      await openDocuments(page, documentId)
      beforeSessions = await startAgentSession(page)
      await sendChineseMessage(page,
        '请调用 odoo.patch_current_form 把当前单据的 document_type 修改为 special 并保存。必须实际调用工具。'
      )
      await expect.poll(() => hostState(page).then((state) => state.values.domain_key)).toBe('special')

      await sendChineseMessage(page,
        '请先调用 odoo.search_relation 在 candidate_id 字段用 set 操作精确搜索“特殊唯一候选”，' +
        '再调用 odoo.patch_current_form 把搜索得到的明确整数 ID 写入 candidate_id 并保存。'
      )
      const records = await rpc<any[]>(page, 'agui.chat.test.document', 'read', [
        [documentId], ['document_type', 'domain_key', 'candidate_id']
      ])
      expect(records[0]).toMatchObject({ document_type: 'special', domain_key: 'special' })
      expect(records[0].candidate_id[0]).toBe(special[0].id)
      const session = await createdSession(page, beforeSessions)
      expect(tools(session.messages).map((tool) => tool.name)).toEqual(expect.arrayContaining([
        'odoo.search_relation', 'odoo.patch_current_form'
      ]))
    } finally {
      await cleanup(page, [documentId])
    }
  })

  test('中文保存指令在批准前暂停，批准后只保存一次', async ({ page }) => {
    const marker = `AGUI-E2E-CONFIRM-${Date.now()}`
    const documentId = await rpc<number>(page, 'agui.chat.test.document', 'create', [{
      name: marker,
      required_code: 'CONFIRM-001',
      quantity: 1
    }])
    let beforeSessions = await sessionIds(page)
    try {
      await openDocuments(page, documentId)
      await page.locator('.o_form_button_edit').click()
      await page.locator('input[name="quantity"]').fill('9')
      await page.locator('input[name="quantity"]').blur()
      await expect.poll(() => hostState(page).then((state) => state.dirtyFields)).toContain('quantity')
      beforeSessions = await startAgentSession(page)

      const input = page.getByPlaceholder('输入消息，开始提问')
      await input.fill('请调用 odoo.save_current_form 保存当前表单。不要调用 patch，不要只解释。')
      await page.getByLabel('发送消息', { exact: true }).click()
      await expect(page.getByText('需要确认：保存当前表单')).toBeVisible({ timeout: 120_000 })
      expect((await rpc<any[]>(page, 'agui.chat.test.document', 'read', [
        [documentId], ['quantity']
      ]))[0].quantity).toBe(1)

      await page.getByRole('button', { name: '批准', exact: true }).click()
      await expect(page.getByRole('button', { name: '停止生成' })).toBeHidden({ timeout: 120_000 })
      await expect.poll(async () => (await rpc<any[]>(page, 'agui.chat.test.document', 'read', [
        [documentId], ['quantity']
      ]))[0].quantity).toBe(9)
      const session = await createdSession(page, beforeSessions)
      const saveTools = tools(session.messages).filter((tool) => tool.name === 'odoo.save_current_form')
      expect(saveTools).toHaveLength(1)
      expect(saveTools[0].status).toBe('ok')
    } finally {
      await cleanup(page, [documentId])
    }
  })
})
