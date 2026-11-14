import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { SetNumberingValueDialog } from './vendor/genoffice-docs/apps/docs/src/renderer/components/ListDialogs'
import { getLang, LocaleProvider } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/locale'
import type { docxNumberingValueTarget } from './docx-custom-list'

/** 复用源对话框；宿主在提交前重新核对来源和选区。 */
export function openDocxNumberingValueDialog(target: ReturnType<typeof docxNumberingValueTarget>, apply: (mode: 'restart' | 'continue', value?: number) => void, report: (error: unknown) => void) {
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const host = document.createElement('div')
  host.className = 'docx-native docx-list-dialog-host'; host.lang = getLang()
  document.body.append(host)
  const root = createRoot(host)
  let closed = false
  const guardIme = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && (event.isComposing || event.keyCode === 229 || event.defaultPrevented)) event.stopImmediatePropagation()
  }
  const close = () => {
    if (closed) return
    closed = true; root.unmount(); host.remove(); window.removeEventListener('keydown', guardIme, true)
    if (opener?.isConnected) opener.focus({ preventScroll: true })
  }
  window.addEventListener('keydown', guardIme, true)
  const level = target.definition.levels[target.ilvl]!
  flushSync(() => root.render(createElement(LocaleProvider, { initial: getLang(), children: createElement(SetNumberingValueDialog, {
    numFmt: level.numFmt, lvlText: level.lvlText, currentValue: target.currentValue, canContinue: !!target.previous,
    onClose: close,
    onApply: (mode, value) => { try { apply(mode, value); close() } catch (error) { report(error) } },
  }) })))
  host.querySelector('[role=dialog]')?.setAttribute('aria-modal', 'true')
  return close
}
