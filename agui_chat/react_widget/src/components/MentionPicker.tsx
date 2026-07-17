import {
  ArrowLeft, AtSign, Database, Filter, FolderTree, Menu, SlidersHorizontal
} from 'lucide-react'
import {
  forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState
} from 'react'
import type { KeyboardEvent } from 'react'
import type {
  HostBridge, MentionAction, MentionCandidate, MentionKind, MentionReference, MentionScope
} from '../types'
import { cn } from '../lib'

const MAX_MENTIONS = 5
const PAGE_ACTIONS = new Set<MentionAction>(['open', 'create', 'view', 'edit', 'apply'])
const ACTION_LABELS: Record<MentionAction, string> = {
  read: '引用数据', open: '打开', create: '新建', view: '打开查看', edit: '打开编辑', apply: '应用'
}

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
  selected: MentionReference[]
  recent: MentionReference[]
  hostBridge: HostBridge
  onSelect: (reference: MentionReference) => void
  onClose: () => void
}

type PickerView = 'home' | 'results' | 'models' | 'actions'

const CATEGORIES: Array<{ scope: Exclude<MentionScope, 'all'>; label: string; detail: string }> = [
  { scope: 'menu', label: '菜单', detail: '打开菜单或新建记录' },
  { scope: 'record', label: '记录', detail: '引用、查看或编辑记录' },
  { scope: 'saved_filter', label: '收藏', detail: '应用个人或共享收藏' },
  { scope: 'current_filter', label: '当前筛选', detail: '复用当前页面筛选' }
]

function MentionIcon({ kind }: { kind: MentionKind }) {
  if (kind === 'menu') return <Menu size={15} />
  if (kind === 'record') return <Database size={15} />
  if (kind === 'saved_filter') return <Filter size={15} />
  return <SlidersHorizontal size={15} />
}

function CategoryIcon({ scope }: { scope: Exclude<MentionScope, 'all'> }) {
  return <MentionIcon kind={scope} />
}

function conflictReason(
  candidate: Pick<MentionCandidate, 'resourceKey'>,
  action: MentionAction | null,
  selected: MentionReference[]
): string {
  if (selected.length >= MAX_MENTIONS) return '已达到 5 个引用上限'
  if (selected.some((item) => item.resourceKey === candidate.resourceKey)) return '已引用此对象'
  if (action && PAGE_ACTIONS.has(action) && selected.some((item) => item.pageAction)) {
    return '本条消息已有页面动作'
  }
  return ''
}

export const MentionPicker = forwardRef<MentionPickerHandle, MentionPickerProps>(function MentionPicker({
  open, query, selected, recent, hostBridge, onSelect, onClose
}, ref) {
  const [view, setView] = useState<PickerView>('home')
  const [scope, setScope] = useState<MentionScope>('all')
  const [modelScope, setModelScope] = useState('')
  const [modelQuery, setModelQuery] = useState('')
  const [models, setModels] = useState<Array<{ model: string; label: string }>>([])
  const [candidates, setCandidates] = useState<MentionCandidate[]>([])
  const [pending, setPending] = useState<MentionCandidate | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [binding, setBinding] = useState(false)
  const [error, setError] = useState('')
  const requestNumber = useRef(0)
  const normalizedQuery = query.query.trim()

  useEffect(() => {
    if (!open) {
      requestNumber.current += 1
      return
    }
    setView(normalizedQuery ? 'results' : 'home')
    setScope('all')
    setModelScope('')
    setPending(null)
    setCandidates([])
    setError('')
    setActiveIndex(0)
  }, [open])

  useEffect(() => {
    if (!open) return
    if (normalizedQuery && view === 'home') {
      setView('results')
      setScope('all')
    } else if (!normalizedQuery && view === 'results' && scope === 'all') {
      setView('home')
    }
    setActiveIndex(0)
  }, [normalizedQuery])

  useEffect(() => {
    const canBrowseEmpty = scope === 'menu' || scope === 'saved_filter' || scope === 'current_filter'
    const shouldSearch = open && (
      view === 'models' || view === 'results' && (normalizedQuery.length >= 2 || canBrowseEmpty)
    )
    const currentRequest = ++requestNumber.current
    setCandidates([])
    setError('')
    setActiveIndex(0)
    if (!shouldSearch || !hostBridge.searchMentions) {
      setLoading(false)
      return
    }
    setLoading(true)
    const timer = window.setTimeout(() => {
      const search = hostBridge.searchMentions!({
        query: view === 'models' ? '' : normalizedQuery,
        scope: view === 'models' ? 'record' : scope,
        modelScope: modelScope || undefined
      })
      Promise.resolve(search).then((result) => {
        if (currentRequest !== requestNumber.current) return
        if (result?.ok === false) {
          setError(result.error || result.code || '对象搜索失败')
          return
        }
        setCandidates(result?.candidates || [])
        setModels((result?.modelScopes || []).slice(0, 100))
      }, (reason) => {
        if (currentRequest !== requestNumber.current) return
        setError((reason as Error)?.message || '对象搜索失败')
      }).finally(() => {
        if (currentRequest === requestNumber.current) setLoading(false)
      })
    }, view === 'models' || !normalizedQuery ? 0 : 300)
    return () => window.clearTimeout(timer)
  }, [hostBridge, modelScope, normalizedQuery, open, scope, view])

  const filteredModels = useMemo(() => {
    const needle = modelQuery.trim().toLocaleLowerCase()
    return models.filter((item) =>
      !needle || item.label.toLocaleLowerCase().includes(needle) || item.model.includes(needle)
    )
  }, [modelQuery, models])

  const bind = async (candidate: MentionCandidate, action: MentionAction) => {
    const reason = conflictReason(candidate, action, selected)
    if (reason || binding || !hostBridge.bindMention) {
      if (reason) setError(reason)
      return
    }
    setBinding(true)
    setError('')
    try {
      const result = await Promise.resolve(hostBridge.bindMention({
        candidateToken: candidate.candidateToken,
        action
      }))
      if (!result?.ok || !result.reference) {
        setError(result?.error || result?.code || '对象绑定失败')
        return
      }
      onSelect(result.reference)
    } catch (reason) {
      setError((reason as Error)?.message || '对象绑定失败')
    } finally {
      setBinding(false)
    }
  }

  const selectCandidate = (candidate: MentionCandidate) => {
    const allBlocked = candidate.actions.every((action) => conflictReason(candidate, action, selected))
    if (allBlocked) return
    if (candidate.actions.length === 1) {
      void bind(candidate, candidate.actions[0])
      return
    }
    setPending(candidate)
    setView('actions')
    setActiveIndex(0)
  }

  const goBack = () => {
    setError('')
    setActiveIndex(0)
    if (view === 'actions') {
      setPending(null)
      setView('results')
    } else if (view === 'models' || scope !== 'all') {
      setScope('all')
      setModelScope('')
      setView(normalizedQuery ? 'results' : 'home')
    } else {
      onClose()
    }
  }

  const optionCount = view === 'actions'
    ? pending?.actions.length || 0
    : view === 'models'
      ? filteredModels.length
      : view === 'results'
        ? candidates.length
        : recent.length + CATEGORIES.length

  const activate = (index: number) => {
    if (view === 'actions' && pending?.actions[index]) {
      void bind(pending, pending.actions[index])
    } else if (view === 'models' && filteredModels[index]) {
      setModelScope(filteredModels[index].model)
      setScope('record')
      setView('results')
      setActiveIndex(0)
    } else if (view === 'results' && candidates[index]) {
      selectCandidate(candidates[index])
    } else if (view === 'home') {
      if (index < recent.length) {
        const reference = recent[index]
        if (!conflictReason(reference, reference.action, selected)) onSelect(reference)
      } else {
        const category = CATEGORIES[index - recent.length]
        if (!category) return
        setScope(category.scope)
        setActiveIndex(0)
        setView(category.scope === 'record' ? 'models' : 'results')
      }
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
      setActiveIndex((value) => optionCount ? (value + delta + optionCount) % optionCount : 0)
      return true
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      activate(activeIndex)
      return true
    }
    return false
  }

  useImperativeHandle(ref, () => ({
    handleKey: (event) => handleKey(event)
  }))

  if (!open) return null
  return <div
    className="agui-picker absolute bottom-full left-0 right-0 z-40 mb-1 max-h-80 overflow-hidden rounded-md border border-zinc-700 bg-zinc-900 text-zinc-200 shadow-xl"
    role="dialog"
    aria-label="选择 Odoo 引用"
  >
    {view !== 'home' ? <div className="flex h-9 items-center gap-2 border-b border-zinc-700 px-2">
      <button type="button" className="grid size-7 place-items-center text-zinc-400 hover:bg-zinc-800 hover:text-white" aria-label="返回" onPointerDown={(event) => event.preventDefault()} onClick={goBack}>
        <ArrowLeft size={15} />
      </button>
      <span className="min-w-0 flex-1 truncate text-xs font-medium">
        {view === 'actions' ? pending?.label : view === 'models' ? '选择记录模型' : CATEGORIES.find((item) => item.scope === scope)?.label || '全部引用'}
      </span>
    </div> : null}
    <div className="max-h-72 overflow-y-auto p-1" role="listbox" aria-busy={loading}>
      {view === 'home' ? <>
        {recent.length ? <div className="pb-1">
          <div className="px-2 py-1 text-[10px] font-medium uppercase text-zinc-500">最近引用</div>
          {recent.map((reference, index) => {
            const reason = conflictReason(reference, reference.action, selected)
            return <button key={reference.id} type="button" role="option" aria-selected={index === activeIndex} disabled={!!reason} className={cn('flex h-10 w-full items-center gap-2 px-2 text-left text-xs hover:bg-zinc-800 disabled:opacity-40', index === activeIndex && 'bg-zinc-800 text-white')} onPointerDown={(event) => event.preventDefault()} onClick={() => activate(index)} title={reason || reference.detail}>
              <MentionIcon kind={reference.kind} />
              <span className="min-w-0 flex-1 truncate">{reference.label}</span>
              <span className="text-[10px] text-zinc-500">{ACTION_LABELS[reference.action]}</span>
            </button>
          })}
        </div> : null}
        <div className="border-t border-zinc-800 pt-1">
          {CATEGORIES.map((category, categoryIndex) => {
            const index = recent.length + categoryIndex
            return <button key={category.scope} type="button" role="option" aria-selected={index === activeIndex} className={cn('flex h-11 w-full items-center gap-2 px-2 text-left hover:bg-zinc-800', index === activeIndex && 'bg-zinc-800')} onPointerDown={(event) => event.preventDefault()} onClick={() => activate(index)}>
              <span className="grid size-7 place-items-center text-zinc-400"><CategoryIcon scope={category.scope} /></span>
              <span className="min-w-0 flex-1"><span className="block text-xs text-zinc-100">{category.label}</span><span className="block truncate text-[10px] text-zinc-500">{category.detail}</span></span>
            </button>
          })}
        </div>
      </> : null}
      {view === 'models' ? <>
        <div className="sticky top-0 bg-zinc-900 p-1">
          <input autoFocus value={modelQuery} onChange={(event) => { setModelQuery(event.target.value); setActiveIndex(0) }} onKeyDown={(event) => handleKey(event)} className="h-8 w-full border border-zinc-700 bg-zinc-950 px-2 text-xs text-white outline-none focus:border-zinc-500" placeholder="搜索模型" aria-label="搜索记录模型" />
        </div>
        {filteredModels.map((model, index) => <button key={model.model} type="button" role="option" aria-selected={index === activeIndex} className={cn('flex h-11 w-full items-center gap-2 px-2 text-left hover:bg-zinc-800', index === activeIndex && 'bg-zinc-800')} onClick={() => activate(index)}>
          <FolderTree size={15} className="shrink-0 text-zinc-400" />
          <span className="min-w-0 flex-1"><span className="block truncate text-xs">{model.label}</span><span className="block truncate text-[10px] text-zinc-500">{model.model}</span></span>
        </button>)}
      </> : null}
      {view === 'results' ? <>
        {loading ? Array.from({ length: 4 }).map((_, index) => <div key={index} className="flex h-11 animate-pulse items-center gap-2 px-2"><span className="size-6 bg-zinc-800"/><span className="h-3 flex-1 bg-zinc-800"/></div>) : null}
        {!loading && candidates.map((candidate, index) => {
          const reasons = candidate.actions.map((action) => conflictReason(candidate, action, selected)).filter(Boolean)
          const disabled = reasons.length === candidate.actions.length
          return <button key={candidate.candidateToken} type="button" role="option" aria-selected={index === activeIndex} disabled={disabled || binding} className={cn('flex min-h-11 w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-zinc-800 disabled:opacity-40', index === activeIndex && 'bg-zinc-800')} onPointerDown={(event) => event.preventDefault()} onClick={() => selectCandidate(candidate)} title={disabled ? reasons[0] : candidate.detail}>
            <span className="grid size-7 shrink-0 place-items-center text-zinc-400"><MentionIcon kind={candidate.kind} /></span>
            <span className="min-w-0 flex-1"><span className="block truncate text-xs text-zinc-100">{candidate.label}</span><span className="block truncate text-[10px] text-zinc-500">{disabled ? reasons[0] : candidate.detail}</span></span>
          </button>
        })}
        {!loading && !candidates.length ? <div className="px-3 py-5 text-center text-xs text-zinc-500">{error || (scope === 'record' && normalizedQuery.length < 2 ? '记录搜索至少需要 2 个字符' : '没有匹配的对象')}</div> : null}
      </> : null}
      {view === 'actions' && pending ? pending.actions.map((action, index) => {
        const reason = conflictReason(pending, action, selected)
        return <button key={action} type="button" role="option" aria-selected={index === activeIndex} disabled={!!reason || binding} className={cn('flex h-10 w-full items-center justify-between px-3 text-left text-xs hover:bg-zinc-800 disabled:opacity-40', index === activeIndex && 'bg-zinc-800 text-white')} onPointerDown={(event) => event.preventDefault()} onClick={() => void bind(pending, action)}>
          <span>{ACTION_LABELS[action]}</span>{reason ? <span className="text-[10px] text-zinc-500">{reason}</span> : null}
        </button>
      }) : null}
    </div>
    {error && (candidates.length || view === 'actions') ? <div role="alert" className="border-t border-zinc-700 px-3 py-2 text-[11px] text-red-300">{error}</div> : null}
  </div>
})

export function mentionIcon(kind: MentionKind) {
  return <MentionIcon kind={kind} />
}

export { ACTION_LABELS, PAGE_ACTIONS }
