// Local AP-aligned draft display: fixed 300x400 horizontal fixture, real UI zoom.
import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'
const near=(actual,expected)=>{assert.equal(actual.length,expected.length);actual.forEach((value,index)=>assert.ok(Math.abs(value-expected[index])<1e-6,`${actual} != ${expected}`))}
export async function verifyDraftDrawingAppearance(page,{directory,sourceSha256,staged}){
 const expected=[{index:0,label:'3.00 m',line:[80,200,240,200],origin:[160,206]},{index:4,label:'0.04 m',line:[80,300,82,300],origin:[81,306]}]
 assert.equal(staged.length,5)
 for(const item of expected){assert.equal(staged[item.index].label,item.label);assert.deepEqual([...staged[item.index].from,...staged[item.index].to],item.line)}
 assert.equal(staged[3].shape,'caret');assert.deepEqual(staged[3].point,[255,300])
 const result={scope:'real browser draft SVG at page rotation 0 and zoom 0.5/2/1; font glyph pixels are not asserted identical to PDF.js',sourceSha256,checkpoints:[]}
 for(const zoom of [.5,2,1]){
  await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.getByLabel('页面缩放',{exact:true}).selectOption(String(zoom))
  await page.waitForFunction(z=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&parseFloat(document.querySelector('.pdf-page-content')?.style.width??'')===300*z&&document.querySelectorAll('.pdf-page-content g[data-pdf-shape-index] [data-pdf-measure-label]').length===2,zoom)
  const capture=await page.evaluate(source=>{
   const root=document.querySelector('.pdf-page-content'),read=(index,selector)=>root.querySelector(`g[data-pdf-shape-index="${index}"] ${selector}`),numbers=value=>value.match(/-?\d+(?:\.\d+)?(?:e[-+]?\d+)?/gi).map(Number),ops=Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([,value])=>JSON.parse(value)).find(value=>value.identity?.sourceSha256===source)?.operations
   return {width:parseFloat(root.style.width),height:parseFloat(root.style.height),operations:ops,measures:[0,4].map(index=>{const text=read(index,'[data-pdf-measure-label]'),style=getComputedStyle(text);return {operationIndex:index,label:text.textContent,matrix:numbers(text.getAttribute('transform')),anchor:text.getAttribute('text-anchor'),fontSize:text.getAttribute('font-size'),fontFamily:style.fontFamily,fontKerning:style.fontKerning,fontVariantLigatures:style.fontVariantLigatures}}),caret:(()=>{const visible=read(3,'[data-pdf-drawing="caret"]'),hit=read(3,'[data-pdf-shape-hit]');return {operationIndex:3,path:visible.getAttribute('d'),vertices:numbers(visible.getAttribute('d')),fill:visible.getAttribute('fill'),stroke:visible.getAttribute('stroke'),hitPath:hit.getAttribute('d'),hitFill:hit.getAttribute('fill'),hitStroke:hit.getAttribute('stroke'),hitWidth:hit.getAttribute('stroke-width')}})()}
  },sourceSha256)
  assert.deepEqual(capture.operations,staged);near([capture.width,capture.height],[300*zoom,400*zoom])
  for(const [index,item]of expected.entries()){const row=capture.measures[index];assert.equal(row.label,item.label);near(row.matrix,[zoom,0,0,zoom,item.origin[0]*zoom,(400-item.origin[1])*zoom]);assert.equal(row.anchor,'start');assert.equal(row.fontSize,'9');assert.ok(row.fontFamily.includes('Helvetica'));assert.equal(row.fontKerning,'none');assert.equal(row.fontVariantLigatures,'none')}
  const caret=capture.caret;near(caret.vertices,[255*zoom,100*zoom,247*zoom,106*zoom,263*zoom,106*zoom]);assert.match(caret.path,/ Z$/);assert.equal(caret.fill,'rgb(219,56,46)');assert.equal(caret.stroke,'none');assert.equal(caret.hitPath,caret.path);assert.equal(caret.hitFill,'none');assert.equal(caret.hitStroke,'transparent');assert.equal(caret.hitWidth,'16')
  result.checkpoints.push({zoom,...capture});await writeFile(join(directory,'draft-appearance.json'),JSON.stringify(result,null,2));await page.screenshot({path:join(directory,`draft-appearance-${zoom}.png`),fullPage:true})
 }
 return result
}
