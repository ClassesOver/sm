import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

/** 实际构建宿主的对象列表，不构造或替换产品DOM。 */
export async function inspectPdfObjectPanel(page,{panel,kind,operations,directory}) {
  if(!process.env.PDF_OBJECT_PANEL_VIEWPORTS)return []
  const viewport=page.viewportSize(),before=await operations(),results=[],failures=[]
  if(directory)await mkdir(directory,{recursive:true})
  for(const size of process.env.PDF_OBJECT_PANEL_VIEWPORTS.split(',')){
    const [width,height]=size.split('x').map(Number);await page.setViewportSize({width,height})
    if(await panel.evaluate(node=>node.tagName==='DETAILS'&&!node.open))await panel.locator('summary').click()
    const buttons=panel.locator('button'),measurements=[]
    // 先进入键盘导航模式，再检查 :focus-visible；程序focus并不总触发它。
    await page.keyboard.press('Tab')
    if(kind==='drawings'){
      const selected=panel.locator('[data-pdf-pending-drawing] button[aria-pressed="true"]')
      await selected.focus();await selected.press('Space')
      assert.ok(await selected.evaluate(node=>document.activeElement===node))
    }
    for(const button of await buttons.all()){
      await button.scrollIntoViewIfNeeded()
      if(await button.isEnabled())await button.focus()
      measurements.push(await button.evaluate(node=>{
        const r=node.getBoundingClientRect(),s=getComputedStyle(node)
        return {label:node.textContent,height:r.height,width:r.width,font:parseFloat(s.fontSize),radius:parseFloat(s.borderRadius),disabled:node.disabled,danger:node.disabled||!node.classList.contains('ui-button--danger')||(s.color===s.borderTopColor&&s.color!==getComputedStyle(node.parentElement).color),focusRing:node.disabled||parseFloat(s.outlineWidth)>=2,hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),within:r.x>=-1&&r.y>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1,pressed:node.getAttribute('aria-pressed')}
      }))
    }
    const geometry=await panel.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {width:r.width,height:r.height,overflowX:node.scrollWidth>node.clientWidth+1,background:s.backgroundColor,font:parseFloat(s.fontSize),actions:!!node.querySelector('.pdf-object-actions'),selected:node.querySelectorAll('[data-pdf-pending-drawing]:has([aria-pressed="true"])').length}})
    const check=(condition,message)=>{if(!condition)failures.push(`${kind} ${size}: ${message}`)}
    check(measurements.length>0,'缺少操作按钮')
    check(measurements.every(b=>b.height>=28&&b.height<=34&&b.radius>=3&&b.font>=12&&b.font<=14),'按钮未采用紧凑桌面尺寸/字体/圆角')
    check(measurements.every(b=>b.within&&b.hit),'操作滚动后仍被遮挡或溢出视口')
    check(measurements.every(b=>b.focusRing),'键盘焦点环缺失')
    check(measurements.every(b=>b.danger),'删除按钮的危险操作颜色被旧工具栏样式覆盖')
    check(!geometry.overflowX&&geometry.actions,'缺少操作分组或面板横向溢出')
    if(kind==='drawings')check(geometry.selected===1,'所选记录状态丢失')
    assert.deepEqual(await operations(),before)
    if(directory)await page.screenshot({path:resolve(directory,`object-panel-${kind}-${size}.png`)})
    results.push({width,height,geometry,buttons:measurements,draftUnchanged:true})
  }
  await page.setViewportSize(viewport)
  if(directory)await writeFile(resolve(directory,`object-panel-${kind}-evidence.json`),JSON.stringify({kind,results,failures},null,2))
  assert.deepEqual(failures,[])
  return results
}
