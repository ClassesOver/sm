import { LifecycleService, LifecycleStages } from '@univerjs/core'
import { IRenderManagerService } from '@univerjs/engine-render'

type Runtime = {
  univer: { __getInjector?: () => { has(token: unknown): boolean; get<T>(token: unknown): T } }
  univerAPI: { getActiveWorkbook?: () => { getWorkbook?(): unknown } | null }
}

/** 滚动等原生控制器在Rendered才注册，不能用文件解析完成代替可交互。 */
export async function waitForWorkbookRendered(runtime: Runtime, disposed: () => boolean): Promise<void> {
  const injector = runtime.univer.__getInjector?.()
  if (!injector?.has(IRenderManagerService)) return
  const core = runtime.univerAPI.getActiveWorkbook?.()?.getWorkbook?.()
  await injector.get<LifecycleService>(LifecycleService).onStage(LifecycleStages.Rendered)
  if (disposed() || runtime.univerAPI.getActiveWorkbook?.()?.getWorkbook?.() !== core) {
    throw new Error('工作簿身份已变化，请重新打开')
  }
}

/** 拦用户输入但保留focus事件，避免inert破坏Univer hidden editor初始化。 */
export function installWorkbookLoadingLock(grid: HTMLElement, loading: () => boolean) {
  const types = ['pointerdown', 'click', 'keydown', 'beforeinput', 'paste'] as const
  const block = (event: Event) => {
    if (!loading()) return
    event.preventDefault()
    event.stopImmediatePropagation()
  }
  types.forEach(type => grid.addEventListener(type, block, true))
  return { dispose() { types.forEach(type => grid.removeEventListener(type, block, true)) } }
}
