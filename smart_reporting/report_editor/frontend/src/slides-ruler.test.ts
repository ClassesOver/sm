import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mountSlidesRuler } from './slides-ruler'

const observed = new Set<Element>()
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe(element: Element) { observed.add(element) }; unobserve(element: Element) { observed.delete(element) }; disconnect() { observed.clear() } })
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1)); vi.stubGlobal('cancelAnimationFrame', vi.fn())
})
afterEach(() => { document.body.replaceChildren(); observed.clear(); vi.unstubAllGlobals() })
function fixture() {
  const stage = document.body.appendChild(document.createElement('div'))
  let content = stage.appendChild(document.createElement('div'))
  const pull = vi.fn(), cancel = vi.fn()
  const ruler = mountSlidesRuler(stage, () => content, () => ({ width: 1000, height: 500 }), 'cm', pull, cancel)
  ruler.setVisible(true)
  return { ruler, stage, pull, cancel, content: () => content, switchHost() { content = stage.appendChild(document.createElement('div')); ruler.update() } }
}
function pointer(target: EventTarget, type: string, x = 200, id = 1) {
  const event = new MouseEvent(type, { bubbles: true, button: 0, clientX: x, clientY: 250 })
  Object.defineProperty(event, 'pointerId', { value: id }); target.dispatchEvent(event)
}
it.each(['composition','legacy','handled'])('标尺拖出参考线保留受保护Escape：%s',protection=>{
 const view=fixture(),strip=view.stage.querySelector('.ruler-h')!
 try{
  pointer(strip,'pointerdown',100);pointer(strip,'pointermove');const event=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();window.dispatchEvent(event)
  expect(view.cancel).not.toHaveBeenCalled();expect(event.defaultPrevented).toBe(protection==='handled');pointer(strip,'pointerup');expect(view.pull).toHaveBeenCalledTimes(2);expect(view.pull).toHaveBeenLastCalledWith('h',{x:200,y:250},true)
 }finally{view.ruler.dispose()}
})
it.each(['hide', 'cancel', 'switch', 'dispose', 'update'])('cancels an active ruler pull on %s', action => {
  const view = fixture(), strip = view.stage.querySelector('.ruler-h')!
  pointer(strip, 'pointerdown', 100); pointer(strip, 'pointermove')
  expect(view.pull).toHaveBeenCalledTimes(1)
  if (action === 'hide') view.ruler.setVisible(false)
  if (action === 'cancel') pointer(strip, 'pointercancel')
  if (action === 'switch') view.switchHost()
  if (action === 'update') view.ruler.update()
  if (action === 'dispose') view.ruler.dispose()
  pointer(strip, 'pointermove', 300); pointer(strip, 'pointerup', 300)
  expect(view.pull).toHaveBeenCalledTimes(1)
  expect(view.cancel).toHaveBeenCalledTimes(1)
  view.ruler.dispose()
})
it('unobserves the previous slide and removes all ruler DOM on disposal', () => {
  const view = fixture(), old = view.content()
  view.switchHost()
  expect(observed.has(old)).toBe(false); expect(observed.has(view.content())).toBe(true)
  view.ruler.dispose(); view.ruler.setVisible(true); view.ruler.update()
  expect(view.stage.querySelector('.ruler')).toBeNull()
  expect(view.stage.querySelector('.ruler-corner')).toBeNull()
  expect(observed.size).toBe(0)
  expect(view.stage.dataset.ruler).toBe('false')
})
it('adds a centered guide with a named native button', () => {
  const view = fixture()
  view.content().getBoundingClientRect = () => ({ x:100, y:100, left:100, top:100, right:1100, bottom:600, width:1000, height:500, toJSON() {} })
  // 刻度绘制由RAF触发；单测执行排队绘制以取得原生按钮。
  const draw = vi.mocked(requestAnimationFrame).mock.calls.at(-1)![0]; draw(0)
  const add = view.stage.querySelector<HTMLButtonElement>('.ruler-h .ruler-add')!
  expect(add.tagName).toBe('BUTTON'); expect(add.getAttribute('aria-label')).toContain('水平参考线')
  add.focus(); add.click()
  expect(view.pull).toHaveBeenCalledWith('h', {x:600,y:350}, true)
  expect(document.activeElement).toBe(add)
  view.ruler.dispose()
})
it('cancels a ruler pull on Escape', () => {
  const view = fixture(), strip = view.stage.querySelector('.ruler-h')!
  pointer(strip, 'pointerdown', 100); pointer(strip, 'pointermove')
  window.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true,cancelable:true}))
  pointer(strip, 'pointerup')
  expect(view.cancel).toHaveBeenCalledTimes(1)
  expect(view.pull).toHaveBeenCalledTimes(1)
  view.ruler.dispose()
})
it('retains the focused add control when ruler ticks redraw', () => {
  const view = fixture()
  const draw = vi.mocked(requestAnimationFrame).mock.calls.at(-1)![0]; draw(0)
  const add = view.stage.querySelector<HTMLButtonElement>('.ruler-h .ruler-add')!
  add.focus(); view.ruler.update(); vi.mocked(requestAnimationFrame).mock.calls.at(-1)![0](1)
  expect(document.activeElement).toBe(add)
  view.ruler.dispose()
})
