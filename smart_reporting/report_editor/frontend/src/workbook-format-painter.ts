/**
 * Excel-style Format Painter button semantics on top of Univer's painter
 * service: a single click paints the next selection once, a double-click
 * keeps the painter on until Esc or another click on the button.
 *
 * Adapted from GenOffice f8c17004 apps/sheets/src/renderer/format-painter.ts
 * (genspark-ai/genoffice, see workbook-vendor/LICENSE and NOTICE). Local
 * changes: services are imported through the pinned preset (sheets-ui/ui are
 * re-exported by @univerjs/preset-sheets-core), the runtime type is the
 * report editor's, and `turnOffFormatPainter` lets save/lock paths disarm it.
 * Painted style deltas land as sheet set-range-values mutations, so the
 * existing style diff persists them like any ribbon style edit.
 */
import { CommandType, ICommandService, LifecycleService, LifecycleStages, toDisposable, type IDisposable } from '@univerjs/core'
import {
  FormatPainterStatus,
  IFormatPainterService,
  IShortcutService,
  KeyCode,
  SetFormatPainterOperation,
  whenSheetEditorFocused,
} from '@univerjs/preset-sheets-core'

type PainterRuntime = { univer: { __getInjector(): { get<T>(token: unknown): T } } }

export type FormatPainterClick = 'once' | 'lock' | 'cancel' | 'ignore' | 'not-ready'

const CANCEL_FORMAT_PAINTER_ID = 'report-editor.command.cancel-format-painter'

/**
 * Maps a ribbon click to the painter transition. A double-click reaches
 * the button as click(detail 1) → click(detail 2), so the first click has
 * already armed the one-shot painter when the second one arrives and only
 * needs to escalate it; a second click that follows a cancel is ignored.
 */
export function formatPainterClickAction(status: FormatPainterStatus, detail: number): FormatPainterClick {
  if (detail >= 2) return status === FormatPainterStatus.ONCE ? 'lock' : 'ignore'
  return status === FormatPainterStatus.OFF ? 'once' : 'cancel'
}

// Resolved at call time (not module load) so callers that stub the preset
// module without painter exports still import this file; every runtime path
// is guarded and treats a missing painter as "off".
const statusAfterClick = (action: Exclude<FormatPainterClick, 'ignore'>): FormatPainterStatus =>
  action === 'once' ? FormatPainterStatus.ONCE : action === 'lock' ? FormatPainterStatus.INFINITE : FormatPainterStatus.OFF

export function formatPainterTurnedOff(previous: FormatPainterStatus, next: FormatPainterStatus): boolean {
  return previous !== FormatPainterStatus.OFF && next === FormatPainterStatus.OFF
}

const painterOf = (runtime: PainterRuntime) => runtime.univer.__getInjector().get<{
  getStatus(): FormatPainterStatus
  getHooks?(): readonly unknown[]
  status$: { subscribe(next: (status: FormatPainterStatus) => void): { unsubscribe(): void } }
}>(IFormatPainterService)

/**
 * Univer 0.25.1 installs the painter's default hook (FormatPainterController,
 * which collects the source format and builds the apply mutations) only at the
 * Steady lifecycle stage, 3 s after the first render. Armed before that, the
 * painter shows as active but paints nothing (found by the real-browser
 * smoke). The ribbon therefore treats it as ready only once a hook exists.
 */
export function formatPainterReady(runtime: PainterRuntime): boolean {
  try { return (painterOf(runtime).getHooks?.() ?? []).length > 0 } catch { return false }
}
const commandsOf = (runtime: PainterRuntime) => runtime.univer.__getInjector().get<ICommandService>(ICommandService)

export function applyFormatPainterClick(runtime: PainterRuntime, detail: number): FormatPainterClick {
  const status = painterOf(runtime).getStatus()
  if (status === FormatPainterStatus.OFF && !formatPainterReady(runtime)) return 'not-ready'
  const action = formatPainterClickAction(status, detail)
  if (action === 'ignore') return action
  void commandsOf(runtime).executeCommand(SetFormatPainterOperation.id, { status: statusAfterClick(action) })
  return action
}

export function formatPainterActive(runtime: PainterRuntime): boolean {
  try { return painterOf(runtime).getStatus() !== FormatPainterStatus.OFF } catch { return false }
}

export function turnOffFormatPainter(runtime: PainterRuntime): void {
  try {
    if (painterOf(runtime).getStatus() === FormatPainterStatus.OFF) return
    void commandsOf(runtime).executeCommand(SetFormatPainterOperation.id, { status: FormatPainterStatus.OFF })
  } catch { /* painter service absent (test doubles): nothing armed */ }
}

/**
 * Mirrors the painter status into the ribbon and binds Esc in the grid to
 * cancel an active painter (Univer only uses Esc to leave the cell editor).
 *
 * The painter service and its default hook come from sheets-ui, which
 * registers/creates them during Univer's lifecycle (the hook at Steady). The
 * report editor mounts before that, so installation waits for Steady instead
 * of failing at mount time (found by the real-browser smoke: the Esc shortcut
 * and status mirroring were silently never installed).
 */
export function installFormatPainter(runtime: PainterRuntime, onStatusChange: (active: boolean, turnedOff: boolean) => void): IDisposable {
  const injector = runtime.univer.__getInjector()
  let disposed = false
  let installed: (() => void) | undefined
  const install = () => {
    if (disposed) return
    const painter = painterOf(runtime)
    const commandService = commandsOf(runtime)
    const shortcutService = injector.get<IShortcutService>(IShortcutService)
    let previous = painter.getStatus()
    const subscription = painter.status$.subscribe(status => {
      onStatusChange(status !== FormatPainterStatus.OFF, formatPainterTurnedOff(previous, status))
      previous = status
    })
    const commandDisposable = commandService.registerCommand({
      id: CANCEL_FORMAT_PAINTER_ID,
      type: CommandType.COMMAND,
      handler: accessor => accessor.get(ICommandService).executeCommand(SetFormatPainterOperation.id, { status: FormatPainterStatus.OFF }),
    })
    const shortcutDisposable = shortcutService.registerShortcut({
      id: CANCEL_FORMAT_PAINTER_ID,
      binding: KeyCode.ESC,
      priority: 100,
      preconditions: contextService => painter.getStatus() !== FormatPainterStatus.OFF && whenSheetEditorFocused(contextService),
    })
    installed = () => { subscription.unsubscribe(); commandDisposable.dispose(); shortcutDisposable.dispose() }
    // Readiness (the default hook) is now known: let the ribbon re-evaluate.
    onStatusChange(painter.getStatus() !== FormatPainterStatus.OFF, false)
  }
  const lifecycle = injector.get<LifecycleService>(LifecycleService)
  // Plugins' own Steady handlers create the hook; install on the next task.
  lifecycle.onStage(LifecycleStages.Steady).then(() => setTimeout(install, 0), () => undefined)
  return toDisposable(() => { disposed = true; installed?.() })
}
