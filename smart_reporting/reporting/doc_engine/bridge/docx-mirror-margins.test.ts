import { test } from 'node:test'
import assert from 'node:assert/strict'
import JSZip from 'jszip'
import { inspectDocxProtection } from './docx-protection'
import { validateDocxMirrorMarginsOperations } from './docx-mirror-margins'
import { parseDocx, saveDocx, readSectionSettings } from '../packages/docx-engine/src/index'
import { buildDocx } from '../packages/docx-engine/tests/helpers/build-docx'
const xml=(inner:string)=>`<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">${inner}</w:settings>`
const settings=xml('<w:zoom w:percent="120"/><w:trackRevisions/><w:defaultTabStop w:val="720"/>')
const model=inspectDocxProtection(settings)
const op=(enabled=true)=>({kind:'setMirrorMargins',expectedSettingsSha256:model.expectedSettingsSha256,enabled})
test('strict mirror op validates boolean or absent and rejects stale, unknown, duplicate input',()=>{
 assert.equal(validateDocxMirrorMarginsOperations([],model),undefined)
 assert.equal(validateDocxMirrorMarginsOperations([op()],model),true)
 assert.equal(validateDocxMirrorMarginsOperations([op(false)],model),false)
 for(const bad of [[{...op(),unexpected:1}],[{...op(),enabled:'true'}],[{...op(),kind:'unknown'}],[{...op(),expectedSettingsSha256:'b'.repeat(64)}],[op(),op()]]) assert.throws(()=>validateDocxMirrorMarginsOperations(bad,model))
})
test('unsupported namespace and enforced protection remain readonly',()=>{
 for(const source of [xml('<w:documentProtection w:edit="readOnly" w:enforcement="1"/>'),'<w:settings xmlns:w="urn:unsupported"/>']){
  const locked=inspectDocxProtection(source)
  assert.throws(()=>validateDocxMirrorMarginsOperations([{...op(),expectedSettingsSha256:locked.expectedSettingsSha256}],locked))
 }
})
test('actual source mirror save preserves sibling settings and unrelated parts',async()=>{
 const bytes=await buildDocx({bodyXml:'<w:p><w:r><w:t>unchanged</w:t></w:r></w:p>',extraParts:[
  {path:'word/settings.xml',xml:settings,contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml'},
  {path:'customXml/item1.xml',xml:'<keep value="exact"/>',contentType:'application/xml'},
 ]})
 let parsed=await parseDocx(bytes)
 const before=await JSZip.loadAsync(bytes)
 for(const enabled of [true,false]){
  const sourceZip=await JSZip.loadAsync(parsed.internal.originalBytes)
  const sourceSettings=await sourceZip.file('word/settings.xml')!.async('string')
  const sourceModel=inspectDocxProtection(sourceSettings)
  const mirrorMargins=validateDocxMirrorMarginsOperations([{...op(enabled),expectedSettingsSha256:sourceModel.expectedSettingsSha256}],sourceModel)
  const result=await saveDocx(parsed,[{kind:'original',docxIndex:0}],{mirrorMargins})
  const zip=await JSZip.loadAsync(result), output=await zip.file('word/settings.xml')!.async('string')
  assert.equal(output.includes('<w:mirrorMargins/>'),enabled)
  for(const sibling of ['<w:zoom w:percent="120"/>','<w:trackRevisions/>','<w:defaultTabStop w:val="720"/>'])assert.ok(output.includes(sibling))
  for(const [name,entry] of Object.entries(before.files))if(!entry.dir&&!['word/settings.xml','docProps/core.xml'].includes(name))assert.equal(await zip.file(name)!.async('string'),await entry.async('string'),name)
  parsed=await parseDocx(result); assert.equal(!!parsed.mirrorMargins,enabled)
 }
})

test('source engine co-saves four section margins with the global mirrored flag',async()=>{
 const bytes=await buildDocx({bodyXml:'<w:p><w:r><w:t>body</w:t></w:r></w:p>',extraParts:[{path:'word/settings.xml',xml:settings,contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml'}]})
 const parsed=await parseDocx(bytes)
 const section={...readSectionSettings(parsed),marginTop:1440,marginRight:1800,marginBottom:1440,marginLeft:2160}
 const mirrorMargins=validateDocxMirrorMarginsOperations([op()],model)
 const result=await parseDocx(await saveDocx(parsed,[{kind:'original',docxIndex:0}],{mirrorMargins,section}))
 assert.equal(result.mirrorMargins,true)
 const actual=readSectionSettings(result)
 for(const key of ['marginTop','marginRight','marginBottom','marginLeft'] as const)assert.equal(actual[key],section[key])
 assert.equal(result.blocks[0]!.originalXml,parsed.blocks[0]!.originalXml)
})
