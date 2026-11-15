import { setOfficeAssistantIdentity } from './office-assistant-preferences'
import { officeRequest } from './office-client'
import type { Theme } from './account-settings/dialog'
import type { OfficePersonalSettings } from './office-settings'
import './office-settings.css'
let appliedTheme: Theme = 'system'
let stopTheme: (() => void) | undefined
export function applyOfficeTheme(theme: Theme) {
  stopTheme?.(); appliedTheme = theme
  const media = matchMedia('(prefers-color-scheme: dark)')
  const apply = () => {
    document.documentElement.dataset.officeTheme = theme === 'system' ? media.matches ? 'dark' : 'light' : theme
    for (const frame of document.querySelectorAll<HTMLIFrameElement>('#office iframe')) {
      try { frame.contentDocument?.documentElement.setAttribute('data-office-theme', document.documentElement.dataset.officeTheme!) } catch { /* separate-origin frames are never modified */ }
    }
  }
  apply(); media.addEventListener('change', apply)
  stopTheme = () => media.removeEventListener('change', apply)
}
export function refreshOfficeTheme() { applyOfficeTheme(appliedTheme) }
export async function loadOfficePreferences(isCurrent: () => boolean) {
  const value = await officeRequest<OfficePersonalSettings>('/settings')
  if (isCurrent()) { setOfficeAssistantIdentity(value.scope); applyOfficeTheme(value.theme) }
}
