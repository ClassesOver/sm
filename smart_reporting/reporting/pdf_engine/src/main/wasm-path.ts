import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Runtime wasm assets live in node_modules during dev/tests but the packaged app
 * ships no node_modules (everything is bundled) — electron-builder copies them
 * into Resources/wasm instead (see apps/shell/electron-builder.cjs extraResources).
 */
const packagedPath = (fileName: string) => {
  const bundled = fileURLToPath(new URL(`../wasm/${fileName}`, import.meta.url))
  if (existsSync(bundled)) return bundled
  if (typeof process.resourcesPath !== 'string') {
    throw new Error('PDF WASM 资源缺失，请配置 AGENT_REPORTING_PDF_WASM_DIR')
  }
  return join(process.resourcesPath, 'wasm', fileName)
}

function configuredPath(fileName: string): string | undefined {
  const directory = process.env.AGENT_REPORTING_PDF_WASM_DIR
  if (!directory) return undefined
  const path = join(directory, fileName)
  if (!existsSync(path)) throw new Error(`PDF WASM 资源不存在：${fileName}`)
  return path
}

const req = () => createRequire(import.meta.url)

export function pdfiumWasmPath(): string {
  const configured = configuredPath('pdfium.wasm')
  if (configured) return configured
  try {
    return req().resolve('@embedpdf/pdfium/pdfium.wasm')
  } catch {
    return packagedPath('pdfium.wasm')
  }
}

export function hbSubsetWasmPath(): string {
  const configured = configuredPath('hb-subset.wasm')
  if (configured) return configured
  const r = req()
  try {
    // harfbuzzjs ≤0.10 ships hb-subset.wasm at the package root with no exports map
    return r.resolve('harfbuzzjs/hb-subset.wasm')
  } catch {
    /* fall through */
  }
  try {
    // harfbuzzjs ≥1.x seals subpaths; the wasm sits next to the exported entry point
    const p = join(dirname(r.resolve('harfbuzzjs')), 'harfbuzz-subset.wasm')
    if (existsSync(p)) return p
  } catch {
    /* fall through */
  }
  return packagedPath('hb-subset.wasm')
}
