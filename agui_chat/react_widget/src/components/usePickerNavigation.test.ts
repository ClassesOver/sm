import type { KeyboardEvent } from 'react'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePickerNavigation } from './usePickerNavigation'

afterEach(cleanup)

function keyEvent(key: string, composing = false) {
  const preventDefault = vi.fn()
  return {
    event: { key, preventDefault, nativeEvent: { isComposing: composing } } as unknown as KeyboardEvent<HTMLElement>,
    preventDefault
  }
}

describe('选择器键盘导航', () => {
  it('循环移动活动项并处理确认和返回', () => {
    const onActivate = vi.fn()
    const onEscape = vi.fn()
    const { result } = renderHook(() => usePickerNavigation({ open: true, optionCount: 3 }))

    const up = keyEvent('ArrowUp')
    act(() => result.current.handleKey(up.event, onActivate, onEscape))
    expect(result.current.activeIndex).toBe(2)
    expect(up.preventDefault).toHaveBeenCalledOnce()

    const enter = keyEvent('Enter')
    expect(result.current.handleKey(enter.event, onActivate, onEscape)).toBe(true)
    expect(onActivate).toHaveBeenCalledWith(2)

    const escape = keyEvent('Escape')
    expect(result.current.handleKey(escape.event, onActivate, onEscape)).toBe(true)
    expect(onEscape).toHaveBeenCalledOnce()
  })

  it('按配置支持 Home、End 和空格，并忽略输入法组合事件', () => {
    const onActivate = vi.fn()
    const { result } = renderHook(() => usePickerNavigation({
      open: true,
      optionCount: 4,
      allowHomeEnd: true,
      allowSpace: true
    }))

    act(() => result.current.handleKey(keyEvent('End').event, onActivate, vi.fn()))
    expect(result.current.activeIndex).toBe(3)
    act(() => result.current.handleKey(keyEvent('Home').event, onActivate, vi.fn()))
    expect(result.current.activeIndex).toBe(0)
    expect(result.current.handleKey(keyEvent(' ').event, onActivate, vi.fn())).toBe(true)
    expect(onActivate).toHaveBeenCalledWith(0)
    expect(result.current.handleKey(keyEvent('ArrowDown', true).event, onActivate, vi.fn())).toBe(false)
    expect(result.current.activeIndex).toBe(0)
  })
})
