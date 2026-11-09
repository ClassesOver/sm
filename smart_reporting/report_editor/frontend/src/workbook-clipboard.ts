/// 固定源 ExcelShell 粘贴下拉（f8c17004 ribbon-actions.ts）：每种选择性粘贴对应一条
/// Univer 官方 sheet 命令，撤销与普通粘贴一致；保存由值/样式/列宽差分写回。
export type PasteSpecialKind = 'value' | 'formula' | 'format' | 'col-width' | 'besides-border'
export const PASTE_SPECIAL_CHOICES: ReadonlyArray<{ value: `paste-special:${PasteSpecialKind}`; label: string; univerCommand: string }> = [
  { value: 'paste-special:value', label: '仅粘贴值', univerCommand: 'sheet.command.paste-value' },
  { value: 'paste-special:formula', label: '仅粘贴公式', univerCommand: 'sheet.command.paste-formula' },
  { value: 'paste-special:format', label: '仅粘贴格式', univerCommand: 'sheet.command.paste-format' },
  { value: 'paste-special:col-width', label: '粘贴列宽', univerCommand: 'sheet.command.paste-col-width' },
  { value: 'paste-special:besides-border', label: '无边框粘贴', univerCommand: 'sheet.command.paste-besides-border' },
]
/// 剪贴板命令 → Univer 官方命令 id（copy/cut/paste 注册在共享 UI 命令 id 上）。
export const CLIPBOARD_COMMANDS: Readonly<Record<string, string>> = {
  copy: 'univer.command.copy', cut: 'univer.command.cut', paste: 'univer.command.paste',
  ...Object.fromEntries(PASTE_SPECIAL_CHOICES.map(choice => [choice.value, choice.univerCommand])),
}

/// Univer 0.25.1 SheetPermissionCheckUIController._permissionCheckByPaste reads
/// `params.value` without a guard, so a parameterless univer.command.paste throws
/// ("reading 'value'") before pasting — found by the real-browser smoke. Plain
/// paste therefore sends `{}` (value undefined = the normal paste branch).
export const clipboardCommandParams = (command: string): Record<string, never> | undefined => command === 'paste' ? {} : undefined
