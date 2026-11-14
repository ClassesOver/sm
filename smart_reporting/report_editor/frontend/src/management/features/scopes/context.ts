// 所有配置属于当前应用实例，不再从URL读取或选择组织。
const instance = { database: 'instance', companyId: 'instance' }
export function useScope() { return instance }
export function scopeSuffix(_scope: { database: string; companyId: string } | null) { return '' }
