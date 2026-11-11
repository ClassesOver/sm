import { expect, it, vi } from 'vitest'
import { Univer } from '@univerjs/core'
import { UniverFormulaEnginePlugin, IFunctionService, functionStatistical, type BaseFunction } from '@univerjs/engine-formula'
import { createIfsEmptySetExecutors, installIfsEmptySetFix } from './workbook-function-ifs'

function setup() {
  const univer = new Univer()
  univer.registerPlugin(UniverFormulaEnginePlugin)
  const service = univer.__getInjector().get(IFunctionService)
  const Builtin = functionStatistical.find(([, name]) => name === 'MINIFS')![0] as new (name: string) => BaseFunction
  const original = new Builtin('MINIFS')
  service.registerExecutors(original)
  return { univer, service, original }
}

it('restores originals, removes previously absent executors and cancels queued reinstallation', () => {
  vi.useFakeTimers()
  const { univer, service, original } = setup()
  service.unregisterExecutors('MAXIFS')
  const installed = installIfsEmptySetFix({ univer })
  try {
    expect(service.getExecutor('MINIFS')).not.toBe(original)
    expect(service.getExecutor('MAXIFS')).toBeDefined()
    installed.dispose(); vi.runOnlyPendingTimers()
    expect(service.getExecutor('MINIFS')).toBe(original)
    expect(service.getExecutor('MAXIFS')).toBeUndefined()
    const replacement = createIfsEmptySetExecutors().find(executor => executor.name === 'MINIFS')!
    service.registerExecutors(replacement); installed.dispose()
    expect(service.getExecutor('MINIFS')).toBe(replacement)
  } finally { installed.dispose(); univer.dispose(); vi.useRealTimers() }
})

it('reinstalls after the native bootstrap replaces an executor and restores the captured original', () => {
  vi.useFakeTimers()
  const { univer, service, original } = setup()
  const installed = installIfsEmptySetFix({ univer }), wrapped = service.getExecutor('MINIFS')
  try {
    service.registerExecutors(original); vi.runOnlyPendingTimers()
    expect(service.getExecutor('MINIFS')).toBe(wrapped)
    installed.dispose(); expect(service.getExecutor('MINIFS')).toBe(original)
  } finally { installed.dispose(); univer.dispose(); vi.useRealTimers() }
})

it('does not overwrite a later extension when this installation is disposed', () => {
  vi.useFakeTimers()
  const { univer, service } = setup(), installed = installIfsEmptySetFix({ univer })
  try {
    vi.runOnlyPendingTimers()
    const replacement = createIfsEmptySetExecutors().find(executor => executor.name === 'MINIFS')!
    service.registerExecutors(replacement)
    installed.dispose()
    expect(service.getExecutor('MINIFS')).toBe(replacement)
  } finally { installed.dispose(); univer.dispose(); vi.useRealTimers() }
})

it('supports headless hosts without an injector while preserving real injector failures', () => {
  expect(() => installIfsEmptySetFix({ univer: {} } as never).dispose()).not.toThrow()
  expect(() => installIfsEmptySetFix({ univer: { __getInjector: () => { throw new Error('injector failed') } } } as never)).toThrow('injector failed')
})

it('preserves an extension registered before the bootstrap reinstallation timer fires', () => {
  vi.useFakeTimers()
  const { univer, service } = setup(), installed = installIfsEmptySetFix({ univer })
  try {
    const replacement = createIfsEmptySetExecutors().find(executor => executor.name === 'MINIFS')!
    service.registerExecutors(replacement)
    vi.runOnlyPendingTimers()
    expect(service.getExecutor('MINIFS')).toBe(replacement)
    installed.dispose(); expect(service.getExecutor('MINIFS')).toBe(replacement)
  } finally { installed.dispose(); univer.dispose(); vi.useRealTimers() }
})
