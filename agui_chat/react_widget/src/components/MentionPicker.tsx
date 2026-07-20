import { AtSign, Menu, Sparkles } from 'lucide-react'
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { MenuMentionOption } from '../types'
import { PickerHeader } from './PickerHeader'
import { PickerOption } from './PickerOption'
import { PickerSearch } from './PickerSearch'
import { PickerSurface } from './PickerSurface'
import { usePickerNavigation } from './usePickerNavigation'

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
  const [typedNavigation, setTypedNavigation] = useState(false)
  const pickerRef = useRef<HTMLDivElement | null>(null)
  const previousViewRef = useRef(view)
  const previousQueryRef = useRef('')

  const filteredMenus = useMemo(() => {
    const needle = searchText.trim().toLocaleLowerCase()
    return menuOptions.filter((option) => (
      !needle || option.fullPath.toLocaleLowerCase().includes(needle)
    )).slice(0, 8)
  }, [menuOptions, searchText])
  const optionCount = view === 'home' ? CATEGORIES.length : filteredMenus.length
  const navigation = usePickerNavigation({ open, optionCount, captureEmptyActivation: true })

  useEffect(() => {
    setSearchText(query.query)
    navigation.resetActiveIndex()
  }, [navigation.resetActiveIndex, query.query])

  useEffect(() => {
    const queryChanged = previousQueryRef.current !== query.query
    previousQueryRef.current = query.query
    if (!open || !queryChanged) return
    if (query.query && view === 'home') {
      if (CATEGORIES[navigation.activeIndex]?.id === 'skill') {
        onOpenSkills({ ...query })
        return
      }
      setTypedNavigation(true)
      setView('menus')
    } else if (!query.query && typedNavigation && view === 'menus') {
      setView('home')
    }
  }, [navigation.activeIndex, onOpenSkills, open, query, typedNavigation, view])

  useEffect(() => {
    if (open && view === 'home' && previousViewRef.current === 'menus') {
      if (typedNavigation) onFocusInput()
      else pickerRef.current?.focus({ preventScroll: true })
    }
    previousViewRef.current = view
  }, [onFocusInput, open, typedNavigation, view])

  const activeOptionId = view === 'home'
    ? `agui-mention-category-${CATEGORIES[navigation.activeIndex]?.id || 'none'}`
    : `agui-mention-menu-${filteredMenus[navigation.activeIndex]?.menuId || 'none'}`

  const goBack = () => {
    navigation.resetActiveIndex()
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
      navigation.resetActiveIndex()
    } else if (category?.id === 'skill') {
      onOpenSkills()
    }
  }

  const handleKey = (event: KeyboardEvent<HTMLElement>): boolean => {
    return navigation.handleKey(event, activate, goBack)
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
      {view === 'home' ? CATEGORIES.map((category, index) => <PickerOption
        id={`agui-mention-category-${category.id}`}
        key={category.id}
        active={index === navigation.activeIndex}
        density="roomy"
        onClick={() => activate(index)}
      >
        <span className="grid size-7 shrink-0 place-items-center text-muted">{category.id === 'menu' ? <Menu size={15} /> : <Sparkles size={15} />}</span>
        <span className="min-w-0 flex-1"><span className="block text-xs text-primary">{category.label}</span><span className="block truncate text-[10px] text-muted">{category.detail}</span></span>
      </PickerOption>) : <>
        {!typedNavigation ? <PickerSearch autoFocus value={searchText} onChange={(event) => { setSearchText(event.target.value); navigation.resetActiveIndex() }} placeholder="搜索菜单名称或完整路径" aria-label="搜索菜单" /> : null}
        {filteredMenus.map((option, index) => <PickerOption
          id={`agui-mention-menu-${option.menuId}`}
          key={option.menuId}
          active={index === navigation.activeIndex}
          density="compact"
          className="text-xs text-secondary"
          onClick={() => onSelectMenu(option)}
        >
          <AtSign className="size-3.5 shrink-0 text-muted" />
          <span className="min-w-0 flex-1 truncate" title={option.fullPath}>{option.fullPath}</span>
        </PickerOption>)}
        {!filteredMenus.length ? <div className="px-3 py-5 text-center text-xs text-muted">没有匹配的菜单</div> : null}
      </>}
    </div>
  </PickerSurface>
})
