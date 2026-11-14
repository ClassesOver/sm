import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'
import {join} from 'node:path'

// 对真实宿主逐控件检查；选区配置只留在当前编辑表单，不加入草稿。
export async function checkPdfTextSettingsLayout(page,{directory,reset}){
 const viewports=[{width:1440,height:900},{width:320,height:640},{width:640,height:360},{width:390,height:320},{width:1440,height:360}],cases=[],failures=[]
 const record=(ok,label)=>{if(!ok)failures.push(label)}
 const luminance=color=>{const values=color.match(/[\d.]+/g).slice(0,3).map(value=>Number(value)/255).map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4);return .2126*values[0]+.7152*values[1]+.0722*values[2]}
 const contrast=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
 const storage=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).sort())
 for(const viewport of viewports){
  await page.setViewportSize(viewport);await reset()
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.home.edit.editText"]').click()
  const panel=page.locator('.pdf-text-editor'),textarea=panel.getByLabel('替换后的文字',{exact:true})
  await panel.getByLabel('待修改文字对象',{exact:true}).selectOption({label:'source page one'});await textarea.fill('AABBCC')
  const before=await storage()
  for(const state of ['unselected','selected','colored']){
   const key=`${state}-${viewport.width}x${viewport.height}`
   await textarea.focus();await textarea.press('Home')
   if(state!=='unselected'){
    await textarea.press('ArrowRight');await textarea.press('ArrowRight');await textarea.press('Shift+ArrowRight');await textarea.press('Shift+ArrowRight')
    await panel.getByLabel('选区字体',{exact:true}).selectOption('times')
    if(state==='colored'){await panel.getByLabel('替换文字指定颜色',{exact:true}).check();await panel.getByLabel('替换文字颜色',{exact:true}).fill('#0000ff');await panel.getByLabel('选区指定颜色',{exact:true}).check();await panel.getByLabel('选区颜色',{exact:true}).fill('#ff0000')}
    await panel.locator('[data-pdf-selection-style-apply]').click()
    assert.deepEqual(await textarea.evaluate(node=>[node.selectionStart,node.selectionEnd,document.activeElement===node]),[2,4,true])
   }
   const structure=await panel.evaluate(element=>({title:element.querySelector('header h3')?.textContent,labels:Array.from(element.querySelectorAll('.pdf-text-content label')).filter(label=>label.control).length,overflow:element.scrollWidth>element.clientWidth+1,scrollable:getComputedStyle(element.querySelector('.pdf-text-settings-body')??element).overflowY==='auto',height:element.getBoundingClientRect().height}))
   record(structure.title==='原位改字',`${key}: panel title`);record(structure.labels===2,`${key}: visible content labels`);record(!structure.overflow,`${key}: panel overflow`);record(structure.scrollable,`${key}: panel scroll`)
   const original=panel.locator('.pdf-original-text');await original.scrollIntoViewIfNeeded();await original.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
   const originalFocus=await original.evaluate(element=>({active:document.activeElement===element,tabIndex:element.tabIndex,ring:parseFloat(getComputedStyle(element).outlineWidth)>=2,role:element.getAttribute('role')}));record(originalFocus.active&&originalFocus.tabIndex===0&&originalFocus.ring&&originalFocus.role==='region',`${key}: original preview keyboard access`)
   const controls=[],targets=panel.locator('input,select,textarea,button')
   for(let index=0;index<await targets.count();index++){
    const control=targets.nth(index);if(!await control.isVisible())continue
    await control.scrollIntoViewIfNeeded()
    const disabled=await control.isDisabled()
    let focus=null
    if(!disabled){
     await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')
     focus=await control.evaluate(element=>{const style=getComputedStyle(element);return {active:document.activeElement===element,ring:style.outlineStyle!=='none'&&parseFloat(style.outlineWidth)>=2}})
    }
    const metrics=await control.evaluate(element=>{
     const box=element.getBoundingClientRect(),style=getComputedStyle(element),root=element.closest('.native-pdf-editor'),native=element instanceof HTMLInputElement&&element.type==='checkbox'
     const points=[[box.x+box.width/2,box.y+box.height/2],[box.left+3,box.top+3],[box.right-3,box.top+3],[box.left+3,box.bottom-3],[box.right-3,box.bottom-3]]
     const obstruction=points.map(([x,y])=>{const hit=document.elementFromPoint(x,y);return {x,y,hit:hit?.tagName,css:hit?.className,text:hit?.textContent?.slice(0,40)}})
     return {obstruction,label:element.getAttribute('aria-label')??element.textContent,tag:element.tagName,type:element.type,native,height:box.height,font:style.fontFamily,themeFont:getComputedStyle(root).fontFamily,hits:points.every(([x,y])=>{const hit=document.elementFromPoint(x,y);return hit===element||element.contains(hit)})}
    })
    record(metrics.font===metrics.themeFont,`${key}: ${metrics.label}: theme font`)
    record(metrics.hits,`${key}: ${metrics.label}: hit edges`)
    record(metrics.tag==='TEXTAREA'?metrics.height>=60:Math.abs(metrics.height-(metrics.native?14:28))<1,`${key}: ${metrics.label}: control height`)
    if(!disabled){record(focus.active,`${key}: ${metrics.label}: Tab return`);record(focus.ring,`${key}: ${metrics.label}: focus ring`)}
    let hoverContrast=null
    if(metrics.tag==='BUTTON'&&!disabled){await control.hover();const colors=await control.evaluate(element=>{const style=getComputedStyle(element);return [style.color,style.backgroundColor]});hoverContrast=contrast(...colors);record(hoverContrast>=4.5,`${key}: ${metrics.label}: hover text contrast`)}
    controls.push({...metrics,disabled,focus,hoverContrast})
   }
   await page.screenshot({path:join(directory,key+'-end.png')})
   await panel.evaluate(element=>{(element.querySelector('.pdf-text-settings-body')??element).scrollTop=0});await panel.scrollIntoViewIfNeeded();await page.screenshot({path:join(directory,key+'.png')})
   assert.deepEqual(await storage(),before,'layout controls must not stage draft changes')
   cases.push({state,viewport,structure,originalFocus,controls});console.log(JSON.stringify({layout:key,controls:controls.length,failures:failures.length}))
  }
 }
 const result={cases,failures,draftUnchanged:true};await writeFile(join(directory,'layout.json'),JSON.stringify(result,null,2));return result
}
