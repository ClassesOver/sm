import { afterEach, expect, it } from 'vitest'
import { bindOfficeRibbonScroll } from './office-ribbon-scroll'
afterEach(() => document.body.replaceChildren())
function setup() {
  const root = document.body.appendChild(document.createElement('section'))
  root.innerHTML = '<div role="tabpanel"><button>命令</button><input type="number"><select><option>字体</option></select></div>'
  const panel = root.firstElementChild as HTMLElement
  Object.defineProperties(panel, { clientWidth: { value: 200 }, scrollWidth: { value: 700 } })
  const dispose = bindOfficeRibbonScroll(root)
  const wheel = (target: Element, deltaY: number, options: WheelEventInit = {}) => {
    const event = new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY, ...options })
    target.dispatchEvent(event); return event
  }
  return { root, panel, dispose, wheel }
}
it('scrolls overflow horizontally and releases the wheel at either edge', () => {
  const { panel, wheel, dispose } = setup()
  expect(wheel(panel, 60).defaultPrevented).toBe(true); expect(panel.scrollLeft).toBe(60)
  panel.scrollLeft = 480; wheel(panel, 60); expect(panel.scrollLeft).toBe(500)
  expect(wheel(panel, 60).defaultPrevented).toBe(false)
  panel.scrollLeft = 0; expect(wheel(panel, -60).defaultPrevented).toBe(false)
  dispose(); wheel(panel, 60); expect(panel.scrollLeft).toBe(0)
})
it('preserves horizontal gestures, browser zoom and editable fields', () => {
  const { panel, wheel } = setup()
  for (const options of [{ ctrlKey: true }, { metaKey: true }, { deltaX: 70 }]) expect(wheel(panel, 20, options).defaultPrevented).toBe(false)
  for (const target of panel.querySelectorAll('input,select')) expect(wheel(target, 20).defaultPrevented).toBe(false)
  expect(panel.scrollLeft).toBe(0)
})
it('normalizes line scrolling and reveals focused commands without scrolling the page', () => {
  const { panel, wheel } = setup()
  wheel(panel, 2, { deltaMode: 1 }); expect(panel.scrollLeft).toBe(32)
  panel.scrollLeft = 0
  panel.getBoundingClientRect = () => ({ left: 0, right: 200 } as DOMRect)
  const button = panel.querySelector('button')!
  button.getBoundingClientRect = () => ({ left: 250, right: 300 } as DOMRect)
  button.focus(); expect(panel.scrollLeft).toBeGreaterThanOrEqual(100)
})
it('leaves dropdown menus and popovers in control of their own scrolling', () => {
  const { panel, wheel } = setup()
  const menu = panel.appendChild(document.createElement('div'));menu.setAttribute('role','menu')
  const item = menu.appendChild(document.createElement('button'));item.textContent='菜单项'
  expect(wheel(item,60).defaultPrevented).toBe(false)
  expect(panel.scrollLeft).toBe(0)
})
