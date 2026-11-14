import assert from 'node:assert/strict'
import {mkdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'

export async function protectedPdfKey(target,key,mode,capture=false){
  return target.evaluate((node,{key,mode,capture})=>{
    if(mode==='consumed')node.addEventListener('keydown',event=>event.preventDefault(),{once:true,capture})
    const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:mode==='composing',keyCode:mode==='legacy229'?229:0})
    node.dispatchEvent(event)
    return {defaultPrevented:event.defaultPrevented,isComposing:event.isComposing,keyCode:event.keyCode}
  },{key,mode,capture})
}

export async function inspectPdfSidebarKeys(page,{operations,directory}){
  const before=await operations(),original=page.viewportSize(),cases=[],originalPreference=await page.evaluate(()=>localStorage.getItem('genoffice-pdf-sidebar-width'))
  const divider=page.getByRole('separator',{name:'调整 PDF 侧栏宽度'})
  const state=()=>divider.evaluate(node=>({width:Number(node.getAttribute('aria-valuenow')),preference:localStorage.getItem('genoffice-pdf-sidebar-width')}))
  const frame=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  for(const [width,height]of [[1440,900],[320,640],[640,360],[390,320]]){
    await page.setViewportSize({width,height});await frame();await divider.focus()
    const initial=await state(),events=[]
    for(const key of ['ArrowLeft','ArrowRight','Home','End'])for(const mode of ['composing','legacy229','consumed']){
      events.push({key,mode,...await protectedPdfKey(divider,key,mode,true)});assert.deepEqual(await state(),initial)
    }
    for(const mode of ['composing','legacy229','consumed','ordinary']){
      await divider.press('End')
      await divider.scrollIntoViewIfNeeded()
      const start=await state(),box=await divider.boundingBox(),x=box.x+box.width/2,y=box.y+Math.min(20,box.height/2)
      const delta=-Math.min(10,(start.width-Number(await divider.getAttribute('aria-valuemin')))/2)
      await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+delta,y,{steps:3});await frame()
      assert.equal((await state()).width,start.width+delta);assert.equal((await state()).preference,start.preference)
      if(mode==='ordinary')await page.keyboard.press('Escape');else events.push({key:'Escape',mode,...await protectedPdfKey(divider,'Escape',mode,true)})
      await page.mouse.up();await frame()
      if(mode==='ordinary')assert.deepEqual(await state(),start)
      else {assert.deepEqual(await state(),{width:start.width+delta,preference:String(start.width+delta)});await divider.press('End');assert.equal((await state()).width,start.width)}
      assert.equal(await divider.evaluate(node=>node.classList.contains('is-resizing')),false)
    }
    const focus=await divider.evaluate(node=>({focused:document.activeElement===node,controls:node.getAttribute('aria-controls'),min:node.getAttribute('aria-valuemin'),max:node.getAttribute('aria-valuemax')}))
    assert.ok(focus.focused&&focus.controls)
    if(directory){await mkdir(directory,{recursive:true});await page.screenshot({path:join(directory,`sidebar-keyboard-${width}x${height}.png`)})}
    cases.push({width,height,events,focus})
  }
  await page.setViewportSize(original);await divider.press('Home');for(let index=0;index<3;index++)await divider.press('ArrowRight')
  await page.evaluate(value=>{if(value===null)localStorage.removeItem('genoffice-pdf-sidebar-width');else localStorage.setItem('genoffice-pdf-sidebar-width',value)},originalPreference)
  assert.equal((await state()).width,150);assert.deepEqual(await operations(),before)
  if(directory)await writeFile(join(directory,'sidebar-keyboard.json'),JSON.stringify(cases,null,2))
  return cases
}

export async function inspectPdfDrawingKeys(page,{operations,loaded,directory}){
  const before=await operations(),original=page.viewportSize(),cases=[]
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.getByRole('button',{name:'选择文字',exact:true}).click()
  for(const [width,height]of [[1440,900],[320,640],[640,360],[390,320]]){
    await page.setViewportSize({width,height});await loaded()
    const events=[]
    for(const mode of ['composing','legacy229','consumed','ordinary']){
      const shape=page.locator('.pdf-drawing-canvas.is-interactive [data-pdf-shape-index="1"] [data-pdf-shape-hit]').first()
      await shape.scrollIntoViewIfNeeded();const box=await shape.boundingBox(),x=box.x+box.width/2,y=box.y
      const svg=page.locator('.pdf-drawing-canvas.is-interactive').first()
      await svg.evaluate(node=>node.addEventListener('pointerdown',event=>{window.__pdfGesturePointer=event.pointerId},{once:true,capture:true}))
      await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+8,y+4,{steps:3})
      assert.equal(await svg.evaluate(node=>node.hasPointerCapture(window.__pdfGesturePointer)),true)
      assert.deepEqual(await operations(),before)
      if(mode==='ordinary')await page.keyboard.press('Escape');else events.push({mode,...await protectedPdfKey(svg,'Escape',mode)})
      assert.equal(await svg.evaluate(node=>node.hasPointerCapture(window.__pdfGesturePointer)),mode!=='ordinary')
      await page.mouse.up();await loaded()
      if(mode==='ordinary')assert.deepEqual(await operations(),before)
      else {
        await page.waitForFunction(before=>JSON.stringify(JSON.parse(Object.entries(localStorage).find(([key])=>key.includes('pending-drawings-fixture'))?.[1]??'{}').operations)!==JSON.stringify(before),before)
        const changed=await operations();assert.deepEqual(changed[0],before[0]);assert.notDeepEqual(changed[1].rect,before[1].rect);assert.deepEqual(changed.slice(2),before.slice(2))
        await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.getByRole('button',{name:/^(撤销|Undo)$/}).click();await loaded();assert.deepEqual(await operations(),before)
        await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
      }
    }
    if(directory){await mkdir(directory,{recursive:true});await page.screenshot({path:join(directory,`drawing-keyboard-${width}x${height}.png`)})}
    cases.push({width,height,events,realPointerCapture:true,undoRestoresExactDraft:true})
  }
  await page.setViewportSize(original);await loaded();assert.deepEqual(await operations(),before)
  if(directory)await writeFile(join(directory,'drawing-keyboard.json'),JSON.stringify(cases,null,2))
  return cases
}
