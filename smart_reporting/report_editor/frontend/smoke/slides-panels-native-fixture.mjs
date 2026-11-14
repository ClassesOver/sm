// 可选冻结 native 宿主；授权/修订为显式夹具，复用现有真实 PPTX inspect/render helper。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { spawnSync } from 'node:child_process'
import { basename, extname, resolve } from 'node:path'

export async function createSlidesPanelsNativeFixture({ frontend, staticRoot, expectedManifest, sourcePath, targetType = 'shape', sourceOrigin }) {
  assert.ok(sourceOrigin || expectedManifest, 'native static 模式必须显式指定 SLIDES_PANELS_EXPECTED_MANIFEST_SHA256')
  const sha = bytes => createHash('sha256').update(bytes).digest('hex')
  const manifest = sourceOrigin ? null : sha(await readFile(resolve(staticRoot, '.vite/manifest.json')))
  if (!sourceOrigin) assert.equal(manifest, expectedManifest, '冻结 manifest 身份不匹配')
  const nativeHtml = sourceOrigin ? (await readFile(resolve(frontend, 'native.html'), 'utf8')).replace('/src/unified-main.ts', sourceOrigin + '/reports/v1/editor/assets/src/unified-main.ts') : await readFile(resolve(staticRoot, 'native.html'))
  const repo = resolve(frontend, '../../..'), helper = resolve(frontend, 'smoke/office-pptx-background-fixture.py')
  const engine = payload => {
    const result = spawnSync(resolve(repo, '.venv/bin/python'), [helper], { cwd: repo,
      env: { ...process.env, PYTHONPATH: repo, TMPDIR: '/dev/shm', PYTHONDONTWRITEBYTECODE: '1' },
      input: JSON.stringify({ directory: resolve(sourcePath, '..'), source: sourcePath, ...payload }), encoding: 'utf8', maxBuffer: 40 * 1024 * 1024, timeout: 120000 })
    assert.equal(result.status, 0, result.stderr); return JSON.parse(result.stdout)
  }
  const bytes = await readFile(sourcePath), identity = sha(bytes), entry = engine({ mode: 'inspect' })
  assert.equal(entry.sha256, identity)
  const chartTargets = element => element.type === 'chart' && element.chartEditSafe && element.chartSeries?.length >= 2 && element.chartCategories?.length >= 2
  const slide = targetType === 'chart' ? entry.model.slides.find(slide => slide.elements.some(chartTargets)) : entry.model.slides.find(slide => slide.elements.filter(element => element.arrangeEditable && element.brushSource?.supported
    && element.brushSource.shape?.fill !== undefined && ['text', 'shape'].includes(element.type)).length >= 2)
  assert.ok(slide, targetType === 'chart' ? '真实来源须有可编辑的双系列图表' : '真实来源须有同页两个可安全修改填充和大小的对象')
  const targets = targetType === 'chart' ? slide.elements.filter(chartTargets).slice(0, 1) : slide.elements.filter(element => element.arrangeEditable && element.brushSource?.supported
    && element.brushSource.shape?.fill !== undefined && ['text', 'shape'].includes(element.type)).slice(0, 2)
  const prefix = '/reports/v1/editor/assets/', docId = 'panels-native', pathBase = `/reports/v1/native/${docId}/`
  const resources = new Map(), checks = [], requests = [], errors = []
  let saveRequests = 0, downloadEvents = 0
  const httpServer = createServer(async (request, response) => {
    try {
      const path = new URL(request.url, 'http://localhost').pathname
      if (path === '/favicon.ico') { response.writeHead(204); response.end(); return }
      if (sourceOrigin && path.startsWith(prefix)) { response.writeHead(302, { Location: sourceOrigin + path }); response.end(); return }
      assert.ok(path.startsWith(prefix)); const file = resolve(staticRoot, path.slice(prefix.length))
      assert.ok(file.startsWith(staticRoot + '/')); const content = await readFile(file)
      response.writeHead(200, { 'Content-Type': { '.js': 'application/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.wasm': 'application/wasm' }[extname(file)] ?? 'application/octet-stream' }); response.end(content)
    } catch { response.writeHead(404); response.end('not found') }
  })
  return {
    server: { httpServer, listen: () => new Promise(resolve => httpServer.listen(0, '127.0.0.1', resolve)), close: () => new Promise(resolve => httpServer.close(resolve)) },
    target: { slideIndex: slide.slideIndex, ...targets[0] },
    otherTarget: targets[1]?.id,
    otherWidth: targets[1] ? String(Math.round(targets[1].geometry.width / (96 / 2.54) * 100) / 100) : undefined,
    requests,
    async setup(page) {
      page.on('download', () => { downloadEvents++ })
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
      page.on('dialog', dialog => dialog.type() === 'beforeunload' ? dialog.accept() : dialog.dismiss())
      page.on('response', response => {
        const path = new URL(response.url()).pathname
        if (response.status() >= 400) errors.push(`${response.status()} ${path}`)
        if (response.status() === 200 && path.startsWith(prefix) && /\.(?:js|css|ts|tsx)$/.test(path)) checks.push(response.body().then(async bytes => {
          if (!sourceOrigin) assert.equal(sha(bytes), sha(await readFile(resolve(staticRoot, path.slice(prefix.length)))))
          resources.set(path, { sha256: sha(bytes), size: bytes.length })
        }).catch(error => errors.push(String(error))))
      })
      await page.route(new RegExp(pathBase + '[0-9]+$'), async route => route.fulfill({ body: nativeHtml, contentType: 'text/html' }))
      await page.route('**' + pathBase + '*/api/**', async route => {
        try {
          const request = route.request(), path = new URL(request.url()).pathname, endpoint = path.split('/').at(-1)
          requests.push(endpoint)
          if (endpoint === 'save') { saveRequests++; throw Error('只读属性窗格补验禁止保存') }
          if (endpoint === 'context') return route.fulfill({ json: { context: { documentId: docId, format: 'pptx', revision: 1, parentRevision: null,
            scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, origin: 'upload',
            sourceFile: { path: basename(sourcePath), size: bytes.length, sha256: identity, mediaType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' } },
            csrfToken: 'fixture', capabilities: { pptx_editor: true }, editingEnabled: true } })
          if (endpoint === 'file') return route.fulfill({ body: bytes, contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })
          if (endpoint === 'preview.pdf') return route.fulfill({ status: 204, body: '' })
          const post = request.method() === 'POST' ? request.postDataJSON() : undefined
          assert.equal(post?.expectedSha256, identity)
          if (endpoint === 'preview') { const preview = engine({ mode: 'inspect', operations: post.operations }); return route.fulfill({ json: { sourceSha256: identity, draftSha256: preview.sha256, model: preview.model } }) }
          assert.equal(endpoint, 'render-tree'); return route.fulfill({ json: engine({ mode: 'render', operations: post.operations }) })
        } catch (error) { errors.push(String(error)); await route.fulfill({ status: 500, json: { detail: String(error) } }) }
      })
    },
    async open(page) {
      const origin = `http://127.0.0.1:${httpServer.address().port}`
      if (page.url().startsWith(origin)) await page.evaluate(() => { for (const key of Object.keys(localStorage)) if (key.startsWith('native-editor-draft:')) localStorage.removeItem(key) })
      await page.goto(origin + pathBase + '1'); await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
      await page.locator(`.slide-open[data-slide-index="${slide.slideIndex}"]`).click()
      await page.locator('#object-select').selectOption(targets[0].id)
    },
    draft: page => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations)),
    async finish() {
      await Promise.all(checks); assert.deepEqual(errors, []); assert.equal(saveRequests, 0); assert.equal(downloadEvents, 0)
      assert.equal(sha(await readFile(sourcePath)), identity)
      return { mode: sourceOrigin ? 'source' : 'frozen', staticRoot: sourceOrigin ? null : staticRoot, sourceOrigin, manifestSha256: manifest, sourcePath, sourceSha256: identity, sourceUnchanged: true, helperSha256: sha(await readFile(helper)), targets: targets.map(target => ({ slideIndex: slide.slideIndex, id: target.id, geometry: target.geometry })), resources: Object.fromEntries(resources), resourcesMatched: !sourceOrigin, saveRequests, downloadEvents, errors }
    },
  }
}
