import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

export async function inspectPdfSidebar(page,{panel,kind,phase,operations,directory,reopen}) {
  if(!process.env.PDF_SIDEBAR_VIEWPORTS)return []
  const original=page.viewportSize(),before=await operations(),results=[],failures=[]
  if(directory)await mkdir(directory,{recursive:true})
  for(const size of process.env.PDF_SIDEBAR_VIEWPORTS.split(',')){
    const [width,height]=size.split('x').map(Number);await page.setViewportSize({width,height})
    const check=(ok,message)=>{if(!ok)failures.push(`${kind}/${phase} ${size}: ${message}`)}
    let statusReading=null,accessibility=null
    if(kind==='attachments'&&process.env.PDF_ATTACHMENTS_KEYBOARD==='1'){
      const status=panel.getByRole('status',{name:'附件读取状态'})
      await panel.locator('header button').focus()
      let reached=false
      for(let step=0;step<5;step++){await page.keyboard.press('Tab');if(await status.evaluate(node=>document.activeElement===node)){reached=true;break}}
      check(reached,'Tab未进入附件读取状态')
      statusReading=await status.evaluate(node=>{const r=node.getBoundingClientRect(),panel=node.closest('aside').getBoundingClientRect(),header=node.closest('aside').querySelector('header').getBoundingClientRect(),body=node.closest('.pdf-attachments-body')?.getBoundingClientRect()??panel;return {text:node.textContent,top:r.top,bottom:r.bottom,visibleTop:Math.max(panel.top,header.bottom,body.top),visibleBottom:Math.min(panel.bottom,body.bottom,innerHeight),outline:parseFloat(getComputedStyle(node).outlineWidth)}})
      check(statusReading.top>=statusReading.visibleTop-1&&statusReading.bottom<=statusReading.visibleBottom+1&&statusReading.outline>=2,'状态说明被侧栏裁切或没有键盘焦点环')
      const add=panel.getByRole('button',{name:'新增附件',exact:true})
      if(await add.isEnabled()){
        await page.keyboard.press('Shift+Tab')
        statusReading.previous=await add.evaluate(node=>{const r=node.getBoundingClientRect(),cover=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {focused:document.activeElement===node,hit:node.contains(cover),top:r.top,bottom:r.bottom,cover:cover?.outerHTML.slice(0,240)}})
        check(statusReading.previous.focused&&statusReading.previous.hit,'Shift+Tab返回新增附件时按钮被遮挡')
      }
      check(await panel.getAttribute('aria-busy')==='false','读取完成后侧栏仍标记忙碌')
      for(const row of await panel.locator('li').all())for(const action of await row.locator('button').all())check((await action.getAttribute('aria-label'))?.includes((await row.locator('strong').textContent()).replace(/（待移除）|（待新增）/g,'')),'附件操作名称没有关联文件名')
    }
    if(process.env.PDF_SIDEBAR_AXE==='1'){
      const {default:AxeBuilder}=await import('@axe-core/playwright')
      const result=await new AxeBuilder({page}).include(`.pdf-${kind==='attachments'?'attachments':'comments'}-sidebar:not([hidden])`).analyze()
      accessibility={violations:result.violations};check(!result.violations.length,`无障碍违规：${result.violations.map(item=>item.id).join(',')}`)
    }
    await page.keyboard.press('Tab')
    const controls=[]
    for(const control of await panel.locator('button:visible,input:visible,summary:visible').all()){
      await control.scrollIntoViewIfNeeded();if(await control.isEnabled())await control.focus()
      const state=await control.evaluate(node=>{
        const r=node.getBoundingClientRect(),s=getComputedStyle(node),p=node.closest('aside').getBoundingClientRect(),row=node.classList.contains('pdf-comment-row'),header=!!node.closest('header')
        const cover=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)
        return {label:node.getAttribute('aria-label')||node.textContent,tag:node.tagName,row,header,width:r.width,height:r.height,top:r.top,bottom:r.bottom,cover:cover?.outerHTML.slice(0,240),font:parseFloat(s.fontSize),radius:parseFloat(s.borderRadius),hit:node.contains(cover),within:r.x>=p.x-1&&r.right<=p.right+1&&r.y>=0&&r.bottom<=innerHeight+1,focus:node.disabled||parseFloat(s.outlineWidth)>=2}
      });controls.push(state)
      check(state.hit&&state.within,'操作滚动后仍不可达：'+state.label)
      check(state.focus,'缺少键盘焦点环：'+state.label)
      if(state.tag==='BUTTON'&&!state.row)check(state.radius>=3&&(state.header?state.font===18&&state.width===28&&state.height===28:state.font>=12&&state.font<=14&&state.height>=30&&state.height<=64),'按钮未采用紧凑侧栏样式：'+state.label)
      if(state.row)check(state.font>=12&&state.font<=14,'线程行字体不统一')
      if(state.row&&await control.evaluate(node=>node.scrollHeight>node.clientHeight+1)){
        const handle=await control.elementHandle()
        await control.press('End');await page.waitForFunction(node=>node.scrollTop+node.clientHeight>=node.scrollHeight-2,handle,{timeout:3000})
        state.textScroll=await control.evaluate(node=>({top:node.scrollTop,height:node.clientHeight,contentHeight:node.scrollHeight}))
        await control.press('Home')
        try{await page.waitForFunction(node=>node.scrollTop<=1,handle,{timeout:3000})}
        catch(error){
          const details=await control.evaluate(node=>({top:node.scrollTop,height:node.clientHeight,contentHeight:node.scrollHeight,html:node.outerHTML.slice(0,350),active:document.activeElement===node,sidebarTop:node.closest('aside').scrollTop}))
          if(directory){await writeFile(resolve(directory,'text-scroll-diagnostic.json'),JSON.stringify(details,null,2));await page.screenshot({path:resolve(directory,'text-scroll-diagnostic.png')})}
          throw error
        }
        await handle.dispose()
      }
    }
    const geometry=await panel.evaluate(node=>{const r=node.getBoundingClientRect();return {width:r.width,height:r.height,overflow:node.scrollWidth>node.clientWidth+1,header:!!node.querySelector('header'),actions:node.querySelectorAll('.pdf-object-actions').length,status:node.querySelector('[role=status]')?.textContent}})
    check(!geometry.overflow&&geometry.header,'侧栏横向溢出或缺少标题')
    check(controls.some(c=>c.header),'缺少可见关闭入口')
    check(await panel.locator('header button').evaluate(node=>{const r=node.getBoundingClientRect();return r.y>=0&&r.bottom<=innerHeight&&node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),'内容滚动后固定标题关闭不可达')
    if(kind==='attachments'&&await panel.locator('li').count())check(geometry.actions>0,'附件操作缺少分组')
    assert.deepEqual(await operations(),before)
    if(directory)await page.screenshot({path:resolve(directory,`sidebar-${kind}-${phase}-${size}.png`)})
    let closeFocus=null
    if(reopen){
      const close=panel.locator('header button');await close.click();await panel.waitFor({state:'hidden'})
      closeFocus=await page.evaluate(()=>document.activeElement?.matches('[data-source-command-id="genoffice.pdf.view.navigation.comments"],[data-source-command-id="genoffice.pdf.view.navigation.attachments"],[data-pdf-ribbon-tab][aria-selected="true"]'))
      check(closeFocus,'关闭侧栏后焦点落到隐藏区域');await reopen()
    }
    results.push({kind,phase,width,height,geometry,controls,closeFocus,statusReading,accessibility,draftUnchanged:true})
  }
  await page.setViewportSize(original)
  if(directory)await writeFile(resolve(directory,`sidebar-${kind}-${phase}-evidence.json`),JSON.stringify({kind,phase,results,failures},null,2))
  assert.deepEqual(failures,[])
  return results
}
