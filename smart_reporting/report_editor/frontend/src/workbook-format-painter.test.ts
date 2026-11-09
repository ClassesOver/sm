import { afterEach, expect, it, vi } from 'vitest'
import { ICommandService, LifecycleService, LifecycleStages, Univer, LocaleType } from '@univerjs/core'
import { FormatPainterStatus, IFormatPainterService, IShortcutService, SetFormatPainterOperation } from '@univerjs/preset-sheets-core'
import { applyFormatPainterClick, formatPainterActive, formatPainterReady, formatPainterClickAction, formatPainterTurnedOff, installFormatPainter, turnOffFormatPainter } from './workbook-format-painter'
import { mountWorkbookRibbon } from './workbook-ribbon'

const univers: Univer[] = []
afterEach(() => { univers.splice(0).forEach(univer => univer.dispose()); document.body.replaceChildren() })

it('maps ribbon clicks to the fixed-source painter transitions', () => {
  expect(formatPainterClickAction(FormatPainterStatus.OFF, 1)).toBe('once')
  expect(formatPainterClickAction(FormatPainterStatus.ONCE, 1)).toBe('cancel')
  expect(formatPainterClickAction(FormatPainterStatus.INFINITE, 1)).toBe('cancel')
  // 双击 = click(1) 先进入 ONCE，click(2) 升级为锁定；取消后的第二击忽略。
  expect(formatPainterClickAction(FormatPainterStatus.ONCE, 2)).toBe('lock')
  expect(formatPainterClickAction(FormatPainterStatus.OFF, 2)).toBe('ignore')
  expect(formatPainterTurnedOff(FormatPainterStatus.INFINITE, FormatPainterStatus.OFF)).toBe(true)
  expect(formatPainterTurnedOff(FormatPainterStatus.OFF, FormatPainterStatus.OFF)).toBe(false)
})

it('drives the painter through the real Univer command service and Esc shortcut registration', async () => {
  // 真实 Univer 注入器与命令服务；painter 服务以官方 token 注册的最小实现（sheets-ui 渲染层需 canvas）。
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  univers.push(univer)
  const injector = univer.__getInjector()
  let status = FormatPainterStatus.OFF
  const listeners = new Set<(value: FormatPainterStatus) => void>()
  const changes: Array<[boolean, boolean]> = []
  // 先安装、后到 Steady（同生产时序：编辑器挂载早于 sheets-ui 注册 painter 服务与默认钩子）。
  const lifecycle = injector.get(LifecycleService)
  const runtime = { univer }
  const listener = installFormatPainter(runtime, (active, turnedOff) => changes.push([active, turnedOff]))
  let hooks: unknown[] = []
  const painter = { getHooks: () => hooks, getStatus: () => status, setStatus: (next: FormatPainterStatus) => { status = next; listeners.forEach(listener => listener(next)) },
    status$: { subscribe: (next: (value: FormatPainterStatus) => void) => { listeners.add(next); return { unsubscribe: () => listeners.delete(next) } } } }
  const shortcuts: unknown[] = []
  injector.add([IFormatPainterService, { useValue: painter } as never])
  injector.add([IShortcutService, { useValue: { registerShortcut: (item: unknown) => { shortcuts.push(item); return { dispose: () => shortcuts.splice(shortcuts.indexOf(item), 1) } } } } as never])
  const commands = injector.get(ICommandService)
  commands.registerCommand({ ...SetFormatPainterOperation, handler: (_accessor: unknown, params: { status: FormatPainterStatus }) => { painter.setStatus(params.status); return true } } as never)
  // 安装时服务尚未就绪也不得抛错；Steady 之前不注册快捷键。
  expect(shortcuts).toHaveLength(0)

  for (const stage of [LifecycleStages.Ready, LifecycleStages.Rendered, LifecycleStages.Steady]) lifecycle.stage = stage
  await vi.waitFor(() => expect(shortcuts).toHaveLength(1))
  changes.splice(0)
  // Steady 之前没有默认钩子：不武装，避免"看似激活却刷不出格式"。
  expect(formatPainterReady(runtime)).toBe(false)
  expect(applyFormatPainterClick(runtime, 1)).toBe('not-ready')
  expect(status).toBe(FormatPainterStatus.OFF)
  hooks = [{ id: 'default-format-painter' }]
  expect(formatPainterReady(runtime)).toBe(true)
  expect(applyFormatPainterClick(runtime, 1)).toBe('once')
  await vi.waitFor(() => expect(status).toBe(FormatPainterStatus.ONCE))
  expect(applyFormatPainterClick(runtime, 2)).toBe('lock')
  await vi.waitFor(() => expect(status).toBe(FormatPainterStatus.INFINITE))
  expect(formatPainterActive(runtime)).toBe(true)
  // 保存路径解除锁定。
  turnOffFormatPainter(runtime)
  await vi.waitFor(() => expect(status).toBe(FormatPainterStatus.OFF))
  expect(changes).toEqual([[true, false], [true, false], [false, true]])
  await commands.executeCommand('report-editor.command.cancel-format-painter')
  listener.dispose()
  expect(shortcuts).toHaveLength(0)
  expect(formatPainterActive({ univer: { __getInjector: () => ({ get: () => { throw new Error('no painter') } }) } })).toBe(false)
})

it('renders the painter as a pressed toggle that dispatches single and double clicks and follows editability', () => {
  const host = document.createElement('div'); document.body.append(host)
  const command = vi.fn(); let active = false, editable = true
  let ready = false
  const ribbon = mountWorkbookRibbon(host, command, { rotation: () => 0, editable: () => editable, hasSelection: () => true, formatPainterActive: () => active, formatPainterReady: () => ready })
  host.querySelector<HTMLButtonElement>('[role="tab"][data-ribbon-tab="Home"]')!.click()
  const button = host.querySelector<HTMLButtonElement>('[data-ribbon-command="format-painter"]')!
  expect(button.disabled).toBe(true)
  expect(button.title).toContain('初始化')
  ready = true; ribbon.refreshState()
  expect(button.disabled).toBe(false)
  expect(button.getAttribute('aria-pressed')).toBe('false')
  button.dispatchEvent(new MouseEvent('click', { detail: 1, bubbles: true }))
  button.dispatchEvent(new MouseEvent('click', { detail: 2, bubbles: true }))
  expect(command.mock.calls.map(call => call[0])).toEqual(['format-painter', 'format-painter:dblclick'])
  active = true; ribbon.refreshState()
  expect(button.getAttribute('aria-pressed')).toBe('true')
  editable = false; ribbon.refreshState()
  expect(button.disabled).toBe(true)
  ribbon.dispose()
})
