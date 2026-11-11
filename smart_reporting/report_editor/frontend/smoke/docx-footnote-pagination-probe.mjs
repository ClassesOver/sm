// 隔离RED探针：复用既有真实GUI路由夹具，临时副本仅注入脚注fixture与观察分支。
// 不修改共享smoke或生产模块；源collector对照只用于诊断，不作为实现。
import assert from 'node:assert/strict'
import { readFile, writeFile, unlink } from 'node:fs/promises'
import { spawn } from 'node:child_process'
const source = new URL('./docx-insert-gui-smoke.mjs', import.meta.url)
const temporary = new URL(`./.footnote-probe-${process.pid}.mjs`, import.meta.url)
let code = await readFile(source, 'utf8')
const replace = (before, after) => { assert.equal(code.split(before).length, 2, `unique probe anchor: ${before.slice(0, 60)}`); code = code.replace(before, after) }
replace("    document.save(payload['path'])", `    if payload.get('case') == 'pagination-snapshot-footnote':
        from docx.shared import Inches, Pt
        for p in list(document.paragraphs): p._element.getparent().remove(p._element)
        sec = document.sections[0]; sec.page_height = Inches(5); sec.page_width = Inches(5)
        sec.top_margin = Inches(.5); sec.bottom_margin = Inches(.5); sec.left_margin = Inches(.5); sec.right_margin = Inches(.5)
        sec.different_first_page_header_footer = True
        for i in range(10):
            p = document.add_paragraph('Body line ' + str(i)); p.paragraph_format.space_after = Pt(6)
    document.save(payload['path'])
    if payload.get('case') == 'pagination-snapshot-footnote':
        original = Path(payload['path']).read_bytes(); block = inspect_docx(original)['blocks'][0]
        Path(payload['path']).write_bytes(patch_docx(original, [{'kind':'insertNote','blockId':block['blockId'],'expectedObjectSha256':block['expectedObjectSha256'],'noteKind':'footnote','offset':4,'text':'A long footnote with real wrapped lines and reserved space. ' * 8}]))`)
replace("    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, cuts, pageErrors }))", `    const facts = builtPreview ? null : await page.evaluate(async () => {
      const root = '/reports/v1/editor/assets/src/'
      const { parseDocxOffThread } = await import(root + 'vendor/genoffice-docs/apps/docs/src/renderer/parse-off-thread.ts')
      const { readSections, readSectionSettings } = await import('/reports/v1/editor/assets/@id/@genoffice/docx-engine')
      const { measureNoteHeightDom, noteRowMetrics } = await import(root + 'vendor/genoffice-docs/apps/docs/src/renderer/editor/note-dom.ts')
      const { resolveNoteStyle, noteRunStyle } = await import(root + 'vendor/genoffice-docs/apps/docs/src/renderer/line-metrics.ts')
      const { withMeasuredPaginationSnapshot, slicePaginationSnapshot } = await import(root + 'vendor/genoffice-docs/apps/docs/src/renderer/pagination-snapshot.ts')
      const parsed = await parseDocxOffThread(new Uint8Array(await (await fetch('/reports/v1/native/fixture-insert/1/api/file')).arrayBuffer()))
      const sections = readSections(parsed), section = readSectionSettings(parsed), pm = document.querySelector('.docx-canvas .tiptap')
      const note = parsed.footnotes[0]
      const metrics = noteRowMetrics({...resolveNoteStyle(parsed, note.styleId, note.spacing), ...noteRunStyle(note.richParas)}, section.docGrid)
      const height = measureNoteHeightDom({no:1,text:note.text,richParas:note.richParas}, 'footnote', (section.pageWidth-section.marginLeft-section.marginRight)/15, metrics.lineHeightPx, metrics.fontSizePt, metrics.fontFamily)
      const indices = parsed.blocks.filter(b => b.runs?.some(r => r.noteRef?.kind === 'footnote')).map(b => b.docxIndex)
      const reference = withMeasuredPaginationSnapshot({pm, section, sections, canvasTop:section.marginTop/15,colMode:'none'}, ({live,blocks,flowH,factor}) => {
        const result = slicePaginationSnapshot({section,sections,live,blocks,flowH,factor,colMode:'none',colFlow:null,hfParts:parsed.hfParts??{},hf:{header:null,footer:null,titlePg:false,evenOddHf:false},blockMetaOf:index=>indices.includes(index)?{footnoteExtraPx:height,footnoteBands:[{heightPx:height}]}:undefined})
        return {cuts:result.cuts.map(c=>({start:c.start,end:c.end,pageNo:c.pageNo})),bands:blocks.filter(b=>b.noteBands).map(b=>b.noteBands)}
      })
      return {noteTextLength:note.text.length,height,indices,reference}
    })
    console.log(JSON.stringify({probe:'footnote-reservation',actual:cuts,facts,pageErrors}))
    if (facts) assert.deepEqual(cuts.map(({start,end,pageNo})=>({start,end,pageNo})),facts.reference.cuts,'当前Preview必须保留真实脚注占位与引用行归页')
    assert.equal(cuts.length,2)
    assert.equal(await page.locator('.pv-footnote').count(),1)
    const closePreview = async () => { await page.keyboard.press('Escape'); await page.locator('.pv-overlay').waitFor({state:'hidden'}); await page.evaluate(()=>{window.__previewDebug=null}) }
    const showPreview = async () => { await page.locator('[data-tab-id="view"]').click(); await page.locator('[data-action="pagination-preview"]').click(); await page.waitForFunction(()=>window.__previewDebug?.slices?.length>0); return page.evaluate(()=>window.__previewDebug.slices.length) }
    const choose = async () => { await page.locator('[data-tab-id="references"]').click(); await page.getByLabel('已有脚注和尾注').selectOption(JSON.stringify(['footnote','1'])) }
    await closePreview()
    await page.locator('[data-tab-id="insert"]').click(); await page.locator('[data-action="insert-page-number"]').click()
    await page.locator('[data-source-action="insert-page-number-footer-center"]').click()
    await choose(); await page.locator('[data-note-action="edit"]').click()
    await page.getByLabel('注释内容').fill('Short changed footnote')
    await page.locator('.workbook-ribbon-note-dialog').getByRole('button',{name:'确定',exact:true}).click()
    assert.equal(await showPreview(),1)
    assert.ok((await page.locator('.pv-footnote').textContent()).includes('Short changed footnote'))
    assert.ok(!(await page.locator('.pv-footnote').textContent()).includes('A long footnote'))
    await closePreview(); await choose(); await page.locator('[data-note-action="delete"]').click()
    assert.equal(await showPreview(),1); assert.equal(await page.locator('.pv-footnote').count(),0)
    await closePreview()
    await page.locator('[data-tab-id="insert"]').click(); await page.locator('[data-action="insert-page-number"]').click()
    await page.locator('[data-source-action="insert-page-number-footer-center"]').click()
    const revision2=await save(2)
    assert.deepEqual(revision2.model.notes.footnotes,[])
    assert.deepEqual(savePayloads.get(1).operations.filter(op=>op.kind==='setHeaderFooter').map(op=>op.variant).sort(),['default','first'])
    assert.deepEqual(pageErrors,[])
    console.log(JSON.stringify({ok:true,probe:'footnote-live-edit-delete-and-edge-save',builtPreview,initialPages:cuts.length,changedPages:1,deletedPages:1,pageErrors}))`)
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", "  if (builtPreview && smokeCase === 'pagination-snapshot-footnote') {")
try {
  await writeFile(temporary, code)
  const exitCode = await new Promise(resolve => { const child = spawn(process.execPath, [temporary.pathname], {stdio:'inherit',env:{...process.env,DOCX_INSERT_CASE:'pagination-snapshot-footnote'}}); child.on('exit', resolve) })
  process.exitCode = exitCode ?? 1
} finally { await unlink(temporary).catch(()=>{}) }
