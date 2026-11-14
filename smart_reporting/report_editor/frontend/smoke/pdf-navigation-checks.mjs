import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

// 从真实构建入口检查导航与来源属性，不复制产品DOM。
export async function inspectPdfNavigation(page,{operations,directory,phase,fileSize}) {
  if(!process.env.PDF_NAVIGATION_VIEWPORTS)return []
  const original=page.viewportSize(),before=await operations(),results=[],failures=[]
  if(directory)await mkdir(directory,{recursive:true})
  const check=(ok,label)=>{if(!ok)failures.push(label)}
  for(const size of process.env.PDF_NAVIGATION_VIEWPORTS.split(',')){
    const [width,height]=size.split('x').map(Number);await page.setViewportSize({width,height})
    for(const kind of ['thumbnails','outline','properties']){
      await page.locator(`[data-pdf-ribbon-tab="${kind==='properties'?'home':'view'}"]`).click()
      const selector=kind==='properties'?'.pdf-properties-panel':kind==='outline'?'.pdf-outline':'.pdf-thumbnails',panel=page.locator(selector)
      const command=kind==='properties'?'home.properties.documentProperties':`view.navigation.${kind}`
      const entry=page.locator(`[data-source-command-id="genoffice.pdf.${command}"]`)
      if(!await panel.isVisible())await entry.click()
      await panel.waitFor({state:'visible'});await page.keyboard.press('Tab')
      if(kind==='properties'&&directory){await panel.evaluate(node=>{node.scrollTop=0});await panel.locator('header').scrollIntoViewIfNeeded();await page.screenshot({path:resolve(directory,`navigation-${phase}-properties-top-${size}.png`)})}
      const controls=[]
      for(const control of await panel.locator('button').all()){
        const target=kind==='thumbnails'&&await control.locator('span').count()?control.locator('span'):control
        await target.scrollIntoViewIfNeeded();await control.evaluate(node=>node.focus({preventScroll:true}))
        const c=await control.evaluate(node=>{
          const target=node.classList.contains('pdf-thumbnail')?node.querySelector('span'):node,r=target.getBoundingClientRect(),s=getComputedStyle(node),header=!!node.closest('header')
          return {label:node.getAttribute('aria-label')||node.textContent,header,width:r.width,height:r.height,font:parseFloat(s.fontSize),hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),within:r.x>=0&&r.right<=innerWidth+1&&r.y>=0&&r.bottom<=innerHeight+1,focus:parseFloat(s.outlineWidth)>=2}
        });controls.push(c)
        check(c.hit&&c.within,`${phase}/${kind}/${size}: 操作不可达 ${c.label}`)
        check(c.focus,`${phase}/${kind}/${size}: 焦点环缺失 ${c.label}`)
        check(c.header?c.width===28&&c.height===28:c.font>=12&&c.font<=14,`${phase}/${kind}/${size}: 控件未采用桌面样式 ${c.label}`)
        if(kind==='outline'&&!c.header&&await control.evaluate(node=>node.scrollHeight>node.clientHeight+1)){
          const handle=await control.elementHandle();await control.press('End')
          await page.waitForFunction(node=>node.scrollTop+node.clientHeight>=node.scrollHeight-2,handle)
          c.textScroll=await control.evaluate(node=>({top:node.scrollTop,height:node.clientHeight,contentHeight:node.scrollHeight}))
          await control.press('Home');await page.waitForFunction(node=>node.scrollTop<=1,handle);await handle.dispose()
        }
      }
      const geometry=await panel.evaluate(node=>{const r=node.getBoundingClientRect();return {width:r.width,height:r.height,overflowX:node.scrollWidth>node.clientWidth+1,header:!!node.querySelector('header'),current:node.querySelectorAll('[aria-current="page"]').length,pairs:node.querySelectorAll('dt').length}})
      check(geometry.header&&!geometry.overflowX,`${phase}/${kind}/${size}: 缺少标题或横向溢出`)
      if(kind==='properties'){
        check(geometry.height<=Math.min(300,height*.45)+2,`${phase}/${kind}/${size}: 属性占用过多工作区`)
        const values=await panel.locator('dd').evaluateAll(nodes=>nodes.map(n=>({name:n.dataset.property,text:n.textContent,overflow:n.scrollWidth>n.clientWidth+1})))
        check(values.length===10&&values.every(v=>!v.overflow),`${phase}/${kind}/${size}: 属性缺失或长值溢出`)
        const title=values.find(v=>v.name==='Title');check(title?.text==='桌面属性与导航核验 · '+ '长标题'.repeat(40),`${phase}/${kind}/${size}: 来源标题未完整保留`)
        check(values.find(v=>v.name==='File Size')?.text===`${fileSize} bytes`,`${phase}/${kind}/${size}: 来源文件大小不准确`)
        await panel.locator('dd').last().scrollIntoViewIfNeeded()
      }else{
        const button=panel.locator(kind==='thumbnails'?'.pdf-thumbnail':'.pdf-outline-link').last()
        await button.scrollIntoViewIfNeeded();await button.press('Space')
        check(await button.getAttribute('aria-current')==='page',`${phase}/${kind}/${size}: 当前页标记缺失`)
        const identity=await button.getAttribute('data-page-id')
        const active=await page.locator('.pdf-page.is-active').getAttribute('data-page-id')
        check(identity===active,`${phase}/${kind}/${size}: 选中页身份与正文不一致`)
        await page.waitForFunction(id=>{
          const node=[...document.querySelectorAll('.pdf-page')].find(node=>node.dataset.pageId===id),viewport=document.querySelector('.pdf-document-pages')
          if(!node||!viewport)return false
          const r=node.getBoundingClientRect(),v=viewport.getBoundingClientRect();return r.top<v.bottom&&r.bottom>v.top
        },identity)
      }
      const close=panel.locator('header button');let closeFocus=null
      if(await close.count()){
        const hit=await close.evaluate(node=>{const r=node.getBoundingClientRect();return r.y>=0&&r.bottom<=innerHeight&&node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))})
        check(hit,`${phase}/${kind}/${size}: 内容滚动后标题关闭被遮挡`)
        if(directory)await page.screenshot({path:resolve(directory,`navigation-${phase}-${kind}-${size}.png`)})
        const changedTab=width===1440&&height===360
        if(changedTab)await page.locator(`[data-pdf-ribbon-tab="${kind==='properties'?'view':'home'}"]`).click()
        await close.click();await panel.waitFor({state:'hidden'})
        closeFocus=changedTab?await page.locator('[data-pdf-ribbon-tab][aria-selected="true"]').evaluate(node=>document.activeElement===node):await entry.evaluate(node=>document.activeElement===node)
        check(closeFocus,`${phase}/${kind}/${size}: 关闭后未返回入口`)
      }else if(directory)await page.screenshot({path:resolve(directory,`navigation-${phase}-${kind}-${size}.png`)})
      assert.deepEqual(await operations(),before)
      results.push({phase,kind,width,height,geometry,controls,closeFocus,draftUnchanged:true})
    }
  }
  await page.setViewportSize(original)
  if(directory)await writeFile(resolve(directory,`navigation-${phase}-evidence.json`),JSON.stringify({results,failures},null,2))
  assert.deepEqual(failures,[])
  return results
}
