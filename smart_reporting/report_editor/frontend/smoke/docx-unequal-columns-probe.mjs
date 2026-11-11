// 独立只读调查：不等宽长段跨栏，复用真实GUI/Python及固定源收敛算法；不改生产/static。
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {spawn} from 'node:child_process'
const sourceFixture=process.env.DOCX_UNEQUAL_FIXTURE
const temporary=new URL(`./.unequal-probe-${process.pid}.mjs`,import.meta.url)
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


replace("    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, cuts, pageErrors }))",`    const caladeaStyles=await page.evaluate(async()=>{const faces=[];for(const style of ['normal 14px Caladea','bold 14px Caladea','italic 14px Caladea','bold italic 14px Caladea'])faces.push({style,count:(await document.fonts.load(style)).length});return faces})
    assert.ok(caladeaStyles.every(face=>face.count>0),'源四款Caladea必须可实际加载')
    const source=await page.evaluate(async built=>{
      if(built){const pm=document.querySelector('.docx-canvas .tiptap');return {fontEvidence:{faces:[...document.fonts].map(f=>({family:f.family,status:f.status})),measure:['Caladea'].map(face=>{const c=document.createElement('canvas').getContext('2d');c.font='14.6667px '+face;return {face,width:c.measureText('Long paragraph 0 across unequal columns.').width}})},geom:{equalWidth:false,widths:[120,240]},body:[...pm.querySelectorAll('p[data-idx]')].map(el=>({css:{font:getComputedStyle(el).font,fontFamily:getComputedStyle(el).fontFamily,fontSize:getComputedStyle(el).fontSize,zoom:el.closest('.doc-zoom')?.style.zoom,lineHeight:getComputedStyle(el).lineHeight,margin:getComputedStyle(el).margin,padding:getComputedStyle(el).padding},width:el.getBoundingClientRect().width,split:!!el.querySelector('.doc-col-split-float'),splitStyles:[...el.querySelectorAll('.doc-col-split-float')].map(s=>s.style.cssText)})),specs:[],sourceCompared:false,cuts:window.__previewDebug.slices.map(({start,end,section,pageNo})=>({start,end,section,pageNo}))}}
      const root='/reports/v1/editor/assets/src/vendor/genoffice-docs/apps/docs/src/renderer/'
      const {parseDocxOffThread}=await import(root+'parse-off-thread.ts')
      const {readSections}=await import('/reports/v1/editor/assets/@id/@genoffice/docx-engine')
      const {sectionColGeom,columnLayoutSpecs}=await import(root+'pagination-sections.ts')
      const {probeColWrap}=await import(root+'pagination-lines.ts');const {withMeasuredPaginationSnapshot,slicePaginationSnapshot}=await import(root+'pagination-snapshot.ts')
      const parsed=await parseDocxOffThread(new Uint8Array(await(await fetch('/reports/v1/native/fixture-insert/1/api/file')).arrayBuffer()))
      const sections=readSections(parsed),section=sections[0].settings,pm=document.querySelector('.docx-canvas .tiptap')
      const body=[...pm.querySelectorAll('p[data-idx]')].map(el=>({css:{font:getComputedStyle(el).font,fontFamily:getComputedStyle(el).fontFamily,fontSize:getComputedStyle(el).fontSize,zoom:el.closest('.doc-zoom')?.style.zoom,lineHeight:getComputedStyle(el).lineHeight,margin:getComputedStyle(el).margin,padding:getComputedStyle(el).padding},width:el.getBoundingClientRect().width,x:el.getBoundingClientRect().left,y:el.getBoundingClientRect().top,split:!!el.querySelector('.doc-col-split-float'),splitStyles:[...el.querySelectorAll('.doc-col-split-float')].map(s=>s.style.cssText)}))
      return withMeasuredPaginationSnapshot({pm,section,sections,canvasTop:section.marginTop/15,colMode:'mixed'},m=>{
        const snap=slicePaginationSnapshot({...m,section,sections,colMode:'mixed',colFlow:null,hfParts:{},hf:{header:null,footer:null,titlePg:true,evenOddHf:false}})
        return {fontEvidence:{faces:[...document.fonts].map(f=>({family:f.family,status:f.status})),measure:['Caladea','Times New Roman','serif'].map(face=>{const c=document.createElement('canvas').getContext('2d');c.font='14.6667px '+face;return {face,width:c.measureText('Long paragraph 0 across unequal columns.').width}})},wrapProbe:[...pm.querySelectorAll('p[data-idx]')].map(el=>probeColWrap(el,120,240,1)),pmHtml:pm.innerHTML,blocks:m.blocks.map(b=>({top:b.top,height:b.height,docxIndex:b.docxIndex,nLines:b.lineBoxes?.length})),canvas:{rect:pm.getBoundingClientRect().toJSON(),border:getComputedStyle(pm).border,padding:getComputedStyle(pm).padding,line:getComputedStyle(pm).lineHeight,first:pm.querySelector('p')?.getBoundingClientRect().toJSON()},parsedStyles:Object.values(parsed.styles).filter(s=>s.id==='Normal'),docDefaults:parsed.docDefaults,geom:sectionColGeom(sections[0]),body,specs:columnLayoutSpecs(m.blocks,snap.cuts,m.live).map(s=>({width:s.widthPx,split:s.split})),cuts:snap.cuts.map(({start,end,section,pageNo})=>({start,end,section,pageNo}))}
      })
    },builtPreview)
    if(${!!sourceFixture})assert.ok(source.body.every(b=>Math.abs(parseFloat(b.css.margin.split(' ')[2])-13.3333)<.01),'同SHA来源Normal的10pt段后距必须覆盖8pt静态回退')
    const before=cuts.map(({start,end,section,pageNo})=>({start,end,section,pageNo}))
    if(${!!sourceFixture}){const caladea=source.fontEvidence;assert.ok(caladea.faces.some(f=>f.family==='Caladea'&&f.status==='loaded'),'Caladea真实字体必须已加载');assert.ok(Math.abs(caladea.measure.find(m=>m.face==='Caladea').width-273)<.01,'同源glyph宽度必须匹配');if(!builtPreview)assert.ok(source.wrapProbe.every(table=>table.n===36),'源不等宽probe必须为36行')}
    assert.deepEqual(source.geom.widths,[120,240]);assert.equal(source.geom.equalWidth,false)
    if(!builtPreview)assert.ok(source.specs.some(s=>s.split),'夹具必须触发source columnLineSplits')
    assert.ok(source.body.some(s=>s.split),'正文必须实际装载source split float')
    const sameCuts=(a,b,message)=>{assert.equal(a.length,b.length,message);a.forEach((cut,i)=>Object.entries(cut).forEach(([key,value])=>typeof value==='number'?assert.ok(Math.abs(value-b[i][key])<1e-6,message):assert.deepEqual(value,b[i][key],message)))}
    if(!builtPreview)sameCuts(source.cuts,before,'只读同DOM源分页必须与Preview一致')
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await page.evaluate(()=>window.__previewDebug=null)
    await page.locator('[data-action="pagination-preview"]').click();await page.waitForFunction(()=>window.__previewDebug?.slices?.length>0)
    const after=await page.evaluate(()=>window.__previewDebug.slices.map(({start,end,section,pageNo})=>({start,end,section,pageNo})))
    console.log(JSON.stringify({probe:'unequal-readonly-repeated-preview',before,after,source,notice:await page.locator('.docx-notice').allTextContents(),pageErrors}))
    if(${process.env.DOCX_UNEQUAL_EDGE_ONLY!=='1'})sameCuts(after,before,'未编辑不等宽长段文档重复Preview必须保持分页稳定')
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await page.waitForFunction(()=>{const pm=document.querySelector('.docx-canvas .tiptap');return pm&&!pm.classList.contains('measuring-natural')&&pm.querySelectorAll('.page-gap').length>0})
    console.log(JSON.stringify({probe:'natural-body-restored-after-preview',state:await editor.evaluate(pm=>({natural:pm.classList.contains('measuring-natural'),gaps:pm.querySelectorAll('.page-gap').length,height:pm.style.height}))}))
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
      sameCuts(edited[1],edited[0],'真实编辑后重排仍须稳定')
      console.log(JSON.stringify({probe:'unequal-real-edit-repeated-preview',edited,pageErrors}))
    }
    console.log(JSON.stringify({ok:true,probe:'unequal-edge-save',operations:savePayloads.get(1).operations,bodyAndSectionsPreserved:true,stabilityAccepted:${process.env.DOCX_UNEQUAL_EDGE_ONLY!=='1'},pageErrors}))`)

replace("  const pageErrors = []", `  const pageErrors = []
  const fontChecks=[],loadedFonts=new Map()
  const fontSources=[]
  for(const family of ['docx-caladea','docx-cjk']){
    const folder=join(frontend,'src/assets',family),provenance=JSON.parse(await readFile(join(folder,'provenance.json'),'utf8'))
    for(const [file,entry] of Object.entries(provenance.files))if(/\\.(ttf|woff2)$/.test(file))fontSources.push({file,sha256:entry.sha256,bytes:await readFile(join(folder,file))})
  }
  page.on('response',response=>{
    const path=new URL(response.url()).pathname
    if(!path.startsWith('/reports/v1/editor/assets/assets/')||!/\\.(ttf|woff2)$/.test(path))return
    fontChecks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body(),hash=sha256(bytes),source=fontSources.find(item=>item.sha256===hash);assert.ok(source,'实际字体响应必须匹配已登记原文件SHA');assert.equal(sha256(source.bytes),hash);loadedFonts.set(source.file,{url:path,status:response.status(),sha256:hash})})())
  })`)
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", `  if(builtPreview){await Promise.all(fontChecks);for(const name of ['Caladea-Regular.ttf', 'Caladea-Bold.ttf', 'Caladea-Italic.ttf', 'Caladea-BoldItalic.ttf'])assert.ok(loadedFonts.has(name),'必须实际加载字体'+name);console.log(JSON.stringify({fontIdentityVerified:true,loadedFonts:Object.fromEntries(loadedFonts)}))}
  if (builtPreview && smokeCase.startsWith('hf-insert')) {`)
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", "  if (builtPreview && smokeCase === 'pagination-snapshot-columns') {")
try{
 await writeFile(temporary,code)
 process.exitCode=await new Promise(resolve=>spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env,DOCX_INSERT_CASE:'pagination-snapshot-columns'}}).on('exit',resolve))??1
}finally{await unlink(temporary).catch(()=>{})}
