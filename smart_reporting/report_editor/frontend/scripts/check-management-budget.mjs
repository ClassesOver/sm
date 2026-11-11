import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'
const root = resolve('../static/management')
const manifest = JSON.parse(
  readFileSync(resolve(root, '.vite/manifest.json'), 'utf8'),
)
function scenario(entries) {
  const visited = new Set(),
    files = new Set(['management.html'])
  function collect(key) {
    if (visited.has(key)) return
    visited.add(key)
    const node = manifest[key]
    if (!node) throw Error('缺少构建节点：' + key)
    files.add(node.file)
    for (const css of node.css || []) files.add(css)
    for (const asset of node.assets || []) files.add(asset)
    for (const dependency of node.imports || []) collect(dependency)
  }
  entries.forEach(collect)
  const assets = [...files].sort().map((file) => {
    const bytes = readFileSync(resolve(root, file))
    return { file, bytes: bytes.length, gzip: gzipSync(bytes).length }
  })
  return { gzip: assets.reduce((sum, item) => sum + item.gzip, 0), assets }
}
const login = scenario([
  'management.html',
  'src/management/features/auth/login.tsx',
])
const list = scenario([
  'management.html',
  'src/management/features/auth/login.tsx',
  'src/management/app/shell.tsx',
  'src/management/features/sources/list.tsx',
])
const report = {
  login,
  list,
  limits: { login: 300 * 1024, list: 500 * 1024 },
  passed: login.gzip <= 300 * 1024 && list.gzip <= 500 * 1024,
}
const output = resolve('../../../output/management-depth')
mkdirSync(output, { recursive: true })
writeFileSync(
  resolve(output, 'build-budget.json'),
  JSON.stringify(report, null, 2),
)
console.log(
  JSON.stringify({
    loginKiB: (login.gzip / 1024).toFixed(1),
    listKiB: (list.gzip / 1024).toFixed(1),
    passed: report.passed,
  }),
)
if (!report.passed) process.exitCode = 1
