import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesNativeRibbon, stepNativeFontSize } from './slides-native-ribbon'

afterEach(() => document.body.replaceChildren())

it('大纲和阅读视图接入源onViewMode并保持四个入口互斥', () => {
  const host = document.body.appendChild(document.createElement('div')), onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  for (const command of ['outlineView', 'readingView']) {
    const button = host.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)
    expect(button).not.toBeNull()
    expect(button!.disabled).toBe(false)
    expect(button!.dataset.sourceAction).toBe('onViewMode')
    button!.click(); expect(onAction).toHaveBeenLastCalledWith(command, true)
  }
  for (const command of ['normalView', 'outlineView', 'slideSorter', 'readingView']) ribbon.setValue(command, String(command === 'outlineView'))
  expect([...host.querySelectorAll('[data-source-action="onViewMode"][aria-pressed="true"]')].map(el => el.getAttribute('data-command'))).toEqual(['outlineView'])
  ribbon.dispose()
})

it('普通和排序视图是可执行的互斥视图入口，状态不要求写回文件', () => {
  const host = document.body.appendChild(document.createElement('div')), onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  for (const command of ['normalView', 'slideSorter']) {
    const button = host.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!
    expect(button.disabled).toBe(false)
    button.click(); expect(onAction).toHaveBeenLastCalledWith(command, true)
  }
  ribbon.setValue('normalView', 'false'); ribbon.setValue('slideSorter', 'true')
  expect(host.querySelector('[data-command="slideSorter"]')!.getAttribute('aria-pressed')).toBe('true')
  expect(host.querySelector('[data-command="normalView"]')!.getAttribute('aria-pressed')).toBe('false')
  ribbon.dispose()
})

const chartGalleryState = { target: 'rev1:0:chart', kind: 'bar' as const,
  style: { legendPos: 'b' as const, dataLabels: false, gridlines: true, gapWidthPct: 150 },
  colorSchemes: [{key:'default' as const,label:'主题默认',colors:[]},{key:'warm' as const,label:'暖色',colors:['#ED7D31','#FFC000','#FF0000','#C55A11','#833C00']}] }

it('图表图库显示源缩略图并按实际样式标记当前预设，点击委托既有编辑动作',()=>{
 const host=document.body.appendChild(document.createElement('div')),onAction=vi.fn()
 const ribbon=createSlidesNativeRibbon(host,{onAction})
 ribbon.setContext('chart');ribbon.setChartDesign(chartGalleryState)
 const cards=host.querySelectorAll<HTMLButtonElement>('[data-chart-preset-card]')
 expect(cards).toHaveLength(10)
 expect(cards[0]!.querySelector('svg')?.getAttribute('viewBox')).toBe('0 0 64 40')
 expect(cards[0]!.querySelectorAll('svg rect')).toHaveLength(8)
 expect(host.querySelector('[data-chart-preset-card="grid"]')?.getAttribute('aria-pressed')).toBe('true')
 host.querySelector<HTMLButtonElement>('[data-chart-preset-card="bold"]')!.click()
 expect(onAction).toHaveBeenCalledWith('chartStylePreset','bold')
 ribbon.setChartDesign({...chartGalleryState,kind:'line',style:{...chartGalleryState.style,gapWidthPct:50}})
 expect(host.querySelector('[data-chart-preset-card="classic"]')!.querySelectorAll('polyline')).toHaveLength(2)
 expect([...host.querySelectorAll('[data-chart-preset-card][aria-pressed="true"]')].map(el=>el.getAttribute('data-chart-preset-card'))).toEqual(['grid','bold','slim'])
 ribbon.setChartDesign({...chartGalleryState,kind:'doughnut'})
 expect(host.querySelector('[data-chart-preset-card="classic"]')!.querySelectorAll('circle')).toHaveLength(2)
 ribbon.dispose()
})

it('图表配色卡片显示来源前四色，选择关闭菜单且旧菜单不能跨对象写入',()=>{
 const host=document.body.appendChild(document.createElement('div')),onAction=vi.fn()
 const ribbon=createSlidesNativeRibbon(host,{onAction})
 ribbon.setContext('chart');ribbon.setChartDesign(chartGalleryState)
 const toggle=host.querySelector<HTMLButtonElement>('[data-chart-colors-toggle]')!
 expect(toggle).not.toBeNull();toggle.click()
 const menu=document.querySelector<HTMLElement>('[data-chart-colors-menu]')!
 expect(menu.hidden).toBe(false)
 const warm=menu.querySelector<HTMLButtonElement>('[data-chart-scheme-card="warm"]')!
 expect(warm.querySelectorAll('.rb-chart-scheme-dot')).toHaveLength(4)
 warm.click();expect(menu.hidden).toBe(true)
 expect(onAction).toHaveBeenCalledWith('chartColorScheme','warm')
 toggle.click()
 const stale=menu.querySelector<HTMLButtonElement>('[data-chart-scheme-card="warm"]')!
 ribbon.setChartDesign({...chartGalleryState,target:'rev1:0:other'})
 expect(menu.hidden).toBe(true);toggle.click();stale.click()
 expect(onAction).toHaveBeenCalledTimes(1)
 ribbon.setLocked(true)
 expect(toggle.disabled).toBe(true)
 expect([...host.querySelectorAll<HTMLButtonElement>('[data-chart-preset-card]')].every(card=>card.disabled)).toBe(true)
 ribbon.setLocked(false);ribbon.setChartDesign(null)
 expect(toggle.disabled).toBe(true)
 ribbon.dispose();expect(document.querySelector('[data-chart-colors-menu]')).toBeNull()
})

it('图表配色菜单支持Escape、点外部和切换功能区关闭，不产生编辑',()=>{
 const host=document.body.appendChild(document.createElement('div')),onAction=vi.fn()
 const ribbon=createSlidesNativeRibbon(host,{onAction})
 ribbon.setContext('chart');ribbon.setChartDesign(chartGalleryState)
 host.querySelector<HTMLButtonElement>('[data-ribbon-tab="chartDesign"]')!.click()
 const toggle=host.querySelector<HTMLButtonElement>('[data-chart-colors-toggle]')!
 toggle.click()
 const menu=document.querySelector<HTMLElement>('[data-chart-colors-menu]')!
 menu.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))
 expect(menu.hidden).toBe(true);expect(document.activeElement).toBe(toggle)
 const outside=document.body.appendChild(document.createElement('button'))
 outside.addEventListener('pointerdown',event=>event.stopPropagation())
 toggle.click();outside.dispatchEvent(new Event('pointerdown',{bubbles:true}))
 expect(menu.hidden).toBe(true)
 toggle.click();host.querySelector<HTMLButtonElement>('[data-ribbon-tab="home"]')!.click()
 expect(menu.hidden).toBe(true)
 toggle.click();ribbon.setContext('shape');expect(menu.hidden).toBe(true)
 expect(onAction).not.toHaveBeenCalled();ribbon.dispose()
})

it('图表配色卡片可在浮层内滚动，页面或功能区滚动时关闭旧锚点',()=>{
 const host=document.body.appendChild(document.createElement('div'))
 const ribbon=createSlidesNativeRibbon(host,{onAction:vi.fn()})
 ribbon.setContext('chart');ribbon.setChartDesign(chartGalleryState)
 host.querySelector<HTMLButtonElement>('[data-chart-colors-toggle]')!.click()
 const menu=document.querySelector<HTMLElement>('[data-chart-colors-menu]')!
 menu.dispatchEvent(new Event('scroll'))
 expect(menu.hidden).toBe(false)
 const toggle=host.querySelector<HTMLButtonElement>('[data-chart-colors-toggle]')!
 vi.spyOn(toggle,'getBoundingClientRect').mockReturnValue({left:20,top:10,width:100,height:30} as DOMRect)
 window.dispatchEvent(new Event('scroll'));expect(menu.hidden).toBe(true)
 ribbon.dispose()
})

it('图表配色浮层忽略打开前延迟送达的滚动和resize，只在锚点实际移动后关闭',()=>{
 const host=document.body.appendChild(document.createElement('div'))
 const ribbon=createSlidesNativeRibbon(host,{onAction:vi.fn()})
 ribbon.setContext('chart');ribbon.setChartDesign(chartGalleryState)
 const toggle=host.querySelector<HTMLButtonElement>('[data-chart-colors-toggle]')!
 const rect=vi.spyOn(toggle,'getBoundingClientRect').mockReturnValue({left:20,top:10,bottom:40,width:100,height:30} as DOMRect)
 toggle.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}))
 const menu=document.querySelector<HTMLElement>('[data-chart-colors-menu]')!
 host.querySelector('.rb-chart-style-row')!.dispatchEvent(new Event('scroll'))
 window.dispatchEvent(new Event('scroll'));window.dispatchEvent(new Event('resize'))
 expect(menu.hidden).toBe(false)
 rect.mockReturnValue({left:10,top:10,bottom:40,width:100,height:30} as DOMRect)
 host.dispatchEvent(new Event('scroll'))
 expect(menu.hidden).toBe(true)
 toggle.click()
 const originalWidth=window.innerWidth
 try {
   window.innerWidth=originalWidth-1
   window.dispatchEvent(new Event('resize'))
   expect(menu.hidden).toBe(true)
 } finally { window.innerWidth=originalWidth }
 ribbon.dispose()
})

it('初始只读的图表图库不能因来源回填而重新启用',()=>{
 const host=document.body.appendChild(document.createElement('div'))
 const ribbon=createSlidesNativeRibbon(host,{onAction:vi.fn(),locked:true})
 ribbon.setContext('chart');ribbon.setChartDesign(chartGalleryState)
 expect(host.querySelector<HTMLButtonElement>('[data-chart-colors-toggle]')!.disabled).toBe(true)
 expect([...host.querySelectorAll<HTMLButtonElement>('[data-chart-preset-card]')].every(card=>card.disabled)).toBe(true)
 ribbon.dispose()
})

it('字体功能区只提供排版控件，正文由画布和对象面板编辑', () => {
  const host = document.body.appendChild(document.createElement('div'))
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const font = host.querySelector('[data-ribbon-group=Font]')!
  expect(font.querySelector('textarea, [data-command=text]')).toBeNull()
  expect(font.querySelectorAll('.slides-ribbon-toggle-label')).toHaveLength(4)
  expect([...font.querySelectorAll('[data-command]')].slice(0, 2).map(control => control.getAttribute('data-command'))).toEqual(['fontFamily', 'fontSize'])
  ribbon.setTextFormatEnabled(true)
  ribbon.setValue('fontFamily', 'Arial')
  ribbon.setValue('fontSize', '24')
  expect(font.querySelector<HTMLInputElement>('[data-command=fontFamily]')!.value).toBe('Arial')
  expect(font.querySelector<HTMLInputElement>('[data-command=fontSize]')!.value).toBe('24')
  font.querySelector<HTMLButtonElement>('[data-command=bold]')!.click()
  expect(onAction).toHaveBeenCalledWith('bold', true)
  ribbon.dispose()
})

it('提供来源组合和取消组合动作，以及两个只读静态放映入口', () => {
  const host = document.body.appendChild(document.createElement('div')), onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  for (const [command, source] of [['groupObjects', 'groupSelected'], ['ungroupObjects', 'ungroupSelected'], ['startShow', 'onSlideShow'], ['startShowCurrent', 'onSlideShow']]) {
    const control = host.querySelector<HTMLButtonElement>('[data-command="' + command + '"]')!
    expect(control, command).not.toBeNull()
    expect(control.disabled, command).toBe(false)
    expect(control.dataset.sourceAction).toBe(source)
    expect(control.querySelector('svg')).not.toBeNull()
    control.click()
  }
  expect(onAction.mock.calls.map(([command]) => command)).toEqual(['groupObjects', 'ungroupObjects', 'startShow', 'startShowCurrent'])
  expect(host.querySelector<HTMLButtonElement>('[data-command="presenter"]')!.disabled).toBe(true)
  ribbon.dispose()
})

it('新增组合和当前页放映入口采用中文文案', () => {
  document.documentElement.lang = 'zh-CN'
  const host = document.body.appendChild(document.createElement('div'))
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  try {
    for (const [command, label] of [['groupObjects', '组合'], ['ungroupObjects', '取消组合'], ['startShowCurrent', '从当前页开始']]) {
      expect(host.querySelector('[data-command="' + command + '"]')?.textContent).toContain(label)
    }
  } finally { ribbon.dispose(); document.documentElement.lang = '' }
})

it('gives every command button a semantic decorative SVG without changing its accessible name', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  const buttons = [...host.querySelectorAll<HTMLButtonElement>('button[data-command]')]
  expect(buttons.length).toBeGreaterThan(70)
  expect(buttons.filter(button => !button.querySelector('svg')).map(button => button.dataset.command)).toEqual([])
  for (const button of buttons) {
    const glyphs = [...button.querySelectorAll('svg')]
    expect(glyphs).toHaveLength(1)
    expect(glyphs[0]!.getAttribute('aria-hidden'), button.dataset.command).toBe('true')
    expect(glyphs[0]!.querySelector('title, desc')).toBeNull()
    const text = button.cloneNode(true) as HTMLButtonElement
    text.querySelectorAll('svg').forEach(glyph => glyph.remove())
    const visibleLabel = text.textContent!.trim()
    expect(visibleLabel, button.dataset.command).not.toBe('')
    const accessibleLabel = button.getAttribute('aria-label')!
    expect(accessibleLabel.startsWith(visibleLabel), button.dataset.command).toBe(true)
    if (button.dataset.unavailable !== 'true') expect(accessibleLabel).toBe(visibleLabel)
  }
  expect(host.querySelector<HTMLButtonElement>('[data-command="print"]')!.disabled).toBe(false)
  ribbon.dispose()
})

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

it('preserves GenOffice Home clipboard action IDs and source glyphs for enabled browser adapters', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  const sourceActions = ['onPaste', 'onCut', 'onCopy', 'onFormatBrushClick']

  expect(host.querySelector('[aria-label="Clipboard"]')).not.toBeNull()
  for (const sourceId of sourceActions) {
    const control = host.querySelector<HTMLButtonElement>(`[data-source-action="${sourceId}"]`)!
    expect(control.disabled).toBe(false)
    expect(control.dataset.unavailable).toBeUndefined()
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

it('localizes visible slide ribbon tabs, groups and controls in Simplified Chinese without dropping icons', () => {
  const host = document.createElement('div')
  document.body.append(host)
  document.documentElement.lang = 'zh-CN'
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })

  expect([...host.querySelectorAll('[role=tab]:not([hidden])')].map(tab => tab.textContent)).toEqual([
    '文件', '开始', '插入', '绘图', '设计', '切换', '动画', '幻灯片放映', '审阅', '视图',
  ])
  expect(host.querySelector('[aria-label="幻灯片"]')).not.toBeNull()
  expect(host.querySelector('[data-command="addSlide"]')?.textContent).toContain('新建幻灯片')
  expect(host.querySelector('[data-command="insertTable"] svg')).not.toBeNull()
  expect(host.querySelector('[data-command="insertTable"]')?.textContent).toContain('表格')
  const transition = host.querySelector<HTMLSelectElement>('[data-command="transition"]')!
  expect(transition.options[0].textContent).toBe('无')
  expect(transition.options[1].textContent).toBe('平滑')
  expect(transition.options[1].value).toBe('morph')
  ribbon.setContext('table')
  expect(host.querySelector('[data-ribbon-tab="tableDesign"]')?.textContent).toBe('表格设计')
  expect(host.querySelector('[aria-label="表格样式"]')).not.toBeNull()
  ribbon.setContext('shape')
  expect(host.querySelector('[data-ribbon-tab="shapeFormat"]')?.textContent).toBe('形状格式')
  expect(host.querySelector('[aria-label="形状样式"]')).not.toBeNull()
  ribbon.dispose()
  document.documentElement.lang = ''
})

it('preserves the pinned Review Comments actions and gates writes on source availability and save lock', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const comments = host.querySelector<HTMLElement>('[aria-label="Comments"]')!
  const controls = [...comments.querySelectorAll<HTMLButtonElement>('[data-source-action]')]

  expect(controls.map(control => control.dataset.sourceAction)).toEqual(['onNewComment', 'onToggleComments'])
  expect(controls[0]!.disabled).toBe(true)
  expect(controls[1]!.disabled).toBe(false)
  expect(controls.every(control => control.querySelector('svg'))).toBe(true)
  ribbon.setCommentEditEnabled(true)
  controls[0]!.click(); controls[1]!.click()
  expect(onAction.mock.calls.map(([command]) => command)).toEqual(['newComment', 'commentsPane'])
  ribbon.setValue('commentsPane', 'true')
  expect(controls[1]!.getAttribute('aria-pressed')).toBe('true')
  ribbon.setCommentEditEnabled(false, '来源只读')
  expect(controls[0]!.disabled).toBe(true); expect(controls[0]!.title).toBe('来源只读')
  ribbon.setLocked(true); expect(controls.every(control => control.disabled)).toBe(true)
  ribbon.setLocked(false); expect(controls[0]!.disabled).toBe(true); expect(controls[1]!.disabled).toBe(false)
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
    const unsupported = controls.filter(control => !['onPickShape', 'onInsertTable', 'onInsertChart', 'onInsertSmartArt'].includes(control.dataset.sourceAction!))
    expect(unsupported.every(control => control.disabled && control.dataset.unavailable === 'true')).toBe(true)
    expect(unsupported.every(control => control.querySelector('svg'))).toBe(true)
  }
  // Chart 已接通（固定源 13 种图表）
  const chartPicker = host.querySelector<HTMLSelectElement>('select[data-command="insertChart"]')!
  expect(chartPicker.disabled).toBe(false)
  expect([...chartPicker.options].slice(1).map(option => option.value)).toEqual(['bar', 'barStacked', 'barPercentStacked', 'barH', 'bar3D', 'line', 'area', 'pie', 'pie3D', 'doughnut', 'scatter', 'radar', 'comboBarLine'])
  // Table 已接通（行列对话框）
  expect(host.querySelector<HTMLButtonElement>('[data-source-action="onInsertTable"]')!.disabled).toBe(false)
  // Shapes 已接通：固定源形状库 7 组 109 个预设
  const shapes = host.querySelector<HTMLSelectElement>('select[data-command="insertShape"]')!
  expect(shapes.closest('[data-source-action]')?.getAttribute('data-source-action') ?? shapes.dataset.sourceAction).toBe('onPickShape')
  expect(shapes.disabled).toBe(false)
  expect(shapes.querySelectorAll('optgroup')).toHaveLength(7)
  expect(shapes.querySelectorAll('optgroup option')).toHaveLength(109)
  const images = host.querySelector<HTMLElement>('[aria-label="Images"]')!
  const picture = images.querySelector<HTMLButtonElement>('[data-source-action="onInsertImage"]')!
  expect(picture.disabled).toBe(false)
  expect(picture.dataset.unavailable).toBeUndefined()
  expect(picture.querySelector('svg')).not.toBeNull()
  // SmartArt 已接通：固定源 7 种布局
  const smartArt = host.querySelector<HTMLSelectElement>('select[data-command="insertSmartArt"]')!
  expect(smartArt.disabled).toBe(false)
  expect([...smartArt.options].slice(1).map(option => option.textContent)).toEqual(['垂直列表', '基本流程', '基本循环', '组织结构', '基本棱锥图', '基本矩阵', '基本维恩图'])
  ribbon.dispose()
})

it('connects the source text-box and Unicode equation actions while retaining unsupported Insert Text actions', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const textGroup = host.querySelector<HTMLElement>('.slides-native-ribbon-group[aria-label="Text"]')!
  const textBox = textGroup.querySelector<HTMLButtonElement>('[data-command="addText"]')!
  const unsupportedTextActions: string[] = []
  const wordArt = textGroup.querySelector<HTMLSelectElement>('select[data-command="insertWordArt"]')!
  expect(wordArt.disabled).toBe(false)
  expect([...wordArt.options].slice(1).map(option => option.textContent)).toEqual(['填充：蓝色', '填充：金色', '填充：深红', '填充：紫色', '填充：绿色；斜体', '填充：白色；描边：橙色', '填充：白色；描边：深红', '填充：金色；描边：棕色', '填充：天蓝；描边：藏青', '填充：藏青；描边：白色', '填充：黑色；描边：金色', '填充：银色；描边：深灰'])
  expect(textGroup.querySelector<HTMLButtonElement>('[data-source-action="onOpenHeaderFooter"]')!.disabled).toBe(false)
  // 日期与页码字段已接通（固定源 insertField）
  for (const action of ['onInsertField:datetime', 'onInsertField:slidenum']) expect(textGroup.querySelector<HTMLButtonElement>(`[data-source-action="${action}"]`)!.disabled).toBe(false)

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
  expect(equation.disabled).toBe(false)
  expect(equation.dataset.unavailable).toBeUndefined()
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
  expect(host.querySelector<HTMLButtonElement>('[data-command="alignLeft"]')!.disabled).toBe(false)
  ribbon.dispose()
})

it('explains why unavailable upstream commands cannot run and prevents dispatch', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const unavailable = host.querySelector<HTMLButtonElement>('[data-command="exportImages"]')!

  expect(unavailable.disabled).toBe(true)
  expect(unavailable.title).toMatch(/写回操作/)
  unavailable.click()
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
  expect(applyAll.dataset.unavailable).toBeUndefined()
  ribbon.setTransitionApplyAllEnabled(true)
  expect(applyAll.disabled).toBe(false)
  applyAll.click()
  expect(onAction).toHaveBeenCalledWith('applyTransitionAll')
  ribbon.setLocked(true); expect(applyAll.disabled).toBe(true)
  ribbon.setLocked(false); expect(applyAll.disabled).toBe(false)
  ribbon.setTransitionApplyAllEnabled(false); expect(applyAll.disabled).toBe(true)

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
  expect(animationPanel.querySelector('[data-command="animationPreview"]')?.getAttribute('data-unavailable')).toBeNull()
  // 整页动画序列接通后：无、动画窗格、按段与五条动作路径均可用，并派发各自命令
  for (const command of ['animationNone', 'toggleAnimationPane', 'animationByParagraph', 'motionPathRight', 'motionPathDown', 'motionPathDiagonal', 'motionPathCircle', 'motionPathZigzag']) {
    const control = animationPanel.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!
    expect(control.dataset.unavailable, command).toBeUndefined()
    control.click()
    expect(onAction, command).toHaveBeenCalledWith(command)
  }
  expect(animationPanel.querySelector<HTMLElement>('[data-command="motionPathZigzag"]')?.dataset.sourceAction).toBe('onApplyMotionPath')
  ribbon.setValue('toggleAnimationPane', 'true'); ribbon.setValue('animationByParagraph', 'true')
  expect(animationGroup.querySelector('[data-command="toggleAnimationPane"]')?.getAttribute('aria-pressed')).toBe('true')
  expect(animationGroup.querySelector('[data-command="animationByParagraph"]')?.getAttribute('aria-pressed')).toBe('true')

  transition.value = 'wipe'
  transition.dispatchEvent(new Event('change', { bubbles: true }))
  expect(onAction).toHaveBeenCalledWith('transition', 'wipe')
  ribbon.dispose()
})

it('uses source paragraph formatting actions, spacing presets and Enter-only point inputs with target and lock gates', () => {
  const host = document.createElement('div'); document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const line = host.querySelector<HTMLSelectElement>('[data-command="lineSpacingPct"]')!
  const before = host.querySelector<HTMLInputElement>('[data-command="spaceBeforePt"]')!
  expect([...line.options].map(option => option.value)).toEqual(['', '100', '115', '150', '200', '250', '300'])
  expect(line.dataset.sourceAction).toBe('onParagraphFormat')
  expect(before.dataset.sourceAction).toBe('onParagraphFormat')
  expect(line.disabled).toBe(true); expect(before.disabled).toBe(true)
  ribbon.setTextFormatEnabled(true)
  expect(line.disabled).toBe(false); expect(before.disabled).toBe(false)
  before.value = '12,5'
  before.dispatchEvent(new Event('change', { bubbles: true }))
  expect(onAction).not.toHaveBeenCalled()
  before.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  expect(onAction).toHaveBeenLastCalledWith('spaceBeforePt', '12,5')
  ribbon.setLocked(true)
  expect(line.disabled).toBe(true); expect(before.disabled).toBe(true)
  ribbon.setLocked(false); ribbon.setTextFormatEnabled(false)
  expect(line.disabled).toBe(true); expect(before.disabled).toBe(true)
  ribbon.dispose()
})

it('exposes all pinned list options, disabled picture picking and honest conditional availability', () => {
  const host = document.createElement('div'); document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const select = (id: string) => host.querySelector<HTMLSelectElement>(`[data-command="${id}"]`)!
  const options = (id: string) => [...select(id).options].map(option => option.value).filter(Boolean)
  expect(options('bulletCharPreset')).toEqual(['0', '1', '2', '3', '4', '5', '6'])
  expect(options('bulletSymbol')).toHaveLength(16)
  expect(options('numType')).toHaveLength(9)
  expect(options('bulletHangEmu')).toEqual(['171450', '285750', '342900'])
  expect(options('bulletSizePct')).toEqual(['75', '90', '100', '125', '150'])
  expect(options('bulletColorPreset')).toHaveLength(10)
  const picture = host.querySelector<HTMLButtonElement>('[data-command="pictureBullet"]')!
  expect(picture.disabled).toBe(true); expect(picture.title).toContain('上传')
  ribbon.setTextFormatEnabled(true)
  expect(select('bulletCharPreset').disabled).toBe(false)
  expect(select('bulletSizePct').disabled).toBe(true)
  expect(host.querySelector<HTMLInputElement>('[data-command="startAt"]')!.disabled).toBe(true)
  ribbon.setListTargets({ bullets: true, numbers: true, hanging: true })
  expect(select('bulletSizePct').disabled).toBe(false)
  const color = host.querySelector<HTMLInputElement>('[data-command="bulletColor"]')!
  ribbon.setValue('bulletColor', '', '未设置或混合值')
  expect(color.getAttribute('aria-valuetext')).toBe('未设置或混合值')
  expect(color.style.opacity).toBe('0')
  expect(color.parentElement!.textContent).toContain('未设置或混合值')
  ribbon.setValue('bulletColor', '#7030A0')
  expect(color.style.opacity).toBe('1')
  expect(color.parentElement!.textContent).toContain('#7030A0')
  const custom = host.querySelector<HTMLInputElement>('[data-command="bulletCustomChar"]')!
  custom.value = '😀'; custom.dispatchEvent(new Event('change'))
  expect(onAction).not.toHaveBeenCalled()
  custom.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  expect(onAction).toHaveBeenCalledWith('bulletCustomChar', '😀')
  ribbon.setValue('paragraphDirection', '')
  expect(host.querySelector('[data-command="directionLtr"]')!.getAttribute('aria-pressed')).toBe('false')
  ribbon.setValue('paragraphDirection', 'false')
  expect(host.querySelector('[data-command="directionLtr"]')!.getAttribute('aria-pressed')).toBe('true')
  ribbon.setLocked(true)
  for (const control of host.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement>('[data-source-action="onParagraphFormat"], [data-source-action="onDirection"]')) expect(control.disabled).toBe(true)
  ribbon.setLocked(false)
  expect(picture.disabled).toBe(true)
  ribbon.dispose()
})

it('retains source transition editability across lock/unlock independently of Apply to All', () => {
  const host = document.createElement('div'); document.body.append(host)
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  const select = host.querySelector<HTMLSelectElement>('[data-command="transition"]')!
  expect(select.disabled).toBe(true)
  ribbon.setTransitionEditEnabled(true); expect(select.disabled).toBe(false)
  ribbon.setLocked(true); expect(select.disabled).toBe(true)
  ribbon.setLocked(false); expect(select.disabled).toBe(false)
  ribbon.setTransitionEditEnabled(false, '来源无法保真'); ribbon.setLocked(true); ribbon.setLocked(false)
  expect(select.disabled).toBe(true); expect(select.title).toBe('来源无法保真')
  ribbon.dispose()
})

it('enables the pinned New Slide command on Home and Insert and dispatches addSlide', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const commands = [...host.querySelectorAll<HTMLButtonElement>('[data-command="addSlide"]')]
  expect(commands).toHaveLength(2)
  for (const command of commands) {
    expect(command.dataset.sourceAction).toBe('onAddSlide')
    expect(command.disabled).toBe(false)
    command.click()
  }
  expect(onAction.mock.calls.map(call => call[0])).toEqual(['addSlide', 'addSlide'])
  ribbon.setLocked(true)
  expect(commands.every(command => command.disabled)).toBe(true)
  ribbon.dispose()
})

it('offers New Slide with Layout as a layout picker that dispatches the chosen path and resets', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction, layouts: [{ path: 'ppt/slideLayouts/slideLayout1.xml', name: 'Title Slide', layoutType: 'title', placeholders: [] }, { path: 'ppt/slideLayouts/slideLayout2.xml', name: 'Title and Content', layoutType: 'obj', placeholders: [] }] as never })
  const picker = host.querySelector<HTMLSelectElement>('select[data-command="addSlideWithLayout"]')!
  expect(picker.dataset.sourceAction ?? picker.closest('[data-source-action]')?.getAttribute('data-source-action')).toBe('onAddSlideWithLayout')
  expect([...picker.options].map(option => option.value)).toEqual(['', 'ppt/slideLayouts/slideLayout1.xml', 'ppt/slideLayouts/slideLayout2.xml'])
  picker.value = 'ppt/slideLayouts/slideLayout2.xml'; picker.dispatchEvent(new Event('change'))
  expect(onAction).toHaveBeenCalledWith('addSlideWithLayout', 'ppt/slideLayouts/slideLayout2.xml')
  expect(picker.value).toBe('')
  ribbon.setLayouts([{ path: 'ppt/slideLayouts/slideLayout7.xml', name: 'Blank' }])
  expect([...picker.options].map(option => option.textContent)).toEqual(['新建指定版式幻灯片…', 'Blank'])
  ribbon.dispose()
})

it('enables the pinned Reset Layout command', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const command = host.querySelector<HTMLButtonElement>('[data-command="resetLayout"]')!
  expect(command.dataset.sourceAction).toBe('onResetLayout')
  expect(command.disabled).toBe(false)
  command.click()
  expect(onAction).toHaveBeenCalledWith('resetLayout')
  ribbon.dispose()
})

it('enables the Shape Format fill and outline controls with their source actions', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  ribbon.setContext('shape')
  const fill = host.querySelector<HTMLInputElement>('input[data-command="shapeFill"]')!
  const width = host.querySelector<HTMLSelectElement>('select[data-command="shapeOutlineWidth"]')!
  expect(fill.disabled).toBe(false)
  expect([...width.options].map(option => option.value)).toEqual(['0.75', '1', '1.5', '2.25', '3', '4.5', '6'])
  fill.value = '#2e7d32'; fill.dispatchEvent(new Event('change'))
  host.querySelector<HTMLButtonElement>('[data-command="shapeNoOutline"]')!.click()
  expect(onAction).toHaveBeenCalledWith('shapeFill', '#2e7d32')
  expect(onAction).toHaveBeenCalledWith('shapeNoOutline')
  const change = host.querySelector<HTMLSelectElement>('select[data-command="changeShape"]')!
  expect(change.disabled).toBe(false)
  expect([...change.querySelectorAll('optgroup option')].map(option => (option as HTMLOptionElement).value)).not.toContain('lineArrow')
  change.value = 'hexagon'; change.dispatchEvent(new Event('change'))
  expect(onAction).toHaveBeenCalledWith('changeShape', 'hexagon')
  expect(change.value).toBe('')
  ribbon.dispose()
})

it('enables the pinned Add Section command', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onAction = vi.fn()
  const ribbon = createSlidesNativeRibbon(host, { onAction })
  const command = host.querySelector<HTMLButtonElement>('[data-command="addSection"]')!
  expect(command.dataset.sourceAction).toBe('onAddSection')
  expect(command.disabled).toBe(false)
  command.click()
  expect(onAction).toHaveBeenCalledWith('addSection')
  ribbon.dispose()
})

it('段落区先呈现列表与对齐，参数输入对齐且保留完整提示', () => {
  const host = document.body.appendChild(document.createElement('div'))
  const ribbon = createSlidesNativeRibbon(host, { onAction: vi.fn() })
  const group = host.querySelector('[data-ribbon-group=Paragraph]')!
  const commands = [...group.querySelectorAll('[data-command]')].map(control => control.getAttribute('data-command'))
  expect(commands.slice(0, 7)).toEqual(['bulletChar', 'bulletNumber', 'bulletNone', 'paragraphAlignLeft', 'paragraphAlignCenter', 'paragraphAlignRight', 'paragraphAlignJustify'])
  expect(group.querySelector('[data-command=bulletCharPreset]')?.parentElement?.className).toBe('slides-ribbon-field')
  for (const command of ['bulletChar', 'indentIncrease', 'paragraphAlignLeft']) {
    const control = group.querySelector<HTMLElement>('[data-command='+command+']')!
    expect(control.title).toContain(control.getAttribute('aria-label'))
  }
  ribbon.dispose()
})

it('uses second-level headings for ribbon groups under the document title', () => {
 const host=document.body.appendChild(document.createElement('main'))
 const title=host.appendChild(document.createElement('h1'));title.textContent='智能报告'
 const ribbon=createSlidesNativeRibbon(host,{onAction:()=>{}})
 const groups=host.querySelectorAll('.slides-native-ribbon-group')
 expect(groups.length).toBeGreaterThan(0)
 for(const group of groups)expect(group.querySelector('h2')).not.toBeNull()
 expect(host.querySelector('.slides-native-ribbon-group h3')).toBeNull()
 ribbon.dispose()
})

it('dispatches browser printing and prevents it while the host is locked',()=>{
 const host=document.createElement('div'),onAction=vi.fn(),ribbon=createSlidesNativeRibbon(host,{onAction});document.body.append(host)
 const print=host.querySelector<HTMLButtonElement>('[data-command="print"]')!;expect(print.disabled).toBe(false);print.click();expect(onAction).toHaveBeenCalledWith('print')
 ribbon.setLocked(true);print.click();expect(onAction).toHaveBeenCalledTimes(1);ribbon.dispose()
})
