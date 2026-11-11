// 独立只读调查：不等宽长段跨栏，复用真实GUI/Python及固定源收敛算法；不改生产/static。
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {spawn} from 'node:child_process'
const sourceFixture=process.env.DOCX_UNEQUAL_FIXTURE
const temporary=new URL(`./.unequal-natural-${process.pid}.mjs`,import.meta.url)
let code=await readFile(new URL('./docx-insert-gui-smoke.mjs',import.meta.url),'utf8')
const replace=(a,b)=>{assert.equal(code.split(a).length,2,`unique anchor: ${a.slice(0,50)}`);code=code.replace(a,b)}
 if(sourceFixture)replace("  const sourceBytes = Buffer.from(runPython({ mode: 'create', path: sourcePath, case: smokeCase }), 'base64')", `  const sourceBytes = await readFile(${JSON.stringify(sourceFixture)})
  console.log(JSON.stringify({probe:'same-input-sha',sha256:sha256(sourceBytes)}))`)
replace("    document.save(payload['path'])",`    if payload.get('case') == 'pagination-snapshot-columns':
        from docx.shared import Inches
        from docx.oxml import OxmlElement
        for p in list(document.paragraphs): p._element.getparent().remove(p._element)
        last=document.sections[0];last.page_width=Inches(5);last.page_height=Inches(5)
        last.left_margin=Inches(.5);last.right_margin=Inches(.5);last.top_margin=Inches(.5);last.bottom_margin=Inches(.5)
        last.different_first_page_header_footer=True
        cols=last._sectPr.find(qn('w:cols'));cols.set(qn('w:num'),'2');cols.set(qn('w:equalWidth'),'0')
        for w in [1800,3600]:
            c=OxmlElement('w:col');c.set(qn('w:w'),str(w));c.set(qn('w:space'),'360');cols.append(c)
        for i in range(3): document.add_paragraph(('Long paragraph '+str(i)+' across unequal columns. ')*12)
    document.save(payload['path'])`)


replace("    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, cuts, pageErrors }))",`    const source=await page.evaluate(async built=>{
      if(built){const pm=document.querySelector('.docx-canvas .tiptap');return {geom:{equalWidth:false,widths:[120,240]},body:[...pm.querySelectorAll('p[data-idx]')].map(el=>({css:{font:getComputedStyle(el).font,fontFamily:getComputedStyle(el).fontFamily,fontSize:getComputedStyle(el).fontSize,zoom:el.closest('.doc-zoom')?.style.zoom,lineHeight:getComputedStyle(el).lineHeight,margin:getComputedStyle(el).margin,padding:getComputedStyle(el).padding},width:el.getBoundingClientRect().width,split:!!el.querySelector('.doc-col-split-float'),splitStyles:[...el.querySelectorAll('.doc-col-split-float')].map(s=>s.style.cssText)})),specs:[],sourceCompared:false,cuts:window.__previewDebug.slices.map(({start,end,section,pageNo})=>({start,end,section,pageNo}))}}
      const root='/reports/v1/editor/assets/src/vendor/genoffice-docs/apps/docs/src/renderer/'
      const {parseDocxOffThread}=await import(root+'parse-off-thread.ts')
      const {readSections}=await import('/reports/v1/editor/assets/@id/@genoffice/docx-engine')
      const {sectionColGeom,columnLayoutSpecs}=await import(root+'pagination-sections.ts')
      const {withMeasuredPaginationSnapshot,slicePaginationSnapshot}=await import(root+'pagination-snapshot.ts')
      const parsed=await parseDocxOffThread(new Uint8Array(await(await fetch('/reports/v1/native/fixture-insert/1/api/file')).arrayBuffer()))
      const sections=readSections(parsed),section=sections[0].settings,pm=document.querySelector('.docx-canvas .tiptap')
      const body=[...pm.querySelectorAll('p[data-idx]')].map(el=>({css:{font:getComputedStyle(el).font,fontFamily:getComputedStyle(el).fontFamily,fontSize:getComputedStyle(el).fontSize,zoom:el.closest('.doc-zoom')?.style.zoom,lineHeight:getComputedStyle(el).lineHeight,margin:getComputedStyle(el).margin,padding:getComputedStyle(el).padding},width:el.getBoundingClientRect().width,x:el.getBoundingClientRect().left,y:el.getBoundingClientRect().top,split:!!el.querySelector('.doc-col-split-float'),splitStyles:[...el.querySelectorAll('.doc-col-split-float')].map(s=>s.style.cssText)}))
      return withMeasuredPaginationSnapshot({pm,section,sections,canvasTop:section.marginTop/15,colMode:'mixed'},m=>{
        const snap=slicePaginationSnapshot({...m,section,sections,colMode:'mixed',colFlow:null,hfParts:{},hf:{header:null,footer:null,titlePg:true,evenOddHf:false}})
        return {parsedStyles:Object.values(parsed.styles).filter(s=>s.id==='Normal'),docDefaults:parsed.docDefaults,geom:sectionColGeom(sections[0]),body,specs:columnLayoutSpecs(m.blocks,snap.cuts,m.live).map(s=>({width:s.widthPx,split:s.split})),cuts:snap.cuts.map(({start,end,section,pageNo})=>({start,end,section,pageNo}))}
      })
    },builtPreview)
    if(${!!sourceFixture})assert.ok(source.body.every(b=>Math.abs(parseFloat(b.css.margin.split(' ')[2])-13.3333)<.01),'同SHA来源Normal的10pt段后距必须覆盖8pt静态回退')
    const natural=await page.evaluate(async()=>{
      const root='/reports/v1/editor/assets/src/vendor/genoffice-docs/apps/docs/src/renderer/'
      const {parseDocxOffThread}=await import(root+'parse-off-thread.ts');const {readSections}=await import('/reports/v1/editor/assets/@id/@genoffice/docx-engine')
      const {withMeasuredPaginationSnapshot,slicePaginationSnapshot}=await import(root+'pagination-snapshot.ts');const {columnLayoutSpecs}=await import(root+'pagination-sections.ts')
      const parsed=await parseDocxOffThread(new Uint8Array(await(await fetch('/reports/v1/native/fixture-insert/1/api/file')).arrayBuffer())),sections=readSections(parsed),section=sections[0].settings,pm=document.querySelector('.docx-canvas .tiptap')
      pm.classList.add('measuring-natural')
      try{return withMeasuredPaginationSnapshot({pm,section,sections,canvasTop:section.marginTop/15,colMode:'mixed'},m=>{const snap=slicePaginationSnapshot({...m,section,sections,colMode:'mixed',colFlow:null,hfParts:{},hf:{header:null,footer:null,titlePg:true,evenOddHf:false}});return {flow:m.flowH,cuts:snap.cuts.map(({start,end,section,pageNo})=>({start,end,section,pageNo})),specs:columnLayoutSpecs(m.blocks,snap.cuts,m.live).map(s=>({width:s.widthPx,dx:s.dx,dy:s.dy,split:s.split}))}})}finally{pm.classList.remove('measuring-natural')}
    })
    console.log(JSON.stringify({probe:'natural-readonly-before-layout-commit',normal:source.cuts,natural,pageErrors}))
    assert.deepEqual(natural.cuts,source.cuts,'旧gap不应改变同DOM自然测量的flow/cuts')
    const before=cuts.map(({start,end,section,pageNo})=>({start,end,section,pageNo}))
    assert.deepEqual(source.geom.widths,[120,240]);assert.equal(source.geom.equalWidth,false)
    if(!builtPreview)assert.ok(source.specs.some(s=>s.split),'夹具必须触发source columnLineSplits')
    assert.ok(source.body.some(s=>s.split),'正文必须实际装载source split float')
    if(!builtPreview)assert.deepEqual(source.cuts,before,'只读同DOM源分页必须与Preview一致')
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await page.evaluate(()=>window.__previewDebug=null)
    await page.locator('[data-action="pagination-preview"]').click();await page.waitForFunction(()=>window.__previewDebug?.slices?.length>0)
    const after=await page.evaluate(()=>window.__previewDebug.slices.map(({start,end,section,pageNo})=>({start,end,section,pageNo})))
    console.log(JSON.stringify({probe:'unequal-readonly-repeated-preview',before,after,source,notice:await page.locator('.docx-notice').allTextContents(),pageErrors}))
    if(${process.env.DOCX_UNEQUAL_EDGE_ONLY!=='1'})assert.deepEqual(after,before,'未编辑不等宽长段文档重复Preview必须保持分页稳定')
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await page.locator('[data-tab-id="insert"]').click();await page.locator('[data-action="insert-page-number"]').click();await page.locator('[data-source-action="insert-page-number-footer-center"]').click()
    const saved=await save(2);assert.deepEqual(saved.body,sourceInspection.body);assert.deepEqual(saved.sections,sourceInspection.sections)
    assert.equal(savePayloads.get(1).operations.length,1);assert.equal(savePayloads.get(1).operations[0].sectionId,sourceInspection.model.sections[0].sectionId);assert.equal(savePayloads.get(1).operations[0].variant,'default');assert.deepEqual(pageErrors,[])
    if(${process.env.DOCX_UNEQUAL_EDIT==='1'}){
      await open(2)
      const current=page.locator('.docx-canvas .tiptap')
      await current.evaluate(el=>el.editor.commands.insertContentAt(2,'changed '))
      const edited=[]
      for(let n=0;n<2;n++){
        await page.locator('[data-tab-id="view"]').click();await page.locator('[data-action="pagination-preview"]').click()
        await page.waitForFunction(()=>window.__previewDebug?.slices?.length>0)
        edited.push(await page.evaluate(()=>window.__previewDebug.slices.map(({start,end,section,pageNo})=>({start,end,section,pageNo}))))
        await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'});await page.evaluate(()=>window.__previewDebug=null)
      }
      assert.deepEqual(edited[1],edited[0],'真实编辑后重排仍须稳定')
      console.log(JSON.stringify({probe:'unequal-real-edit-repeated-preview',edited,pageErrors}))
    }
    console.log(JSON.stringify({ok:true,probe:'unequal-edge-save',operations:savePayloads.get(1).operations,bodyAndSectionsPreserved:true,stabilityAccepted:${process.env.DOCX_UNEQUAL_EDGE_ONLY!=='1'},pageErrors}))`)
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", "  if (builtPreview && smokeCase === 'pagination-snapshot-columns') {")
try{
 await writeFile(temporary,code)
 process.exitCode=await new Promise(resolve=>spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env,DOCX_INSERT_CASE:'pagination-snapshot-columns'}}).on('exit',resolve))??1
}finally{await unlink(temporary).catch(()=>{})}
