import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {inspectDocxBookmarks,patchDocxBookmarks} from '../docx-bookmarks.ts'
const plain='<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Alpha 😀 Beta</w:t></w:r><w:r><w:t> Gamma</w:t></w:r></w:p><w:p/><w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>'
const range=(m:any,index:number,from:number,to:number)=>{const t=m.targets[index];return{targetId:t.targetId,expectedParagraphSha256:t.expectedParagraphSha256,from,to,text:t.text.slice(from,to)}}
const create=(m:any)=>({kind:'createBookmark' as const,sourceId:m.sourceId,name:'精确Bookmark',ranges:[range(m,0,6,13)]})
async function document(b:Uint8Array){return(await JSZip.loadAsync(b)).file('word/document.xml')!.async('string')}
test('creates exact UTF16 bookmark, preserves all other parts and deletes only markers after reopen',async()=>{
 const bytes=await buildDocx({bodyXml:plain,extraParts:[{path:'word/opaque.xml',xml:'<keep xmlns="urn:unknown">unchanged</keep>',contentType:'application/xml'}]}),m=await inspectDocxBookmarks(bytes)
 assert.equal(m.readOnlyReason,null);assert.equal(m.targets[0].text,'Alpha 😀 Beta Gamma')
 const saved=await patchDocxBookmarks(bytes,[create(m)]),next=await inspectDocxBookmarks(saved)
 assert.equal(next.bookmarks[0].name,'精确Bookmark');assert.equal(next.bookmarks[0].readOnlyReason,null);assert.equal(next.bookmarks[0].ranges[0].text,'😀 Beta')
 assert.match(await document(saved),/<w:rPr><w:b\/><\/w:rPr>/)
 const before=await JSZip.loadAsync(bytes),after=await JSZip.loadAsync(saved)
 assert.deepEqual(Object.keys(after.files).sort(),Object.keys(before.files).sort())
 for(const f of Object.values(before.files))if(!f.dir&&f.name!=='word/document.xml')assert.deepEqual(await after.file(f.name)!.async('uint8array'),await f.async('uint8array'),f.name)
 const removed=await patchDocxBookmarks(saved,[{kind:'deleteBookmark',sourceId:next.sourceId!,bookmarkId:next.bookmarks[0].bookmarkId}]);assert.equal((await inspectDocxBookmarks(removed)).bookmarks.length,0)
 assert.equal((await inspectDocxBookmarks(removed)).targets[0].text,m.targets[0].text)
 await assert.rejects(patchDocxBookmarks(saved,[create(m)]),/source|identity/)
 await assert.rejects(patchDocxBookmarks(bytes,[{...create(m),ranges:[range(m,0,7,13)]}]),/range/)
})
test('cross paragraph ranges include an ordinary empty paragraph and keep unknown paragraph XML',async()=>{
 const bytes=await buildDocx({bodyXml:plain}),m=await inspectDocxBookmarks(bytes),op={...create(m),ranges:[range(m,0,13,19),range(m,1,0,0),range(m,2,0,6)]}
 const saved=await patchDocxBookmarks(bytes,[op]),next=await inspectDocxBookmarks(saved)
 assert.deepEqual(next.bookmarks[0].ranges.map(r=>r.text),[' Gamma','','Second']);assert.ok((await document(saved)).includes('<w:p/>'))
 await assert.rejects(patchDocxBookmarks(bytes,[{...op,ranges:[op.ranges[0],op.ranges[2]]}]),/continuity/)
})
test('ordinary existing nested bookmark markers remain editable and byte preserved around a new range',async()=>{
 const existing=plain.replace('<w:r><w:rPr>','<w:bookmarkStart w:id="7" w:name="Existing"/><w:r><w:rPr>').replace(' Gamma</w:t></w:r>',' Gamma</w:t></w:r><w:bookmarkEnd w:id="7"/>')
 const bytes=await buildDocx({bodyXml:existing}),m=await inspectDocxBookmarks(bytes)
 assert.equal(m.bookmarks[0].readOnlyReason,null)
 const saved=await patchDocxBookmarks(bytes,[create(m)]),raw=await document(saved)
 assert.ok(raw.includes('<w:bookmarkStart w:id="7" w:name="Existing"/>'));assert.ok(raw.includes('<w:bookmarkEnd w:id="7"/>'))
 assert.equal((await inspectDocxBookmarks(saved)).bookmarks.length,2)
 await assert.rejects(patchDocxBookmarks(bytes,[{...create(m),name:'Existing'}]),/name/)
})
test('complex bookmarks stay listed and readonly without closing unrelated ordinary paragraphs',async()=>{
 const complex='<w:p><w:bookmarkStart w:id="4" w:name="Complex"/><w:hyperlink w:anchor="Elsewhere"><w:r><w:t>link</w:t></w:r></w:hyperlink><w:bookmarkEnd w:id="4"/></w:p>'
 const bytes=await buildDocx({bodyXml:plain+complex}),m=await inspectDocxBookmarks(bytes)
 assert.equal(m.readOnlyReason,null);assert.ok(m.bookmarks[0].readOnlyReason);assert.ok(m.targets.at(-1)!.readOnlyReason)
 assert.ok((await patchDocxBookmarks(bytes,[create(m)])).length)
 await assert.rejects(patchDocxBookmarks(bytes,[{kind:'deleteBookmark',sourceId:m.sourceId!,bookmarkId:m.bookmarks[0].bookmarkId}]),/readonly/)
})
test('duplicate names, duplicate normalized ids, orphan markers and protected documents reject atomically',async()=>{
 for(const marks of [
 '<w:bookmarkStart w:id="1" w:name="A"/><w:bookmarkEnd w:id="1"/><w:bookmarkStart w:id="2" w:name="A"/><w:bookmarkEnd w:id="2"/>',
 '<w:bookmarkStart w:id="1" w:name="A"/><w:bookmarkEnd w:id="1"/><w:bookmarkStart w:id="01" w:name="B"/><w:bookmarkEnd w:id="01"/>',
 '<w:bookmarkStart w:id="1" w:name="Orphan"/>',
 ]){const bytes=await buildDocx({bodyXml:plain.replace('<w:p>','<w:p>'+marks)}),m=await inspectDocxBookmarks(bytes);assert.ok(m.readOnlyReason);assert.ok(m.bookmarks.length);await assert.rejects(patchDocxBookmarks(bytes,[create(m)]))}
 const bytes=await buildDocx({bodyXml:plain,extraRels:'<Relationship Id="rSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>',extraParts:[{path:'word/settings.xml',xml:'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:documentProtection w:edit="readOnly" w:enforcement="1"/></w:settings>',contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml'}]}),m=await inspectDocxBookmarks(bytes);assert.ok(m.readOnlyReason);await assert.rejects(patchDocxBookmarks(bytes,[create(m)]))
})
test('batch identities, names, overlapping operation ids and field ranges are checked before mutation',async()=>{
 const bytes=await buildDocx({bodyXml:plain}),m=await inspectDocxBookmarks(bytes)
 for(const op of [{...create(m),name:'a b'},{...create(m),name:'A'.repeat(41)},{...create(m),extra:true},{...create(m),ranges:[{...range(m,0,6,13),text:'forged'}]},{...create(m),ranges:[range(m,0,6,6)]}])await assert.rejects(patchDocxBookmarks(bytes,[op] as any))
 await assert.rejects(patchDocxBookmarks(bytes,[create(m),create(m)]),/name/)
 const fields=await buildDocx({bodyXml:'<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:t>Cache</w:t></w:r></w:p>'}),fm=await inspectDocxBookmarks(fields);assert.ok(fm.targets[0].readOnlyReason)
 await assert.rejects(patchDocxBookmarks(fields,[{...create(m),sourceId:fm.sourceId!,ranges:[range(fm,0,0,5)]}]))
})
test('hidden property markers cannot escape id accounting and default-namespace protection remains readonly',async()=>{
 const hidden=await buildDocx({bodyXml:plain.replace('<w:p>','<w:p><w:pPr><w:bookmarkStart w:id="9" w:name="Hidden"/></w:pPr>')}),hm=await inspectDocxBookmarks(hidden)
 assert.ok(hm.readOnlyReason,'未在普通正文中核验的隐藏端点必须关闭写入')
 const bytes=await buildDocx({bodyXml:plain,extraRels:'<Relationship Id="rSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>',extraParts:[{path:'word/settings.xml',xml:'<settings xmlns="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:q="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><documentProtection q:enforcement="true"/></settings>',contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml'}]}),m=await inspectDocxBookmarks(bytes)
 assert.ok(m.readOnlyReason,'默认namespace的保护声明仍然有效')
})
