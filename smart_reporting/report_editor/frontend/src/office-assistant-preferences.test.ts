import { afterEach, expect, it, vi } from 'vitest'
afterEach(() => { localStorage.clear(); vi.resetModules() })
it('助手界面偏好按用户隔离，其他标签切换账户后拒绝旧页面写入', async () => {
  const prefs = await import('./office-assistant-preferences')
  prefs.setOfficeAssistantIdentity('alice'); prefs.saveOfficeAssistantSide('right')
  prefs.setOfficeAssistantIdentity('bob'); expect(prefs.readOfficeAssistantPreferences().side).toBe('left')
  prefs.setOfficeAssistantIdentity('alice'); expect(prefs.readOfficeAssistantPreferences().side).toBe('right')
  localStorage.setItem('genoffice-assistant-identity', 'bob')
  expect(() => prefs.saveOfficeAssistantSide('left')).toThrow('账户已变化')
  expect(localStorage.getItem('genoffice-assistant-preferences:bob')).toBeNull()
})
