// 仅验证多栏→none→多栏宿主状态恢复，无保存整链。
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {spawn} from 'node:child_process'
const temporary=new URL(`./.columns-state-${process.pid}.mjs`,import.meta.url)
let code=await readFile(new URL('./docx-insert-gui-smoke.mjs',import.meta.url),'utf8')
const replace=(a,b)=>{assert.equal(code.split(a).length,2,`unique anchor ${a.slice(0,50)}`);code=code.replace(a,b)}
const mixed=process.env.DOCX_COLUMNS_MIXED==='1'
replace("    document.save(payload['path'])",`    if payload.get('case') == 'columns-state':
        from docx.shared import Inches
        for p in list(document.paragraphs): p._element.getparent().remove(p._element)
        sec=document.sections[0];sec.page_width=Inches(5);sec.page_height=Inches(5)
        sec.left_margin=Inches(.5);sec.right_margin=Inches(.5);sec.top_margin=Inches(.5);sec.bottom_margin=Inches(.5)
        if ${mixed?'True':'False'}:
            document.add_paragraph('Single initial section')
            sec=document.add_section(WD_SECTION.CONTINUOUS)
        sec._sectPr.find(qn('w:cols')).set(qn('w:num'),'2')
        for i in range(12):document.add_paragraph('State line '+str(i))
    document.save(payload['path'])`)
replace("  if (smokeCase === 'hf-insert-delete') {",`  if(smokeCase==='columns-state'){
    const mixed=${mixed}
    const facts=()=>editor.evaluate(pm=>({columns:getComputedStyle(pm).columnCount,height:pm.style.height,uniform:pm.classList.contains('native-uniform-columns'),decos:pm.querySelectorAll('.doc-col-block').length,gaps:pm.querySelectorAll('.page-gap').length,width:pm.getBoundingClientRect().width}))
    await page.waitForFunction(isMixed=>{const pm=document.querySelector('.docx-canvas .tiptap');return isMixed?pm.querySelector('.doc-col-block'):getComputedStyle(pm).columnCount==='2'},mixed)
    const before=await facts()
    await editor.evaluate(pm=>pm.editor.commands.setTextSelection(pm.editor.state.doc.content.size-1))
    await page.locator('[data-tab-id="layout"]').click();await page.getByLabel('分栏',{exact:true}).selectOption('1')
    await page.waitForFunction(()=>{const pm=document.querySelector('.docx-canvas .tiptap');return !pm.querySelector('.doc-col-block')&&!pm.classList.contains('native-uniform-columns')&&pm.style.height==='';})
    const none=await facts();assert.equal(none.height,'');assert.equal(none.decos,0);assert.equal(none.gaps,0);assert.equal(none.width,480)
    await page.getByLabel('分栏',{exact:true}).selectOption('2')
    await page.waitForFunction(isMixed=>{const pm=document.querySelector('.docx-canvas .tiptap');return isMixed?pm.querySelector('.doc-col-block'):getComputedStyle(pm).columnCount==='2'},mixed)
    const after=await facts();assert.equal(after.uniform,before.uniform);assert.equal(after.decos,before.decos)
    assert.deepEqual(pageErrors,[]);assert.equal(savePayloads.size,0)
    console.log(JSON.stringify({ok:true,probe:'columns-none-state-recovery',mixed,before,none,after,pageErrors}))
  }else if (smokeCase === 'hf-insert-delete') {`)
try{
 await writeFile(temporary,code)
 process.exitCode=await new Promise(resolve=>spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env,NATIVE_GUI_PREVIEW:'0',DOCX_INSERT_CASE:'columns-state'}}).on('exit',resolve))??1
}finally{await unlink(temporary).catch(()=>{})}
