import type { FormulaTraceKind, FormulaTracePlan } from './workbook-formula-trace'
interface Disposable { dispose(): void }
let nextController = 0
/** 仅持有会话浮层；调用期间真实worksheet改变时丢弃，失效后不保留旧依赖坐标。 */
export function createFormulaTraceController<T extends { getSheet(): object }>(options: {
  target(): T | null
  plan(target: T, kind: FormulaTraceKind): FormulaTracePlan
  render(target: T, plan: FormulaTracePlan, prefix: string): Disposable
  changed?(): void
}) {
  let disposed = false, core: object | undefined, generation = 0, count = 0
  const layers: Disposable[] = [], id = ++nextController
  const clear = () => { generation++; for (const layer of layers.splice(0).reverse()) { try { layer.dispose() } catch { /* 已销毁的工作表仍需释放其余句柄。 */ } }; core = undefined; count = 0; options.changed?.() }
  return {
    state: () => ({ active: layers.length > 0 }),
    trace(kind: FormulaTraceKind) {
      if (disposed) return
      const target = options.target()
      if (!target) return '工作表视图尚未就绪。'
      if (core && core !== target.getSheet()) clear()
      core = target.getSheet()
      const current = ++generation, plan = options.plan(target, kind)
      if (disposed || current !== generation || options.target()?.getSheet() !== core) return '工作表已变化，请重新追踪。'
      const added = plan.arrows.length + plan.highlights.length
      if (!added) return plan.message
      if (count + added > 200) throw new Error('追踪累计超过 200 个浮层，请先移除箭头。')
      const layer = options.render(target, plan, `formula-trace-${id}-${current}`)
      if (disposed || current !== generation || options.target()?.getSheet() !== core) { layer.dispose(); return '工作表已变化，请重新追踪。' }
      layers.push(layer); count += added; options.changed?.(); return plan.message
    },
    clear() { const active = layers.length > 0; clear(); return active ? '追踪箭头已移除。' : '没有追踪箭头。' },
    invalidate() { const active = layers.length > 0; if (active || core) clear(); return active },
    syncTarget() { if (core && core !== options.target()?.getSheet()) clear() },
    dispose() { disposed = true; clear() },
  }
}
