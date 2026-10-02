/**
 * 证据浏览器导航状态机（证据浏览器 v6）：纯状态、无 DOM，供视图层驱动。
 *
 * 三种状态严格分开：
 * - 核对任务（EvidenceTask）：顶层页签，持有独立导航历史与页面状态；
 * - 当前页面（EvidencePage）：历史栈条目，携带路径、预览选择、筛选、滚动；
 * - 预览选择（page.selected）：只影响摘要展示，不改路径与历史。
 *
 * 导航语义与 docs/superpowers/designs/report-editor-trace-ui/README.md 一致：
 * - 路径含目标对象时截短到该位置，不无限追加；
 * - 前进栈存在同对象同路径条目时复用（恢复筛选/滚动/预览），否则丢弃前进分支；
 * - 进入当前页面对象不追加历史；
 * - 关闭任务后激活最近使用的任务，没有任务时回到「报告正文」。
 */

export type EvidenceObjectKind = 'fact' | 'computation' | 'dataset' | 'chart' | 'subject'

/** 对象身份：报告与修订由客户端上下文固定，这里包含对象类型与对象键。 */
export interface EvidenceObjectRef {
  kind: EvidenceObjectKind
  key: string
  /** 事实对象需要 analysisId 才能定位。 */
  analysisId?: string
  /** 展示名（任务名、面包屑、节点文字）。 */
  label: string
}

export interface EvidencePage {
  ref: EvidenceObjectRef
  /** 探索路径：从任务起点（path[0] === 任务 root）到当前页。 */
  path: EvidenceObjectRef[]
  selected: EvidenceObjectRef | null
  collapsed: boolean
  showList: boolean
  graphView: boolean
  filter: string
  datasetCursors: (string | null)[]
  datasetPageIndex: number
  chartOffset: number
  columnWidths: Record<string, number>
  tableScroll: number
  scroll: number
  graphScroll: { left: number; top: number }
  graphScale: number
  graphPan: { x: number; y: number }
}

export interface EvidenceTask {
  key: string
  root: EvidenceObjectRef
  history: EvidencePage[]
  index: number
  /** 最近使用时间戳（关闭任务后的回退依据）。 */
  used: number
}

export const REPORT_TAB = 'report'

export function evidenceRefId(ref: EvidenceObjectRef): string {
  return `${ref.kind}:${ref.analysisId ? `${ref.analysisId}/` : ''}${ref.key}`
}

export function sameEvidenceRef(a: EvidenceObjectRef, b: EvidenceObjectRef): boolean {
  return evidenceRefId(a) === evidenceRefId(b)
}

function samePath(a: EvidenceObjectRef[], b: EvidenceObjectRef[]): boolean {
  return a.length === b.length && a.every((ref, index) => sameEvidenceRef(ref, b[index]))
}

/** 首次进入事实/计算页默认展开关系区，快照/图表/引用页默认收起。 */
function defaultCollapsed(kind: EvidenceObjectKind): boolean {
  return kind !== 'fact' && kind !== 'computation'
}

function makePage(ref: EvidenceObjectRef, path: EvidenceObjectRef[]): EvidencePage {
  return {
    ref,
    path,
    selected: null,
    collapsed: defaultCollapsed(ref.kind),
    showList: false,
    graphView: false,
    filter: '',
    datasetCursors: [null],
    datasetPageIndex: 0,
    chartOffset: 0,
    columnWidths: {},
    tableScroll: 0,
    scroll: 0,
    graphScroll: { left: 0, top: 0 },
    graphScale: 1,
    graphPan: { x: 0, y: 0 },
  }
}

export interface EvidenceStore {
  tasks: EvidenceTask[]
  active: string
}

export function createEvidenceState(store: EvidenceStore = { tasks: [], active: REPORT_TAB }) {
  const closedTasks: EvidenceTask[] = []
  let counter = store.tasks.reduce((max, task) => {
    const match = /^task-(\d+)$/.exec(task.key)
    return Math.max(max, match ? Number(match[1]) : 0)
  }, 0)
  let clock = store.tasks.reduce((max, task) => Math.max(max, task.used), 0)

  const currentTask = (): EvidenceTask | null =>
    store.active === REPORT_TAB ? null : (store.tasks.find((task) => task.key === store.active) ?? null)

  const currentPage = (): EvidencePage | null => {
    const task = currentTask()
    return task ? task.history[task.index] : null
  }

  const touch = (task: EvidenceTask) => {
    clock += 1
    task.used = clock
  }

  /** 开启或激活核对任务；同一对象身份去重，不因名称相同误合并。 */
  const openTask = (root: EvidenceObjectRef, options: { foreground?: boolean } = {}): EvidenceTask => {
    const existing = store.tasks.find((task) => sameEvidenceRef(task.root, root))
    if (existing) {
      if (options.foreground !== false) {
        touch(existing)
        store.active = existing.key
      }
      return existing
    }
    counter += 1
    const task: EvidenceTask = {
      key: `task-${counter}`,
      root,
      history: [makePage(root, [root])],
      index: 0,
      used: ++clock,
    }
    store.tasks.push(task)
    // 后台打开不抢焦点；已有任务被显式打开时激活。
    if (options.foreground !== false) store.active = task.key
    return task
  }

  const switchTask = (key: string) => {
    if (key !== REPORT_TAB && !store.tasks.some((task) => task.key === key)) return
    store.active = key
    const task = currentTask()
    if (task) touch(task)
  }

  const closeTask = (key: string) => {
    const position = store.tasks.findIndex((task) => task.key === key)
    if (position < 0) return
    const wasActive = store.active === key
    const [closed] = store.tasks.splice(position, 1)
    closedTasks.push(closed)
    if (!wasActive) return
    const fallback = store.tasks.reduce<EvidenceTask | null>(
      (latest, task) => (latest === null || task.used > latest.used ? task : latest),
      null,
    )
    store.active = fallback ? fallback.key : REPORT_TAB
  }

  const restoreTask = (): EvidenceTask | null => {
    const closed = closedTasks.pop()
    if (!closed) return null
    const existing = store.tasks.find((task) => sameEvidenceRef(task.root, closed.root))
    const task = existing ?? closed
    if (!existing) store.tasks.push(task)
    touch(task)
    store.active = task.key
    return task
  }

  const reorderTask = (key: string, targetIndex: number) => {
    const from = store.tasks.findIndex((task) => task.key === key)
    if (from < 0) return
    const bounded = Math.max(0, Math.min(targetIndex, store.tasks.length - 1))
    if (from === bounded) return
    const [task] = store.tasks.splice(from, 1)
    store.tasks.splice(bounded, 0, task)
  }

  /** 当前任务内导航：路径截短、前进栈复用、进入当前页不追加历史。 */
  const navigate = (ref: EvidenceObjectRef): EvidencePage | null => {
    const task = currentTask()
    const page = currentPage()
    if (!task || !page) return null
    const existing = page.path.findIndex((item) => sameEvidenceRef(item, ref))
    const path = existing >= 0 ? page.path.slice(0, existing + 1) : [...page.path, ref]
    if (sameEvidenceRef(page.ref, ref) && samePath(page.path, path)) return page
    const reusable = task.history.findIndex(
      (entry, index) => index > task.index && sameEvidenceRef(entry.ref, ref) && samePath(entry.path, path),
    )
    if (reusable >= 0) {
      // 复用前进栈条目：保留其后分支，返回时筛选/滚动/预览现场不丢。
      task.index = reusable
      return task.history[task.index]
    }
    const remembered = task.history.slice(0, task.index + 1).reverse().find(
      (entry) => sameEvidenceRef(entry.ref, ref) && samePath(entry.path, path),
    )
    const next = remembered ? {
      ...remembered, ref, path,
      graphScroll: { ...remembered.graphScroll }, graphPan: { ...remembered.graphPan },
      datasetCursors: [...remembered.datasetCursors], columnWidths: { ...remembered.columnWidths },
    } : makePage(ref, path)
    task.history = [...task.history.slice(0, task.index + 1), next]
    task.index = task.history.length - 1
    return task.history[task.index]
  }

  const back = (): EvidencePage | null => {
    const task = currentTask()
    if (!task || task.index <= 0) return null
    task.index -= 1
    return task.history[task.index]
  }

  const forward = (): EvidencePage | null => {
    const task = currentTask()
    if (!task || task.index >= task.history.length - 1) return null
    task.index += 1
    return task.history[task.index]
  }

  /** 更新当前页的现场状态（筛选、预览、收起、滚动等）。 */
  const updatePage = (patch: Partial<Omit<EvidencePage, 'ref' | 'path'>>): EvidencePage | null => {
    const page = currentPage()
    if (!page) return null
    Object.assign(page, patch)
    return page
  }

  return {
    store,
    currentTask,
    currentPage,
    openTask,
    switchTask,
    closeTask,
    closedTasks,
    restoreTask,
    reorderTask,
    navigate,
    back,
    forward,
    updatePage,
  }
}

export type EvidenceState = ReturnType<typeof createEvidenceState>
