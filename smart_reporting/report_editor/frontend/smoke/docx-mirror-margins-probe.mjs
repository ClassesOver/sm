// 独立镜像边距真实RED：逻辑页码12/13，必须按显示页号交换inside/outside。
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {spawn} from 'node:child_process'
const start=Number(process.env.DOCX_MIRROR_START??12)
assert.ok(start===12||start===13)
const temporary=new URL(`./.mirror-probe-${process.pid}.mjs`,import.meta.url)
let code=await readFile(new URL('./docx-insert-gui-smoke.mjs',import.meta.url),'utf8')
const replace=(a,b)=>{assert.equal(code.split(a).length,2,`unique mirror anchor ${a.slice(0,50)}`);code=code.replace(a,b)}
replace("    document.save(payload['path'])",`    if payload.get('case') == 'pagination-snapshot-mirror':
        from docx.shared import Inches
        from docx.oxml import OxmlElement
        for p in list(document.paragraphs): p._element.getparent().remove(p._element)
        sec=document.sections[0];sec.page_width=Inches(5);sec.page_height=Inches(5)
        sec.left_margin=Inches(1);sec.right_margin=Inches(.5);sec.top_margin=Inches(.5);sec.bottom_margin=Inches(.5)
        pg=OxmlElement('w:pgNumType');pg.set(qn('w:start'),'${start}');sec._sectPr.append(pg)
        document.settings.element.append(OxmlElement('w:mirrorMargins'))
        document.settings.odd_and_even_pages_header_footer=True
        document.add_paragraph('Even logical page twelve')
        p=document.add_paragraph('Odd logical page thirteen');p.paragraph_format.page_break_before=True
    document.save(payload['path'])`)
replace("    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, cuts, pageErrors }))",`    const body=await editor.evaluate(pm=>({x:pm.getBoundingClientRect().left,blocks:[...pm.querySelectorAll('p[data-idx]')].map(p=>({text:p.textContent,x:p.getBoundingClientRect().left,width:p.getBoundingClientRect().width}))}))
    console.log(JSON.stringify({probe:'mirror-logical-page-margins',cuts,body,pageErrors}))
    assert.deepEqual(cuts.map(c=>c.pageNo),[${start},${start+1}])
    assert.ok(Math.abs(body.blocks[0].x-body.x-${start%2===0?48:96})<1,'逻辑偶数12页必须使用outside边距48px')
    assert.ok(Math.abs(body.blocks[1].x-body.x-${start%2===0?96:48})<1,'逻辑奇数13页必须使用inside边距96px')
    const gaps=await editor.evaluate(pm=>[...pm.querySelectorAll('.page-gap')].map(el=>({left:el.style.getPropertyValue('--gap-ml'),right:el.style.getPropertyValue('--gap-mr')})))
    assert.deepEqual(gaps,[{left:'${start%2===0?96:48}px',right:'${start%2===0?48:96}px'}])
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await editor.evaluate(el=>el.editor.commands.setTextSelection(el.editor.state.doc.content.size-1))
    await page.locator('[data-tab-id="insert"]').click();await page.locator('[data-action="insert-page-number"]').click();await page.locator('[data-source-action="insert-page-number-footer-center"]').click()
    const saved=await save(2)
    assert.deepEqual(saved.body,sourceInspection.body);assert.deepEqual(saved.sections,sourceInspection.sections)
    assert.equal(saved.packageParts['word/settings.xml'],sourceInspection.packageParts['word/settings.xml'])
    const operations=savePayloads.get(1).operations
    assert.equal(operations.length,1);assert.equal(operations[0].sectionId,sourceInspection.model.sections[0].sectionId)
    assert.equal(operations[0].variant,'${start%2===0?'default':'even'}');assert.deepEqual(pageErrors,[])
    console.log(JSON.stringify({ok:true,probe:'mirror-body-preview-edge-save',builtPreview,logicalPages:cuts.map(c=>c.pageNo),gaps,pageErrors}))`)
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", "  if (builtPreview && smokeCase === 'pagination-snapshot-mirror') {")
try{
 await writeFile(temporary,code)
 process.exitCode=await new Promise(resolve=>spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env,DOCX_INSERT_CASE:'pagination-snapshot-mirror'}}).on('exit',resolve))??1
}finally{await unlink(temporary).catch(()=>{})}
