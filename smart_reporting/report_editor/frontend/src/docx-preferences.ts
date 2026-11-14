import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { getLang, LocaleProvider } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/locale'
import { PreferencesDialog } from './docx-preferences-general'
import { AutoCorrectDialog } from './docx-preferences-autocorrect'

/** Uses the same preference stores and measurement subscriptions as the source ruler and length inputs. */
export function openDocxPreferencesDialog(kind: 'general' | 'autocorrect'): () => void {
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const host = document.createElement('div')
  host.className = 'docx-native docx-preferences-host'; host.lang = getLang(); document.body.append(host)
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
  flushSync(() => root.render(createElement(LocaleProvider, { initial: getLang(), children: createElement(kind === 'general' ? PreferencesDialog : AutoCorrectDialog, { onClose: close }) })))
  host.querySelector('[role=dialog]')?.setAttribute('aria-modal', 'true')
  return close
}

export { installDocxAutocorrect } from './docx-preferences-autocorrect-adapter'
