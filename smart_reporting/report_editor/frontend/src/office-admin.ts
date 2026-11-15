import { officeRequest, officeSession, type OfficeUser } from './office-client'
import { showOfficeAdministration } from './office-administration'
import { showOfficeSources } from './office-sources'
import './office.css'
import './office-settings.css'
type GlobalSettings = { version: number; modelId: string; imageModel: string; searchEnabled: boolean; integrationsEnabled: boolean }
const host = document.querySelector<HTMLElement>('#office-admin')!
let user: OfficeUser, settings: GlobalSettings, baseline = '', section = '模型配置', busy = false
const labels = ['模型配置', '生图', '媒体', '搜索', '集成', '数据源管理', '用户管理']
const dirty = () => settings && JSON.stringify(settings) !== baseline
window.addEventListener('beforeunload', event => { if (dirty()) { event.preventDefault(); event.returnValue = '' } })
window.addEventListener('genoffice-session-expired', () => { host.textContent = '登录已失效，请返回工作区重新登录。'; settings = undefined! })
function element<K extends keyof HTMLElementTagNameMap>(tag: K, text = '') { const node = document.createElement(tag); node.textContent = text; return node }
function render() {
  host.className = 'office-admin-page'; host.replaceChildren()
  const header = element('header'), back = element('a', '返回工作区'); back.href = '/office'
  header.append(element('h1', '管理后台'), back); host.append(header)
  const layout = element('div'); layout.className = 'office-admin-layout'
  const nav = element('nav'); nav.setAttribute('aria-label', '全局设置')
  for (const label of labels) { const button = element('button', label); button.setAttribute('aria-current', String(section === label)); button.onclick = () => { section = label; render() }; nav.append(button) }
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
  if (section === '模型配置') { text('模型 ID', 'modelId'); form.append(element('p', '公司内统一使用此模型；服务地址和凭据沿用已部署的 Office 提供商。留空恢复部署默认。')) }
  if (section === '生图') { text('图像模型', 'imageModel'); form.append(element('p', '用于幻灯片 AI 配图，服务地址和凭据沿用已部署的图像提供商。')) }
  if (section === '搜索') flag('启用文件内容搜索和 AI 重排', 'searchEnabled')
  if (section === '集成') flag('允许助手使用已授权的数据源集成', 'integrationsEnabled')
  if (section === '媒体') content.append(element('p', '当前服务尚未接入音频／视频生成提供商。'))
  if (section === '用户管理' || section === '数据源管理') {
    const open = element('button', section === '用户管理' ? '管理用户' : '管理公司数据源')
    open.onclick = async () => { try { if (section === '用户管理') await showOfficeAdministration(host, { user, onChanged: async () => {} }); else await showOfficeSources(host, { admin: true }) } catch (e) { status.textContent = (e as Error).message } }
    content.append(open)
  }
  const save = element('button', busy ? '保存中…' : '保存全局设置'); save.type = 'submit'; save.disabled = busy
  if (form.childElementCount) form.append(save)
  form.onsubmit = async event => {
    event.preventDefault(); if (busy || !dirty()) return
    busy = true; status.textContent = '正在保存…'
    const locked = [...host.querySelectorAll<HTMLInputElement | HTMLButtonElement>('input, button')]
    for (const control of locked) control.disabled = true
    try {
      const { version, ...document } = settings
      settings = await officeRequest('/admin/settings', 'PUT', { ...document, expectedVersion: version })
      baseline = JSON.stringify(settings); status.textContent = '已保存，对后续任务生效。'
    } catch (e) { status.textContent = (e as Error).message } finally { busy = false; for (const control of locked) control.disabled = false }
  }
  content.append(form, status); layout.append(nav, content); host.append(layout)
}
async function start() {
  try {
    user = await officeSession()
    if (user.role !== 'admin') { host.textContent = '需要管理员权限。'; return }
    settings = await officeRequest('/admin/settings'); baseline = JSON.stringify(settings); render()
  } catch (error) { host.textContent = (error as Error).message; const back = element('a', '返回工作区登录'); back.href = '/office'; host.append(back) }
}
void start()
