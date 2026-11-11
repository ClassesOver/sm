import { expect, it, vi } from 'vitest'
import type { FormulaTracePlan } from './workbook-formula-trace'
import { createFormulaTraceController } from './workbook-formula-trace-controller'
it('accumulates read-only traces and clears all layers on invalidation, identity replacement and dispose', () => {
  let core = {}; const dispose = vi.fn(), plan = { arrows: [{from:{row:0,column:0},to:{row:1,column:1}}], highlights: [], issues: [], message: 'ok' }
  const controller = createFormulaTraceController({ target: () => ({ getSheet: () => core }), plan: () => plan, render: () => ({ dispose }) })
  expect(controller.trace('precedents')).toBe('ok'); controller.trace('dependents'); expect(controller.state().active).toBe(true)
  controller.invalidate(); expect(dispose).toHaveBeenCalledTimes(2); expect(controller.state().active).toBe(false)
  controller.trace('precedents'); core = {}; controller.syncTarget(); expect(dispose).toHaveBeenCalledTimes(3)
  controller.trace('precedents'); controller.dispose(); expect(dispose).toHaveBeenCalledTimes(4)
  expect(controller.trace('precedents')).toBeUndefined()
})

it('refuses a stale render target and does not install empty or excess traces', () => {
  let core = {}, replace = false; const dispose = vi.fn()
  const empty = { arrows: [], highlights: [], issues: [], message: 'empty' }
  let plan: FormulaTracePlan = empty
  const controller = createFormulaTraceController({ target: () => ({getSheet: () => core}), plan: () => plan, render: () => { if (replace) core = {}; return { dispose } } })
  expect(controller.trace('precedents')).toBe('empty'); expect(controller.state().active).toBe(false)
  plan = { ...empty, arrows: Array.from({length: 101}, () => ({from: {row: 0,column: 0},to: {row: 1,column: 1}})) }
  controller.trace('precedents')
  expect(() => controller.trace('precedents')).toThrow('200')
  controller.clear(); replace = true
  expect(controller.trace('precedents')).toContain('变化'); expect(dispose).toHaveBeenCalledTimes(2)
})
