import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addPicture, createBlankPptx, duplicateSlide, openPptx, savePptx } from '@genoffice/pptx-engine'
import { inspectPictureImages } from '../pptx-images.ts'
import { applyPictureCrops } from '../pptx-picture-crop.ts'
import { applyPictureOpacities, inspectPictureOpacity, validatePictureOpacities } from '../pptx-picture-opacity.ts'

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
async function fixture() {
  const opened = await openPptx(await createBlankPptx())
  addPicture(opened, opened.deck.slides[0]!, { bytes: Buffer.from(png, 'base64'), ext: 'png', offset: { x: 952500, y: 952500, cx: 3810000, cy: 1905000 } })
  duplicateSlide(opened, 0)
  return openPptx(await savePptx(opened))
}
const edit = (opened: Awaited<ReturnType<typeof fixture>>, opacity: number) => { const picture = inspectPictureImages(opened)[0]!; return { slideIndex: 0, elementId: picture.elementId, expectedSha256: picture.sha256!, expectedSize: picture.size!, opacity } }

test('透明度写入 alphaModFix 并可回读、清除；媒体与其他页字节不变，可与裁切同批', async () => {
  const opened = await fixture(), item = edit(opened, 0.4)
  assert.deepEqual(inspectPictureOpacity(opened, 0, item.elementId), { pictureOpacityEditable: true, pictureOpacityReason: null, pictureOpacity: 1 })
  const other = opened.archive.readBytes(opened.deck.slides[1]!.path)
  applyPictureOpacities(opened, [item])
  applyPictureCrops(opened, [{ slideIndex: 0, elementId: item.elementId, expectedSha256: item.expectedSha256, expectedSize: item.expectedSize, srcRect: { l: 0.25, t: 0, r: 0, b: 0 }, geometry: { x: 200, y: 100, width: 300, height: 200 } }])
  const saved = await openPptx(await savePptx(opened))
  const xml = new TextDecoder().decode(saved.archive.readBytes(saved.deck.slides[0]!.path)!)
  assert.match(xml, /<a:alphaModFix amt="40000"\/>/)
  assert.match(xml, /<a:srcRect l="25000"/)
  const reopenedId = saved.deck.slides[0]!.elements[0]!.id
  assert.equal(inspectPictureOpacity(saved, 0, reopenedId).pictureOpacity, 0.4)
  assert.deepEqual(saved.archive.readBytes(saved.deck.slides[1]!.path), other)
  assert.equal(inspectPictureImages(saved)[0]!.sha256, item.expectedSha256)
  applyPictureOpacities(saved, [{ ...edit(saved, 1), elementId: reopenedId }])
  const cleared = await openPptx(await savePptx(saved))
  assert.doesNotMatch(new TextDecoder().decode(cleared.archive.readBytes(cleared.deck.slides[0]!.path)!), /alphaModFix/)
  assert.equal(inspectPictureOpacity(cleared, 0, cleared.deck.slides[0]!.elements[0]!.id).pictureOpacity, 1)
})

test('重复、过期身份、越界值、删除或替换冲突整批拒绝且不改动来源', async () => {
  const opened = await fixture(), item = edit(opened, 0.5), before = opened.deck.slides[0]!.elements[0]!.anchor.originalXml
  assert.throws(() => applyPictureOpacities(opened, [item, { ...item, slideIndex: 1, elementId: opened.deck.slides[1]!.elements[0]!.id, expectedSha256: '0'.repeat(64) }]), /identity/)
  assert.equal(opened.deck.slides[0]!.elements[0]!.anchor.originalXml, before)
  assert.throws(() => validatePictureOpacities(opened, [item, item]), /conflict/)
  assert.throws(() => validatePictureOpacities(opened, [item], { deletedSlides: [0] }), /conflict/)
  assert.throws(() => validatePictureOpacities(opened, [item], { deletions: [item] }), /conflict/)
  assert.throws(() => validatePictureOpacities(opened, [item], { pictureReplacements: [item] }), /conflict/)
  for (const opacity of [-0.1, 1.1, 0.333, Number.NaN, '0.5']) assert.throws(() => validatePictureOpacities(opened, [{ ...item, opacity }]), /invalid/)
  assert.throws(() => validatePictureOpacities(opened, [{ ...item, extra: 1 }]), /invalid/)
  assert.throws(() => validatePictureOpacities(opened, [{ ...item, expectedSize: item.expectedSize + 1 }]), /identity/)
  assert.throws(() => validatePictureOpacities(opened, [{ ...item, elementId: 'missing' }]), /unsupported/)
})
