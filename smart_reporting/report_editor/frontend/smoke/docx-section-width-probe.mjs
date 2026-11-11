// 单栏跨节宽度/镜像边距只读RED；仅临时GUI夹具，无生产/static写入。
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {spawn} from 'node:child_process'
const temporary=new URL(`./.section-width-probe-${process.pid}.mjs`,import.meta.url)
let code=await readFile(new URL('./docx-insert-gui-smoke.mjs',import.meta.url),'utf8')
const replace=(a,b)=>{assert.equal(code.split(a).length,2,`unique anchor ${a.slice(0,50)}`);code=code.replace(a,b)}
replace("    document.save(payload['path'])",`    if payload.get('case') == 'pagination-snapshot-section-width':
        from docx.shared import Inches
        from docx.oxml import OxmlElement
        for p in list(document.paragraphs): p._element.getparent().remove(p._element)
        first=document.sections[0]; first.page_width=Inches(5); first.page_height=Inches(5)
        first.left_margin=Inches(.5); first.right_margin=Inches(.5); first.top_margin=Inches(.5); first.bottom_margin=Inches(.5)
        document.add_paragraph('First section body')
        last=document.add_section(WD_SECTION.NEW_PAGE); last.page_width=Inches(7); last.left_margin=Inches(1)
        for i in range(4):document.add_paragraph('Last section long wrapping text. '*10)
    document.save(payload['path'])`)
replace("    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, cuts, pageErrors }))",`    const geometry=await page.evaluate(async built=>{
      if(built){const pm=document.querySelector('.docx-canvas .tiptap');return {actual:[...pm.querySelectorAll('p[data-idx]')].map(el=>({text:el.textContent,width:el.getBoundingClientRect().width,x:el.getBoundingClientRect().left})),expected:[{text:'Last section',width:528}],canvasX:pm.getBoundingClientRect().left,canvasWidth:pm.getBoundingClientRect().width,paperWidth:672}}
      const root='/reports/v1/editor/assets/src/vendor/genoffice-docs/apps/docs/src/renderer/'
      const {parseDocxOffThread}=await import(root+'parse-off-thread.ts')
      const {readSections,readSectionSettings}=await import('/reports/v1/editor/assets/@id/@genoffice/docx-engine')
      const {sectionWidthSpecs,paperWidthPx,mirrorMarginSpecs}=await import(root+'pagination-sections.ts')
      const {withMeasuredPaginationSnapshot,slicePaginationSnapshot}=await import(root+'pagination-snapshot.ts')
      const parsed=await parseDocxOffThread(new Uint8Array(await(await fetch('/reports/v1/native/fixture-insert/1/api/file')).arrayBuffer()))
      const sections=readSections(parsed),section=sections[0].settings,pm=document.querySelector('.docx-canvas .tiptap')
      const actual=[...pm.querySelectorAll('p[data-idx]')].map(el=>({text:el.textContent,width:el.getBoundingClientRect().width,x:el.getBoundingClientRect().left}))
      const expected=withMeasuredPaginationSnapshot({pm,sections,section,canvasTop:section.marginTop/15,colMode:'none'},m=>{
        const snap=slicePaginationSnapshot({...m,sections,section,colMode:'none',colFlow:null,hfParts:{},hf:{header:null,footer:null,titlePg:false,evenOddHf:false}})
        return sectionWidthSpecs(m.blocks,m.live,snap.geoms,paperWidthPx(sections)).map(s=>({text:s.el.textContent,width:s.widthPx,dx:s.dx,pageDx:s.pageDx}))
      })
      return {actual,expected,canvasX:pm.getBoundingClientRect().left,canvasWidth:pm.getBoundingClientRect().width,paperWidth:paperWidthPx(sections)}
    },builtPreview)
    console.log(JSON.stringify({probe:'single-column-section-width',geometry,cuts,pageErrors}))
    const last=geometry.actual.find(x=>x.text.startsWith('Last section')),expected=geometry.expected.find(x=>x.text.startsWith('Last section'))
    assert.ok(Math.abs(last.width-expected.width)<1,'单栏后节正文必须使用source sectionWidthSpecs自己的内容宽度')
    assert.equal(geometry.canvasWidth,672);assert.ok(Math.abs(geometry.actual[0].x-geometry.canvasX-144)<1);assert.ok(Math.abs(last.x-geometry.canvasX-96)<1)
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await editor.evaluate(el=>el.editor.commands.setTextSelection(el.editor.state.doc.content.size-1))
    await page.locator('[data-tab-id="insert"]').click();await page.locator('[data-action="insert-page-number"]').click();await page.locator('[data-source-action="insert-page-number-footer-center"]').click()
    const saved=await save(2);assert.deepEqual(saved.body,sourceInspection.body);assert.deepEqual(saved.sections,sourceInspection.sections)
    assert.equal(savePayloads.get(1).operations.length,1);assert.equal(savePayloads.get(1).operations[0].sectionId,sourceInspection.model.sections.at(-1).sectionId)
    assert.deepEqual(pageErrors,[]);console.log(JSON.stringify({ok:true,probe:'single-column-width-body-edge-save',builtPreview,pages:cuts.length,pageErrors}))`)
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", "  if (builtPreview && smokeCase === 'pagination-snapshot-section-width') {")
try{
 await writeFile(temporary,code)
 process.exitCode=await new Promise(resolve=>spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env,DOCX_INSERT_CASE:'pagination-snapshot-section-width'}}).on('exit',resolve))??1
}finally{await unlink(temporary).catch(()=>{})}
