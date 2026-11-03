import './style.css'
import { mountEditor } from './editor'
import { requestJson, type SlidesDocument } from './state'

const root = document.querySelector<HTMLElement>('#app')!
const endpoint = location.pathname.replace(/\/$/, '')
root.textContent = '正在载入幻灯片…'
try {
  const document = await requestJson<SlidesDocument>(`${endpoint}/document`)
  mountEditor(root, document, endpoint)
} catch (error) {
  root.replaceChildren()
  const panel = document.createElement('main')
  panel.className = 'load-error'
  const title = document.createElement('h1')
  title.textContent = '无法载入幻灯片'
  const detail = document.createElement('p')
  detail.textContent = error instanceof Error ? error.message : '请稍后重试。'
  const retry = document.createElement('button')
  retry.textContent = '重新载入'
  retry.addEventListener('click', () => location.reload())
  panel.append(title, detail, retry)
  root.append(panel)
}
