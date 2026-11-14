import { afterEach, expect, it } from 'vitest'
import { createSlidesNativeRibbon } from './slides-native-ribbon'

afterEach(() => { document.body.replaceChildren(); document.documentElement.lang = '' })

it('中文尺寸选项显示源含义和单位，选择仍提交原预设键', () => {
  document.documentElement.lang = 'zh-CN'
  const host = document.body.appendChild(document.createElement('div'))
  const actions: unknown[][] = []
  const ribbon = createSlidesNativeRibbon(host, { onAction: (...action) => actions.push(action) })
  ribbon.setSlideOrientationEnabled(true)
  const select = host.querySelector<HTMLSelectElement>('[data-command="slideSize"]')!
  expect([...select.options].map(option => [option.value, option.textContent])).toEqual([
    ['16:9', '宽屏 (16:9)'], ['4:3', '标准 (4:3)'],
    ['A4', 'A4 纸 (210 × 297 毫米)'], ['A3', 'A3 纸 (297 × 420 毫米)'],
  ])
  for (const value of ['16:9', '4:3', 'A4', 'A3']) {
    select.value = value; select.dispatchEvent(new Event('change'))
  }
  expect(actions).toEqual([['slideSize', '16:9'], ['slideSize', '4:3'], ['slideSize', 'A4'], ['slideSize', 'A3']])
  ribbon.dispose()
})

it('中文圆形转场使用源标签，选择保留原工具参数与SVG', () => {
  document.documentElement.lang = 'zh-CN'
  const host = document.body.appendChild(document.createElement('div'))
  const actions: unknown[][] = []
  const ribbon = createSlidesNativeRibbon(host, { onAction: (...action) => actions.push(action) })
  ribbon.setTransitionEditEnabled(true)
  const transition = host.querySelector<HTMLSelectElement>('[data-command="transition"]')!
  expect(transition.querySelector('option[value="circle"]')?.textContent).toBe('圆形')
  transition.value = 'circle'; transition.dispatchEvent(new Event('change'))
  expect(actions).toEqual([['transition', 'circle']])
  expect(host.querySelector('[data-command="motionPathCircle"] svg')).not.toBeNull()
  ribbon.dispose()
})

it('中文艺术字的无障碍名称采用源标签并保留原预设参数', () => {
  document.documentElement.lang = 'zh-CN'
  const host = document.body.appendChild(document.createElement('div'))
  const actions: unknown[][] = []
  const ribbon = createSlidesNativeRibbon(host, { onAction: (...action) => actions.push(action) })
  const wordArt = host.querySelector<HTMLSelectElement>('[data-command="insertWordArt"]')!
  expect(wordArt.getAttribute('aria-label')).toBe('艺术字')
  expect(wordArt.title).toBe('艺术字')
  wordArt.value = 'blue'; wordArt.dispatchEvent(new Event('change'))
  expect(wordArt.value).toBe('')
  expect(actions).toEqual([['insertWordArt', 'blue']])
  ribbon.dispose()
})

it('英文界面保留尺寸与转场原标签', () => {
  document.documentElement.lang = 'en'
  const host = document.body.appendChild(document.createElement('div'))
  const ribbon = createSlidesNativeRibbon(host, { onAction: () => {} })
  expect([...host.querySelectorAll('[data-command="slideSize"] option')].map(option => option.textContent)).toEqual(['16:9', '4:3', 'A4', 'A3'])
  expect(host.querySelector('[data-command="transition"] option[value="circle"]')?.textContent).toBe('circle')
  expect(host.querySelector('[data-command="insertWordArt"]')?.getAttribute('aria-label')).toBe('WordArt')
  ribbon.dispose()
})
