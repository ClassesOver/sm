// 中文原字体真实加载/分页/字体选择保存，临时夹具与实际Python ZIP回读。
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {spawn} from 'node:child_process'
const pickedFont=process.env.CJK_PICK_FONT??'Noto Sans CJK SC'
assert.ok(['Noto Sans CJK SC','LXGW WenKai','Ma Shan Zheng','ZCOOL XiaoWei'].includes(pickedFont))
const temporary=new URL(`./.cjk-font-probe-${process.pid}.mjs`,import.meta.url)
let code=await readFile(new URL('./docx-insert-gui-smoke.mjs',import.meta.url),'utf8')
const replace=(a,b)=>{assert.equal(code.split(a).length,2,`unique CJK anchor ${a.slice(0,50)}`);code=code.replace(a,b)}
replace("    document.save(payload['path'])",`    if payload.get('case') == 'pagination-snapshot-cjk-font':
        from docx.shared import Inches
        for p in list(document.paragraphs): p._element.getparent().remove(p._element)
        sec=document.sections[0];sec.page_width=Inches(5);sec.page_height=Inches(5)
        sec.left_margin=Inches(.5);sec.right_margin=Inches(.5);sec.top_margin=Inches(.5);sec.bottom_margin=Inches(.5)
        for i in range(12):
            p=document.add_paragraph()
            r=p.add_run(('中文字体测试，报告数据展示；宋黑风格与中英文混排ABC123。')*4)
            r.font.name='Noto Serif CJK SC';r._r.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Noto Serif CJK SC')
    document.save(payload['path'])`)
replace("    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, cuts, pageErrors }))",`    const fonts=await page.evaluate(async()=>{
      const families=['Noto Sans CJK SC','Noto Serif CJK SC','Noto Sans CJK GO','Noto Serif CJK GO','LXGW WenKai','Ma Shan Zheng','ZCOOL XiaoWei']
      const faces=[]
      for(const family of families){const loaded=await document.fonts.load('16px "'+family+'"','中文报告');faces.push({family,count:loaded.length,status:loaded.map(f=>f.status)})}
      await document.fonts.ready
      const pm=document.querySelector('.docx-canvas .tiptap')
      return {faces,body:[...pm.querySelectorAll('p[data-idx]')].slice(0,2).map(el=>({font:getComputedStyle(el).fontFamily,text:el.textContent,width:el.getBoundingClientRect().width})),natural:pm.classList.contains('measuring-natural')}
    })
    assert.ok(fonts.faces.every(f=>f.count>0&&f.status.every(s=>s==='loaded')),'四个source CJK family必须真实加载')
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await page.evaluate(()=>window.__previewDebug=null)
    await page.locator('[data-action="pagination-preview"]').click();await page.waitForFunction(()=>window.__previewDebug?.slices?.length>0)
    const again=await page.evaluate(()=>window.__previewDebug.slices.map(({start,end,section,pageNo})=>({start,end,section,pageNo})))
    assert.equal(again.length,cuts.length);again.forEach((c,i)=>{assert.ok(Math.abs(c.start-cuts[i].start)<1e-6);assert.ok(Math.abs(c.end-cuts[i].end)<1e-6)})
    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await editor.evaluate(el=>el.editor.commands.setTextSelection({from:1,to:5}))
    await page.locator('[data-tab-id="home"]').click()
    const input=page.locator('[data-action="font-family"]');await input.fill('${pickedFont}');await input.press('Enter')
    const selectedFont=await editor.evaluate(pm=>{const editor=pm.editor,{from,to}=editor.state.selection,segments=[];editor.state.doc.nodesBetween(from,to,(node,pos)=>{if(!node.isText)return;const dom=editor.view.domAtPos(Math.min(Math.max(pos,from)+1,Math.min(to,pos+node.nodeSize)));let el=dom.node.nodeType===Node.TEXT_NODE?dom.node.parentElement:dom.node;if(el?.nodeType!==Node.ELEMENT_NODE)return;segments.push({text:node.text?.slice(Math.max(from-pos,0),Math.min(to-pos,node.nodeSize)),font:getComputedStyle(el).fontFamily,eastAsia:getComputedStyle(el).getPropertyValue('--doc-east-asian-font'),marks:node.marks.map(m=>({type:m.type.name,attrs:m.attrs}))})});return {from,to,segments,font:segments.map(s=>s.font).join('|'),html:pm.querySelector('p').innerHTML}})
    console.log(JSON.stringify({probe:'cjk-selected-font-before-save',selectedFont}))
    assert.ok(selectedFont.segments.length>0&&selectedFont.segments.every(s=>s.font.includes('${pickedFont}')),'已有东亚槽时选择字体必须即时更新选中文字computed font chain')
    const saved=await save(2)
    const fontOperations=savePayloads.get(1).operations
    assert.ok(fontOperations.length>0)
    const xml=runPython({mode:'font-inspect',bytes:Buffer.from(revisions.get(2)).toString('base64')})
    assert.ok(xml.includes('w:eastAsia="${pickedFont}"'),'字体选择必须实际写入OOXML东亚槽')
    assert.ok(xml.includes('w:ascii="Noto Serif CJK SC"'),'中文选字应保留原Latin槽，不能误改英文')
    await page.waitForLoadState('networkidle')
    await open(2)
    const reopenedFont=await page.locator('.docx-canvas .tiptap').evaluate(pm=>{const dom=pm.editor.view.domAtPos(2),el=dom.node.nodeType===Node.TEXT_NODE?dom.node.parentElement:dom.node;return {text:el.textContent,font:getComputedStyle(el).fontFamily,eastAsia:getComputedStyle(el).getPropertyValue('--doc-east-asian-font')}})
    assert.ok(reopenedFont.text.startsWith('中文字体')&&reopenedFont.font.includes('${pickedFont}'),'保存重开后实际中文字字体必须保持Sans')
    console.log(JSON.stringify({probe:'cjk-saved-reopened-font',reopenedFont}))
    await page.waitForLoadState('networkidle')
    assert.deepEqual(pageErrors,[])
    console.log(JSON.stringify({ok:true,probe:'source-cjk-font-load-pagination-save',builtPreview,pages:cuts.length,fonts,selectedFont,fontOperations,eastAsiaSaved:true,pageErrors}))`)
replace("if payload['mode'] == 'create':",`if payload['mode'] == 'font-inspect':
    print(ZipFile(BytesIO(base64.b64decode(payload['bytes']))).read('word/document.xml').decode());sys.exit(0)
if payload['mode'] == 'create':`)

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
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", `  if(builtPreview){await Promise.all(fontChecks);for(const name of ['NotoSansCJKsc-Regular-subset.woff2', 'NotoSerifCJKsc-Regular-subset.woff2','LXGWWenKai-Regular-subset.woff2','MaShanZheng-Regular-subset.woff2','ZCOOLXiaoWei-Regular-subset.woff2'])assert.ok(loadedFonts.has(name),'必须实际加载字体'+name);console.log(JSON.stringify({fontIdentityVerified:true,loadedFonts:Object.fromEntries(loadedFonts)}))}
  if (builtPreview && smokeCase.startsWith('hf-insert')) {`)
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", "  if (builtPreview && smokeCase === 'pagination-snapshot-cjk-font') {")
try{
 await writeFile(temporary,code)
 process.exitCode=await new Promise(resolve=>spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env,DOCX_INSERT_CASE:'pagination-snapshot-cjk-font'}}).on('exit',resolve))??1
}finally{await unlink(temporary).catch(()=>{})}
