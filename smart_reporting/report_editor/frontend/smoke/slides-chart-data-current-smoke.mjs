// 真实图表数据对话框与样式；显式宿主回调夹具不执行保存或导出。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const phase = process.env.SLIDES_CHART_DATA_PHASE ?? 'green'
const directory = join(process.env.SLIDES_CHART_DATA_DIRECTORY ?? '/dev/shm/office-current-state-pptx-20261113', phase)
await mkdir(directory, { recursive: true })
const source = `import {createNativeChartEditDialog} from './src/slides-native-chart-edit';
import './src/style.css';import './src/office-theme.css';import './src/native.css';import './src/slides.css';
const initial={kind:'bar',categories:['甲','乙'],series:[{name:'收入',values:[1,2]},{name:'成本',values:[3,4]}]},commits=[];let dialog,locked=false,target='A';
const opener=document.querySelector('#opener');opener.addEventListener('click',()=>{dialog?.dispose();const opened=target;dialog=createNativeChartEditDialog(document.body,{mode:'data',initial,onConfirm:patch=>{if(locked||target!==opened)throw Error('当前目标或锁定状态已变化，请取消后重新打开');commits.push(patch)},onClose:()=>{}})});
window.chartDataProbe={initial,commits,setLocked:value=>locked=value,changeTarget:()=>{target='B';dialog?.dispose()},open:()=>opener.click()};`
const baseline = process.env.SLIDES_CHART_DATA_BASELINE
const baselineBytes = baseline ? await readFile(baseline) : undefined
const built = await build({ plugins: baselineBytes ? [{ name: 'explicit-baseline', setup(build) { build.onLoad({ filter: /\/slides-native-chart-edit\.ts$/ }, () => ({ contents: baselineBytes.toString(), loader: 'ts', resolveDir: join(frontend, 'src') })) } }] : [], absWorkingDir: frontend, stdin: { contents: source, resolveDir: frontend, sourcefile: 'slides-chart-data-current.ts', loader: 'ts' }, bundle: true, format: 'esm', outfile: join(directory, 'component.js'), loader: { '.svg': 'dataurl', '.png': 'dataurl', '.woff': 'dataurl', '.woff2': 'dataurl' }, metafile: true })
await writeFile(join(directory, 'metafile.json'), JSON.stringify(built.metafile, null, 2))
const sources = await Promise.all(['src/slides-native-chart-edit.ts', 'src/office-theme.css', 'src/slides.css'].map(async file => ({ file, sha256: createHash('sha256').update(file === 'src/slides-native-chart-edit.ts' && baselineBytes ? baselineBytes : await readFile(join(frontend, file))).digest('hex') })))
const server = createServer(async (request, response) => {
  const file = request.url === '/component.js' ? 'component.js' : request.url === '/component.css' ? 'component.css' : null
  response.setHeader('content-type', file ? file.endsWith('.js') ? 'text/javascript' : 'text/css' : 'text/html')
  response.end(file ? await readFile(join(directory, file)) : '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/component.css"></head><body class="editor-format-pptx" style="margin:0"><button id="opener">编辑图表数据</button><script type="module" src="/component.js"></script></body></html>')
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const browser = await chromium.launch({ headless: true }), page = await browser.newPage()
const evidence = { phase, baseline: baseline ?? null, scope: 'Actual createNativeChartEditDialog and product styles; explicit host lock/target callback fixture, no backend/save/export. Real Chromium keyboard structure-edit operations.', browserVersion: browser.version(), sources, cases: [], errors: [], failures: [] }
page.on('pageerror', error => evidence.errors.push(error.message))
const check = (value, label) => { if (!value) evidence.failures.push(label) }

try {
 for(const [width,height] of phase==='red'?[[1440,900]]:[[1440,900],[320,640],[640,360],[390,320]]) {
  await page.setViewportSize({width,height});await page.goto(`http://127.0.0.1:${server.address().port}`);await page.waitForFunction(()=>window.chartDataProbe)
  for(const kind of ['category','series'])for(const action of ['add','remove']) {
   await page.locator('#opener').click();const dialog=page.locator('dialog'),row={width,height,kind,action}
   check(await dialog.locator('[data-chart-category="0"]').inputValue()==='甲'&&await dialog.locator('[data-chart-value="1:1"]').inputValue()==='4',`${width} ${kind} ${action} initial current values`)
   await dialog.locator('[data-chart-value="0:0"]').fill('27.5')
   const button=action==='add'?dialog.locator(`[data-chart-add-${kind}]`):dialog.locator(`[data-chart-${kind}="1"]`).locator('..').getByRole('button',{name:kind==='category'?'删除类别':'删除系列',exact:true})
   await button.focus();await page.keyboard.press('Enter')
   const expected=dialog.locator(`[data-chart-${kind}="${action==='add'?2:0}"]`)
   row.focus=await expected.evaluate(node=>{const r=node.getBoundingClientRect();return{focused:node===document.activeElement,value:node.value,x:r.x,y:r.y,right:r.right,bottom:r.bottom,hit:node===document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)}})
   check(row.focus.focused&&row.focus.hit&&row.focus.x>=0&&row.focus.y>=0&&row.focus.right<=width+1&&row.focus.bottom<=height+1,`${width}x${height} ${kind} ${action} focus/visibility`)
   row.currentValue=await dialog.locator('[data-chart-value="0:0"]').inputValue();check(row.currentValue==='27.5',`${width} ${kind} ${action} lost current value`)
   if(action==='remove')check(await expected.locator('..').locator('button').isDisabled(),`${width} ${kind} lower-bound reason not represented`)
   await page.screenshot({path:join(directory,`${kind}-${action}-${width}x${height}.png`)})
   await dialog.getByRole('button',{name:'取消',exact:true}).click();check(await page.locator('#opener').evaluate(node=>node===document.activeElement),`${width} cancel opener focus`)
   check(await page.evaluate(()=>window.chartDataProbe.commits.length)===0,`${width} cancel wrote data`)
   await page.locator('#opener').click();check(await page.locator('[data-chart-value="0:0"]').inputValue()==='1',`${width} cancelled draft mutated source`);await page.keyboard.press('Escape')
   evidence.cases.push(row)
  }
  // 显式宿主变更：确认被拒时保留当前输入，取消不写；目标替换移除旧窗口。
  await page.locator('#opener').click();await page.locator('[data-chart-value="0:0"]').fill('99');await page.evaluate(()=>window.chartDataProbe.setLocked(true))
  await page.locator('[data-chart-confirm]').click();check((await page.locator('[role=alert]').innerText()).includes('锁定'),`${width} locked reason`);check(await page.locator('[data-chart-value="0:0"]').inputValue()==='99',`${width} locked lost draft`)
  await page.getByRole('button',{name:'取消',exact:true}).click();await page.evaluate(()=>window.chartDataProbe.setLocked(false));await page.locator('#opener').click()
  await page.evaluate(()=>window.chartDataProbe.changeTarget());check(await page.locator('dialog').count()===0&&await page.evaluate(()=>window.chartDataProbe.commits.length)===0,`${width} target change kept stale dialog or committed`)
 }
 check(evidence.errors.length===0,`errors ${evidence.errors}`);evidence.ok=!evidence.failures.length
 await writeFile(join(directory,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:evidence.ok,cases:evidence.cases.length,failures:evidence.failures}));if(!evidence.ok)process.exitCode=1
}finally{await browser.close();await new Promise(resolve=>server.close(resolve))}
