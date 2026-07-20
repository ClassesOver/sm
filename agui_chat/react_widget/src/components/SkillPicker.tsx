import { Check, Sparkles } from 'lucide-react'
import { forwardRef, useEffect, useImperativeHandle, useMemo } from 'react'
import type { KeyboardEvent } from 'react'
import type { AgentSkillOption, SelectedAgentSkill } from '../types'
import { cn } from '../lib'
import { PickerHeader } from './PickerHeader'
import { PickerOption } from './PickerOption'
import { PickerSearch } from './PickerSearch'
import { PickerSurface } from './PickerSurface'
import { usePickerNavigation } from './usePickerNavigation'

export interface SkillQuery {
  start: number
  end: number
  query: string
}

export interface SkillPickerHandle {
  handleKey: (event: KeyboardEvent<HTMLTextAreaElement>) => boolean
}

interface SkillPickerProps {
  open: boolean
  query: string
  skills: AgentSkillOption[]
  selected: SelectedAgentSkill[]
  inlineQuery?: boolean
  onQueryChange: (query: string) => void
  onToggle: (skill: AgentSkillOption) => void
  onBack?: () => void
  onClose: () => void
}

export function skillQueryAtCursor(value: string, cursor: number): SkillQuery | null {
  if (!value.startsWith('/')) return null
  const lineEnd = value.indexOf('\n')
  const tokenEnd = lineEnd < 0 ? value.length : lineEnd
  if (cursor > tokenEnd) return null
  return {
    start: 0,
    end: lineEnd < 0 ? tokenEnd : tokenEnd + 1,
    query: value.slice(1, tokenEnd)
  }
}

export const SkillPicker = forwardRef<SkillPickerHandle, SkillPickerProps>(function SkillPicker({
  open, query, skills, selected, inlineQuery = false, onQueryChange, onToggle, onBack, onClose
}, ref) {
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return skills.slice(0, 50).filter((skill) =>
      !needle || skill.name.toLocaleLowerCase().includes(needle) ||
      skill.description.toLocaleLowerCase().includes(needle)
    )
  }, [query, skills])
  const navigation = usePickerNavigation({
    open,
    optionCount: filtered.length,
    allowHomeEnd: true,
    allowSpace: true
  })

  useEffect(() => navigation.resetActiveIndex(), [navigation.resetActiveIndex, open, query])

  const handleKey = (event: KeyboardEvent<HTMLElement>): boolean => {
    return navigation.handleKey(
      event,
      (index) => onToggle(filtered[index]),
      onBack || onClose
    )
  }

  useImperativeHandle(ref, () => ({
    handleKey: (event) => handleKey(event)
  }))

  if (!open) return null
  return <PickerSurface ariaLabel="选择技能" onKeyDown={(event) => handleKey(event)}>
    {onBack ? <PickerHeader title="选择技能" onBack={onBack} /> : null}
    {!inlineQuery ? <PickerSearch autoFocus aria-controls="agui-skill-options" aria-expanded={open} value={query} onChange={(event) => { onQueryChange(event.target.value); navigation.resetActiveIndex() }} placeholder="搜索技能名称或用途" aria-label="搜索技能" trailing={<>已选 {selected.length}/1</>} /> : null}
    <div id="agui-skill-options" className="max-h-60 overflow-y-auto p-1" role="listbox" aria-label="技能列表" aria-activedescendant={filtered[navigation.activeIndex] ? `agui-skill-${filtered[navigation.activeIndex].id}` : undefined}>
      {filtered.map((skill, index) => {
        const checked = selected.some((item) => item.id === skill.id)
        return <PickerOption id={`agui-skill-${skill.id}`} key={skill.id} active={index === navigation.activeIndex} selected={checked} title={skill.description} onClick={() => onToggle(skill)}>
          <span className={cn('grid size-5 shrink-0 place-items-center rounded border border-border bg-white', checked && 'border-positive bg-positive text-white')}>
            {checked ? <Check size={13} /> : <Sparkles size={12} />}
          </span>
          <span className="min-w-0 flex-1"><span className="block truncate text-xs">{skill.name}</span><span className="block truncate text-[10px] text-muted">{skill.description}</span></span>
        </PickerOption>
      })}
      {!filtered.length ? <div className="px-3 py-5 text-center text-xs text-muted">没有匹配的技能</div> : null}
    </div>
  </PickerSurface>
})
