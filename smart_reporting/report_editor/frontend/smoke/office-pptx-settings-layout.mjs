import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { inspectSlidesDialogInputProtection } from './slides-dialog-input-protection.mjs'

// Uses the editor's real inline dialogs through its ribbon; no copied dialog markup.
export async function inspectPptxSettingsLayout(page, { viewports, output, draft }) {
  const evidence={kind:'actual-built-editor-inline-settings-dialogs',cases:[],failures:[],accessibility:[]}
  const specs=[
    {command:'insertTable',tab:'insert',title:'插入表格',width:420,fields:{cols:'5',rows:'2'},invalid:{cols:'0',rows:'1.5'},message:'行数和列数须为 1–75 的整数'},
    {command:'addSection',tab:'home',title:'新增节',width:480,fields:{name:'无标题节'},invalid:{name:''},message:'请输入节名称'},
    {command:'headerFooter',tab:'insert',title:'页眉和页脚',width:520,fields:{footer:''}},
  ]
  for(const viewport of viewports.split(',')){
    const [width,height]=viewport.split('x').map(Number);await page.setViewportSize({width,height})
    for(const spec of specs){
      const before=await draft(),check=(ok,message)=>{if(!ok)evidence.failures.push(`${spec.command} ${viewport}: ${message}`)}
      await page.locator(`[data-ribbon-tab="${spec.tab}"]`).click()
      const opener=page.locator(`[data-command="${spec.command}"]`);await opener.click()
      const dialog=page.getByRole('dialog',{name:spec.title,exact:true})
      check(await dialog.locator('input').first().evaluate(node=>document.activeElement===node),'初始焦点未进入首个字段')
      for(const [name,value] of Object.entries(spec.fields))assert.equal(await dialog.locator(`[name="${name}"]`).inputValue(),value)
      if(spec.command==='headerFooter'){
        await dialog.locator('[name=footerOn]').check()
        await dialog.locator('[name=footer]').fill('内部经营分析 · 长页脚文字与来源说明 '.repeat(20))
      }
      if(spec.invalid){
        for(const [name,value] of Object.entries(spec.invalid))await dialog.locator(`[name="${name}"]`).fill(value)
        await dialog.locator('button[value=ok]').click()
        assert.equal(await dialog.getByRole('alert').textContent(),spec.message)
        assert.deepEqual(await draft(),before)
        const alert=dialog.getByRole('alert')
        check(await alert.getAttribute('aria-label')===`${spec.title}错误`,'错误缺少阅读名称')
        let reached=false
        for(let step=0;step<12;step++){
          await page.keyboard.press('Tab')
          if(await alert.evaluate(node=>document.activeElement===node)){reached=true;break}
        }
        check(reached,'Tab无法进入错误说明')
        if(reached)check(await alert.evaluate(node=>{
          const r=node.getBoundingClientRect(),body=node.closest('.slides-settings-body')?.getBoundingClientRect()
          return body&&r.top>=body.top-1&&r.bottom<=body.bottom+1&&parseFloat(getComputedStyle(node).outlineWidth)>=2
        }),'错误未滚入主体可视区或没有焦点环')
      }
      const chrome=await dialog.evaluate(node=>{
        const body=node.querySelector('.slides-settings-body'),header=node.querySelector('header'),footer=node.querySelector('footer')
        if(!body||!header||!footer)return null
        const before={header:header.getBoundingClientRect().top,footer:footer.getBoundingClientRect().bottom}
        body.scrollTop=body.scrollHeight
        return {before,after:{header:header.getBoundingClientRect().top,footer:footer.getBoundingClientRect().bottom},bodyHeight:body.clientHeight,bodyScrollHeight:body.scrollHeight}
      })
      check(!!chrome&&chrome.before.header===chrome.after.header&&chrome.before.footer===chrome.after.footer,'主体滚动时标题或底部操作移动')
      if(process.env.PPTX_SETTINGS_AXE==='1'){
        const {default:AxeBuilder}=await import('@axe-core/playwright')
        const result=await new AxeBuilder({page}).include('dialog[open]').analyze()
        evidence.accessibility.push({command:spec.command,width,height,violations:result.violations})
        check(result.violations.length===0,`无障碍违规：${result.violations.map(item=>item.id).join(',')}`)
      }
      await page.evaluate(()=>document.fonts.ready)
      const geometry=await dialog.evaluate(node=>{
        const r=node.getBoundingClientRect(),controls=[...node.querySelectorAll('input,button')]
        return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,font:getComputedStyle(node).fontFamily,overflow:node.scrollWidth>node.clientWidth+1,
          fields:[...node.querySelectorAll('label')].filter(label=>label.querySelector('input:not([type=checkbox])')).map(label=>{
            const input=label.querySelector('input'),field=input.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(label.firstChild)
            const text=range.getBoundingClientRect()
            return {name:input.name,width:field.width,leftLabel:text.right<field.left&&text.top<field.bottom&&text.bottom>field.top}
          }),controls:controls.map(control=>{const c=control.getBoundingClientRect();return {type:control.type,width:c.width,height:c.height,font:getComputedStyle(control).fontFamily,x:c.x,right:c.right}})}
      })
      check(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,'弹窗超出视口或横向溢出')
      check(geometry.font.includes('Noto Sans')&&geometry.controls.every(c=>c.font.includes('Noto Sans')),'字体未继承Office主题')
      check(geometry.controls.every(c=>c.x>=geometry.x&&c.right<=geometry.right),'控件横向溢出')
      check(geometry.controls.every(c=>c.type==='checkbox'?c.width>=14&&c.width<=20&&c.height<=20:c.height>=28&&c.height<=36),'控件尺寸不符合紧凑PC主题')
      if(width>=1000)check(geometry.width===spec.width&&geometry.fields.every(field=>field.leftLabel&&field.width>=160),'PC宽度或左标签右字段不正确')
      check(geometry.fields.every(field=>field.width>=130),'输入字段过窄')
      const first=dialog.locator('[data-settings-close]'),last=dialog.locator('button[value=ok]')
      const inputProtection=process.env.PPTX_DIALOG_INPUT_PROTECTION==='1'?await inspectSlidesDialogInputProtection(page,dialog):undefined
      check(await first.count()===1,'缺少标题关闭按钮')
      await last.focus();await last.scrollIntoViewIfNeeded()
      check(await last.evaluate(node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),'底部操作不可命中')
      await page.screenshot({path:resolve(output,`settings-${spec.command}-${viewport}.png`)})
      await page.keyboard.press('Tab')
      check(await dialog.evaluate(node=>node.contains(document.activeElement)),'Tab离开弹窗')
      if(await first.count()){
        check(await first.evaluate(node=>document.activeElement===node),'Tab未从最后操作返回标题关闭')
        await page.keyboard.press('Shift+Tab')
        check(await last.evaluate(node=>document.activeElement===node),'Shift+Tab未从标题关闭返回最后操作')
      }
      await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'})
      check(await opener.evaluate(node=>document.activeElement===node),'Escape后焦点未返回入口')
      assert.deepEqual(await draft(),before)
      await opener.click()
      const reopened=page.getByRole('dialog',{name:spec.title,exact:true})
      for(const [name,value] of Object.entries(spec.fields))assert.equal(await reopened.locator(`[name="${name}"]`).inputValue(),value)
      if(await reopened.locator('[data-settings-close]').count())await reopened.locator('[data-settings-close]').click()
      else await reopened.locator('button[value=cancel]').click()
      await reopened.waitFor({state:'detached'})
      check(await opener.evaluate(node=>document.activeElement===node),'标题关闭后焦点未返回入口')
      assert.deepEqual(await draft(),before)
      evidence.cases.push({command:spec.command,width,height,geometry,chrome,invalidInputChecked:!!spec.invalid,draftUnchanged:true,inputProtection})
    }
  }
  await writeFile(resolve(output,'settings-evidence.json'),JSON.stringify(evidence,null,2))
  assert.deepEqual(evidence.failures,[],JSON.stringify(evidence.failures))
  return evidence
}
