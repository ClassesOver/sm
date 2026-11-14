import {describe,it,expect} from 'vitest'
import {projectDocxPictureFormat,normalizeDocxPictureFormats,pictureSizeForSide,resetPictureDimensions} from './docx-picture-format'
const anchor={docxIndex:1,blockId:'picture',expectedObjectSha256:'xml',editable:false,imageEditable:true,imageFormatEditable:true,imageSha256:'media'}
const original={type:'doc',content:[{type:'docProtected',attrs:{docxIndex:1,blockType:'image',imageDataUrl:'original',imageWidthPx:192,imageHeightPx:144}}]}
const op={kind:'formatImage',blockId:'picture',expectedObjectSha256:'xml',expectedImageSha256:'media',widthPx:320,heightPx:240,rotDeg:90,flipH:true,wrap:'behind',align:'center'}
describe('图片几何原生草稿',()=>{
 it('投影并还原原始attrs，仅产生真实格式操作',()=>{
  const projected=projectDocxPictureFormat(original.content[0],anchor,op)
  expect(projected.attrs).toMatchObject({imageWidthPx:320,imageHeightPx:240,imageRotDeg:90,imageFlipH:true,imageWrap:'behind',imageAlign:'center',imageDataUrl:'original'})
  expect(normalizeDocxPictureFormats(original,{type:'doc',content:[projected]},[anchor])).toEqual({current:original,operations:[op]})
 })
 it('拒绝媒体替换混合、篡改投影和身份',()=>{
  expect(()=>projectDocxPictureFormat({...original.content[0],attrs:{...original.content[0].attrs,imageReplace:{}}},anchor,op)).toThrow()
  expect(()=>projectDocxPictureFormat(original.content[0],anchor,{...op,expectedImageSha256:'foreign'})).toThrow()
  const projected=projectDocxPictureFormat(original.content[0],anchor,op);projected.attrs!.imageWidthPx=321
  expect(()=>normalizeDocxPictureFormats(original,{type:'doc',content:[projected]},[anchor])).toThrow()
 })
 it('尺寸锁定按源比例、重置按源自然像素适应栏宽',()=>{
  expect(pictureSizeForSide(192,144,'w',320,true)).toEqual({widthPx:320,heightPx:240})
  expect(pictureSizeForSide(192,144,'h',200,false)).toEqual({widthPx:192,heightPx:200})
  expect(resetPictureDimensions(1200,800,624)).toEqual({widthPx:624,heightPx:416})
  expect(()=>pictureSizeForSide(192,144,'h',NaN,true)).toThrow()
 })
})
