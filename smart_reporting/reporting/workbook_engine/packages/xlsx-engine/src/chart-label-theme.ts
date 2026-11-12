import {SaxesParser} from 'saxes'
import type {EntrySource} from './zip'
import {parseThemePalette} from './style-read'

// Follow the actual relationship: a conventional filename may be stale.
// Missing, external or ambiguous themes leave scheme labels unsupported.
export async function chartThemePalette(source: EntrySource): Promise<string[] | undefined> {
  try {
    const path = 'xl/_rels/workbook.xml.rels'
    if (!await source.has(path)) return undefined
    const parser = new SaxesParser({xmlns:true}), themes: {target:string; mode:string}[] = []
    const ids = new Set<string>()
    let depth = 0, invalid = false
    parser.on('opentag', node => {
      depth++
      if (depth !== 2 || node.local !== 'Relationship' || node.uri !== 'http://schemas.openxmlformats.org/package/2006/relationships') return
      const attr = (name:string) => Object.values(node.attributes).find(value => value.local === name && !value.uri)?.value ?? ''
      const id = attr('Id')
      if (!id || ids.has(id)) invalid = true
      ids.add(id)
      if (/^(?:http:\/\/schemas.openxmlformats.org\/officeDocument\/2006|http:\/\/purl.oclc.org\/ooxml\/officeDocument)\/relationships\/theme$/.test(attr('Type'))) themes.push({target:attr('Target'),mode:attr('TargetMode')})
    })
    parser.on('closetag', () => {depth--})
    parser.write(await source.readText(path)).close()
    if (invalid || themes.length !== 1) return undefined
    const theme = themes[0]!
    if (!theme.target || theme.mode && theme.mode !== 'Internal') return undefined
    const url = new URL(theme.target, 'http://pkg/xl/')
    if (url.origin !== 'http://pkg' || url.search || url.hash) return undefined
    const target = url.pathname.slice(1)
    if (!await source.has(target)) return undefined
    const xml = await source.readText(target)
    new SaxesParser({xmlns:true}).write(xml).close()
    return parseThemePalette(xml, {requireComplete:true})
  } catch {
    return undefined
  }
}
