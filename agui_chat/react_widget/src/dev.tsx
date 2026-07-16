import type { AguiChatProps, ChatMessage } from './types'
import { AguiChat, ChatRuntime } from './index'
import { devHandshake, devHostState } from './dev-v2'

type Scenario = 'empty' | 'complete' | 'streaming' | 'markdown' | 'tool' | 'relation' | 'attachments' | 'error' | 'panels'

const requested = new URLSearchParams(window.location.search).get('scenario')
const scenario: Scenario = ['empty', 'complete', 'streaming', 'markdown', 'tool', 'relation', 'attachments', 'error', 'panels'].includes(requested || '')
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
  panels: [user, assistant]
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
if (!root) throw new Error('Dev root element was not found.')

const props: AguiChatProps = {
  runtimeUrl: scenario === 'error' ? undefined : '/dev/agui',
  handshake: devHandshake,
  hostState: devHostState,
  agentState: {},
  tools: [],
  menuOptions: [],
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
if (scenario === 'streaming') {
  window.setTimeout(() => void devRuntime.send('开始生成销售摘要'), 0)
}
