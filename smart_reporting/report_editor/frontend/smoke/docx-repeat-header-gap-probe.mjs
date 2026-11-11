// 真实DOCX重复标题行验收：源前缀开关、Undo/Redo、草稿、Python保存与修订重开。
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {spawn} from 'node:child_process'
const temporary=new URL(`./.repeat-header-gap-${process.pid}.mjs`,import.meta.url)
let code=await readFile(new URL('./docx-insert-gui-smoke.mjs',import.meta.url),'utf8')
const replace=(a,b)=>{assert.equal(code.split(a).length,2,`unique repeat-header anchor ${a.slice(0,50)}`);code=code.replace(a,b)}
replace("    document.save(payload['path'])",`    if payload.get('case') == 'pagination-snapshot-repeat-header-gap':
        t=document.add_table(rows=3,cols=3);t.autofit=False
        t._tbl.tblPr.find(qn('w:tblW')).set(qn('w:type'),'dxa');t._tbl.tblPr.find(qn('w:tblW')).set(qn('w:w'),'9000')
        for g in t._tbl.tblGrid:g.set(qn('w:w'),'3000')
        for r,row in enumerate(t.rows):
            for c,cell in enumerate(row.cells):
                cell._tc.get_or_add_tcPr().find(qn('w:tcW')).set(qn('w:w'),'3000')
                cell.text='HEADER' + str(c) if r == 0 else 'R'+str(r)+'C'+str(c)
    document.save(payload['path'])`)
replace("    console.log(JSON.stringify({ ok: true, case: smokeCase, builtPreview, cuts, pageErrors }))",`    await page.keyboard.press('Escape');await page.locator('.pv-overlay').waitFor({state:'hidden'})
    await editor.locator('table').getByText('HEADER0',{exact:true}).click()
    await page.locator('[data-tab-id="tableLayout"]').click()
    const action=page.locator('[data-action="table-repeat-header-rows"]')
    const evidence={probe:'repeat-header-command-gap',builtPreview,sourceFixtureSha:sha256(sourceBytes),sourceTable:sourceInspection.model.blocks.filter(b=>b.type==='table'),actionCount:await action.count(),disabled:await action.isDisabled(),title:await action.getAttribute('title'),insertRowEnabled:await page.locator('[data-action="table-insert-row-after"]').isEnabled(),rows:await editor.locator('table tr').count(),pageErrors}
    console.log(JSON.stringify(evidence))
    assert.equal(evidence.insertRowEnabled,true,'夹具必须是现有可编辑矩形表')
    assert.deepEqual(pageErrors,[])
    assert.equal(evidence.disabled,false,'固定源支持首行重复标题切换，宿主必须接入真实命令')
    const flags=()=>editor.evaluate(pm=>{const table=pm.editor.state.doc.content.content.find(n=>n.type.name==='docTable');return table.content.content.map(row=>!!row.attrs.repeatHeader)})
    assert.equal(await action.getAttribute('aria-pressed'),'false')
    await action.click();assert.deepEqual(await flags(),[true,false,false]);assert.equal(await action.getAttribute('aria-pressed'),'true')
    await page.keyboard.press('Control+z');assert.deepEqual(await flags(),[false,false,false]);assert.equal(await action.getAttribute('aria-pressed'),'false')
    await page.keyboard.press('Control+Shift+z');assert.deepEqual(await flags(),[true,false,false]);assert.equal(await action.getAttribute('aria-pressed'),'true')
    await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.deepEqual(await flags(),[true,false,false])
    await save(2)
    assert.deepEqual(savePayloads.get(1).operations.map(op=>[op.kind,op.expectedRowCount,op.prefixRowCount,op.headers]),[['setTableRepeatHeaders',3,1,[true,false,false]]])
    const persisted=revision=>JSON.parse(runPython({mode:'header-inspect',bytes:Buffer.from(revisions.get(revision)).toString('base64')}))
    assert.deepEqual(persisted(2),[true,false,false])
    await page.waitForLoadState('networkidle');await open(2);assert.deepEqual(await flags(),[true,false,false])
    await editor.locator('table').getByText('HEADER0',{exact:true}).click();await page.locator('[data-tab-id="tableLayout"]').click();assert.equal(await action.getAttribute('aria-pressed'),'true');await action.click();assert.equal(await action.getAttribute('aria-pressed'),'false')
    await save(3);assert.deepEqual(persisted(3),[false,false,false])
    await page.waitForLoadState('networkidle');await open(3);assert.deepEqual(await flags(),[false,false,false]);await page.waitForLoadState('networkidle')
    assert.deepEqual(pageErrors,[])
    console.log(JSON.stringify({ok:true,probe:'repeat-header-real-save-reopen',builtPreview,savedFlags:[persisted(2),persisted(3)],pageErrors}))`)
replace("if payload['mode'] == 'create':",`if payload['mode'] == 'header-inspect':
    d=Document(BytesIO(base64.b64decode(payload['bytes'])))
    print(json.dumps([r._tr.trPr is not None and r._tr.trPr.find(qn('w:tblHeader')) is not None for r in d.tables[0].rows]));sys.exit(0)
if payload['mode'] == 'create':`)
replace("  if (builtPreview && smokeCase.startsWith('hf-insert')) {", "  if (builtPreview && smokeCase === 'pagination-snapshot-repeat-header-gap') {")
try{await writeFile(temporary,code);process.exitCode=await new Promise(resolve=>spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env,DOCX_INSERT_CASE:'pagination-snapshot-repeat-header-gap'}}).on('exit',resolve))??1}finally{await unlink(temporary).catch(()=>{})}
