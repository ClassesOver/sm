import {expect,it} from 'vitest'
import {validatePdfExistingImage,existingImageTransform,PDF_EXISTING_IMAGE_ALONE_REASON} from './pdf-existing-image'
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0'
const pages=[{pageId,index:0,rotation:90,cropBox:{x:10,y:20,width:380,height:460},mediaBox:{x:0,y:0,width:400,height:500}}]
const target={pageId,pageIndex:0,rect:[60,90,160,170] as [number,number,number,number],imageId:'b'.repeat(64),expectedImageSha256:'c'.repeat(64),aboveText:true,editable:true}
const operation={kind:'transformExistingImage',sourceSha256:sha,pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:[80,110,230,210]}
it('stages actual source image move and resize in original PDF coordinates',()=>{
 expect(existingImageTransform(sha,target,{x:80,y:110,width:150,height:100})).toEqual(operation)
 expect(()=>validatePdfExistingImage(pages,[operation],[target])).not.toThrow()
})
it.each([{rect:[9,110,230,210]},{rect:[80,110,391,210]},{rect:[80,110,80,210]},{imageId:'d'.repeat(64)},{expectedImageSha256:'d'.repeat(64)},{sourceSha256:'d'.repeat(64)},{layer:'belowText'}])('rejects stale source and unsafe geometry %j',patch=>{
 expect(()=>validatePdfExistingImage(pages,[{...operation,...patch}],[target])).toThrow()
})
it('requires a unique editable target and an independent save',()=>{
 expect(()=>validatePdfExistingImage(pages,[operation],[{...target,editable:false}])).toThrow()
 expect(()=>validatePdfExistingImage(pages,[operation,operation],[target])).toThrow(PDF_EXISTING_IMAGE_ALONE_REASON)
})

const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
it('stages pinned replaceImage pixels on a replaceable target only',()=>{
 const replaceable={...target,replaceable:true}
 const staged=existingImageTransform(sha,replaceable,{x:60,y:90,width:100,height:80},png)
 expect(staged).toEqual({...operation,rect:[60,90,160,170],image:png})
 expect(()=>validatePdfExistingImage(pages,[staged],[replaceable])).not.toThrow()
 expect(()=>existingImageTransform(sha,{...target,replaceable:false,replaceReason:'同一图像数据被多处引用'},{x:60,y:90,width:100,height:80},png)).toThrow('多处引用')
 expect(()=>validatePdfExistingImage(pages,[staged],[{...target,replaceable:false,replaceReason:'同一图像数据被多处引用'}])).toThrow('多处引用')
 expect(()=>validatePdfExistingImage(pages,[staged],[target])).toThrow('暂不支持替换')
 for(const bad of ['R0lGODlhAQABAAAAACw=','iVBORw0KGgo'+'A'.repeat(6_000_000),'iVBORw0KGgo***',42])
  expect(()=>validatePdfExistingImage(pages,[{...staged,image:bad}],[replaceable])).toThrow('参数无效')
 expect(()=>existingImageTransform(sha,replaceable,{x:60,y:90,width:100,height:80},'R0lGODlh')).toThrow('PNG')
})
