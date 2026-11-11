// 固定源 clear-selection-keyboard.ts 的 grid target，适配本地容器。
const SKIP_HOST = [
  'input', 'textarea', 'select', '[role="dialog"]', '[role="alertdialog"]', '.dialog-backdrop',
  ...['formula-bar', 'input', 'textarea', 'panel', 'panel-field', 'cell-popup', 'defined-name',
    'defined-name-container', 'select', 'multiple-select', 'sheets-dropdown-list', 'gallery', 'slide-tab-item']
    .map(value => `[data-u-comp="${value}"]`),
  '.shape-editable', '.chart-editor',
].join(',')

export function isWorkbookGridKeyTarget(target: EventTarget | null): boolean {
  const element = target instanceof Element ? target : null
  return !element?.closest(SKIP_HOST) && !(element?.closest('[contenteditable="true"]') && !element.closest('#workbook-grid'))
}
export function hasWorkbookModal(document: Document): boolean {
  return [...document.querySelectorAll('[role="dialog"], [role="alertdialog"], dialog[open]')].some(dialog => !dialog.closest('[hidden]'))
}
