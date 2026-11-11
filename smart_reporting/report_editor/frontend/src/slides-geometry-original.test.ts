import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesGeometryPane } from './slides-geometry-pane'

// jsdom不解码图片；只替换浏览器解码边界，真实分组、事件和提交保持运行。
class DecodedImage {
  static instances: DecodedImage[] = []
  src = ''; naturalWidth = 0; naturalHeight = 0
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor() { DecodedImage.instances.push(this) }
  resolve(width = 48, height = 32) { this.naturalWidth = width; this.naturalHeight = height; this.onload?.() }
}
const initial = { x: 96.123456, y: 72, width: 192, height: 96 }
let pane: ReturnType<typeof createSlidesGeometryPane>
afterEach(() => { pane?.dispose(); document.body.innerHTML = ''; vi.unstubAllGlobals(); DecodedImage.instances = [] })
function setup() {
  vi.stubGlobal('Image', DecodedImage)
  let state = { target: '0:picture', picture: true, geometry: initial, slideSize: { width: 960, height: 540 } }
  const confirm = vi.fn((geometry: typeof initial) => { state = { ...state, geometry }; pane.update(state) })
  pane = createSlidesGeometryPane(confirm); document.body.append(pane.element); pane.update(state)
  const field = (key: string) => pane.element.querySelector<HTMLInputElement>(`[data-geometry="${key}"]`)!
  const checkbox = () => pane.element.querySelector<HTMLInputElement>('[data-geometry-original]')!
  const change = (key: string, value: string) => { field(key).value = value; field(key).dispatchEvent(new Event('change')) }
  const source = (url = 'data:image/png;base64,first', replaced = false) => pane.setPictureSource(state.target, { type: 'picture', dataUrl: url }, replaced)
  return { confirm, field, checkbox, change, source, state: () => state }
}

it('真实像素作为原始基准，切换仅改显示，原始百分比与会话百分比分别换算', () => {
  const { confirm, field, checkbox, change, source, state } = setup()
  expect(checkbox()).not.toBeNull()
  source(); expect(field('scaleWidth').disabled).toBe(true)
  DecodedImage.instances[0]!.resolve()
  expect(checkbox().checked).toBe(true)
  expect(field('scaleWidth').value).toBe('400'); expect(field('scaleHeight').value).toBe('300')
  expect(confirm).not.toHaveBeenCalled()
  checkbox().click(); expect(field('scaleWidth').value).toBe('100'); expect(confirm).not.toHaveBeenCalled()
  change('scaleWidth', '150'); expect(state().geometry).toEqual({ ...initial, width: 288 })
  checkbox().click(); expect(field('scaleWidth').value).toBe('600'); expect(confirm).toHaveBeenCalledTimes(1)
  pane.element.querySelector<HTMLInputElement>('[data-geometry-ratio]')!.click()
  change('scaleWidth', '200'); expect(state().geometry).toEqual({ ...initial, width: 96, height: 32 })
  expect(field('width').value).toBe('2.54')
  field('scaleHeight').value = '200'; expect(pane.flush()).toBe(true)
  expect(state().geometry).toEqual({ ...initial, width: 192, height: 64 })
})

it('图片解码不重建厘米输入或丢失未提交值，无效图片回退会话且不发起远程读取', () => {
  const { confirm, field, checkbox, source, change, state } = setup()
  expect(checkbox()).not.toBeNull()
  source(); const width = field('width'); width.value = '7.62'
  DecodedImage.instances[0]!.resolve()
  expect(field('width')).toBe(width); expect(width.value).toBe('7.62'); expect(confirm).not.toHaveBeenCalled()
  expect(pane.flush()).toBe(true); expect(state().geometry.width).toBe(288)
  source('data:image/png;base64,broken'); DecodedImage.instances[1]!.onerror?.()
  expect(checkbox().disabled).toBe(true); expect(checkbox().checked).toBe(false)
  expect(field('scaleWidth').disabled).toBe(false); expect(field('scaleWidth').value).toBe('150')
  expect(pane.element.textContent).toContain('选中尺寸')
  change('scaleWidth', '200'); expect(state().geometry.width).toBe(384)
  source('https://example.invalid/image.png'); expect(DecodedImage.instances).toHaveLength(2)
})

it('异步结果按对象与图片来源失效，替换待保存时禁用原始模式，撤回后重新读取', () => {
  const { confirm, field, checkbox, source, state } = setup()
  expect(checkbox()).not.toBeNull()
  source(); const old = DecodedImage.instances[0]!
  pane.update({ ...state(), target: '0:other' })
  pane.setPictureSource('0:other', { type: 'picture', dataUrl: 'data:image/png;base64,other' })
  old.resolve(1000, 2000); expect(field('scaleWidth').disabled).toBe(true)
  DecodedImage.instances[1]!.resolve(96, 48); expect(field('scaleWidth').value).toBe('200')
  pane.update(state()); source(); const pending = DecodedImage.instances[2]!
  source('data:image/png;base64,first', true); pending.resolve()
  expect(checkbox().disabled).toBe(true); expect(field('scaleWidth').value).toBe('100')
  expect(pane.element.textContent).toContain('替换')
  source(); DecodedImage.instances[3]!.resolve(); expect(field('scaleWidth').value).toBe('400')
  pane.setLocked(true); expect(checkbox().disabled).toBe(true)
  pane.setLocked(false); expect(checkbox().checked).toBe(true)
  source('data:image/png;base64,last'); const last = DecodedImage.instances[4]!
  pane.dispose(); last.resolve(); expect(confirm).not.toHaveBeenCalled()
})

it('重复来源不重复解码，非图片与陈旧来源回调不能改变当前基准', () => {
  const { confirm, checkbox, source, state, field } = setup()
  expect(checkbox()).not.toBeNull()
  source(); DecodedImage.instances[0]!.resolve(); source(); expect(DecodedImage.instances).toHaveLength(1)
  pane.update({ ...state(), target: '0:text', picture: false }); expect(checkbox().disabled).toBe(true)
  pane.setPictureSource('0:picture', { type: 'picture', dataUrl: 'data:image/png;base64,stale' })
  expect(DecodedImage.instances).toHaveLength(1); expect(field('scaleWidth').value).toBe('100')
  expect(confirm).not.toHaveBeenCalled()
})

it('未完成厘米输入不能阻止新来源解码或替换禁用，来源回调不提交输入', () => {
  const { confirm, checkbox, source, field } = setup()
  source(); DecodedImage.instances[0]!.resolve()
  field('width').value = ''
  source('data:image/png;base64,second')
  expect(DecodedImage.instances).toHaveLength(2)
  expect(checkbox().disabled).toBe(true); expect(field('width').value).toBe('')
  DecodedImage.instances[1]!.resolve(96, 48)
  expect(field('scaleWidth').value).toBe('200'); expect(field('width').value).toBe('')
  source('data:image/png;base64,second', true)
  expect(checkbox().disabled).toBe(true); expect(checkbox().checked).toBe(false)
  expect(field('scaleWidth').value).toBe('100'); expect(field('width').value).toBe('')
  field('width').value = '5.08'; expect(pane.flush()).toBe(true)
  expect(confirm).not.toHaveBeenCalled(); expect(checkbox().disabled).toBe(true)
})
