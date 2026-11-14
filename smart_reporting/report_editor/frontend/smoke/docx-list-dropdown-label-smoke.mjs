import assert from 'node:assert/strict'
import {createServer} from 'vite'
import {chromium} from 'playwright'
import {mkdir,writeFile} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import {join} from 'node:path'
const frontend=fileURLToPath(new URL('../',import.meta.url)),output=process.env.DOCX_LIST_DROPDOWN_OUTPUT??'/dev/shm/office-word-list-libraries-20261113/dropdown-label'
await mkdir(output,{recursive:true})
const vite=await createServer({root:frontend,configFile:join(frontend,'vite.config.ts'),server:{host:'127.0.0.1',port:4434,strictPort:true,cors:true}})
await vite.listen()
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),cases=[]
try {
 for(const kind of ['bullets','numbers','multi']) {
  await page.route('**/__list_case__',route=>route.fulfill({contentType:'text/html',body:`<html><head><meta charset="utf-8"><link rel="stylesheet" href="/reports/v1/editor/assets/src/vendor/genoffice-docs/apps/docs/src/renderer/styles.css"></head><body><script type="module">import {createDocxListGallery} from '/reports/v1/editor/assets/src/docx-list-gallery.tsx';window.trace=[];document.addEventListener('click',e=>trace.push({target:e.target.tagName,cls:typeof e.target.className==='string'?e.target.className:'',value:e.target.dataset.value,prevented:e.defaultPrevented,trusted:e.isTrusted}));const v=createDocxListGallery({kind:${JSON.stringify(kind)},reason:()=>null,current:()=>undefined,styles:()=>[],apply:()=>{},clear:()=>{},report:console.error});document.body.append(v.element);window.ready=true;</script></body></html>`}))
  await page.goto('http://127.0.0.1:4434/__list_case__');await page.waitForFunction(()=>window.ready)
  await page.locator('[data-docx-list-toggle]').click();await page.locator('[data-docx-list-define]').click()
  const font=page.locator('.list-dialog-font .gs-dd-btn').first();await font.click();await page.locator('.list-dialog-font .gs-dd-item[data-value="Arial"]').click()
  const state=await font.evaluate(n=>({expanded:n.getAttribute('aria-expanded'),value:n.dataset.value,trace:window.trace}))
  cases.push({kind,...state});await writeFile(join(output,'summary.json'),JSON.stringify({cases},null,2));await page.screenshot({path:join(output,`${kind}.png`)})
  assert.equal(state.value,'Arial');assert.equal(state.expanded,'false','label默认行为不能再次激活Dropdown trigger')
  await page.locator('.modal-actions .primary').click();assert.equal(await page.locator('[role=dialog]').count(),0)
  await page.unroute('**/__list_case__')
 }
 await writeFile(join(output,'summary.json'),JSON.stringify({ok:true,cases},null,2));console.log(JSON.stringify({ok:true,cases:cases.length}))
}finally{await browser.close();await vite.close()}
