import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AccountSettingsDialog, type PersonalSettings } from './dialog'

let root: Root
const saved: PersonalSettings = { theme: 'system', skills: [{ id: 'reports', name: '报告', description: '生成报告', enabled: true }] }
const click = async (label: string) => {
  const button = [...document.querySelectorAll('button')].find(item => item.textContent === label)!
  await act(async () => button.click())
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  document.body.innerHTML = '<button id="trigger">账户</button><div id="test"></div>'
  document.querySelector<HTMLButtonElement>('#trigger')!.focus()
  root = createRoot(document.querySelector('#test')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.restoreAllMocks() })
it('个人菜单仅有账户、偏好和技能，关闭恢复账户入口焦点', async () => {
  const close = vi.fn()
  await act(async () => root.render(<AccountSettingsDialog username="alice" settings={saved} onSave={async value => value} onClose={close} onLogout={async () => {}} />))
  expect([...document.querySelectorAll('nav button')].map(x => x.textContent)).toEqual(['账户', '偏好', '技能'])
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain('alice')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="关闭设置"]')!.click())
  expect(close).toHaveBeenCalledOnce()
  await act(async () => root.unmount())
  expect(document.activeElement?.id).toBe('trigger')
  root = createRoot(document.querySelector('#test')!)
})
it('保存失败保留个人草稿，可以重试，不误报成功', async () => {
  let fail = true
  const save = vi.fn(async (value: PersonalSettings) => { if (fail) throw new Error('网络不可用'); return value })
  await act(async () => root.render(<AccountSettingsDialog username="alice" settings={saved} onSave={save} onClose={() => {}} onLogout={async () => {}} />))
  await click('偏好')
  const select = document.querySelector<HTMLSelectElement>('select')!
  await act(async () => { select.value = 'dark'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  await click('保存')
  expect(document.querySelector('[role="alert"]')?.textContent).toBe('网络不可用')
  expect(select.value).toBe('dark')
  expect(document.body.textContent).not.toContain('已保存')
  fail = false
  await click('保存')
  expect(save).toHaveBeenLastCalledWith({ ...saved, theme: 'dark' })
  expect(document.body.textContent).toContain('已保存')
})
it('未保存修改关闭时提示，取消关闭保留技能选择', async () => {
  const close = vi.fn()
  await act(async () => root.render(<AccountSettingsDialog username="alice" settings={saved} onSave={async x => x} onClose={close} onLogout={async () => {}} />))
  await click('技能')
  await act(async () => document.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click())
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="关闭设置"]')!.click())
  expect(close).not.toHaveBeenCalled()
  await click('继续编辑')
  expect(document.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false)
})
