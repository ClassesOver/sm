// 仅打包镜像运行桥接；源码检出的 tsx 回退不受影响。
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs'
import { isBuiltin } from 'node:module'
import { dirname, join, relative, resolve } from 'node:path'

const [source, destination] = process.argv.slice(2).map(value => resolve(value))
const metadata = JSON.parse(readFileSync(join(source, 'dist/metafile.json'), 'utf8'))
for (const output of Object.values(metadata.outputs)) {
  for (const dependency of output.imports) {
    if (dependency.external && !isBuiltin(dependency.path)) {
      throw new Error(`Office bridge has an unbundled dependency: ${dependency.path}`)
    }
  }
}

function copy(path, target = relative(source, path)) {
  const output = join(destination, target)
  mkdirSync(dirname(output), { recursive: true })
  copyFileSync(path, output)
}
const licenseFile = name => /license|notice|copying|copyright/i.test(name)
for (const entry of readdirSync(source, { withFileTypes: true })) {
  if (entry.isFile() && (licenseFile(entry.name) || /^(SOURCE|UPSTREAM)/.test(entry.name))) copy(join(source, entry.name))
}
for (const entry of readdirSync(join(source, 'dist'))) {
  if (entry.endsWith('.mjs')) copy(join(source, 'dist', entry))
}
// 供应商许可可能嵌在源码/夹具目录，仍保留原始路径以便追溯。
function vendorLicenses(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) vendorLicenses(path)
    else if (entry.isFile() && licenseFile(entry.name)) copy(path, join('licenses', relative(source, path)))
  }
}
if (existsSync(join(source, 'packages'))) vendorLicenses(join(source, 'packages'))

// 外部依赖保留来源路径的层级，但不允许 .. 将许可写到运行目录外。
function licenseTarget(path) {
  const parts = relative(source, path).split(/[\\/]/)
  return parts.includes('..')
    ? join('licenses', 'external', ...parts.map(part => part === '..' ? '_parent_' : part))
    : join('licenses', ...parts)
}
const packages = new Set()
const localAncestors = new Set()
for (const input of Object.keys(metadata.inputs)) {
  const path = resolve(source, input)
  const parts = path.split('/')
  const modules = parts.lastIndexOf('node_modules')
  if (modules >= 0 && parts[modules + 1]) {
    packages.add(parts.slice(0, modules + (parts[modules + 1].startsWith('@') ? 3 : 2)).join('/'))
    continue
  }
  // 跨工作区本地源码（如 sibling shared package 或 vendor helper）的许可在祖先目录。
  // 仅检查到它与当前引擎的公共祖先；不递归复制该来源树。
  if (!relative(source, path).startsWith('..')) continue
  let directory = dirname(path)
  while (directory !== dirname(directory)) {
    localAncestors.add(directory)
    const back = relative(directory, source)
    if (back === '' || !back.startsWith('..')) break
    directory = dirname(directory)
  }
}
for (const dependency of packages) {
  // 个别 npm 包将完整许可放在 README 中；同时保留 manifest 的身份和 SPDX 信息。
  for (const entry of readdirSync(dependency, { withFileTypes: true })) {
    if (entry.isFile() && (licenseFile(entry.name) || /^readme/i.test(entry.name) || entry.name === 'package.json')) {
      const path = join(dependency, entry.name)
      copy(path, licenseTarget(path))
    }
  }
}
for (const directory of localAncestors) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.isFile() && licenseFile(entry.name)) {
      const path = join(directory, entry.name)
      copy(path, licenseTarget(path))
    }
  }
}
