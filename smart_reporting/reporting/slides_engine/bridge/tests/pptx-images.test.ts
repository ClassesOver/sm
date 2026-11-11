import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addPicture, createBlankPptx, duplicateSlide, openPptx, savePptx } from '@genoffice/pptx-engine'
import { inspectPictureImages, validatePictureInsertions, validatePictureReplacements, applyPictureReplacements } from '../pptx-images.ts'
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
const asset = { bytesBase64: png, extension: 'png' as const }
async function fixture() {
 const opened = await openPptx(await createBlankPptx())
 addPicture(opened, opened.deck.slides[0]!, { bytes: Buffer.from(png,'base64'), ext:'png', offset:{x:100,y:200,cx:300,cy:400},descr:'原图' })
 duplicateSlide(opened,0)
 return openPptx(await savePptx(opened))
}
test('替换真实PPTX图片保留共享媒体的其他页、框、描述和未修改部件', async () => {
 const opened = await fixture(), before = inspectPictureImages(opened)
 const original = new Map([...opened.archive.entries.keys()].map(path=>[path,opened.archive.readBytes(path)!]))
 const target = before[0]!
 const replacement = {...asset,bytesBase64:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',slideIndex:0,elementId:target.elementId,expectedSha256:target.sha256!,expectedSize:target.size!}
 const geometry = structuredClone(opened.deck.slides[0]!.elements[0]!.transform)
 applyPictureReplacements(opened,[replacement])
 const reopened = await openPptx(await savePptx(opened))
 assert.equal(inspectPictureImages(reopened)[1]!.sha256,before[1]!.sha256)
 assert.notEqual(inspectPictureImages(reopened)[0]!.sha256,before[0]!.sha256)
 const replaced=reopened.deck.slides[0]!.elements[0]!
 assert.equal(replaced.type,'picture')
 assert.deepEqual(reopened.archive.readBytes((replaced as any).mediaRef),new Uint8Array(Buffer.from(replacement.bytesBase64,'base64')))
 assert.deepEqual(reopened.deck.slides[0]!.elements[0]!.transform,geometry)
 assert.equal(reopened.deck.slides[0]!.elements[0]!.descr,'原图')
 for (const [path, bytes] of original) {
  if (path==='ppt/slides/slide1.xml'||path==='ppt/slides/_rels/slide1.xml.rels'||path==='[Content_Types].xml') continue
  assert.deepEqual(reopened.archive.readBytes(path),bytes,path)
 }
})
test('整批先验证身份，后项过期时不得修改前项', async () => {
 const opened = await fixture(), targets = inspectPictureImages(opened)
 const items = targets.map(p=>({...asset,slideIndex:p.slideIndex,elementId:p.elementId,expectedSha256:p.sha256!,expectedSize:p.size!}))
 items[1]!.expectedSha256='0'.repeat(64)
 const before = opened.deck.slides[0]!.elements[0]!.anchor.originalXml
 assert.throws(()=>applyPictureReplacements(opened,items),/identity_changed/)
 assert.equal(opened.deck.slides[0]!.elements[0]!.anchor.originalXml,before)
 assert.throws(()=>validatePictureReplacements(opened,[items[0]!,items[0]!]),/duplicate/)
})
test('插入拒绝伪装图片、非规范base64和无效几何', async () => {
 const opened=await fixture(), item={...asset,slideIndex:0,geometry:{x:1,y:2,width:3,height:4}}
 validatePictureInsertions(opened,[item])
 assert.throws(()=>validatePictureInsertions(opened,[{...item,bytesBase64:png+'\n'}]),/asset_invalid/)
 assert.throws(()=>validatePictureInsertions(opened,[{...item,bytesBase64:Buffer.from('not an image').toString('base64')}]),/asset_invalid/)
 assert.throws(()=>validatePictureInsertions(opened,[{...item,geometry:{...item.geometry,width:-1}}]),/geometry_invalid/)
})
