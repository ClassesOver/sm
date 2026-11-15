import assert from 'node:assert/strict'
import {test} from 'node:test'
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join,resolve} from 'node:path'
import {execFileSync} from 'node:child_process'
import JSZip from 'jszip'
import {parseDocx} from '../../packages/docx-engine/src/parse.ts'

test('blank Word bridge produces deterministic source template with a real empty paragraph',async()=>{
 const root=await mkdtemp(join(tmpdir(),'new-word-test-'))
 try{
  let first:Buffer|undefined
  for(const index of [0,1]){
   const output=join(root,`${index}.docx`),request=join(root,`${index}.json`)
   await writeFile(request,JSON.stringify({output}))
   const receipt=JSON.parse(execFileSync(resolve('node_modules/.bin/tsx'),[resolve('bridge/new-docx.ts'),request],{encoding:'utf8'}))
   const bytes=await readFile(output),parsed=await parseDocx(bytes),zip=await JSZip.loadAsync(bytes)
   assert.equal(receipt.ok,true);assert.equal(receipt.size,bytes.length)
   assert.equal(parsed.blocks.filter(block=>block.type==='paragraph').length,1)
   assert.match(await zip.file('word/document.xml')!.async('string'),/<w:p><\/w:p>/)
   assert.ok(zip.file('word/styles.xml'));assert.ok(zip.file('word/numbering.xml'))
   if(first)assert.deepEqual(bytes,first);first=bytes
  }
 }finally{await rm(root,{recursive:true,force:true})}
})
