import { createRef } from 'react'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AttachmentRef, SelectedAgentSkill, WorkspaceReference } from '../types'
import { useComposerSubmit, type ComposerSend } from './useComposerSubmit'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const attachment: AttachmentRef = {
  id: 'attachment-1',
  name: '合同.pdf',
  mimeType: 'application/pdf',
  size: 1024,
  modality: 'document'
}
const skill: SelectedAgentSkill = {
  id: 'audit',
  name: '合同审计',
  description: '核对合同字段',
  valid: true
}
const reference: WorkspaceReference = {
  id: 'workspace-1',
  path: '合同/甲.pdf',
  name: '甲.pdf',
  isDirectory: false
}

function renderSubmit(overrides: Partial<Parameters<typeof useComposerSubmit>[0]> = {}) {
  const textarea = document.createElement('textarea')
  const focus = vi.spyOn(textarea, 'focus')
  const textareaRef = { current: textarea }
  const options: Parameters<typeof useComposerSubmit>[0] = {
    running: false,
    disabled: false,
    value: '  检查合同  ',
    setValue: vi.fn(),
    attachmentItems: [{ status: 'ready' }],
    readyAttachments: [attachment],
    selectedSkills: [skill],
    workspaceReferences: [reference],
    onSend: vi.fn(async () => true),
    resetSelections: vi.fn(),
    dismissPickers: vi.fn(),
    resetAttachments: vi.fn(),
    textareaRef,
    ...overrides
  }
  return { ...renderHook(() => useComposerSubmit(options)), options, focus }
}

describe('消息提交状态', () => {
  it('成功发送后克隆上下文并统一重置', async () => {
    vi.useFakeTimers()
    const onSend = vi.fn<ComposerSend>(async () => true)
    const { result, options, focus } = renderSubmit({ onSend })

    await act(async () => result.current.submit())
    const [, sentAttachments, , sentSkills, sentReferences] = onSend.mock.calls[0]
    expect(onSend).toHaveBeenCalledWith('检查合同', [attachment], undefined, [skill], [reference])
    expect(sentAttachments).toBe(options.readyAttachments)
    expect(sentSkills?.[0]).not.toBe(skill)
    expect(sentReferences?.[0]).not.toBe(reference)
    expect(options.setValue).toHaveBeenCalledWith('')
    expect(options.resetSelections).toHaveBeenCalledOnce()
    expect(options.dismissPickers).toHaveBeenCalledOnce()
    expect(options.resetAttachments).toHaveBeenCalledOnce()
    act(() => vi.runAllTimers())
    expect(focus).toHaveBeenCalledOnce()
  })

  it('没有技能时省略技能参数', async () => {
    const onSend = vi.fn<ComposerSend>(async () => true)
    const { result } = renderSubmit({ selectedSkills: [], onSend })

    await act(async () => result.current.submit())
    expect(onSend.mock.calls[0][3]).toBeUndefined()
  })

  it('发送失败或抛错时保留当前输入和上下文', async () => {
    const resetSelections = vi.fn()
    const resetAttachments = vi.fn()
    const { result, rerender } = renderHook(
      ({ onSend }: { onSend: ComposerSend }) => useComposerSubmit({
        running: false,
        disabled: false,
        value: '检查合同',
        setValue: vi.fn(),
        attachmentItems: [],
        readyAttachments: [],
        selectedSkills: [],
        workspaceReferences: [],
        onSend,
        resetSelections,
        dismissPickers: vi.fn(),
        resetAttachments,
        textareaRef: createRef<HTMLTextAreaElement>()
      }),
      { initialProps: { onSend: vi.fn(async () => false) as ComposerSend } }
    )

    await act(async () => result.current.submit())
    expect(resetSelections).not.toHaveBeenCalled()
    rerender({ onSend: vi.fn(async () => { throw new Error('发送失败') }) })
    await act(async () => result.current.submit())
    expect(resetAttachments).not.toHaveBeenCalled()
    expect(result.current.sending).toBe(false)
  })

  it('运行中、禁用或存在未完成附件时不可发送', () => {
    expect(renderSubmit({ running: true }).result.current.canSend).toBe(false)
    expect(renderSubmit({ disabled: true }).result.current.canSend).toBe(false)
    expect(renderSubmit({ attachmentItems: [{ status: 'uploading' }] }).result.current.canSend).toBe(false)
  })
})
