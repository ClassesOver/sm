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
import { CommandType, ICommandService, toDisposable, type IDisposable } from '@univerjs/core'
import {
  FormatPainterStatus,
  IFormatPainterService,
  IShortcutService,
  KeyCode,
  SetFormatPainterOperation,
  whenSheetEditorFocused,
} from '@univerjs/preset-sheets-core'

type PainterRuntime = { univer: { __getInjector(): { get<T>(token: unknown): T } } }

export type FormatPainterClick = 'once' | 'lock' | 'cancel' | 'ignore'

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
  status$: { subscribe(next: (status: FormatPainterStatus) => void): { unsubscribe(): void } }
}>(IFormatPainterService)
const commandsOf = (runtime: PainterRuntime) => runtime.univer.__getInjector().get<ICommandService>(ICommandService)

export function applyFormatPainterClick(runtime: PainterRuntime, detail: number): FormatPainterClick {
  const action = formatPainterClickAction(painterOf(runtime).getStatus(), detail)
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
 */
export function installFormatPainter(runtime: PainterRuntime, onStatusChange: (active: boolean, turnedOff: boolean) => void): IDisposable {
  const injector = runtime.univer.__getInjector()
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
  return toDisposable(() => { subscription.unsubscribe(); commandDisposable.dispose(); shortcutDisposable.dispose() })
}
