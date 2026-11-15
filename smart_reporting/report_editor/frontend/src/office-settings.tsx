import React from 'react'
import { createRoot } from 'react-dom/client'
import { officeRequest, type OfficeUser } from './office-client'
import { AccountSettingsDialog, type PersonalSettings } from './account-settings/dialog'
import { applyOfficeTheme } from './office-personal-theme'
import { showOfficeAssistantPreferences } from './office-assistant-preferences'
import './office-settings.css'
export interface OfficePersonalSettings extends PersonalSettings { version: number; scope: string }
export async function showOfficeSettings(host: HTMLElement, options: { user: OfficeUser; isCurrent(): boolean; onLogout(): void; initialSection?: 'account' | 'general' }) {
  let value = await officeRequest<OfficePersonalSettings>('/settings')
  if (!options.isCurrent()) return
  const opener = document.activeElement as HTMLElement | null
  const container = document.createElement('dialog'); container.className = 'office-personal-host'
  container.setAttribute('aria-label', '个人设置')
  const mount = document.createElement('div'); container.append(mount); host.ownerDocument.body.append(container)
  const root = createRoot(mount)
  const expired = () => container.close()
  container.addEventListener('click', event => event.stopPropagation())
  container.addEventListener('cancel', event => { event.preventDefault(); container.querySelector<HTMLButtonElement>('[aria-label="关闭设置"]')?.click() })
  container.onclose = () => { window.removeEventListener('genoffice-session-expired', expired); root.unmount(); container.remove(); opener?.focus() }
  window.addEventListener('genoffice-session-expired', expired)
  container.showModal()
  root.render(<AccountSettingsDialog initialSection={options.initialSection} onDocumentPreferences={() => { void import('./office-document-preferences').then(({ showOfficeDocumentPreferences }) => showOfficeDocumentPreferences(() => options.isCurrent() && container.isConnected)).catch(error => window.alert((error as Error).message)) }} username={options.user.name || options.user.user} settings={value} onAssistantPreferences={() => showOfficeAssistantPreferences(container)} onClose={() => container.close()} onSave={async draft => {
    if (!options.isCurrent()) throw new Error('账户已变化，请重新打开设置。')
    const saved = await officeRequest<OfficePersonalSettings>('/settings', 'PUT', { theme: draft.theme, disabledSkills: draft.skills.filter(item => !item.enabled).map(item => item.id), expectedVersion: value.version })
    if (!options.isCurrent()) throw new Error('账户已变化，请重新打开设置。')
    value = saved; applyOfficeTheme(saved.theme); return saved
  }} onLogout={async () => {
    if (!options.isCurrent()) throw new Error('账户已变化，请重新打开设置。')
    await officeRequest('/logout', 'POST')
    if (!options.isCurrent()) throw new Error('账户已变化，请重新打开设置。')
    applyOfficeTheme('system'); options.onLogout()
  }} />)
}
