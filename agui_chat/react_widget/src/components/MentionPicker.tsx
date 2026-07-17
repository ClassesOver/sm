import {
  ArrowLeft, AtSign, Database, Eye, FolderTree, Menu, Pencil, Plus, Sparkles
} from 'lucide-react'
import {
  forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState
} from 'react'
import type { KeyboardEvent } from 'react'
import type {
  HostBridge, MentionAction, MentionCandidate, MentionKind, MentionReference, MentionScope
} from '../types'
import { cn } from '../lib'
import { PickerSearch } from './PickerSearch'

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
  workspaceReferenceCount: number
  hostBridge: HostBridge
  onSelect: (reference: MentionReference) => void
  onOpenSkills: () => void
  onClose: () => void
}

type PickerView = 'home' | 'results' | 'models' | 'actions'
const CATEGORIES = [
  { scope: 'menu', label: '菜单', detail: '按完整路径打开菜单，或直接进入新建' },
  { scope: 'record', label: '业务记录', detail: '查找客户、订单、合同等具体业务记录' },
  { scope: 'skill', label: '技能', detail: '选择适合当前任务的专业能力' }
] as const

function MentionIcon({ kind }: { kind: MentionKind }) {
  return kind === 'menu' ? <Menu size={15} /> : <Database size={15} />
}

function CategoryIcon({ scope }: { scope: typeof CATEGORIES[number]['scope' ] }) {
  return scope === 'skill' ? <Sparkles size={15} /> : <MentionIcon kind={scope} />
}

function ActionIcon({ action }: { action: MentionAction }) {
  if (action === 'create') return <Plus size={14} />
  if (action === 'view') return <Eye size={14} />
  if (action === 'edit') return <Pencil size={14} />
  return <AtSign size={14} />
}
function conflictReason(
  candidate: Pick<MentionCandidate, 'resourceKey'>,
  action: MentionAction | null,
  selected: MentionReference[],
  workspaceReferenceCount = 0
): string {
  if (selected.length + workspaceReferenceCount >= MAX_MENTIONS) return '已达到 5 个引用上限'
  if (selected.some((item) => item.resourceKey === candidate.resourceKey)) return '已引用此对象'
  if (action && PAGE_ACTIONS.has(action) && selected.some((item) => item.pageAction)) {
    return '本条消息已有页面动作'
  }
  return ''
}

export const MentionPicker = forwardRef<MentionPickerHandle, MentionPickerProps>(function MentionPicker({
  open, query, selected, workspaceReferenceCount, hostBridge, onSelect, onOpenSkills, onClose
}, ref) {
  const [view, setView] = useState<PickerView>('home')
  const [scope, setScope] = useState<MentionScope>('all')
  const [modelScope, setModelScope] = useState('')
  const [modelQuery, setModelQuery] = useState('')
  const [searchText, setSearchText] = useState(query.query)
  const [models, setModels] = useState<Array<{ model: string; label: string }>>([])
  const [candidates, setCandidates] = useState<MentionCandidate[]>([])
  const [pending, setPending] = useState<MentionCandidate | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [binding, setBinding] = useState(false)
  const [error, setError] = useState('')
  const requestNumber = useRef(0)
  const normalizedQuery = searchText.trim()
  useEffect(() => setSearchText(query.query), [query.query])


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
    const canBrowseEmpty = scope === 'menu'
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
        setCandidates((result?.candidates || []).filter((item) => item.kind === 'record' || item.kind === 'menu'))
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
    const reason = conflictReason(candidate, action, selected, workspaceReferenceCount)
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
    const allBlocked = candidate.actions.every((action) => conflictReason(candidate, action, selected, workspaceReferenceCount))
    if (allBlocked) return
    const defaultAction = candidate.kind === 'record' ? 'read' : 'open'
    if (candidate.actions.includes(defaultAction)) {
      void bind(candidate, defaultAction)
      return
    }
    void bind(candidate, candidate.actions[0])
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
        : CATEGORIES.length

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
      const category = CATEGORIES[index]
      if (!category) return
      if (category.scope === 'skill') {
        onOpenSkills()
        return
      }
      setSearchText('')

      setScope(category.scope)
      setActiveIndex(0)
      setView(category.scope === 'record' ? 'models' : 'results')
    }
  }
  const activeOptionId = view === 'home' ? `agui-mention-category-${CATEGORIES[activeIndex]?.scope || 'none'}` : view === 'models' ? `agui-mention-model-${filteredModels[activeIndex]?.model || 'none'}` : view === 'results' ? `agui-mention-candidate-${candidates[activeIndex]?.candidateToken || 'none'}` : `agui-mention-action-${pending?.actions[activeIndex] || 'none'}`


  const handleKey = (event: KeyboardEvent<HTMLElement>): boolean => {
    if (!open || event.nativeEvent.isComposing) return false
    if (event.key === 'Escape') {
      event.preventDefault()
      goBack()
      return true
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      goBack()
      return true
    }
    if (event.key === 'ArrowRight' && view === 'results' && candidates[activeIndex]?.actions.length > 1) {
      event.preventDefault()
      setPending(candidates[activeIndex])
      setView('actions')
      setActiveIndex(0)
      return true
    }
    if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      setActiveIndex(event.key === 'Home' ? 0 : Math.max(0, optionCount - 1))
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
    className="agui-picker absolute bottom-full left-0 z-40 mb-2 w-full max-w-md overflow-hidden rounded-md border border-border/70 bg-white text-secondary shadow-[0_12px_32px_rgba(15,23,42,0.14)]"
    role="dialog" onKeyDown={(event) => handleKey(event)}
    aria-label="添加到对话"
  >
    <div className="flex h-9 items-center gap-2 border-b border-border px-2">
      {view !== 'home' ? <button type="button" className="grid size-7 place-items-center rounded-md border-0 bg-background-secondary text-secondary shadow-none transition-colors hover:bg-accent hover:text-primary" aria-label="返回" onPointerDown={(event) => event.preventDefault()} onClick={goBack}><ArrowLeft size={15} /></button> : <AtSign size={15} className="mx-1 text-muted" />}
      <span className="min-w-0 flex-1 truncate text-xs font-medium">{view === 'home' ? '添加到对话' : view === 'actions' ? pending?.label : view === 'models' ? '选择业务类型' : scope === 'menu' ? '选择菜单' : scope === 'record' ? '搜索业务记录' : '搜索结果'}</span>
    </div>
    <div id="agui-mention-options" className="max-h-72 overflow-y-auto p-1" role="listbox" aria-busy={loading} aria-activedescendant={activeOptionId}>
      {view === 'home' ? CATEGORIES.map((category, index) => <button id={`agui-mention-category-${category.scope}`} key={category.scope} type="button" role="option" aria-selected={index === activeIndex} className={cn('flex h-12 w-full items-center gap-2 border-l-2 border-l-transparent bg-white px-2 text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary', index === activeIndex && 'border-l-primary bg-background-secondary text-primary')} onPointerDown={(event) => event.preventDefault()} onClick={() => activate(index)}>
        <span className="grid size-7 shrink-0 place-items-center text-muted"><CategoryIcon scope={category.scope} /></span>
        <span className="min-w-0 flex-1"><span className="block text-xs text-primary">{category.label}</span><span className="block truncate text-[10px] text-muted">{category.detail}</span></span>
      </button>) : null}
      {view === 'models' ? <>
        <PickerSearch autoFocus value={modelQuery} onChange={(event) => { setModelQuery(event.target.value); setActiveIndex(0) }} placeholder="搜索业务类型" aria-label="搜索业务类型" />
        {filteredModels.map((model, index) => <button id={`agui-mention-model-${model.model}`} key={model.model} type="button" role="option" aria-selected={index === activeIndex} className={cn('group flex min-h-12 w-full items-center gap-2.5 border-l-2 border-l-transparent bg-white px-2.5 py-1.5 text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary', index === activeIndex && 'border-l-primary bg-background-secondary text-primary')} onClick={() => activate(index)}>
          <span className="grid size-7 shrink-0 place-items-center rounded-md bg-background-secondary text-muted transition-colors group-hover:bg-white group-hover:text-primary"><FolderTree size={15} /></span>
          <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-primary">{model.label}</span><span className="mt-0.5 block truncate text-[10px] text-muted">{model.model}</span></span>
          <ArrowLeft size={13} className="shrink-0 rotate-180 text-muted/60 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
        </button>)}
        {!filteredModels.length && !loading ? <div className="grid min-h-28 place-items-center px-4 text-center text-xs text-muted">没有匹配的业务类型</div> : null}
      </> : null}
      {view === 'results' ? <>
        <PickerSearch autoFocus value={searchText} onChange={(event) => { setSearchText(event.target.value); setActiveIndex(0) }} placeholder={scope === 'menu' ? '搜索菜单名称或完整路径' : scope === 'record' ? '搜索记录名称' : '搜索记录或菜单'} aria-label={scope === 'menu' ? '搜索菜单' : scope === 'record' ? '搜索业务记录' : '搜索记录或菜单'} />
        {loading ? Array.from({ length: 4 }).map((_, index) => <div key={index} className="flex h-11 animate-pulse items-center gap-2 px-2"><span className="size-6 bg-accent"/><span className="h-3 flex-1 bg-accent"/></div>) : null}
        {!loading && candidates.map((candidate, index) => {
          const reasons = candidate.actions.map((action) => conflictReason(candidate, action, selected, workspaceReferenceCount)).filter(Boolean)
          const disabled = reasons.length === candidate.actions.length
          return <button id={`agui-mention-candidate-${candidate.candidateToken}`} key={candidate.candidateToken} type="button" role="option" aria-selected={index === activeIndex} disabled={disabled || binding} className={cn('group flex min-h-12 w-full items-center gap-2.5 border-l-2 border-l-transparent bg-white px-2.5 py-1.5 text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary disabled:opacity-40', index === activeIndex && 'border-l-primary bg-background-secondary text-primary')} onPointerDown={(event) => event.preventDefault()} onClick={() => selectCandidate(candidate)} title={disabled ? reasons[0] : candidate.detail}>
            <span className="grid size-7 shrink-0 place-items-center rounded-md bg-background-secondary text-muted transition-colors group-hover:bg-white group-hover:text-primary"><MentionIcon kind={candidate.kind} /></span>
            <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-primary">{candidate.label}</span><span className="mt-0.5 block truncate text-[10px] text-muted">{disabled ? reasons[0] : candidate.detail}</span></span>
            {candidate.kind === 'menu' && candidate.actions.includes('create') ? <span className="grid size-6 shrink-0 place-items-center rounded-md bg-background-secondary text-muted transition-colors group-hover:bg-white group-hover:text-primary" title="支持新建"><Plus size={13} /></span> : candidate.actions.length > 1 ? <ArrowLeft size={13} className="shrink-0 rotate-180 text-muted/60 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" /> : null}
          </button>
        })}
        {!loading && !candidates.length ? <div className="px-3 py-5 text-center text-xs text-muted">{error || (scope === 'record' && normalizedQuery.length < 2 ? '输入至少 2 个字符开始搜索' : '没有匹配的对象')}</div> : null}
      </> : null}
      {view === 'actions' && pending ? pending.actions.map((action, index) => {
        const reason = conflictReason(pending, action, selected, workspaceReferenceCount)
        return <button id={`agui-mention-action-${action}`} key={action} type="button" role="option" aria-selected={index === activeIndex} disabled={!!reason || binding} className={cn('flex h-10 w-full items-center justify-between border-l-2 border-l-transparent bg-white px-3 text-left text-xs transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary disabled:opacity-40', index === activeIndex && 'border-l-primary bg-background-secondary text-primary')} onPointerDown={(event) => event.preventDefault()} onClick={() => void bind(pending, action)}>
          <span className="inline-flex items-center gap-2"><ActionIcon action={action} />{ACTION_LABELS[action]}</span>{reason ? <span className="text-[10px] text-muted">{reason}</span> : null}
        </button>
      }) : null}
    </div>
    {error && (candidates.length || view === 'actions') ? <div role="alert" className="border-t border-border px-3 py-2 text-[11px] text-destructive">{error}</div> : null}
  </div>
})

export function mentionIcon(kind: MentionKind) {
  return <MentionIcon kind={kind} />
}

export { ACTION_LABELS, PAGE_ACTIONS }
