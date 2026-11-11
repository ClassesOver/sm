// @vitest-environment node
import {expect,it} from 'vitest'
import {readFileSync} from 'node:fs'

it('PDF form controls leave the main PDF chunk without changing its budget',()=>{
 const source=readFileSync(new URL('../vite.config.ts',import.meta.url),'utf8')
 const line=source.split('\n').find(line=>line.includes("return 'native-pdf-form-controls'"))
 expect(line).toBeDefined()
 const chunks=new Function('id',line!)
 for(const name of ['pdf-form-create','pdf-form-design','pdf-form-radio-extension','pdf-form-text-properties']){
  expect(chunks('/workspace/frontend/src/'+name+'.ts')).toBe('native-pdf-form-controls')
 }
 expect(chunks('/workspace/frontend/src/pdf-main.ts')).toBeUndefined()
})
