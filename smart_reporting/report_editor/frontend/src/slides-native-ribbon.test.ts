import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesNativeRibbon, stepNativeFontSize } from './slides-native-ribbon'

afterEach(() => document.body.replaceChildren())

it('keeps the upstream slide ribbon tabs and contextual tabs available by selection type', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })

  expect([...host.querySelectorAll('[role=tab]')].map(tab => tab.textContent)).toEqual([
    'File', 'Home', 'Insert', 'Draw', 'Design', 'Transitions', 'Animations', 'Slide Show', 'Review', 'View',
    'Table Design', 'Chart Design', 'Picture Format', 'Shape Format', '3D Model',
  ])
  expect(host.querySelector('[data-ribbon-tab="shapeFormat"]')?.hasAttribute('hidden')).toBe(true)
  ribbon.setContext('shape')
  expect(host.querySelector('[data-ribbon-tab="shapeFormat"]')?.hasAttribute('hidden')).toBe(false)
  ribbon.dispose()
})

it('preserves GenOffice Home clipboard action IDs, source glyphs and disabled browser states', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  const sourceActions = ['onPaste', 'onCut', 'onCopy', 'onFormatBrushClick']

  expect(host.querySelector('[aria-label="Clipboard"]')).not.toBeNull()
  for (const sourceId of sourceActions) {
    const control = host.querySelector<HTMLButtonElement>(`[data-source-action="${sourceId}"]`)!
    expect(control.disabled).toBe(true)
    expect(control.dataset.unavailable).toBe('true')
    expect(control.querySelector('svg')).not.toBeNull()
  }
  ribbon.dispose()
})

it('uses the pinned GenOffice Simplified Chinese clipboard labels when the document language is Chinese', () => {
  const host = document.createElement('div')
  document.body.append(host)
  document.documentElement.lang = 'zh-CN'
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })

  expect(host.querySelector('[aria-label="剪贴板"]')).not.toBeNull()
  expect(host.querySelector('[data-source-action="onPaste"]')?.textContent).toContain('粘贴')
  expect(host.querySelector('[data-source-action="onFormatBrushClick"]')?.textContent).toContain('格式刷')
  ribbon.dispose()
  document.documentElement.lang = ''
})

it('preserves the pinned Review Comments actions, order, icons and disabled states', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  const comments = host.querySelector<HTMLElement>('[aria-label="Comments"]')!
  const controls = [...comments.querySelectorAll<HTMLButtonElement>('[data-source-action]')]

  expect(controls.map(control => control.dataset.sourceAction)).toEqual(['onNewComment', 'onToggleComments'])
  expect(controls.every(control => control.disabled && control.dataset.unavailable === 'true')).toBe(true)
  expect(controls.every(control => control.querySelector('svg'))).toBe(true)
  ribbon.dispose()
})

it('shows contextual tabs without changing the active tab until the user selects one', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  const animationsTab = host.querySelector<HTMLButtonElement>('[data-ribbon-tab="animations"]')!
  const pictureTab = host.querySelector<HTMLButtonElement>('[data-ribbon-tab="pictureFormat"]')!

  animationsTab.click()
  ribbon.setContext('shape')
  expect(animationsTab.getAttribute('aria-selected')).toBe('true')
  expect(host.querySelector('[data-ribbon-tab="shapeFormat"]')?.hasAttribute('hidden')).toBe(false)

  ribbon.setContext('picture')
  expect(animationsTab.getAttribute('aria-selected')).toBe('true')
  expect(host.querySelector('[data-ribbon-tab="shapeFormat"]')?.hasAttribute('hidden')).toBe(true)
  expect(pictureTab.hasAttribute('hidden')).toBe(false)

  pictureTab.click()
  expect(pictureTab.getAttribute('aria-selected')).toBe('true')
  ribbon.dispose()
})

it('dispatches supported commands with selected values through the native adapter', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction, layouts: [{ path: 'ppt/slideLayouts/layout2.xml', name: 'Title Only' }] })

  host.querySelector<HTMLButtonElement>('[data-command="addText"]')!.click()
  host.querySelector<HTMLSelectElement>('[data-command="theme"]')!.value = 'modern'
  host.querySelector<HTMLSelectElement>('[data-command="theme"]')!.dispatchEvent(new Event('change', { bubbles: true }))
  host.querySelector<HTMLSelectElement>('[data-command="layout"]')!.value = 'ppt/slideLayouts/layout2.xml'
  host.querySelector<HTMLSelectElement>('[data-command="layout"]')!.dispatchEvent(new Event('change', { bubbles: true }))

  expect(onAction.mock.calls).toEqual([
    ['addText'], ['theme', 'modern'], ['layout', 'ppt/slideLayouts/layout2.xml'],
  ])
  ribbon.dispose()
})

it('steps selected PPTX text sizes on the fixed GenOffice font ladder', () => {
  expect(stepNativeFontSize(18, 1)).toBe(20)
  expect(stepNativeFontSize(19, 1)).toBe(20)
  expect(stepNativeFontSize(19, -1)).toBe(18)
  expect(stepNativeFontSize(96, 1)).toBe(104)
  expect(stepNativeFontSize(100, -1)).toBe(96)
  expect(stepNativeFontSize(null, 1)).toBe(20)
})

it('gates upstream font-size step commands on a text target and the save lock', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const commands = ['fontSizeUp', 'fontSizeDown']
  const controls = commands.map(command => host.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!)
  const clickAll = () => controls.forEach(control => control.click())

  expect(controls.every(control => control.disabled)).toBe(true)
  clickAll()
  expect(onAction).not.toHaveBeenCalled()

  ribbon.setTextFormatEnabled(true)
  expect(controls.every(control => !control.disabled)).toBe(true)
  clickAll()
  expect(onAction.mock.calls).toEqual([['fontSizeUp'], ['fontSizeDown']])
  onAction.mockClear()

  ribbon.setLocked(true)
  expect(controls.every(control => control.disabled)).toBe(true)
  clickAll()
  expect(onAction).not.toHaveBeenCalled()
  ribbon.setLocked(false)
  expect(controls.every(control => !control.disabled)).toBe(true)

  ribbon.setTextFormatEnabled(false)
  expect(controls.every(control => control.disabled)).toBe(true)
  ribbon.setLocked(true)
  ribbon.setLocked(false)
  expect(controls.every(control => control.disabled)).toBe(true)
  clickAll()
  expect(onAction).not.toHaveBeenCalled()
  ribbon.dispose()
})

it('dispatches source-derived paragraph alignment commands from the Home group', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const group = host.querySelector<HTMLElement>('[aria-label="Paragraph"]')!
  const commands = ['paragraphAlignLeft', 'paragraphAlignCenter', 'paragraphAlignRight', 'paragraphAlignJustify']
  const controls = commands.map(command => group.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!)
  expect(controls.map(control => control.dataset.sourceAction)).toEqual(['onAlign', 'onAlign', 'onAlign', 'onAlign'])
  expect(controls.every(control => control.disabled)).toBe(true)
  controls.forEach(control => control.click())
  expect(onAction).not.toHaveBeenCalled()

  ribbon.setTextFormatEnabled(true)
  controls.forEach(control => control.click())

  expect(onAction.mock.calls).toEqual([
    ['paragraphAlignLeft'], ['paragraphAlignCenter'], ['paragraphAlignRight'], ['paragraphAlignJustify'],
  ])
  expect(controls.every(control => !control.disabled)).toBe(true)
  ribbon.dispose()
})

it('keeps Home slide layout changes connected and unsupported slide actions explicitly disabled', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, {
    onAction,
    layouts: [{ path: 'ppt/slideLayouts/layout2.xml', name: 'Title Only' }],
  })
  const group = host.querySelector<HTMLElement>('[aria-label="Slides"]')!
  const layout = group.querySelector<HTMLSelectElement>('[data-command="layout"]')!
  const unavailable = [...group.querySelectorAll<HTMLButtonElement>('[data-unavailable="true"]')]

  expect([...group.querySelectorAll('[data-source-action]')].map(control => control.getAttribute('data-source-action'))).toEqual([
    'onAddSlide', 'onAddSlideWithLayout', 'onSetLayout', 'onResetLayout', 'onAddSection',
  ])
  expect(unavailable.every(control => control.disabled && control.dataset.unavailable === 'true')).toBe(true)
  expect(layout.dataset.sourceAction).toBe('onSetLayout')
  expect(layout.options[0]?.value).toBe('ppt/slideLayouts/layout2.xml')
  layout.value = 'ppt/slideLayouts/layout2.xml'
  layout.dispatchEvent(new Event('change', { bubbles: true }))
  expect(onAction.mock.calls).toEqual([['layout', 'ppt/slideLayouts/layout2.xml']])
  ribbon.dispose()
})

it('preserves Insert table, image, shape and chart source actions while disabling unsupported writes', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  const expected = [
    ['Tables', ['onInsertTable']],
    ['Illustrations', ['onPickShape', 'onInsertSmartArt', 'onInsertChart']],
  ] as const
  for (const [groupName, actions] of expected) {
    const group = host.querySelector<HTMLElement>(`[aria-label="${groupName}"]`)!
    const controls = [...group.querySelectorAll<HTMLButtonElement>('[data-source-action]')]
    expect(controls.map(control => control.dataset.sourceAction)).toEqual(actions)
    expect(controls.every(control => control.disabled && control.dataset.unavailable === 'true')).toBe(true)
    expect(controls.every(control => control.querySelector('svg'))).toBe(true)
  }
  const images = host.querySelector<HTMLElement>('[aria-label="Images"]')!
  const picture = images.querySelector<HTMLButtonElement>('[data-source-action="onInsertImage"]')!
  expect(picture.disabled).toBe(true)
  expect(picture.dataset.unavailable).toBe('true')
  expect(picture.querySelector('svg')).not.toBeNull()
  const smartArt = host.querySelector<HTMLButtonElement>('[data-source-action="onInsertSmartArt"]')!
  expect(smartArt.disabled).toBe(true)
  expect(smartArt.dataset.unavailable).toBe('true')
  ribbon.dispose()
})

it('connects the source text-box action and disables unsupported Insert Text and Equation actions', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const textGroup = host.querySelector<HTMLElement>('.slides-native-ribbon-group[aria-label="Text"]')!
  const textBox = textGroup.querySelector<HTMLButtonElement>('[data-command="addText"]')!
  const unsupportedTextActions = [
    'onInsertWordArt', 'onOpenHeaderFooter', 'onInsertField:datetime', 'onInsertField:slidenum',
  ]

  expect(textBox.disabled).toBe(false)
  expect(textBox.dataset.sourceAction).toBe('onInsert')
  expect(textBox.querySelector('svg')).not.toBeNull()
  textBox.click()
  expect(onAction).toHaveBeenCalledWith('addText')
  for (const action of unsupportedTextActions) {
    const control = textGroup.querySelector<HTMLButtonElement>(`[data-source-action="${action}"]`)!
    expect(control.disabled).toBe(true)
    expect(control.dataset.unavailable).toBe('true')
    expect(control.title).toMatch(/尚无受支持的 editSlides 写回操作/)
  }
  const equation = host.querySelector<HTMLButtonElement>('[data-source-action="onOpenEquation"]')!
  expect(equation.disabled).toBe(true)
  expect(equation.dataset.unavailable).toBe('true')
  ribbon.dispose()
})

it('dispatches selected text formatting and keeps unsupported paragraph formats unavailable', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  expect(host.querySelector('[data-command="saveRevision"] svg')).not.toBeNull()
  expect(host.querySelector('[data-command="addSlide"] svg')).not.toBeNull()
  const bold = host.querySelector<HTMLButtonElement>('[data-command="bold"]')!
  const italic = host.querySelector<HTMLButtonElement>('[data-command="italic"]')!
  const underline = host.querySelector<HTMLButtonElement>('[data-command="underline"]')!
  const strike = host.querySelector<HTMLButtonElement>('[data-command="strike"]')!
  const fontSize = host.querySelector<HTMLInputElement>('[data-command="fontSize"]')!
  const fontFamily = host.querySelector<HTMLInputElement>('[data-command="fontFamily"]')!
  const fontColor = host.querySelector<HTMLInputElement>('[data-command="fontColor"]')!

  expect(italic.disabled).toBe(true)
  ribbon.setTextFormatEnabled(true)
  bold.click()
  italic.click()
  underline.click()
  strike.click()
  fontSize.value = '24'
  fontSize.dispatchEvent(new Event('change', { bubbles: true }))
  fontFamily.value = 'Arial'
  fontFamily.dispatchEvent(new Event('change', { bubbles: true }))
  fontColor.value = '#123456'
  fontColor.dispatchEvent(new Event('change', { bubbles: true }))

  expect(onAction.mock.calls).toEqual([
    ['bold', true], ['italic', true], ['underline', true], ['strike', true],
    ['fontSize', '24'], ['fontFamily', 'Arial'], ['fontColor', '#123456'],
  ])
  expect(italic.disabled).toBe(false)
  expect(bold.querySelector('svg')).not.toBeNull()
  ribbon.setValue('underline', 'true')
  expect(underline.getAttribute('aria-pressed')).toBe('true')
  expect(host.querySelector<HTMLButtonElement>('[data-command="alignLeft"]')!.disabled).toBe(true)
  ribbon.dispose()
})

it('explains why unavailable upstream commands cannot run and prevents dispatch', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const print = host.querySelector<HTMLButtonElement>('[data-command="print"]')!

  expect(print.disabled).toBe(true)
  expect(print.title).toMatch(/桌面 IPC/)
  print.click()
  expect(onAction).not.toHaveBeenCalled()
  ribbon.dispose()
})

it('only enables animation direction for directional effects and preserves that rule while locked', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  const direction = host.querySelector<HTMLSelectElement>('[data-command="animationDirection"]')!

  ribbon.setValue('animationEffect', 'fade')
  expect(direction.disabled).toBe(true)
  ribbon.setValue('animationEffect', 'wipe')
  expect(direction.disabled).toBe(false)
  ribbon.setLocked(true)
  expect(direction.disabled).toBe(true)
  ribbon.setLocked(false)
  expect(direction.disabled).toBe(false)
  ribbon.setValue('animationEffect', 'appear')
  ribbon.setLocked(true)
  ribbon.setLocked(false)
  expect(direction.disabled).toBe(true)
  ribbon.dispose()
})

it('tracks the pinned GenOffice transition and animation actions against native write support', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const transitionGroup = host.querySelector<HTMLElement>('[aria-label="Transition to This Slide"]')!
  const timingGroup = host.querySelector<HTMLElement>('[aria-label="Timing"]')!
  const transition = transitionGroup.querySelector<HTMLSelectElement>('[data-command="transition"]')!
  const applyAll = timingGroup.querySelector<HTMLButtonElement>('[data-source-action="onTransition"]')!
  const animationTab = host.querySelector<HTMLButtonElement>('[data-ribbon-tab="animations"]')!

  expect(transition.dataset.sourceAction).toBe('onTransition')
  expect(transition.options.length).toBe(12)
  expect(timingGroup.querySelector('[data-command="transitionDuration"]')).toBeNull()
  expect(timingGroup.querySelector('[data-command="transitionSound"]')).toBeNull()
  expect(applyAll.disabled).toBe(true)
  expect(applyAll.dataset.unavailable).toBe('true')

  animationTab.click()
  const animationPanel = host.querySelector<HTMLElement>('[data-ribbon-panel="animations"]')!
  const animationGroup = animationPanel.querySelector<HTMLElement>('[aria-label="Animation"]')!
  const animationCommands = [...animationPanel.querySelectorAll<HTMLElement>('[data-command]')]
  expect(animationCommands.map(control => control.dataset.command)).toEqual([
    'animationPreview', 'animationNone', 'animationEffect', 'animationDirection',
    'addAnimation', 'toggleAnimationPane', 'animationByParagraph',
    'motionPathRight', 'motionPathDown', 'motionPathDiagonal', 'motionPathCircle', 'motionPathZigzag',
    'animationTrigger', 'animationDuration', 'animationDelay',
  ])
  expect(animationGroup.querySelector('[data-source-action="onApplyAnimation"]')).not.toBeNull()
  expect(animationGroup.querySelector<HTMLElement>('[data-source-action="onAddAnimation"]')?.dataset.command).toBe('addAnimation')
  expect(animationPanel.querySelector<HTMLElement>('[data-source-action="onAnimTiming"]')?.dataset.command).toBe('animationTrigger')
  expect(animationPanel.querySelector('[data-command="animationPreview"]')?.getAttribute('data-unavailable')).toBe('true')
  expect(animationPanel.querySelector('[data-command="motionPathRight"]')?.getAttribute('data-unavailable')).toBe('true')
  expect(animationGroup.querySelector('[data-command="toggleAnimationPane"]')?.getAttribute('data-unavailable')).toBe('true')
  expect(animationGroup.querySelector('[data-command="animationByParagraph"]')?.getAttribute('data-unavailable')).toBe('true')

  transition.value = 'wipe'
  transition.dispatchEvent(new Event('change', { bubbles: true }))
  expect(onAction).toHaveBeenCalledWith('transition', 'wipe')
  ribbon.dispose()
})
