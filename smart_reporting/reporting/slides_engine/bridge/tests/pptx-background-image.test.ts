import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createBlankPptx, insertBlankSlide, openPptx, savePptx } from '@genoffice/pptx-engine'
import { applyBackgroundImages, inspectBackgroundImage, validateBackgroundImages } from '../pptx-background-image.ts'

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
async function deck() {
  const opened = await openPptx(await createBlankPptx())
  insertBlankSlide(opened, 0); insertBlankSlide(opened, 1)
  return openPptx(await savePptx(opened))
}
const text = (opened: Awaited<ReturnType<typeof deck>>, path: string) => new TextDecoder().decode(opened.archive.readBytes(path)!)

test('一张图片应用到多页只落一个媒体部件，拉伸/平铺可回读，未选页保持原样', async () => {
  const opened = await deck(), untouched = opened.archive.readBytes(opened.deck.slides[2]!.path)
  const mediaBefore = [...opened.archive.entries.keys()].filter(path => path.startsWith('ppt/media/')).length
  const items = validateBackgroundImages(opened, [{ slideIndices: [0, 1], bytesBase64: png, extension: 'png', tile: true }])
  applyBackgroundImages(opened, opened.deck.slides, items)
  const saved = await openPptx(await savePptx(opened))
  assert.deepEqual([0, 1, 2].map(index => inspectBackgroundImage(saved, index).backgroundImage), [{ mode: 'tile' }, { mode: 'tile' }, null])
  assert.equal([...saved.archive.entries.keys()].filter(path => path.startsWith('ppt/media/')).length, mediaBefore + 1)
  for (const index of [0, 1]) assert.match(text(saved, saved.deck.slides[index]!.path), /<p:bg><p:bgPr><a:blipFill[^>]*><a:blip r:embed="rId\d+"\/><a:tile /)
  assert.deepEqual(saved.archive.readBytes(saved.deck.slides[2]!.path), untouched)
  // 拉伸覆盖平铺
  applyBackgroundImages(saved, saved.deck.slides, validateBackgroundImages(saved, [{ slideIndices: [0], bytesBase64: png, extension: 'png', tile: false }]))
  const stretched = await openPptx(await savePptx(saved))
  assert.deepEqual(inspectBackgroundImage(stretched, 0).backgroundImage, { mode: 'stretch' })
  assert.match(text(stretched, stretched.deck.slides[0]!.path), /<a:stretch>/)
})

test('越界、重复页、与纯色或删除页冲突、非法图片整批拒绝', async () => {
  const opened = await deck(), item = { slideIndices: [0], bytesBase64: png, extension: 'png' as const, tile: false }
  for (const bad of [{ ...item, slideIndices: [] }, { ...item, slideIndices: [3] }, { ...item, slideIndices: [0, 0] }, { ...item, tile: 'yes' }, { ...item, extra: 1 },
    { ...item, bytesBase64: 'AAAA' }, { ...item, extension: 'jpg' }]) assert.throws(() => validateBackgroundImages(opened, [bad]), JSON.stringify(Object.keys(bad)))
  assert.throws(() => validateBackgroundImages(opened, [item, { ...item }]), /target_invalid/)
  assert.throws(() => validateBackgroundImages(opened, [item], { colorSlides: new Set([0]) }), /conflict/)
  assert.throws(() => validateBackgroundImages(opened, [item], { removedSlides: new Set([0]) }), /conflict/)
  assert.throws(() => validateBackgroundImages(opened, Array.from({ length: 11 }, (_, index) => ({ ...item, slideIndices: [index % 3] }))), /request_invalid/)
})
