import { createHash } from 'node:crypto'
import { readFile, stat } from 'node:fs/promises'
import http from 'node:http'
import { extname, join, normalize } from 'node:path'

const port = Number(process.env.REPORT_EDITOR_FIXTURE_PORT ?? 4173)
const root = new URL('../../static/', import.meta.url).pathname
const editorPath = '/reports/v1/editor/fixture-report/1'
let markdown = '# 医院整体运营情况分析报告\n\n## 核心结论\n\n华东营收为 12,450 万元。[[citation:sub-fixture-001]]\n'
const traceSources = {
  available: true,
  datasets: [{
    datasetId: 'dataset-fixture-001', sourceType: 'url_csv', requirementId: 'fixture-attachment',
    filename: '收入明细.csv', businessLabel: '季度收入快照', rowCount: 4, size: 125,
    materializedAt: '2026-09-29T08:00:00Z', periodRoles: ['current'], queryWindowId: 'current',
  }],
  subjects: [{
    subjectId: 'sub-fixture-001', subjectKind: 'text_claim', locator: { sectionId: 'section-fixture' },
    factRefs: [{ analysisId: 'analysis-fixture-001', factId: 'fact-fixture-001' }], computationId: 'comp-fixture-001',
  }],
  drilldown: { enabled: false, metrics: [], subjects: [] },
}
const traceComputation = {
  computationId: 'comp-fixture-001', method: '渠道收入汇总', parameters: { column: 'revenue' },
  executionId: 'exec-fixture-001', environment: { python: '3.12' }, verification: 'verified',
  reproducibility: 'reproducible', limitations: [], inputDatasetIds: ['dataset-fixture-001'],
  outputFactRefs: [{ analysisId: 'analysis-fixture-001', factKey: 'fact-fixture-001', factKind: 'metric', jsonPointer: '/metrics/revenue' }],
  scriptFile: null, chain: { computationId: 'comp-fixture-001', method: '渠道收入汇总' },
}
const traceFact = {
  analysisId: 'analysis-fixture-001', factId: 'fact-fixture-001', factKind: 'metric', displayValue: 12450,
  entry: { unit: '万元', formula: 'sum(revenue)' }, inputFactRefs: [], warnings: [],
}
const tracePreview = {
  datasetId: 'dataset-fixture-001', columns: ['region', 'channel', 'revenue', 'period'],
  rows: [['华东', '线上', '4230', '2026 Q3'], ['华东', '线下', '8220', '2026 Q3'], ['华北', '线上', '3100', '2026 Q3'], ['华北', '线下', '5400', '2026 Q3']],
  rowCountTotal: 4, offset: 0, limit: 50, nextCursor: null, truncatedCells: 0, truncatedByBudget: false, cellTruncationNote: null,
}
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
  if (request.method === 'GET' && url.pathname === `${editorPath}/api/sources`) {
    json(response, traceSources)
    return
  }
  if (request.method === 'POST' && url.pathname === `${editorPath}/api/sources/validate`) {
    const payload = await requestJson(request)
    const draftSha256 = createHash('sha256').update(String(payload.markdown)).digest('hex')
    if (payload.draftSha256 !== draftSha256) {
      response.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' })
      response.end(JSON.stringify({ detail: { code: 'request_invalid' } }))
      return
    }
    const changed = String(payload.markdown).includes('12,780')
    json(response, {
      draftSha256,
      subjects: [{ subjectId: 'sub-fixture-001', claimId: 'claim-fixture-001', sectionId: 'section-fixture', status: changed ? 'stale' : 'valid', factValue: 12450, unit: '万元' }],
      summary: { valid: changed ? 0 : 1, stale: changed ? 1 : 0, unbound: 0 },
    })
    return
  }
  if (request.method === 'GET' && url.pathname === `${editorPath}/api/computations`) {
    json(response, { available: true, computations: [{ computationId: traceComputation.computationId, method: traceComputation.method, verification: traceComputation.verification, reproducibility: traceComputation.reproducibility, inputDatasetCount: 1, outputFactCount: 1 }] })
    return
  }
  if (request.method === 'GET' && url.pathname === `${editorPath}/api/computations/${traceComputation.computationId}`) {
    json(response, traceComputation)
    return
  }
  if (request.method === 'GET' && url.pathname === `${editorPath}/api/charts`) {
    json(response, { available: false, charts: [] })
    return
  }
  if (request.method === 'GET' && url.pathname === `${editorPath}/api/facts/${traceFact.analysisId}/${traceFact.factId}`) {
    json(response, traceFact)
    return
  }
  if (request.method === 'GET' && url.pathname === `${editorPath}/api/datasets/${tracePreview.datasetId}/preview`) {
    const offset = url.searchParams.get('cursor') === 'fixture-page-2' ? 2 : 0
    json(response, {
      ...tracePreview, offset, rows: tracePreview.rows.slice(offset, offset + 2),
      nextCursor: offset === 0 ? 'fixture-page-2' : null,
    })
    return
  }
  if (request.method === 'HEAD' && url.pathname === `${editorPath}/api/datasets/${tracePreview.datasetId}/download`) {
    response.writeHead(200, { 'Content-Length': '125', 'Content-Type': 'text/csv' })
    response.end()
    return
  }
  if (request.method === 'GET' && url.pathname === `${editorPath}/api/datasets/${tracePreview.datasetId}/download`) {
    response.writeHead(200, { 'Content-Type': 'text/csv; charset=utf-8' })
    response.end('region,channel,revenue,period\n华东,线上,4230,2026 Q3\n华东,线下,8220,2026 Q3\n华北,线上,3100,2026 Q3\n华北,线下,5400,2026 Q3\n')
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
