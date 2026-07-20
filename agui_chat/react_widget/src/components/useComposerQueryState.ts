import { useCallback, useState } from 'react'
import type { Dispatch, RefObject, SetStateAction } from 'react'
import type { MentionQuery } from './MentionPicker'
import { skillQueryAtCursor, type SkillQuery } from './SkillPicker'

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
  const [menuQuery, setMenuQuery] = useState<MentionQuery | null>(null)
  const [skillQuery, setSkillQuery] = useState<SkillQuery | null>(null)
  const [skillSearch, setSkillSearch] = useState('')
  const [skillOpen, setSkillOpen] = useState(false)
  const [skillReturnQuery, setSkillReturnQuery] = useState<MentionQuery | null>(null)
  const mentionSkillQuery = skillOpen && skillQuery && value[skillQuery.start] === '@' ? skillQuery : null
  const mentionPickerQuery = menuQuery || skillReturnQuery

  const dismissPickers = useCallback(() => {
    setMenuQuery(null)
    setSkillOpen(false)
    setSkillReturnQuery(null)
  }, [])

  const handleValueChange = (nextValue: string, cursor: number) => {
    const nextSkillQuery = skillQueryAtCursor(nextValue, cursor)
    const nextMention = menuQueryAtCursor(nextValue, cursor)
    setValue(nextValue)
    if (mentionSkillQuery) {
      if (nextMention?.query) {
        setSkillQuery(nextMention)
        setSkillSearch(nextMention.query)
        setSkillReturnQuery(nextMention)
        setMenuQuery(null)
      } else {
        setSkillQuery(null)
        setSkillSearch('')
        setSkillOpen(false)
        setSkillReturnQuery(null)
        setMenuQuery(nextMention)
      }
    } else if (nextSkillQuery && hasSkills) {
      setSkillQuery(nextSkillQuery)
      setSkillSearch(nextSkillQuery.query)
      setSkillOpen(true)
      setSkillReturnQuery(null)
      setMenuQuery(null)
    } else {
      setSkillQuery(null)
      setMenuQuery(nextMention)
      if (nextMention) {
        setSkillOpen(false)
        setSkillReturnQuery(null)
      }
    }
  }

  const handleCursorChange = (cursor: number) => {
    const nextSkillQuery = skillQueryAtCursor(value, cursor)
    if (nextSkillQuery && hasSkills) {
      setSkillQuery(nextSkillQuery)
      setSkillSearch(nextSkillQuery.query)
      setSkillOpen(true)
      setSkillReturnQuery(null)
      setMenuQuery(null)
    } else {
      const nextMention = menuQueryAtCursor(value, cursor)
      setMenuQuery(nextMention)
      if (nextMention) {
        setSkillOpen(false)
        setSkillQuery(null)
        setSkillSearch('')
        setSkillReturnQuery(null)
      }
    }
  }

  const returnToMentionCategories = () => {
    if (!skillReturnQuery) return
    const query = { ...skillReturnQuery }
    const mentionText = `@${query.query}`
    setValue((current) => current.slice(query.start, query.end) === mentionText
      ? current
      : current.slice(0, query.start) + mentionText + current.slice(query.start))
    setSkillOpen(false)
    setSkillQuery(null)
    setSkillSearch('')
    setMenuQuery(query)
    setSkillReturnQuery(null)
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
    setMenuQuery(null)
    window.setTimeout(() => {
      textareaRef.current?.focus()
      textareaRef.current?.setSelectionRange(cursor, cursor)
    }, 0)
    return query
  }

  const completeSkillSelection = () => {
    setSkillOpen(false)
    setSkillReturnQuery(null)
    if (skillQuery) {
      setValue((current) => current.slice(0, skillQuery.start) + current.slice(skillQuery.end))
      setSkillQuery(null)
      setSkillSearch('')
    }
  }

  const openSkillsFromMention = (typedQuery?: MentionQuery) => {
    const currentQuery = typedQuery || menuQuery || skillReturnQuery
    if (!currentQuery) return
    setSkillReturnQuery(currentQuery)
    if (typedQuery) {
      setSkillQuery(currentQuery)
      setSkillSearch(currentQuery.query)
      setSkillOpen(true)
      setMenuQuery(null)
      return
    }
    const cursor = currentQuery.start
    setValue((current) => current.slice(0, currentQuery.start) + current.slice(currentQuery.end))
    setMenuQuery(null)
    setSkillQuery(null)
    setSkillSearch('')
    setSkillOpen(true)
    window.setTimeout(() => textareaRef.current?.setSelectionRange(cursor, cursor), 0)
  }

  const closeMenuPicker = () => {
    setMenuQuery(null)
    setSkillReturnQuery(null)
  }

  const closeSkillPicker = () => {
    setSkillOpen(false)
    setSkillQuery(null)
    setSkillReturnQuery(null)
  }

  const toggleSkillPicker = () => {
    setSkillOpen((current) => !current)
    setSkillQuery(null)
    setSkillSearch('')
    setSkillReturnQuery(null)
    setMenuQuery(null)
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
