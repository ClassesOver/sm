import assert from 'node:assert/strict'
import test from 'node:test'
import {createHash} from 'node:crypto'
import {mkdtemp,rm,writeFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join,resolve} from 'node:path'
import {spawnSync} from 'node:child_process'
import {PDFDocument,StandardFonts} from 'pdf-lib'

const hash=(value:Uint8Array)=>createHash('sha256').update(value).digest('hex')
const module=await import('./protection').catch(()=>({protectPdf:undefined}))
const permissions={printing:true,modifying:false,annotating:true,copying:false}
async function fixture(){const doc=await PDFDocument.create();const font=await doc.embedFont(StandardFonts.Helvetica);doc.addPage([300,400]).drawText('Protection source text',{x:25,y:300,font,size:12});return doc.save()}
test('password protection creates AES256 bytes with independently readable passwords and permission bits',async()=>{
 assert.equal(typeof module.protectPdf,'function','missing protection bridge')
 const source=await fixture(),original=hash(source)
 const result=await module.protectPdf!(source,{sourceSha256:original,userPassword:'reader-secret',ownerPassword:'owner-secret',permissions})
 assert.equal(result.sourceSha256,original);assert.equal(result.sha256,hash(result.bytes));assert.equal(result.size,result.bytes.length);assert.deepEqual(result.reviewIssues,[])
 assert.equal(hash(source),original);assert.notEqual(result.sha256,original)
 const directory=await mkdtemp(join(tmpdir(),'pdf-protection-'))
 try{
  await writeFile(join(directory,'protected.pdf'),result.bytes)
  const script=['import sys,json','from pypdf import PdfReader','p=sys.argv[1]','r=PdfReader(p);assert r.is_encrypted','assert r.decrypt("wrong-secret")==0','assert r.decrypt("reader-secret")==1','assert "Protection source text" in r.pages[0].extract_text()','assert list(r.pages[0].mediabox)==[0,0,300,400]','e=r.trailer["/Encrypt"];assert e["/R"]==6 and e["/Length"]==256','perms=int(e["/P"]);assert perms&4 and not perms&8 and perms&32 and not perms&16','o=PdfReader(p);assert o.decrypt("owner-secret")==2','print(json.dumps({"ok":True,"revision":6,"keyBits":256,"permissions":perms}))'].join(String.fromCharCode(10))
  const checked=spawnSync(resolve('../../../.venv/bin/python'),['-c',script,join(directory,'protected.pdf')],{encoding:'utf8'})
  assert.equal(checked.status,0,checked.stderr);assert.equal(JSON.parse(checked.stdout).ok,true)
 }finally{await rm(directory,{recursive:true,force:true})}
})
test('password protection refuses invalid credentials, forged sources and protected forms before producing bytes',async()=>{
 assert.equal(typeof module.protectPdf,'function')
 const source=await fixture(),input={sourceSha256:hash(source),userPassword:'reader-secret',ownerPassword:'owner-secret',permissions}
 for(const change of [{sourceSha256:'0'.repeat(64)},{userPassword:''},{ownerPassword:''},{userPassword:'密'.repeat(43)},{permissions:{printing:true}},{unexpected:'secret'}])await assert.rejects(()=>module.protectPdf!(source,{...input,...change}))
 const form=await PDFDocument.load(source);form.getForm().createTextField('keep').addToPage(form.getPage(0));const formBytes=await form.save()
 await assert.rejects(()=>module.protectPdf!(formBytes,{...input,sourceSha256:hash(formBytes)}))
 const encrypted=await module.protectPdf!(source,input)
 await assert.rejects(()=>module.protectPdf!(encrypted.bytes,{...input,sourceSha256:hash(encrypted.bytes)}))
})
