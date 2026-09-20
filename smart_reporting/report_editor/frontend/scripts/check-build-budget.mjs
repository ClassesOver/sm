import { readdir, stat } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative } from 'node:path'

const KIB = 1024
const limits = {
  entry: 180 * KIB,
  milkdown: 700 * KIB,
  plotly: 5 * 1024 * KIB,
  other: 250 * KIB,
}

function limitFor(file) {
  const name = file.split('/').at(-1) ?? file
  if (name.startsWith('milkdown-')) return limits.milkdown
  if (name.startsWith('plotly.min-')) return limits.plotly
  if (name.startsWith('index-')) return limits.entry
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
