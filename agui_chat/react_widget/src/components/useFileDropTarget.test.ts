import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useFileDropTarget } from './useFileDropTarget'

afterEach(() => {
  cleanup()
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

function setupTarget() {
  const main = document.createElement('main')
  const textarea = document.createElement('textarea')
  main.append(textarea)
  document.body.append(main)
  return { main, anchorRef: { current: textarea } }
}

function dragEvent(type: string, files: File[] = []) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', {
    value: {
      files,
      items: files.map((file) => ({ kind: 'file', getAsFile: () => file })),
      types: files.length ? ['Files'] : []
    }
  })
  return event
}

describe('文件拖放目标', () => {
  it('跟踪嵌套拖入层级并在最后一次离开时关闭状态', () => {
    const { main, anchorRef } = setupTarget()
    const file = new File(['report'], 'report.txt', { type: 'text/plain' })
    const { result } = renderHook(() => useFileDropTarget({
      enabled: true,
      disabled: false,
      anchorRef,
      onFiles: vi.fn()
    }))

    act(() => main.dispatchEvent(dragEvent('dragenter', [file])))
    act(() => main.dispatchEvent(dragEvent('dragenter', [file])))
    expect(result.current.dragging).toBe(true)
    act(() => main.dispatchEvent(dragEvent('dragleave', [file])))
    expect(result.current.dragging).toBe(true)
    act(() => main.dispatchEvent(dragEvent('dragleave', [file])))
    expect(result.current.dragging).toBe(false)
  })

  it('投放时去重文件并调用最新回调', () => {
    const { main, anchorRef } = setupTarget()
    const file = new File(['report'], 'report.txt', { type: 'text/plain' })
    const first = vi.fn()
    const second = vi.fn()
    const { result, rerender } = renderHook(
      ({ onFiles }) => useFileDropTarget({ enabled: true, disabled: false, anchorRef, onFiles }),
      { initialProps: { onFiles: first } }
    )

    act(() => main.dispatchEvent(dragEvent('dragenter', [file])))
    expect(result.current.dragging).toBe(true)
    rerender({ onFiles: second })
    const event = dragEvent('drop', [file])
    act(() => main.dispatchEvent(event))

    expect(event.defaultPrevented).toBe(true)
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledWith([file])
    expect(result.current.dragging).toBe(false)
  })

  it('禁用或卸载后移除目标监听', () => {
    const { main, anchorRef } = setupTarget()
    const removeEventListener = vi.spyOn(main, 'removeEventListener')
    const onFiles = vi.fn()
    const { rerender, unmount } = renderHook(
      ({ disabled }) => useFileDropTarget({ enabled: true, disabled, anchorRef, onFiles }),
      { initialProps: { disabled: false } }
    )

    rerender({ disabled: true })
    act(() => main.dispatchEvent(dragEvent('drop', [new File(['x'], 'x.txt', { type: 'text/plain' })])))
    expect(onFiles).not.toHaveBeenCalled()
    expect(removeEventListener).toHaveBeenCalledWith('drop', expect.any(Function))
    unmount()
  })
})
