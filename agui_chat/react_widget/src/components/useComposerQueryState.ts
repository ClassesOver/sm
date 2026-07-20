import { useCallback, useReducer } from 'react'
import type { Dispatch, RefObject, SetStateAction } from 'react'
import type { MentionQuery } from './useMentionPickerState'
import { skillQueryAtCursor } from './SkillPicker'
import { composerQueryReducer, INITIAL_COMPOSER_QUERY_STATE } from './composerQueryState'

interface UseComposerQueryStateOptions {
  value: string
  setValue: Dispatch<SetStateAction<string>>
  hasSkills: boolean
  textareaRef: RefObject<HTMLTextAreaElement>
}

const MENTION_BOUNDARY = /[\s,，.。!！?？;；:：、()\[\]{}【】<>《》"'“”‘’]/u
const MENTION_TERMINATOR = /[\s@,，.。!！?？;；:：、()\[\]{}【】<>《》"'“”‘’]/u

export function menuQueryAtCursor(value: string, cursor: number): MentionQuery | null {
  const safeCursor = Math.max(0, Math.min(cursor, value.length))
  let at = safeCursor - 1
  while (at >= 0 && value[at] !== '@' && !MENTION_TERMINATOR.test(value[at])) at -= 1
  if (at < 0 || value[at] !== '@') return null
  if (at > 0 && !MENTION_BOUNDARY.test(value[at - 1])) return null
  let end = safeCursor
  while (end < value.length && !MENTION_TERMINATOR.test(value[end])) end += 1
  return { start: at, end, query: value.slice(at + 1, end) }
}

export function useComposerQueryState({
  value, setValue, hasSkills, textareaRef
}: UseComposerQueryStateOptions) {
  const [queryState, dispatch] = useReducer(composerQueryReducer, INITIAL_COMPOSER_QUERY_STATE)
  const menuQuery = queryState.mode === 'menu' ? queryState.query : null
  const skillQuery = queryState.mode === 'skills' ? queryState.query : null
  const skillSearch = queryState.mode === 'skills' ? queryState.search : ''
  const skillOpen = queryState.mode === 'skills'
  const skillReturnQuery = queryState.mode === 'skills' ? queryState.returnQuery : null
  const mentionSkillQuery = skillQuery && value[skillQuery.start] === '@' ? skillQuery : null
  const mentionPickerQuery = menuQuery || skillReturnQuery

  const dismissPickers = useCallback(() => {
    dispatch({ type: 'dismiss' })
  }, [])

  const setSkillSearch = useCallback((search: string) => {
    dispatch({ type: 'skill_search_changed', search })
  }, [])

  const handleValueChange = (nextValue: string, cursor: number) => {
    const nextSkillQuery = skillQueryAtCursor(nextValue, cursor)
    const nextMention = menuQueryAtCursor(nextValue, cursor)
    setValue(nextValue)
    dispatch({
      type: 'value_changed',
      mentionQuery: nextMention,
      skillQuery: nextSkillQuery,
      hasSkills,
      editingMentionSkill: Boolean(mentionSkillQuery)
    })
  }

  const handleCursorChange = (cursor: number) => {
    const nextSkillQuery = skillQueryAtCursor(value, cursor)
    dispatch({
      type: 'cursor_changed',
      mentionQuery: menuQueryAtCursor(value, cursor),
      skillQuery: nextSkillQuery,
      hasSkills
    })
  }

  const returnToMentionCategories = () => {
    if (!skillReturnQuery) return
    const query = { ...skillReturnQuery }
    const mentionText = `@${query.query}`
    setValue((current) => current.slice(query.start, query.end) === mentionText
      ? current
      : current.slice(0, query.start) + mentionText + current.slice(query.start))
    dispatch({ type: 'return_to_mentions' })
    window.setTimeout(() => {
      textareaRef.current?.focus({ preventScroll: true })
      textareaRef.current?.setSelectionRange(query.end, query.end)
    }, 0)
  }

  const consumeMenuQuery = (): MentionQuery | null => {
    if (!menuQuery) return null
    const query = { ...menuQuery }
    const cursor = query.start
    setValue((current) => current.slice(0, query.start) + current.slice(query.end))
    dispatch({ type: 'consume_menu' })
    window.setTimeout(() => {
      textareaRef.current?.focus()
      textareaRef.current?.setSelectionRange(cursor, cursor)
    }, 0)
    return query
  }

  const completeSkillSelection = () => {
    if (skillQuery) {
      setValue((current) => current.slice(0, skillQuery.start) + current.slice(skillQuery.end))
    }
    dispatch({ type: 'complete_skill' })
  }

  const openSkillsFromMention = (typedQuery?: MentionQuery) => {
    const currentQuery = typedQuery || menuQuery || skillReturnQuery
    if (!currentQuery) return
    if (typedQuery) {
      dispatch({ type: 'open_skills_from_mention', query: currentQuery, inline: true })
      return
    }
    const cursor = currentQuery.start
    setValue((current) => current.slice(0, currentQuery.start) + current.slice(currentQuery.end))
    dispatch({ type: 'open_skills_from_mention', query: currentQuery, inline: false })
    window.setTimeout(() => textareaRef.current?.setSelectionRange(cursor, cursor), 0)
  }

  const closeMenuPicker = () => {
    dispatch({ type: 'close_menu' })
  }

  const closeSkillPicker = () => {
    dispatch({ type: 'close_skills' })
  }

  const toggleSkillPicker = () => {
    dispatch({ type: 'toggle_skills' })
  }

  return {
    menuQuery,
    skillSearch,
    skillOpen,
    skillReturnQuery,
    mentionSkillQuery,
    mentionPickerQuery,
    setSkillSearch,
    dismissPickers,
    handleValueChange,
    handleCursorChange,
    returnToMentionCategories,
    consumeMenuQuery,
    completeSkillSelection,
    openSkillsFromMention,
    closeMenuPicker,
    closeSkillPicker,
    toggleSkillPicker
  }
}
