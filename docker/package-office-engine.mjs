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

const packages = new Set()
for (const input of Object.keys(metadata.inputs)) {
  if (!input.startsWith('node_modules/')) continue
  const parts = input.split('/')
  packages.add(parts.slice(0, parts[1].startsWith('@') ? 3 : 2).join('/'))
}
for (const dependency of packages) {
  // 个别 npm 包将完整许可放在 README 中；同时保留 manifest 的身份和 SPDX 信息。
  for (const entry of readdirSync(join(source, dependency), { withFileTypes: true })) {
    if (entry.isFile() && (licenseFile(entry.name) || /^readme/i.test(entry.name) || entry.name === 'package.json')) {
      const path = join(source, dependency, entry.name)
      copy(path, join('licenses', relative(source, path)))
    }
  }
}
