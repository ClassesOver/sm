// PDF 专用资源收口；通用 packer 仍拒绝所有非 builtin external。
import { createHash } from 'node:crypto'
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const [sourceArg, destinationArg, packerArg] = process.argv.slice(2)
const source = resolve(sourceArg), destination = resolve(destinationArg)
const assets = {
  'pdfium.wasm': ['@embedpdf/pdfium/dist/pdfium.wasm', '5e4cd023c3dad4a895b3571ca573d3fc51bac6de48360d95283134385b954eaa'],
  'hb-subset.wasm': ['harfbuzzjs/hb-subset.wasm', '3a5d246b0e4c0017084775e9f2c7fce96e45d09b1a354fd9e2e440c88fb9890d'],
}
for (const [name, [path, digest]] of Object.entries(assets)) {
  const input = join(source, 'node_modules', path)
  if (!existsSync(input)) throw new Error(`PDF runtime asset missing: ${name}`)
  if (createHash('sha256').update(readFileSync(input)).digest('hex') !== digest) {
    throw new Error(`PDF runtime asset identity mismatch: ${name}`)
  }
}
const packer = packerArg ?? fileURLToPath(new URL('../../../../docker/package-office-engine.mjs', import.meta.url))
execFileSync(process.execPath, [packer, source, destination], { stdio: 'inherit' })
mkdirSync(join(destination, 'wasm'), { recursive: true })
for (const [name, [path]] of Object.entries(assets)) copyFileSync(join(source, 'node_modules', path), join(destination, 'wasm', name))
writeFileSync(join(destination, 'WASM-SHA256.json'), JSON.stringify(Object.fromEntries(Object.entries(assets).map(([name, [, hash]]) => [name, hash])), null, 2) + '\n')
// HarfBuzz WASM不一定进入JS metafile，仍须附带其许可证和manifest。
for (const dependency of ['harfbuzzjs', '@embedpdf/pdfium']) {
  const root = join(source, 'node_modules', dependency)
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (!entry.isFile() || !/license|notice|copying|copyright|^readme|^package\.json$/i.test(entry.name)) continue
    const output = join(destination, 'licenses/node_modules', dependency, entry.name)
    mkdirSync(dirname(output), { recursive: true })
    copyFileSync(join(root, entry.name), output)
  }
}
