import type { PageBreakPreviewPlan } from './workbook-page-break-preview'

interface Disposable { dispose(): void }
interface Target { getSheet(): object }
export interface PageBreakPreviewState { active: boolean; pending: boolean; issues: readonly string[]; reason?: string }

/** 工作表身份只管会话模式；异步plan与安装必须属于同一次、同一张真实工作表。 */
export function createPageBreakPreviewController<T extends Target>(options: {
  target(): T | null
  plan(target: T): Promise<PageBreakPreviewPlan>
  render(target: T, plan: Extract<PageBreakPreviewPlan, { status: 'ready' }>, idPrefix: string): Disposable
  changed?(): void
}) {
  const modes = new WeakSet<object>()
  let generation = 0, disposed = false, layer: Disposable | undefined
  let state: PageBreakPreviewState = { active: false, pending: false, issues: [] }
  const clear = () => { layer?.dispose(); layer = undefined }
  const refresh = async () => {
    if (disposed) return
    const target = options.target(), core = target?.getSheet(), current = ++generation
    clear()
    state = { active: false, pending: !!core && modes.has(core), issues: [] }; options.changed?.()
    if (!target || !core || !modes.has(core)) return
    const valid = () => !disposed && generation === current && options.target()?.getSheet() === core
    try {
      const plan = await options.plan(target)
      if (!valid()) return
      if (plan.status === 'unavailable') {
        modes.delete(core); state = { active: false, pending: false, issues: [], reason: plan.reason }
      } else {
        layer = options.render(target, plan, `page-break-preview-${controllerId}-${current}`)
        state = { active: true, pending: false, issues: plan.issues }
      }
    } catch (error) {
      if (!valid()) return
      modes.delete(core); state = { active: false, pending: false, issues: [], reason: (error as Error).message }
    }
    if (valid()) options.changed?.()
  }
  const controllerId = ++nextController
  return {
    state: () => state,
    refresh,
    async setVisible(visible: boolean) {
      if (disposed) return
      const core = options.target()?.getSheet()
      if (core) { if (visible) modes.add(core); else modes.delete(core) }
      await refresh()
    },
    dispose() { disposed = true; generation++; clear(); state = { active: false, pending: false, issues: [] } },
  }
}
let nextController = 0
