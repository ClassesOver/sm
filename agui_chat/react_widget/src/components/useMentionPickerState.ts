import { useEffect, useMemo, useReducer, useRef } from 'react'
import type { KeyboardEvent } from 'react'
import type { MenuMentionOption } from '../types'
import { createMentionPickerState, mentionPickerReducer } from './mentionPickerState'
import { usePickerNavigation } from './usePickerNavigation'

export interface MentionQuery {
  start: number
  end: number
  query: string
}

export const MENTION_PICKER_CATEGORIES = [
  { id: 'menu', label: '菜单', detail: '按名称或完整路径查找菜单' },
  { id: 'skill', label: '技能', detail: '选择适合当前任务的专业能力' }
] as const

interface UseMentionPickerStateOptions {
  open: boolean
  query: MentionQuery
  menuOptions: MenuMentionOption[]
  onSelectMenu: (option: MenuMentionOption) => void
  onOpenSkills: (query?: MentionQuery) => void
  onFocusInput: () => void
  onClose: () => void
}

export function useMentionPickerState({
  open, query, menuOptions, onSelectMenu, onOpenSkills, onFocusInput, onClose
}: UseMentionPickerStateOptions) {
  const [state, dispatch] = useReducer(mentionPickerReducer, query.query, createMentionPickerState)
  const { view, searchText } = state
  const typedNavigation = state.navigationSource === 'typed'
  const pickerRef = useRef<HTMLDivElement | null>(null)
  const previousViewRef = useRef(view)
  const previousQueryRef = useRef('')

  const filteredMenus = useMemo(() => {
    const needle = searchText.trim().toLocaleLowerCase()
    return menuOptions.filter((option) => (
      !needle || option.fullPath.toLocaleLowerCase().includes(needle)
    )).slice(0, 8)
  }, [menuOptions, searchText])
  const optionCount = view === 'home' ? MENTION_PICKER_CATEGORIES.length : filteredMenus.length
  const navigation = usePickerNavigation({ open, optionCount, captureEmptyActivation: true })

  useEffect(() => {
    dispatch({ type: 'query_synced', query: query.query })
    navigation.resetActiveIndex()
  }, [navigation.resetActiveIndex, query.query])

  useEffect(() => {
    const queryChanged = previousQueryRef.current !== query.query
    previousQueryRef.current = query.query
    if (!open || !queryChanged) return
    if (query.query && view === 'home') {
      if (MENTION_PICKER_CATEGORIES[navigation.activeIndex]?.id === 'skill') {
        onOpenSkills({ ...query })
        return
      }
      dispatch({ type: 'typed_query_started', query: query.query })
    } else if (!query.query && typedNavigation && view === 'menus') {
      dispatch({ type: 'typed_query_cleared' })
    }
  }, [navigation.activeIndex, onOpenSkills, open, query, typedNavigation, view])

  useEffect(() => {
    if (open && view === 'home' && previousViewRef.current === 'menus') {
      if (typedNavigation) onFocusInput()
      else pickerRef.current?.focus({ preventScroll: true })
    }
    previousViewRef.current = view
  }, [onFocusInput, open, typedNavigation, view])

  const goBack = () => {
    navigation.resetActiveIndex()
    if (view === 'menus') dispatch({ type: 'home_returned' })
    else onClose()
  }

  const activate = (index: number) => {
    if (view === 'menus') {
      const option = filteredMenus[index]
      if (option) onSelectMenu(option)
      return
    }
    const category = MENTION_PICKER_CATEGORIES[index]
    if (category?.id === 'menu') {
      dispatch({ type: 'menus_opened' })
      navigation.resetActiveIndex()
    } else if (category?.id === 'skill') {
      onOpenSkills()
    }
  }

  const handleKey = (event: KeyboardEvent<HTMLElement>): boolean => {
    return navigation.handleKey(event, activate, goBack)
  }

  const changeSearchText = (value: string) => {
    dispatch({ type: 'search_changed', searchText: value })
    navigation.resetActiveIndex()
  }

  const activeOptionId = view === 'home'
    ? `agui-mention-category-${MENTION_PICKER_CATEGORIES[navigation.activeIndex]?.id || 'none'}`
    : `agui-mention-menu-${filteredMenus[navigation.activeIndex]?.menuId || 'none'}`

  return {
    view,
    searchText,
    typedNavigation,
    pickerRef,
    filteredMenus,
    activeIndex: navigation.activeIndex,
    activeOptionId,
    activate,
    goBack,
    handleKey,
    changeSearchText
  }
}
