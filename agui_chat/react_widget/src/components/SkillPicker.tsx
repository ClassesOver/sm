import { Check, Search, Sparkles } from 'lucide-react'
import { forwardRef, useImperativeHandle, useMemo, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { AgentSkillOption, SelectedAgentSkill } from '../types'
import { cn } from '../lib'

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
  onQueryChange: (query: string) => void
  onToggle: (skill: AgentSkillOption) => void
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
  open, query, skills, selected, onQueryChange, onToggle, onClose
}, ref) {
  const [activeIndex, setActiveIndex] = useState(0)
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return skills.slice(0, 50).filter((skill) =>
      !needle || skill.name.toLocaleLowerCase().includes(needle) ||
      skill.description.toLocaleLowerCase().includes(needle)
    )
  }, [query, skills])

  const handleKey = (event: KeyboardEvent<HTMLElement>): boolean => {
    if (!open || event.nativeEvent.isComposing) return false
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
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
    if (event.key === 'Enter' && filtered[activeIndex]) {
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
  return <div className="agui-picker absolute bottom-full left-0 right-0 z-40 mb-1 max-h-72 overflow-hidden rounded-md border border-zinc-700 bg-zinc-900 text-zinc-100 shadow-xl" role="dialog" aria-label="选择技能">
    <div className="flex h-10 items-center gap-2 border-b border-zinc-700 px-2">
      <Search size={14} className="text-zinc-500" />
      <input autoFocus className="min-w-0 flex-1 border-0 bg-transparent text-xs text-white outline-none placeholder:text-zinc-600" value={query} onChange={(event) => { onQueryChange(event.target.value); setActiveIndex(0) }} onKeyDown={(event) => handleKey(event)} placeholder="搜索技能" aria-label="搜索技能" />
      <span className="text-[10px] text-zinc-500">{selected.length}/3</span>
    </div>
    <div className="max-h-60 overflow-y-auto p-1" role="listbox">
      {filtered.map((skill, index) => {
        const checked = selected.some((item) => item.id === skill.id)
        const disabled = !checked && selected.length >= 3
        return <button key={skill.id} type="button" role="option" aria-selected={checked} disabled={disabled} className={cn('flex min-h-11 w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-zinc-800 disabled:opacity-40', index === activeIndex && 'bg-zinc-800')} onClick={() => onToggle(skill)}>
          <span className={cn('grid size-5 shrink-0 place-items-center border border-zinc-600', checked && 'border-emerald-500 bg-emerald-500 text-zinc-950')}>
            {checked ? <Check size={13} /> : <Sparkles size={12} />}
          </span>
          <span className="min-w-0 flex-1"><span className="block truncate text-xs">{skill.name}</span><span className="block truncate text-[10px] text-zinc-500">{skill.description}</span></span>
        </button>
      })}
      {!filtered.length ? <div className="px-3 py-5 text-center text-xs text-zinc-500">没有匹配的技能</div> : null}
    </div>
  </div>
})
