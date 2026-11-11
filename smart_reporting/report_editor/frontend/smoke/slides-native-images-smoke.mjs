/** 独立真实浏览器图片 helper 探针；不构建完整前端。 */
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { chromium } from 'playwright'
const result=await build({entryPoints:['src/slides-native-images.ts'],bundle:true,write:false,format:'iife',globalName:'SlideImages',platform:'browser'})
const browser=await chromium.launch({headless:true})
try{
 const page=await browser.newPage()
 await page.setContent('<main>图片专项探针</main>')
 await page.addScriptTag({content:result.outputFiles[0].text})
 const output=await page.evaluate(async()=>{
  const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
  const bytes=Uint8Array.from(atob(png),c=>c.charCodeAt(0))
  const image=await SlideImages.prepareSlideImage(new File([bytes],'原始图片.png',{type:'image/png'}),{cx:12192000,cy:6858000})
  let corruptRejected=false
  try{await SlideImages.prepareSlideImage(new File([bytes.slice(0,24)],'伪装.png',{type:'image/png'}),{cx:12192000,cy:6858000})}catch{corruptRejected=true}
  const picked=SlideImages.pickSlideImage()
  const input=document.querySelector('input[type=file]')
  const data=new DataTransfer();data.items.add(new File([bytes],'选择图片.png',{type:'image/png'}));input.files=data.files
  input.dispatchEvent(new Event('change'))
  const file=await picked
  const cancelled=SlideImages.pickSlideImage()
  document.querySelector('input[type=file]').dispatchEvent(new Event('cancel'))
  return {image,unchanged:image.bytesBase64===png,corruptRejected,picked:file.name,cancelled:await cancelled,remaining:document.querySelectorAll('input[type=file]').length}
 })
 assert.equal(output.unchanged,true)
 assert.equal(output.corruptRejected,true)
 assert.equal(output.picked,'选择图片.png')
 assert.equal(output.cancelled,null)
 assert.equal(output.remaining,0)
 assert.equal(output.image.geometry.width,1)
 console.log(JSON.stringify({status:'passed',...output},null,2))
}finally{await browser.close()}
