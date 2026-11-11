import assert from 'node:assert/strict'
import {test} from 'node:test'
import {mkdirSync,writeFileSync} from 'node:fs'
import {execFileSync} from 'node:child_process'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {inspectDocxCommentCreation,patchDocxCommentCreation} from '../docx-comment-create.ts'
const body='<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Alpha 😀 Beta</w:t></w:r><w:r><w:t> Gamma</w:t></w:r></w:p><w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>'
const operation=(model:any)=>({kind:'createComment' as const,sourceId:model.sourceId,clientId:'new-thread-1',author:'测试作者',date:'2026-11-11T01:02:03Z',text:'精确选区 & 新批注😀',ranges:[{targetId:model.targets[0].targetId,expectedParagraphSha256:model.targets[0].expectedParagraphSha256,from:6,to:13,text:'😀 Beta'}]})
test('new thread persists exact UTF16 selection and preserves opaque metadata',async()=>{
 const source=await buildDocx({bodyXml:body,extraParts:[{path:'word/people.xml',xml:'<x:people xmlns:x="urn:unknown"><x:keep id="90"/></x:people>',contentType:'application/xml'}]})
 const model=await inspectDocxCommentCreation(source);assert.equal(model.readOnlyReason,null);assert.equal(model.targets[0].text,'Alpha 😀 Beta Gamma')
 const saved=await patchDocxCommentCreation(source,[operation(model)]),reopened=await inspectDocxCommentCreation(saved)
 assert.equal(reopened.readOnlyReason,null);assert.notEqual(reopened.sourceId,model.sourceId)
 const a=await JSZip.loadAsync(source),b=await JSZip.loadAsync(saved);assert.equal(await b.file('word/people.xml')!.async('string'),await a.file('word/people.xml')!.async('string'))
 const dir='/tmp/word-comment-create-core-20261111';mkdirSync(dir,{recursive:true});writeFileSync(dir+'/source.docx',source);writeFileSync(dir+'/saved.docx',saved)
 const py=[
 'import sys,zipfile,json',
 'from lxml import etree as E',
 "W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';ns={'w':W}",
 'with zipfile.ZipFile(sys.argv[1]) as z:',
 ' for n in z.namelist():',
 "  if n.endswith(('.xml','.rels')):E.fromstring(z.read(n))",
 " d=E.fromstring(z.read('word/document.xml'));c=E.fromstring(z.read('word/comments.xml'))",
 " p=d.find('.//w:body/w:p',ns);active=False;selected=''",
 ' for n in p:',
 "  if n.tag=='{'+W+'}commentRangeStart':active=True",
 "  elif n.tag=='{'+W+'}commentRangeEnd':active=False",
 "  elif active:selected+=''.join(n.itertext())",
 " assert selected=='😀 Beta',repr(selected)",
 " new=c.find('w:comment',ns);assert new.get('{'+W+'}author')=='测试作者';assert new.get('{'+W+'}date')=='2026-11-11T01:02:03Z'",
 " assert ''.join(new.itertext())=='精确选区 & 新批注😀'",
 " print(json.dumps({'exactText':selected,'allXmlValid':True,'newId':new.get('{'+W+'}id')},ensure_ascii=False))",
 ].join('\n')
 writeFileSync(dir+'/zip-lxml.json',execFileSync('/home/junge/pros/smart_reporting/.venv/bin/python',['-c',py,dir+'/saved.docx'],{encoding:'utf8'}))
 await assert.rejects(patchDocxCommentCreation(saved,[operation(model)]));await assert.rejects(patchDocxCommentCreation(source,[{...operation(model),ranges:[{...operation(model).ranges[0],from:7}]}]))
})
test('cross paragraph range preserves boundaries and unsafe source rejects atomically',async()=>{
 const bytes=await buildDocx({bodyXml:body}),model=await inspectDocxCommentCreation(bytes),op=operation(model)
 op.ranges=[{targetId:model.targets[0].targetId,expectedParagraphSha256:model.targets[0].expectedParagraphSha256,from:13,to:19,text:' Gamma'},{targetId:model.targets[1].targetId,expectedParagraphSha256:model.targets[1].expectedParagraphSha256,from:0,to:6,text:'Second'}]
 assert.ok((await patchDocxCommentCreation(bytes,[op])).length)
 await assert.rejects(patchDocxCommentCreation(bytes,[op,{...op,clientId:'bad',sourceId:'f'.repeat(64)}]))
 const zip=await JSZip.loadAsync(bytes);zip.file('word/document.xml',(await zip.file('word/document.xml')!.async('string')).replace('<w:t>Second paragraph</w:t>','<w:fldChar w:fldCharType="begin"/><w:t>Second paragraph</w:t>'))
 const complex=await inspectDocxCommentCreation(await zip.generateAsync({type:'uint8array'}));assert.ok(complex.targets[1].readOnlyReason)
})
test('existing threads and unknown XML survive overlapping new anchors and modern thread metadata',async()=>{
 const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main',R='http://schemas.openxmlformats.org/officeDocument/2006/relationships',W15='http://schemas.microsoft.com/office/word/2012/wordml'
 const old='<w:comment w:id="0" w:author="Alice"><w:p><w:r><w:t>原批注</w:t></w:r></w:p></w:comment>'
 const anchored=body.replace('<w:p>','<w:p><w:commentRangeStart w:id="0"/>').replace(' Gamma</w:t></w:r></w:p>',' Gamma</w:t></w:r><w:commentRangeEnd w:id="0"/><w:r><w:commentReference w:id="0"/></w:r></w:p>')
 const source=await buildDocx({bodyXml:anchored,extraRels:'<Relationship Id="rId9" Type="'+R+'/comments" Target="comments.xml"/>',extraParts:[{path:'word/comments.xml',xml:'<w:comments xmlns:w="'+W+'">'+old+'</w:comments>',contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'},{path:'word/commentsExtended.xml',xml:'<w15:commentsEx xmlns:w15="'+W15+'"><w15:commentEx w15:paraId="00000001" w15:done="1"/><x:opaque xmlns:x="urn:opaque" keep="yes"/></w15:commentsEx>',contentType:'application/xml'},{path:'word/commentsIds.data',xml:'<x:ids xmlns:x="urn:opaque"><x:id x:id="1" x:paraId="00000002"/></x:ids>',contentType:'application/xml'}]})
 const model=await inspectDocxCommentCreation(source);assert.equal(model.readOnlyReason,null)
 const saved=await patchDocxCommentCreation(source,[operation(model)]),before=await JSZip.loadAsync(source),after=await JSZip.loadAsync(saved)
 const comments=await after.file('word/comments.xml')!.async('string');assert.ok(comments.includes(old));assert.match(comments,/w:id="2"/);assert.match(comments,/w14:paraId="00000003"/)
 const ex=await after.file('word/commentsExtended.xml')!.async('string');assert.ok(ex.includes('<x:opaque xmlns:x="urn:opaque" keep="yes"/>'));assert.ok(ex.includes('w15:done="1"'));assert.ok(ex.includes('w15:paraId="00000003" w15:done="0"'))
 assert.equal(await after.file('word/commentsIds.data')!.async('string'),await before.file('word/commentsIds.data')!.async('string'))
 for(const path of Object.keys(before.files))if(!before.files[path].dir&&!['word/document.xml','word/comments.xml','word/commentsExtended.xml'].includes(path))assert.deepEqual(await after.file(path)!.async('uint8array'),await before.file(path)!.async('uint8array'),path)
})
test('table cell paragraphs retain exact range identity without rewriting the table or adjacent cells',async()=>{
 const body='<w:tbl><w:tblPr><w:tblW w:w="4000" w:type="dxa"/></w:tblPr><w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="2000"/></w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/></w:tcPr><w:p><w:r><w:t>Cell Alpha Beta</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/></w:tcPr><w:p><w:r><w:t>Keep cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
 const bytes=await buildDocx({bodyXml:body}),model=await inspectDocxCommentCreation(bytes);assert.equal(model.readOnlyReason,null);assert.equal(model.targets[0].blockIndex,0);assert.equal(model.targets[1].paragraphOrdinal,1)
 const op=operation(model);op.ranges=[{targetId:model.targets[0].targetId,expectedParagraphSha256:model.targets[0].expectedParagraphSha256,from:5,to:10,text:'Alpha'}]
 const output=await patchDocxCommentCreation(bytes,[op]),zip=await JSZip.loadAsync(output),document=await zip.file('word/document.xml')!.async('string')
 assert.ok(document.includes('<w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/></w:tcPr><w:p><w:r><w:t>Keep cell</w:t></w:r></w:p></w:tc>'))
 assert.match(document,/<w:commentRangeStart w:id="0"\/>/)
})

test('ordinary empty paragraphs inside an exact range remain source-bound and byte-preserved',async()=>{
 const bytes=await buildDocx({bodyXml:body.replace('</w:p><w:p>','</w:p><w:p/><w:p>')}),model=await inspectDocxCommentCreation(bytes),op=operation(model)
 op.ranges=[{targetId:model.targets[0].targetId,expectedParagraphSha256:model.targets[0].expectedParagraphSha256,from:13,to:19,text:' Gamma'},{targetId:model.targets[1].targetId,expectedParagraphSha256:model.targets[1].expectedParagraphSha256,from:0,to:0,text:''},{targetId:model.targets[2].targetId,expectedParagraphSha256:model.targets[2].expectedParagraphSha256,from:0,to:6,text:'Second'}]
 const output=await patchDocxCommentCreation(bytes,[op]),zip=await JSZip.loadAsync(output);assert.ok((await zip.file('word/document.xml')!.async('string')).includes('<w:p/>'))
 await assert.rejects(patchDocxCommentCreation(bytes,[{...op,ranges:op.ranges.slice(1)}]))
})
