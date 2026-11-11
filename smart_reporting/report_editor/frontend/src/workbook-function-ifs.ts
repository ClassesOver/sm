// 固定源 GenOffice f8c17004 apps/sheets/src/renderer/ifs-empty-set.ts；仅补运行时类型、headless宿主与生命周期归属保护。
/**
 * MINIFS/MAXIFS over an empty match set must return 0 (Excel semantics).
 * Univer's empty-set branch builds `ArrayValueObject.create('0')`, but the
 * string form is parsed as an array literal whose brace-stripping slice turns
 * '0' into '' — the cell renders blank. Wrap both executors and rewrite that
 * 1x1 empty-string artifact into a real 0.
 */
import {
  ArrayValueObject,
  BaseFunction,
  FUNCTION_NAMES_STATISTICAL,
  IFunctionService,
  NumberValueObject,
  functionStatistical,
} from '@univerjs/engine-formula'
import type { BaseValueObject } from '@univerjs/engine-formula'

import type { Univer } from '@univerjs/core'

type IfsRuntime = { univer?: { __getInjector?: Univer['__getInjector'] } }

interface ValueLike {
  isArray?(): boolean
  isString?(): boolean
  getValue(): unknown
  getRowCount?(): number
  getColumnCount?(): number
  getFirstCell?(): ValueLike
  getArrayValue?(): ValueLike[][]
}

function isEmptySetArtifact(value: ValueLike | undefined): boolean {
  if (!value?.isArray?.() || value.getRowCount?.() !== 1 || value.getColumnCount?.() !== 1) {
    return false
  }
  const cell = value.getFirstCell?.()
  return cell?.isString?.() === true && cell.getValue() === ''
}

export function fixIfsEmptySetResult(value: ValueLike): ValueLike {
  if (isEmptySetArtifact(value)) return NumberValueObject.create(0) as unknown as ValueLike
  if (!value?.isArray?.() || !value.getArrayValue) return value
  // Array-criteria expansion: each zero-match slot carries its own artifact.
  const rows = value.getArrayValue()
  if (!rows.some((row) => row.some(isEmptySetArtifact))) return value
  const mapped = rows.map((row) =>
    row.map((cell) =>
      isEmptySetArtifact(cell) ? (NumberValueObject.create(0) as unknown as ValueLike) : cell,
    ),
  )
  return ArrayValueObject.create({
    calculateValueList: mapped,
    rowCount: mapped.length,
    columnCount: mapped[0]?.length ?? 0,
    unitId: '',
    sheetId: '',
    row: 0,
    column: 0,
  } as unknown as Parameters<typeof ArrayValueObject.create>[0]) as unknown as ValueLike
}

function createExecutor(name: string): BaseFunction | null {
  const Builtin = functionStatistical.find(([, builtinName]) => builtinName === name)?.[0] as
    (new (functionName: string) => BaseFunction) | undefined
  if (!Builtin) return null
  class IfsWithEmptySetZero extends Builtin {
    override calculate(...variants: BaseValueObject[]): ReturnType<BaseFunction['calculate']> {
      return fixIfsEmptySetResult(super.calculate(...variants) as ValueLike) as ReturnType<
        BaseFunction['calculate']
      >
    }
  }
  return new IfsWithEmptySetZero(name)
}

export function createIfsEmptySetExecutors(): BaseFunction[] {
  return [FUNCTION_NAMES_STATISTICAL.MINIFS, FUNCTION_NAMES_STATISTICAL.MAXIFS]
    .map(createExecutor)
    .filter((executor): executor is BaseFunction => executor !== null)
}

export function installIfsEmptySetFix(runtime: IfsRuntime): { dispose(): void } {
  const injector = runtime.univer?.__getInjector?.()
  if (!injector) return { dispose() {} }
  const functionService = injector.get(IFunctionService)
  const executors = createIfsEmptySetExecutors()
  if (executors.length === 0) return { dispose() {} }
  const originals = executors.map(
    (executor) => functionService.getExecutor(executor.name) ?? undefined,
  )
  functionService.registerExecutors(...executors)
  let disposed = false
  const timer = setTimeout(() => {
    if (disposed) return
    const stale = executors.filter((executor, index) => {
      const current = functionService.getExecutor(executor.name)
      const Builtin = functionStatistical.find(([, name]) => name === executor.name)?.[0]
      // 原生初始化会重新登记 builtin；后装第三方执行器仍由其自身拥有。
      return current !== executor && (current === originals[index] || current?.constructor === Builtin)
    })
    if (stale.length > 0) functionService.registerExecutors(...stale)
  }, 0)
  return {
    dispose() {
      if (disposed) return
      disposed = true
      clearTimeout(timer)
      executors.forEach((executor, index) => {
        // 只撤销本安装仍拥有的执行器；不覆盖后装的同名扩展。
        if (functionService.getExecutor(executor.name) !== executor) return
        const original = originals[index]
        if (original) functionService.registerExecutors(original)
        else functionService.unregisterExecutors(executor.name)
      })
    },
  }
}
