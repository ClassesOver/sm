import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'

export async function inspectCommentComposer(page,{output,phase,evidence,draft}) {
  const panel=page.locator('.docx-comment-create'),before=await draft(),input=await panel.locator('textarea').inputValue()
  const check=(ok,label)=>{if(!ok)evidence.failures.push(`${phase}: ${label}`)}
  for(const [width,height] of [[1440,900],[320,640],[640,360],[390,320],[1440,360]]){
    await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready)
    await panel.scrollIntoViewIfNeeded()
    const geometry=await panel.evaluate(node=>{
      const r=node.getBoundingClientRect(),style=getComputedStyle(node)
      return {x:r.x,right:r.right,width:r.width,overflow:node.scrollWidth>node.clientWidth+1,
        font:style.fontFamily,themeFont:getComputedStyle(node.closest('.docx-native')).fontFamily,
        header:!!node.querySelector('header h2'),namedList:node.querySelector('ul')?.getAttribute('aria-label')==='待保存的新批注',
        previewRegion:node.querySelector('[data-new-comment-selection]')?.getAttribute('role')==='region',
        draftTexts:[...node.querySelectorAll('[data-new-comment-list] li')].map(row=>row.textContent)}
    })
    check(!geometry.overflow&&geometry.x>=0&&geometry.right<=width+1,`${width}x${height}横向边界`)
    check(geometry.header&&geometry.namedList&&geometry.previewRegion,`${width}x${height}结构及命名`)
    check(geometry.font===geometry.themeFont,`${width}x${height}主题字体`)
    const states=[]
    for(const control of await panel.locator('button,textarea,[data-new-comment-selection]:not([hidden]):not(:empty),[data-new-comment-list]:not([hidden]):has(li)').all()){
      const disabled=await control.isDisabled();await control.scrollIntoViewIfNeeded()
      if(!disabled){await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')}
      const state=await control.evaluate(node=>{
        const r=node.getBoundingClientRect(),s=getComputedStyle(node)
        return {label:node.getAttribute('aria-label')||node.textContent,tag:node.tagName,disabled:!!node.disabled,
          focused:node===document.activeElement,font:s.fontFamily,height:r.height,
          ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2,
          hit:[[r.x+r.width/2,r.y+r.height/2],[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]].every(([x,y])=>node.contains(document.elementFromPoint(x,y)))}
      })
      check(state.hit&&(disabled||state.focused&&state.ring),`${width}x${height} ${state.tag}焦点及命中`)
      check(state.font===geometry.themeFont&&(state.tag!=='BUTTON'||Math.abs(state.height-28)<1),`${width}x${height} ${state.tag}紧凑主题控件`)
      states.push(state)
    }
    const screenshots=[]
    for(const end of ['first','last']){
      const controls=panel.locator('button,textarea');await(end==='first'?controls.first():controls.last()).scrollIntoViewIfNeeded()
      const file=`comment-create-${phase}-${width}x${height}-${end}.png`;await page.screenshot({path:join(output,file)});screenshots.push(file)
    }
    assert.deepEqual(await draft(),before);assert.equal(await panel.locator('textarea').inputValue(),input)
    evidence.cases.push({phase,width,height,geometry,states,screenshots})
    await writeFile(join(output,'comment-create-layout.json'),JSON.stringify(evidence,null,2))
    console.log(JSON.stringify({phase,width,height,controls:states.length,failures:evidence.failures.length}))
  }
  await page.setViewportSize({width:1600,height:1100})
}
