type Batch = { redos: any[]; undos: any[] }
type PasteMethod = 'paste' | 'pasteByCopyId' | 'legacyPaste' | 'rePasteWithPasteType'
type Clipboard = { getClipboardHooks(): any[]; addClipboardHook(hook: any): { dispose(): void } } & Partial<Record<PasteMethod, (...args: any[]) => any>>

// 官方服务先收集全部 hook 的计划，再执行；最后一个 hook 统一规划表头从属变更。
export function followTableHeaderPaste(clipboard: Clipboard, plan: (batch: Batch) => Batch, onRejected?: (message: string) => void, captureRePaste?: () => (() => void)): () => void {
  const restores: (() => void)[] = []
  const wrapped = new WeakSet<object>()
  let batch: Batch = { redos: [], undos: [] }
  const rejected = new WeakSet<object>()
  const finish = () => {
    try { return plan(batch) }
    catch (error) {
      if (!onRejected) throw error
      const failure = error instanceof Error ? error : new Error(String(error))
      rejected.add(failure); throw failure
    }
  }
  // 官方服务收集完整计划后才写入；在公共入口返回 false，避免原生粘贴事件产生未处理异常。
  if (onRejected) for (const key of ['paste', 'pasteByCopyId', 'legacyPaste', 'rePasteWithPasteType'] as const) {
    const original = clipboard[key]
    if (!original) continue
    const wrapped = function(this: unknown, ...args: any[]) {
      const restore = key === 'rePasteWithPasteType' ? captureRePaste?.() : undefined
      const reject = (error: unknown) => {
        if (!(error instanceof Error) || !rejected.has(error)) throw error
        rejected.delete(error); restore?.(); onRejected(error.message); return false
      }
      try {
        const result = original.apply(this, args)
        return result instanceof Promise ? result.catch(reject) : result
      } catch (error) { return reject(error) }
    }
    clipboard[key] = wrapped
    restores.push(() => { if (clipboard[key] === wrapped) clipboard[key] = original })
  }
  const follower = { id: 'native-table-header-paste', priority: Number.MAX_SAFE_INTEGER,
    onPasteCells: finish, onPastePlainText: finish,
    onBeforePaste() {
      batch = { redos: [], undos: [] }
      for (const hook of clipboard.getClipboardHooks()) {
        if (hook === follower || wrapped.has(hook)) continue
        wrapped.add(hook)
        for (const key of ['onPasteCells', 'onPastePlainText']) {
          const original = hook[key]
          if (typeof original !== 'function') continue
          const collect = function(this: unknown, ...args: any[]) {
            const result = original.apply(this, args)
            if (result) { batch.redos.push(...result.redos); batch.undos.push(...result.undos) }
            return result
          }
          hook[key] = collect
          restores.push(() => { if (hook[key] === collect) hook[key] = original })
        }
      }
    },
  }
  const registration = clipboard.addClipboardHook(follower)
  return () => { registration.dispose(); restores.forEach(restore => restore()) }
}
