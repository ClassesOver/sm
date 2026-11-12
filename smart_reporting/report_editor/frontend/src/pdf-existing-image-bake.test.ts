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

it('rejects unbakeable targets, invalid bakes, moved rects and bake with replacement',()=>{
 expect(()=>existingImageBake(sha,{...target,bakeable:false,bakeReason:'图像带旋转、镜像或位于模板内'},{kind:'flip',axis:'h'})).toThrow('旋转、镜像')
 for(const bake of [{kind:'flip',axis:'d'},{kind:'opacity',alpha:1},{kind:'opacity',alpha:.333},{kind:'crop',crop:{l:0,t:0,r:1,b:1}},{kind:'crop',crop:{l:.6,t:0,r:.5,b:1}},{kind:'crop',crop:{l:0,t:0,r:1.2,b:1}},{kind:'flip',axis:'h',x:1}])
  expect(()=>existingImageBake(sha,target,bake as never),JSON.stringify(bake)).toThrow()
 const flip=existingImageBake(sha,target,{kind:'flip',axis:'h'})
 expect(()=>validatePdfExistingImage(pages,[{...flip,rect:[70,90,170,170]}],[target])).toThrow('不能同时移动')
 expect(()=>validatePdfExistingImage(pages,[{...flip,image:'iVBORw0KGgoAAAA'}],[target])).toThrow('参数无效')
 expect(()=>validatePdfExistingImage(pages,[flip],[{...target,bakeable:false}])).toThrow()
 expect(()=>validatePdfExistingImage(pages,[{...flip,bake:{kind:'opacity',alpha:2}}],[target])).toThrow()
})
