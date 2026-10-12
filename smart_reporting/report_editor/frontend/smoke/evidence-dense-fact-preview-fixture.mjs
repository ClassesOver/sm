// 单独复查39节点、长业务名和登记摘要的手机3D预览，不运行完整场景矩阵。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const analysisId = 'analysis-fixture-001'
const root = 'fact-fixture-001'
const layer = prefix => Array.from({ length: 12 }, (_, i) => `${prefix}-${i}`)
const first = layer('first')
const shared = layer('shared')
const branch = layer('branch')
first[0] = '跨院区收入与成本口径调整后月度汇总计算结果'.repeat(3)
shared[0] = '医疗服务收入明细与患者来源渠道关联输入快照'.repeat(3)
const inputs = new Map([
  [root, first],
  [first[0], [...shared, root, first[0]]],
  [first[1], [...shared, ...branch]],
  [branch[0], [first[1], root]],
])
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  // 视差随指针偏转视角；像素与几何检查需要静止视角，先关闭。
  await page.addInitScript(() => localStorage.setItem('smart-reporting-evidence-3d-parallax', 'off'))
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await mkdir('/home/junge/pros/smart_reporting/output', { recursive: true })
  await page.addInitScript(() => {
    const NativeWorker = window.Worker
    window.Worker = class extends NativeWorker {
      postMessage(data, ...args) {
        if (data.input) window.lastLabelLayoutInput = data.input
        return super.postMessage(data, ...args)
      }
    }
  })
  // 保留组件原生相机动作，记录实际适应输入与节点投影，避免仅凭四边未裁切判断概览。
  await page.route('**/assets/3d-force-graph-*.js', async route => {
    const response = await route.fetch()
    const source = await response.text()
    const patched = source.replace(/export\{(\w+) as default\};/, (_, constructor) => `
      function GraphProbe(...args) {
        const graph = new ${constructor}(...args);
        window.currentGraph3d = graph;
        const fit = graph.zoomToFit;
        graph.zoomToFit = function(...args) {
          window.graphFitPadding = args[1];
          return fit.apply(this, args);
        };
        return graph;
      }
      export { GraphProbe as default };`)
    assert.notEqual(patched, source, '找到组件默认导出以读取原生相机')
    await route.fulfill({ response, body: patched })
  })
  await page.route('**/api/sources', async route => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.facts = [root, ...first, ...shared, ...branch].map(factId => ({
      analysisId, factId, factKind: 'metric', label: factId, name: factId,
      displayValue: 12450, unit: '万元', datasetIds: [], periodRoles: ['current'],
      periodStart: '2025-01-01', periodEnd: '2025-11-01',
    }))
    await route.fulfill({ response, json: payload })
  })
  await page.route('**/api/facts/**', route => {
    const factId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1))
    return route.fulfill({ json: {
      analysisId, factId, factKind: 'metric', displayValue: 12450,
      entry: { unit: '万元' }, inputFactRefs: (inputs.get(factId) ?? []).map(factId => ({ analysisId, factId })), warnings: [],
    } })
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
  // 15 个节点以内的小图默认 2D；本检查针对 3D，先显式切换。
  await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
  const canvas = page.locator('.evidence-graph-3d canvas')
  const settledCanvas = async (options) => {
    await page.waitForFunction(() => document.querySelector('.evidence-graph-3d')?.dataset.labelLayout !== 'settling')
    return canvas.screenshot(options)
  }
  // 检查真实渲染像素：内缩2px避开主题边框/截图舍入，标签或球体触边即视为裁切风险。
  const fitsCanvas = async () => page.evaluate(async png => {
    const image = new Image()
    image.src = `data:image/png;base64,${png}`
    await image.decode()
    const probe = document.createElement('canvas')
    probe.width = image.width
    probe.height = image.height
    const context = probe.getContext('2d')
    context.drawImage(image, 0, 0)
    const { data } = context.getImageData(0, 0, probe.width, probe.height)
    const background = (x, y) => {
      const offset = (y * probe.width + x) * 4
      return [7, 19, 33].every((value, channel) => Math.abs(data[offset + channel] - value) <= 2)
    }
    const pixel = (x, y) => ({ x, y, color: [...data.slice((y * probe.width + x) * 4, (y * probe.width + x) * 4 + 4)] })
    for (let x = 2; x < probe.width - 2; x++) {
      if (!background(x, 2)) return pixel(x, 2)
      if (!background(x, probe.height - 3)) return pixel(x, probe.height - 3)
    }
    for (let y = 2; y < probe.height - 2; y++) {
      if (!background(2, y)) return pixel(2, y)
      if (!background(probe.width - 3, y)) return pixel(probe.width - 3, y)
    }
    return true
  }, (await settledCanvas()).toString('base64'))
  const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
  const trace = page.getByRole('combobox', { name: '追踪预览关系端点' })
  await canvas.waitFor()
  assert.equal(await picker.locator('option').count(), 16)
  const title = await page.locator('.evidence-object-title').textContent()
  const back = await page.locator('[data-evidence="back"]').isEnabled()
  for (const [key, count] of [[first[0], 27], [first[1], 39], [branch[0], 39]]) {
    await page.waitForTimeout(100);
    const previous=await page.evaluate(()=>window.currentGraph3d.graphData().nodes.map(n=>({id:n.id,x:n.x,y:n.y,z:n.z})));
    await picker.selectOption(`fact:${analysisId}/${key}`)
    await page.locator('.evidence-branch-load').click()
    await page.getByRole('button', { name: '已加载登记关系', exact: true }).waitFor()
    await page.waitForTimeout(150);
    const expanded=await page.evaluate(()=>window.currentGraph3d.graphData().nodes.map(n=>({id:n.id,x:n.x,y:n.y,z:n.z})));
    for(const old of previous){const n=expanded.find(n=>n.id===old.id);assert.ok(n);for(const axis of ['x','y','z'])assert.ok(Math.abs(n[axis]-old[axis])<.001, '展开后原节点坐标保持')}
    assert.equal(await picker.locator('option').count(), count + 1)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), back)
  }

  assert.equal(await page.evaluate(()=>window.currentGraph3d.dagMode()),null,'反馈环使用原生自由布局');
  const audit = []
  for (const [width,height] of [[390,844]]) {
    await page.setViewportSize({width,height})
    if(width===390) await page.getByRole('button',{name:'查看关系图',exact:true}).click()
    await picker.selectOption(`fact:${analysisId}/${first[0]}`)
    await page.getByRole('button',{name:'适应 3D',exact:true}).click()
    await page.waitForTimeout(700)
    await page.mouse.move(0,0)
    await settledCanvas({path:`/home/junge/pros/smart_reporting/output/report-editor-dense-registered-spatial-long-focus-${width}.png`})
    assert.equal(await picker.locator('option').count(),40)
    assert.equal(await fitsCanvas(),true)
    await settledCanvas({path:`/home/junge/pros/smart_reporting/output/report-editor-dense-registered-spatial-long-all-${width}.png`})
    for (const rotation of [0, 1, 2]) {
      if (rotation) {
        const rect = await canvas.boundingBox()
        await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2)
        await page.mouse.down()
        await page.mouse.move(rect.x + rect.width / 2 + (rotation === 1 ? 60 : -100), rect.y + rect.height / 2 + 20, {steps: 8})
        await page.mouse.up()
        await page.mouse.move(0,0)
        await page.waitForTimeout(700)
      }
    const geometry = await page.evaluate(()=>{
      const graph=window.currentGraph3d, camera=graph.camera(), size=document.querySelector('.evidence-graph-3d canvas').getBoundingClientRect(), labels=[];
      graph.scene().updateMatrixWorld(true);
      // 节点信息卡（Mesh）的实际投影矩形；名称绘制在卡片贴图内。
      graph.scene().traverse(mesh=>{const card=mesh.userData?.evidenceCard, id=mesh.__data?.id;if(!card||!mesh.visible||!id)return;
       if(!mesh.geometry.boundingBox)mesh.geometry.computeBoundingBox();const box=mesh.geometry.boundingBox;
       const corners=[[box.min.x,box.min.y],[box.max.x,box.min.y],[box.min.x,box.max.y],[box.max.x,box.max.y]].map(([x,y])=>mesh.position.clone().set(x,y,0).applyMatrix4(mesh.matrixWorld).project(camera)).map(p=>({x:(p.x+1)*size.width/2,y:(1-p.y)*size.height/2}));
       const center=mesh.position.clone().setFromMatrixPosition(mesh.matrixWorld).project(camera), left=Math.min(...corners.map(p=>p.x)), top=Math.min(...corners.map(p=>p.y));
       labels.push({id,text:card.detail+'\n'+card.name,x:left,y:top,width:Math.max(...corners.map(p=>p.x))-left,height:Math.max(...corners.map(p=>p.y))-top,nodeX:(center.x+1)*size.width/2,nodeY:(1-center.y)*size.height/2});
      });
      const area=(a,b)=>Math.max(0,Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y));
      return {labels,names:labels.flatMap((a,i)=>labels.slice(i+1).filter(b=>area(a,b)>1).map(b=>[a.id,b.id])),icons:labels.flatMap(a=>labels.filter(b=>a.id!==b.id&&area(a,{x:b.nodeX-1,y:b.nodeY-1,width:2,height:2})>0).map(b=>[a.id,b.id]))};
    });
    const {writeFile:saveGeometry}=await import('node:fs/promises');await saveGeometry(`/home/junge/pros/smart_reporting/output/report-editor-dense-registered-rotation-${rotation}-label-geometry.json`,JSON.stringify(geometry,null,2));
    // 适应视图下信息卡互不遮挡；旋转后不同纵深的卡片前后交叠属正常 3D 遮挡，只记录数量。
    if (rotation === 0) {
      assert.equal(geometry.names.length, 0, '密集预览信息卡互不覆盖');
      assert.equal(geometry.icons.length, 0, '密集预览信息卡不覆盖其他节点中心');
    }
    assert.equal(await fitsCanvas(), true, '旋转后无画布边界裁切');
    console.log(JSON.stringify({rotation,labels:geometry.labels.length,nameCollisions:geometry.names.length,iconCollisions:geometry.icons.length}));
      await settledCanvas({path:`/home/junge/pros/smart_reporting/output/report-editor-dense-registered-rotation-${rotation}-390.png`})
    }
    const preview = page.locator('.evidence-preview')
    assert.ok((await preview.boundingBox()).height <= 170.1)
    for (const button of await preview.locator('button').all()) {
      await button.scrollIntoViewIfNeeded()
      const bounds = await button.boundingBox(), region = await preview.boundingBox()
      assert.ok(bounds.y >= region.y - 1 && bounds.y + bounds.height <= region.y + region.height + 1, '预览操作滚动后完整可见')
    }
    const beforeClose = (await canvas.boundingBox()).height
    await preview.getByRole('button', {name:'关闭预览',exact:true}).click()
    await page.waitForTimeout(250)
    assert.ok((await canvas.boundingBox()).height > beforeClose, '关闭预览释放画布空间')
    const graph = await page.evaluate(()=>({nodes:window.currentGraph3d.graphData().nodes.length,edges:window.currentGraph3d.graphData().links.length,opacity:window.currentGraph3d.nodeOpacity()}))
    assert.deepEqual(graph,{nodes:39,edges:55,opacity:1})
    audit.push({width,...graph,bounds:'passed'})
  }
  assert.deepEqual(errors,[])
  const result={audit,errors}
  const {writeFile}=await import('node:fs/promises')
  await writeFile('/home/junge/pros/smart_reporting/output/report-editor-dense-registered-preview-final-label-geometry-result.json',JSON.stringify(result,null,2))
  console.log(JSON.stringify(result))
} finally { await browser.close() }
