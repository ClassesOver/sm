import {createHash} from 'node:crypto'
import {readFile} from 'node:fs/promises'

/** Probe a blank page before app/web-font loading can mask system failures.
 * Keep the configuration explicit in evidence; never silently change fonts.
 */
export async function probeCanvasTextRendering(browser) {
 const page=await browser.newPage()
 try {
  const fonts=await page.evaluate(()=>[
   'sans-serif','serif','monospace','system-ui','Arial','Calibri','"DejaVu Sans"',
  ].map(family=>{
   const canvas=document.createElement('canvas');canvas.width=320;canvas.height=80
   const context=canvas.getContext('2d');context.font='20px '+family;context.fillStyle='#000000'
   const text='Canvas probe 123',width=context.measureText(text).width
   context.fillText(text,8,36)
   const pixels=context.getImageData(0,0,canvas.width,canvas.height).data
   let inkPixels=0
   for(let index=3;index<pixels.length;index+=4)if(pixels[index]>0)inkPixels++
   return {family,font:context.font,width,inkPixels}
  }))
  const path=process.env.FONTCONFIG_FILE??null
  const fontconfig=path?{path,sha256:createHash('sha256').update(await readFile(path)).digest('hex')}:null
  return {ok:fonts.every(font=>Number.isFinite(font.width)&&font.width>0&&font.inkPixels>0),browserVersion:browser.version(),fontconfig,fonts}
 }finally{await page.close()}
}
