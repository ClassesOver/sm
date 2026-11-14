import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../',import.meta.url))
const output = resolve(process.env.OFFICE_PPTX_TEXT_OUTPUT ?? '/tmp/office-pptx-text-panels')
const port = Number(process.env.OFFICE_PPTX_TEXT_PORT ?? 4299), base = `http://127.0.0.1:${port}/reports/v1/editor/assets/`
const modes = process.env.OFFICE_PPTX_TEXT_CASES?.split(',') ?? ['find','find-matches','find-empty','find-error','find-locked','notes','notes-readonly','notes-error','notes-collapsed']
const viewports = process.env.OFFICE_PPTX_TEXT_VIEWPORTS?.split(',').map(value=>value.split('x').map(Number)) ?? [[1440,900],[768,1024],[390,844],[320,640],[640,360],[390,320]]
const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><script type="module" src="./smoke/office-pptx-text-panels-fixture.mjs"></script></body></html>'
const server = spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
let browser,log=''
server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const evidence = {kind:'real-product-components-explicit-source-callback-fixture',cases:[],failures:[],pageErrors:[]}
try {
  await mkdir(output,{recursive:true})
  for(let attempt=0;;attempt++){
    if(server.exitCode!==null) throw Error(log)
    try{if((await fetch(base)).ok)break}catch{}
    if(attempt>120)throw Error(log)
    await delay(250)
  }
  browser=await chromium.launch({headless:true})
  for(const mode of modes){
    const page=await browser.newPage();page.on('pageerror',error=>evidence.pageErrors.push({mode,message:error.message}))
    await page.route('**/office-pptx-text-panels.html?*',route=>route.fulfill({contentType:'text/html',body:html}))
    for(const [width,height] of viewports){
      await page.setViewportSize({width,height});await page.goto(`${base}office-pptx-text-panels.html?mode=${mode}`)
      await page.waitForSelector('html[data-fixture-ready=true]')
      const documentBefore=await page.locator('[data-fixture-document]').textContent(),opener=page.getByRole('button',{name:'打开面板',exact:true})
      await opener.click()
      const modal=mode.startsWith('find'),surface=page.locator(modal?'.slides-find-replace':'.slides-notes-pane')
      const check=(condition,message)=>{if(!condition)evidence.failures.push(`${mode} ${width}×${height}: ${message}`)}
      if(modal){
        check(await surface.getByLabel('查找文字',{exact:true}).evaluate(node=>document.activeElement===node),'初始焦点不是查找文字')
        if(mode!=='find'){
          await surface.getByLabel('查找文字',{exact:true}).fill(mode==='find-empty'?'无此文字':'经营数据')
          await surface.locator(`[data-command=${mode==='find-error'||mode==='find-locked'?'replaceAll':'findNext'}]`).click()
          check(!!await surface.getByRole('status').textContent(),'反馈状态为空')
        }
      }else if(mode.endsWith('error')) await surface.locator('textarea').fill('保留失败的备注输入')
      await page.evaluate(()=>document.fonts.ready)
      const measurement=await surface.evaluate(node=>{
        const rect=node.getBoundingClientRect(),fields=[...node.querySelectorAll('input,textarea')].filter(el=>el.getBoundingClientRect().width>0)
        const controls=[...node.querySelectorAll('button,input,textarea')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0})
        const text=fields.find(el=>el.type!=='checkbox'),label=text?.closest('label'),range=document.createRange()
        if(label)range.selectNodeContents(label.firstChild)
        return {x:rect.x,y:rect.y,right:rect.right,bottom:rect.bottom,width:rect.width,font:getComputedStyle(node).fontFamily,overflow:node.scrollWidth>node.clientWidth+1,
          leftLabel:!!label&&range.getBoundingClientRect().right<text.getBoundingClientRect().left,
          textWidth:text?.getBoundingClientRect().width,controls:controls.map(el=>{const r=el.getBoundingClientRect();return {kind:el.type,x:r.x,right:r.right,width:r.width,height:r.height,font:getComputedStyle(el).fontFamily}})}
      })
      check(measurement.x>=0&&measurement.right<=width+1&&!measurement.overflow,'面板横向溢出')
      check(measurement.y>=0&&measurement.bottom<=height+1,'面板高度超出视口')
      check(measurement.font.includes('Noto Sans'),'面板未继承Office字体')
      check(measurement.controls.every(c=>c.font.includes('Noto Sans')&&c.x>=measurement.x-1&&c.right<=measurement.right+1),'控件字体或横向边界不正确')
      check(measurement.controls.every(c=>c.kind==='checkbox'?c.width>=14&&c.width<=20&&c.height<=20:c.height>=28),'控件尺寸不符合紧凑PC主题')
      if(modal&&width>=1000)check(measurement.width>=500&&measurement.width<=640&&measurement.leftLabel,'PC弹窗宽度或左标签右字段布局不正确')
      if(modal)check(measurement.textWidth>=140,'查找字段过窄')
      if(mode.endsWith('readonly'))check(await surface.locator('textarea').evaluate(node=>node.readOnly),'只读备注可写')
      if(mode.endsWith('error')&&!modal)check(!!await surface.getByRole('alert').textContent(),'备注错误原因缺失')
      if(mode.startsWith('notes-host')) {
        const textarea=surface.locator('textarea');await textarea.scrollIntoViewIfNeeded()
        check(await textarea.evaluate(node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),'画布遮挡备注输入')
        check(await surface.evaluate(node=>{const frame=node.parentElement.querySelector('.slides-canvas');return getComputedStyle(node).position==='fixed'||frame.getBoundingClientRect().bottom<=node.getBoundingClientRect().top+1}),'停靠的画布行与备注行重叠')
        if(height<=480){
          const original=await textarea.inputValue();await textarea.evaluate(node=>{window.officeNotesInput=node});await textarea.click()
          const drawer=await surface.evaluate(node=>{const r=node.getBoundingClientRect();return {position:getComputedStyle(node).position,x:r.x,y:r.y,right:r.right,bottom:r.bottom,controls:[...node.querySelectorAll('textarea,button')].map(control=>{const c=control.getBoundingClientRect();return {inside:c.y>=r.y&&c.bottom<=r.bottom&&c.x>=r.x&&c.right<=r.right,accessible:control.contains(document.elementFromPoint(c.x+c.width/2,c.y+c.height/2))}})}})
          check(drawer.position==='fixed'&&drawer.x>=0&&drawer.y>=0&&drawer.right<=width&&drawer.bottom<=height,'短屏编辑备注未展开到完整视口区域')
          check(drawer.controls.every(control=>control.inside&&control.accessible),'短屏备注输入或收起按钮被裁切')
          await page.screenshot({path:join(output,`${mode}-${width}x${height}-focused.png`)})
          await page.setViewportSize({width,height:900})
          check(await surface.evaluate(node=>getComputedStyle(node).position!=='fixed'),'恢复PC高度后仍覆盖画布')
          check(await textarea.evaluate(node=>node===window.officeNotesInput&&document.activeElement===node),'切换视口重建备注输入或丢失焦点')
          check(await textarea.inputValue()===original,'切换视口修改备注文字')
          await page.setViewportSize({width,height});await opener.focus()
          check(await surface.evaluate(node=>getComputedStyle(node).position!=='fixed'),'离开焦点未恢复停靠')
        }
      }
      const focus=surface.locator(modal?'[data-command=closeFindReplace]':'.slides-notes-heading button')
      await focus.focus();await focus.scrollIntoViewIfNeeded()
      check(await focus.evaluate(node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),'底部操作无法滚动访问')
      if(modal&&height<=360)await page.screenshot({path:join(output,`${mode}-${width}x${height}-actions.png`)})
      await page.keyboard.press(modal?'Tab':'Shift')
      if(modal)check(await surface.evaluate(node=>node.contains(document.activeElement)),'Tab离开模态窗口')
      check(await page.evaluate(()=>parseFloat(getComputedStyle(document.activeElement).outlineWidth)>=2),'键盘焦点环缺失')
      await page.screenshot({path:join(output,`${mode}-${width}x${height}.png`)})
      if(modal){
        await page.keyboard.press('Escape');check(!await surface.count(),'Esc未关闭弹窗')
        check(await opener.evaluate(node=>document.activeElement===node),'关闭后未返回入口')
      }else if(!mode.endsWith('error')){
        await focus.click();check(await surface.locator('textarea').isVisible()=== (mode==='notes-collapsed'),'备注折叠切换不正确')
      }
      check(await page.locator('[data-fixture-document]').textContent()===documentBefore,'布局检查改动来源正文')
      check(await page.evaluate(()=>window.officePptxPanelCommits.length)===0,'布局检查提交了内容修改')
      evidence.cases.push({mode,width,height,measurement})
    }
    await page.close()
  }
}finally{await browser?.close();server.kill('SIGTERM');await writeFile(join(output,'evidence.json'),JSON.stringify(evidence,null,2))}
assert.deepEqual(evidence.pageErrors,[]);assert.deepEqual(evidence.failures,[])
console.log(JSON.stringify({output,cases:evidence.cases.length,failures:evidence.failures}))
