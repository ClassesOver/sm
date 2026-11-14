import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

export async function observePdfBuiltAssets(page) {
  const root=process.env.PDF_STATIC_ROOT?resolve(process.env.PDF_STATIC_ROOT):fileURLToPath(new URL('../../static/',import.meta.url)),sha=bytes=>createHash('sha256').update(bytes).digest('hex')
  const manifestSha256=sha(await readFile(resolve(root,'.vite/manifest.json'))),reads=[],errors=[],files=new Map()
  if(process.env.PDF_EXPECTED_MANIFEST_SHA256)assert.equal(manifestSha256,process.env.PDF_EXPECTED_MANIFEST_SHA256)
  page.on('response',response=>{
    const path=new URL(response.url()).pathname,prefix='/reports/v1/editor/assets/'
    if(response.ok()&&path.startsWith(prefix)&&path.endsWith('.js'))reads.push((async()=>{
      const relative=path.slice(prefix.length);assert.ok(!relative.split('/').includes('..'))
      const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(resolve(root,relative))))
      files.set(path,{path,size:bytes.length,sha256:sha(bytes)})
    })().catch(error=>errors.push(String(error))))
  })
  return async()=>{
    await Promise.all(reads);assert.deepEqual(errors,[]);assert.ok(files.size>0)
    assert.equal(sha(await readFile(resolve(root,'.vite/manifest.json'))),manifestSha256)
    return {manifestSha256,runtimeJavaScript:[...files.values()]}
  }
}

export async function inspectPdfObjectDialog(page,{opener,title,operations,directory}) {
  if(!process.env.PDF_OBJECT_DIALOG_VIEWPORTS)return []
  const originalViewport=page.viewportSize(),before=await operations(),results=[]
  if(directory)await mkdir(directory,{recursive:true})
  for(const viewport of process.env.PDF_OBJECT_DIALOG_VIEWPORTS.split(',')){
    const [width,height]=viewport.split('x').map(Number);await page.setViewportSize({width,height})
    await opener.click()
    const dialog=page.getByRole('dialog',{name:title,exact:true}),close=dialog.getByRole('button',{name:'关闭'+title,exact:true})
    assert.equal(await dialog.getByRole('heading').textContent(),title)
    const initial=dialog.locator('input,textarea').first()
    assert.ok(await initial.evaluate(node=>document.activeElement===node))
    await initial.fill(await initial.evaluate(node=>node.tagName==='TEXTAREA')?'尚未提交的便签正文':'12')
    const last=dialog.locator('form button').last();await last.focus();await last.scrollIntoViewIfNeeded()
    const geometry=await dialog.evaluate(node=>{
      const r=node.getBoundingClientRect(),heading=node.querySelector('header').getBoundingClientRect()
      return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,overflow:node.scrollWidth>node.clientWidth+1,heading:{y:heading.y,bottom:heading.bottom},controls:[...node.querySelectorAll('header button,form button')].map(control=>{const c=control.getBoundingClientRect();return {y:c.y,bottom:c.bottom,accessible:control.contains(document.elementFromPoint(c.x+c.width/2,c.y+c.height/2))}})}
    })
    assert.ok(geometry.x>=0&&geometry.y>=0&&geometry.right<=width+1&&geometry.bottom<=height+1&&!geometry.overflow,JSON.stringify(geometry))
    assert.ok(geometry.heading.y>=geometry.y&&geometry.heading.bottom<=geometry.bottom&&geometry.controls.every(c=>c.y>=geometry.y&&c.bottom<=geometry.bottom&&c.accessible),JSON.stringify(geometry))
    if(width>=1000)assert.equal(geometry.width,560)
    await page.keyboard.press('Tab');assert.ok(await close.evaluate(node=>document.activeElement===node))
    await page.keyboard.press('Shift+Tab');assert.ok(await last.evaluate(node=>document.activeElement===node))
    if(directory)await page.screenshot({path:resolve(directory,`object-dialog-${viewport}.png`)})
    await close.click();await dialog.waitFor({state:'detached'})
    assert.ok(await opener.evaluate(node=>document.activeElement===node));assert.deepEqual(await operations(),before)
    results.push({width,height,geometry,titleClose:true,focusRestored:true,draftUnchanged:true})
  }
  await page.setViewportSize(originalViewport)
  return results
}
