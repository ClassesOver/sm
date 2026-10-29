import { ChartNoAxesCombined, Table2, createElement } from 'lucide'
import type { EditorTemplateInfo } from './api'

/** 只展示服务端模板能力与限制；不伪造示例数据或预览图。 */
export function createAITemplateCard(template: EditorTemplateInfo, kind: 'chart' | 'table', apply: () => void): HTMLButtonElement {
  const card = document.createElement('button')
  card.type = 'button'
  card.className = `ask-ai-template-card ${kind}-ai-template`
  card.disabled = !template.available
  card.title = template.reason ?? template.name
  const icon = document.createElement('span'); icon.className = 'ask-ai-template-icon'
  icon.append(createElement(kind === 'chart' ? ChartNoAxesCombined : Table2, { width: 24, height: 24, 'aria-hidden': 'true' }))
  const content = document.createElement('span'); content.className = 'ask-ai-template-content'
  const title = document.createElement('strong'); title.textContent = template.name
  const status = document.createElement('span'); status.className = 'ask-ai-template-status'
  status.textContent = template.available ? '可用模板' : '暂不可用'
  const reason = document.createElement('span'); reason.className = 'ask-ai-template-reason'
  reason.textContent = template.available ? '点击生成预览，确认后替换' : template.reason || '当前数据尚不满足模板要求'
  content.append(title, status, reason)
  card.append(icon, content)
  card.addEventListener('click', () => { if (template.available) apply() })
  return card
}
