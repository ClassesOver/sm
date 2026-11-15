import {describe,it,expect} from 'vitest'
import JSZip from 'jszip'
import {buildDocx,IMAGE_PARAGRAPH_XML} from './helpers/build-docx'
import {parseDocx} from '../src/parse'
import {inspectDocxPictureFormats,patchDocxPictureFormat,readDocxPictureFormat} from '../../../bridge/docx-picture-format'
const picture=IMAGE_PARAGRAPH_XML.replace('</pic:pic>','<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm></pic:spPr></pic:pic>')
describe('图片格式原生保存及源保全',()=>{
 it('重开尺寸旋转翻转对齐；媒体与其他ZIP部件字节不变',async()=>{
  const bytes=await buildDocx({bodyXml:picture+'<w:p><w:r><w:t>保留正文</w:t></w:r></w:p>',withImage:true})
  const [target]=await inspectDocxPictureFormats(bytes)
  expect(target).toBeDefined()
  const output=await patchDocxPictureFormat(bytes,{kind:'formatImage',...target,widthPx:192,heightPx:144,rotDeg:90,flipH:true,align:'center'})
  expect((await parseDocx(output)).blocks[0]).toMatchObject({imageWidthPx:192,imageHeightPx:144,imageRotDeg:90,imageFlipH:true,imageAlign:'center'})
  const a=await JSZip.loadAsync(bytes),b=await JSZip.loadAsync(output)
  expect(Object.keys(b.files)).toEqual(Object.keys(a.files))
  for(const name of Object.keys(a.files))if(name!=='word/document.xml'&&!a.files[name].dir)expect(await b.file(name)!.async('uint8array')).toEqual(await a.file(name)!.async('uint8array'))
  expect(await b.file('word/document.xml')!.async('string')).toContain('<w:p><w:r><w:t>保留正文</w:t></w:r></w:p>')
 })
 it('切换浮动环绕并可恢复行内',async()=>{
  const bytes=await buildDocx({bodyXml:picture,withImage:true}),[target]=await inspectDocxPictureFormats(bytes)
  const floating=await patchDocxPictureFormat(bytes,{kind:'formatImage',...target,wrap:'square-left'})
  expect((await parseDocx(floating)).blocks[0].imageWrap).toBe('square-left')
  const [next]=await inspectDocxPictureFormats(floating)
  const inline=await patchDocxPictureFormat(floating,{kind:'formatImage',...next,wrap:null})
  expect((await parseDocx(inline)).blocks[0].imageWrap).toBeUndefined()
 })
 it('固定源九宫格位置写margin-relative align并保留图片数据',async()=>{
  const bytes=await buildDocx({bodyXml:picture,withImage:true}),[target]=await inspectDocxPictureFormats(bytes)
  const output=await patchDocxPictureFormat(bytes,{kind:'formatImage',...target,wrap:'square-right',posH:'right',posV:'bottom'})
  const block=(await parseDocx(output)).blocks[0]
  expect(block).toMatchObject({imagePosH:'right',imagePosV:'bottom',imageWrap:'square-right'})
  expect(block.originalXml).toContain('<wp:positionH relativeFrom="margin"><wp:align>right</wp:align></wp:positionH>')
  expect(block.originalXml).toContain('<wp:positionV relativeFrom="margin"><wp:align>bottom</wp:align></wp:positionV>')
  const [next]=await inspectDocxPictureFormats(output)
  expect(next.expectedImageSha256).toBe(target.expectedImageSha256)
 })
 it('组合和外链来源不提供格式身份',async()=>{
  for(const xml of [picture.replace('r:embed="rId10"','r:link="rId10"'),picture.replace('</w:p>','<w:object/></w:p>')])expect(await inspectDocxPictureFormats(await buildDocx({bodyXml:xml,withImage:true}))).toEqual([])
 })
 it('拒绝身份篡改、未知属性与超界值',async()=>{
  const bytes=await buildDocx({bodyXml:picture,withImage:true}),[target]=await inspectDocxPictureFormats(bytes)
  await expect(patchDocxPictureFormat(bytes,{kind:'formatImage',...target,expectedImageSha256:'0'.repeat(64),rotDeg:90})).rejects.toThrow()
  for(const patch of [{opacity:0.5},{rotDeg:NaN},{widthPx:10},{widthPx:0,heightPx:10},{flipH:'yes'},{wrap:'square'},{xml:'<x/>'}])expect(()=>readDocxPictureFormat({kind:'formatImage',...target,...patch})).toThrow()
 })
})
