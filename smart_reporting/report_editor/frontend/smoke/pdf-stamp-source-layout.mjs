import assert from 'node:assert/strict'
import {join} from 'node:path'
export async function inspectStampLayout(page,{directory,phase,layout,draft}){
 const dialog=page.locator('.pdf-stamp-source-dialog'),before=await draft()
 for(const [width,height] of [[1440,900],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await dialog.locator('input').first().focus()
  for(const tab of ['水印','页眉页脚']){
   await dialog.getByRole('button',{name:tab,exact:true}).click()
   const geometry=await dialog.evaluate(node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,overflow:node.scrollWidth>node.clientWidth+1}})
   assert.ok(geometry.left>=0&&geometry.right<=width+1&&geometry.top>=0&&geometry.bottom<=height+1&&!geometry.overflow,JSON.stringify({width,height,tab,geometry}))
   const states=[]
   for(const control of await dialog.locator('input:not([type=color]),button').all()){
    if(!await control.isVisible()||await control.isDisabled())continue
    await control.focus();await control.scrollIntoViewIfNeeded()
    const state=await control.evaluate(node=>{const r=node.getBoundingClientRect();return {label:node.getAttribute('aria-label')||node.closest('label')?.textContent||node.textContent,focused:document.activeElement===node,hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===node,width:r.width,height:r.height}})
    assert.ok(state.focused&&state.hit,JSON.stringify({width,height,tab,state}));states.push(state)
   }
   const tabButtons=dialog.locator('.pdf-sign-tabs button');await tabButtons.first().scrollIntoViewIfNeeded()
   await page.screenshot({path:join(directory,'stamp-'+phase+'-'+tab+'-'+width+'x'+height+'-top.png')})
   await dialog.locator('.pdf-modal-actions button').last().focus();await page.screenshot({path:join(directory,'stamp-'+phase+'-'+tab+'-'+width+'x'+height+'-actions.png')})
   assert.deepEqual(await draft(),before);layout.cases.push({phase,width,height,tab,geometry,states})
  }
 }
 await page.setViewportSize({width:1440,height:900});await dialog.getByRole('button',{name:'水印',exact:true}).click()
}
