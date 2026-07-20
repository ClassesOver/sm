import { Check, Sparkles } from 'lucide-react'
import { forwardRef, useEffect, useImperativeHandle, useMemo, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { AgentSkillOption, SelectedAgentSkill } from '../types'
import { cn } from '../lib'
import { PickerHeader } from './PickerHeader'
import { PickerSearch } from './PickerSearch'
import { PickerSurface } from './PickerSurface'

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
  const [activeIndex, setActiveIndex] = useState(0)
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return skills.slice(0, 50).filter((skill) =>
      !needle || skill.name.toLocaleLowerCase().includes(needle) ||
      skill.description.toLocaleLowerCase().includes(needle)
    )
  }, [query, skills])

  useEffect(() => setActiveIndex(0), [query, open])

  const handleKey = (event: KeyboardEvent<HTMLElement>): boolean => {
    if (!open || event.nativeEvent.isComposing) return false
    if (event.key === 'Escape') {
      event.preventDefault()
      const close = onBack || onClose
      close()
      return true
    }
    if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      setActiveIndex(event.key === 'Home' ? 0 : Math.max(0, filtered.length - 1))
      return true
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const delta = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex((value) => filtered.length
        ? (value + delta + filtered.length) % filtered.length
        : 0)
      return true
    }
    if ((event.key === 'Enter' || event.key === ' ') && filtered[activeIndex]) {
      event.preventDefault()
      onToggle(filtered[activeIndex])
      return true
    }
    return false
  }

  useImperativeHandle(ref, () => ({
    handleKey: (event) => handleKey(event)
  }))

  if (!open) return null
  return <PickerSurface ariaLabel="选择技能" onKeyDown={(event) => handleKey(event)}>
    {onBack ? <PickerHeader title="选择技能" onBack={onBack} /> : null}
    {!inlineQuery ? <PickerSearch autoFocus aria-controls="agui-skill-options" aria-expanded={open} value={query} onChange={(event) => { onQueryChange(event.target.value); setActiveIndex(0) }} placeholder="搜索技能名称或用途" aria-label="搜索技能" trailing={<>已选 {selected.length}/1</>} /> : null}
    <div id="agui-skill-options" className="max-h-60 overflow-y-auto p-1" role="listbox" aria-label="技能列表" aria-activedescendant={filtered[activeIndex] ? `agui-skill-${filtered[activeIndex].id}` : undefined}>
      {filtered.map((skill, index) => {
        const checked = selected.some((item) => item.id === skill.id)
        return <button id={`agui-skill-${skill.id}`} key={skill.id} type="button" role="option" aria-selected={checked} title={skill.description} className={cn('flex min-h-11 w-full items-center gap-2 border-l-2 border-l-transparent bg-white px-2 py-1.5 text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary', index === activeIndex && 'border-l-primary bg-background-secondary text-primary')} onClick={() => onToggle(skill)}>
          <span className={cn('grid size-5 shrink-0 place-items-center rounded border border-border bg-white', checked && 'border-positive bg-positive text-white')}>
            {checked ? <Check size={13} /> : <Sparkles size={12} />}
          </span>
          <span className="min-w-0 flex-1"><span className="block truncate text-xs">{skill.name}</span><span className="block truncate text-[10px] text-muted">{skill.description}</span></span>
        </button>
      })}
      {!filtered.length ? <div className="px-3 py-5 text-center text-xs text-muted">没有匹配的技能</div> : null}
    </div>
  </PickerSurface>
})
