import type { IFunctionInfo } from '@univerjs/engine-formula'
import { useMemo, useState } from 'react'

import { loadHistory, pushHistory } from './workbook-function-history'
import {
  DEFAULT_RECENT_FUNCTIONS,
  findFunctionCallAtCaret,
  finishedFormula,
  RECENT_FUNCTIONS_KEY,
} from './workbook-function-arguments'
import type { FunctionArgumentsHost, FunctionTarget } from './workbook-function-runtime'
import { FunctionArgumentsDialog } from './workbook-function-arguments-dialog'
import type { FunctionSpec } from './workbook-function-catalog'
import { InsertFunctionDialog, useFunctionCatalog } from './workbook-function-catalog-dialog'

/// Excel's two-step Insert Function: the catalog, then Function Arguments.
/// Opened over a formula whose caret sits inside a call (the fx button on
/// `=SUM(A1:A3)`), the first step is skipped and that call is edited.

export function InsertFunctionFlow({
  functions,
  target,
  initialCategory,
  host,
  onClose,
}: {
  readonly functions: readonly IFunctionInfo[]
  readonly target: FunctionTarget
  readonly initialCategory: string
  readonly host: FunctionArgumentsHost
  readonly onClose: () => void
}): React.JSX.Element {
  const catalog = useFunctionCatalog(functions)
  const span = useMemo(
    () => (target.formula === '' ? null : findFunctionCallAtCaret(target.formula, target.caret)),
    [target],
  )
  const [recent, setRecent] = useState(() => {
    const stored = loadHistory(globalThis.localStorage, RECENT_FUNCTIONS_KEY)
    return stored.length > 0 ? stored : [...DEFAULT_RECENT_FUNCTIONS]
  })
  const [picked, setPicked] = useState<FunctionSpec | null>(() =>
    span ? (catalog.find((spec) => spec.name === span.name) ?? null) : null,
  )
  const [error, setError] = useState<string | null>(null)

  const close = (): void => {
    host.cancel(target)
    onClose()
  }

  if (!picked) {
    return (
      <InsertFunctionDialog
        targetLabel={target.label}
        catalog={catalog}
        recent={recent}
        initialCategory={initialCategory}
        onPick={setPicked}
        onClose={close}
      />
    )
  }
  const initialArgs = span?.name === picked.name ? span.args : []
  return (
    <FunctionArgumentsDialog
      spec={picked}
      target={target}
      initialArgs={initialArgs}
      host={host}
      error={error}
      onCancel={close}
      onOk={(args) => {
        const failure = host.write(target, finishedFormula(target, span, picked.name, args))
        setError(failure)
        if (failure !== null) return
        setRecent(pushHistory(globalThis.localStorage, RECENT_FUNCTIONS_KEY, picked.name))
        onClose()
      }}
    />
  )
}
