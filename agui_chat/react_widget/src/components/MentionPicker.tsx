import { AtSign, Menu, Sparkles } from 'lucide-react'
import { forwardRef, useImperativeHandle } from 'react'
import type { KeyboardEvent } from 'react'
import type { MenuMentionOption } from '../types'
import { PickerHeader } from './PickerHeader'
import { PickerOption } from './PickerOption'
import { PickerSearch } from './PickerSearch'
import { PickerSurface } from './PickerSurface'
import {
  MENTION_PICKER_CATEGORIES,
  useMentionPickerState,
  type MentionQuery
} from './useMentionPickerState'

export type { MentionQuery } from './useMentionPickerState'

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

export const MentionPicker = forwardRef<MentionPickerHandle, MentionPickerProps>(function MentionPicker({
  open, query, menuOptions, onSelectMenu, onOpenSkills, onFocusInput, onClose
}, ref) {
  const picker = useMentionPickerState({
    open,
    query,
    menuOptions,
    onSelectMenu,
    onOpenSkills,
    onFocusInput,
    onClose
  })

  useImperativeHandle(ref, () => ({ handleKey: (event) => picker.handleKey(event) }))

  if (!open) return null
  return <PickerSurface
    ref={picker.pickerRef}
    tabIndex={-1}
    className="text-secondary outline-none"
    ariaLabel="添加到对话"
    onKeyDown={picker.handleKey}
  >
    <PickerHeader title={picker.view === 'home' ? '添加到对话' : '选择菜单'} leading={<AtSign size={15} />} onBack={picker.view === 'menus' ? picker.goBack : undefined} />
    <div id="agui-mention-options" className="max-h-72 overflow-y-auto p-1" role="listbox" aria-activedescendant={picker.activeOptionId}>
      {picker.view === 'home' ? MENTION_PICKER_CATEGORIES.map((category, index) => <PickerOption
        id={`agui-mention-category-${category.id}`}
        key={category.id}
        active={index === picker.activeIndex}
        density="roomy"
        onClick={() => picker.activate(index)}
      >
        <span className="grid size-7 shrink-0 place-items-center text-muted">{category.id === 'menu' ? <Menu size={15} /> : <Sparkles size={15} />}</span>
        <span className="min-w-0 flex-1"><span className="block text-xs text-primary">{category.label}</span><span className="block truncate text-[10px] text-muted">{category.detail}</span></span>
      </PickerOption>) : <>
        {!picker.typedNavigation ? <PickerSearch autoFocus value={picker.searchText} onChange={(event) => picker.changeSearchText(event.target.value)} placeholder="搜索菜单名称或完整路径" aria-label="搜索菜单" /> : null}
        {picker.filteredMenus.map((option, index) => <PickerOption
          id={`agui-mention-menu-${option.menuId}`}
          key={option.menuId}
          active={index === picker.activeIndex}
          density="compact"
          className="text-xs text-secondary"
          onClick={() => picker.activate(index)}
        >
          <AtSign className="size-3.5 shrink-0 text-muted" />
          <span className="min-w-0 flex-1 truncate" title={option.fullPath}>{option.fullPath}</span>
        </PickerOption>)}
        {!picker.filteredMenus.length ? <div className="px-3 py-5 text-center text-xs text-muted">没有匹配的菜单</div> : null}
      </>}
    </div>
  </PickerSurface>
})
