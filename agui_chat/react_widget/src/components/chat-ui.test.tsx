import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mergeIcons, mergeLabels, observeInteraction } from '../customization'
import type { AssistantMessageProps, ChatMessage, RuntimeSnapshot, UserMessageProps } from '../types'
import { ChatRuntime } from '../runtime/ChatRuntime'
import { testHostState, v2Props } from '../test/fixtures'
import { AguiChatApp } from './AguiChatApp'
import { ChatInput, menuQueryAtCursor } from './ChatInput'
import { FilePreviewPanel } from './FilePreviewPanel'
import { Messages } from './Messages'

vi.mock('@file-viewer/react-full', () => ({
  FileViewer: ({ url, filename, type, options }: {
    url: string
    filename: string
    type: string
    options: { theme: string; styleIsolation: string }
  }) => <div
    data-testid="file-viewer"
    data-url={url}
    data-filename={filename}
    data-type={type}
    data-options={`${options.theme}:${options.styleIsolation}`}
  />
}))

afterEach(cleanup)

const labels = mergeLabels()
const icons = mergeIcons()
const messages: ChatMessage[] = [
  { id: 'user-1', role: 'user', content: 'Question' },
  { id: 'assistant-1', role: 'assistant', content: 'First answer' },
  { id: 'assistant-2', role: 'assistant', content: 'Current answer' }
]

function renderMessages(overrides: Partial<React.ComponentProps<typeof Messages>> = {}) {
  return render(<Messages
    messages={messages}
    running={false}
    labels={labels}
    icons={icons}
    onConfirmTool={vi.fn()}
    onRegenerate={vi.fn()}
    onSuggestion={vi.fn()}
    onCopy={vi.fn()}
    onFeedback={vi.fn()}
    onPreviewAttachment={vi.fn()}
    hostState={testHostState}
    onSelectRelation={vi.fn()}
    onSelectRecord={vi.fn()}
    {...overrides}
  />)
}

describe('chat customization', () => {
  it('merges partial labels and icons with defaults', () => {
    const custom = <span data-testid="custom-send" />
    expect(mergeLabels({ inputPlaceholder: '输入内容' })).toMatchObject({
      inputPlaceholder: '输入内容',
      sendMessage: '发送消息'
    })
    expect(mergeIcons({ send: custom }).send).toBe(custom)
    expect(mergeIcons({ send: custom }).assistant).toBeTruthy()
  })

  it('passes stable props to message slots', () => {
    const Assistant = vi.fn((_props: AssistantMessageProps) => <div>assistant slot</div>)
    const User = vi.fn((_props: UserMessageProps) => <div>user slot</div>)
    renderMessages({ components: { AssistantMessage: Assistant, UserMessage: User } })
    expect(screen.getAllByText('assistant slot')).toHaveLength(2)
    expect(screen.getByText('user slot')).toBeTruthy()
    expect(Assistant.mock.calls[0][0]).toMatchObject({ running: false, labels, icons })
    expect(User.mock.calls[0][0]).toMatchObject({ message: messages[0], icons })
  })

  it('hides feedback controls while preserving the callback contract', () => {
    const onFeedback = vi.fn()
    renderMessages({ messages: [messages[1]], onFeedback })
    expect(screen.queryByRole('button', { name: labels.positiveFeedback })).toBeNull()
    expect(screen.queryByRole('button', { name: labels.negativeFeedback })).toBeNull()
    expect(onFeedback).not.toHaveBeenCalled()
  })

  it('uses Chinese labels for Odoo form tools', () => {
    renderMessages({
      messages: [{
        id: 'assistant-tool',
        role: 'assistant',
        content: '',
        tool_calls: [{
          id: 'patch-1',
          name: 'odoo.patch_current_form',
          status: 'needs_confirmation',
          needs_confirmation: true,
          result: { operation: 'odoo.patch_current_form' }
        }]
      }]
    })
    expect(screen.getByText('修改当前表单')).toBeTruthy()
    expect(screen.getByText('需要确认：修改当前表单')).toBeTruthy()
  })

  it('renders filter candidates and disables an expired snapshot', () => {
    const onSelectRecord = vi.fn()
    const filterTool = {
      id: 'filter-1', name: 'odoo.apply_filter', status: 'ok' as const,
      result: {
        ok: true, operation: 'odoo.apply_filter', label: '上海客户', domain: [['city', '=', '上海']],
        count: 2, snapshotId: testHostState.snapshotId, hostRevision: testHostState.hostRevision,
        candidates: [{ token: 'record-1', displayName: '上海某公司' }]
      }
    }
    const { rerender } = renderMessages({
      messages: [{ id: 'assistant-filter', role: 'assistant', content: '请选择', tool_calls: [filterTool] }],
      onSelectRecord
    })
    fireEvent.click(screen.getByRole('button', { name: /上海某公司/ }))
    expect(onSelectRecord).toHaveBeenCalledWith(filterTool, { token: 'record-1', displayName: '上海某公司' })

    rerender(<Messages messages={[{ id: 'assistant-filter', role: 'assistant', content: '请选择', tool_calls: [filterTool] }]} running={false} labels={labels} icons={icons} hostState={{ ...testHostState, hostRevision: 2 }} onSelectRelation={vi.fn()} onSelectRecord={onSelectRecord} onConfirmTool={vi.fn()} onRegenerate={vi.fn()} onSuggestion={vi.fn()} onCopy={vi.fn()} onFeedback={vi.fn()} onPreviewAttachment={vi.fn()} />)
    expect(screen.getByText('候选快照已过期，请重新筛选。')).toBeTruthy()
    expect((screen.getByRole('button', { name: /上海某公司/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('recognizes menu mention boundaries', () => {
    expect(menuQueryAtCursor('@客户', 3)).toEqual({ start: 0, end: 3, query: '客户' })
    expect(menuQueryAtCursor('打开 @客户', 6)).toEqual({ start: 3, end: 6, query: '客户' })
    expect(menuQueryAtCursor('打开@客户', 5)).toBeNull()
  })

  it('searches, selects, replaces, removes, and sends one menu mention', () => {
    const onSend = vi.fn()
    render(<ChatInput
      running={false}
      attachments={false}
      menuOptions={[
        { menuId: 1, actionId: 11, name: '客户', path: ['销售', '客户'], fullPath: '销售 / 客户' },
        { menuId: 2, actionId: 12, name: '线索', path: ['销售', '线索'], fullPath: '销售 / 线索' }
      ]}
      labels={labels}
      icons={icons}
      onSend={onSend}
      onStop={vi.fn()}
      onUpload={vi.fn()}
      onRemove={vi.fn()}
    />)
    const input = screen.getByPlaceholderText(labels.inputPlaceholder)
    fireEvent.change(input, { target: { value: '@客户', selectionStart: 3 } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByText('销售 / 客户')).toBeTruthy()
    expect((input as HTMLTextAreaElement).value).toBe('')

    fireEvent.change(input, { target: { value: '@线索', selectionStart: 3 } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.queryByText('销售 / 客户')).toBeNull()
    expect(screen.getByText('销售 / 线索')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: labels.sendMessage }))
    expect(onSend).toHaveBeenCalledWith('', [], expect.objectContaining({ menuId: 2, actionId: 12, valid: true }))

    fireEvent.change(input, { target: { value: '@客户', selectionStart: 3 } })
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.click(screen.getByRole('button', { name: '移除菜单' }))
    expect(screen.queryByText('销售 / 客户')).toBeNull()
  })

  it('shows and removes an invalid menu mention from a sent message', () => {
    const onRemoveMenuMention = vi.fn()
    renderMessages({
      messages: [{
        id: 'user-menu', role: 'user', content: '打开',
        menuMention: {
          menuId: 1, actionId: 11, name: '客户', path: ['销售', '客户'],
          fullPath: '销售 / 客户', valid: false
        }
      }],
      onRemoveMenuMention
    })
    expect(screen.getByText('（已失效）')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '移除菜单' }))
    expect(onRemoveMenuMention).toHaveBeenCalledWith('user-menu')
  })

  it('renders relation candidates and reports an explicit selection', () => {
    const onSelectRelation = vi.fn()
    const relationTool = {
      id: 'relation-1', name: 'odoo.search_relation', status: 'ok' as const,
      result: {
        ok: true, operation: 'odoo.search_relation', field: 'partner_id', fieldLabel: '客户',
        fieldType: 'many2one', relation: 'res.partner', query: '上海', relationOperation: 'set',
        resolution: 'ambiguous', snapshotId: testHostState.snapshotId,
        hostRevision: testHostState.hostRevision,
        candidates: [{ id: 42, displayName: '上海某公司', selected: false }]
      }
    }
    renderMessages({
      messages: [{ id: 'assistant-relation', role: 'assistant', content: '请选择', tool_calls: [relationTool] }],
      onSelectRelation
    })
    fireEvent.click(screen.getByRole('button', { name: /上海某公司/ }))
    expect(onSelectRelation).toHaveBeenCalledWith(relationTool, [
      { id: 42, displayName: '上海某公司', selected: false }
    ])
  })

  it('supports many2many selection and disables stale relation results', () => {
    const onSelectRelation = vi.fn()
    const relationTool = {
      id: 'relation-tags', name: 'odoo.search_relation', status: 'ok' as const,
      result: {
        ok: true, operation: 'odoo.search_relation', field: 'category_id', fieldLabel: '标签',
        fieldType: 'many2many', relation: 'res.partner.category', query: '重点', relationOperation: 'link',
        resolution: 'ambiguous', snapshotId: testHostState.snapshotId,
        hostRevision: testHostState.hostRevision,
        candidates: [{ id: 7, displayName: '重点客户', selected: false }]
      }
    }
    const { rerender } = renderMessages({
      messages: [{ id: 'assistant-tags', role: 'assistant', content: '请选择', tool_calls: [relationTool] }],
      onSelectRelation
    })
    fireEvent.click(screen.getByRole('checkbox', { name: /重点客户/ }))
    fireEvent.click(screen.getByRole('button', { name: labels.confirmRelationSelection }))
    expect(onSelectRelation).toHaveBeenCalledWith(relationTool, [
      { id: 7, displayName: '重点客户', selected: false }
    ])

    rerender(<Messages messages={[{ id: 'assistant-tags', role: 'assistant', content: '请选择', tool_calls: [relationTool] }]} running={false} labels={labels} icons={icons} hostState={{ ...testHostState, hostRevision: 2 }} onSelectRelation={onSelectRelation} onSelectRecord={vi.fn()} onConfirmTool={vi.fn()} onRegenerate={vi.fn()} onSuggestion={vi.fn()} onCopy={vi.fn()} onFeedback={vi.fn()} onPreviewAttachment={vi.fn()} />)
    expect(screen.getByText(labels.relationSelectionExpired)).toBeTruthy()
    expect((screen.getByRole('checkbox', { name: /重点客户/ }) as HTMLInputElement).disabled).toBe(true)
  })

  it('opens attachments through the file preview callback', () => {
    const attachment = {
      id: 'preview-1', name: 'contract.pdf', mimeType: 'application/pdf', size: 128,
      modality: 'document' as const
    }
    const onPreviewAttachment = vi.fn()
    renderMessages({
      messages: [{ id: 'user-preview', role: 'user', content: 'Review', attachments: [attachment] }],
      onPreviewAttachment
    })
    fireEvent.click(screen.getByRole('button', { name: `${labels.filePreview}: ${attachment.name}` }))
    expect(onPreviewAttachment).toHaveBeenCalledWith(attachment)
  })

  it('isolates exceptions from interaction observers', () => {
    const next = vi.fn()
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    observeInteraction(() => { throw new Error('observer failed') })
    next()
    expect(next).toHaveBeenCalledOnce()
    expect(error).toHaveBeenCalledOnce()
    error.mockRestore()
  })

  it('keeps current controls visible and history controls hover-only', () => {
    const { container } = renderMessages()
    const controls = container.querySelectorAll('.agui-message-controls')
    expect(controls).toHaveLength(2)
    expect(controls[0].className).toContain('opacity-0')
    expect(controls[0].classList.contains('opacity-100')).toBe(false)
    expect(controls[1].classList.contains('opacity-100')).toBe(true)
  })

  it('focuses the textarea when the empty input area is clicked', () => {
    const { container } = render(<ChatInput
      running={false}
      attachments={false}
      menuOptions={[]}
      labels={labels}
      icons={icons}
      onSend={vi.fn()}
      onStop={vi.fn()}
      onUpload={vi.fn()}
      onRemove={vi.fn()}
    />)
    fireEvent.click(container.querySelector('form')!)
    expect(document.activeElement).toBe(screen.getByPlaceholderText(labels.inputPlaceholder))
  })

  it('disables composing while a session is switching', () => {
    render(<ChatInput
      running={false}
      disabled
      attachments
      menuOptions={[]}
      labels={labels}
      icons={icons}
      onSend={vi.fn()}
      onStop={vi.fn()}
      onUpload={vi.fn()}
      onRemove={vi.fn()}
    />)
    expect((screen.getByPlaceholderText(labels.inputPlaceholder) as HTMLTextAreaElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: labels.addAttachments }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: labels.sendMessage }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('uploads files pasted from the clipboard', async () => {
    const onUpload = vi.fn(async (file: File) => ({
      id: 'pasted-1', name: file.name, mimeType: file.type, size: file.size, modality: 'document' as const
    }))
    const onRemove = vi.fn(async () => undefined)
    render(<ChatInput
      running={false}
      attachments
      menuOptions={[]}
      labels={labels}
      icons={icons}
      onSend={vi.fn()}
      onStop={vi.fn()}
      onUpload={onUpload}
      onRemove={onRemove}
    />)
    const file = new File(['clipboard'], 'clipboard.txt', { type: 'text/plain' })
    fireEvent.paste(screen.getByPlaceholderText(labels.inputPlaceholder), {
      clipboardData: { files: [file] }
    })
    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file, expect.any(Function)))
    await waitFor(() => expect(screen.getByText('文本文件 · 1 KB')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: labels.clearAttachments }))
    expect(screen.queryByText(file.name)).toBeNull()
    expect(onRemove).toHaveBeenCalledWith('pasted-1')
  })

  it('shows a stable drop target and uploads dropped files', async () => {
    const onUpload = vi.fn(async (file: File) => ({
      id: 'dropped-1', name: file.name, mimeType: file.type, size: file.size, modality: 'document' as const
    }))
    const { container } = render(<div className="agui-chat-react relative"><main className="relative"><ChatInput
        running={false}
        attachments
        menuOptions={[]}
        labels={labels}
        icons={icons}
        onSend={vi.fn()}
        onStop={vi.fn()}
        onUpload={onUpload}
        onRemove={vi.fn()}
      /></main></div>)
    const form = container.querySelector('form')!
    const file = new File(['drop'], 'dropped.txt', { type: 'text/plain' })
    fireEvent.dragEnter(form, { dataTransfer: { types: ['Files'], files: [file] } })
    expect(screen.getByLabelText('拖放附件')).toBeTruthy()
    fireEvent.drop(form, { dataTransfer: { types: ['Files'], files: [file] } })
    expect(screen.queryByLabelText('拖放附件')).toBeNull()
    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file, expect.any(Function)))
  })
})

class FakeRuntime {
  snapshot: RuntimeSnapshot = {
    messages: [{ id: 'a-1', role: 'assistant', content: 'Initial' }],
    sessions: [], session: null, hostState: testHostState, agentState: {}, threadId: 'thread-1', running: false,
    transportState: null, loadingSessions: false, error: ''
  }
  listener?: () => void
  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => { this.listener = listener; return () => undefined }
  emit() { this.listener?.() }
  newSession = vi.fn()
  refreshSessions = vi.fn()
  loadSession = vi.fn()
  regenerate = vi.fn()
  send = vi.fn()
  confirmTool = vi.fn()
  stop = vi.fn()
  uploadAttachment = vi.fn()
  deleteAttachment = vi.fn()
}

describe('stream following', () => {
  it('protects user scroll and resumes for a new user message and thread', async () => {
    const runtime = new FakeRuntime()
    const { container } = render(<AguiChatApp runtime={runtime as unknown as ChatRuntime} props={v2Props({ attachments: false })} />)
    const scroller = container.querySelector('main > div.overflow-y-auto') as HTMLDivElement
    let scrollTop = 0
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, get: () => 1000 },
      clientHeight: { configurable: true, get: () => 400 },
      scrollTop: { configurable: true, get: () => scrollTop, set: (value) => { scrollTop = Number(value) } }
    })

    scrollTop = 500
    fireEvent.scroll(scroller)
    scroller.append(document.createElement('span'))
    await act(async () => undefined)
    expect(scrollTop).toBe(500)

    runtime.snapshot = {
      ...runtime.snapshot,
      messages: [...runtime.snapshot.messages, { id: 'u-1', role: 'user', content: 'New question' }]
    }
    act(() => runtime.emit())
    expect(scrollTop).toBe(1000)

    scrollTop = 300
    fireEvent.scroll(scroller)
    runtime.snapshot = { ...runtime.snapshot, threadId: 'thread-2' }
    act(() => runtime.emit())
    expect(scrollTop).toBe(1000)
  })

  it('follows streaming DOM mutations while pinned to the bottom', async () => {
    const runtime = new FakeRuntime()
    const { container } = render(<AguiChatApp runtime={runtime as unknown as ChatRuntime} props={v2Props({ attachments: false })} />)
    const scroller = container.querySelector('main > div.overflow-y-auto') as HTMLDivElement
    let scrollTop = 0
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, get: () => 900 },
      clientHeight: { configurable: true, get: () => 400 },
      scrollTop: { configurable: true, get: () => scrollTop, set: (value) => { scrollTop = Number(value) } }
    })
    scrollTop = 500
    fireEvent.scroll(scroller)
    scroller.append(document.createTextNode('stream chunk'))
    await act(async () => undefined)
    expect(scrollTop).toBe(900)
  })
})

describe('file preview', () => {
  it('passes files to FileViewer and closes on Escape', async () => {
    const onClose = vi.fn()
    render(<FilePreviewPanel
      attachment={{ id: 'pdf-1', name: 'contract.pdf', mimeType: 'application/pdf', size: 1024, modality: 'document' }}
      labels={labels}
      onClose={onClose}
    />)
    expect(await screen.findByTestId('file-viewer')).toMatchObject({
      dataset: {
        url: '/agui_chat/attachment/pdf-1',
        filename: 'contract.pdf',
        type: 'pdf',
        options: 'light:shadow'
      }
    })
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('resizes the reusable aside with pointer and keyboard controls', async () => {
    const { container } = render(<div>
      <main />
      <FilePreviewPanel
        attachment={{ id: 'sheet-1', name: 'report.xlsx', mimeType: 'application/octet-stream', size: 1024, modality: 'document' }}
        labels={labels}
        onClose={vi.fn()}
      />
    </div>)
    const main = container.querySelector('main')!
    const panel = screen.getByRole('complementary', { name: labels.filePreview }) as HTMLElement
    main.getBoundingClientRect = () => ({ width: 600 } as DOMRect)
    panel.getBoundingClientRect = () => ({ width: 620 } as DOMRect)
    const resize = screen.getByRole('button', { name: '调整文件预览宽度' })
    await screen.findByTestId('file-viewer')

    fireEvent(resize, new MouseEvent('pointerdown', { bubbles: true, clientX: 700 }))
    fireEvent(window, new MouseEvent('pointermove', { bubbles: true, clientX: 600 }))
    expect(panel.style.getPropertyValue('--agui-aside-width')).toBe('720px')
    fireEvent.keyDown(resize, { key: 'ArrowLeft' })
    expect(panel.style.getPropertyValue('--agui-aside-width')).toBe('744px')
    fireEvent(window, new MouseEvent('pointerup', { bubbles: true }))
  })
})
