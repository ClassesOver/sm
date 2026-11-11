// 独立真实RED：uniform多栏，同一当前DOM按固定源measuring-columns宽度测量。
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {spawn} from 'node:child_process'
const temporary=new URL(`./.columns-probe-${process.pid}.mjs`,import.meta.url)
let code=await readFile(new URL('./docx-insert-gui-smoke.mjs',import.meta.url),'utf8')
const replace=(a,b)=>{assert.equal(code.split(a).length,2,`unique anchor: ${a.slice(0,50)}`);code=code.replace(a,b)}
replace("        pg = sec._sectPr.find(qn('w:pgNumType'))", "        info['columns'] = int(sec._sectPr.find(qn('w:cols')).get(qn('w:num'), '1'))\n        pg = sec._sectPr.find(qn('w:pgNumType'))")
replace("    document.save(payload['path'])",`    if payload.get('case') == 'pagination-snapshot-columns':
        from docx.shared import Inches, Pt
        from docx.oxml import OxmlElement
        for p in list(document.paragraphs): p._element.getparent().remove(p._element)
        sec=document.sections[0]; sec.page_height=Inches(5); sec.page_width=Inches(5)
        sec.top_margin=Inches(.5); sec.bottom_margin=Inches(.5); sec.left_margin=Inches(.5); sec.right_margin=Inches(.5)
        sec.different_first_page_header_footer=True
        cols=sec._sectPr.find(qn('w:cols')); cols.set(qn('w:num'),'2'); cols.set(qn('w:space'),'360')
        for i in range(20):
            p=document.add_paragraph('Line '+str(i)); p.paragraph_format.space_after=Pt(6)
    document.save(payload['path'])`)
replace("    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, cuts, pageErrors }))",`    const reference=builtPreview?null:await page.evaluate(async()=>{
      const root='/reports/v1/editor/assets/src/vendor/genoffice-docs/apps/docs/src/renderer/'
      const {parseDocxOffThread}=await import(root+'parse-off-thread.ts')
      const {readSections,readSectionSettings}=await import('/reports/v1/editor/assets/@id/@genoffice/docx-engine')
      const {sectionColGeom}=await import(root+'pagination-sections.ts')
      const {withMeasuredPaginationSnapshot,slicePaginationSnapshot}=await import(root+'pagination-snapshot.ts')
      const parsed=await parseDocxOffThread(new Uint8Array(await(await fetch('/reports/v1/native/fixture-insert/1/api/file')).arrayBuffer()))
      const sections=readSections(parsed),section=readSectionSettings(parsed),colFlow=sectionColGeom(sections[0])
      const pm=document.querySelector('.docx-canvas .tiptap'),original=pm.style.width
      pm.style.width=(colFlow.colWidthPx+(section.marginLeft+section.marginRight)/15)+'px'
      try{return withMeasuredPaginationSnapshot({pm,section,sections,canvasTop:section.marginTop/15,colMode:'uniform'},m=>{
        const snap=slicePaginationSnapshot({...m,section,sections,colMode:'uniform',colFlow,hfParts:{},hf:{header:null,footer:null,titlePg:false,evenOddHf:false}})
        return {colFlow,width:pm.getBoundingClientRect().width,cuts:snap.cuts.map(({start,end,pageNo,regions})=>({start,end,pageNo,regions}))}
      })}finally{pm.style.width=original}
    })
    console.log(JSON.stringify({probe:'uniform-columns',actual:cuts,reference,pageErrors}))
    assert.equal(cuts.length,reference?.cuts.length??1,'同一双栏文档必须以实际栏宽与双栏容量分页')`)
if(process.env.DOCX_COLUMNS_CURSOR!=='1' && process.env.DOCX_COLUMNS_MIXED!=='1'){
 replace("    assert.equal(cuts.length,reference?.cuts.length??1,'同一双栏文档必须以实际栏宽与双栏容量分页')",`    assert.equal(cuts.length,reference?.cuts.length??1,'同一双栏文档必须以实际栏宽与双栏容量分页')
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    const canvas=await editor.evaluate(pm=>({cols:getComputedStyle(pm).columnCount,width:pm.getBoundingClientRect().width,neutral:pm.classList.contains('measuring-columns'),firstLeft:pm.querySelector('p').getBoundingClientRect().left,lastLeft:pm.querySelector('p:last-child').getBoundingClientRect().left}))
    assert.equal(canvas.cols,'2');assert.equal(canvas.width,480);assert.equal(canvas.neutral,false);assert.ok(canvas.lastLeft>canvas.firstLeft)
    await page.locator('[data-tab-id="insert"]').click();await page.locator('[data-action="insert-page-number"]').click()
    await page.locator('[data-source-action="insert-page-number-footer-center"]').click()
    const saved=await save(2)
    assert.equal(savePayloads.get(1).operations.find(op=>op.kind==='setHeaderFooter').variant,'first')
    assert.ok(!savePayloads.get(1).operations.some(op=>op.kind==='setSectionLayout'))
    assert.deepEqual(saved.body,sourceInspection.body)
    assert.equal(saved.sections[0].columns,2)
    await open(2);await page.locator('[data-tab-id="layout"]').click()
    assert.equal(await page.getByLabel('分栏',{exact:true}).inputValue(),'2')
    await page.getByLabel('分栏',{exact:true}).selectOption('1')
    const restored=await editor.evaluate(pm=>({cols:getComputedStyle(pm).columnCount,width:pm.getBoundingClientRect().width,uniform:pm.classList.contains('native-uniform-columns'),gaps:pm.querySelectorAll('.page-gap').length}))
    assert.equal(restored.cols,'auto');assert.equal(restored.width,480);assert.equal(restored.uniform,false);assert.equal(restored.gaps,0)
    assert.deepEqual(pageErrors,[])
    console.log(JSON.stringify({ok:true,probe:'uniform-columns-edge-save',builtPreview,pages:cuts.length,canvas,restored,pageErrors}))`)
}
if(process.env.DOCX_COLUMNS_MIXED==='1'){
 replace("    const reference=builtPreview?null:await page.evaluate(async()=>{", "    const mixedCanvas=await editor.evaluate(pm=>({width:pm.getBoundingClientRect().width,height:pm.getBoundingClientRect().height,gaps:pm.querySelectorAll('.page-gap').length,blocks:[...pm.querySelectorAll('p[data-idx]')].map(p=>({text:p.textContent,x:p.getBoundingClientRect().left,y:p.getBoundingClientRect().top,width:p.getBoundingClientRect().width,col:p.classList.contains('doc-col-block')}))})); const reference=builtPreview?null:await page.evaluate(async()=>{")
 replace("    document.save(payload['path'])",`    if payload.get('case') == 'pagination-snapshot-columns':
        for p in list(document.paragraphs): p._element.getparent().remove(p._element)
        document.sections[0]._sectPr.find(qn('w:cols')).set(qn('w:num'),'1')
        document.add_paragraph('Single column before continuous section')
        last=document.add_section(WD_SECTION.CONTINUOUS)
        last._sectPr.find(qn('w:cols')).set(qn('w:num'),'2')
        for i in range(24): document.add_paragraph('Mixed line '+str(i))
    document.save(payload['path'])`)
 replace("colMode:'uniform'},m=>{", "colMode:'mixed'},m=>{")
 replace("      const {sectionColGeom}=await import(root+'pagination-sections.ts')", "      const {sectionColGeom,columnLayoutSpecs,sectionWidthSpecs,newWidthPassState,widthPassGate}=await import(root+'pagination-sections.ts'); const {setColumnLayout}=await import(root+'editor/column-layout.ts')")
 replace("      pm.style.width=(colFlow.colWidthPx+(section.marginLeft+section.marginRight)/15)+'px'", "      pm.style.width=(sections[0].settings.pageWidth/15)+'px'")
 replace("      try{return withMeasuredPaginationSnapshot", "      const history=newWidthPassState(); let result; try{for(let pass=0;pass<8;pass++){result=withMeasuredPaginationSnapshot")
 replace("section,sections,colMode:'uniform',colFlow,hfParts", "section,sections,colMode:'mixed',colFlow:null,hfParts")
 replace("        return {colFlow,width:pm.getBoundingClientRect().width,cuts:snap.cuts.map(({start,end,pageNo,regions})=>({start,end,pageNo,regions}))}", "        const columns=columnLayoutSpecs(m.blocks,snap.cuts,m.live); const again=widthPassGate(history,columns); const widths=sectionWidthSpecs(m.blocks,m.live,snap.geoms,sections[0].settings.pageWidth/15); const merged=new Map(); for(const spec of [...widths,...columns]){const prev=merged.get(spec.el);merged.set(spec.el,prev?{...prev,...spec,dx:prev.dx+spec.dx,dy:prev.dy+spec.dy}:spec)};setColumnLayout(pm.editor.view,[...merged.values()]); return {again,sectionFacts:m.live.map(s=>({columns:s.settings.columns,startType:s.startType,first:s.firstBlockIndex,last:s.lastBlockIndex})),colFlow,width:pm.getBoundingClientRect().width,cuts:snap.cuts.map(({start,end,pageNo,regions})=>({start,end,pageNo,regions}))}")
 replace("      })}finally{pm.style.width=original}", "      });if(!result.again)break;}return result;}finally{pm.style.width=original}")
 replace("    assert.equal(cuts.length,reference?.cuts.length??1,'同一双栏文档必须以实际栏宽与双栏容量分页')", `    if(reference)assert.equal(cuts.length,reference.cuts.length,'mixed必须使用真实逐块栏宽和源regions分页')
    assert.equal(mixedCanvas.gaps,cuts.length-1);assert.ok(Math.abs(mixedCanvas.height-(cuts.length*480+(cuts.length-1)*28))<=1);assert.ok(mixedCanvas.blocks.some(b=>b.width<200&&b.col));assert.ok(new Set(mixedCanvas.blocks.filter(b=>b.col).map(b=>Math.round(b.x))).size>=2)
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await page.locator('[data-tab-id="insert"]').click();await page.locator('[data-action="insert-page-number"]').click();await page.locator('[data-source-action="insert-page-number-footer-center"]').click()
    const saved=await save(2);assert.deepEqual(saved.body,sourceInspection.body);assert.equal(saved.sections[1].columns,2);assert.deepEqual(saved.sections.map(s=>[s.start,s.columns]),sourceInspection.sections.map(s=>[s.start,s.columns]));assert.equal(savePayloads.get(1).operations.length,1)
    assert.equal(savePayloads.get(1).operations.find(op=>op.kind==='setHeaderFooter').variant,cuts.length===1?'first':'default')
    assert.deepEqual(pageErrors,[]);console.log(JSON.stringify({ok:true,probe:'mixed-columns-layout-edge-save',builtPreview,pages:cuts.length,mixedCanvas,pageErrors}))`)
 if(process.env.DOCX_COLUMNS_NEXT==='1'){
  replace("document.sections[0]._sectPr.find(qn('w:cols')).set(qn('w:num'),'1')", "document.sections[0]._sectPr.find(qn('w:cols')).set(qn('w:num'),'2')")
  replace("last=document.add_section(WD_SECTION.CONTINUOUS)", "last=document.add_section(WD_SECTION.NEW_COLUMN)")
 }
 if(process.env.DOCX_COLUMNS_PAGES==='1')replace("range(24): document.add_paragraph", "range(64): document.add_paragraph")
}
if(process.env.DOCX_COLUMNS_CURSOR==='1'){
 replace("  } else if (smokeCase.startsWith('pagination-snapshot')) {", "  } else if (smokeCase.startsWith('pagination-snapshot')) {\n    await editor.evaluate(el=>el.editor.commands.setTextSelection(1))")
 replace("    document.save(payload['path'])",`    if payload.get('case') == 'pagination-snapshot-columns':
        from docx.shared import Inches
        for p in list(document.paragraphs): p._element.getparent().remove(p._element)
        document.sections[0]._sectPr.find(qn('w:cols')).set(qn('w:num'),'1')
        for i in range(5): document.add_paragraph('First section wrapping text. '*12)
        last=document.add_section(WD_SECTION.NEW_PAGE); last.page_width=Inches(7)
        for i in range(5): document.add_paragraph('Last section wrapping text. '*12)
    document.save(payload['path'])`)
 replace("    assert.equal(cuts.length,reference?.cuts.length??1,'同一双栏文档必须以实际栏宽与双栏容量分页')",`    await page.keyboard.press('Escape'); await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await editor.evaluate(el=>{el.editor.commands.setTextSelection(el.editor.state.doc.content.size-1);window.__previewDebug=null})
    await page.locator('[data-tab-id="view"]').click(); await page.locator('[data-action="pagination-preview"]').click()
    await page.waitForFunction(()=>window.__previewDebug?.slices?.length>0)
    const after=await page.evaluate(()=>window.__previewDebug.slices.map(({start,end,section,pageNo})=>({start,end,section,pageNo})))
    const before=cuts.map(({start,end,section,pageNo})=>({start,end,section,pageNo}))
    console.log(JSON.stringify({probe:'cursor-section-width',before,after,pageErrors}))
    assert.deepEqual(after,before,'同文档分页不得因正文光标移至末节改变')`)
}
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", "  if (builtPreview && smokeCase === 'pagination-snapshot-columns') {")
try{
 await writeFile(temporary,code)
 process.exitCode=await new Promise(resolve=>spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env,DOCX_INSERT_CASE:'pagination-snapshot-columns'}}).on('exit',resolve))??1
}finally{await unlink(temporary).catch(()=>{})}
