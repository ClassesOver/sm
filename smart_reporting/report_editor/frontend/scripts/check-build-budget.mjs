import { readdir, stat } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative } from 'node:path'

const KIB = 1024
const limits = {
  entry: 180 * KIB,
  milkdown: 700 * KIB,
  other: 250 * KIB,
}

// Workbook-only lazy chunks retain the pinned engine's native package
// boundaries. Formula evaluation, canvas rendering and grid commands have
// separate bounded budgets; document entry and ordinary chunks keep theirs.
const workbookLimits = {
  // 272 KiB (2026-11-07): the official sheets-filter preset's UI icons joined
  // the shared icon chunk when native filtering was wired into the ribbon.
  'workbook-icons': 274 * KIB,
  'workbook-engine': 390 * KIB,
  'workbook-core': 400 * KIB,
  'workbook-sheets': 430 * KIB,
  'workbook-docs-ui': 470 * KIB,
  'workbook-sheets-formula': 710 * KIB,
  'workbook-engine-formula': 760 * KIB,
  'workbook-sheets-ui': 910 * KIB,
  'workbook-engine-render': 650 * KIB,
}

// 原生编辑按固定引擎边界懒加载；正文入口与普通模块仍保持原预算。
const nativeLimits = {
  'native-docx-engine': 420 * KIB,
  // 710 KiB (2026-11-08): the vendored GenOffice cover-page gallery
  // (editor/cover-pages.ts presets) joined the Word render chunk with Insert ▸
  // Cover Page; it is needed synchronously by the native save guard.
  'native-docx-render': 710 * KIB,
  'native-pdfjs': 500 * KIB,
  'native-tiptap': 370 * KIB,
  'parse-worker': 700 * KIB,
}

function limitFor(file) {
  const filename = file.split('/').at(-1) ?? file
  const lazy = filename.startsWith('lazy-')
  const name = filename.replace(/^lazy-/, '')
  if (name.startsWith('workbook-dictionary-')) return 780 * KIB
  const workbookPackage = name.replace(/-[A-Za-z0-9_-]{8}\.js$/, '')
  if (workbookPackage in nativeLimits) return nativeLimits[workbookPackage]
  if (workbookPackage in workbookLimits) return workbookLimits[workbookPackage]
  if (name.startsWith('milkdown-prosemirror-')) return 270 * KIB
  if (name.startsWith('milkdown-')) return limits.milkdown
  if (!lazy && name.startsWith('index-')) return limits.entry
  return limits.other
}

export function checkBuildBudget(chunks) {
  return chunks.flatMap(({ file, size }) => {
    const limit = limitFor(file)
    return size > limit
      ? [`${file}: ${(size / KIB).toFixed(1)} KiB exceeds ${(limit / KIB).toFixed(0)} KiB`]
      : []
  })
}

async function javascriptChunks(directory) {
  const chunks = []
  for (const name of await readdir(directory)) {
    const path = join(directory, name)
    const info = await stat(path)
    if (info.isFile() && name.endsWith('.js')) {
      chunks.push({ file: relative(dirname(directory), path), size: info.size })
    }
  }
  return chunks
}

const invoked = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]
if (invoked) {
  const assets = fileURLToPath(new URL('../../static/assets/', import.meta.url))
  const chunks = await javascriptChunks(assets)
  const failures = checkBuildBudget(chunks)
  for (const chunk of chunks.sort((left, right) => right.size - left.size)) {
    console.log(`${chunk.file}: ${(chunk.size / KIB).toFixed(1)} KiB`)
  }
  if (failures.length) {
    console.error(`Build budget exceeded:\n${failures.join('\n')}`)
    process.exitCode = 1
  }
}
