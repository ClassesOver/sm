/// Legacy-comment (note) writer, ported from genoffice xlsx-notes.ts:
/// replaces a worksheet's full comment set — the comments part, the note
/// shapes of the VML drawing Excel needs to show them, the worksheet rels,
/// the `<legacyDrawing>` element, and the [Content_Types].xml entries.
/// Non-note VML shapes (checkboxes, buttons) survive a rewrite untouched.

import { shiftIndex, type ShiftSpec } from './structural'
import { readSheetNotes, noteKey, NOTE_LIMIT, NOTE_TEXT_LIMIT, type LegacyNote } from './note-read'
import { ensureRelationshipNamespace, readXmlAttribute } from './xml'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { assemblePackage, createBufferEntrySource, type EntrySource, type MutationPlan } from './zip'

export class NoteEditError extends Error {}

export interface SheetNote {
  readonly row: number
  readonly column: number
  readonly author: string
  readonly text: string
}

const COMMENTS_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments'
const VML_REL_TYPE =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing'
const COMMENTS_CONTENT_TYPE =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml'
const CONTENT_TYPES_PATH = '[Content_Types].xml'

function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function columnName(index: number): string {
  let label = ''
  for (let i = index; i >= 0; i = Math.floor(i / 26) - 1) {
    label = String.fromCharCode(65 + (i % 26)) + label
  }
  return label
}

function worksheetRelsPath(worksheetPath: string): string {
  return worksheetPath.replace(/^(xl\/worksheets\/)([^/]+)$/, '$1_rels/$2.rels')
}

function relTarget(relsXml: string, type: string): string | null {
  const found = relsXml.match(new RegExp(`<Relationship\\b[^>]*Type="${type}"[^>]*/?>`))
  if (!found) return null
  return found[0].match(/ Target="([^"]*)"/)?.[1] ?? null
}

/// "../comments1.xml" or "/xl/comments1.xml" → package path.
function resolveRelTarget(worksheetPath: string, target: string): string {
  if (target.startsWith('/')) return target.slice(1)
  const base = worksheetPath.split('/').slice(0, -1)
  for (const part of target.split('/')) {
    if (part === '..') base.pop()
    else if (part !== '.') base.push(part)
  }
  return base.join('/')
}

function nextFreeRid(relsXml: string): string {
  const ids = [...relsXml.matchAll(/ Id="rId(\d+)"/g)].map((match) => Number(match[1]))
  return `rId${ids.length === 0 ? 1 : Math.max(...ids) + 1}`
}

function buildCommentsXml(notes: readonly SheetNote[]): string {
  const authors: string[] = []
  const authorId = (author: string): number => {
    const existing = authors.indexOf(author)
    if (existing !== -1) return existing
    authors.push(author)
    return authors.length - 1
  }
  const comments = notes
    .map((note) => {
      const ref = `${columnName(note.column)}${note.row + 1}`
      return (
        `<comment ref="${ref}" authorId="${authorId(note.author)}">` +
        `<text><t xml:space="preserve">${escapeXml(note.text)}</t></text></comment>`
      )
    })
    .join('')
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    `<authors>${authors.map((author) => `<author>${escapeXml(author)}</author>`).join('')}</authors>` +
    `<commentList>${comments}</commentList></comments>`
  )
}

const VML_HEADER =
  '<xml xmlns:v="urn:schemas-microsoft-com:vml"' +
  ' xmlns:o="urn:schemas-microsoft-com:office:office"' +
  ' xmlns:x="urn:schemas-microsoft-com:office:excel">' +
  '<o:shapelayout v:ext="edit"><o:idmap v:ext="edit" data="1"/></o:shapelayout>' +
  '<v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202"' +
  ' path="m,l,21600r21600,l21600,xe">' +
  '<v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/>' +
  '</v:shapetype>'

function noteShape(note: SheetNote, index: number): string {
  // Anchor: from one column right of the cell, spanning ~3 columns / 4 rows.
  const anchor = [note.column + 1, 15, note.row, 2, note.column + 4, 15, note.row + 4, 2].join(',')
  return (
    `<v:shape id="_x0000_s${1025 + index}" type="#_x0000_t202"` +
    ' style="position:absolute;margin-left:80pt;margin-top:2pt;width:108pt;height:60pt;' +
    `z-index:${index + 1};visibility:hidden" fillcolor="#ffffe1" o:insetmode="auto">` +
    '<v:fill color2="#ffffe1"/><v:shadow on="t" color="black" obscured="t"/>' +
    '<v:path o:connecttype="none"/>' +
    '<v:textbox style="mso-direction-alt:auto"><div style="text-align:left"></div></v:textbox>' +
    '<x:ClientData ObjectType="Note"><x:MoveWithCells/><x:SizeWithCells/>' +
    `<x:Anchor>${anchor}</x:Anchor>` +
    '<x:AutoFill>False</x:AutoFill>' +
    `<x:Row>${note.row}</x:Row><x:Column>${note.column}</x:Column></x:ClientData>` +
    '</v:shape>'
  )
}

/// Drops every Note-typed shape, keeping other legacy objects verbatim.
function stripNoteShapes(vmlXml: string): string {
  return vmlXml.replace(/<v:shape\b[\s\S]*?<\/v:shape>/g, (shape) =>
    shape.includes('ObjectType="Note"') ? '' : shape,
  )
}

function ensureContentTypeOverride(contentTypes: string, partName: string): string {
  if (contentTypes.includes(`PartName="/${partName}"`)) return contentTypes
  return contentTypes.replace(
    '</Types>',
    `<Override PartName="/${partName}" ContentType="${COMMENTS_CONTENT_TYPE}"/></Types>`,
  )
}

function ensureVmlDefault(contentTypes: string): string {
  if (/<Default\b[^>]*Extension="vml"/.test(contentTypes)) return contentTypes
  return contentTypes.replace(
    '</Types>',
    '<Default Extension="vml"' +
      ' ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/></Types>',
  )
}

function appendRel(relsXml: string, id: string, type: string, target: string): string {
  return relsXml.replace(
    '</Relationships>',
    `<Relationship Id="${id}" Type="${type}" Target="${target}"/></Relationships>`,
  )
}

function removeRel(relsXml: string, type: string): string {
  return relsXml.replace(new RegExp(`<Relationship\\b[^>]*Type="${type}"[^>]*/?>`), '')
}

const EMPTY_RELS =
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
  '</Relationships>'

/// CT_Worksheet order: legacyDrawing follows drawing and precedes these.
const AFTER_LEGACY_DRAWING =
  /<legacyDrawingHF\b|<picture\b|<oleObjects\b|<controls\b|<webPublishItems\b|<tableParts\b|<extLst\b/

function ensureLegacyDrawingElement(worksheetXml: string, rid: string): string {
  if (/<legacyDrawing\b/.test(worksheetXml)) return worksheetXml
  worksheetXml = ensureRelationshipNamespace(worksheetXml)
  const element = `<legacyDrawing r:id="${rid}"/>`
  const anchor = worksheetXml.match(AFTER_LEGACY_DRAWING)
  if (anchor) {
    const at = anchor.index ?? 0
    return worksheetXml.slice(0, at) + element + worksheetXml.slice(at)
  }
  const end = worksheetXml.lastIndexOf('</worksheet>')
  if (end === -1) throw new NoteEditError('Worksheet has no closing element.')
  return worksheetXml.slice(0, end) + element + worksheetXml.slice(end)
}

interface PlanParts {
  readonly replaced: Map<string, string>
  readonly added: Map<string, string>
  readonly removedEntries: string[]
  readonly touchedEntries: string[]
}

/// Replaces the worksheet's whole comment set (empty list removes it all).
async function rewriteSheetNotes(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
  worksheetPath: string,
  notes: readonly SheetNote[],
): Promise<PlanParts> {
  const replaced = new Map<string, string>()
  const added = new Map<string, string>()
  const removedEntries: string[] = []
  const touchedEntries: string[] = []

  const relsPath = worksheetRelsPath(worksheetPath)
  const hasRels = await source.has(relsPath)
  let relsXml = hasRels ? await source.readText(relsPath) : EMPTY_RELS
  const existingCommentsTarget = relTarget(relsXml, COMMENTS_REL_TYPE)
  const existingCommentsPath =
    existingCommentsTarget === null
      ? null
      : resolveRelTarget(worksheetPath, existingCommentsTarget)
  const existingVmlTarget = relTarget(relsXml, VML_REL_TYPE)
  const existingVmlPath =
    existingVmlTarget === null ? null : resolveRelTarget(worksheetPath, existingVmlTarget)
  let relsChanged = false

  if (notes.length === 0) {
    if (existingCommentsPath === null) return { replaced, added, removedEntries, touchedEntries }
    removedEntries.push(existingCommentsPath)
    touchedEntries.push(existingCommentsPath)
    relsXml = removeRel(relsXml, COMMENTS_REL_TYPE)
    const contentTypes = await source.readText(CONTENT_TYPES_PATH)
    const stripped = contentTypes.replace(
      new RegExp(`<Override\\b[^>]*PartName="/${existingCommentsPath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"[^>]*/>`),
      '',
    )
    if (stripped !== contentTypes) {
      replaced.set(CONTENT_TYPES_PATH, stripped)
      touchedEntries.push(CONTENT_TYPES_PATH)
    }
    if (existingVmlPath !== null && (await source.has(existingVmlPath))) {
      const remaining = stripNoteShapes(await source.readText(existingVmlPath))
      if (/<v:shape\b/.test(remaining)) {
        replaced.set(existingVmlPath, remaining)
      } else {
        removedEntries.push(existingVmlPath)
        relsXml = removeRel(relsXml, VML_REL_TYPE)
        const worksheetXml = await source.readText(worksheetPath)
        const withoutLegacy = worksheetXml.replace(/<legacyDrawing\b[^>]*\/>/, '')
        if (withoutLegacy !== worksheetXml) {
          replaced.set(worksheetPath, withoutLegacy)
          touchedEntries.push(worksheetPath)
        }
      }
      touchedEntries.push(existingVmlPath)
    }
    if (hasRels) replaced.set(relsPath, relsXml)
    else added.set(relsPath, relsXml)
    touchedEntries.push(relsPath)
    return { replaced, added, removedEntries, touchedEntries }
  }

  // Comments part: rewrite in place, or allocate a fresh one.
  let commentsPath = existingCommentsPath
  if (commentsPath === null) {
    let index = 1
    while (await source.has(`xl/comments${index}.xml`)) index += 1
    commentsPath = `xl/comments${index}.xml`
    const rid = nextFreeRid(relsXml)
    const target = `../${commentsPath.replace(/^xl\//, '')}`
    relsXml = appendRel(relsXml, rid, COMMENTS_REL_TYPE, target)
    relsChanged = true
    added.set(commentsPath, buildCommentsXml(notes))
  } else {
    replaced.set(commentsPath, buildCommentsXml(notes))
  }
  touchedEntries.push(commentsPath)

  // VML part: keep foreign shapes, replace the note shapes.
  const shapes = notes.map((note, index) => noteShape(note, index)).join('')
  if (existingVmlPath !== null && (await source.has(existingVmlPath))) {
    const vml = stripNoteShapes(await source.readText(existingVmlPath))
    const end = vml.lastIndexOf('</xml>')
    if (end === -1) throw new NoteEditError(`${existingVmlPath} is not a VML drawing.`)
    replaced.set(existingVmlPath, vml.slice(0, end) + shapes + vml.slice(end))
    touchedEntries.push(existingVmlPath)
  } else {
    let index = 1
    while (await source.has(`xl/drawings/vmlDrawing${index}.vml`)) index += 1
    const vmlPath = `xl/drawings/vmlDrawing${index}.vml`
    const rid = nextFreeRid(relsXml)
    relsXml = appendRel(relsXml, rid, VML_REL_TYPE, `../drawings/${vmlPath.split('/').pop()}`)
    relsChanged = true
    added.set(vmlPath, `${VML_HEADER}${shapes}</xml>`)
    touchedEntries.push(vmlPath)
    const worksheetXml = await source.readText(worksheetPath)
    const withLegacy = ensureLegacyDrawingElement(worksheetXml, rid)
    if (withLegacy !== worksheetXml) {
      replaced.set(worksheetPath, withLegacy)
      touchedEntries.push(worksheetPath)
    }
  }

  const contentTypes = await source.readText(CONTENT_TYPES_PATH)
  const updatedTypes = ensureVmlDefault(ensureContentTypeOverride(contentTypes, commentsPath))
  if (updatedTypes !== contentTypes) {
    replaced.set(CONTENT_TYPES_PATH, updatedTypes)
    touchedEntries.push(CONTENT_TYPES_PATH)
  }

  if (relsChanged) {
    if (hasRels) replaced.set(relsPath, relsXml)
    else added.set(relsPath, relsXml)
    touchedEntries.push(relsPath)
  }
  return { replaced, added, removedEntries, touchedEntries }
}

/// Entry: replace one sheet's full comment set by sheet name.
export async function applySheetNotes(
  sourceBytes: Uint8Array,
  sheetName: string,
  notes: readonly SheetNote[],
): Promise<Uint8Array> {
  const source = await createBufferEntrySource(sourceBytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const element = parseSheetElements(workbookXml).find((entry) => entry.name === sheetName)
  if (!element?.relationshipId) {
    throw new Error(`工作表 "${sheetName}" 不存在。`)
  }
  const worksheetPath = await resolveWorksheetPath(source, element.relationshipId)
  const parts = await rewriteSheetNotes(source, worksheetPath, notes)
  const plan: MutationPlan = {
    replaced: parts.replaced,
    added: parts.added,
    addedBinary: new Map(),
    removedEntries: parts.removedEntries,
    addedEntries: [...parts.added.keys()],
    touchedEntries: parts.touchedEntries,
  }
  return (await assemblePackage(sourceBytes, plan)).buffer
}

export interface NoteShiftPlan {
  readonly replaced: Map<string, string>
  readonly removedEntries: string[]
  readonly touchedEntries: string[]
}

function shiftedAnchorMark(position: number, offset: number, spec: ShiftSpec): [number, number] {
  const shifted = shiftIndex(position, spec)
  if (shifted !== null) return [shifted, offset]
  return [spec.start, 0]
}

function shiftNoteShape(shape: string, row: number, column: number, specs: readonly ShiftSpec[]): string {
  const rowTag = '(?:[\\w.-]+:)?Row'
  const columnTag = '(?:[\\w.-]+:)?Column'
  const anchorTag = '(?:[\\w.-]+:)?Anchor'
  let next = shape
    .replace(new RegExp(`(<${rowTag}\\b[^>]*>)[^<]*(</${rowTag}>)`), (full, open: string, close: string) => `${open}${row}${close}`)
    .replace(new RegExp(`(<${columnTag}\\b[^>]*>)[^<]*(</${columnTag}>)`), (full, open: string, close: string) => `${open}${column}${close}`)
  next = next.replace(new RegExp(`(<${anchorTag}\\b[^>]*>)([^<]*)(</${anchorTag}>)`), (_full, open: string, body: string, close: string) => {
    const values = body.split(',').map((part) => Number(part.trim()))
    if (values.length !== 8 || values.some((value) => !Number.isFinite(value))) return _full
    const shifted = [...values]
    for (const spec of specs) {
      const start = spec.axis === 'row' ? 2 : 0
      const end = start + 4
      ;[shifted[start], shifted[start + 1]] = shiftedAnchorMark(shifted[start]!, shifted[start + 1]!, spec)
      ;[shifted[end], shifted[end + 1]] = shiftedAnchorMark(shifted[end]!, shifted[end + 1]!, spec)
    }
    return `${open}${shifted.join(',')}${close}`
  })
  return next
}

/** Shift legacy comment refs and only their Note VML shapes with worksheet structure. */
export async function shiftSheetNotes(
  source: EntrySource,
  worksheetPath: string,
  specs: readonly ShiftSpec[],
  worksheetXmlOverride?: string,
): Promise<NoteShiftPlan> {
  const empty: NoteShiftPlan = { replaced: new Map(), removedEntries: [], touchedEntries: [] }
  if (specs.length === 0) return empty
  // VML-only form controls and unrelated protected sheets retain the old structural path.
  const relationshipsPath = worksheetRelsPath(worksheetPath)
  const relationships = await source.has(relationshipsPath) ? await source.readText(relationshipsPath) : ''
  const ownsComments = [...relationships.matchAll(/<Relationship\b[^>]*\/?\s*>/g)].some(match => {
    const type = readXmlAttribute(match[0], 'Type') ?? ''
    return type === COMMENTS_REL_TYPE || /threadedcomments|\/persons?$/i.test(type)
  })
  if (!ownsComments) return empty
  const model = await readSheetNotes(source, worksheetPath)
  if (model.readOnlyReason) throw new NoteEditError(model.readOnlyReason)
  if (!model.commentsPath || !model.vmlPath || !model.commentsXml || !model.vmlXml) return empty
  const moved = new Map<string, LegacyNote>()
  const destinations = new Set<string>()
  for (const note of model.notes) {
    let row = note.row
    let column = note.column
    let removed = false
    for (const spec of specs) {
      const shifted = spec.axis === 'row' ? shiftIndex(row, spec) : shiftIndex(column, spec)
      if (shifted === null) { removed = true; break }
      if (shifted < 0 || shifted > (spec.axis === 'row' ? 1048575 : 16383)) throw new NoteEditError('批注移位超出工作表边界')
      if (spec.axis === 'row') row = shifted
      else column = shifted
    }
    const oldKey = noteKey(note.row, note.column)
    if (removed) continue
    const newKey = noteKey(row, column)
    if (destinations.has(newKey)) throw new NoteEditError('结构变更导致批注目标冲突')
    destinations.add(newKey)
    moved.set(oldKey, { ...note, row, column })
  }
  const commentReplacements = new Map<string, string>()
  const shapeReplacements = new Map<string, string>()
  for (const note of model.notes) {
    const oldKey = noteKey(note.row, note.column)
    const next = moved.get(oldKey)
    const raw = model.commentXml.get(oldKey)!
    const shape = model.shapeXml.get(oldKey)!
    commentReplacements.set(raw, next ? raw.replace(/(\bref=")[^"]*(")/, (_full, open: string, close: string) => `${open}${columnName(next.column)}${next.row + 1}${close}`) : '')
    shapeReplacements.set(shape, next ? shiftNoteShape(shape, next.row, next.column, specs) : '')
  }
  // One pass over original elements prevents cascading A1→A2→A3 replacements.
  const comments = model.commentsXml.replace(/<comment\b[^>]*>[\s\S]*?<\/comment>/g, raw => commentReplacements.get(raw) ?? raw)
  const drawing = model.vmlXml.replace(/<(?:[\w.-]+:)?shape\b[^>]*>[\s\S]*?<\/(?:[\w.-]+:)?shape>/g, raw => shapeReplacements.get(raw) ?? raw)
  const replaced = new Map<string, string>()
  const removedEntries: string[] = []
  const touchedEntries: string[] = []
  if (moved.size === 0) {
    removedEntries.push(model.commentsPath)
    const hasForeignShapes = /<(?:[\w.-]+:)?shape\b/.test(drawing)
    if (hasForeignShapes) replaced.set(model.vmlPath, drawing)
    else {
      removedEntries.push(model.vmlPath)
      const relsPath = worksheetRelsPath(worksheetPath)
      const rels = await source.readText(relsPath)
      replaced.set(relsPath, removeRel(rels, VML_REL_TYPE))
      touchedEntries.push(relsPath)
      const worksheetXml = worksheetXmlOverride ?? await source.readText(worksheetPath)
      replaced.set(worksheetPath, worksheetXml.replace(/<legacyDrawing\b[^>]*\/>/, ''))
      touchedEntries.push(worksheetPath)
    }
    const relsPath = worksheetRelsPath(worksheetPath)
    const rels = replaced.get(relsPath) ?? await source.readText(relsPath)
    replaced.set(relsPath, removeRel(rels, COMMENTS_REL_TYPE))
    touchedEntries.push(relsPath)
    const contentTypes = await source.readText(CONTENT_TYPES_PATH)
    const deletedPaths = new Set(removedEntries.map(entry => `/${entry}`))
    const cleaned = contentTypes.replace(/<Override\b[^>]*\/>/g, entry => deletedPaths.has(readXmlAttribute(entry, 'PartName') ?? '') ? '' : entry)
    if (cleaned !== contentTypes) replaced.set(CONTENT_TYPES_PATH, cleaned)
  } else {
    replaced.set(model.commentsPath, comments)
    replaced.set(model.vmlPath, drawing)
    touchedEntries.push(model.commentsPath, model.vmlPath)
  }
  return { replaced, removedEntries, touchedEntries: [...new Set([...touchedEntries, ...replaced.keys(), ...removedEntries])] }
}

/** Move keeps the source note's author and text; the engine resolves the
 *  author from the source itself, so clients never supply identity. */
export interface NoteMoveChange { fromRow: number; fromColumn: number; toRow: number; toColumn: number }
export type NotePatchChange = { row: number; column: number; text: string | null } | NoteMoveChange

const isMoveChange = (change: NotePatchChange): change is NoteMoveChange =>
  (change as NoteMoveChange).fromRow !== undefined

const inCellRange = (row: number, column: number) =>
  Number.isInteger(row) && row >= 0 && row <= 1048575 && Number.isInteger(column) && column >= 0 && column <= 16383

/** Single-cell patches retain all untouched comment elements and original VML shapes. */
export async function patchSheetNotes(sourceBytes: Uint8Array, sheetName: string, sourceIdentity: string,
  changes: readonly NotePatchChange[]): Promise<Uint8Array> {
  if (!/^[a-f0-9]{64}$/.test(sourceIdentity) || !Array.isArray(changes) || changes.length > NOTE_LIMIT) throw new NoteEditError('批注请求身份或预算无效')
  const source = await createBufferEntrySource(sourceBytes)
  const element = parseSheetElements(await source.readText('xl/workbook.xml')).find(s => s.name === sheetName)
  if (!element?.relationshipId) throw new NoteEditError('批注来源工作表不存在')
  const path = await resolveWorksheetPath(source, element.relationshipId)
  const original = await readSheetNotes(source, path)
  if (original.readOnlyReason) throw new NoteEditError(original.readOnlyReason)
  if (original.sourceIdentity !== sourceIdentity) throw new NoteEditError('批注来源身份已变化，请刷新后重试')
  const plainKeys = new Set<string>()
  const moveFroms = new Set<string>()
  const moveTargets = new Set<string>()
  const notes = new Map(original.notes.map(n => [noteKey(n.row, n.column), n]))
  const moves: { change: NoteMoveChange; moving: { row: number; column: number; author: string; text: string } }[] = []
  const edits: { key: string; change: { row: number; column: number; text: string | null } }[] = []
  for (const change of changes) {
    if (isMoveChange(change)) {
      if (!inCellRange(change.fromRow, change.fromColumn) || !inCellRange(change.toRow, change.toColumn)) throw new NoteEditError('批注移动地址超出范围')
      const fromKey = noteKey(change.fromRow, change.fromColumn), toKey = noteKey(change.toRow, change.toColumn)
      // Cyclic permutations make one key both a target and another move's
      // source, so from/to keys may overlap across moves; only duplicate
      // froms, duplicate targets and plain-change collisions collide.
      if (fromKey === toKey || moveFroms.has(fromKey) || moveTargets.has(toKey) || plainKeys.has(fromKey) || plainKeys.has(toKey)) throw new NoteEditError('批注目标重复')
      const moving = notes.get(fromKey)
      if (!moving) throw new NoteEditError('批注移动来源不存在')
      moveFroms.add(fromKey)
      moveTargets.add(toKey)
      moves.push({ change, moving })
      continue
    }
    if (!inCellRange(change.row, change.column) ||
      change.text !== null && (typeof change.text !== 'string' || change.text.length > NOTE_TEXT_LIMIT || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(change.text))) throw new NoteEditError('批注文本或地址超出预算')
    const key = noteKey(change.row, change.column)
    if (plainKeys.has(key) || moveFroms.has(key) || moveTargets.has(key)) throw new NoteEditError('批注目标重复')
    plainKeys.add(key)
    edits.push({ key, change })
  }
  // Order-independent application: frees first, then move targets, then text edits.
  for (const change of changes) {
    const key = isMoveChange(change) ? noteKey(change.fromRow, change.fromColumn) : change.text === null ? noteKey(change.row, change.column) : null
    if (key) notes.delete(key)
  }
  for (const { change, moving } of moves) notes.set(noteKey(change.toRow, change.toColumn), { ...moving, row: change.toRow, column: change.toColumn })
  for (const { key, change } of edits) {
    if (change.text === null) continue
    notes.set(key, { row: change.row, column: change.column, author: notes.get(key)?.author ?? '用户', text: change.text })
  }
  if (notes.size > NOTE_LIMIT || [...notes.values()].reduce((sum, n) => sum + n.text.length, 0) > 1024 * 1024) throw new NoteEditError('批注集合超出预算')
  if (!changes.length) return sourceBytes
  if (!original.commentsPath) return applySheetNotes(sourceBytes, sheetName, [...notes.values()])
  const replaced = new Map<string, string>(), removedEntries: string[] = []
  const relsPath = worksheetRelsPath(path)
  let comments = original.commentsXml!, drawing = original.vmlXml!
  if (!notes.size) {
    removedEntries.push(original.commentsPath)
    for (const shape of original.shapeXml.values()) drawing = drawing.replace(shape, () => '')
    const keepVml = /<(?:[\w.-]+:)?shape\b/.test(drawing)
    if (keepVml) replaced.set(original.vmlPath!, drawing)
    else {
      removedEntries.push(original.vmlPath!)
      replaced.set(path, (await source.readText(path)).replace(/<legacyDrawing\b[^>]*\/>/, ''))
    }
    let rels = await source.readText(relsPath)
    rels = rels.replace(/<Relationship\b[^>]*\/>/g, relationship => {
      const type = readXmlAttribute(relationship, 'Type')
      return type === COMMENTS_REL_TYPE || !keepVml && type === VML_REL_TYPE ? '' : relationship
    })
    replaced.set(relsPath, rels)
    const contentTypes = await source.readText(CONTENT_TYPES_PATH)
    const deletedPaths = new Set(removedEntries.map(entry => `/${entry}`))
    const cleanedTypes = contentTypes.replace(/<Override\b[^>]*\/>/g, entry => deletedPaths.has(readXmlAttribute(entry, 'PartName') ?? '') ? '' : entry)
    if (cleanedTypes !== contentTypes) replaced.set(CONTENT_TYPES_PATH, cleanedTypes)
  } else {
    const removals = new Set<string>()
    const creations: { key: string; text: string; author: string }[] = []
    for (const change of changes) {
      if (isMoveChange(change)) {
        const fromKey = noteKey(change.fromRow, change.fromColumn), toKey = noteKey(change.toRow, change.toColumn)
        removals.add(fromKey)
        creations.push({ key: toKey, text: notes.get(toKey)!.text, author: original.notes.find(n => noteKey(n.row, n.column) === fromKey)!.author })
        continue
      }
      const key = noteKey(change.row, change.column)
      if (change.text === null) removals.add(key)
      else if (original.commentXml.has(key)) {
        const raw = original.commentXml.get(key)!
        comments = comments.replace(raw, () => raw.replace(/<text>[\s\S]*?<\/text>/, () => `<text><t xml:space="preserve">${escapeXml(change.text).replace(/\r/g, '&#13;')}</t></text>`))
      } else creations.push({ key, text: change.text, author: '用户' })
    }
    for (const key of removals) {
      const raw = original.commentXml.get(key), shape = original.shapeXml.get(key)
      if (raw) comments = comments.replace(raw, () => '')
      if (shape) drawing = drawing.replace(shape, () => '')
    }
    for (const creation of creations) {
      const [row, column] = creation.key.split(':').map(Number) as [number, number]
      let authorId = original.authors.indexOf(creation.author)
      if (authorId < 0) {
        authorId = original.authors.length; original.authors.push(creation.author)
        comments = comments.replace('</authors>', `<author>${escapeXml(creation.author)}</author></authors>`)
      }
      const comment = `<comment ref="${columnName(column)}${row + 1}" authorId="${authorId}"><text><t xml:space="preserve">${escapeXml(creation.text).replace(/\r/g, '&#13;')}</t></text></comment>`
      comments = comments.replace('</commentList>', () => comment + '</commentList>')
      let index = 0
      while (drawing.includes(`_x0000_s${1025 + index}`)) index++
      // Source VML producers use ns0/ns1 prefixes. Bind the writer's prefixes locally.
      let nextShape = noteShape(notes.get(creation.key)!, index).replace('<v:shape ', '<v:shape xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" ')
      const type = drawing.match(/<(?:[\w.-]+:)?shapetype\b[^>]*\bid="([^"]+)"/)?.[1]
      if (!type) throw new NoteEditError('VML 批注图形类型缺失')
      nextShape = nextShape.replace('type="#_x0000_t202"', () => `type="#${type}"`)
      drawing = drawing.replace(/(<\/(?:[\w.-]+:)?xml>\s*)$/, (_match, end: string) => nextShape + end)
    }
    replaced.set(original.commentsPath, comments)
    replaced.set(original.vmlPath!, drawing)
  }
  return (await assemblePackage(sourceBytes, { replaced, added: new Map(), addedBinary: new Map(), removedEntries,
    addedEntries: [], touchedEntries: [...replaced.keys(), ...removedEntries] })).buffer
}
