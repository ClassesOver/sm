import { AtSign, Menu, Sparkles } from 'lucide-react'
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { MenuMentionOption } from '../types'
import { cn } from '../lib'
import { PickerHeader } from './PickerHeader'
import { PickerSearch } from './PickerSearch'
import { PickerSurface } from './PickerSurface'

export interface MentionQuery {
  start: number
  end: number
  query: string
}

export interface MentionPickerHandle {
  handleKey: (event: KeyboardEvent<HTMLTextAreaElement>) => boolean
}

interface MentionPickerProps {
  open: boolean
  query: MentionQuery
  menuOptions: MenuMentionOption[]
  onSelectMenu: (option: MenuMentionOption) => void
  onOpenSkills: (query?: MentionQuery) => void
  onFocusInput: () => void
  onClose: () => void
}

const CATEGORIES = [
  { id: 'menu', label: '菜单', detail: '按名称或完整路径查找菜单' },
  { id: 'skill', label: '技能', detail: '选择适合当前任务的专业能力' }
] as const

export const MentionPicker = forwardRef<MentionPickerHandle, MentionPickerProps>(function MentionPicker({
  open, query, menuOptions, onSelectMenu, onOpenSkills, onFocusInput, onClose
}, ref) {
  const [view, setView] = useState<'home' | 'menus'>('home')
  const [searchText, setSearchText] = useState(query.query)
  const [activeIndex, setActiveIndex] = useState(0)
  const [typedNavigation, setTypedNavigation] = useState(false)
  const pickerRef = useRef<HTMLDivElement | null>(null)
  const previousViewRef = useRef(view)
  const previousQueryRef = useRef('')

  useEffect(() => {
    setSearchText(query.query)
    setActiveIndex(0)
  }, [query.query])

  useEffect(() => {
    const queryChanged = previousQueryRef.current !== query.query
    previousQueryRef.current = query.query
    if (!open || !queryChanged) return
    if (query.query && view === 'home') {
      if (CATEGORIES[activeIndex]?.id === 'skill') {
        onOpenSkills({ ...query })
        return
      }
      setTypedNavigation(true)
      setView('menus')
    } else if (!query.query && typedNavigation && view === 'menus') {
      setView('home')
    }
  }, [activeIndex, onOpenSkills, open, query, typedNavigation, view])

  useEffect(() => {
    if (open && view === 'home' && previousViewRef.current === 'menus') {
      if (typedNavigation) onFocusInput()
      else pickerRef.current?.focus({ preventScroll: true })
    }
    previousViewRef.current = view
  }, [onFocusInput, open, typedNavigation, view])

  const filteredMenus = useMemo(() => {
    const needle = searchText.trim().toLocaleLowerCase()
    return menuOptions.filter((option) => (
      !needle || option.fullPath.toLocaleLowerCase().includes(needle)
    )).slice(0, 8)
  }, [menuOptions, searchText])

  const optionCount = view === 'home' ? CATEGORIES.length : filteredMenus.length
  const activeOptionId = view === 'home'
    ? `agui-mention-category-${CATEGORIES[activeIndex]?.id || 'none'}`
    : `agui-mention-menu-${filteredMenus[activeIndex]?.menuId || 'none'}`

  const goBack = () => {
    setActiveIndex(0)
    if (view === 'menus') setView('home')
    else onClose()
  }

  const activate = (index: number) => {
    if (view === 'menus') {
      const option = filteredMenus[index]
      if (option) onSelectMenu(option)
      return
    }
    const category = CATEGORIES[index]
    if (category?.id === 'menu') {
      setTypedNavigation(false)
      setView('menus')
      setActiveIndex(0)
    } else if (category?.id === 'skill') {
      onOpenSkills()
    }
  }

  const handleKey = (event: KeyboardEvent<HTMLElement>): boolean => {
    if (!open || event.nativeEvent.isComposing) return false
    if (event.key === 'Escape') {
      event.preventDefault()
      goBack()
      return true
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const delta = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex((current) => optionCount ? (current + delta + optionCount) % optionCount : 0)
      return true
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      activate(activeIndex)
      return true
    }
    return false
  }

  useImperativeHandle(ref, () => ({ handleKey: (event) => handleKey(event) }))

  if (!open) return null
  return <PickerSurface
    ref={pickerRef}
    tabIndex={-1}
    className="text-secondary outline-none"
    ariaLabel="添加到对话"
    onKeyDown={handleKey}
  >
    <PickerHeader title={view === 'home' ? '添加到对话' : '选择菜单'} leading={<AtSign size={15} />} onBack={view === 'menus' ? goBack : undefined} />
    <div id="agui-mention-options" className="max-h-72 overflow-y-auto p-1" role="listbox" aria-activedescendant={activeOptionId}>
      {view === 'home' ? CATEGORIES.map((category, index) => <button
        id={`agui-mention-category-${category.id}`}
        key={category.id}
        type="button"
        role="option"
        aria-selected={index === activeIndex}
        className={cn('flex h-12 w-full items-center gap-2 border-l-2 border-l-transparent bg-white px-2 text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary', index === activeIndex && 'border-l-primary bg-background-secondary text-primary')}
        onClick={() => activate(index)}
      >
        <span className="grid size-7 shrink-0 place-items-center text-muted">{category.id === 'menu' ? <Menu size={15} /> : <Sparkles size={15} />}</span>
        <span className="min-w-0 flex-1"><span className="block text-xs text-primary">{category.label}</span><span className="block truncate text-[10px] text-muted">{category.detail}</span></span>
      </button>) : <>
        {!typedNavigation ? <PickerSearch autoFocus value={searchText} onChange={(event) => { setSearchText(event.target.value); setActiveIndex(0) }} placeholder="搜索菜单名称或完整路径" aria-label="搜索菜单" /> : null}
        {filteredMenus.map((option, index) => <button
          id={`agui-mention-menu-${option.menuId}`}
          key={option.menuId}
          type="button"
          role="option"
          aria-selected={index === activeIndex}
          className={cn('flex min-h-10 w-full items-center gap-2 border-l-2 border-l-transparent bg-white px-2.5 py-2 text-left text-xs text-secondary transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary', index === activeIndex && 'border-l-primary bg-background-secondary text-primary')}
          onClick={() => onSelectMenu(option)}
        >
          <AtSign className="size-3.5 shrink-0 text-muted" />
          <span className="min-w-0 flex-1 truncate" title={option.fullPath}>{option.fullPath}</span>
        </button>)}
        {!filteredMenus.length ? <div className="px-3 py-5 text-center text-xs text-muted">没有匹配的菜单</div> : null}
      </>}
    </div>
  </PickerSurface>
})
