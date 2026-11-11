// 官方footer menu/component扩展；preset需关闭原zoomSlider，避免重复缩放控件。
import { CommandType, ICommandService } from '@univerjs/core'
import { ComponentManager, ContextMenuGroup, ContextMenuPosition, IMenuManagerService, MenuItemType } from '@univerjs/ui'
import { createElement, useEffect, useState } from 'react'
import { BehaviorSubject } from 'rxjs'
import './workbook-zoom-launcher.css'
let launcherSerial = 0
export type WorkbookZoomLauncherCommand = 'zoom-open' | 'zoom-in' | 'zoom-out' | `zoom:${number}`
export function installWorkbookZoomDialogLauncher(runtime: any, host: HTMLElement,
  onCommand: (command: WorkbookZoomLauncherCommand) => void, available: () => boolean = () => true): { refresh(): void; dispose(): void } {
  const injector = runtime.univer?.__getInjector?.()
  if (!injector?.has?.(IMenuManagerService) || !injector.has(ComponentManager)) return { refresh() {}, dispose() {} }
  const components = injector.get(ComponentManager), menus = injector.get(IMenuManagerService)
  const commandService = injector.get(ICommandService)
  const id = `smart-reporting.workbook-zoom-launcher.${++launcherSerial}`, hidden = new BehaviorSubject(false)
  let disposed = false
  const menuCommand = commandService.registerCommand({ id, type: CommandType.OPERATION, handler: () => true })
  const read = () => Math.round((runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getZoom() ?? 1) * 100)
  const state = new BehaviorSubject({ percent: read(), enabled: available() })
  const refresh = () => { if (!disposed) state.next({ percent: read(), enabled: available() }) }
  const commands = runtime.univerAPI.onCommandExecuted(refresh)
  function ZoomLauncher() {
    const [current, setCurrent] = useState(state.value)
    useEffect(() => { const subscription = state.subscribe(setCurrent); return () => subscription.unsubscribe() }, [])
    const { percent, enabled } = current
    const ready = () => !disposed && host.isConnected && available()
    const button = (label: string, text: string, action: () => void, disabled = false) => createElement('button', {
      type: 'button', 'aria-label': label, disabled: !enabled || disabled,
      onClick: () => { if (ready()) action() },
    }, text)
    return createElement('span', { className: 'workbook-footer-zoom', 'aria-label': '工作表缩放', onClick: (event: { stopPropagation(): void }) => event.stopPropagation() },
      button('缩小', '−', () => onCommand('zoom-out'), percent <= 10),
      createElement('input', { type: 'range', min: 10, max: 400, value: percent, 'aria-label': '缩放滑块', disabled: !enabled,
        onChange: (event: { currentTarget: HTMLInputElement }) => { if (ready()) onCommand(`zoom:${Number(event.currentTarget.value)}`) } }),
      button('放大', '+', () => onCommand('zoom-in'), percent >= 400),
      button('缩放比例', `${percent}%`, () => onCommand('zoom-open')))
  }
  const registered = components.register(id, ZoomLauncher)
  menus.mergeMenu({ [ContextMenuPosition.FOOTER_MENU]: { [ContextMenuGroup.OTHERS]: { [id]: {
    order: 99, menuItemFactory: () => ({ id, type: MenuItemType.BUTTON,
      label: { name: id, selectable: false, hoverable: false }, hidden$: hidden }),
  } } } })
  return { refresh, dispose() { if (disposed) return; disposed = true; hidden.next(true); commands?.dispose?.(); state.complete(); menuCommand.dispose(); registered.dispose() } }
}
