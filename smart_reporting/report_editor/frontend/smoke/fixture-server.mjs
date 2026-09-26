import { createHash } from 'node:crypto'
import { readFile, stat } from 'node:fs/promises'
import http from 'node:http'
import { extname, join, normalize } from 'node:path'

const port = Number(process.env.REPORT_EDITOR_FIXTURE_PORT ?? 4173)
const root = new URL('../../static/', import.meta.url).pathname
const editorPath = '/reports/v1/editor/fixture-report/1'
let markdown = '# 医院整体运营情况分析报告\n\n## 核心结论\n\n用于浏览器布局回归。\n'
const history = [
  { revision: 1, markdown: '# 医院整体运营情况分析报告\n\n## 核心结论\n\n初始版本。\n', source: 'published', createdAt: '2026-09-20T08:30:00+08:00', note: '初始发布' },
  { revision: 2, markdown: '# 医院整体运营情况分析报告\n\n## 核心结论\n\n补充运营数据。\n', source: 'manual', createdAt: '2026-09-21T09:15:00+08:00', note: '运营数据复核' },
]
const digest = () => createHash('sha256').update(markdown).digest('hex')
const pdf = Buffer.from('%PDF-1.7\n%%EOF\n')
const word = Buffer.from('PK\u0003\u0004fixture-docx')
const exports = new Map()
const contentTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.woff2': 'font/woff2',
}

function json(response, body) {
  response.writeHead(200, {
    'Cache-Control': 'no-store',
    'Content-Type': 'application/json; charset=utf-8',
  })
  response.end(JSON.stringify(body))
}

async function requestJson(request) {
  let body = ''
  for await (const chunk of request) body += chunk
  return JSON.parse(body)
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, `http://127.0.0.1:${port}`)
  if (request.method === 'GET' && url.pathname === editorPath) {
    response.writeHead(200, { 'Content-Type': contentTypes['.html'] })
    response.end(await readFile(join(root, 'index.html')))
    return
  }
  if (request.method === 'GET' && url.pathname === `${editorPath}/api/document`) {
    json(response, {
      path: 'reports/revision-1/report.md',
      markdown,
      sha256: digest(),
      csrfToken: 'fixture-csrf',
    })
    return
  }
  if (request.method === 'PUT' && url.pathname === `${editorPath}/api/document`) {
    const payload = await requestJson(request)
    if (payload.expectedSha256 !== digest()) {
      response.writeHead(409, { 'Content-Type': 'application/json; charset=utf-8' })
      response.end(JSON.stringify({ detail: { code: 'report_editor_conflict' } }))
      return
    }
    markdown = payload.markdown
    json(response, { path: 'reports/revision-1/draft/report.md', markdown, sha256: digest() })
    return
  }
  if (request.method === 'POST' && url.pathname === `${editorPath}/api/export`) {
    const payload = await requestJson(request)
    if (payload.expectedSha256 !== digest()) {
      response.writeHead(409, { 'Content-Type': 'application/json; charset=utf-8' })
      response.end(JSON.stringify({ detail: { code: 'report_editor_conflict' } }))
      return
    }
    // 与服务端一致：导出为后台任务，提交返回 202，结果通过状态接口轮询。
    const exportId = String(request.headers['x-request-id'] || 'fixture-export')
    exports.set(exportId, {
      revision: 2,
      pdf: { downloadUrl: `http://127.0.0.1:${port}/fixture.pdf`, size: pdf.length },
      word: { downloadUrl: `http://127.0.0.1:${port}/fixture.docx`, size: word.length },
    })
    response.writeHead(202, { 'Content-Type': 'application/json; charset=utf-8' })
    response.end(JSON.stringify({ exportId, status: 'running', requestId: exportId }))
    return
  }
  if (request.method === 'GET' && url.pathname.startsWith(`${editorPath}/api/export/`)) {
    const exportId = decodeURIComponent(url.pathname.slice(`${editorPath}/api/export/`.length))
    const result = exports.get(exportId)
    if (!result) {
      response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' })
      response.end(JSON.stringify({ detail: { code: 'report_editor_export_missing' } }))
      return
    }
    json(response, { exportId, status: 'succeeded', requestId: exportId, result })
    return
  }
  if (request.method === 'POST' && url.pathname === `${editorPath}/api/events`) {
    response.writeHead(204)
    response.end()
    return
  }
  if (request.method === 'GET' && url.pathname === '/fixture.pdf') {
    response.writeHead(200, { 'Content-Type': 'application/pdf' })
    response.end(pdf)
    return
  }
  if (request.method === 'GET' && url.pathname === '/fixture.docx') {
    response.writeHead(200, { 'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
    response.end(word)
    return
  }
  if (request.method === 'GET' && url.pathname === `${editorPath}/api/history`) {
    const limit = Number(url.searchParams.get('limit') ?? 20)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const items = history.slice(offset, offset + limit).map(({ markdown: _markdown, ...item }) => ({
      ...item,
      sha256: createHash('sha256').update(history.find((entry) => entry.revision === item.revision)?.markdown ?? '').digest('hex'),
    }))
    json(response, { items, total: history.length, hasMore: offset + items.length < history.length })
    return
  }
  if (request.method === 'GET' && url.pathname.startsWith(`${editorPath}/api/history/`)) {
    const revision = Number(url.pathname.split('/').at(-1))
    const item = history.find((entry) => entry.revision === revision)
    if (!item) {
      response.writeHead(404)
      response.end()
      return
    }
    json(response, {
      ...item,
      sha256: createHash('sha256').update(item.markdown).digest('hex'),
    })
    return
  }
  const prefix = '/reports/v1/editor/assets/'
  if (request.method === 'GET' && url.pathname.startsWith(prefix)) {
    const relative = normalize(url.pathname.slice(prefix.length))
    const target = join(root, relative)
    try {
      if (relative.startsWith('..') || !(await stat(target)).isFile()) throw new Error('missing')
      response.writeHead(200, {
        'Content-Type': contentTypes[extname(target)] ?? 'application/octet-stream',
      })
      response.end(await readFile(target))
    } catch {
      response.writeHead(404)
      response.end()
    }
    return
  }
  response.writeHead(404)
  response.end()
})

server.listen(port, '0.0.0.0', () => {
  console.log(`fixture ready: http://127.0.0.1:${port}${editorPath}`)
})
