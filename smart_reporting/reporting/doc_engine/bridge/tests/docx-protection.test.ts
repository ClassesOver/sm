import assert from 'node:assert/strict'
import { test } from 'node:test'
import { inspectDocxProtection, validateDocxProtectionOperations, assertDocxProtectionWritten } from '../docx-protection.ts'
import { hashProtectionPassword } from '../../packages/docx-engine/src/protection.ts'
const settings = (tag = '') => `<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">${tag}</w:settings>`
const operation = (m: ReturnType<typeof inspectDocxProtection>, action: string, extra = {}) => ({kind:'setDocumentProtection',expectedSettingsSha256:m.expectedSettingsSha256,expectedProtectionSha256:m.expectedProtectionSha256,action,...extra})
test('source binding, exact schema, locked content and passwordless removal', async () => {
 const m=inspectDocxProtection(settings()); assert.equal(m.editable,true)
 assert.deepEqual(await validateDocxProtectionOperations([operation(m,'enable',{mode:'readOnly',password:''})],m),{protection:{edit:'readOnly',enforced:true}})
 await assert.rejects(validateDocxProtectionOperations([operation(m,'enable',{mode:'forms',password:'',expectedSettingsSha256:'stale'})],m),/anchor/)
 await assert.rejects(validateDocxProtectionOperations([operation(m,'disable',{password:'',bogus:true})],m),/invalid/)
 const locked=inspectDocxProtection(settings('<w:documentProtection w:edit="comments" w:enforcement="1"/>'))
 assert.equal(locked.contentLocked,true)
 assert.deepEqual(await validateDocxProtectionOperations([operation(locked,'disable',{password:''})],locked),{protection:null})
 assert.throws(()=>assertDocxProtectionWritten(settings(),{edit:'forms',enforced:true}),/not_applied/)
})
test('vendor password verification and fail closed XML',async()=>{
 const c=await hashProtectionPassword('secret',1)
 const m=inspectDocxProtection(settings(`<w:documentProtection w:edit="readOnly" w:enforcement="1" w:hash="${c.hash}" w:salt="${c.salt}" w:cryptSpinCount="1" w:cryptAlgorithmSid="14"/>`))
 await assert.rejects(validateDocxProtectionOperations([operation(m,'disable',{password:'wrong'})],m),/password/)
 assert.deepEqual(await validateDocxProtectionOperations([operation(m,'disable',{password:'secret'})],m),{protection:null})
 for(const xml of [settings('<x:documentProtection x:enforcement="1"/>'),settings('<w:documentProtection w:enforcement="1" w:edit="unknown"/>'),settings('<w:documentProtection/><w:documentProtection/>'),'<bad>']) {const m=inspectDocxProtection(xml);assert.equal(m.editable,false);assert.equal(m.contentLocked,true)}
})

test('all four restrictions save/read back and removal preserves every original non-settings ZIP part',async()=>{
 const {default:JSZip}=await import('jszip')
 const {buildDocx}=await import('../../packages/docx-engine/tests/helpers/build-docx.ts')
 const {parseDocx,saveDocx}=await import('../../packages/docx-engine/src/index.ts')
 let bytes=await buildDocx({bodyXml:'<w:p><w:r><w:t>保留正文</w:t></w:r></w:p>'})
 const z=await JSZip.loadAsync(bytes);z.file('word/settings.xml',settings('<w:zoom w:percent="85"/>'));z.file('customXml/protection-sentinel.xml','<retain exact="yes"/>');bytes=await z.generateAsync({type:'uint8array'})
 const baseline=await JSZip.loadAsync(bytes)
 for(const mode of ['readOnly','trackedChanges','comments','forms']){
  const source=await parseDocx(bytes),m=inspectDocxProtection(await baseline.file('word/settings.xml')!.async('string'))
  const options=await validateDocxProtectionOperations([operation(m,'enable',{mode,password:''})],m)
  const blocks=source.blocks.filter(b=>!b.hidden&&b.docxIndex!==null).map(b=>({kind:'original' as const,docxIndex:b.docxIndex!}))
  const saved=await saveDocx(source,blocks,options),zip=await JSZip.loadAsync(saved)
  const savedSettings=await zip.file('word/settings.xml')!.async('string')
  assertDocxProtectionWritten(savedSettings,options.protection!)
  assert.equal((await parseDocx(saved)).protection?.edit,mode)
  for(const name of Object.keys(baseline.files).filter(p=>!baseline.files[p]!.dir&&p!=='word/settings.xml'))assert.deepEqual(await zip.file(name)!.async('uint8array'),await baseline.file(name)!.async('uint8array'),name)
  const current=await parseDocx(saved),remove=await validateDocxProtectionOperations([operation(inspectDocxProtection(savedSettings),'disable',{password:''})],inspectDocxProtection(savedSettings))
  const unprotected=await saveDocx(current,blocks,remove)
  assertDocxProtectionWritten(await (await JSZip.loadAsync(unprotected)).file('word/settings.xml')!.async('string'),null)
 }
})
