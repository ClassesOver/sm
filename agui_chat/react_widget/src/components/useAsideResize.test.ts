import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent
} from 'react'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAsideResize } from './useAsideResize'

afterEach(() => {
  cleanup()
  document.body.replaceChildren()
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  vi.restoreAllMocks()
})

function setupElements(panelWidth = 620, mainWidth = 600) {
  const main = document.createElement('main')
  const backdrop = document.createElement('button')
  const panel = document.createElement('aside')
  backdrop.className = 'agui-aside-backdrop'
  main.getBoundingClientRect = () => ({ width: mainWidth } as DOMRect)
  panel.getBoundingClientRect = () => ({ width: panelWidth } as DOMRect)
  document.body.append(main, backdrop, panel)
  return panel
}

function pointerEvent(clientX: number): ReactPointerEvent<HTMLButtonElement> {
  return { clientX, preventDefault: vi.fn() } as unknown as ReactPointerEvent<HTMLButtonElement>
}

function keyboardEvent(key: string): ReactKeyboardEvent<HTMLButtonElement> {
  return { key, preventDefault: vi.fn() } as unknown as ReactKeyboardEvent<HTMLButtonElement>
}

describe('侧栏尺寸状态', () => {
  it('使用主区域可用空间约束指针和键盘调整', () => {
    const panel = setupElements()
    const { result } = renderHook(() => useAsideResize({
      defaultWidth: 620,
      minWidth: 360,
      maxWidth: 920,
      minMainWidth: 420
    }))
    result.current.panelRef.current = panel

    act(() => result.current.handleResizeStart(pointerEvent(700)))
    act(() => window.dispatchEvent(new MouseEvent('pointermove', { clientX: 600 })))
    expect(result.current.style['--agui-aside-width' as keyof typeof result.current.style]).toBe('720px')
    act(() => result.current.handleResizeKeyDown(keyboardEvent('ArrowLeft')))
    expect(result.current.style['--agui-aside-width' as keyof typeof result.current.style]).toBe('744px')
    act(() => window.dispatchEvent(new MouseEvent('pointerup')))
  })

  it('拖动中卸载时移除全局监听并恢复 body 样式', () => {
    const panel = setupElements()
    const removeEventListener = vi.spyOn(window, 'removeEventListener')
    document.body.style.cursor = 'crosshair'
    document.body.style.userSelect = 'text'
    const { result, unmount } = renderHook(() => useAsideResize({
      defaultWidth: 620,
      minWidth: 360,
      maxWidth: 920,
      minMainWidth: 420
    }))
    result.current.panelRef.current = panel

    act(() => result.current.handleResizeStart(pointerEvent(700)))
    expect(document.body.style.cursor).toBe('col-resize')
    expect(document.body.style.userSelect).toBe('none')
    unmount()

    expect(document.body.style.cursor).toBe('crosshair')
    expect(document.body.style.userSelect).toBe('text')
    expect(removeEventListener).toHaveBeenCalledWith('pointermove', expect.any(Function))
    expect(removeEventListener).toHaveBeenCalledWith('pointerup', expect.any(Function))
  })
})
