import type { ConfigurationItem } from './contracts'

const commonKeys = new Set([
  'AGENT_MODEL_FAST', 'AGENT_MODEL_STANDARD', 'AGENT_MODEL_STRONG',
  'OPENAI_BASE_URL', 'OPENAI_API_KEY', 'AGENT_MODEL_TIMEOUT_SECONDS',
])

/** 页面只维护日常配置，协议与部署参数保留在部署配置中。 */
export function systemFields(items: ConfigurationItem[], category: string, search: string) {
  const term = search.trim().toLowerCase()
  return items.filter(item => item.owner !== 'preferences' && commonKeys.has(item.key) && (term
    ? (item.label + item.key).toLowerCase().includes(term)
    : item.category === category))
}
