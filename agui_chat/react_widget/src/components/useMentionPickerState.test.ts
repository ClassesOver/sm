import type { KeyboardEvent } from 'react'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MenuMentionOption } from '../types'
import { createMentionPickerState, mentionPickerReducer } from './mentionPickerState'
import { type MentionQuery, useMentionPickerState } from './useMentionPickerState'

afterEach(cleanup)

const menuOptions: MenuMentionOption[] = [
  { menuId: 1, actionId: 11, name: '客户', path: ['销售', '客户'], fullPath: '销售 / 客户' },
  { menuId: 2, actionId: 12, name: '工单', path: ['服务', '工单'], fullPath: '服务 / 工单' }
]

function keyEvent(key: string): KeyboardEvent<HTMLElement> {
  return {
    key,
    nativeEvent: { isComposing: false },
    preventDefault: vi.fn()
  } as unknown as KeyboardEvent<HTMLElement>
}

describe('菜单选择器状态', () => {
  it('reducer 原子维护菜单层级和进入来源', () => {
    const initial = createMentionPickerState('')
    const explicit = mentionPickerReducer(initial, { type: 'menus_opened' })
    expect(explicit).toEqual({ view: 'menus', searchText: '', navigationSource: 'explicit' })
    expect(mentionPickerReducer(explicit, { type: 'typed_query_cleared' })).toBe(explicit)

    const typed = mentionPickerReducer(initial, { type: 'typed_query_started', query: '客户' })
    expect(typed).toEqual({ view: 'menus', searchText: '客户', navigationSource: 'typed' })
    expect(mentionPickerReducer(typed, { type: 'typed_query_cleared' })).toEqual({
      view: 'home',
      searchText: '',
      navigationSource: 'typed'
    })
  })

  it('管理分类、菜单搜索和返回层级', () => {
    const onSelectMenu = vi.fn()
    const onClose = vi.fn()
    const { result } = renderHook(() => useMentionPickerState({
      open: true,
      query: { start: 0, end: 1, query: '' },
      menuOptions,
      onSelectMenu,
      onOpenSkills: vi.fn(),
      onFocusInput: vi.fn(),
      onClose
    }))

    act(() => result.current.activate(0))
    expect(result.current.view).toBe('menus')
    expect(result.current.typedNavigation).toBe(false)
    act(() => result.current.changeSearchText('工单'))
    expect(result.current.filteredMenus).toEqual([menuOptions[1]])
    act(() => result.current.activate(0))
    expect(onSelectMenu).toHaveBeenCalledWith(menuOptions[1])
    act(() => result.current.goBack())
    expect(result.current.view).toBe('home')
    act(() => result.current.goBack())
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('输入菜单查询时自动进入菜单并在清空后恢复分类', () => {
    const onFocusInput = vi.fn()
    const { result, rerender } = renderHook(
      ({ query }: { query: MentionQuery }) => useMentionPickerState({
        open: true,
        query,
        menuOptions,
        onSelectMenu: vi.fn(),
        onOpenSkills: vi.fn(),
        onFocusInput,
        onClose: vi.fn()
      }),
      { initialProps: { query: { start: 0, end: 1, query: '' } } }
    )

    rerender({ query: { start: 0, end: 3, query: '客户' } })
    expect(result.current.view).toBe('menus')
    expect(result.current.typedNavigation).toBe(true)
    expect(result.current.filteredMenus).toEqual([menuOptions[0]])
    rerender({ query: { start: 0, end: 1, query: '' } })
    expect(result.current.view).toBe('home')
    expect(onFocusInput).toHaveBeenCalledOnce()
  })

  it('高亮技能分类后将输入查询转交技能选择器', () => {
    const onOpenSkills = vi.fn()
    const { result, rerender } = renderHook(
      ({ query }: { query: MentionQuery }) => useMentionPickerState({
        open: true,
        query,
        menuOptions,
        onSelectMenu: vi.fn(),
        onOpenSkills,
        onFocusInput: vi.fn(),
        onClose: vi.fn()
      }),
      { initialProps: { query: { start: 0, end: 1, query: '' } } }
    )

    act(() => result.current.handleKey(keyEvent('ArrowDown')))
    expect(result.current.activeOptionId).toContain('skill')
    rerender({ query: { start: 0, end: 3, query: '审计' } })
    expect(onOpenSkills).toHaveBeenCalledWith({ start: 0, end: 3, query: '审计' })
  })
})
