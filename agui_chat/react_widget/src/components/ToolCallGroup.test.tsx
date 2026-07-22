import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mergeLabels } from '../customization'
import type { ToolCall } from '../types'
import { testHostState } from '../test/fixtures'
import { ToolCallGroup } from './ToolCallGroup'
import { getToolCallGroups } from './messagePresentation'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const labels = mergeLabels()

function groupFor(tools: ToolCall[]) {
  return getToolCallGroups([{
    id: 'assistant-1', role: 'assistant', extra_data: { agent_run_id: 'run-1' }, tool_calls: tools
  }]).get('assistant-1')!
}

function renderGroup(tools: ToolCall[], overrides: Record<string, unknown> = {}) {
  return render(<ToolCallGroup
    group={groupFor(tools)}
    labels={labels}
    hostState={testHostState}
    running={false}
    onSelectRelation={vi.fn()}
    onSelectRecord={vi.fn()}
    onConfirmTool={vi.fn()}
    onUndoTool={vi.fn()}
    {...overrides}
  />)
}

describe('工具调用组', () => {
  it('运行时展开、结束后收起并允许手动切换', async () => {
    const { rerender } = renderGroup([{ id: 'call-1', name: 'custom.run', status: 'running' }])
    const details = screen.getByTestId('tool-call-group') as HTMLDetailsElement
    expect(details.open).toBe(true)
    expect(screen.getByRole('list').className).toContain('max-h-56')

    rerender(<ToolCallGroup
      group={groupFor([{ id: 'call-1', name: 'custom.run', status: 'ok' }])}
      labels={labels}
      hostState={testHostState}
      running={false}
      onSelectRelation={vi.fn()}
      onSelectRecord={vi.fn()}
      onConfirmTool={vi.fn()}
      onUndoTool={vi.fn()}
    />)
    await waitFor(() => expect(details.open).toBe(false))

    fireEvent.click(screen.getByText('思考过程'))
    await waitFor(() => expect(details.open).toBe(true))
  })

  it('执行时在组内跟随最后一个活动工具', async () => {
    const originalDescriptors = {
      clientHeight: Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight'),
      scrollHeight: Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight'),
      scrollTo: Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo')
    }
    Object.defineProperties(HTMLElement.prototype, {
      clientHeight: { configurable: true, get() { return this instanceof HTMLElement && this.getAttribute('role') === 'list' ? 64 : 0 } },
      scrollHeight: { configurable: true, get() { return this instanceof HTMLElement && this.getAttribute('role') === 'list' ? this.children.length * 32 : 0 } }
    })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.getAttribute('role') === 'list') return new DOMRect(0, 100, 320, 64)
      if (this.classList.contains('agui-tool-row')) {
        const index = Array.from(this.parentElement?.children || []).indexOf(this)
        return new DOMRect(0, 100 + (index * 32) - (this.parentElement?.scrollTop || 0), 320, 32)
      }
      return new DOMRect()
    })
    const scrollTo = vi.fn(function (this: HTMLElement, options: ScrollToOptions) {
      this.scrollTop = Number(options.top || 0)
    })
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: scrollTo })

    try {
      renderGroup(Array.from({ length: 8 }, (_, index) => ({
        id: `call-${index}`,
        name: `custom.tool_${index}`,
        status: index === 7 ? 'running' : 'ok'
      })))

      await waitFor(() => expect(scrollTo).toHaveBeenCalledWith({ top: 192, behavior: 'smooth' }))
      expect((screen.getByRole('list') as HTMLElement).scrollTop).toBe(192)
    } finally {
      for (const [name, descriptor] of Object.entries(originalDescriptors)) {
        if (descriptor) {
          Object.defineProperty(HTMLElement.prototype, name, descriptor)
        } else {
          Reflect.deleteProperty(HTMLElement.prototype, name)
        }
      }
    }
  })

  it('保留确认、拒绝和撤销操作', () => {
    const onConfirmTool = vi.fn()
    const confirmation = { id: 'confirm-1', name: 'odoo.patch_current_form', status: 'needs_confirmation' as const }
    const { unmount } = renderGroup([confirmation], { onConfirmTool })
    fireEvent.click(screen.getByRole('button', { name: labels.approve }))
    fireEvent.click(screen.getByRole('button', { name: labels.reject }))
    expect(onConfirmTool).toHaveBeenNthCalledWith(1, confirmation, true)
    expect(onConfirmTool).toHaveBeenNthCalledWith(2, confirmation, false)

    unmount()
    const onUndoTool = vi.fn()
    const undo = {
      id: 'undo-1', name: 'odoo.patch_current_form', status: 'ok' as const,
      result: { receipt: { undo: { available: true, status: 'available' } } }
    }
    renderGroup([undo], { onUndoTool })
    fireEvent.click(screen.getByText('思考过程'))
    fireEvent.click(screen.getByText('修改当前表单'))
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    expect(onUndoTool).toHaveBeenCalledWith(undo)
  })

  it('折叠承载自定义 renderer 并为长名称提供 tooltip', () => {
    const name = 'custom.tool_with_a_very_long_name_that_must_be_truncated'
    renderGroup([{ id: 'custom-1', name, status: 'ok' }], {
      renderers: { [name]: ({ tool }: { tool: ToolCall }) => <div>自定义结果 {tool.id}</div> }
    })

    const label = screen.getByText(name)
    expect(label.getAttribute('title')).toBe(name)
    const row = label.closest('details') as HTMLDetailsElement
    expect(row.open).toBe(false)
    fireEvent.click(label)
    expect(row.open).toBe(true)
    expect(screen.getByText('自定义结果 custom-1')).toBeTruthy()
  })
})
