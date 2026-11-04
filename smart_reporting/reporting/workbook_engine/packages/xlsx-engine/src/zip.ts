/// ZIP/package layer: safe load with limits, entry source, inventory, and
/// in-memory JSZip assembly. Browser-safe: Uint8Array I/O, no node: imports.

import JSZip from 'jszip'

import { sha256Hex } from './sha256'
import { normalizeOoxmlPartPrefix } from './xml'

export const XLSX_ZIP_LIMITS = { maxParts: 10_000, maxTotalBytes: 256 * 1024 * 1024 } as const

const MAX_ENTRY_COUNT = XLSX_ZIP_LIMITS.maxParts
const MAX_UNCOMPRESSED_BYTES = XLSX_ZIP_LIMITS.maxTotalBytes

export interface PackageEntry {
  path: string
  size: number
  sha256: string
}

export interface XlsxMutation {
  readonly buffer: Uint8Array
  readonly touchedEntries: readonly string[]
  readonly removedEntries: readonly string[]
  readonly addedEntries: readonly string[]
  readonly beforeEntries: readonly PackageEntry[]
  readonly afterEntries: readonly PackageEntry[]
}

/// Read access to the entries of a source package.
export interface EntrySource {
  paths(): Promise<readonly string[]>
  has(path: string): Promise<boolean>
  readText(path: string): Promise<string>
}

/// The entry-level outcome of patch planning: what the assembler must
/// replace, add, and drop.
export interface MutationPlan {
  readonly replaced: ReadonlyMap<string, string>
  readonly added: ReadonlyMap<string, string>
  /// Non-text entries (media bytes); disjoint from `added`.
  readonly addedBinary: ReadonlyMap<string, Uint8Array>
  readonly removedEntries: readonly string[]
  readonly addedEntries: readonly string[]
  readonly touchedEntries: readonly string[]
}

/// Package-relative form of a ZIP entry name, null when it escapes the root.
/// '\' separators, a leading '/' and empty segments are producer quirks Excel
/// tolerates; folding them keeps lookups and the saved package on conformant
/// names.
function canonicalEntryName(raw: string): string | null {
  if (raw.includes('\0')) return null
  const segments: string[] = []
  for (const segment of raw.split(/[/\\]/)) {
    if (segment === '' || segment === '.') continue
    if (segment === '..') {
      if (segments.pop() === undefined) return null
      continue
    }
    segments.push(segment)
  }
  if (segments.length === 0) return null
  return segments.join('/')
}

async function loadSafeZip(bytes: Uint8Array): Promise<JSZip> {
  const zip = await JSZip.loadAsync(bytes, { checkCRC32: true })
  const paths = Object.keys(zip.files)
  if (paths.length > MAX_ENTRY_COUNT) throw new Error('工作簿包含的 ZIP 条目过多。')
  // Snapshot first: removing a folder entry such as "/" drops its children too.
  const files = paths.map((path) => [path, zip.files[path]] as const)
  for (const [path, file] of files) {
    // folder entries are left alone: zip.remove on a folder ("xl/") drops
    // every child with it, and folders carry no content to canonicalize —
    // file lookups skip them and children fold individually
    if (file?.dir) continue
    const canonical = canonicalEntryName(path)
    if (canonical === null) throw new Error('工作簿包含不安全的 ZIP 路径。')
    if (canonical === path) continue
    zip.remove(path)
    if (file && canonical && !zip.files[canonical]) {
      zip.file(canonical, await file.async('uint8array'), { createFolders: false, date: file.date })
    }
  }
  return zip
}

export async function createBufferEntrySource(bytes: Uint8Array): Promise<EntrySource> {
  const zip = await loadSafeZip(bytes)
  return {
    paths: async () =>
      Object.entries(zip.files)
        .filter(([, file]) => !file.dir)
        .map(([path]) => path),
    has: async (path) => zip.file(path) !== null,
    readText: async (path) => {
      const entry = zip.file(path)
      if (!entry) throw new Error(`工作簿缺少 ${path}。`)
      const text = await entry.async('text')
      if (/\.xml$|\.rels$/i.test(path) && /<!\s*(?:DOCTYPE|ENTITY)\b/i.test(text)) {
        throw new Error(`${path} 包含不受支持的 DOCTYPE 或 ENTITY 声明。`)
      }
      return normalizeOoxmlPartPrefix(text)
    },
  }
}

export async function inventoryXlsx(bytes: Uint8Array): Promise<readonly PackageEntry[]> {
  const zip = await loadSafeZip(bytes)
  const entries: PackageEntry[] = []
  let totalSize = 0
  for (const [path, file] of Object.entries(zip.files)) {
    if (file.dir) continue
    const data = await file.async('uint8array')
    totalSize += data.length
    if (totalSize > MAX_UNCOMPRESSED_BYTES) {
      throw new Error('工作簿超出解压大小上限。')
    }
    entries.push({ path, size: data.length, sha256: sha256Hex(data) })
  }
  return entries.sort((left, right) => left.path.localeCompare(right.path))
}

/// In-memory assembler: applies a plan onto the source bytes with JSZip.
/// Every entry is recompressed, so it stays subject to the whole-package
/// decompression limit — the streaming assembler was the desktop large-file
/// path; the web app gates file size before reaching here.
export async function assemblePackage(
  source: Uint8Array,
  plan: MutationPlan,
): Promise<XlsxMutation> {
  const zip = await loadSafeZip(source)
  const beforeEntries = await inventoryXlsx(source)
  for (const path of plan.removedEntries) zip.remove(path)
  for (const [path, content] of plan.replaced) zip.file(path, content, { createFolders: false })
  for (const [path, content] of plan.added) zip.file(path, content, { createFolders: false })
  for (const [path, bytes] of plan.addedBinary) zip.file(path, bytes, { createFolders: false })
  const buffer = await zip.generateAsync({
    type: 'uint8array',
    compression: 'DEFLATE',
    compressionOptions: { level: 6 },
  })
  return {
    buffer,
    touchedEntries: plan.touchedEntries,
    removedEntries: plan.removedEntries,
    addedEntries: plan.addedEntries,
    beforeEntries,
    afterEntries: await inventoryXlsx(buffer),
  }
}

export function assertOnlyTouchedEntriesChanged(mutation: XlsxMutation): void {
  const touched = new Set(mutation.touchedEntries)
  const removed = new Set(mutation.removedEntries)
  const added = new Set(mutation.addedEntries)
  const before = new Set(mutation.beforeEntries.map((entry) => entry.path))
  const after = new Map(mutation.afterEntries.map((entry) => [entry.path, entry.sha256]))
  if (mutation.beforeEntries.length !== mutation.afterEntries.length + removed.size - added.size) {
    throw new Error('保存会改变工作簿包结构，已中止。')
  }
  for (const entry of mutation.beforeEntries) {
    const afterHash = after.get(entry.path)
    if (afterHash === undefined) {
      if (removed.has(entry.path)) continue
      throw new Error(`保存会丢失 ${entry.path}，已中止。`)
    }
    if (removed.has(entry.path)) {
      throw new Error(`Saving should have removed ${entry.path} but did not — aborted.`)
    }
    if (!touched.has(entry.path) && afterHash !== entry.sha256) {
      throw new Error(`Saving would unexpectedly modify ${entry.path} — aborted.`)
    }
  }
  for (const path of added) {
    if (before.has(path)) {
      throw new Error(`Saving should have created ${path} but it already existed — aborted.`)
    }
    if (!after.has(path)) {
      throw new Error(`Saving should have created ${path} but did not — aborted.`)
    }
  }
  for (const entry of mutation.afterEntries) {
    if (!before.has(entry.path) && !added.has(entry.path)) {
      throw new Error(`Saving would unexpectedly create ${entry.path} — aborted.`)
    }
  }
}
