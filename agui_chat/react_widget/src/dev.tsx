import type { AguiChatProps, ChatMessage } from './types'
import { AguiChat, ChatRuntime } from './index'
import { devHandshake, devHostState } from './dev-v2'

type Scenario = 'empty' | 'complete' | 'streaming' | 'markdown' | 'tool' | 'relation' | 'attachments' | 'error' | 'panels' | 'workspace'

const requested = new URLSearchParams(window.location.search).get('scenario')
const scenario: Scenario = ['empty', 'complete', 'streaming', 'markdown', 'tool', 'relation', 'attachments', 'error', 'panels', 'workspace'].includes(requested || '')
  ? requested as Scenario
  : 'complete'

const user: ChatMessage = { id: 'message-user-001', role: 'user', content: '请整理今天的销售跟进重点。', created_at: '2026-07-15T08:00:00+08:00' }
const assistant: ChatMessage = {
  id: 'message-assistant-001', role: 'assistant', created_at: '2026-07-15T08:00:10+08:00',
  content: '今天建议优先处理 **3 个高价值商机**，确认报价有效期，并在下午 4 点前完成回访记录。'
}

const scenarios: Record<Scenario, ChatMessage[]> = {
  empty: [],
  complete: [user, assistant],
  streaming: [user],
  markdown: [
    { ...user, content: '展示销售汇总和调用示例。' },
    {
      ...assistant,
      content: [
        '## 销售摘要', '',
        '| 指标 | 本周 | 变化 |', '| --- | ---: | ---: |', '| 新商机 | 18 | +12% |', '| 成交额 | ¥126,000 | +8% |', '',
        '- 优先跟进高意向客户', '- 核对两份待确认报价', '',
        '```ts', "const opportunities = await odoo.searchRead('crm.lead')", "console.log(opportunities.length)", '```'
      ].join('\n')
    }
  ],
  tool: [
    { ...user, content: '把报价单 SO026 的有效期延长 7 天。' },
    {
      ...assistant,
      content: '已准备好变更，确认后将写入 Odoo。',
      tool_calls: [{
        id: 'tool-call-001', name: 'update_sale_order', status: 'needs_confirmation', needs_confirmation: true,
        args: { order: 'SO026', validity_days: 7 },
        result: { operation: '更新报价有效期', target: { model: 'sale.order', name: 'SO026' }, patch: { validity_date: '2026-07-22' } }
      }]
    }
  ],
  relation: [
    { ...user, content: '把当前商机的客户改为上海的客户。' },
    {
      ...assistant,
      content: '找到多个符合当前表单条件的客户，请明确选择一个。',
      tool_calls: [{
        id: 'tool-relation-001', name: 'odoo.search_relation', status: 'ok',
        args: { field: 'partner_id', query: '上海', operation: 'set' },
        result: {
          ok: true, operation: 'odoo.search_relation', field: 'partner_id', fieldLabel: '客户',
          fieldType: 'many2one', relation: 'res.partner', query: '上海', relationOperation: 'set',
          resolution: 'ambiguous', snapshotId: 'dev-snapshot-1', hostRevision: 1,
          candidates: [
            { id: 42, displayName: '上海星河科技有限公司', selected: false },
            { id: 57, displayName: '上海远景贸易有限公司', selected: false },
            { id: 81, displayName: '上海云帆企业服务有限公司', selected: false }
          ]
        }
      }]
    }
  ],
  attachments: [
    {
      ...user,
      content: '请检查这两份附件。',
      attachments: [
        { id: 'dev-image', name: 'sales-dashboard.svg', mimeType: 'image/svg+xml', size: 18420, modality: 'image' },
        { id: 'dev-document', name: 'Q3-sales-brief.pdf', mimeType: 'application/pdf', size: 82400, modality: 'document' }
      ]
    },
    { ...assistant, content: '图片中的管道分布清晰，文档附件也已成功关联到当前消息。' }
  ],
  error: [user, { ...assistant, streaming_error: '上游服务暂时不可用，请稍后重试。' }],
  panels: [user, assistant],
  workspace: [user, assistant]
}

const originalFetch = window.fetch.bind(window)
window.fetch = async (input, init) => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  if (!url.endsWith('/dev/agui')) return originalFetch(input, init)

  const encoder = new TextEncoder()
  let timer: number | undefined
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const messageId = 'message-stream-001'
      controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'TEXT_MESSAGE_START', messageId })}\n\n`))
      timer = window.setTimeout(() => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'TEXT_MESSAGE_CONTENT', messageId, delta: '正在读取商机数据并生成摘要' })}\n\n`))
      }, 150)
      init?.signal?.addEventListener('abort', () => {
        if (timer !== undefined) window.clearTimeout(timer)
        try { controller.close() } catch (_error) { /* stream already closed */ }
      }, { once: true })
    },
    cancel() { if (timer !== undefined) window.clearTimeout(timer) }
  })
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

const root = document.getElementById('root')
if (!root) throw new Error('未找到开发预览根节点。')

const props: AguiChatProps = {
  runtimeUrl: scenario === 'error' ? undefined : '/dev/agui',
  handshake: devHandshake,
  hostState: devHostState,
  agentState: {},
  tools: [],
  menuOptions: [],
  agentSkills: [
    { id: 'contract-audit', name: '合同审计', description: '核对合同条款、金额和关键日期' },
    { id: 'sales-analysis', name: '销售分析', description: '分析销售机会与客户跟进优先级' },
    { id: 'data-quality', name: '数据质量检查', description: '识别缺失字段和异常业务数据' }
  ],
  hostBridge: {
    searchMentions: async (request) => ({
      candidates: request.scope === 'menu' ? [
        { candidateToken: 'menu-sales', resourceKey: 'menu:1', kind: 'menu', label: '销售订单', detail: '销售 / 订单 / 销售订单', model: 'sale.order', actions: ['open', 'create'], expiresAt: '2099-01-01 00:00:00' },
        { candidateToken: 'menu-contracts', resourceKey: 'menu:2', kind: 'menu', label: '客户合同', detail: '销售 / 合同 / 客户合同', model: 'contract.contract', actions: ['open'], expiresAt: '2099-01-01 00:00:00' }
      ] : [],
      modelScopes: [
        { model: 'res.partner', label: '客户' },
        { model: 'sale.order', label: '销售订单' },
        { model: 'contract.contract', label: '合同' },
        { model: 'crm.lead', label: '销售机会' }
      ]
    }),
    bindMention: async (request) => {
      const action: 'open' | 'create' = request.action === 'create' ? 'create' : 'open'
      const candidate = request.candidateToken === 'menu-contracts'
        ? { resourceKey: 'menu:2', label: '客户合同', detail: '销售 / 合同 / 客户合同', model: 'contract.contract' }
        : { resourceKey: 'menu:1', label: '销售订单', detail: '销售 / 订单 / 销售订单', model: 'sale.order' }
      return { ok: true, reference: { id: `visual-${request.candidateToken}-${action}`, token: `visual-${request.candidateToken}-${action}`, kind: 'menu', action, expiresAt: '2099-01-01 00:00:00', valid: true, pageAction: true, ...candidate } }
    }
  },
  surface: 'dock',
  attachments: { enabled: true, maxFiles: 5, maxFileSize: 10 * 1024 * 1024 },
  threadId: 'visual-thread-001',
  initialMessages: scenarios[scenario],
  sessions: [
    { id: 101, thread_id: 'visual-thread-001', name: '销售跟进', write_date: '2026-07-15T08:00:00+08:00' },
    { id: 102, thread_id: 'visual-thread-002', name: '库存复核', write_date: '2026-07-14T16:30:00+08:00' }
  ],
  session: scenario === 'panels'
    ? { id: 101, protocol: 'agui.odoo.v2', thread_id: 'visual-thread-001', name: '销售跟进', messages: scenarios.panels }
    : { id: 100, protocol: 'agui.odoo.v2', thread_id: 'visual-thread-001', name: '视觉测试', messages: scenarios[scenario] },
  suggestions: [
    { title: '销售摘要', message: '汇总今天需要跟进的销售机会' },
    { title: '检查库存', message: '检查低于安全库存的产品' },
    { title: '待办事项', message: '列出本周尚未完成的活动' }
  ],
  ui: { initialSidebarCollapsed: scenario !== 'panels' },
  __debug: true
}

const handle = AguiChat.mount(root, props)
const devRuntime = handle.__runtime as ChatRuntime
devRuntime.uploadAttachment = async (file, onProgress) => {
  onProgress?.(35)
  await new Promise((resolve) => window.setTimeout(resolve, 120))
  onProgress?.(100)
  return {
    id: `dev-upload-${encodeURIComponent(file.name)}`,
    name: file.name,
    mimeType: file.type || 'application/octet-stream',
    size: file.size,
    modality: file.type.startsWith('image/') ? 'image' : 'document'
  }
}
devRuntime.deleteAttachment = async () => undefined
if (scenario === 'workspace') {
  devRuntime.listWorkspace = async () => [
    { path: '报表归档', name: '报表归档', isDirectory: true, size: 0, mimeType: false, modifiedAt: '2026-07-20T08:30:00+08:00' },
    { path: '季度工作区摘要.txt', name: '季度工作区摘要.txt', isDirectory: false, size: 1860, mimeType: 'text/plain', modifiedAt: '2026-07-20T09:42:00+08:00' },
    { path: '客户合同汇总.pdf', name: '客户合同汇总.pdf', isDirectory: false, size: 328400, mimeType: 'application/pdf', modifiedAt: '2026-07-19T16:20:00+08:00' },
    { path: '华东销售数据.xlsx', name: '华东销售数据.xlsx', isDirectory: false, size: 84520, mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', modifiedAt: '2026-07-19T14:10:00+08:00' },
    { path: '跟进事项.csv', name: '跟进事项.csv', isDirectory: false, size: 12140, mimeType: 'text/csv', modifiedAt: '2026-07-18T18:05:00+08:00' },
    { path: '产品演示.pptx', name: '产品演示.pptx', isDirectory: false, size: 1248200, mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', modifiedAt: '2026-07-18T10:12:00+08:00' }
  ]
  devRuntime.readWorkspaceFile = async () => ({
    blob: new Blob(['季度工作区摘要\n\n华东区销售额保持增长，重点跟进三项高价值商机。'], { type: 'text/plain' }),
    mimeType: 'text/plain'
  })
  devRuntime.downloadWorkspaceFile = async () => undefined
  devRuntime.deleteWorkspaceEntry = async () => undefined
}
if (scenario === 'streaming') {
  window.setTimeout(() => void devRuntime.send('开始生成销售摘要'), 0)
}
