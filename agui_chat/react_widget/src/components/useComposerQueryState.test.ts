import { useRef, useState } from 'react'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { composerQueryReducer, INITIAL_COMPOSER_QUERY_STATE } from './composerQueryState'
import { useComposerQueryState } from './useComposerQueryState'

afterEach(cleanup)

function useQueryHarness(hasSkills = true) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const picker = useComposerQueryState({ value, setValue, hasSkills, textareaRef })
  return { value, ...picker }
}

describe('消息输入查询状态', () => {
  it('reducer 用互斥模式表达菜单和技能状态', () => {
    const menuQuery = { start: 0, end: 3, query: '客户' }
    const menuState = composerQueryReducer(INITIAL_COMPOSER_QUERY_STATE, {
      type: 'value_changed',
      mentionQuery: menuQuery,
      skillQuery: null,
      hasSkills: true,
      editingMentionSkill: false
    })
    expect(menuState).toEqual({ mode: 'menu', query: menuQuery })

    const skillState = composerQueryReducer(menuState, {
      type: 'open_skills_from_mention',
      query: menuQuery,
      inline: true
    })
    expect(skillState).toEqual({
      mode: 'skills',
      query: menuQuery,
      search: '客户',
      returnQuery: menuQuery
    })
    expect(composerQueryReducer(skillState, { type: 'return_to_mentions' })).toEqual(menuState)
  })

  it('保持菜单和技能选择器互斥', () => {
    const { result } = renderHook(() => useQueryHarness())

    act(() => result.current.handleValueChange('@客户', 3))
    expect(result.current.menuQuery).toEqual({ start: 0, end: 3, query: '客户' })
    expect(result.current.skillOpen).toBe(false)

    act(() => result.current.openSkillsFromMention(result.current.menuQuery!))
    expect(result.current.menuQuery).toBeNull()
    expect(result.current.skillOpen).toBe(true)
    expect(result.current.skillSearch).toBe('客户')

    act(() => result.current.handleValueChange('@', 1))
    expect(result.current.skillOpen).toBe(false)
    expect(result.current.menuQuery).toEqual({ start: 0, end: 1, query: '' })
  })

  it('从菜单分类进入技能后可恢复原始 @ 查询', () => {
    const { result } = renderHook(() => useQueryHarness())

    act(() => result.current.handleValueChange('@', 1))
    act(() => result.current.openSkillsFromMention())
    expect(result.current.value).toBe('')
    expect(result.current.skillOpen).toBe(true)
    expect(result.current.skillReturnQuery).toEqual({ start: 0, end: 1, query: '' })

    act(() => result.current.returnToMentionCategories())
    expect(result.current.value).toBe('@')
    expect(result.current.skillOpen).toBe(false)
    expect(result.current.menuQuery).toEqual({ start: 0, end: 1, query: '' })
  })

  it('完成斜杠技能选择后移除查询文本', () => {
    const { result } = renderHook(() => useQueryHarness())

    act(() => result.current.handleValueChange('/审计', 3))
    expect(result.current.skillOpen).toBe(true)
    expect(result.current.skillSearch).toBe('审计')

    act(() => result.current.completeSkillSelection())
    expect(result.current.value).toBe('')
    expect(result.current.skillOpen).toBe(false)
    expect(result.current.skillSearch).toBe('')
  })

  it('消费菜单查询并保留查询前后的正文', () => {
    const { result } = renderHook(() => useQueryHarness())

    act(() => result.current.handleValueChange('请打开 @客户 后检查', 7))
    let consumed = null
    act(() => { consumed = result.current.consumeMenuQuery() })

    expect(consumed).toEqual({ start: 4, end: 7, query: '客户' })
    expect(result.current.value).toBe('请打开  后检查')
    expect(result.current.menuQuery).toBeNull()
  })
})
