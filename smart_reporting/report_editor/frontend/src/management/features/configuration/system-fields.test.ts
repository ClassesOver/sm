import { expect, it } from 'vitest'
import { systemFields } from './system-fields'
import type { ConfigurationItem } from './contracts'

const item = (key: string, extra: Partial<ConfigurationItem> = {}) => ({ key, label: key, category: '模型与服务', owner: 'system', ...extra }) as ConfigurationItem

it('只呈现日常维护项，不再展开底层协议参数或重复偏好', () => {
  const items = [item('AGENT_MODEL_FAST'), item('AGENT_MODEL_FAST_STRUCTURED_MODE'), item('AGENT_REPORT_ORGANIZATION_NAME', { owner: 'preferences' })]
  expect(systemFields(items, '模型与服务', '').map(item => item.key)).toEqual(['AGENT_MODEL_FAST'])
})

it('搜索不能重新显示已移除的冗余参数', () => {
  expect(systemFields([item('AGENT_MODEL_FAST_STRUCTURED_MODE')], '报告运行', 'structured')).toEqual([])
  expect(systemFields([item('AGENT_MODEL_FAST')], '报告运行', 'fast')).toHaveLength(1)
})

it('部署连接与路径不挤占日常维护页面', () => {
  const items = ['AGENT_OS_HOST', 'AGENT_OS_PORT', 'AGENT_LOG_FILE', 'AGENT_REPORT_PUBLIC_BASE_URL'].map(key => item(key, { category: '部署与启动' }))
  expect(systemFields(items, '部署与启动', '')).toEqual([])
})

it('执行协议与运维诊断不再混入日常表单或搜索结果', () => {
  const items = ['AGENT_REPORT_CODING_EXECUTION_MODE', 'AGENT_DEBUG', 'AGENT_TRACING_ENABLED', 'AGENT_OS_ACCESS_LOG'].map(key => item(key))
  expect(systemFields(items, '模型与服务', '')).toEqual([])
  for (const entry of items) expect(systemFields(items, '', entry.key)).toEqual([])
})
