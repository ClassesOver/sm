import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addElement, createBlankPptx, insertBlankSlide, openPptx, savePptx, setSlideBackground } from '@genoffice/pptx-engine'
import { applyBackgroundOps, inspectBackgroundState, validateBackgroundOps } from '../pptx-background-ops.ts'

async function deck() {
  const opened = await openPptx(await createBlankPptx())
  insertBlankSlide(opened, 0); insertBlankSlide(opened, 1)
  setSlideBackground(opened, opened.deck.slides[1]!, '#112233')
  return openPptx(await savePptx(opened))
}
const xml = (opened: Awaited<ReturnType<typeof deck>>, index: number) => new TextDecoder().decode(opened.archive.readBytes(opened.deck.slides[index]!.path)!)

test('渐变、径向、重置与隐藏背景图形经规范 setBackground 写入并可回读', async () => {
  const opened = await deck(), untouched = opened.archive.readBytes(opened.deck.slides[2]!.path)
  assert.deepEqual(inspectBackgroundState(opened, 1), { backgroundOwn: true, backgroundGraphicsHidden: false, backgroundGradient: null })
  const ops = validateBackgroundOps(opened, {
    backgroundGradients: [{ slideIndices: [0], from: '#ff0000', to: '#0000FF', angleDeg: 90, radial: false }],
    backgroundResets: [1], backgroundGraphics: [{ slideIndex: 0, hidden: true }],
  })
  applyBackgroundOps(opened, opened.deck.slides, ops)
  const saved = await openPptx(await savePptx(opened))
  assert.deepEqual(inspectBackgroundState(saved, 0), { backgroundOwn: true, backgroundGraphicsHidden: true, backgroundGradient: { from: '#FF0000', to: '#0000FF', radial: false, angleDeg: 90 } })
  assert.match(xml(saved, 0), /<a:gradFill[^>]*><a:gsLst><a:gs pos="0"><a:srgbClr val="FF0000"\/><\/a:gs><a:gs pos="100000"><a:srgbClr val="0000FF"\/><\/a:gs><\/a:gsLst><a:lin ang="5400000"/)
  assert.match(xml(saved, 0), /<p:sld[^>]*showMasterSp="0"/)
  assert.equal(inspectBackgroundState(saved, 1).backgroundOwn, false)
  assert.doesNotMatch(xml(saved, 1), /<p:bg>/)
  assert.deepEqual(saved.archive.readBytes(saved.deck.slides[2]!.path), untouched)
  // 径向；取消隐藏背景图形
  applyBackgroundOps(saved, saved.deck.slides, validateBackgroundOps(saved, { backgroundGradients: [{ slideIndices: [0, 2], from: '#FFFFFF', to: '#000000', angleDeg: 0, radial: true }], backgroundGraphics: [{ slideIndex: 0, hidden: false }] }))
  const again = await openPptx(await savePptx(saved))
  for (const index of [0, 2]) assert.equal(inspectBackgroundState(again, index).backgroundGradient?.radial, true)
  assert.match(xml(again, 2), /<a:path path="circle">/)
  assert.equal(inspectBackgroundState(again, 0).backgroundGraphicsHidden, false)
})

test('全幅无字底板随渐变一起重绘（固定源 repaintFullBleedBackdrops）', async () => {
  const opened = await deck(), size = opened.deck.size
  addElement(opened.deck.slides[0]!, { kind: 'rect', offset: { x: 0, y: 0, cx: size.cx, cy: size.cy }, fillColor: '#EEEEEE' })
  const saved = await openPptx(await savePptx(opened))
  applyBackgroundOps(saved, saved.deck.slides, validateBackgroundOps(saved, { backgroundGradients: [{ slideIndices: [0], from: '#FF0000', to: '#00FF00', angleDeg: 0, radial: false }] }))
  const backdrop = saved.deck.slides[0]!.elements.find(element => element.type === 'shape')!
  assert.equal(backdrop.fill?.type, 'gradient')
})

test('冲突、非法方向与颜色、重置非自有背景整批拒绝', async () => {
  const opened = await deck(), item = { slideIndices: [0], from: '#FF0000', to: '#0000FF', angleDeg: 0, radial: false }
  for (const bad of [{ ...item, angleDeg: 30 }, { ...item, radial: true, angleDeg: 90 }, { ...item, from: 'red' }, { ...item, slideIndices: [] }, { ...item, slideIndices: [5] }, { ...item, extra: 1 }])
    assert.throws(() => validateBackgroundOps(opened, { backgroundGradients: [bad] }), JSON.stringify(bad))
  assert.throws(() => validateBackgroundOps(opened, { backgroundGradients: [item, item] }), /conflict/)
  assert.throws(() => validateBackgroundOps(opened, { backgroundGradients: [item], backgroundResets: [0] }), /conflict/)
  assert.throws(() => validateBackgroundOps(opened, { backgroundGradients: [item] }, { fillSlides: new Set([0]) }), /conflict/)
  assert.throws(() => validateBackgroundOps(opened, { backgroundResets: [0] }), /not_own/)
  assert.throws(() => validateBackgroundOps(opened, { backgroundResets: [1] }, { removedSlides: new Set([1]) }), /conflict/)
  assert.throws(() => validateBackgroundOps(opened, { backgroundGraphics: [{ slideIndex: 0, hidden: true }, { slideIndex: 0, hidden: false }] }), /invalid/)
  assert.throws(() => validateBackgroundOps(opened, { backgroundGraphics: [{ slideIndex: 0, hidden: 'yes' }] }), /invalid/)
})
