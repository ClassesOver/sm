/// Legacy-comment (note) writer, ported from genoffice xlsx-notes.ts:
/// replaces a worksheet's full comment set — the comments part, the note
/// shapes of the VML drawing Excel needs to show them, the worksheet rels,
/// the `<legacyDrawing>` element, and the [Content_Types].xml entries.
/// Non-note VML shapes (checkboxes, buttons) survive a rewrite untouched.

import { ensureRelationshipNamespace } from './xml'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { assemblePackage, createBufferEntrySource, type MutationPlan } from './zip'

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
