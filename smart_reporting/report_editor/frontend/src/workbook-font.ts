import { BooleanNumber, TextDecoration } from '@univerjs/core'
import type { WorkbookFormatState } from './workbook-format'

export type WorkbookFontCommand = 'strike' | 'underline' | 'underline:double'
export interface FontDecorationRange {
  setValue?(value: { s: { st?: { s: number }; ul?: { s: number; t: number } } }): unknown
}

/** Public FRange style-only commands merge one decoration and record one undo
 * entry. setFontLine('none') clears BOTH underline and strike; null re-inherits
 * the source style, so toggling off needs an explicit BooleanNumber.FALSE.
 */
export function applyWorkbookFontDecoration(command: WorkbookFontCommand, range: FontDecorationRange, state: WorkbookFormatState): void {
  const current = command === 'strike' ? state.strikethrough : command === 'underline:double' ? state.doubleUnderline : state.underline
  if (current.kind === 'unavailable') throw new Error(current.reason)
  if (!range.setValue) throw new Error('当前网格未提供可撤销的字体样式命令')
  const s = current.kind !== 'value' || !current.value ? BooleanNumber.TRUE : BooleanNumber.FALSE
  const style = command === 'strike' ? { st: { s } } : { ul: { s, t: command === 'underline:double' ? TextDecoration.DOUBLE : TextDecoration.SINGLE } }
  if (range.setValue({ s: style }) === false) throw new Error('字体格式未应用')
}
