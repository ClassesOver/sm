import assert from 'node:assert/strict'
import {test} from 'node:test'
import {addPicture,createBlankPptx,openPptx,savePptx} from '@genoffice/pptx-engine'
import {applyPictureReplacements,inspectPictureImages} from '../pptx-images.ts'
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
test('去背景复用源writer keepSrcRect 保留裁切与框，常规replace仍清裁切',async()=>{
 async function fixture(){const o=await openPptx(await createBlankPptx());addPicture(o,o.deck.slides[0]!,{bytes:Buffer.from(png,'base64'),ext:'png',offset:{x:10,y:20,cx:300,cy:400}});const p=o.deck.slides[0]!.elements[0]!;p.anchor.originalXml=p.anchor.originalXml.replace('<a:stretch>','<a:srcRect l="10000" t="20000" r="10000" b="0"/><a:stretch>');o.deck.slides[0]!.structureDirty=true;return openPptx(await savePptx(o))}
 const o=await fixture(),id=inspectPictureImages(o)[0]!,frame=o.deck.slides[0]!.elements[0]!.transform,source=o.deck.slides[0]!.elements[0]!.anchor.originalXml;assert.match(source,/srcRect/)
 const item={slideIndex:0,elementId:id.elementId,expectedSha256:id.sha256!,expectedSize:id.size!,bytesBase64:png,extension:'png' as const,keepSrcRect:true as const};applyPictureReplacements(o,[item]);const saved=await openPptx(await savePptx(o));assert.match(saved.deck.slides[0]!.elements[0]!.anchor.originalXml,/srcRect l="10000" t="20000" r="10000" b="0"/);assert.deepEqual(saved.deck.slides[0]!.elements[0]!.transform,frame)
 const plain=await fixture(),identity=inspectPictureImages(plain)[0]!;const {keepSrcRect:_keep,...normal}=item;applyPictureReplacements(plain,[{...normal,elementId:identity.elementId,expectedSha256:identity.sha256!,expectedSize:identity.size!}]);assert.doesNotMatch(plain.deck.slides[0]!.elements[0]!.anchor.originalXml,/srcRect/)
})
