// 真实native宿主：当前设置、无修改确认、取消与仅改一个格式字段。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const liveFrontend = fileURLToPath(new URL('../', import.meta.url)), repo = resolve(liveFrontend, '../../..')
const frontend = process.env.CHART_CURRENT_FRONTEND ?? liveFrontend
const out = process.env.CHART_CURRENT_DIRECTORY
assert(out, '显式设置CHART_CURRENT_DIRECTORY'); await mkdir(out, { recursive: true })
const staticRoot = process.env.CHART_CURRENT_STATIC_ROOT, baseline = process.env.CHART_CURRENT_BASELINE
const port = Number(process.env.CHART_CURRENT_PORT ?? 4481), origin = `http://127.0.0.1:${port}`
const sha = value => createHash('sha256').update(value).digest('hex')
const python = 'from openpyxl import Workbook\nfrom openpyxl.chart import BarChart,Reference\nfrom openpyxl.chart.label import DataLabelList\nfrom openpyxl.chart.axis import ChartLines\nfrom io import BytesIO\nimport sys\nb=Workbook();s=b.active;s.title="Data";s.append(["季度","收入"]);s.append(["Q1",12]);s.append(["Q2",25]);s["D1"]="保留来源";c=BarChart();c.add_data(Reference(s,min_col=2,min_row=1,max_row=3),titles_from_data=True);c.set_categories(Reference(s,min_col=1,min_row=2,max_row=3));c.title="来源标题";c.x_axis.title="季度 & 月份";c.y_axis.title="营收（万元）";c.grouping="stacked";c.legend.position="b";c.y_axis.majorGridlines=ChartLines();c.dLbls=DataLabelList(showVal=True);s.add_chart(c,"F3");f=BytesIO();b.save(f);sys.stdout.buffer.write(f.getvalue())'
const fixture = spawnSync(join(repo, '.venv/bin/python'), ['-c', python]); assert.equal(fixture.status, 0, fixture.stderr.toString())
const bytes = fixture.stdout; await writeFile(join(out, 'source.xlsx'), bytes)
const manifest = staticRoot ? sha(await readFile(join(staticRoot, '.vite/manifest.json'))) : null
if (process.env.CHART_CURRENT_MANIFEST) assert.equal(manifest, process.env.CHART_CURRENT_MANIFEST)
const code = `import {createServer,preview} from 'vite';import {readFile} from 'node:fs/promises';const root=${JSON.stringify(frontend)},staticRoot=${JSON.stringify(staticRoot ?? null)},baseline=${JSON.stringify(baseline ?? null)};if(staticRoot){await preview({root,build:{outDir:staticRoot},preview:{host:'127.0.0.1',port:${port},strictPort:true}})}else{const s=await createServer({root,cacheDir:${JSON.stringify(join(out,'vite-cache'))},server:{host:'127.0.0.1',port:${port},strictPort:true},plugins:[{name:'explicit-pre-change-sources',enforce:'pre',async load(id){if(baseline&&['workbook-main.ts','workbook-chart-design-dialog.ts','chart-read.ts'].some(name=>id.endsWith('/'+name)))return readFile(baseline+'/'+id.split('/').at(-1),'utf8')}}]});await s.listen()}`
const server = spawn(process.execPath, ['--input-type=module', '-e', code], { cwd: frontend })
let log = '', browser, page; const errors = [], requests = [], assets = {}, checks = [], cases = []
server.stdout.on('data', data => { log += data }); server.stderr.on('data', data => { log += data })
try {
  for (let i=0;;i++) { assert.equal(server.exitCode, null, log); try { if ((await fetch(origin+'/reports/v1/editor/assets/native.html')).ok) break } catch {} assert(i<240,log);await delay(250) }
  browser = await chromium.launch({ headless: true }); page = await browser.newPage()
  page.on('pageerror', error=>errors.push(error.message))
  if(staticRoot) page.on('response', response=>{ const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/assets/')||!/\.(js|css)$/.test(path))return;checks.push((async()=>{const body=await response.body(),rel=path.slice('/reports/v1/editor/assets/'.length);assert.equal(sha(body),sha(await readFile(join(staticRoot,rel))));assets[rel]=sha(body)})()) })
  await page.route('**/reports/v1/native/chart-current/1/api/**',route=>{const path=new URL(route.request().url()).pathname;requests.push({method:route.request().method(),path});if(path.endsWith('/context'))return route.fulfill({json:{ok:true,context:{documentId:'chart-current',format:'xlsx',revision:1,parentRevision:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'当前设置.xlsx',size:bytes.length,sha256:sha(bytes),mediaType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},origin:'upload'},csrfToken:'fixture',capabilities:{xlsx_editor:true},editingEnabled:true}});if(path.endsWith('/file'))return route.fulfill({body:bytes,contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});return route.fulfill({status:405,json:{error:'不允许保存/发布'}})})
  await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/chart-current/1'))
  const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')))
  const open=async command=>{await page.locator('[data-ribbon-tab="Chart Design"]').click();await page.locator(`[data-ribbon-command="${command}"]`).click();await page.locator('[role="dialog"][aria-label="编辑图表设计"]').waitFor()}
  const dialog=page.locator('[role="dialog"][aria-label="编辑图表设计"]')
  const viewports = process.env.CHART_CURRENT_VIEWPORTS?.split(',').map(value=>value.split('x').map(Number)) ?? [[1440,900],[320,640],[640,360],[390,320]]
  for(const [width,height] of viewports) {
    await page.setViewportSize({width,height});await page.goto(origin+'/reports/v1/editor/assets/native.html');await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:120000})
    const before=await draft(),unchanged=[]
    for(const [command,label,value] of [['chart-axis-cat','分类轴标题','季度 & 月份'],['chart-axis-val','数值轴标题','营收（万元）'],['chart-legend','图例位置','bottom'],['chart-labels','数据标签','value'],['chart-format-pane','图表分组','stacked']]) {
      await open(command);const control=dialog.getByLabel(label,{exact:true});const actual=await control.inputValue();await writeFile(join(out,`current-${width}x${height}-${command}.json`),JSON.stringify({expected:value,actual}));assert.equal(actual,value)
      if(command==='chart-format-pane')assert(await dialog.getByLabel('显示主网格线',{exact:true}).isChecked())
      const hit=await dialog.locator('[data-chart-design-submit]').evaluate(element=>{const r=element.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===element});assert(hit)
      await dialog.locator('[data-chart-design-submit]').click();await dialog.waitFor({state:'hidden'});assert.deepEqual(await draft(),before);unchanged.push(command)
    }
    await open('chart-format-pane');await dialog.getByLabel('图表分组',{exact:true}).selectOption('clustered');await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.deepEqual(await draft(),before)
    await open('chart-format-pane');assert.equal(await dialog.getByLabel('图表分组',{exact:true}).inputValue(),'stacked');await page.screenshot({path:join(out,`format-current-${width}x${height}.png`),animations:'disabled'})
    await dialog.getByLabel('显示主网格线',{exact:true}).uncheck();await dialog.locator('[data-chart-design-submit]').click();await dialog.waitFor({state:'hidden'})
    const after=await draft(),edits=after.flatMap(([,v])=>JSON.parse(v).operations??[]).filter(op=>op.kind==='applyChartEdits').flatMap(op=>op.edits)
    assert.deepEqual(edits,[{chartPath:'xl/charts/chart1.xml',gridlines:false}]);await open('chart-format-pane');assert.equal(await dialog.getByLabel('图表分组',{exact:true}).inputValue(),'stacked');assert.equal(await dialog.getByLabel('显示主网格线',{exact:true}).isChecked(),false)
    await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.deepEqual(await draft(),after)
    cases.push({width,height,unchanged,partialEdit:edits[0],cancelPreserved:true});await page.evaluate(()=>localStorage.clear())
  }
  await Promise.all(checks);assert.deepEqual(errors,[]);assert.equal(requests.filter(r=>r.method!=='GET').length,0)
  await writeFile(join(out,'evidence.json'),JSON.stringify({ok:true,scope:staticRoot?'Frozen native current-state/no-op/partial-edit':'Source native current-state/no-op/partial-edit',manifest,sourceSha256:sha(bytes),cases,requests,errors,assets},null,2));console.log(JSON.stringify({ok:true,cases:cases.length,assets:Object.keys(assets).length,manifest}))
} catch(error) {await page?.screenshot({path:join(out,'failure.png')}).catch(()=>undefined);await writeFile(join(out,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,cases,errors,requests},null,2));throw error}
finally {await browser?.close();server.kill('SIGTERM');await writeFile(join(out,'server.log'),log)}
