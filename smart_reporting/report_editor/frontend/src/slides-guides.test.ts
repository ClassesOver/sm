import { afterEach, beforeEach, expect, it } from 'vitest'
import { mountSlidesGuides, type SlidesGuides } from './slides-guides'

const mounted: SlidesGuides[] = []
beforeEach(() => { localStorage.clear() })
afterEach(() => { mounted.splice(0).forEach(guides => guides.dispose()); document.body.replaceChildren() })
function fixture(key = 'guides') {
  let host = document.body.appendChild(document.createElement('div'))
  host.className = 'slides-canvas'
  const size = () => ({ x: 100, y: 100, left: 100, top: 100, right: 1100, bottom: 600, width: 1000, height: 500, toJSON() {} })
  host.getBoundingClientRect = size
  const guides = mountSlidesGuides(() => host, () => ({ width: 1000, height: 500 }), key, () => {})
  mounted.push(guides)
  guides.setVisible(true)
  return { guides, host: () => host, switchHost() { host = document.body.appendChild(document.createElement('div')); host.className = 'slides-canvas'; host.getBoundingClientRect = size; guides.render() } }
}
function pointer(target: EventTarget, type: string, x = 800, id = 1) {
  const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: 350, button: 0 })
  Object.defineProperty(event, 'pointerId', { value: id }); target.dispatchEvent(event)
}
it.each(['composition','legacy','handled'])('参考线保留受保护移动和删除按键：%s',protection=>{
 const view=fixture(),before=view.guides.guides()
 for(const axis of ['v','h']){
  const line=view.host().querySelector<HTMLElement>(`.guide-${axis}`)!;line.focus()
  for(const name of [axis==='v'?'ArrowLeft':'ArrowUp',axis==='v'?'ArrowRight':'ArrowDown','Home','End','Delete','Backspace']){
   const event=new KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();line.dispatchEvent(event)
   expect(view.guides.guides()).toEqual(before);expect(document.activeElement).toBe(line);expect(event.defaultPrevented).toBe(protection==='handled');expect(localStorage.getItem('guides')).toBeNull()
  }
 }
 const line=view.host().querySelector<HTMLElement>('.guide-v')!;key(line,'ArrowRight');expect(view.guides.guides()[0].pos).toBeCloseTo(.501)
})
it.each(['composition','legacy','handled'])('参考线拖动保留受保护Escape并仅在松开时提交：%s',protection=>{
 const view=fixture(),line=view.host().querySelector<HTMLElement>('.guide-v')!;line.focus();pointer(line,'pointerdown');pointer(window,'pointermove')
 const event=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();window.dispatchEvent(event)
 expect(view.guides.guides()[0].pos).toBe(.7);expect(localStorage.getItem('guides')).toBeNull();expect(document.activeElement).toBe(line);expect(event.defaultPrevented).toBe(protection==='handled')
 pointer(window,'pointerup');expect(JSON.parse(localStorage.getItem('guides')!)[0].pos).toBe(.7)
})
it('keeps reference lines owned by another editor', () => {
  const first = fixture('first'), second = fixture('second')
  expect(first.host().querySelectorAll('.guide-line')).toHaveLength(2)
  second.guides.setVisible(false)
  expect(first.host().querySelectorAll('.guide-line')).toHaveLength(2)
})
it.each(['hide', 'switch', 'cancel', 'render'])('rolls back an uncommitted drag on %s', action => {
  const view = fixture(), line = view.host().querySelector<HTMLElement>('.guide-v')!
  pointer(line, 'pointerdown'); pointer(window, 'pointermove')
  expect(view.guides.guides()[0].pos).toBe(0.7)
  if (action === 'hide') view.guides.setVisible(false)
  if (action === 'switch') view.switchHost()
  if (action === 'render') view.guides.render()
  if (action === 'cancel') pointer(window, 'pointercancel')
  pointer(window, 'pointermove', 1000); pointer(window, 'pointerup', 1000)
  expect(view.guides.guides()[0].pos).toBe(0.5)
  expect(localStorage.getItem('guides')).toBeNull()
  expect(document.querySelector<HTMLElement>('.ruler-bubble')!.hidden).toBe(true)
})
it('disposes overlays and stops pending drag without persisting', () => {
  const view = fixture()
  pointer(view.host().querySelector('.guide-v')!, 'pointerdown'); pointer(window, 'pointermove')
  expect(typeof view.guides.dispose).toBe('function')
  view.guides.dispose()
  pointer(window, 'pointerup')
  expect(document.querySelector('.ruler-bubble')).toBeNull()
  expect(view.host().querySelector('.guide-line')).toBeNull()
  expect(localStorage.getItem('guides')).toBeNull()
  view.guides.render(); view.guides.setVisible(true)
  expect(view.host().querySelector('.guide-line')).toBeNull()
})
it('does not create a guide when there is no measurable page', () => {
  const guides = mountSlidesGuides(() => null, () => ({ width: 1000, height: 500 }), 'empty', () => {})
  mounted.push(guides)
  guides.pull('v', { x: 400, y: 350 }, true)
  expect(guides.guides()).toHaveLength(2)
  expect(localStorage.getItem('empty')).toBeNull()
})

it('commits only the active pointer and persists the moved position', () => {
  const view = fixture(), line = view.host().querySelector('.guide-v')!
  pointer(line, 'pointerdown'); pointer(window, 'pointermove', 900, 2); pointer(window, 'pointerup', 900, 2)
  expect(view.guides.guides()[0].pos).toBe(0.5)
  pointer(window, 'pointermove', 800); pointer(window, 'pointerup', 800)
  expect(JSON.parse(localStorage.getItem('guides')!)[0].pos).toBe(0.7)
})
it('cancels a drag when pointer capture is lost', () => {
  const view = fixture(), line = view.host().querySelector('.guide-v')!
  pointer(line, 'pointerdown'); pointer(window, 'pointermove'); pointer(line, 'lostpointercapture')
  pointer(window, 'pointerup')
  expect(view.guides.guides()[0].pos).toBe(0.5)
  expect(localStorage.getItem('guides')).toBeNull()
})
it('previews a pull while guides are hidden and cancellation leaves no stored change', () => {
  const view = fixture(); view.guides.setVisible(false)
  view.guides.pull('h', { x: 500, y: 350 }, false)
  expect(view.host().querySelectorAll('.guide-line')).toHaveLength(1)
  view.guides.cancelPull()
  expect(view.host().querySelector('.guide-line')).toBeNull()
  expect(localStorage.getItem('guides')).toBeNull()
})

function key(target: EventTarget, value: string, shiftKey = false) {
  const event = new KeyboardEvent('keydown', { key: value, shiftKey, bubbles: true, cancelable: true })
  target.dispatchEvent(event); return event
}
it.each(['v', 'h'])('exposes a named keyboard-adjustable %s guide and retains focus while moving', axis => {
  const view = fixture(), line = view.host().querySelector<HTMLElement>(`.guide-${axis}`)!
  expect(line.tabIndex).toBe(0); expect(line.getAttribute('role')).toBe('slider')
  expect(line.getAttribute('aria-label')).toContain(axis === 'v' ? '垂直参考线' : '水平参考线')
  expect(line.getAttribute('aria-valuenow')).toBe('50')
  line.focus()
  const index = axis === 'v' ? 0 : 1, length = axis === 'v' ? 1000 : 500
  expect(key(line, axis === 'v' ? 'ArrowRight' : 'ArrowDown').defaultPrevented).toBe(true)
  expect(view.guides.guides()[index].pos).toBeCloseTo(.5 + 1 / length)
  expect(document.activeElement).toBe(line)
  key(line, axis === 'v' ? 'ArrowLeft' : 'ArrowUp', true)
  expect(view.guides.guides()[index].pos).toBeCloseTo(.5 - 9 / length)
  expect(JSON.parse(localStorage.getItem('guides')!)[index].pos).toBeCloseTo(.5 - 9 / length)
  expect(line.getAttribute('aria-valuetext')).toContain('cm')
  key(line, 'Home'); expect(view.guides.guides()[index].pos).toBe(0)
  key(line, 'End'); expect(view.guides.guides()[index].pos).toBe(1)
})
it('moves keyboard focus to a surviving guide after deletion and to the page after the last guide', () => {
  const view = fixture(), line = view.host().querySelector<HTMLElement>('.guide-v')!
  line.focus(); key(line, 'Delete')
  expect(view.guides.guides()).toHaveLength(1)
  expect(document.activeElement).toBe(view.host().querySelector('.guide-h'))
  key(document.activeElement!, 'Delete')
  expect(view.guides.guides()).toHaveLength(0)
  expect(document.activeElement).toBe(view.host())
})
it('cancels an active pointer drag with Escape without committing or losing focus', () => {
  const view = fixture(), line = view.host().querySelector<HTMLElement>('.guide-v')!
  line.focus(); pointer(line, 'pointerdown'); pointer(window, 'pointermove')
  key(window, 'Escape'); pointer(window, 'pointerup')
  expect(view.guides.guides()[0].pos).toBe(.5)
  expect(localStorage.getItem('guides')).toBeNull()
  expect(document.activeElement).toBe(line)
  expect(line.getAttribute('aria-valuenow')).toBe('50')
})

it.each(['v', 'h'])('clicking the %s guide transfers focus so the next arrow adjusts that guide', axis => {
  const view = fixture(), input = document.body.appendChild(document.createElement('input'))
  input.focus()
  const line = view.host().querySelector<HTMLElement>(`.guide-${axis}`)!
  pointer(line, 'pointerdown'); pointer(window, 'pointerup')
  expect(document.activeElement).toBe(line)
  key(document.activeElement!, axis === 'v' ? 'ArrowRight' : 'ArrowDown')
  expect(view.guides.guides()[axis === 'v' ? 0 : 1].pos).toBeCloseTo(axis === 'v' ? .501 : .502)
})
