import {expect,it} from 'vitest'
import {existingImageBake,validatePdfExistingImage} from './pdf-existing-image'
import {cropRect} from './vendor/genoffice-pdf/renderer/image-bake'
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0'
const pages=[{pageId,index:0,rotation:0,cropBox:{x:0,y:0,width:400,height:500},mediaBox:{x:0,y:0,width:400,height:500}}]
const target={pageId,pageIndex:0,rect:[60,90,160,170] as [number,number,number,number],imageId:'b'.repeat(64),expectedImageSha256:'c'.repeat(64),aboveText:true,editable:true,replaceable:true,bakeable:true}
const base={kind:'transformExistingImage',sourceSha256:sha,pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256}

it('stages flip and opacity in place and crop with the pinned cropRect footprint',()=>{
 expect(existingImageBake(sha,target,{kind:'flip',axis:'h'})).toEqual({...base,rect:[60,90,160,170],bake:{kind:'flip',axis:'h'}})
 expect(existingImageBake(sha,target,{kind:'opacity',alpha:.35})).toEqual({...base,rect:[60,90,160,170],bake:{kind:'opacity',alpha:.35}})
 const crop={l:.25,t:0,r:1,b:.5},staged=existingImageBake(sha,target,{kind:'crop',crop})
 expect(staged.rect).toEqual(cropRect(target.rect,crop))
 expect(staged.rect).toEqual([85,130,160,170])
 for(const operation of [staged,existingImageBake(sha,target,{kind:'flip',axis:'v'})])expect(()=>validatePdfExistingImage(pages,[operation],[target])).not.toThrow()
})

it.each([1,3] as const)('stages quarter-turn %i around the image center and swaps the PDF footprint',turns=>{
 const operation=existingImageBake(sha,target,{kind:'rotate',quarterTurns:turns})
 expect(operation).toEqual({...base,rect:[70,80,150,180],bake:{kind:'rotate',quarterTurns:turns}})
 expect(()=>validatePdfExistingImage(pages,[operation],[target])).not.toThrow()
 expect(()=>validatePdfExistingImage(pages,[{...operation,rect:target.rect}],[target])).toThrow()
 expect(()=>existingImageBake(sha,{...target,bakeable:false,bakeReason:'图像身份不能安全读取像素'},{kind:'rotate',quarterTurns:turns})).toThrow('不能安全读取像素')
})

it('rejects unbakeable targets, invalid bakes, moved rects and bake with replacement',()=>{
 expect(()=>existingImageBake(sha,{...target,bakeable:false,bakeReason:'图像带旋转、镜像或位于模板内'},{kind:'flip',axis:'h'})).toThrow('旋转、镜像')
 for(const bake of [{kind:'flip',axis:'d'},{kind:'opacity',alpha:1},{kind:'opacity',alpha:.333},{kind:'crop',crop:{l:0,t:0,r:1,b:1}},{kind:'crop',crop:{l:.6,t:0,r:.5,b:1}},{kind:'crop',crop:{l:0,t:0,r:1.2,b:1}},{kind:'flip',axis:'h',x:1},{kind:'rotate',quarterTurns:2},{kind:'rotate',quarterTurns:1,extra:true}])
  expect(()=>existingImageBake(sha,target,bake as never),JSON.stringify(bake)).toThrow()
 const flip=existingImageBake(sha,target,{kind:'flip',axis:'h'})
 expect(()=>validatePdfExistingImage(pages,[{...flip,rect:[70,90,170,170]}],[target])).toThrow('不能同时移动')
 expect(()=>validatePdfExistingImage(pages,[{...flip,image:'iVBORw0KGgoAAAA'}],[target])).toThrow('参数无效')
 expect(()=>validatePdfExistingImage(pages,[flip],[{...target,bakeable:false}])).toThrow()
 expect(()=>validatePdfExistingImage(pages,[{...flip,bake:{kind:'opacity',alpha:2}}],[target])).toThrow()
})

it('stages the pinned cutout bake in place with an integer 0–100 tolerance and rejects invalid ones',()=>{
 const staged=existingImageBake(sha,target,{kind:'cutout',tolerance:30})
 expect(staged).toEqual({...base,rect:[60,90,160,170],bake:{kind:'cutout',tolerance:30}})
 expect(()=>validatePdfExistingImage(pages,[staged],[target])).not.toThrow()
 for(const tolerance of [0,100])expect(()=>existingImageBake(sha,target,{kind:'cutout',tolerance})).not.toThrow()
 for(const bake of [{kind:'cutout',tolerance:101},{kind:'cutout',tolerance:-1},{kind:'cutout',tolerance:12.5},{kind:'cutout'},{kind:'cutout',tolerance:30,extra:1}])
  expect(()=>existingImageBake(sha,target,bake as never),JSON.stringify(bake)).toThrow()
 expect(()=>validatePdfExistingImage(pages,[{...staged,rect:[70,90,170,170]}],[target])).toThrow('不能同时移动')
 expect(()=>validatePdfExistingImage(pages,[{...staged,bake:{kind:'cutout',tolerance:500}}],[target])).toThrow()
})
it('rejects non-finite opacity before it can become null in a draft',()=>{
 expect(()=>existingImageBake(sha,target,{kind:'opacity',alpha:NaN})).toThrow('不透明度')
 const valid=existingImageBake(sha,target,{kind:'flip',axis:'h'})
 expect(()=>validatePdfExistingImage(pages,[{...valid,bake:{kind:'opacity',alpha:NaN}}],[target])).toThrow('不透明度')
})
