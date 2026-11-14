import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesNativeRibbon, type NativeSlidesContext } from './slides-native-ribbon'

afterEach(() => document.body.replaceChildren())

function fixture() {
  const host = document.body.appendChild(document.createElement('div'))
  const onAction = vi.fn(), ribbon = createSlidesNativeRibbon(host, { onAction })
  const tab = (id: string) => host.querySelector<HTMLButtonElement>(`[data-ribbon-tab="${id}"]`)!
  const selected = () => host.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]')!
  const press = (key: string, init: KeyboardEventInit = {}) => {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
    document.activeElement!.dispatchEvent(event)
    return event
  }
  return { host, ribbon, onAction, tab, selected, press }
}

for (const protection of ['composing', 'legacy229', 'consumed']) for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
  it(`页签保留 ${protection} ${key} 输入及焦点`, () => {
    const f = fixture(), initial = key === 'Home' ? 'view' : 'home'
    f.tab(initial).click(); f.tab(initial).focus()
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composing', keyCode: protection === 'legacy229' ? 229 : 0 })
    if (protection === 'consumed') event.preventDefault()
    f.tab(initial).dispatchEvent(event)
    expect(f.selected()).toBe(f.tab(initial)); expect(document.activeElement).toBe(f.tab(initial))
    expect(event.defaultPrevented).toBe(protection === 'consumed'); expect(f.onAction).not.toHaveBeenCalled()
    f.ribbon.dispose()
  })
}

it('普通方向键与首尾键同步选择、焦点、roving tabindex 和关联面板，并跳过不可用页签', () => {
  const f = fixture()
  f.tab('insert').disabled = true; f.tab('draw').hidden = true
  for (const [from, key, expected] of [['home', 'ArrowRight', 'design'], ['design', 'ArrowLeft', 'home'], ['file', 'ArrowLeft', 'view'], ['view', 'ArrowRight', 'file'], ['home', 'Home', 'file'], ['home', 'End', 'view']]) {
    f.tab(from!).click(); f.tab(from!).focus()
    expect(f.press(key!).defaultPrevented).toBe(true)
    expect(f.selected()).toBe(f.tab(expected!)); expect(document.activeElement).toBe(f.tab(expected!))
    expect([...f.host.querySelectorAll<HTMLElement>('[role="tab"]')].filter(tab => tab.tabIndex === 0)).toEqual([f.tab(expected!)])
    expect([...f.host.querySelectorAll<HTMLElement>('[role="tabpanel"]')].filter(panel => !panel.hidden).map(panel => panel.id)).toEqual([f.tab(expected!).getAttribute('aria-controls')])
  }
  expect(f.onAction).not.toHaveBeenCalled(); f.ribbon.dispose()
})

for (const [context, id] of [['table', 'tableDesign'], ['chart', 'chartDesign'], ['picture', 'pictureFormat'], ['shape', 'shapeFormat'], ['model3d', 'model3dFormat']] as const) {
  for (const focus of ['tab', 'panel', 'outside']) it(`${context} 上下文消失恢复 ${focus} 焦点且不抢外部焦点`, () => {
    const f = fixture(); f.ribbon.setContext(context)
    f.tab('home').focus(); f.press('End'); expect(f.selected()).toBe(f.tab(id))
    const panel = f.host.querySelector<HTMLElement>(`[data-ribbon-panel="${id}"]`)!
    const target = focus === 'tab' ? f.tab(id) : (focus === 'panel' ? panel : document.body).appendChild(document.createElement('button'))
    target.focus(); f.ribbon.setContext(null)
    expect(f.tab(id).hidden).toBe(true); expect(panel.hidden).toBe(true)
    expect(f.selected()).toBe(f.tab('home'))
    expect(document.activeElement).toBe(focus === 'outside' ? target : f.tab('home'))
    expect(f.onAction).not.toHaveBeenCalled(); f.ribbon.dispose()
  })
}

it('上下文替换、重复刷新和停留普通页签保持有效选择及焦点', () => {
  const f = fixture()
  f.ribbon.setContext('table'); f.tab('tableDesign').click(); f.tab('tableDesign').focus()
  f.ribbon.setContext('table'); expect(document.activeElement).toBe(f.tab('tableDesign'))
  f.ribbon.setContext('picture'); expect(document.activeElement).toBe(f.tab('home')); expect(f.tab('pictureFormat').hidden).toBe(false)
  f.press('End'); expect(f.selected()).toBe(f.tab('pictureFormat'))
  f.tab('view').click(); f.tab('view').focus()
  f.ribbon.setContext('shape' as NativeSlidesContext)
  expect(f.selected()).toBe(f.tab('view')); expect(document.activeElement).toBe(f.tab('view'))
  expect(f.onAction).not.toHaveBeenCalled(); f.ribbon.dispose()
})
