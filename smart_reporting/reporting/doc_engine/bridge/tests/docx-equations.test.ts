import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {inspectDocxEquations,patchDocxEquations} from '../docx-equations.ts'
import {parseDocx} from '../../packages/docx-engine/src/parse.ts'
const p='<w:p w:rsidR="ABCDEF01"><w:pPr><w:keepNext/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>A😀B</w:t></w:r></w:p>'
test('source-bound equations insert inline/display, update/delete and preserve all other ZIP parts',async()=>{
 const source=await buildDocx({bodyXml:p+'<w:tbl><w:tr><w:tc>'+p+'</w:tc></w:tr></w:tbl>',headerXml:p})
 const model=await inspectDocxEquations(source);assert.equal(model.targets.length,2)
 const steps=[{targetId:model.targets[0].targetId,action:'insert',offset:3,display:false,latex:'\\frac{x}{2}'},{targetId:model.targets[1].targetId,action:'insert',offset:0,display:true,latex:'x^2'}]
 const output=await patchDocxEquations(source,{kind:'editEquations',sourceId:model.sourceId,steps})
 const a=await JSZip.loadAsync(source),b=await JSZip.loadAsync(output),xml=await b.file('word/document.xml')!.async('string')
 assert.match(xml,/<m:f>/);assert.match(xml,/<m:oMathPara>/);assert.match(xml,/w:rsidR="ABCDEF01"/);assert.match(xml,/<w:keepNext\/>/)
 for(const file of Object.values(a.files))if(!file.dir&&file.name!=='word/document.xml')assert.deepEqual(await b.file(file.name)!.async('uint8array'),await file.async('uint8array'))
 const reopened=await inspectDocxEquations(output),target=reopened.targets.find(t=>t.formulas.length&&t.text.startsWith('A'))!,formula=target.formulas[0]
 const updated=await patchDocxEquations(output,{kind:'editEquations',sourceId:reopened.sourceId,steps:[{targetId:target.targetId,action:'update',formulaId:formula.formulaId,latex:'\\sqrt{y}'}]})
 assert.match(await (await JSZip.loadAsync(updated)).file('word/document.xml')!.async('string'),/<m:rad>/)
 const m=await inspectDocxEquations(updated),t=m.targets.find(t=>t.formulas.some(f=>f.latex?.includes('sqrt')))!
 const deleted=await patchDocxEquations(updated,{kind:'editEquations',sourceId:m.sourceId,steps:[{targetId:t.targetId,action:'delete',formulaId:t.formulas[0].formulaId}]})
 assert.equal((await inspectDocxEquations(deleted)).targets.find(t=>t.text==='A😀B')?.formulas.length,0)
})
test('reject stale source, forged fields, surrogate offsets and unsupported LaTeX',async()=>{
 const source=await buildDocx({bodyXml:p}),model=await inspectDocxEquations(source),step={targetId:model.targets[0].targetId,action:'insert',offset:1,display:false,latex:'x^2'}
 for(const extra of [{sourceId:'0'.repeat(64)},{genXml:'<w:p/>'},{steps:[{...step,offset:2}]},{steps:[{...step,omml:'<m:r/>'}]},{steps:[{...step,latex:'\\unsupported{x}'}]}])await assert.rejects(patchDocxEquations(source,{kind:'editEquations',sourceId:model.sourceId,steps:[step],...extra}),/equation/)
})
test('display math splits body at its offset and preserves unlocked SDT shells and following block identities',async()=>{
 const shell='<w:sdt><w:sdtPr><w:tag w:val="retain"/></w:sdtPr><w:sdtContent>'+p+p+'</w:sdtContent></w:sdt>'
 const source=await buildDocx({bodyXml:shell+p}),m=await inspectDocxEquations(source)
 assert.deepEqual(m.targets.map(t=>t.blockIndex),[0,1,2]);assert.ok(m.targets.every(t=>!t.readOnlyReason))
 const output=await patchDocxEquations(source,{kind:'editEquations',sourceId:m.sourceId,steps:[{targetId:m.targets[0].targetId,action:'insert',offset:3,display:true,latex:'x^2'}]})
 const xml=await (await JSZip.loadAsync(output)).file('word/document.xml')!.async('string'),parsed=await parseDocx(output)
 assert.match(xml,/<w:tag w:val="retain"\/>/);assert.equal((xml.match(/<w:sdt>/g)??[]).length,1);assert.equal(parsed.blocks.filter(b=>b.formulaDisplay).length,1)
 assert.equal(parsed.blocks[0].runs?.map(r=>r.text).join(''),'A😀');assert.equal(parsed.blocks[2].runs?.map(r=>r.text).join(''),'B');assert.equal(parsed.blocks[3].runs?.map(r=>r.text).join(''),'A😀B')
})
test('display math in an SDT-wrapped table stays in its original cell paragraph',async()=>{
 const source=await buildDocx({bodyXml:'<w:sdt><w:sdtPr><w:tag w:val="table"/></w:sdtPr><w:sdtContent><w:tbl><w:tr><w:tc>'+p+'</w:tc></w:tr></w:tbl></w:sdtContent></w:sdt>'+p}),model=await inspectDocxEquations(source)
 assert.equal(model.targets[0].container,'table');assert.ok(!model.targets[0].readOnlyReason)
 const output=await patchDocxEquations(source,{kind:'editEquations',sourceId:model.sourceId,steps:[{targetId:model.targets[0].targetId,action:'insert',offset:3,display:true,latex:'\\sqrt{x}'}]})
 const xml=await (await JSZip.loadAsync(output)).file('word/document.xml')!.async('string'),cell=xml.match(/<w:tc>([\s\S]*?)<\/w:tc>/)![1]
 assert.equal((cell.match(/<w:p(?:\s|>)/g)??[]).length,1);assert.match(cell,/<m:oMathPara>/);assert.equal((await inspectDocxEquations(output)).targets[0].formulas[0].display,true)
})
test('accepts repeated equivalent namespace declarations but rejects namespace shadowing',async()=>{
 const original=await buildDocx({bodyXml:p}),zip=await JSZip.loadAsync(original),xml=await zip.file('word/document.xml')!.async('string')
 const namespace='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
 zip.file('word/document.xml',xml.replace('<w:p ', '<w:p xmlns:w="'+namespace+'" '));const repeated=await zip.generateAsync({type:'uint8array'})
 const model=await inspectDocxEquations(repeated);assert.equal(model.targets.length,1);assert.ok(!model.targets[0].readOnlyReason)
 zip.file('word/document.xml',xml.replace('<w:p ', '<w:p xmlns:w="urn:foreign" '));await assert.rejects(inspectDocxEquations(await zip.generateAsync({type:'uint8array'})),/namespace/)
})
