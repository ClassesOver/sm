import assert from 'node:assert/strict'
import { join } from 'node:path'
import { writeFile } from 'node:fs/promises'
import { protectedPdfKey } from './pdf-gesture-keyboard-checks.mjs'

export const formSettingsModes = [
  ['text','addTextField','create'],['checkbox','addCheckBox','create'],['date','addDateField','create'],
  ['choice','addDropdown','create'],['radio','addRadioGroup','create'],['properties','fieldProperties','create'],
  ['arrange','alignFields','create'],['text-properties','textProperties','text-properties'],['radio-append','addRadioOption','radio-extension'],
]

export async function checkFormSettingsLayout(page,directory) {
  const cases=[],failures=[],record=(ok,message)=>{if(!ok)failures.push(message)}
  const storage=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')))
  const initial=await storage()
  const viewports=process.env.PDF_SETTINGS_VIEWPORTS?process.env.PDF_SETTINGS_VIEWPORTS.split(',').map(size=>{const [width,height]=size.split('x').map(Number);return {width,height}}):[{width:1440,height:900},{width:320,height:640},{width:640,height:360},{width:390,height:320},{width:1440,height:360}]
  const modes=process.env.PDF_SETTINGS_MODES?formSettingsModes.filter(([mode])=>process.env.PDF_SETTINGS_MODES.split(',').includes(mode)):formSettingsModes
  for(const [mode,id,kind] of modes)for(const viewport of viewports){
    await page.setViewportSize(viewport)
    await page.locator('[data-pdf-ribbon-tab="formDesign"]').click()
    const command=page.locator(`[data-source-command-id="genoffice.pdf.formDesign.${id}"]`)
    assert.equal(await command.count(),1,`missing command ${id}`)
    await command.click()
    const panel=page.locator(`.pdf-form-${kind}-panel`),key=`${mode}-${viewport.width}x${viewport.height}`
    await panel.waitFor({state:'visible'})
    const structure=await panel.evaluate(element=>({header:!!element.querySelector('header h3'),fieldset:!!element.querySelector(':scope > fieldset > legend'),
      scrollable:getComputedStyle(element).overflowY==='auto',width:element.getBoundingClientRect().width,overflow:element.scrollWidth>element.clientWidth+1,
      radioRows:element.querySelectorAll('table[aria-label="单选选项"] tbody tr').length}))
    record(structure.header&&structure.fieldset&&structure.scrollable,`${key}: desktop structure`)
    record(!structure.overflow&&structure.width<=viewport.width+1,`${key}: panel overflow`)
    if(mode==='radio')record(structure.radioRows===2,`${key}: editable radio rows`)
    const controls=panel.locator('button,input,select,textarea'),checks=[]
    for(let index=0;index<await controls.count();index++){
      const control=controls.nth(index);await control.scrollIntoViewIfNeeded()
      const state=await control.evaluate(element=>{
        const box=element.getBoundingClientRect(),style=getComputedStyle(element),native=element.matches('input[type=checkbox],input[type=radio]')
        return {label:element.getAttribute('aria-label')??element.textContent,tag:element.tagName,type:element.getAttribute('type'),native,disabled:element.matches(':disabled'),uncheckedRadio:element.matches('input[type=radio]:not(:checked)'),
          height:box.height,font:style.fontFamily,themeFont:getComputedStyle(element.closest('.native-pdf-editor')).fontFamily,
          geometry:{top:box.top,bottom:box.bottom,panel:element.closest('.pdf-form-settings-panel').getBoundingClientRect().toJSON(),header:element.closest('.pdf-form-settings-panel').querySelector('header').getBoundingClientRect().toJSON()},
          hitTargets:[[.5,.5],[.12,.12],[.88,.12],[.12,.88],[.88,.88]].map(([x,y])=>{const hit=document.elementFromPoint(box.x+box.width*x,box.y+box.height*y);return {ok:element.contains(hit),target:hit?.outerHTML.slice(0,220)}}),
          hits:[[.5,.5],[.12,.12],[.88,.12],[.12,.88],[.88,.88]].every(([x,y])=>element.contains(document.elementFromPoint(box.x+box.width*x,box.y+box.height*y)))}
      })
      record(state.hits,`${key}/${index}: hit obstruction`)
      if(!state.native){record(state.font===state.themeFont,`${key}/${index}: theme font`);record(state.tag==='TEXTAREA'?state.height>=60:state.height>=26&&state.height<=32,`${key}/${index}: control height ${state.height}`)}
      if(!state.disabled){
        await control.focus()
        if(!state.uncheckedRadio){await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')}
        const focus=await control.evaluate(element=>({active:document.activeElement===element,ring:parseFloat(getComputedStyle(element).outlineWidth)>=2&&getComputedStyle(element).outlineStyle!=='none'}))
        record(focus.active&&focus.ring,`${key}/${index}: keyboard focus or ring`);state.focus=focus
      }
      checks.push(state)
    }
    let radioKeyboard=null
    if(mode==='radio'){
      const radios=panel.locator('table input[type=radio]');await radios.first().focus();await page.keyboard.press('ArrowRight')
      const next=await radios.nth(1).isChecked();await page.keyboard.press('ArrowLeft');const previous=await radios.first().isChecked()
      record(next&&previous,`${key}: native radio arrow selection`)
      const region=panel.getByRole('region',{name:'单选选项表格，可横向滚动',exact:true});await region.scrollIntoViewIfNeeded();await region.evaluate(element=>{element.scrollLeft=0});await region.focus()
      const dimensions=await region.evaluate(element=>({clientWidth:element.clientWidth,scrollWidth:element.scrollWidth,ring:parseFloat(getComputedStyle(element).outlineWidth)>=2}))
      if(dimensions.scrollWidth>dimensions.clientWidth+1){await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>document.querySelector('.pdf-form-radio-scroll').scrollLeft>0)}
      const scrollLeft=await region.evaluate(element=>element.scrollLeft);record(dimensions.ring,`${key}: scroll region focus ring`)
      radioKeyboard={next,previous,...dimensions,scrollLeft}
    }
    await page.screenshot({path:join(directory,`${key}-end.png`)})
    await panel.evaluate(element=>{element.scrollTop=0})
    await page.screenshot({path:join(directory,`${key}.png`)})
    const close=panel.locator('button').first(),protectedKeys=[]
    if(process.env.PDF_GESTURE_KEYBOARD==='1')for(const mode of ['composing','legacy229','consumed']){
      const input=panel.locator('input:not(:disabled),select:not(:disabled),textarea:not(:disabled)').first();await input.focus()
      protectedKeys.push({mode,...await protectedPdfKey(input,'Escape',mode)})
      record(await panel.isVisible()&&await input.evaluate(node=>node===document.activeElement),`${key}: ${mode} Escape closes panel or moves focus`)
    }
    let accessibility=null
    if(process.env.PDF_GESTURE_AXE==='1'){
      const {default:AxeBuilder}=await import('@axe-core/playwright'),result=await new AxeBuilder({page}).include('.pdf-form-settings-panel:not([hidden])').analyze()
      accessibility={violations:result.violations};record(!result.violations.length,`${key}: accessibility ${result.violations.map(issue=>issue.id).join(',')}`)
    }
    await close.focus()
    if(viewport.width===390&&viewport.height===320)await page.screenshot({path:join(directory,`${key}-close-focused.png`)})
    await page.keyboard.press('Escape')
    record(await panel.isHidden(),`${key}: Escape`)
    record(await command.evaluate(element=>document.activeElement===element),`${key}: opener focus`)
    if(await panel.isVisible())await close.click()
    cases.push({mode,id,viewport,structure,controls:checks,radioKeyboard,protectedKeys,accessibility})
  }
  assert.deepEqual(await storage(),initial)
  const evidence={cases,failures,draftUnchanged:true}
  await writeFile(join(directory,'layout.json'),JSON.stringify(evidence,null,2))
  assert.deepEqual(failures,[],'PC PDF form settings')
  await page.setViewportSize({width:1440,height:900})
  return evidence
}
