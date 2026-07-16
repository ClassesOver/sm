import { afterEach, describe, expect, it, vi } from 'vitest'
import { AguiChat } from '../index'
import { ChatRuntime } from './ChatRuntime'
import type { AguiChatProps } from '../types'
import { v2Props } from '../test/fixtures'

function createRuntime(props: Partial<AguiChatProps> = {}) {
  return new ChatRuntime(v2Props(props))
}

function sseResponse(events: unknown[]) {
  const encoder = new TextEncoder()
  const blocks = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(blocks))
        controller.close()
      }
    }),
    {
      status: 200,
      headers: {
        'content-type': 'text/event-stream'
      }
    }
  )
}

describe('AguiChat public API', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('mounts, updates, and unmounts a runtime-backed widget', () => {
    const host = document.createElement('div')
    document.body.append(host)

    const handle = AguiChat.mount(host, v2Props({
      __debug: true,
      threadId: 'thread-1'
    }))

    expect(AguiChat.version).toBe('12.0.7.0.0')
    expect(handle.__runtime).toBeInstanceOf(ChatRuntime)
    expect((handle.__runtime as ChatRuntime).getSnapshot().threadId).toBe('thread-1')

    handle.update({ threadId: 'thread-2' })
    expect((handle.__runtime as ChatRuntime).getSnapshot().threadId).toBe('thread-2')

    handle.unmount()
    expect(host.innerHTML).toBe('')
  })
})

describe('ChatRuntime protocol handling', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('streams text, executes host tools, and sends a follow-up with hidden tool messages', async () => {
    const requests: Array<{ url: string; body: any }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init: RequestInit) => {
        const body = JSON.parse(String(init.body))
        requests.push({ url, body })
        if (requests.length === 1) {
          return Promise.resolve(
            sseResponse([
              { type: 'TEXT_MESSAGE_START', messageId: 'assistant-1' },
              { type: 'TEXT_MESSAGE_CONTENT', messageId: 'assistant-1', delta: 'Updating ' },
              {
                type: 'TOOL_CALL_START',
                toolCallId: 'tool-1',
                toolCallName: 'odoo.patch_current_form'
              },
              {
                type: 'TOOL_CALL_ARGS',
                toolCallId: 'tool-1',
                delta: JSON.stringify({ field: 'name', value: 'Acme' })
              },
              { type: 'TOOL_CALL_END', toolCallId: 'tool-1' },
              { type: 'RUN_FINISHED' }
            ])
          )
        }
        return Promise.resolve(
          sseResponse([
            { type: 'TEXT_MESSAGE_START', messageId: 'assistant-2' },
            { type: 'TEXT_MESSAGE_CONTENT', messageId: 'assistant-2', delta: 'done' },
            { type: 'RUN_FINISHED' }
          ])
        )
      })
    )

    const runtime = createRuntime({
      runtimeUrl: '/runtime/run',
      attachments: false,
      threadId: 'thread-1',
      hostBridge: {
        executeTool(call) {
          return {
            ok: true,
            operation: call.tool,
            applied: ['name'],
            rejected: []
          }
        }
      }
    })

    await runtime.send('Change customer name')

    expect(requests).toHaveLength(2)
    expect(requests[0].url).toBe('/runtime/run')
    expect(requests[0].body.threadId).toBe('thread-1')
    expect(requests[0].body.state).toEqual({
      protocol: 'agui.odoo.v2',
      host: expect.objectContaining({ snapshotId: 'snapshot-test-1' }),
      agent: {}
    })
    expect(requests[0].body.tools.map((tool: any) => tool.name)).toEqual(['odoo.patch_current_form'])
    expect(requests[0].body.messages[0].content).toBe('Change customer name')
    expect(requests[1].body.messages.some((message: any) => message.role === 'tool')).toBe(true)
    expect(requests[1].body.messages.find((message: any) => message.role === 'assistant').toolCalls).toEqual([
      {
        id: 'tool-1',
        type: 'function',
        function: {
          name: 'odoo.patch_current_form',
          arguments: JSON.stringify({ field: 'name', value: 'Acme' })
        }
      }
    ])
    expect(runtime.getSnapshot().messages.some((message) => message.role === 'tool' && message.hidden)).toBe(true)
    const assistantMessages = runtime.getSnapshot().messages.filter((message) => message.role === 'assistant')
    expect(assistantMessages).toHaveLength(2)
    expect(assistantMessages[0].content).toBe('')
    expect(assistantMessages[0].tool_calls?.[0].status).toBe('ok')
    expect(assistantMessages[1].content).toBe('done')
  })

  it('keeps an asynchronous host result on the original tool card', () => {
    const runtime = createRuntime()
    const internal = runtime as any
    internal.messages = [
      {
        id: 'assistant-original', role: 'assistant', content: '', tool_calls: [], created_at: 1
      },
      {
        id: 'assistant-current', role: 'assistant', content: '', tool_calls: [], created_at: 2
      }
    ]
    internal.pendingAssistantId = 'assistant-current'
    const tool = internal.mergeTool({
      id: 'call-open-1',
      name: 'odoo.open_record',
      parentMessageId: 'assistant-original',
      args: { recordToken: 'record-1', mode: 'readonly' },
      status: 'running'
    })

    internal.recordHostBridgeResult(tool, {
      ok: true,
      code: 'ok',
      operation: 'odoo.open_record',
      navigated: true,
      opened: true
    })

    const messages = runtime.getSnapshot().messages
    const original = messages.find((message) => message.id === 'assistant-original')
    const current = messages.find((message) => message.id === 'assistant-current')
    expect(original?.tool_calls?.[0].result).toEqual(expect.objectContaining({
      ok: true, navigated: true, opened: true
    }))
    expect(current?.tool_calls).toEqual([])
  })

  it.each([
    { approved: true, decision: { ok: true, code: 'ok', saved: true }, status: 'ok' },
    {
      approved: false,
      decision: { ok: false, code: 'authorization_rejected' },
      status: 'error'
    }
  ])('pauses confirmations and follows up once after decision ($status)', async ({
    approved, decision, status
  }) => {
    const requests: any[] = []
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      requests.push(JSON.parse(String(init.body)))
      return Promise.resolve(sseResponse(requests.length === 1 ? [
        {
          type: 'TOOL_CALL_START',
          toolCallId: 'confirm-tool-1',
          toolCallName: 'odoo.patch_current_form'
        },
        {
          type: 'TOOL_CALL_ARGS',
          toolCallId: 'confirm-tool-1',
          delta: JSON.stringify({ patch: { name: '待确认名称' } })
        },
        { type: 'TOOL_CALL_END', toolCallId: 'confirm-tool-1' },
        { type: 'RUN_FINISHED' }
      ] : [
        { type: 'TEXT_MESSAGE_CONTENT', delta: '确认流程已完成' },
        { type: 'RUN_FINISHED' }
      ]))
    })
    vi.stubGlobal('fetch', fetchMock)
    const confirmTool = vi.fn(() => decision)
    const runtime = createRuntime({
      runtimeUrl: '/runtime/run',
      attachments: false,
      hostBridge: {
        executeTool: () => ({
          ok: false,
          code: 'confirmation_required',
          needs_confirmation: true,
          authorization_id: 'authorization-1',
          operation: 'odoo.patch_current_form'
        }),
        confirmTool
      }
    })

    await runtime.send('修改当前表单')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(runtime.getSnapshot().messages.filter((message) => message.role === 'tool')).toHaveLength(0)
    const pending = runtime.getSnapshot().messages
      .flatMap((message) => message.tool_calls || [])[0]
    expect(pending.status).toBe('needs_confirmation')

    await runtime.confirmTool(pending, approved)

    expect(confirmTool).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(requests[1].messages.filter((message: any) => message.role === 'tool')).toHaveLength(1)
    const completed = runtime.getSnapshot().messages
      .flatMap((message) => message.tool_calls || [])[0]
    expect(completed.status).toBe(status)
    expect(runtime.getSnapshot().messages.filter((message) => message.role === 'tool')).toHaveLength(1)

    await runtime.confirmTool(pending, approved)
    expect(confirmTool).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('persists confirmation results, merges one revision conflict, then resumes', async () => {
    const order: string[] = []
    const savedPayloads: any[] = []
    const saveSession = vi.fn(async (_sessionId: string | number | false, values: Record<string, unknown>) => {
      order.push('save')
      savedPayloads.push(values)
      if (savedPayloads.length === 1) {
        return { ok: false, error: 'session_revision_conflict', sessionRevision: 2 } as any
      }
      return {
        ok: true,
        session: {
          id: 9, protocol: 'agui.odoo.v2' as const, thread_id: 'thread-confirm-save',
          sessionRevision: savedPayloads.length + 1, messages: values.messages as any[]
        }
      }
    })
    const loadSession = vi.fn(async () => ({
      session: {
        id: 9, protocol: 'agui.odoo.v2' as const, thread_id: 'thread-confirm-save',
        sessionRevision: 2,
        messages: [{ id: 'remote-message', role: 'user' as const, content: 'remote' }]
      }
    }))
    vi.stubGlobal('fetch', vi.fn(() => {
      order.push('fetch')
      return Promise.resolve(sseResponse([
        { type: 'TEXT_MESSAGE_CONTENT', delta: 'final' },
        { type: 'RUN_FINISHED' }
      ]))
    }))
    const runtime = createRuntime({
      runtimeUrl: '/runtime/run', attachments: false,
      session: {
        id: 9, protocol: 'agui.odoo.v2', thread_id: 'thread-confirm-save', sessionRevision: 1,
        messages: [{
          id: 'assistant-confirm', role: 'assistant', content: '', tool_calls: [{
            id: 'confirm-save-tool', name: 'odoo.patch_current_form',
            args: { patch: { name: 'After' } }, status: 'needs_confirmation',
            result: { needs_confirmation: true, authorization_id: 'authorization-save' }
          }]
        }]
      },
      hostBridge: {
        confirmTool: () => ({ ok: false, code: 'authorization_rejected' }),
        saveSession,
        loadSession
      }
    })
    const tool = runtime.getSnapshot().messages[0].tool_calls![0]

    await runtime.confirmTool(tool, false)

    expect(loadSession).toHaveBeenCalledTimes(1)
    expect(order.slice(0, 3)).toEqual(['save', 'save', 'fetch'])
    const mergedIds = (savedPayloads[1].messages as any[]).map((message) => message.id)
    expect(mergedIds).toEqual(expect.arrayContaining([
      'remote-message', 'assistant-confirm', 'tool-confirm-save-tool'
    ]))
  })

  it('recreates a deleted session once and preserves the current conversation', async () => {
    const savedSessionIds: Array<string | number | false> = []
    const savedPayloads: Array<Record<string, unknown>> = []
    const createSession = vi.fn(async () => ({
      session: {
        id: 42,
        protocol: 'agui.odoo.v2' as const,
        thread_id: 'thread-replacement',
        sessionRevision: 0,
        messages: [],
        agentState: {}
      }
    }))
    const saveSession = vi.fn(async (sessionId: string | number | false, values: Record<string, unknown>) => {
      savedSessionIds.push(sessionId)
      savedPayloads.push(values)
      if (sessionId === 9) return { ok: false, error: 'session_not_found' } as any
      return {
        ok: true,
        session: {
          id: 42,
          protocol: 'agui.odoo.v2' as const,
          thread_id: 'thread-replacement',
          sessionRevision: 1,
          messages: values.messages as any[],
          agentState: values.agentState as Record<string, unknown>
        }
      }
    })
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(sseResponse([
      { type: 'TEXT_MESSAGE_CONTENT', delta: '已完成' },
      { type: 'RUN_FINISHED' }
    ]))))
    const runtime = createRuntime({
      runtimeUrl: '/runtime/run',
      agentState: { retained: true },
      session: {
        id: 9,
        protocol: 'agui.odoo.v2',
        thread_id: 'thread-deleted',
        sessionRevision: 3,
        name: '保留中的对话',
        messages: [],
        agentState: { retained: true },
        uiPreferences: { compact: true }
      },
      hostBridge: {createSession, saveSession}
    })

    await runtime.send('继续处理')

    expect(createSession).toHaveBeenCalledTimes(1)
    expect(savedSessionIds).toEqual([9, 42])
    expect(runtime.getSnapshot().session?.id).toBe(42)
    expect(runtime.getSnapshot().threadId).toBe('thread-replacement')
    expect(runtime.getSnapshot().agentState).toEqual({retained: true})
    expect(savedPayloads[1].messages).toEqual(expect.arrayContaining([
      expect.objectContaining({role: 'user', content: '继续处理'}),
      expect.objectContaining({role: 'assistant', content: '已完成'})
    ]))
    expect(savedPayloads[1].uiPreferences).toEqual({compact: true})
  })

  it('uses an undo authorization once and stores the receipt state', async () => {
    const undoTool = vi.fn(async () => ({ ok: true, undone: true, code: 'ok' }))
    const runtime = createRuntime({
      session: {
        id: 10, protocol: 'agui.odoo.v2', thread_id: 'thread-undo', sessionRevision: 1,
        messages: [{
          id: 'assistant-undo', role: 'assistant', content: '', tool_calls: [{
            id: 'patch-with-undo', name: 'odoo.patch_current_form', status: 'ok',
            result: {
              ok: true,
              receipt: { undo: { available: true, authorization_id: 'undo-authorization', status: 'available' } }
            }
          }]
        }]
      },
      hostBridge: { undoTool }
    })
    const tool = runtime.getSnapshot().messages[0].tool_calls![0]

    await runtime.undoTool(tool)
    await runtime.undoTool(tool)

    expect(undoTool).toHaveBeenCalledTimes(1)
    const result = runtime.getSnapshot().messages[0].tool_calls![0].result as any
    expect(result.receipt.undo.status).toBe('undone')
    expect(result.undoResult).toMatchObject({ ok: true, undone: true })
  })

  it('proxies and serializes attachment references without base64', async () => {
    let request: { url: string; body: any } | undefined
    vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => {
      request = { url, body: JSON.parse(String(init.body)) }
      return Promise.resolve(sseResponse([
        { type: 'TEXT_MESSAGE_CONTENT', delta: 'ok' },
        { type: 'RUN_FINISHED' }
      ]))
    }))
    const runtime = createRuntime({ runtimeUrl: '/external/run', threadId: 'thread-attachments' })
    await runtime.send('Review this', [{
      id: '42', name: 'report.pdf', mimeType: 'application/pdf',
      size: 128, modality: 'document'
    }])
    expect(request?.url).toBe('/external/run')
    expect(request?.body.messages[0].attachments).toEqual([{
      id: '42', name: 'report.pdf', mimeType: 'application/pdf',
      size: 128, modality: 'document'
    }])
    expect(JSON.stringify(request?.body)).not.toContain('base64')
  })

  it('stops without an error and preserves streamed content', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => {
      const encoder = new TextEncoder()
      return Promise.resolve(new Response(new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(
            'data: {"type":"TEXT_MESSAGE_CONTENT","delta":"partial"}\n\n'
          ))
          init.signal?.addEventListener('abort', () => {
            controller.error(new DOMException('Aborted', 'AbortError'))
          })
        }
      }), { status: 200, headers: { 'content-type': 'text/event-stream' } }))
    }))
    const runtime = createRuntime({ runtimeUrl: '/runtime/run', attachments: false })
    const pending = runtime.send('start')
    await vi.waitFor(() => expect(runtime.getSnapshot().messages[1]?.content).toBe('partial'))
    runtime.stop()
    await pending
    expect(runtime.getSnapshot().error).toBe('')
    expect(runtime.getSnapshot().transportState).toBe('cancelled')
    expect(runtime.getSnapshot().messages[1].content).toBe('partial')
  })

  it('regenerates from the preceding user message and retains its attachments', async () => {
    let body: any
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => {
      body = JSON.parse(String(init.body))
      return Promise.resolve(sseResponse([
        { type: 'TEXT_MESSAGE_CONTENT', delta: 'new answer' },
        { type: 'RUN_FINISHED' }
      ]))
    }))
    const attachment = {
      id: '7', name: 'data.csv', mimeType: 'text/csv',
      size: 20, modality: 'document' as const
    }
    const runtime = createRuntime({
      runtimeUrl: '/runtime/run',
      initialMessages: [
        { id: 'user-1', role: 'user', content: 'analyze', attachments: [attachment] },
        { id: 'assistant-1', role: 'assistant', content: 'old answer' },
        { id: 'user-2', role: 'user', content: 'later question' },
        { id: 'assistant-2', role: 'assistant', content: 'later answer' }
      ]
    })
    await runtime.regenerate('assistant-1')
    expect(body.messages).toHaveLength(1)
    expect(body.messages[0].id).toBe('user-1')
    expect(body.messages[0].attachments).toEqual([attachment])
    expect(runtime.getSnapshot().messages.map((message) => message.content)).toEqual([
      'analyze', 'new answer'
    ])
  })

  it('records run errors and interrupt confirmations', () => {
    const runtime = createRuntime({ threadId: 'thread-1' })

    runtime.applyEvent({ type: 'RUN_ERROR', message: 'failed' })
    runtime.applyEvent({
      type: 'RUN_FINISHED',
      outcome: {
        type: 'interrupt',
        interrupts: [{ id: 'interrupt-1', reason: 'needs approval' }]
      }
    })

    const message = runtime.getSnapshot().messages[0]
    expect(message.streaming_error).toBe('failed')
    expect(message.tool_calls?.[0].status).toBe('needs_confirmation')
  })

  it('rejects non-SSE responses, missing bodies, and streams without RUN_FINISHED', async () => {
    const runtime = createRuntime({ runtimeUrl: '/runtime/run', attachments: false })

    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{}', {
      status: 200, headers: { 'content-type': 'application/json' }
    }))))
    await runtime.send('json')
    expect(runtime.getSnapshot().error).toBe('AG-UI runtime must return text/event-stream.')

    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, {
      status: 200, headers: { 'content-type': 'text/event-stream' }
    }))))
    await runtime.send('no body')
    expect(runtime.getSnapshot().error).toBe('AG-UI SSE response has no body.')

    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(sseResponse([
      { type: 'TEXT_MESSAGE_CONTENT', delta: 'partial' }
    ]))))
    await runtime.send('early end')
    expect(runtime.getSnapshot().error).toBe('AG-UI stream ended before RUN_FINISHED.')
  })

  it('parses fragmented CRLF events, reports malformed events, and isolates run and thread ids', async () => {
    const onError = vi.fn()
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => {
      const input = JSON.parse(String(init.body))
      const encoder = new TextEncoder()
      const payload = [
        'data: {bad json}\r\n\r\n',
        'data: ' + JSON.stringify({ type: 'TEXT_MESSAGE_CONTENT', runId: 'other', delta: 'wrong-run' }) + '\r\n\r\n',
        'data: ' + JSON.stringify({ type: 'TEXT_MESSAGE_CONTENT', threadId: 'other', delta: 'wrong-thread' }) + '\r\n\r\n',
        'data: ' + JSON.stringify({ type: 'TEXT_MESSAGE_CONTENT', runId: input.runId, threadId: input.threadId, delta: 'accepted' }) + '\r\n\r\n',
        'data: ' + JSON.stringify({ type: 'RUN_FINISHED', runId: input.runId, threadId: input.threadId }) + '\r\n\r\n'
      ].join('')
      return Promise.resolve(new Response(new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(payload.slice(0, 17)))
          controller.enqueue(encoder.encode(payload.slice(17, 73)))
          controller.enqueue(encoder.encode(payload.slice(73)))
          controller.close()
        }
      }), { status: 200, headers: { 'content-type': 'text/event-stream; charset=utf-8' } }))
    }))
    const runtime = createRuntime({
      runtimeUrl: '/runtime/run', attachments: false, threadId: 'thread-isolated', onError
    })

    await runtime.send('stream')

    expect(runtime.getSnapshot().messages[1].content).toBe('accepted')
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'Ignored malformed SSE event.' }))
  })

  it('does not execute AgentOS server tools that were not declared as client tools', async () => {
    const executeTool = vi.fn()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(sseResponse([
      { type: 'TOOL_CALL_START', toolCallId: 'server-tool-1', toolCallName: 'server.lookup' },
      { type: 'TOOL_CALL_ARGS', toolCallId: 'server-tool-1', delta: '{}' },
      { type: 'TOOL_CALL_END', toolCallId: 'server-tool-1' },
      { type: 'TOOL_CALL_RESULT', toolCallId: 'server-tool-1', content: '{"ok":true}' },
      { type: 'RUN_FINISHED' }
    ]))))
    const runtime = createRuntime({
      runtimeUrl: '/runtime/run', tools: [], hostBridge: { executeTool }
    })

    await runtime.send('server tool')

    expect(executeTool).not.toHaveBeenCalled()
    expect(runtime.getSnapshot().messages[1].tool_calls?.[0].status).toBe('ok')
  })

  it('does not execute named HostBridge fallbacks without executeTool', async () => {
    const patchCurrentForm = vi.fn()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(sseResponse([
      { type: 'TOOL_CALL_START', toolCallId: 'tool-client-only', toolCallName: 'odoo.patch_current_form' },
      { type: 'TOOL_CALL_ARGS', toolCallId: 'tool-client-only', delta: '{}' },
      { type: 'TOOL_CALL_END', toolCallId: 'tool-client-only' },
      { type: 'RUN_FINISHED' }
    ]))))
    const runtime = createRuntime({
      runtimeUrl: '/runtime/run', attachments: false,
      hostBridge: { patchCurrentForm } as any
    })

    await runtime.send('tool')

    expect(patchCurrentForm).not.toHaveBeenCalled()
  })

  it('sends an explicit relation selection message and rejects stale candidates', async () => {
    let body: any
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      body = JSON.parse(String(init.body))
      return Promise.resolve(sseResponse([{ type: 'RUN_FINISHED' }]))
    })
    vi.stubGlobal('fetch', fetchMock)
    const runtime = createRuntime({ runtimeUrl: '/runtime/run', attachments: false })
    const tool = {
      id: 'relation-1', name: 'odoo.search_relation', status: 'ok' as const,
      result: {
        ok: true, operation: 'odoo.search_relation', field: 'partner_id', fieldLabel: '客户',
        fieldType: 'many2one', relation: 'res.partner', query: '上海', relationOperation: 'set',
        resolution: 'ambiguous', snapshotId: 'snapshot-test-1', hostRevision: 1,
        candidates: [{ id: 42, displayName: '上海某公司', selected: false }]
      }
    }
    const content = await runtime.selectRelationCandidates(tool, [
      { id: 42, displayName: '上海某公司', selected: false }
    ])
    expect(content).toContain('"field":"partner_id"')
    expect(content).toContain('"id":42')
    expect(body.messages[0].content).toBe(content)

    const onError = vi.fn()
    const staleRuntime = createRuntime({ runtimeUrl: '/runtime/run', attachments: false, onError })
    const stale = await staleRuntime.selectRelationCandidates({
      ...tool, result: { ...tool.result, hostRevision: 0 }
    }, [{ id: 42, displayName: '上海某公司', selected: false }])
    expect(stale).toBeNull()
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('过期') }))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('stores a valid menu mention and rejects it after access is lost', async () => {
    let body: any
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      body = JSON.parse(String(init.body))
      return Promise.resolve(sseResponse([{ type: 'RUN_FINISHED' }]))
    })
    vi.stubGlobal('fetch', fetchMock)
    const option = {
      menuId: 8, actionId: 42, name: '客户', path: ['销售', '客户'], fullPath: '销售 / 客户'
    }
    const runtime = createRuntime({ runtimeUrl: '/runtime/run', menuOptions: [option] })
    await runtime.send('打开', [], { ...option, valid: true })

    expect(runtime.getSnapshot().messages[0].menuMention).toEqual({ ...option, valid: true })
    expect(body.messages[0].content).toBe('打开')
    expect(body.context).toContainEqual(expect.objectContaining({ description: 'Selected Odoo menu' }))

    runtime.update({ menuOptions: [] })
    expect(runtime.getSnapshot().messages[0].menuMention?.valid).toBe(false)
    await runtime.regenerate(runtime.getSnapshot().messages[1].id)
    expect(runtime.getSnapshot().error).toContain('菜单已失效')
    expect(fetchMock).toHaveBeenCalledTimes(1)

    runtime.removeMenuMention(runtime.getSnapshot().messages[0].id)
    expect(runtime.getSnapshot().messages[0].menuMention).toBeUndefined()
  })

  it('sends record choices as structured context and rejects stale candidates', async () => {
    let body: any
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      body = JSON.parse(String(init.body))
      return Promise.resolve(sseResponse([{ type: 'RUN_FINISHED' }]))
    })
    vi.stubGlobal('fetch', fetchMock)
    const hostState = {
      ...v2Props().hostState,
      capabilities: {
        ...v2Props().hostState.capabilities,
        records: [{ token: 'record-token', displayName: '上海某公司' }]
      }
    }
    const runtime = createRuntime({ runtimeUrl: '/runtime/run', hostState })
    const tool = {
      id: 'filter-1', name: 'odoo.apply_filter', status: 'ok' as const,
      result: {
        ok: true, operation: 'odoo.apply_filter', label: '上海客户', domain: [], count: 1,
        candidates: hostState.capabilities.records,
        snapshotId: hostState.snapshotId, hostRevision: hostState.hostRevision
      }
    }
    const content = await runtime.selectRecordCandidate(tool, hostState.capabilities.records[0])
    expect(content).toBe('选择记录：上海某公司')
    expect(body.messages[0].content).toBe(content)
    expect(body.messages[0]).not.toHaveProperty('recordSelection')
    expect(body.context).toContainEqual({
      description: 'Selected Odoo record candidate',
      value: JSON.stringify({
        token: 'record-token', displayName: '上海某公司',
        snapshotId: hostState.snapshotId, hostRevision: hostState.hostRevision
      })
    })

    const stale = await runtime.selectRecordCandidate({
      ...tool, result: { ...tool.result, hostRevision: 0 }
    }, hostState.capabilities.records[0])
    expect(stale).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('stops after four automatic client-tool follow-ups by default', async () => {
    let requestCount = 0
    vi.stubGlobal('fetch', vi.fn(() => {
      requestCount += 1
      return Promise.resolve(sseResponse([
        {
          type: 'TOOL_CALL_START', toolCallId: `tool-${requestCount}`,
          toolCallName: 'odoo.patch_current_form'
        },
        { type: 'TOOL_CALL_ARGS', toolCallId: `tool-${requestCount}`, delta: '{}' },
        { type: 'TOOL_CALL_END', toolCallId: `tool-${requestCount}` },
        { type: 'RUN_FINISHED' }
      ]))
    }))
    const runtime = createRuntime({
      runtimeUrl: '/runtime/run',
      hostBridge: { executeTool: () => ({ ok: true, operation: 'odoo.patch_current_form' }) }
    })

    await runtime.send('连续操作')

    expect(requestCount).toBe(5)
    expect(runtime.getSnapshot().messages.some((message) =>
      message.role === 'assistant' && String(message.content).includes('4 次页面操作上限')
    )).toBe(true)
  })

  it('applies agent state events and rejects host state mutations', () => {
    const states: unknown[] = []
    const onError = vi.fn()
    const runtime = createRuntime({
      agentState: { revision: 1 },
      onError,
      onAgentStateChange(state) {
        states.push(state)
      }
    })

    runtime.applyEvent({ type: 'STATE_DELTA', delta: { agent: { model: 'res.partner' }, host: { interactive: false } } })
    runtime.applyEvent({ type: 'STATE_PATCH', patch: [{ op: 'replace', path: '/agent/revision', value: 2 }] })

    expect(runtime.getSnapshot().agentState).toEqual({ revision: 2, model: 'res.partner' })
    expect(states).toHaveLength(2)
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('hostState') }))
    expect(runtime.getSnapshot().hostState.interactive).toBe(true)
  })

  it('reads standard AG-UI snapshots and JSON Patch state deltas', () => {
    const runtime = createRuntime({ agentState: { revision: 1 } })
    runtime.applyEvent({
      type: 'STATE_SNAPSHOT',
      snapshot: {
        protocol: 'agui.odoo.v2',
        host: runtime.getSnapshot().hostState,
        agent: {
          revision: 2,
          business: {
            host: 'warehouse.example',
            protocol: 'custom-business-protocol'
          }
        }
      }
    })
    runtime.applyEvent({
      type: 'STATE_DELTA',
      delta: [{ op: 'replace', path: '/agent/revision', value: 3 }]
    })

    expect(runtime.getSnapshot().agentState).toEqual({
      revision: 3,
      business: {
        host: 'warehouse.example',
        protocol: 'custom-business-protocol'
      }
    })
  })

  it('unwraps legacy recursive snapshot state without rewriting business fields', () => {
    const expected = {
      revision: 1,
      deeply: { nested: { host: 'keep', protocol: 'keep' } }
    }
    const envelope = (agent: Record<string, unknown>) => ({
      protocol: 'agui.odoo.v2',
      host: { snapshotId: 'old' },
      agent
    })
    const legacyState = {
      snapshot: envelope({
        type: 'STATE_SNAPSHOT',
        snapshot: envelope(expected)
      })
    }

    const runtime = createRuntime({ agentState: legacyState })

    expect(runtime.getSnapshot().agentState).toEqual(expected)
  })

  it('writes cleaned legacy agent state back through the session API', async () => {
    vi.useFakeTimers()
    try {
      const expected = { revision: 4 }
      const saveSession = vi.fn(async () => undefined)
      const runtime = createRuntime({
        session: {
          id: 9,
          name: 'Legacy',
          thread_id: 'legacy-thread',
          sessionRevision: 7,
          agentState: {
            snapshot: {
              protocol: 'agui.odoo.v2',
              host: { snapshotId: 'old' },
              agent: expected
            }
          }
        },
        hostBridge: { saveSession }
      })

      await vi.advanceTimersByTimeAsync(600)

      expect(saveSession).toHaveBeenCalledWith(9, expect.objectContaining({
        agentState: expected,
        expectedSessionRevision: 7
      }))
      runtime.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})
