import { officeRequest, officeSession, type OfficeUser } from './office-client'
import { showOfficeAdministration } from './office-administration'
import { showOfficeSources } from './office-sources'
import { mountOfficeProviderSettings } from './office-provider-settings'
import './office.css'
import './office-settings.css'
type GlobalSettings = { version: number; modelId: string; imageModel: string; searchEnabled: boolean; integrationsEnabled: boolean }
const host = document.querySelector<HTMLElement>('#office-admin')!
let user: OfficeUser, settings: GlobalSettings, baseline = '', section = '模型配置', busy = false, providerDirty = false, providerBusy = false, expired = false
const labels = ['模型配置', '生图', '媒体', '搜索', '集成', '数据源管理', '用户管理']
const dirty = () => settings && JSON.stringify(settings) !== baseline
window.addEventListener('beforeunload', event => { if (dirty() || providerDirty || providerBusy) { event.preventDefault(); event.returnValue = '' } })
window.addEventListener('genoffice-session-expired', () => { expired = true; busy = false; providerBusy = false; host.textContent = '登录已失效，请返回工作区重新登录。'; settings = undefined!; providerDirty = false })
function element<K extends keyof HTMLElementTagNameMap>(tag: K, text = '') { const node = document.createElement(tag); node.textContent = text; return node }
function render() {
  if (expired) return
  host.className = 'office-admin-page'; host.replaceChildren()
  const header = element('header'), back = element('a', '返回工作区'); back.href = '/office'; back.onclick = event => { if (providerBusy || (providerDirty && !window.confirm('有未保存的提供商修改，是否离开？'))) event.preventDefault() }
  header.append(element('h1', '管理后台'), back); host.append(header)
  const layout = element('div'); layout.className = 'office-admin-layout'
  const nav = element('nav'); nav.setAttribute('aria-label', '全局设置')
  for (const label of labels) { const button = element('button', label); button.setAttribute('aria-current', String(section === label)); button.onclick = () => { if (busy || providerBusy || (providerDirty && !window.confirm('切换页面将放弃未保存的提供商修改，是否继续？'))) return; providerDirty = false; section = label; render() }; nav.append(button) }
  const content = element('section'); content.append(element('h2', section))
  const status = element('p'); status.setAttribute('role', 'status')
  const form = element('form')
  const text = (label: string, key: 'modelId' | 'imageModel') => {
    const row = element('label'), input = element('input'); input.maxLength = 200; input.value = settings[key]; input.placeholder = '沿用部署默认'; input.disabled = busy
    input.oninput = () => { settings[key] = input.value; status.textContent = '有未保存的修改' }; row.append(element('span', label), input); form.append(row)
  }
  const flag = (label: string, key: 'searchEnabled' | 'integrationsEnabled') => {
    const row = element('label'), input = element('input'); input.type = 'checkbox'; input.checked = settings[key]; input.disabled = busy
    input.onchange = () => { settings[key] = input.checked; status.textContent = '有未保存的修改' }; row.append(element('span', label), input); form.append(row)
  }
  if (section === '模型配置') { text('模型 ID', 'modelId'); form.append(element('p', '仅在尚未保存上方提供商配置时，使用此部署默认模型 ID。留空沿用部署配置。')) }
  if (section === '搜索') flag('启用文件内容搜索和 AI 重排', 'searchEnabled')
  if (section === '集成') flag('允许助手使用已授权的数据源集成', 'integrationsEnabled')
  if (['模型配置','生图','媒体','搜索'].includes(section)) {
    const cards = element('div'); content.append(cards)
    // Mount after the node is connected; detached results never replace another page.
    queueMicrotask(() => void mountOfficeProviderSettings(cards, {
      capabilities: section === '媒体' ? ['imageAnalysis', 'videoAnalysis'] : section === '搜索' ? ['webSearch'] : section === '生图' ? ['imageGeneration'] : ['chatModel'],
      onDirty: value => { if (cards.isConnected) providerDirty = value },
      onBusy: value => { if (!cards.isConnected || expired) return; providerBusy = value; for (const button of host.querySelectorAll<HTMLButtonElement>('nav button')) button.disabled = value; save.disabled = value },
    }))
  }
  if (section === '用户管理' || section === '数据源管理') {
    const open = element('button', section === '用户管理' ? '管理用户' : '工作区数据源授权')
    open.onclick = async () => { try { if (section === '用户管理') await showOfficeAdministration(host, { user, onChanged: async () => {} }); else await showOfficeSources(host, { admin: true, grantsOnly: true }) } catch (e) { status.textContent = (e as Error).message } }
    if (section === '数据源管理') { const original = element('a', '打开数据源管理'); original.href = '/management/sources'; content.append(original, element('p', '沿用原数据源管理页面及其管理员登录。')) }
    content.append(open)
  }
  const save = element('button', busy ? '保存中…' : '保存全局设置'); save.type = 'submit'; save.disabled = busy
  if (form.childElementCount) form.append(save)
  form.onsubmit = async event => {
    event.preventDefault(); if (busy || providerBusy || !dirty()) return
    busy = true; status.textContent = '正在保存…'
    const locked = [...host.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement>('input, button, select')].map(control => ({control, disabled: control.disabled}))
    for (const {control} of locked) control.disabled = true
    try {
      const { version, ...document } = settings
      const saved = await officeRequest<GlobalSettings>('/admin/settings', 'PUT', { ...document, expectedVersion: version })
      if (expired) return
      settings = saved
      baseline = JSON.stringify(settings); status.textContent = '已保存，对后续任务生效。'
    } catch (e) { status.textContent = (e as Error).message } finally { busy = false; for (const {control, disabled} of locked) control.disabled = disabled }
  }
  content.append(form, status); layout.append(nav, content); host.append(layout)
}
async function start() {
  try {
    user = await officeSession()
    if (expired) return
    if (user.role !== 'admin') { host.textContent = '需要管理员权限。'; return }
    const loaded = await officeRequest<GlobalSettings>('/admin/settings')
    if (expired) return
    settings = loaded; baseline = JSON.stringify(settings); render()
  } catch (error) { if (expired) return; host.textContent = (error as Error).message; const back = element('a', '返回工作区登录'); back.href = '/office'; host.append(back) }
}
void start()
