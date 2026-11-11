import { expect, it, vi } from 'vitest'
import { createPageBreakPreviewController } from './workbook-page-break-controller'
import type { PageBreakPreviewPlan } from './workbook-page-break-preview'
const ready = { status: 'ready', printPlan: {}, layers: [], issues: ['仅显示前60页'] } as unknown as PageBreakPreviewPlan
it('keeps independent per-worksheet modes and disposes rendered layers on refresh, switching and shutdown', async () => {
  const a = { getSheet: () => coreA }, b = { getSheet: () => coreB }, coreA = {}, coreB = {}
  let target = a; const release = vi.fn(), render = vi.fn(() => ({ dispose: release }))
  const controller = createPageBreakPreviewController({ target: () => target, plan: async () => ready, render })
  await controller.setVisible(true); expect(controller.state()).toMatchObject({ active: true, issues: ['仅显示前60页'] })
  await controller.refresh(); expect(release).toHaveBeenCalledOnce()
  target = b; await controller.refresh(); expect(controller.state().active).toBe(false)
  await controller.setVisible(true); target = a; await controller.refresh(); expect(controller.state().active).toBe(true)
  await controller.setVisible(false); expect(controller.state().active).toBe(false)
  controller.dispose(); expect(release).toHaveBeenCalledTimes(4)
})
it('ignores stale plans and failures after switch or dispose and reports current unavailable plans honestly', async () => {
  const core = {}, target = { getSheet: () => core }; let finish!: (value: PageBreakPreviewPlan) => void
  const render = vi.fn(() => ({ dispose() {} })), plan = vi.fn().mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValue({ status: 'unavailable', reason: '预算不足' })
  const controller = createPageBreakPreviewController({ target: () => target, plan, render })
  const old = controller.setVisible(true); await controller.setVisible(false); finish(ready); await old
  expect(render).not.toHaveBeenCalled()
  await controller.setVisible(true); expect(controller.state()).toMatchObject({ active: false, reason: '预算不足' })
  controller.dispose(); await controller.setVisible(true); expect(plan).toHaveBeenCalledTimes(2)
})
it('retains normal view after a render failure and releases stale rendering', async () => {
  const core = {}, target = { getSheet: () => core }
  const controller = createPageBreakPreviewController({ target: () => target, plan: async () => ready, render() { throw Error('浮层注册失败') } })
  await controller.setVisible(true); expect(controller.state()).toMatchObject({ active: false, reason: '浮层注册失败' })
  controller.dispose()
})
