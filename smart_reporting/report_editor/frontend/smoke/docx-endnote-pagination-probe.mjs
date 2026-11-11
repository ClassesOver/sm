// 尾注真实GUI探针：临时复用脚注夹具，使用源endnoteItems对照和实际保存。
// 不修改生产/static；可用NATIVE_GUI_PREVIEW=1验收最终构建。
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {spawn} from 'node:child_process'
const temporary=new URL(`./.endnote-probe-${process.pid}.mjs`,import.meta.url)
let code=await readFile(new URL('./docx-footnote-pagination-probe.mjs',import.meta.url),'utf8')
code=code.replaceAll('footnote','endnote').replaceAll('Footnote','Endnote')
const replace=(a,b)=>{assert.equal(code.split(a).length,2,`unique endnote anchor: ${a.slice(0,50)}`);code=code.replace(a,b)}
replace("canvasTop:section.marginTop/15,colMode:'none'}, ({live,blocks,flowH,factor})", "canvasTop:section.marginTop/15,colMode:'none',endnoteItems:[{...note,no:1,height,...metrics}]}, ({live,blocks,flowH,factor})")
replace("blockMetaOf:index=>indices.includes(index)?{endnoteExtraPx:height,endnoteBands:[{heightPx:height}]}:undefined", "blockMetaOf:undefined")
replace("    assert.equal(await page.locator('.pv-endnote').count(),1)", "    assert.equal(await page.locator('.pv-endnotes').count(),1)")
code=code.replaceAll("page.locator('.pv-endnote')", "page.locator('.pv-endnotes .pv-footnote')")
if(process.env.DOCX_ENDNOTE_EDGE_ONLY==='1'){
 replace("    if (facts) assert.deepEqual(cuts.map(({start,end,pageNo})=>({start,end,pageNo})),facts.reference.cuts,'当前Preview必须保留真实脚注占位与引用行归页')", "    console.log(JSON.stringify({edgeProbe:true,actualPages:cuts.length,expectedPages:facts.reference.cuts.length}))")
 replace("    assert.equal(cuts.length,2)", "")
 replace("    assert.equal(await page.locator('.pv-endnotes').count(),1)", "")

}
try{
 await writeFile(temporary,code)
 process.exitCode=await new Promise(resolve=>spawn(process.execPath,[temporary.pathname],{stdio:'inherit',env:{...process.env}}).on('exit',resolve))??1
}finally{await unlink(temporary).catch(()=>{})}
