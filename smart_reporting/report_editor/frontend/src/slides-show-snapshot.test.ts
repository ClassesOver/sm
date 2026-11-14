import { expect, it } from 'vitest'
import type { RenderSlide } from '@genoffice/pptx-render'
import { slidesShowSnapshot } from './slides-show-snapshot'

const render = [{ nodes: [{ type: 'group', sourceId: 'g', children: [{ type: 'shape', sourceId: 'a' }] }, { type: 'shape', sourceId: 'decoration', decoration: true }] }] as unknown as RenderSlide[]
const elements = [{ id: 'a', name: '真实来源名称' }]

it('完整快照使用真实名称和组内sourceId，保留来源分步与方向/路径，不生成虚构cNvPr键', () => {
  const model = [{ elements, transition: 'morph', animations: [
    { spid: 2, elementId: 'a', effect: 'wipe', trigger: 'withPrev', durationMs: 640, delayMs: 120, direction: 'top' },
    { spid: 2, elementId: 'a', effect: 'motionPath', trigger: 'afterPrev', motionPath: 'M 0 0 L 0.25 0', durationMs: 500 },
  ] }]
  const before = JSON.stringify({ render, model }), result = slidesShowSnapshot(render, model)
  expect(result.animations![0]).toEqual([
    { sourceId: 'a', targetName: 'a', effect: 'wipe', trigger: 'withPrev', durationMs: 640, delayMs: 120, direction: 'top' },
    { sourceId: 'a', targetName: 'a', effect: 'motionPath', trigger: 'afterPrev', durationMs: 500, delayMs: 0, motionPath: 'M 0 0 L 0.25 0' },
  ])
  expect(result.shapeKeys).toEqual([[{ sourceId: 'a', spid: null, name: '真实来源名称' }]])
  expect(result.transitions).toEqual(['morph']); expect(result.warnings!.join('；')).toContain('变形转场')
  expect(JSON.stringify({ render, model })).toBe(before)
})

it('来源未建模预设、媒体、装饰和失配对象不被假装播放，返回具体缺口', () => {
  const result = slidesShowSnapshot(render, [{ elements, transition: 'unmodeled', animations: [
    { elementId: 'a', effect: 'fade', trigger: 'onClick', presetXml: '<p:par/>' },
    { elementId: 'a', effect: 'mediaPlay', trigger: 'onClick' },
    { elementId: 'missing', effect: 'fade', trigger: 'onClick' },
    { elementId: 'decoration', effect: 'fade', trigger: 'onClick' },
  ] }])
  expect(result.animations).toEqual([[]]); expect(result.transitions).toEqual(['none'])
  const messages = result.warnings!.join('；')
  for (const reason of ['来源预设', '音视频', '渲染快照', '来源转场', '演讲者', '自动换页', '文字内链接']) expect(messages).toContain(reason)
})

it('链接只使用实际对象元数据中的合法URL、页号与来源命名动作', () => {
  const links = [
    { kind: 'url', url: 'https://example.test/slides?q=1' }, { kind: 'url', url: 'mailto:slides@example.test' },
    { kind: 'slide', slideIndex: 0 }, { kind: 'action', action: 'lastslideviewed' },
    { kind: 'url', url: 'javascript:alert(1)' }, { kind: 'url', url: 'https://example.test/a b' },
    { kind: 'url', url: 'https://example.test/\\evil' }, { kind: 'slide', slideIndex: 1 }, { kind: 'action', action: 'unknown' },
  ]
  const result = slidesShowSnapshot(render, [{ elements: links.map((elementLink, i) => ({ id: `link-${i}`, name: `Link ${i}`, elementLink })) } as any])
  expect(result.links![0]).toEqual(links.slice(0, 4).map((target, i) => ({ sourceId: `link-${i}`, target })))
  expect(result.warnings!.join('；')).toContain('无效的来源链接')
})

it('模型页面数量或elements失配时拒绝使用不一致快照', () => {
  expect(() => slidesShowSnapshot(render, [])).toThrow('不一致')
  expect(() => slidesShowSnapshot(render, [{} as any])).toThrow('不一致')
})

 it('真实媒体节点的播放暂停停止顺序进入源动画播放器，编辑预览默认仍静音跳过',()=>{
  const slides=[{nodes:[{type:'picture',sourceId:'movie',media:'video'}]}] as unknown as RenderSlide[]
  const animations=['mediaPlay','mediaPause','mediaStop'].map(effect=>({elementId:'movie',effect,trigger:'onClick',durationMs:0,delayMs:0}))
  expect(slidesShowSnapshot(slides,[{elements:[{id:'movie',name:'视频'}],animations}]).animations![0]!.map(item=>item.effect)).toEqual(['mediaPlay','mediaPause','mediaStop'])
 })
